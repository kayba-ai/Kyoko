from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .operator_prompts import (
    BEGIN_ISSUES_BLOCK,
    BEGIN_PROPOSAL_BLOCK,
    END_ISSUES_BLOCK,
    END_PROPOSAL_BLOCK,
    write_diagnosis_prompt_artifacts,
    write_proposal_prompt_artifacts,
)
from .issues import (
    IssueError,
    get_issue,
    link_proposal_to_issue,
    merge_observation,
    surface_issue,
    update_issue,
    validate_issue,
)
from .proposals import (
    ProposalError,
    submit_learning_proposal_payload,
)
from .storage import connect, initialize_database, utc_now
from . import cancellation


def _run_operator_subprocess(
    command: "list[str]",
    *,
    input: str,
    env: "dict[str, str]",
    timeout: "Optional[int]",
) -> "subprocess.CompletedProcess[str]":
    """Run an operator command like ``subprocess.run`` but cancellable.

    Drop-in for the operator-call sites: same return shape, and still raises
    ``FileNotFoundError`` (bad command) and ``subprocess.TimeoutExpired`` (timeout)
    so the existing handlers are unchanged. Additionally, the live process is
    registered with the current job's cancel token (see :mod:`kyoko.cancellation`)
    and launched in its own session so a cancel can kill the whole process group;
    on cancel it raises ``cancellation.CancelledError``.
    """
    token = cancellation.current_token()
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    if token is not None:
        token.register_proc(proc)
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        if token is not None:
            token.unregister_proc(proc)
    if token is not None and token.cancelled:
        raise cancellation.CancelledError("cancelled")
    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


@dataclass(frozen=True)
class AnalyzeReport:
    """Issue-centric analysis result (ST2 decoupling): analysis surfaces ISSUES only
    (diagnosis), never a proposal. A proposal is authored in a separate, gate-#1-guarded
    step (:func:`propose_for_issue`)."""

    operator: str
    profile_id: str
    issue_ids: tuple[str, ...]          # all surfaced (new + bundled), in order
    new_issue_ids: tuple[str, ...]      # newly created this run
    bundled_issue_ids: tuple[str, ...]  # folded into an existing issue
    evidence_path: Path
    prompt_path: Path
    persisted: bool                     # True iff >=1 issue surfaced
    operator_run_id: Optional[str] = None
    raw_output_path: Optional[Path] = None
    attempts: int = 1

    def to_json(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "profile_id": self.profile_id,
            "issue_ids": list(self.issue_ids),
            "new_issue_ids": list(self.new_issue_ids),
            "bundled_issue_ids": list(self.bundled_issue_ids),
            "evidence_path": str(self.evidence_path),
            "prompt_path": str(self.prompt_path),
            "persisted": self.persisted,
            "operator_run_id": self.operator_run_id,
            "raw_output_path": str(self.raw_output_path)
            if self.raw_output_path is not None
            else None,
            "attempts": self.attempts,
        }


class AnalyzeError(Exception):
    """Raised when analysis cannot produce or persist surfaced issues."""


@dataclass(frozen=True)
class ProposeForIssueReport:
    """Result of authoring a proposal from one accepted issue (the proposal-authoring
    turn, decoupled from the diagnosis turn)."""

    issue_id: str
    proposal_id: str
    profile_id: str
    proposal_path: Optional[Path] = None
    operator_run_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "proposal_id": self.proposal_id,
            "profile_id": self.profile_id,
            "proposal_path": str(self.proposal_path) if self.proposal_path else None,
            "operator_run_id": self.operator_run_id,
        }


def analyze_with_mock_operator(
    *,
    db_path: Path,
    output_dir: Path,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    schema_path: Optional[Path] = None,
    schedule_id: Optional[str] = None,
) -> AnalyzeReport:
    """Diagnosis turn (mock): deterministically surface ``kyoko.issue.v1`` issues from the
    evidence bundle. No proposal and no gate is involved — a proposal is authored later in
    a separate, gate-#1-guarded step (:func:`propose_for_issue`)."""

    prompt_report = write_diagnosis_prompt_artifacts(
        db_path=db_path,
        output_dir=output_dir,
        target="mock",
        profile_id=profile_id,
        run_id=run_id,
        since=since,
        schema_path=schema_path,
    )
    resolved_schema_path = prompt_report.schema_path
    operator_run_id = _insert_operator_run(
        db_path=db_path,
        profile_id=prompt_report.profile_id,
        operator_label="mock",
        operator_kind="mock",
        adapter_id=None,
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        raw_output_path=None,
        command=None,
        schema_path=resolved_schema_path,
        max_retries=0,
        analyzed_since=since,
        schedule_id=schedule_id,
    )

    try:
        issues = mock_issues_from_bundle(prompt_report.bundle)
    except AnalyzeError as exc:
        _update_operator_run(db_path, operator_run_id, status="failed", error=str(exc))
        raise

    new_ids, bundled_ids, all_ids = _surface_issues(
        db_path=db_path,
        issues=issues,
        profile_id=prompt_report.profile_id,
    )

    _update_operator_run(
        db_path,
        operator_run_id,
        status="succeeded",
        metadata_updates={"issue_ids": list(all_ids)},
    )

    return AnalyzeReport(
        operator="mock",
        profile_id=prompt_report.profile_id,
        issue_ids=tuple(all_ids),
        new_issue_ids=tuple(new_ids),
        bundled_issue_ids=tuple(bundled_ids),
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        persisted=bool(all_ids),
        operator_run_id=operator_run_id,
    )


