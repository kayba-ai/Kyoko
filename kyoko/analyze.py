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
    BEGIN_PROPOSAL_BLOCK,
    END_PROPOSAL_BLOCK,
    write_operator_prompt_artifacts,
)
from .autonomy import evaluate_issue_to_proposal_gate
from .issues import link_proposal_to_issue
from .proposals import (
    ProposalError,
    originate_issue_for_proposal,
    submit_learning_proposal_payload,
)
from .storage import connect, initialize_database, utc_now


@dataclass(frozen=True)
class AnalyzeReport:
    operator: str
    profile_id: str
    proposal_id: Optional[str]
    evidence_path: Path
    prompt_path: Path
    proposal_path: Optional[Path]
    persisted: bool
    operator_run_id: Optional[str] = None
    raw_output_path: Optional[Path] = None
    attempts: int = 1
    issue_id: Optional[str] = None
    # Gate #1 (issue -> proposal). When the section's autonomy mode is `off`, analysis
    # still surfaces+diagnoses the Issue but generates no proposal (proposal_id is None).
    gate1_mode: Optional[str] = None
    gate1_allow: bool = True
    gate1_reason: Optional[str] = None


class AnalyzeError(Exception):
    """Raised when analysis cannot produce or persist a proposal."""


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
    prompt_report = write_operator_prompt_artifacts(
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
        proposal = mock_learning_proposal(prompt_report.bundle)
    except AnalyzeError as exc:
        _update_operator_run(db_path, operator_run_id, status="failed", error=str(exc))
        raise

    # Issue-centric spine: analysis surfaces+diagnoses an Issue first, and the proposal
    # is born of it. originate_issue_for_proposal stamps proposal["issue_id"] in place.
    issue = originate_issue_for_proposal(
        db_path=db_path,
        proposal=proposal,
        source="analysis",
        profile_id=prompt_report.profile_id,
    )

    # Gate #1: may this issue generate a proposal? Reuses the section's autonomy mode.
    gate = evaluate_issue_to_proposal_gate(
        db_path=db_path,
        section=proposal.get("section"),
        profile_id=prompt_report.profile_id,
    )
    if not gate.allow_generate:
        _update_operator_run(
            db_path,
            operator_run_id,
            status="succeeded",
            metadata_updates={"gate1": gate.to_json(), "issue_id": issue["id"]},
        )
        return AnalyzeReport(
            operator="mock",
            profile_id=prompt_report.profile_id,
            proposal_id=None,
            evidence_path=prompt_report.evidence_path,
            prompt_path=prompt_report.prompt_path,
            proposal_path=None,
            persisted=False,
            operator_run_id=operator_run_id,
            issue_id=issue["id"],
            gate1_mode=gate.mode,
            gate1_allow=False,
            gate1_reason=gate.reason,
        )

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
        db_path=db_path, issue_id=issue["id"], proposal_id=str(proposal["id"])
    )
    _update_operator_run(
        db_path,
        operator_run_id,
        status="succeeded",
        proposal_id=str(proposal["id"]),
    )

    return AnalyzeReport(
        operator="mock",
        profile_id=prompt_report.profile_id,
        proposal_id=str(proposal["id"]),
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        proposal_path=proposal_path,
        persisted=True,
        operator_run_id=operator_run_id,
        issue_id=issue["id"],
        gate1_mode=gate.mode,
        gate1_allow=True,
        gate1_reason=gate.reason,
    )


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

    prompt_report = write_operator_prompt_artifacts(
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
    env["KYOKO_PROPOSAL_BLOCK_BEGIN"] = BEGIN_PROPOSAL_BLOCK
    env["KYOKO_PROPOSAL_BLOCK_END"] = END_PROPOSAL_BLOCK
    if resolved_schema_path is not None:
        env["KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH"] = str(resolved_schema_path)
    if run_id is not None:
        env["KYOKO_RUN_ID"] = run_id

    base_prompt_text = prompt_report.prompt_path.read_text()
    attempt_results: list[dict[str, Any]] = []
    last_error: Optional[str] = None
    proposal: Optional[dict[str, Any]] = None
    proposal_path: Optional[Path] = None
    originated_issue: Optional[dict[str, Any]] = None
    resolved_gate: Optional[Any] = None
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
            completed = subprocess.run(
                expanded_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=attempt_env,
                input=prompt_text,
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

        try:
            proposal = extract_proposal_from_output(completed.stdout)
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

        # Issue-centric spine: the proposal is born of an Issue. Create it once and
        # reuse it across retries (each retry re-stamps the same issue_id) so a failed
        # attempt does not orphan a fresh issue.
        if originated_issue is None:
            originated_issue = originate_issue_for_proposal(
                db_path=db_path,
                proposal=proposal,
                source="analysis",
                profile_id=prompt_report.profile_id,
            )
            # Gate #1: if the section's mode is `off`, surface+diagnose only — no
            # proposal, no retries. The decision is fixed by the proposal's section.
            gate = evaluate_issue_to_proposal_gate(
                db_path=db_path,
                section=proposal.get("section"),
                profile_id=prompt_report.profile_id,
            )
            resolved_gate = gate
            if not gate.allow_generate:
                attempt_result["status"] = "succeeded"
                _write_attempt_outputs(raw_output_path, attempt_results)
                _update_operator_run(
                    db_path,
                    operator_run_id,
                    status="succeeded",
                    raw_output_path=raw_output_path,
                    metadata_updates={
                        "gate1": gate.to_json(),
                        "issue_id": originated_issue["id"],
                        **_attempt_metadata(attempt_results, max_retries),
                    },
                )
                return AnalyzeReport(
                    operator=operator_label,
                    profile_id=prompt_report.profile_id,
                    proposal_id=None,
                    evidence_path=prompt_report.evidence_path,
                    prompt_path=prompt_report.prompt_path,
                    proposal_path=None,
                    persisted=False,
                    operator_run_id=operator_run_id,
                    raw_output_path=raw_output_path,
                    attempts=len(attempt_results),
                    issue_id=originated_issue["id"],
                    gate1_mode=gate.mode,
                    gate1_allow=False,
                    gate1_reason=gate.reason,
                )
        else:
            proposal["issue_id"] = originated_issue["id"]

        proposal_path = output_dir / f"{proposal['id']}.json"
        proposal_path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n")
        try:
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=resolved_schema_path,
            )
        except ProposalError as exc:
            last_error = str(exc)
            attempt_result["status"] = "invalid_proposal"
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
            raise AnalyzeError(last_error) from exc

        attempt_result["status"] = "succeeded"
        _write_attempt_outputs(raw_output_path, attempt_results)
        break

    if proposal is None or proposal_path is None:
        raise AnalyzeError(last_error or "operator_retry_exhausted")

    if originated_issue is not None:
        link_proposal_to_issue(
            db_path=db_path,
            issue_id=originated_issue["id"],
            proposal_id=str(proposal["id"]),
        )
    _update_operator_run(
        db_path,
        operator_run_id,
        status="succeeded",
        raw_output_path=raw_output_path,
        proposal_id=str(proposal["id"]),
        metadata_updates=_attempt_metadata(attempt_results, max_retries),
    )

    return AnalyzeReport(
        operator=operator_label,
        profile_id=prompt_report.profile_id,
        proposal_id=str(proposal["id"]),
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        proposal_path=proposal_path,
        persisted=True,
        operator_run_id=operator_run_id,
        raw_output_path=raw_output_path,
        attempts=len(attempt_results),
        issue_id=originated_issue["id"] if originated_issue is not None else None,
        gate1_mode=resolved_gate.mode if resolved_gate is not None else None,
        gate1_allow=resolved_gate.allow_generate if resolved_gate is not None else True,
        gate1_reason=resolved_gate.reason if resolved_gate is not None else None,
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
            "Your previous output was rejected by Kyoko and no proposal was persisted.",
            f"Rejection reason: `{last_error or 'unknown'}`",
            "",
            "Return exactly one corrected proposal block on stdout. Do not include extra proposal blocks.",
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
