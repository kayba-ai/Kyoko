from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.metadata
import io
import json
import os
import platform
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional, Sequence

from .proposals import submit_learning_proposal_payload
from .skillbook import export_skillbook
from .storage import connect, initialize_database, utc_now


ACE_SKILLBOOK_SCHEMA_VERSION = "2"
PROPOSAL_SCHEMA_VERSION = "kyoko.learning_proposal.v1"
ACE_NATIVE_RUN_REPORT_FILENAME = "ace-native-run-report.json"
EVIDENCE_ROLES = {
    "failure",
    "context",
    "counterexample",
    "verification",
    "regression",
    "source",
}
ENTITY_TABLES = {
    "run": "runs",
    "span": "spans",
    "task": "tasks",
    "task_attempt": "task_attempts",
    "handoff": "handoffs",
    "timeline_event": "timeline_events",
    "skill": "skills",
}


class AceBridgeError(Exception):
    """Raised when Kyoko cannot convert ACE state safely."""


@dataclass(frozen=True)
class AceDiffReport:
    profile_id: str
    proposal_ids: tuple[str, ...]
    proposal_paths: tuple[Path, ...]
    proposals: tuple[dict[str, Any], ...]
    persisted: bool
    unsupported_changes: tuple[str, ...]

    def to_json(self, *, include_proposals: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "profile_id": self.profile_id,
            "proposal_ids": list(self.proposal_ids),
            "proposal_paths": [str(path) for path in self.proposal_paths],
            "persisted": self.persisted,
            "unsupported_changes": list(self.unsupported_changes),
        }
        if include_proposals:
            payload["proposals"] = list(self.proposals)
        return payload


@dataclass(frozen=True)
class AceNativePrepareReport:
    profile_id: str
    db_path: Path
    output_dir: Path
    before_path: Path
    after_path: Path
    proposal_output_dir: Path
    stdout_path: Path
    stderr_path: Path
    handoff_path: Path
    original_command: tuple[str, ...]
    command: tuple[str, ...]
    environment: dict[str, str]
    timeout_seconds: int
    used_temporary_output_dir: bool
    include_inactive: bool
    schema_path: Optional[Path]
    provider_backed: bool
    before_schema_version: str
    before_skill_count: int

    @property
    def shell_command(self) -> str:
        return shlex.join(self.command)

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "before_path": str(self.before_path),
            "after_path": str(self.after_path),
            "proposal_output_dir": str(self.proposal_output_dir),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "handoff_path": str(self.handoff_path),
            "original_command": list(self.original_command),
            "command": list(self.command),
            "expanded_command": list(self.command),
            "shell_command": self.shell_command,
            "environment": dict(sorted(self.environment.items())),
            "environment_keys": sorted(self.environment),
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": "",
            "timeout_seconds": self.timeout_seconds,
            "used_temporary_output_dir": self.used_temporary_output_dir,
            "include_inactive": self.include_inactive,
            "schema_path": str(self.schema_path) if self.schema_path is not None else None,
            "before_schema_version": self.before_schema_version,
            "before_skill_count": self.before_skill_count,
            "after_initialized_from_before": True,
            "prepare_only": True,
            "prepared": True,
            "external_command_invoked": False,
            "provider_backed": self.provider_backed,
            "live_operator_invoked": False,
            "external_model_invoked": False,
            "canonical_mutation": False,
            "passed": True,
            "diff": None,
        }