def _surface_issues(
    *,
    db_path: Path,
    issues: Sequence[dict[str, Any]],
    profile_id: str,
) -> tuple[list[str], list[str], list[str]]:
    """Integrate authored ``kyoko.issue.v1`` findings into the living skillbook.

    Each finding carries an integration ``op`` (the analysing agent reconciled it against
    the skillbook it was shown):

    - ``update`` — refine the existing entry ``target_id`` in place.
    - ``merge`` — fold this recurrence into ``target_id`` (union evidence, bump recurrence).
    - ``add`` (default) — surface a fresh entry through the deterministic dedup net (a
      run-independent signature backstop folds an obvious recurrence the agent missed).

    An ``update``/``merge`` whose target has vanished or has gone ``active`` (injected —
    its content evolves only through the gate) falls back to ``add`` so the observation is
    never lost. Returns ``(new_issue_ids, bundled_issue_ids, all_issue_ids)`` in order;
    ``update``/``merge`` count as bundled (folded into an existing entry)."""

    new_ids: list[str] = []
    bundled_ids: list[str] = []
    all_ids: list[str] = []
    for issue in issues:
        op = issue.get("op") if isinstance(issue.get("op"), str) else "add"
        target_id = issue.get("target_id") if isinstance(issue.get("target_id"), str) else None
        evidence_refs = (
            issue.get("evidence_refs") if isinstance(issue.get("evidence_refs"), list) else None
        )
        affected_span_ids = (
            issue.get("affected_span_ids")
            if isinstance(issue.get("affected_span_ids"), list)
            else None
        )

        if op in ("update", "merge") and target_id:
            try:
                if op == "merge":
                    integrated = merge_observation(
                        db_path=db_path,
                        issue_id=target_id,
                        evidence_refs=evidence_refs,
                        affected_span_ids=affected_span_ids,
                    )
                else:
                    section = issue.get("section")
                    integrated = update_issue(
                        db_path=db_path,
                        issue_id=target_id,
                        title=issue.get("title") if isinstance(issue.get("title"), str) else None,
                        body=issue.get("body") if isinstance(issue.get("body"), str) else None,
                        section=section if section in ("context", "harness") else None,
                        severity=issue.get("severity")
                        if isinstance(issue.get("severity"), str)
                        else None,
                        category=issue.get("category")
                        if isinstance(issue.get("category"), str)
                        else None,
                        root_cause=issue.get("root_cause")
                        if isinstance(issue.get("root_cause"), str)
                        else None,
                        evidence_refs=evidence_refs,
                        affected_span_ids=affected_span_ids,
                    )
                all_ids.append(integrated["id"])
                bundled_ids.append(integrated["id"])
                continue
            except IssueError:
                # Target vanished or has gone active (injected) — fall back to a fresh add
                # so the observation is never lost; the gate reconciles active entries.
                pass

        section = issue.get("section")
        status = "diagnosed" if issue.get("root_cause") else "open"
        surfaced, was_bundled = surface_issue(
            db_path=db_path,
            title=str(issue.get("title") or "Surfaced agent failure"),
            body=issue.get("body") if isinstance(issue.get("body"), str) else None,
            section=section if section in ("context", "harness") else None,
            severity=issue.get("severity") if isinstance(issue.get("severity"), str) else None,
            status=status,
            evidence_refs=evidence_refs,
            affected_span_ids=affected_span_ids,
            affected_agent_identity_ids=issue.get("affected_agent_identity_ids")
            if isinstance(issue.get("affected_agent_identity_ids"), list)
            else None,
            root_cause=issue.get("root_cause")
            if isinstance(issue.get("root_cause"), str)
            else None,
            source="analysis",
            profile_id=profile_id,
        )
        all_ids.append(surfaced["id"])
        if was_bundled:
            bundled_ids.append(surfaced["id"])
        else:
            new_ids.append(surfaced["id"])
    return new_ids, bundled_ids, all_ids


