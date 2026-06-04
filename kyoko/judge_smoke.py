from __future__ import annotations

import json
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .bundled_assets import AssetError, bundled_asset_path, load_bundled_json
from .checks import (
    BEGIN_JUDGE_RESULT_BLOCK,
    END_JUDGE_RESULT_BLOCK,
    CheckError,
    build_judge_request,
    generate_checks_for_proposal,
    run_judge_command,
)
from .proposals import ProposalError, list_learning_proposals, submit_learning_proposal_payload
from .storage import StorageError, ingest_source_payload, initialize_database


JUDGE_SMOKE_PROPOSAL_ID = "proposal_context_timeout_judge_smoke_001"


class JudgeSmokeError(Exception):
    """Raised when the judge-command smoke cannot complete."""


@dataclass(frozen=True)
class JudgeSmokeReport:
    db_path: Path
    output_dir: Path
    profile_id: str
    proposal_id: str
    check_spec_id: str
    request_path: Path
    handoff_path: Path
    result_path: Path
    raw_output_path: Path
    command: tuple[str, ...]
    prepare_only: bool
    used_demo_database: bool
    proposal_created: bool
    external_command_invoked: bool
    provider_backed: bool
    external_model_invoked: bool
    check_run_id: Optional[str]
    check_status: Optional[str]
    promoted_trust_level: Optional[str]
    judgment: Optional[dict[str, Any]]
    passed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "judge_command_smoke",
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "profile_id": self.profile_id,
            "proposal_id": self.proposal_id,
            "check_spec_id": self.check_spec_id,
            "request_path": str(self.request_path),
            "handoff_path": str(self.handoff_path),
            "result_path": str(self.result_path),
            "raw_output_path": str(self.raw_output_path),
            "command": list(self.command),
            "shell_command": _shell_command(self.command),
            "prepare_only": self.prepare_only,
            "used_demo_database": self.used_demo_database,
            "proposal_created": self.proposal_created,
            "external_command_invoked": self.external_command_invoked,
            "provider_backed": self.provider_backed,
            "external_model_invoked": self.external_model_invoked,
            "check_run_id": self.check_run_id,
            "check_status": self.check_status,
            "promoted_trust_level": self.promoted_trust_level,
            "judgment": self.judgment,
            "passed": self.passed,
        }


def run_judge_smoke(
    *,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    command: Optional[Sequence[str]] = None,
    prepare_only: bool = False,
    provider_backed: bool = False,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 120,
) -> JudgeSmokeReport:
    selected_output_dir, selected_db_path, used_demo_database = _prepare_judge_smoke_workspace(
        db_path=db_path,
        output_dir=output_dir,
    )
    seed = _seed_judge_smoke_database(
        db_path=selected_db_path,
        schema_path=schema_path,
    )
    check_spec_id = seed["check_spec_id"]
    profile_id = seed["profile_id"]
    selected_command = tuple(str(part) for part in (command or ()))
    request_path = selected_output_dir / "judge-request.json"
    raw_output_path = selected_output_dir / "judge-command-output.txt"
    result_path = selected_output_dir / "judge-result.json"
    handoff_path = selected_output_dir / "judge-command.handoff.json"

    if prepare_only:
        request = build_judge_request(
            db_path=selected_db_path,
            check_spec_id=check_spec_id,
            redaction_consumer="judge:command",
        )
        request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
        _write_handoff(
            handoff_path=handoff_path,
            db_path=selected_db_path,
            output_dir=selected_output_dir,
            profile_id=profile_id,
            check_spec_id=check_spec_id,
            command=selected_command,
            request_path=request_path,
            result_path=result_path,
            raw_output_path=raw_output_path,
            provider_backed=provider_backed,
            prepare_only=True,
        )
        return JudgeSmokeReport(
            db_path=selected_db_path,
            output_dir=selected_output_dir,
            profile_id=profile_id,
            proposal_id=JUDGE_SMOKE_PROPOSAL_ID,
            check_spec_id=check_spec_id,
            request_path=request_path,
            handoff_path=handoff_path,
            result_path=result_path,
            raw_output_path=raw_output_path,
            command=selected_command,
            prepare_only=True,
            used_demo_database=used_demo_database,
            proposal_created=bool(seed["proposal_created"]),
            external_command_invoked=False,
            provider_backed=provider_backed,
            external_model_invoked=False,
            check_run_id=None,
            check_status="prepared",
            promoted_trust_level=None,
            judgment=None,
            passed=True,
        )

    if not selected_command:
        raise JudgeSmokeError("judge_command_required")

    report = run_judge_command(
        db_path=selected_db_path,
        check_spec_id=check_spec_id,
        output_dir=selected_output_dir,
        command=selected_command,
        timeout_seconds=timeout_seconds,
    )
    _write_handoff(
        handoff_path=handoff_path,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        profile_id=profile_id,
        check_spec_id=check_spec_id,
        command=selected_command,
        request_path=report.request_path,
        result_path=report.result_path,
        raw_output_path=report.raw_output_path,
        provider_backed=provider_backed,
        prepare_only=False,
    )
    passed = report.check_run.status == "passed"
    return JudgeSmokeReport(
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        profile_id=report.profile_id,
        proposal_id=report.proposal_id or JUDGE_SMOKE_PROPOSAL_ID,
        check_spec_id=report.check_spec_id,
        request_path=report.request_path,
        handoff_path=handoff_path,
        result_path=report.result_path,
        raw_output_path=report.raw_output_path,
        command=selected_command,
        prepare_only=False,
        used_demo_database=used_demo_database,
        proposal_created=bool(seed["proposal_created"]),
        external_command_invoked=True,
        provider_backed=provider_backed,
        external_model_invoked=provider_backed,
        check_run_id=report.check_run.check_run_id,
        check_status=report.check_run.status,
        promoted_trust_level=report.check_run.promoted_trust_level,
        judgment=report.judgment,
        passed=passed,
    )