@dataclass(frozen=True)
class AceNativeRunReport:
    profile_id: str
    db_path: Path
    output_dir: Path
    before_path: Path
    after_path: Path
    proposal_output_dir: Path
    command: tuple[str, ...]
    original_command: tuple[str, ...]
    environment: dict[str, str]
    handoff_path: Path
    returncode: int
    stdout_path: Path
    stderr_path: Path
    stdout_tail: str
    stderr_tail: str
    timeout_seconds: int
    diff: AceDiffReport
    used_temporary_output_dir: bool
    provider_backed: bool
    report_path: Optional[Path] = None

    @property
    def shell_command(self) -> str:
        return shlex.join(self.command)

    def to_json(self, *, include_proposals: bool = True) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "before_path": str(self.before_path),
            "after_path": str(self.after_path),
            "proposal_output_dir": str(self.proposal_output_dir),
            "handoff_path": str(self.handoff_path),
            "original_command": list(self.original_command),
            "command": list(self.command),
            "expanded_command": list(self.command),
            "shell_command": self.shell_command,
            "environment": dict(sorted(self.environment.items())),
            "environment_keys": sorted(self.environment),
            "returncode": self.returncode,
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "timeout_seconds": self.timeout_seconds,
            "used_temporary_output_dir": self.used_temporary_output_dir,
            "prepare_only": False,
            "prepared": True,
            "external_command_invoked": True,
            "provider_backed": self.provider_backed,
            "report_path": str(self.report_path) if self.report_path is not None else None,
            "live_operator_invoked": False,
            "external_model_invoked": self.provider_backed,
            "canonical_mutation": False,
            "passed": self.returncode == 0,
            "diff": self.diff.to_json(include_proposals=include_proposals),
        }