def analyze_with_command_operator(
    *,
    db_path: Path,
    output_dir: Path,
    command: Sequence[str],
    operator_label: str = "command",
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 120,
    operator_kind: str = "generic",
    adapter_id: Optional[str] = None,
    max_retries: int = 0,
    prompt_suffix: Optional[str] = None,
    schedule_id: Optional[str] = None,
) -> AnalyzeReport:
    if not command:
        raise AnalyzeError("operator_command_required")
    if max_retries < 0:
        raise AnalyzeError("operator_max_retries_must_be_non_negative")

    prompt_report = write_diagnosis_prompt_artifacts(
        db_path=db_path,
        output_dir=output_dir,
        target=operator_kind if operator_kind else operator_label,
        profile_id=profile_id,
        run_id=run_id,
        since=since,
        schema_path=schema_path,
    )
    resolved_schema_path = prompt_report.schema_path
    if prompt_suffix:
        prompt_report.prompt_path.write_text(
            "\n".join(
                [
                    prompt_report.prompt_path.read_text().rstrip(),
                    "",
                    prompt_suffix.strip(),
                    "",
                ]
            )
        )
    raw_output_path = output_dir / "operator-output.txt"
    operator_run_id = _insert_operator_run(
        db_path=db_path,
        profile_id=prompt_report.profile_id,
        operator_label=operator_label,
        operator_kind=operator_kind,
        adapter_id=adapter_id,
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        raw_output_path=raw_output_path,
        command=command,
        schema_path=resolved_schema_path,
        max_retries=max_retries,
        analyzed_since=since,
        schedule_id=schedule_id,
    )

    env = os.environ.copy()
    env["KYOKO_EVIDENCE_PATH"] = str(prompt_report.evidence_path)
    env["KYOKO_OPERATOR_PROMPT_PATH"] = str(prompt_report.prompt_path)
    env["KYOKO_PROFILE_ID"] = prompt_report.profile_id
    env["KYOKO_OPERATOR_TARGET"] = operator_kind
    # Diagnosis turn now advertises the ISSUES block. The proposal-block vars are kept
    # too (harmless) so an operator that also authors proposals elsewhere keeps working.
    env["KYOKO_ISSUES_BLOCK_BEGIN"] = BEGIN_ISSUES_BLOCK
    env["KYOKO_ISSUES_BLOCK_END"] = END_ISSUES_BLOCK
    env["KYOKO_PROPOSAL_BLOCK_BEGIN"] = BEGIN_PROPOSAL_BLOCK
    env["KYOKO_PROPOSAL_BLOCK_END"] = END_PROPOSAL_BLOCK
    if resolved_schema_path is not None:
        env["KYOKO_ISSUE_SCHEMA_PATH"] = str(resolved_schema_path)
    if run_id is not None:
        env["KYOKO_RUN_ID"] = run_id

    base_prompt_text = prompt_report.prompt_path.read_text()
    attempt_results: list[dict[str, Any]] = []
    last_error: Optional[str] = None
    surfaced_new: list[str] = []
    surfaced_bundled: list[str] = []
    surfaced_all: list[str] = []
    surfaced_done = False
    for attempt in range(1, max_retries + 2):
        prompt_text = base_prompt_text if attempt == 1 else _retry_prompt_text(base_prompt_text, last_error)
        prompt_path = prompt_report.prompt_path
        if attempt > 1:
            prompt_path = output_dir / f"operator-instructions-attempt-{attempt}.md"
            prompt_path.write_text(prompt_text)
        attempt_env = env.copy()
        attempt_env["KYOKO_OPERATOR_ATTEMPT"] = str(attempt)
        attempt_env["KYOKO_OPERATOR_MAX_RETRIES"] = str(max_retries)
        attempt_env["KYOKO_OPERATOR_PROMPT_PATH"] = str(prompt_path)
        expanded_command = expand_operator_command(
            command,
            prompt_text=prompt_text,
            evidence_path=prompt_report.evidence_path,
            prompt_path=prompt_path,
            profile_id=prompt_report.profile_id,
            schema_path=resolved_schema_path,
            run_id=run_id,
        )
        try:
            completed = _run_operator_subprocess(
                expanded_command,
                env=attempt_env,
                input=prompt_text,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            last_error = f"operator_command_not_found:{expanded_command[0]}"
            attempt_results.append(_attempt_result(attempt, "command_not_found", last_error))
            _write_attempt_outputs(raw_output_path, attempt_results)
            _update_operator_run(
                db_path,
                operator_run_id,
                status="failed",
                raw_output_path=raw_output_path,
                error=last_error,
                metadata_updates=_attempt_metadata(attempt_results, max_retries),
            )
            raise AnalyzeError(last_error) from exc
        except subprocess.TimeoutExpired as exc:
            last_error = f"operator_timeout:{timeout_seconds}"
            attempt_results.append(_attempt_result(attempt, "timeout", last_error))
            _write_attempt_outputs(raw_output_path, attempt_results)
            _update_operator_run(
                db_path,
                operator_run_id,
                status="failed",
                raw_output_path=raw_output_path,
                error=last_error,
                metadata_updates=_attempt_metadata(attempt_results, max_retries),
            )
            raise AnalyzeError(last_error) from exc

        attempt_result = _attempt_result(
            attempt,
            "completed",
            None,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            prompt_path=prompt_path,
        )
        attempt_results.append(attempt_result)
        _write_attempt_outputs(raw_output_path, attempt_results)

        if completed.returncode != 0:
            last_error = f"operator_failed:{completed.returncode}"
            attempt_result["status"] = "failed"
            attempt_result["error"] = last_error
            _write_attempt_outputs(raw_output_path, attempt_results)
            _update_operator_run(
                db_path,
                operator_run_id,
                status="failed",
                raw_output_path=raw_output_path,
                error=last_error,
                metadata_updates=_attempt_metadata(attempt_results, max_retries),
            )
            raise AnalyzeError(last_error)

        # Diagnosis turn: extract a JSON array of kyoko.issue.v1 issues and validate each.
        try:
            issues = extract_issues_from_output(completed.stdout)
            with connect(db_path) as connection:
                for issue in issues:
                    result = validate_issue(
                        connection=connection,
                        issue=issue,
                        schema_path=resolved_schema_path,
                    )
                    if not result.ok:
                        raise AnalyzeError(
                            "operator_issue_invalid:" + ",".join(result.errors)
                        )
        except AnalyzeError as exc:
            last_error = str(exc)
            attempt_result["status"] = "invalid_output"
            attempt_result["error"] = last_error
            _write_attempt_outputs(raw_output_path, attempt_results)
            if attempt <= max_retries:
                continue
            _update_operator_run(
                db_path,
                operator_run_id,
                status="failed",
                raw_output_path=raw_output_path,
                error=last_error,
                metadata_updates=_attempt_metadata(attempt_results, max_retries),
            )
            raise

        surfaced_new, surfaced_bundled, surfaced_all = _surface_issues(
            db_path=db_path,
            issues=issues,
            profile_id=prompt_report.profile_id,
        )
        surfaced_done = True
        attempt_result["status"] = "succeeded"
        _write_attempt_outputs(raw_output_path, attempt_results)
        break

    if not surfaced_done:
        raise AnalyzeError(last_error or "operator_retry_exhausted")

    _update_operator_run(
        db_path,
        operator_run_id,
        status="succeeded",
        raw_output_path=raw_output_path,
        metadata_updates={
            "issue_ids": list(surfaced_all),
            **_attempt_metadata(attempt_results, max_retries),
        },
    )

    return AnalyzeReport(
        operator=operator_label,
        profile_id=prompt_report.profile_id,
        issue_ids=tuple(surfaced_all),
        new_issue_ids=tuple(surfaced_new),
        bundled_issue_ids=tuple(surfaced_bundled),
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        persisted=bool(surfaced_all),
        operator_run_id=operator_run_id,
        raw_output_path=raw_output_path,
        attempts=len(attempt_results),
    )


def list_operator_runs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    initialize_database(db_path)
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM operator_runs
                ORDER BY started_at DESC, id DESC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_decode_operator_run(row) for row in rows]