def _prepare_judge_smoke_workspace(
    *,
    db_path: Optional[Path],
    output_dir: Optional[Path],
) -> tuple[Path, Path, bool]:
    selected_output_dir = output_dir or Path(tempfile.mkdtemp(prefix="kyoko-judge-smoke-"))
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    selected_db_path = db_path or selected_output_dir / "smoke.db"
    initialize_database(selected_db_path)
    return selected_output_dir, selected_db_path, db_path is None


def _seed_judge_smoke_database(*, db_path: Path, schema_path: Optional[Path]) -> dict[str, Any]:
    try:
        source_payload = load_bundled_json("source-events/hermes-news-research-minimal.json")
        proposal_payload = _judge_smoke_proposal_payload()
    except AssetError as exc:
        raise JudgeSmokeError(str(exc)) from exc

    try:
        ingest_report = ingest_source_payload(
            db_path=db_path,
            fixture=source_payload,
            source_label="judge-smoke",
        )
        existing = {proposal["id"] for proposal in list_learning_proposals(db_path)}
        proposal_created = False
        if JUDGE_SMOKE_PROPOSAL_ID not in existing:
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal_payload,
                schema_path=_schema_path(schema_path),
            )
            proposal_created = True
        check_report = generate_checks_for_proposal(
            db_path=db_path,
            proposal_id=JUDGE_SMOKE_PROPOSAL_ID,
        )
    except (CheckError, ProposalError, StorageError) as exc:
        raise JudgeSmokeError(str(exc)) from exc

    check_spec_ids = tuple(check_report.check_spec_ids + check_report.existing_check_spec_ids)
    if not check_spec_ids:
        raise JudgeSmokeError(f"judge_smoke_check_not_available:{JUDGE_SMOKE_PROPOSAL_ID}")
    return {
        "profile_id": ingest_report.profile_id,
        "proposal_created": proposal_created,
        "check_spec_id": check_spec_ids[0],
    }


def _judge_smoke_proposal_payload() -> dict[str, Any]:
    proposal = json.loads(json.dumps(load_bundled_json("learning-proposals/valid-context-proposal.json")))
    proposal["id"] = JUDGE_SMOKE_PROPOSAL_ID
    proposal["title"] = "Judge smoke review for recovered source handoff"
    proposal["summary"] = "Smoke proposal used to verify explicit judge-command handoff evidence."
    producer = proposal.get("producer")
    if isinstance(producer, dict):
        producer["session_id"] = JUDGE_SMOKE_PROPOSAL_ID

    target = {
        "entity_type": "span",
        "entity_id": "span_fetch_timeout_001",
        "source": "judge_smoke",
        "role": "failure",
    }
    evidence_refs = proposal.get("evidence_refs") if isinstance(proposal.get("evidence_refs"), list) else []
    changes = proposal.get("proposed_changes") if isinstance(proposal.get("proposed_changes"), list) else []
    for change in changes:
        if not isinstance(change, dict) or change.get("type") != "check_spec":
            continue
        change["name"] = "judge smoke: recovered source evidence satisfies rubric"
        change["check_type"] = "judge"
        change["side_effect_mode"] = "none"
        change["definition"] = {
            "rubric": (
                "Pass if the target failure and proposal evidence are sufficient "
                "to justify the recovered-source retry guidance."
            ),
            "target": target,
            "evidence_refs": evidence_refs,
        }
        break
    return proposal


def _schema_path(schema_path: Optional[Path]) -> Optional[Path]:
    if schema_path is not None:
        return schema_path
    try:
        return bundled_asset_path("schemas/learning-proposal.schema.json")
    except AssetError:
        return None


def _write_handoff(
    *,
    handoff_path: Path,
    db_path: Path,
    output_dir: Path,
    profile_id: str,
    check_spec_id: str,
    command: Sequence[str],
    request_path: Path,
    result_path: Path,
    raw_output_path: Path,
    provider_backed: bool,
    prepare_only: bool,
) -> None:
    payload = {
        "schema_version": "kyoko.judge_smoke_handoff.v1",
        "db_path": str(db_path),
        "output_dir": str(output_dir),
        "profile_id": profile_id,
        "check_spec_id": check_spec_id,
        "command": list(command),
        "shell_command": _shell_command(command),
        "environment": {
            "KYOKO_JUDGE_REQUEST_PATH": str(request_path),
            "KYOKO_CHECK_SPEC_ID": check_spec_id,
            "KYOKO_PROFILE_ID": profile_id,
            "KYOKO_JUDGE_RESULT_BLOCK_BEGIN": BEGIN_JUDGE_RESULT_BLOCK,
            "KYOKO_JUDGE_RESULT_BLOCK_END": END_JUDGE_RESULT_BLOCK,
        },
        "artifacts": {
            "request_path": str(request_path),
            "result_path": str(result_path),
            "raw_output_path": str(raw_output_path),
        },
        "prepare_only": prepare_only,
        "provider_backed": provider_backed,
        "external_model_invoked": False if prepare_only else provider_backed,
    }
    handoff_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _shell_command(command: Sequence[str]) -> Optional[str]:
    if not command:
        return None
    return " ".join(shlex.quote(str(part)) for part in command)