def check_ace_compatibility(
    *,
    db_path: Path,
    ace_path: Optional[Path] = None,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Load Kyoko's ACE Skillbook export through ACE's public Skillbook API."""

    initialize_database(db_path)
    exported = export_skillbook(
        db_path,
        section="all",
        include_inactive=include_inactive,
    )
    report: dict[str, Any] = {
        "available": False,
        "schema_version": exported.get("schema_version"),
        "skill_count": len(exported.get("skills", {}))
        if isinstance(exported.get("skills"), dict)
        else 0,
        "ace_path": str(ace_path) if ace_path is not None else None,
        "ace_package_version": _ace_package_version(),
        "ace_source_version": _ace_source_version(ace_path),
        "python_version": platform.python_version(),
        "expected_api": "ace.core.skillbook.Skillbook",
        "ace_importable": False,
        "ace_import_path": None,
        "ace_module_version": None,
        "ace_import_stdout": "",
        "ace_import_stderr": "",
        "ace_import_error": None,
        "detected_api": None,
        "skillbook_import_path": None,
        "skillbook_api_error": None,
        "import_path": None,
        "import_stdout": "",
        "import_stderr": "",
        "roundtrip_schema_version": None,
        "roundtrip_skill_count": None,
        "error": None,
    }
    report.update(_detect_ace_runtime(ace_path))

    import_stdout = io.StringIO()
    import_stderr = io.StringIO()
    try:
        with _temporary_ace_import_path(ace_path):
            with redirect_stdout(import_stdout), redirect_stderr(import_stderr):
                module = importlib.import_module("ace.core.skillbook")
                skillbook_class = getattr(module, "Skillbook")
                skillbook = skillbook_class.from_dict(copy.deepcopy(exported))
                roundtrip = skillbook.to_dict()
            report.update(
                {
                    "available": True,
                    "import_path": str(getattr(module, "__file__", "")) or None,
                    "import_stdout": import_stdout.getvalue(),
                    "import_stderr": import_stderr.getvalue(),
                    "roundtrip_schema_version": roundtrip.get("schema_version"),
                    "roundtrip_skill_count": len(roundtrip.get("skills", {}))
                    if isinstance(roundtrip.get("skills"), dict)
                    else None,
                    "stats": skillbook.stats() if hasattr(skillbook, "stats") else None,
                }
            )
    except Exception as exc:  # pragma: no cover - exact import failures are environment-specific.
        report["error"] = str(exc)
        report["import_stdout"] = import_stdout.getvalue()
        report["import_stderr"] = import_stderr.getvalue()

    return report


def run_native_ace_command(
    *,
    db_path: Path,
    command: Sequence[str],
    profile_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    persist: bool = False,
    schema_path: Optional[Path] = None,
    producer_name: str = "native_ace",
    evidence_refs: Sequence[dict[str, Any]] = (),
    include_inactive: bool = False,
    provider_backed: bool = False,
    timeout_seconds: int = 120,
) -> AceNativeRunReport:
    """Run an external ACE command against a cloned Skillbook and import its diff."""

    prepared = prepare_native_ace_command(
        db_path,
        profile_id=profile_id,
        output_dir=output_dir,
        schema_path=schema_path,
        command=command,
        include_inactive=include_inactive,
        provider_backed=provider_backed,
        timeout_seconds=timeout_seconds,
    )
    env = os.environ.copy()
    env.update(prepared.environment)
    try:
        completed = subprocess.run(
            prepared.command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            cwd=prepared.output_dir,
        )
    except FileNotFoundError as exc:
        raise AceBridgeError(f"ace_command_not_found:{prepared.command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        prepared.stdout_path.write_text(stdout, encoding="utf-8")
        prepared.stderr_path.write_text(stderr, encoding="utf-8")
        raise AceBridgeError(f"ace_command_timeout:{timeout_seconds}") from exc

    prepared.stdout_path.write_text(completed.stdout, encoding="utf-8")
    prepared.stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise AceBridgeError(f"ace_command_failed:{completed.returncode}")
    if not prepared.after_path.exists():
        raise AceBridgeError(f"ace_after_skillbook_missing:{prepared.after_path}")

    diff = diff_ace_skillbook_files(
        db_path=prepared.db_path,
        before_path=prepared.before_path,
        after_path=prepared.after_path,
        profile_id=prepared.profile_id,
        output_dir=prepared.proposal_output_dir,
        persist=persist,
        schema_path=schema_path,
        producer_name=producer_name,
        evidence_refs=evidence_refs,
    )
    report_path = prepared.output_dir / ACE_NATIVE_RUN_REPORT_FILENAME
    report = AceNativeRunReport(
        profile_id=prepared.profile_id,
        db_path=prepared.db_path,
        output_dir=prepared.output_dir,
        before_path=prepared.before_path,
        after_path=prepared.after_path,
        proposal_output_dir=prepared.proposal_output_dir,
        command=tuple(prepared.command),
        original_command=tuple(prepared.original_command),
        environment=dict(prepared.environment),
        handoff_path=prepared.handoff_path,
        returncode=completed.returncode,
        stdout_path=prepared.stdout_path,
        stderr_path=prepared.stderr_path,
        stdout_tail=completed.stdout[-5000:],
        stderr_tail=completed.stderr[-5000:],
        timeout_seconds=timeout_seconds,
        diff=diff,
        used_temporary_output_dir=prepared.used_temporary_output_dir,
        provider_backed=provider_backed,
        report_path=report_path,
    )
    report_path.write_text(
        json.dumps(report.to_json(include_proposals=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def prepare_native_ace_command(
    db_path: Path,
    *,
    command: Sequence[str],
    profile_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    include_inactive: bool = False,
    provider_backed: bool = False,
    timeout_seconds: int = 120,
) -> AceNativePrepareReport:
    """Prepare the cloned Skillbook and command contract without invoking ACE."""

    if not command:
        raise AceBridgeError("ace_command_required")
    if timeout_seconds <= 0:
        raise AceBridgeError("timeout_seconds_must_be_positive")

    selected_db_path = db_path.resolve()
    selected_schema_path = schema_path.resolve() if schema_path is not None else None

    initialize_database(selected_db_path)
    with connect(selected_db_path) as connection:
        selected_profile_id = profile_id or _default_profile_id(connection)
        _ensure_profile_exists(connection, selected_profile_id)

    selected_output_dir = (
        output_dir.resolve()
        if output_dir is not None
        else Path(tempfile.mkdtemp(prefix="kyoko-ace-native-")).resolve()
    )
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    used_temporary_output_dir = output_dir is None
    before_path = selected_output_dir / "before.skillbook.json"
    after_path = selected_output_dir / "after.skillbook.json"
    stdout_path = selected_output_dir / "ace-command.stdout.txt"
    stderr_path = selected_output_dir / "ace-command.stderr.txt"
    handoff_path = selected_output_dir / "ace-command.handoff.json"
    proposal_output_dir = selected_output_dir / "proposals"
    proposal_output_dir.mkdir(parents=True, exist_ok=True)

    before = export_skillbook(
        selected_db_path,
        section="all",
        include_inactive=include_inactive,
        profile_id=selected_profile_id,
    )
    before_text = json.dumps(before, indent=2, sort_keys=True) + "\n"
    before_path.write_text(before_text, encoding="utf-8")
    after_path.write_text(before_text, encoding="utf-8")
    stdout_path.write_text("", encoding="utf-8")
    stderr_path.write_text("", encoding="utf-8")

    expanded_command = expand_native_ace_command(
        command,
        before_path=before_path,
        after_path=after_path,
        output_dir=selected_output_dir,
        db_path=selected_db_path,
        profile_id=selected_profile_id,
        schema_path=selected_schema_path,
    )
    environment = _native_ace_environment(
        before_path=before_path,
        after_path=after_path,
        output_dir=selected_output_dir,
        db_path=selected_db_path,
        profile_id=selected_profile_id,
        schema_path=selected_schema_path,
    )
    skills = before.get("skills", {})
    report = AceNativePrepareReport(
        profile_id=selected_profile_id,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        before_path=before_path,
        after_path=after_path,
        proposal_output_dir=proposal_output_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        handoff_path=handoff_path,
        original_command=tuple(str(part) for part in command),
        command=tuple(expanded_command),
        environment=environment,
        timeout_seconds=timeout_seconds,
        used_temporary_output_dir=used_temporary_output_dir,
        include_inactive=include_inactive,
        schema_path=selected_schema_path,
        provider_backed=provider_backed,
        before_schema_version=str(before.get("schema_version") or ""),
        before_skill_count=len(skills) if isinstance(skills, dict) else 0,
    )
    handoff_path.write_text(json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def expand_native_ace_command(
    command: Sequence[str],
    *,
    before_path: Path,
    after_path: Path,
    output_dir: Path,
    db_path: Path,
    profile_id: str,
    schema_path: Optional[Path] = None,
) -> tuple[str, ...]:
    replacements = {
        "{before_path}": str(before_path),
        "{after_path}": str(after_path),
        "{output_dir}": str(output_dir),
        "{db_path}": str(db_path),
        "{profile_id}": profile_id,
        "{schema_path}": str(schema_path) if schema_path is not None else "",
    }
    expanded: list[str] = []
    for part in command:
        value = str(part)
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        expanded.append(value)
    return tuple(expanded)


def _native_ace_environment(
    *,
    before_path: Path,
    after_path: Path,
    output_dir: Path,
    db_path: Path,
    profile_id: str,
    schema_path: Optional[Path],
) -> dict[str, str]:
    env = {
        "KYOKO_ACE_BEFORE_PATH": str(before_path),
        "KYOKO_ACE_AFTER_PATH": str(after_path),
        "KYOKO_ACE_OUTPUT_DIR": str(output_dir),
        "KYOKO_ACE_DB_PATH": str(db_path),
        "KYOKO_ACE_PROFILE_ID": profile_id,
        "KYOKO_ACE_COMMAND_MODE": "clone_diff",
    }
    if schema_path is not None:
        env["KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH"] = str(schema_path)
    return env


def diff_ace_skillbook_files(
    *,
    db_path: Path,
    before_path: Path,
    after_path: Path,
    profile_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    persist: bool = False,
    schema_path: Optional[Path] = None,
    producer_name: str = "native_ace",
    evidence_refs: Sequence[dict[str, Any]] = (),
) -> AceDiffReport:
    before = _load_json(before_path)
    after = _load_json(after_path)
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise AceBridgeError("ace_skillbook_diff_requires_json_objects")
    return build_learning_proposals_from_ace_diff(
        db_path=db_path,
        before_skillbook=before,
        after_skillbook=after,
        profile_id=profile_id,
        output_dir=output_dir,
        persist=persist,
        schema_path=schema_path,
        producer_name=producer_name,
        evidence_refs=evidence_refs,
    )


def build_learning_proposals_from_ace_diff(
    *,
    db_path: Path,
    before_skillbook: dict[str, Any],
    after_skillbook: dict[str, Any],
    profile_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    persist: bool = False,
    schema_path: Optional[Path] = None,
    producer_name: str = "native_ace",
    evidence_refs: Sequence[dict[str, Any]] = (),
) -> AceDiffReport:
    _validate_ace_skillbook_payload(before_skillbook, label="before")
    _validate_ace_skillbook_payload(after_skillbook, label="after")
    initialize_database(db_path)

    with connect(db_path) as connection:
        selected_profile_id = profile_id or _default_profile_id(connection)
        _ensure_profile_exists(connection, selected_profile_id)
        fallback_refs = [_normalize_evidence_ref(ref) for ref in evidence_refs]
        changes, unsupported_changes = _diff_skillbooks(before_skillbook, after_skillbook)
        proposals = tuple(
            _proposal_from_change(
                connection=connection,
                profile_id=selected_profile_id,
                change=change,
                fallback_evidence_refs=fallback_refs,
                producer_name=producer_name,
            )
            for change in changes
        )

    proposal_paths: list[Path] = []
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        for proposal in proposals:
            path = output_dir / f"{proposal['id']}.json"
            path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n")
            proposal_paths.append(path)

    if persist:
        for proposal in proposals:
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=schema_path,
                require_jsonschema=False,
            )

    return AceDiffReport(
        profile_id=selected_profile_id,
        proposal_ids=tuple(str(proposal["id"]) for proposal in proposals),
        proposal_paths=tuple(proposal_paths),
        proposals=proposals,
        persisted=persist,
        unsupported_changes=tuple(unsupported_changes),
    )


def _diff_skillbooks(
    before_skillbook: dict[str, Any],
    after_skillbook: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    before_skills = _skills(before_skillbook)
    after_skills = _skills(after_skillbook)
    changes: list[dict[str, Any]] = []
    unsupported: list[str] = []

    for skill_id in sorted(after_skills):
        after = after_skills[skill_id]
        before = before_skills.get(skill_id)
        if before is None:
            if _section(after) not in {"context", "harness"}:
                unsupported.append(f"unsupported_section:{skill_id}:{_section(after)}")
                continue
            changes.append({"operation": "create", "skill_id": skill_id, "after": after})
            continue

        if _section(after) not in {"context", "harness"}:
            unsupported.append(f"unsupported_section:{skill_id}:{_section(after)}")
            continue
        if _active(before) and not _active(after):
            changes.append(
                {
                    "operation": "deactivate",
                    "skill_id": skill_id,
                    "before": before,
                    "after": after,
                }
            )
            continue
        if _skill_material_fields(before) != _skill_material_fields(after):
            changes.append(
                {
                    "operation": "update",
                    "skill_id": skill_id,
                    "before": before,
                    "after": after,
                }
            )
            continue
        if _new_occurrences(before, after):
            changes.append(
                {
                    "operation": "link_occurrence",
                    "skill_id": skill_id,
                    "before": before,
                    "after": after,
                }
            )

    for skill_id in sorted(before_skills):
        if skill_id not in after_skills:
            before = before_skills[skill_id]
            if _section(before) not in {"context", "harness"}:
                unsupported.append(f"unsupported_section:{skill_id}:{_section(before)}")
                continue
            changes.append(
                {"operation": "deactivate", "skill_id": skill_id, "before": before}
            )

    return changes, unsupported


def _proposal_from_change(
    *,
    connection: sqlite3.Connection,
    profile_id: str,
    change: dict[str, Any],
    fallback_evidence_refs: Sequence[dict[str, Any]],
    producer_name: str,
) -> dict[str, Any]:
    operation = str(change["operation"])
    skill = change.get("after") if isinstance(change.get("after"), dict) else change.get("before")
    if not isinstance(skill, dict):
        raise AceBridgeError("ace_diff_change_missing_skill")

    section = _section(skill)
    if section not in {"context", "harness"}:
        raise AceBridgeError(f"unsupported_ace_skill_section:{section}")

    evidence_refs = _evidence_refs_for_skill(
        connection,
        profile_id=profile_id,
        skill=skill,
        fallback_refs=fallback_evidence_refs,
    )
    if not evidence_refs:
        raise AceBridgeError(f"ace_diff_missing_evidence:{change['skill_id']}")

    issue = _required_text(skill.get("issue"), "issue")
    insight = _required_text(skill.get("insight") or skill.get("issue"), "insight")
    keywords = _keywords(skill)
    proposal_id = _proposal_id(profile_id=profile_id, change=change)
    now = utc_now()
    action = operation.replace("_", " ")
    title = f"ACE {action} for {section} skill"
    change_skill_id = str(change["skill_id"])
    skill_id = change_skill_id if _valid_kyoko_id(change_skill_id) else f"skill_{proposal_id}_1"

    proposal = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "id": proposal_id,
        "profile_id": profile_id,
        "producer": {
            "kind": "native_ace",
            "name": producer_name,
        },
        "state": "pending",
        "section": section,
        "title": title,
        "summary": (
            f"ACE mutated a cloned Skillbook and Kyoko converted the {operation} "
            "diff into a gated LearningProposal."
        ),
        "confidence": 0.72 if operation == "create" else 0.62,
        "evidence_refs": evidence_refs,
        "problem": {
            "issue": issue,
            "severity": "medium" if operation == "create" else "low",
            "root_cause": "Derived from a native ACE Skillbook diff.",
            "target": {
                "entity_type": "profile",
                "entity_id": profile_id,
                "name": profile_id,
            },
        },
        "insight": insight,
        "proposed_changes": [
            {
                "type": "skillbook_update",
                "operation": operation,
                "skill_id": skill_id,
                "section": section,
                "issue": issue,
                "insight": insight,
                "keywords": keywords,
                "occurrence_refs": evidence_refs,
            },
            _baseline_eval_change(section=section, operation=operation, title=title),
        ],
        "gate_expectations": {
            "requires_human_review": operation != "create",
            "requires_eval_level": "L1_repeated",
            "requires_replay": True,
            "allowed_autonomy_section": section,
            "notes": (
                "Native ACE changes are imported as proposals; Kyoko owns "
                "validation, eval/replay gates, and final writes."
            ),
        },
        "created_at": now,
    }
    return proposal


def _baseline_eval_change(*, section: str, operation: str, title: str) -> dict[str, Any]:
    side_effect_mode = "sandboxed_filesystem" if section == "harness" else "network_mocked"
    return {
        "type": "eval_spec",
        "name": f"Regression replay for {title.lower()}",
        "eval_type": "deterministic_assertion",
        "trust_level": "L0_generated",
        "side_effect_mode": side_effect_mode,
        "definition": {
            "given": "Replay the source evidence after the ACE-derived learning change.",
            "expect": "The replay target does not fail and the output trace has no failed spans.",
            "source": "native_ace_diff",
            "operation": operation,
            "assertions": [
                {"type": "target_status_not_failed"},
                {"type": "replay_no_failed_spans"},
            ],
        },
    }


def _evidence_refs_for_skill(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    skill: dict[str, Any],
    fallback_refs: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for occurrence in _occurrences(skill):
        refs.extend(_refs_from_occurrence(connection, profile_id=profile_id, occurrence=occurrence))
    if not refs:
        refs.extend(fallback_refs)
    return _dedupe_refs(refs)


def _refs_from_occurrence(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    occurrence: dict[str, Any],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    role = _evidence_role(occurrence.get("relation"))
    display_name = str(occurrence.get("display_name") or "")
    if ":" in display_name:
        entity_type, entity_id = display_name.split(":", 1)
        if _entity_exists(connection, profile_id=profile_id, entity_type=entity_type, entity_id=entity_id):
            refs.append({"entity_type": entity_type, "entity_id": entity_id, "role": role})

    for raw_trace_id in (occurrence.get("trace_id"), _trace_id_from_uid(occurrence.get("trace_uid"))):
        if not isinstance(raw_trace_id, str) or not raw_trace_id:
            continue
        for entity_type in ("run", "span", "task", "task_attempt", "handoff", "timeline_event", "skill"):
            if _entity_exists(
                connection,
                profile_id=profile_id,
                entity_type=entity_type,
                entity_id=raw_trace_id,
            ):
                refs.append({"entity_type": entity_type, "entity_id": raw_trace_id, "role": role})
                break

    return refs


def _entity_exists(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    entity_type: str,
    entity_id: str,
) -> bool:
    table = ENTITY_TABLES.get(entity_type)
    if table is None:
        return False
    if table in {"spans"}:
        row = connection.execute(
            """
            SELECT spans.id
            FROM spans
            JOIN runs ON runs.id = spans.run_id
            WHERE spans.id = ? AND runs.profile_id = ?
            """,
            (entity_id, profile_id),
        ).fetchone()
        return row is not None
    if table == "task_attempts":
        row = connection.execute(
            """
            SELECT task_attempts.id
            FROM task_attempts
            JOIN tasks ON tasks.id = task_attempts.task_id
            WHERE task_attempts.id = ? AND tasks.profile_id = ?
            """,
            (entity_id, profile_id),
        ).fetchone()
        return row is not None
    query = f"SELECT id FROM {table} WHERE id = ?"
    args: tuple[Any, ...]
    if table in {"runs", "tasks", "handoffs", "timeline_events", "skills"}:
        query += " AND profile_id = ?"
        args = (entity_id, profile_id)
    else:
        args = (entity_id,)
    return connection.execute(query, args).fetchone() is not None


def _normalize_evidence_ref(ref: dict[str, Any]) -> dict[str, Any]:
    entity_type = str(ref.get("entity_type", "")).strip()
    entity_id = str(ref.get("entity_id", "")).strip()
    role = _evidence_role(ref.get("role"))
    if not entity_type or not entity_id:
        raise AceBridgeError("invalid_fallback_evidence_ref")
    normalized = {"entity_type": entity_type, "entity_id": entity_id, "role": role}
    if isinstance(ref.get("quote_ref"), str):
        normalized["quote_ref"] = ref["quote_ref"]
    if isinstance(ref.get("note"), str):
        normalized["note"] = ref["note"]
    return normalized


def _dedupe_refs(refs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for ref in refs:
        key = (str(ref.get("entity_type")), str(ref.get("entity_id")), str(ref.get("role")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(ref))
    return deduped


def _validate_ace_skillbook_payload(payload: dict[str, Any], *, label: str) -> None:
    if str(payload.get("schema_version")) != ACE_SKILLBOOK_SCHEMA_VERSION:
        raise AceBridgeError(f"{label}_ace_skillbook_schema_version_not_supported")
    if not isinstance(payload.get("skills"), dict):
        raise AceBridgeError(f"{label}_ace_skillbook_missing_skills")
    if not isinstance(payload.get("sections"), dict):
        raise AceBridgeError(f"{label}_ace_skillbook_missing_sections")


def _skills(skillbook: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_skills = skillbook.get("skills", {})
    if not isinstance(raw_skills, dict):
        return {}
    return {
        str(skill_id): skill
        for skill_id, skill in raw_skills.items()
        if isinstance(skill, dict)
    }


def _skill_material_fields(skill: dict[str, Any]) -> dict[str, Any]:
    return {
        "section": _section(skill),
        "issue": _required_text(skill.get("issue"), "issue"),
        "insight": _required_text(skill.get("insight") or skill.get("issue"), "insight"),
        "keywords": _keywords(skill),
        "active": _active(skill),
    }


def _new_occurrences(before: dict[str, Any], after: dict[str, Any]) -> bool:
    before_signatures = {_json_signature(item) for item in _occurrences(before)}
    return any(_json_signature(item) not in before_signatures for item in _occurrences(after))


def _occurrences(skill: dict[str, Any]) -> list[dict[str, Any]]:
    raw = skill.get("occurrences", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _section(skill: dict[str, Any]) -> str:
    section = str(skill.get("section", "context")).strip().lower()
    return section or "context"


def _active(skill: dict[str, Any]) -> bool:
    return bool(skill.get("active", True))


def _keywords(skill: dict[str, Any]) -> list[str]:
    raw = skill.get("keywords", [])
    keywords: list[str] = []
    if isinstance(raw, list):
        keywords = [str(item).strip() for item in raw if str(item).strip()]
    if not keywords:
        keywords = [_section(skill)]
    return keywords


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AceBridgeError(f"ace_skill_missing_{field_name}")
    return text


def _proposal_id(*, profile_id: str, change: dict[str, Any]) -> str:
    signature = _json_signature(
        {
            "profile_id": profile_id,
            "operation": change.get("operation"),
            "skill_id": change.get("skill_id"),
            "before": _skill_material_fields(change["before"])
            if isinstance(change.get("before"), dict)
            else None,
            "after": _skill_material_fields(change["after"])
            if isinstance(change.get("after"), dict)
            else None,
        }
    )
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]
    return f"proposal_native_ace_{digest}"


def _valid_kyoko_id(value: str) -> bool:
    return re.match(r"^[a-z][a-z0-9_]*_[A-Za-z0-9][A-Za-z0-9_-]*$", value) is not None


def _trace_id_from_uid(value: Any) -> Optional[str]:
    if not isinstance(value, str) or ":" not in value:
        return None
    source_system, trace_id = value.split(":", 1)
    if source_system == "kyoko" and trace_id:
        return trace_id
    return None


def _evidence_role(value: Any) -> str:
    role = str(value or "source").strip().lower()
    return role if role in EVIDENCE_ROLES else "source"


def _default_profile_id(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at ASC, id ASC LIMIT 1").fetchone()
    if row is None:
        raise AceBridgeError("profile_required")
    return str(row["id"])


def _ensure_profile_exists(connection: sqlite3.Connection, profile_id: str) -> None:
    row = connection.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise AceBridgeError(f"profile_not_found:{profile_id}")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise AceBridgeError(f"invalid_json:{path}:{exc}") from exc


def _json_signature(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _ace_package_version() -> Optional[str]:
    try:
        return importlib.metadata.version("ace-framework")
    except importlib.metadata.PackageNotFoundError:
        return None


def _ace_source_version(ace_path: Optional[Path]) -> Optional[str]:
    if ace_path is None:
        return None
    pyproject = ace_path / "pyproject.toml"
    if not pyproject.exists():
        return None
    for line in pyproject.read_text().splitlines():
        if line.strip().startswith("version"):
            _key, _sep, value = line.partition("=")
            return value.strip().strip("\"'")
    return None


def _detect_ace_runtime(ace_path: Optional[Path]) -> dict[str, Any]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    detail: dict[str, Any] = {
        "ace_importable": False,
        "ace_import_path": None,
        "ace_module_version": None,
        "ace_import_stdout": "",
        "ace_import_stderr": "",
        "ace_import_error": None,
        "detected_api": None,
        "skillbook_import_path": None,
        "skillbook_api_error": None,
    }
    try:
        with _temporary_ace_import_path(ace_path):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                ace_module = importlib.import_module("ace")
                detail.update(
                    {
                        "ace_importable": True,
                        "ace_import_path": str(getattr(ace_module, "__file__", "")) or None,
                        "ace_module_version": getattr(ace_module, "__version__", None),
                    }
                )
                try:
                    skillbook_module = importlib.import_module("ace.core.skillbook")
                    getattr(skillbook_module, "Skillbook")
                    detail.update(
                        {
                            "detected_api": "skillbook_v2",
                            "skillbook_import_path": str(
                                getattr(skillbook_module, "__file__", "")
                            )
                            or None,
                        }
                    )
                except Exception as exc:
                    detail["skillbook_api_error"] = str(exc)
                    if hasattr(ace_module, "Playbook"):
                        detail["detected_api"] = "legacy_playbook"
    except Exception as exc:  # pragma: no cover - import failures are environment-specific.
        detail["ace_import_error"] = str(exc)
    detail["ace_import_stdout"] = stdout.getvalue()
    detail["ace_import_stderr"] = stderr.getvalue()
    return detail


@contextmanager
def _temporary_ace_import_path(ace_path: Optional[Path]) -> Iterator[None]:
    original_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "ace" or name.startswith("ace.")
    }
    for name in saved_modules:
        sys.modules.pop(name, None)
    if ace_path is not None:
        sys.path.insert(0, str(ace_path))
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "ace" or name.startswith("ace."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path[:] = original_path