def parse_operator_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise AnalyzeError(f"invalid_operator_command:{exc}") from exc


def _retry_prompt_text(base_prompt_text: str, last_error: Optional[str]) -> str:
    return "\n".join(
        [
            base_prompt_text.rstrip(),
            "",
            "## Retry Correction",
            "",
            "Your previous output was rejected by Kyoko and nothing was persisted.",
            f"Rejection reason: `{last_error or 'unknown'}`",
            "",
            "Return exactly one corrected block on stdout. Do not include extra blocks.",
            "",
        ]
    )


def _attempt_result(
    attempt: int,
    status: str,
    error: Optional[str],
    *,
    returncode: Optional[int] = None,
    stdout: str = "",
    stderr: str = "",
    prompt_path: Optional[Path] = None,
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "status": status,
        "error": error,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "prompt_path": str(prompt_path) if prompt_path is not None else None,
    }


def _write_attempt_outputs(raw_output_path: Path, attempts: Sequence[dict[str, Any]]) -> None:
    sections: list[str] = []
    for attempt in attempts:
        number = attempt.get("attempt", "?")
        status = attempt.get("status", "unknown")
        returncode = attempt.get("returncode")
        sections.append(f"=== attempt {number} status={status} returncode={returncode} ===")
        if attempt.get("error"):
            sections.append(f"error: {attempt['error']}")
        if attempt.get("prompt_path"):
            sections.append(f"prompt_path: {attempt['prompt_path']}")
        sections.append("--- stdout ---")
        sections.append(str(attempt.get("stdout") or ""))
        if attempt.get("stderr"):
            sections.append("--- stderr ---")
            sections.append(str(attempt.get("stderr") or ""))
    raw_output_path.write_text("\n".join(sections).rstrip() + "\n")


def _attempt_metadata(attempts: Sequence[dict[str, Any]], max_retries: int) -> dict[str, Any]:
    return {
        "attempts": len(attempts),
        "max_retries": max_retries,
        "attempt_results": [
            {
                "attempt": attempt.get("attempt"),
                "status": attempt.get("status"),
                "error": attempt.get("error"),
                "returncode": attempt.get("returncode"),
                "prompt_path": attempt.get("prompt_path"),
                "stdout_chars": len(str(attempt.get("stdout") or "")),
                "stderr_chars": len(str(attempt.get("stderr") or "")),
            }
            for attempt in attempts
        ],
    }


def expand_operator_command(
    command: Sequence[str],
    *,
    prompt_text: str,
    evidence_path: Path,
    prompt_path: Path,
    profile_id: str,
    schema_path: Optional[Path],
    run_id: Optional[str],
) -> list[str]:
    replacements = {
        "{prompt}": prompt_text,
        "{prompt_path}": str(prompt_path),
        "{evidence_path}": str(evidence_path),
        "{profile_id}": profile_id,
        "{schema_path}": str(schema_path) if schema_path is not None else "",
        "{run_id}": run_id or "",
    }
    expanded: list[str] = []
    for part in command:
        value = str(part)
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        expanded.append(value)
    return expanded


def _expand_operator_command(
    command: Sequence[str],
    *,
    prompt_text: str,
    evidence_path: Path,
    prompt_path: Path,
    profile_id: str,
    schema_path: Optional[Path],
    run_id: Optional[str],
) -> list[str]:
    return expand_operator_command(
        command,
        prompt_text=prompt_text,
        evidence_path=evidence_path,
        prompt_path=prompt_path,
        profile_id=profile_id,
        schema_path=schema_path,
        run_id=run_id,
    )


def extract_proposal_from_output(output: str) -> dict[str, Any]:
    if output.count(BEGIN_PROPOSAL_BLOCK) != 1 or output.count(END_PROPOSAL_BLOCK) != 1:
        raise AnalyzeError("operator_output_must_contain_exactly_one_proposal_block")

    start = output.index(BEGIN_PROPOSAL_BLOCK) + len(BEGIN_PROPOSAL_BLOCK)
    end = output.index(END_PROPOSAL_BLOCK)
    if end <= start:
        raise AnalyzeError("operator_proposal_block_order_invalid")

    raw_json = output[start:end].strip()
    try:
        proposal = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise AnalyzeError(f"operator_proposal_json_invalid:{exc}") from exc
    if not isinstance(proposal, dict):
        raise AnalyzeError("operator_proposal_must_be_object")
    return proposal


def extract_issues_from_output(output: str) -> list[dict[str, Any]]:
    """Parse exactly one issues block from operator stdout and json-load a JSON array of
    issue objects. Mirrors :func:`extract_proposal_from_output` (raises
    :class:`AnalyzeError` on malformed output)."""

    if output.count(BEGIN_ISSUES_BLOCK) != 1 or output.count(END_ISSUES_BLOCK) != 1:
        raise AnalyzeError("operator_output_must_contain_exactly_one_issues_block")

    start = output.index(BEGIN_ISSUES_BLOCK) + len(BEGIN_ISSUES_BLOCK)
    end = output.index(END_ISSUES_BLOCK)
    if end <= start:
        raise AnalyzeError("operator_issues_block_order_invalid")

    raw_json = output[start:end].strip()
    try:
        issues = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise AnalyzeError(f"operator_issues_json_invalid:{exc}") from exc
    if not isinstance(issues, list):
        raise AnalyzeError("operator_issues_must_be_array")
    for issue in issues:
        if not isinstance(issue, dict):
            raise AnalyzeError("operator_issue_must_be_object")
    return issues


def mock_learning_proposal(bundle: dict[str, Any]) -> dict[str, Any]:
    failed_span = _first_failed_span(bundle)
    if failed_span is None:
        raise AnalyzeError("no_failed_span_evidence")

    handoff = _nearest_handoff(bundle, failed_span)
    target_agent_id = failed_span.get("agent_identity_id") or "unknown"
    span_id = str(failed_span["id"])
    proposal_id = f"proposal_mock_{span_id}"

    evidence_refs = [
        {
            "entity_type": "span",
            "entity_id": span_id,
            "role": "failure",
            "note": f"Mock operator identified failed span {span_id}.",
        }
    ]
    if handoff is not None:
        evidence_refs.append(
            {
                "entity_type": "handoff",
                "entity_id": str(handoff["id"]),
                "role": "context",
                "note": "Failure happened before or during a handoff.",
            }
        )

    issue = _mock_issue(failed_span)
    insight = _mock_insight(failed_span)
    keywords = _mock_keywords(failed_span, handoff)

    return {
        "schema_version": "kyoko.learning_proposal.v1",
        "id": proposal_id,
        "profile_id": bundle["profile_id"],
        "producer": {
            "kind": "operator_agent",
            "name": "mock",
            "session_id": f"mock_session_{span_id}",
        },
        "state": "pending",
        "section": "context",
        "title": f"Add context guidance for {failed_span.get('name', 'failed span')}",
        "summary": f"Mock operator found failed span {span_id} and proposed a context skill.",
        "confidence": 0.5,
        "evidence_refs": evidence_refs,
        "problem": {
            "issue": issue,
            "severity": "medium",
            "root_cause": "The workflow context lacks explicit handling guidance for this failure mode.",
            "target": {
                "entity_type": "agent_identity",
                "entity_id": str(target_agent_id),
            },
        },
        "insight": insight,
        "proposed_changes": [
            {
                "type": "skillbook_update",
                "operation": "create",
                "section": "context",
                "issue": issue,
                "insight": insight,
                "keywords": keywords,
                "occurrence_refs": [
                    {
                        "entity_type": "span",
                        "entity_id": span_id,
                        "role": "failure",
                    }
                ],
            }
        ],
        "gate_expectations": {
            "requires_human_review": False,
            "requires_check_level": "L1_repeated",
            "requires_replay": False,
            "allowed_autonomy_section": "context",
            "notes": "Mock operator output is for deterministic bridge validation.",
        },
        "created_at": utc_now(),
    }


def mock_issues_from_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Deterministic DIAGNOSIS-half of the mock operator: surface one ``kyoko.issue.v1``
    issue from the first failed span (no fix is proposed here)."""

    failed_span = _first_failed_span(bundle)
    if failed_span is None:
        raise AnalyzeError("no_failed_span_evidence")

    handoff = _nearest_handoff(bundle, failed_span)
    span_id = str(failed_span["id"])
    name = str(failed_span.get("name") or "failed span")

    evidence_refs = [
        {
            "entity_type": "span",
            "entity_id": span_id,
            "role": "failure",
            "note": f"Mock operator identified failed span {span_id}.",
        }
    ]
    if handoff is not None:
        evidence_refs.append(
            {
                "entity_type": "handoff",
                "entity_id": str(handoff["id"]),
                "role": "context",
                "note": "Failure happened before or during a handoff.",
            }
        )

    issue: dict[str, Any] = {
        "schema_version": "kyoko.issue.v1",
        "title": f"Add context guidance for {name}",
        "body": _mock_insight(failed_span),
        "section": "context",
        "severity": "medium",
        "root_cause": _mock_issue(failed_span),
        "evidence_refs": evidence_refs,
        "affected_span_ids": [span_id],
        "keywords": _mock_keywords(failed_span, handoff),
    }
    # Only anchor a real agent identity (referential integrity); never the "unknown" stub.
    agent_id = failed_span.get("agent_identity_id")
    if isinstance(agent_id, str) and agent_id and agent_id != "unknown":
        issue["affected_agent_identity_ids"] = [agent_id]
    return [issue]


def mock_proposal_from_issue(
    issue: dict[str, Any], bundle: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """Deterministic FIX-half of the mock operator: author one ``LearningProposal`` that
    fixes an accepted ``issue``. ``issue_id``/``profile_id`` are injected by the caller
    (:func:`propose_for_issue`); a direct caller should pass a fully-stored issue dict."""

    issue_key = str(issue.get("id") or "unknown")
    section = issue.get("section") or "context"
    profile_id = issue.get("profile_id") or (bundle or {}).get("profile_id") or "unknown"

    span_ids = [str(s) for s in (issue.get("affected_span_ids") or [])]
    # Deterministic, span-anchored id (matches the legacy `proposal_mock_span_<id>`
    # convention) so the same failure always yields the same proposal id; fall back to the
    # issue id only when no span anchor exists.
    proposal_id = (
        f"proposal_mock_{span_ids[0]}" if span_ids else f"proposal_mock_{issue_key}"
    )
    agent_ids = [str(a) for a in (issue.get("affected_agent_identity_ids") or [])]
    target = (
        {"entity_type": "agent_identity", "entity_id": agent_ids[0]}
        if agent_ids
        else {"entity_type": "agent_identity", "entity_id": "unknown"}
    )

    evidence_refs = []
    for index, ref in enumerate(issue.get("evidence_refs") or []):
        if not isinstance(ref, dict):
            continue
        evidence_refs.append(
            {
                "entity_type": ref.get("entity_type"),
                "entity_id": ref.get("entity_id"),
                "role": ref.get("role") or ("failure" if index == 0 else "context"),
                "note": ref.get("note") or "Carried from the originating issue.",
            }
        )
    if not evidence_refs and span_ids:
        evidence_refs = [
            {"entity_type": "span", "entity_id": span_ids[0], "role": "failure"}
        ]

    issue_text = issue.get("root_cause") or issue.get("title") or "agent failure"
    insight = issue.get("body") or issue.get("root_cause") or (
        "Record the failure reason and avoid treating incomplete evidence as complete."
    )
    keywords = list(issue.get("keywords") or ["failure"])
    if span_ids:
        occurrence_refs = [
            {"entity_type": "span", "entity_id": span_id, "role": "failure"}
            for span_id in span_ids
        ]
    elif evidence_refs:
        occurrence_refs = [
            {
                "entity_type": evidence_refs[0]["entity_type"],
                "entity_id": evidence_refs[0]["entity_id"],
                "role": "failure",
            }
        ]
    else:
        occurrence_refs = []

    return {
        "schema_version": "kyoko.learning_proposal.v1",
        "id": proposal_id,
        "profile_id": profile_id,
        "producer": {
            "kind": "operator_agent",
            "name": "mock",
            "session_id": f"mock_session_{issue_key}",
        },
        "state": "pending",
        "section": section,
        "title": issue.get("title") or f"Fix {issue_text}",
        "summary": f"Mock operator authored a {section} fix for issue {issue_key}.",
        "confidence": 0.5,
        "evidence_refs": evidence_refs,
        "problem": {
            "issue": issue_text,
            "severity": issue.get("severity") or "medium",
            "root_cause": issue.get("root_cause")
            or "The workflow context lacks explicit handling guidance for this failure mode.",
            "target": target,
        },
        "insight": insight,
        "proposed_changes": [
            {
                "type": "skillbook_update",
                "operation": "create",
                "section": section,
                "issue": issue_text,
                "insight": insight,
                "keywords": keywords,
                "occurrence_refs": occurrence_refs,
            }
        ],
        "gate_expectations": {
            "requires_human_review": False,
            "requires_check_level": "L1_repeated",
            "requires_replay": False,
            "allowed_autonomy_section": section,
            "notes": "Mock operator output is for deterministic bridge validation.",
        },
        "created_at": utc_now(),
    }


def propose_for_issue(
    *,
    db_path: Path,
    output_dir: Path,
    issue_id: str,
    operator: str = "mock",
    command: Optional[Sequence[str]] = None,
    schema_path: Optional[Path] = None,
    operator_kind: str = "generic",
    adapter_id: Optional[str] = None,
    timeout_seconds: int = 120,
    max_retries: int = 0,
    profile_id: Optional[str] = None,
) -> ProposeForIssueReport:
    """Author one ``LearningProposal`` from an accepted issue (the proposal-authoring turn).

    Loads the issue, builds the proposal-authoring prompt, invokes the operator
    (``mock`` is deterministic; ``command`` shells out), injects the issue/profile ids on
    the result (never trusting the operator for them), validates+persists the proposal, and
    links it back to the issue (advancing it to ``proposed``). Gate #2 (checks/replay/apply)
    is unchanged and runs downstream."""

    initialize_database(db_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    issue = get_issue(db_path=db_path, issue_id=issue_id)
    resolved_profile_id = profile_id or str(issue["profile_id"])

    prompt_report = write_proposal_prompt_artifacts(
        db_path=db_path,
        output_dir=output_dir,
        issue=issue,
        target="mock" if operator == "mock" else operator_kind,
        profile_id=resolved_profile_id,
        schema_path=schema_path,
    )
    resolved_schema_path = prompt_report.schema_path
    raw_output_path = None if operator == "mock" else output_dir / "propose-output.txt"
    operator_run_id = _insert_operator_run(
        db_path=db_path,
        profile_id=resolved_profile_id,
        operator_label="propose" if operator == "mock" else f"propose:{operator_kind}",
        operator_kind="mock" if operator == "mock" else operator_kind,
        adapter_id=adapter_id,
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        raw_output_path=raw_output_path,
        command=command,
        schema_path=resolved_schema_path,
        max_retries=max_retries,
    )

    try:
        if operator == "mock":
            proposal = mock_proposal_from_issue(issue, bundle=prompt_report.bundle)
        elif operator == "command":
            if not command:
                raise AnalyzeError("operator_command_required")
            proposal = _invoke_proposal_command(
                command=command,
                prompt_report=prompt_report,
                profile_id=resolved_profile_id,
                schema_path=resolved_schema_path,
                operator_kind=operator_kind,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                raw_output_path=raw_output_path,
            )
        else:
            raise AnalyzeError(f"unsupported_propose_operator:{operator}")
    except AnalyzeError as exc:
        _update_operator_run(db_path, operator_run_id, status="failed", error=str(exc))
        raise

    # Inject identity — never trust the operator to echo these correctly.
    proposal["issue_id"] = issue_id
    proposal["profile_id"] = resolved_profile_id

    proposal_path = output_dir / f"{proposal['id']}.json"
    proposal_path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n")
    try:
        submit_learning_proposal_payload(
            db_path=db_path,
            proposal=proposal,
            schema_path=resolved_schema_path,
        )
    except ProposalError as exc:
        _update_operator_run(db_path, operator_run_id, status="failed", error=str(exc))
        raise AnalyzeError(str(exc)) from exc

    link_proposal_to_issue(
        db_path=db_path, issue_id=issue_id, proposal_id=str(proposal["id"])
    )
    _update_operator_run(
        db_path,
        operator_run_id,
        status="succeeded",
        raw_output_path=raw_output_path,
        proposal_id=str(proposal["id"]),
    )
    return ProposeForIssueReport(
        issue_id=issue_id,
        proposal_id=str(proposal["id"]),
        profile_id=resolved_profile_id,
        proposal_path=proposal_path,
        operator_run_id=operator_run_id,
    )


def _invoke_proposal_command(
    *,
    command: Sequence[str],
    prompt_report: Any,
    profile_id: str,
    schema_path: Optional[Path],
    operator_kind: str,
    timeout_seconds: int,
    max_retries: int,
    raw_output_path: Optional[Path],
) -> dict[str, Any]:
    """Run the proposal-authoring subprocess operator and extract its proposal block.
    Retries on malformed output up to ``max_retries`` times."""

    base_prompt_text = prompt_report.prompt_path.read_text()
    env = os.environ.copy()
    env["KYOKO_EVIDENCE_PATH"] = str(prompt_report.evidence_path)
    env["KYOKO_OPERATOR_PROMPT_PATH"] = str(prompt_report.prompt_path)
    env["KYOKO_PROFILE_ID"] = profile_id
    env["KYOKO_OPERATOR_TARGET"] = operator_kind
    env["KYOKO_PROPOSAL_BLOCK_BEGIN"] = BEGIN_PROPOSAL_BLOCK
    env["KYOKO_PROPOSAL_BLOCK_END"] = END_PROPOSAL_BLOCK
    if schema_path is not None:
        env["KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH"] = str(schema_path)

    last_error: Optional[str] = None
    outputs: list[str] = []
    for attempt in range(1, max_retries + 2):
        prompt_text = (
            base_prompt_text
            if attempt == 1
            else _retry_prompt_text(base_prompt_text, last_error)
        )
        expanded_command = expand_operator_command(
            command,
            prompt_text=prompt_text,
            evidence_path=prompt_report.evidence_path,
            prompt_path=prompt_report.prompt_path,
            profile_id=profile_id,
            schema_path=schema_path,
            run_id=None,
        )
        try:
            completed = _run_operator_subprocess(
                expanded_command,
                env=env,
                input=prompt_text,
                timeout=timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise AnalyzeError(f"operator_command_not_found:{expanded_command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AnalyzeError(f"operator_timeout:{timeout_seconds}") from exc
        outputs.append(completed.stdout)
        if raw_output_path is not None:
            raw_output_path.write_text("\n".join(outputs))
        if completed.returncode != 0:
            raise AnalyzeError(f"operator_failed:{completed.returncode}")
        try:
            return extract_proposal_from_output(completed.stdout)
        except AnalyzeError as exc:
            last_error = str(exc)
            if attempt <= max_retries:
                continue
            raise
    raise AnalyzeError(last_error or "operator_retry_exhausted")


def _first_failed_span(bundle: dict[str, Any]) -> Optional[dict[str, Any]]:
    for span in bundle.get("spans", []):
        if isinstance(span, dict) and span.get("status") == "failed":
            return span
    return None


def _nearest_handoff(bundle: dict[str, Any], failed_span: dict[str, Any]) -> Optional[dict[str, Any]]:
    run_id = failed_span.get("run_id")
    for handoff in bundle.get("handoffs", []):
        if isinstance(handoff, dict) and handoff.get("run_id") == run_id:
            return handoff
    return None


def _mock_issue(failed_span: dict[str, Any]) -> str:
    name = str(failed_span.get("name") or "operation")
    attributes = failed_span.get("attributes_json")
    if isinstance(attributes, dict) and attributes.get("error_type") == "timeout":
        return f"{name} timeouts are treated as final failures without recovery guidance."
    return f"{name} failures do not have explicit recovery guidance."


def _mock_insight(failed_span: dict[str, Any]) -> str:
    name = str(failed_span.get("name") or "operation")
    attributes = failed_span.get("attributes_json")
    if isinstance(attributes, dict) and attributes.get("error_type") == "timeout":
        return f"When {name} times out, retry once and mark the evidence incomplete if the retry fails."
    return f"When {name} fails, record the failure reason and avoid treating incomplete evidence as complete."


def _mock_keywords(failed_span: dict[str, Any], handoff: Optional[dict[str, Any]]) -> list[str]:
    keywords = [str(failed_span.get("kind") or "span"), str(failed_span.get("name") or "failure")]
    attributes = failed_span.get("attributes_json")
    if isinstance(attributes, dict) and isinstance(attributes.get("error_type"), str):
        keywords.append(attributes["error_type"])
    if handoff is not None:
        keywords.append("handoff")
    normalized = []
    seen = set()
    for keyword in keywords:
        value = keyword.strip().lower().replace(" ", "_")
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _insert_operator_run(
    *,
    db_path: Path,
    profile_id: str,
    operator_label: str,
    operator_kind: str,
    adapter_id: Optional[str],
    evidence_path: Path,
    prompt_path: Path,
    raw_output_path: Optional[Path],
    command: Optional[Sequence[str]],
    schema_path: Optional[Path],
    max_retries: int,
    analyzed_since: Optional[str] = None,
    schedule_id: Optional[str] = None,
) -> str:
    initialize_database(db_path)
    operator_run_id = f"oprun_{utc_now().replace(':', '').replace('-', '').replace('Z', '')}_{uuid.uuid4().hex[:8]}"
    now = utc_now()
    metadata = {
        "command": list(command) if command is not None else None,
        "schema_path": str(schema_path) if schema_path is not None else None,
        "max_retries": max_retries,
        "attempts": 0,
        "attempt_results": [],
    }
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO operator_runs (
              id,
              profile_id,
              adapter_id,
              operator_label,
              operator_kind,
              status,
              started_at,
              ended_at,
              evidence_ref,
              prompt_ref,
              raw_output_ref,
              proposal_id,
              error,
              metadata_json,
              schedule_id,
              analyzed_since,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operator_run_id,
                profile_id,
                adapter_id,
                operator_label,
                operator_kind,
                "running",
                now,
                None,
                str(evidence_path),
                str(prompt_path),
                str(raw_output_path) if raw_output_path is not None else None,
                None,
                None,
                _json_dumps(metadata),
                schedule_id,
                analyzed_since,
                now,
                now,
            ),
        )
    return operator_run_id


def _update_operator_run(
    db_path: Path,
    operator_run_id: str,
    *,
    status: str,
    proposal_id: Optional[str] = None,
    raw_output_path: Optional[Path] = None,
    error: Optional[str] = None,
    metadata_updates: Optional[dict[str, Any]] = None,
) -> None:
    now = utc_now()
    with connect(db_path) as connection:
        metadata = None
        if metadata_updates is not None:
            row = connection.execute(
                "SELECT metadata_json FROM operator_runs WHERE id = ?",
                (operator_run_id,),
            ).fetchone()
            metadata = _json_loads(row["metadata_json"], {}) if row is not None else {}
            metadata.update(metadata_updates)
        connection.execute(
            """
            UPDATE operator_runs
            SET status = ?,
                ended_at = ?,
                proposal_id = COALESCE(?, proposal_id),
                raw_output_ref = COALESCE(?, raw_output_ref),
                error = ?,
                metadata_json = COALESCE(?, metadata_json),
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                now,
                proposal_id,
                str(raw_output_path) if raw_output_path is not None else None,
                error,
                _json_dumps(metadata) if metadata is not None else None,
                now,
                operator_run_id,
            ),
        )


def _decode_operator_run(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    metadata = _json_loads(payload.pop("metadata_json"), {})
    payload["metadata"] = metadata
    attempt_results = metadata.get("attempt_results") if isinstance(metadata, dict) else None
    if isinstance(attempt_results, list) and attempt_results:
        last_attempt = attempt_results[-1]
        payload["attempt_count"] = len(attempt_results)
        payload["max_retries"] = metadata.get("max_retries", 0)
        payload["last_attempt_status"] = (
            last_attempt.get("status") if isinstance(last_attempt, dict) else None
        )
    else:
        payload["attempt_count"] = int(metadata.get("attempts") or 0) if isinstance(metadata, dict) else 0
        payload["max_retries"] = metadata.get("max_retries", 0) if isinstance(metadata, dict) else 0
        payload["last_attempt_status"] = None
    payload["failure_kind"] = _operator_failure_kind(payload.get("status"), payload.get("error"))
    return payload


def _operator_failure_kind(status: Any, error: Any) -> Optional[str]:
    if status != "failed" or not isinstance(error, str) or not error:
        return None
    if error.startswith("operator_timeout:"):
        return "timeout"
    if error.startswith("operator_command_not_found:"):
        return "command_not_found"
    if error.startswith("operator_failed:"):
        return "nonzero_exit"
    if error.startswith("operator_proposal_json_invalid:"):
        return "invalid_output"
    if error.startswith("operator_output_must_contain_exactly_one_proposal_block"):
        return "invalid_output"
    if error.startswith("operator_issues_json_invalid:"):
        return "invalid_output"
    if error.startswith("operator_output_must_contain_exactly_one_issues_block"):
        return "invalid_output"
    if error.startswith("operator_issue_invalid:"):
        return "invalid_output"
    if error.startswith("schema_error:"):
        return "invalid_proposal"
    if "evidence_ref_not_found:" in error:
        return "invalid_proposal"
    return "operator_error"


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
