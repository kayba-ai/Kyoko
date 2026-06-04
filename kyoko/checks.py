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

from .blobs import put_json_blob
from .redaction import (
    RedactionError,
    get_redaction_policy,
    redact_evidence_bundle,
)
from .storage import IngestReport, StorageError, connect, ingest_source_payload, initialize_database, utc_now


FAILURE_STATUSES = {"failed", "timed_out", "cancelled", "errored"}
SAFE_REPLAY_SIDE_EFFECT_MODES = {
    "none",
    "filesystem_read",
    "sandboxed_filesystem",
    "network_mocked",
}
ALLOWED_ACTUAL_SIDE_EFFECT_MODES_BY_REQUEST = {
    "none": {"none"},
    "filesystem_read": {"none", "filesystem_read"},
    "sandboxed_filesystem": {"none", "filesystem_read", "sandboxed_filesystem"},
    "network_mocked": {"none", "network_mocked"},
}
EXECUTABLE_CHECK_TYPES = ("deterministic_assertion", "judge", "regression_replay", "smoke_run")
GATEABLE_CHECK_TYPES = ("deterministic_assertion", "regression_replay")
CHECK_TRUST_LEVELS = ("L0_generated", "L1_repeated", "L2_regression", "L3_human_approved")
REPLAY_MODES = ("dry_run", "sandbox", "live")
SCHEMA_SIDE_EFFECT_MODES = (
    "none",
    "filesystem_read",
    "sandboxed_filesystem",
    "network_mocked",
    "live_network",
    "unknown",
)
JUDGE_PASS_VERDICTS = {"pass", "passed", "accept", "accepted", "meets_rubric"}
JUDGE_FAIL_VERDICTS = {"fail", "failed", "reject", "rejected", "does_not_meet_rubric"}
DETERMINISTIC_ASSERTION_DEFINITIONS: dict[str, dict[str, Any]] = {
    "target_status_not_failed": {
        "name": "target_status_not_failed",
        "description": "Check that the baseline target is not failed, or that a replay-mapped target improves from failed to not failed.",
        "requires_replay": False,
    },
    "replay_target_field_equals": {
        "name": "replay_target_field_equals",
        "description": "Check a decoded field on the replay target mapped from the baseline evidence.",
        "requires_replay": True,
    },
    "replay_entity_field_equals": {
        "name": "replay_entity_field_equals",
        "description": "Find a replay output entity and compare a decoded field.",
        "requires_replay": True,
    },
    "replay_run_status_equals": {
        "name": "replay_run_status_equals",
        "description": "Check the replay output run status.",
        "requires_replay": True,
    },
    "replay_no_failed_spans": {
        "name": "replay_no_failed_spans",
        "description": "Check that the replay output run has no failed spans.",
        "requires_replay": True,
    },
    "replay_span_count_at_least": {
        "name": "replay_span_count_at_least",
        "description": "Check that the replay output run has at least the requested number of spans.",
        "requires_replay": True,
    },
    "replay_handoff_count_at_least": {
        "name": "replay_handoff_count_at_least",
        "description": "Check that the replay output run has at least the requested number of handoffs.",
        "requires_replay": True,
    },
}
ASSERTION_PRESET_DEFINITIONS: dict[str, dict[str, Any]] = {
    "replay_success_shape": {
        "name": "replay_success_shape",
        "description": "Check that the replay output run succeeded, has no failed spans, and has enough spans.",
        "assertions": [
            "replay_run_status_equals",
            "replay_no_failed_spans",
            "replay_span_count_at_least",
        ],
        "options": [
            {
                "name": "expected_run_status",
                "aliases": ["replay_run_status"],
                "type": "string",
                "default": "succeeded",
            },
            {
                "name": "min_spans",
                "aliases": ["minimum_spans"],
                "type": "integer",
                "default": 1,
                "minimum": 0,
            },
        ],
        "gateable_check_types": ["deterministic_assertion", "regression_replay"],
    },
    "replay_handoff_present": {
        "name": "replay_handoff_present",
        "description": "Check that the replay output run contains at least one handoff.",
        "assertions": ["replay_handoff_count_at_least"],
        "options": [
            {
                "name": "min_handoffs",
                "aliases": ["minimum_handoffs"],
                "type": "integer",
                "default": 1,
                "minimum": 0,
            }
        ],
        "gateable_check_types": ["deterministic_assertion", "regression_replay"],
    },
}
SUPPORTED_ASSERTION_PRESETS = tuple(ASSERTION_PRESET_DEFINITIONS)
BEGIN_REPLAY_RESULT_BLOCK = "BEGIN_KYOKO_REPLAY_RESULT_JSON"
END_REPLAY_RESULT_BLOCK = "END_KYOKO_REPLAY_RESULT_JSON"
BEGIN_JUDGE_RESULT_BLOCK = "BEGIN_KYOKO_JUDGE_RESULT_JSON"
END_JUDGE_RESULT_BLOCK = "END_KYOKO_JUDGE_RESULT_JSON"


class CheckError(Exception):
    """Raised when check or replay work cannot be performed."""


@dataclass(frozen=True)
class CheckGenerationReport:
    proposal_id: str
    profile_id: str
    check_spec_ids: tuple[str, ...]
    existing_check_spec_ids: tuple[str, ...]


@dataclass(frozen=True)
class ReplayRunReport:
    replay_run_id: str
    profile_id: str
    proposal_id: Optional[str]
    check_spec_id: str
    source_run_id: Optional[str]
    mode: str
    side_effect_mode: str
    status: str
    result: dict[str, Any]


@dataclass(frozen=True)
class CheckRunReport:
    check_run_id: str
    profile_id: str
    proposal_id: Optional[str]
    check_spec_id: str
    replay_run_id: Optional[str]
    status: str
    result: dict[str, Any]
    promoted_trust_level: Optional[str]


@dataclass(frozen=True)
class CheckSpecLockReport:
    check_spec_id: str
    profile_id: str
    human_locked: bool
    reason: Optional[str]
    actor_agent_identity_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "check_spec_id": self.check_spec_id,
            "profile_id": self.profile_id,
            "human_locked": self.human_locked,
            "reason": self.reason,
            "actor_agent_identity_id": self.actor_agent_identity_id,
        }


@dataclass(frozen=True)
class CheckSpecApprovalReport:
    check_spec_id: str
    profile_id: str
    previous_trust_level: str
    trust_level: str
    reason: Optional[str]
    actor_agent_identity_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "check_spec_id": self.check_spec_id,
            "profile_id": self.profile_id,
            "previous_trust_level": self.previous_trust_level,
            "trust_level": self.trust_level,
            "reason": self.reason,
            "actor_agent_identity_id": self.actor_agent_identity_id,
        }


@dataclass(frozen=True)
class ReplayCompletionReport:
    replay_run_id: str
    profile_id: str
    check_spec_id: str
    output_run_id: str
    status: str
    result: dict[str, Any]
    ingest_report: IngestReport


@dataclass(frozen=True)
class ReplayCommandReport:
    replay_run_id: str
    profile_id: str
    check_spec_id: str
    request_path: Path
    result_path: Path
    raw_output_path: Path
    completion: ReplayCompletionReport
    check_run: Optional[CheckRunReport]


@dataclass(frozen=True)
class JudgeCommandReport:
    profile_id: str
    proposal_id: Optional[str]
    check_spec_id: str
    request_path: Path
    result_path: Path
    raw_output_path: Path
    judgment: dict[str, Any]
    check_run: CheckRunReport


def list_assertion_presets() -> list[dict[str, Any]]:
    return [
        json.loads(json.dumps(ASSERTION_PRESET_DEFINITIONS[name], sort_keys=True))
        for name in SUPPORTED_ASSERTION_PRESETS
    ]


def list_check_capabilities() -> dict[str, Any]:
    return {
        "check_types": [
            {
                "name": "deterministic_assertion",
                "storage": True,
                "executable": True,
                "gateable": True,
                "requires_replay": False,
                "auto_promotes_trust": ["L1_repeated", "L2_regression"],
                "notes": "Runs concrete assertions over stored source evidence and optional completed replay evidence.",
            },
            {
                "name": "judge",
                "storage": True,
                "executable": True,
                "gateable": False,
                "requires_replay": False,
                "auto_promotes_trust": [],
                "notes": "Executes recorded pass/fail verdicts only. Live/provider judges must use explicit judge-command capture first.",
            },
            {
                "name": "regression_replay",
                "storage": True,
                "executable": True,
                "gateable": True,
                "requires_replay": True,
                "auto_promotes_trust": ["L2_regression"],
                "notes": "Requires completed bounded replay evidence and fail-before/pass-after proof.",
            },
            {
                "name": "smoke_run",
                "storage": True,
                "executable": True,
                "gateable": False,
                "requires_replay": False,
                "auto_promotes_trust": [],
                "notes": "Runs informational checks over an already-recorded source run or replay output run.",
            },
        ],
        "executable_check_types": list(EXECUTABLE_CHECK_TYPES),
        "gateable_check_types": list(GATEABLE_CHECK_TYPES),
        "trust_levels": [
            {"name": "L0_generated", "gateable": False, "set_by": "proposal_or_generation"},
            {"name": "L1_repeated", "gateable": True, "set_by": "automatic_repeated_deterministic_results"},
            {"name": "L2_regression", "gateable": True, "set_by": "automatic_fail_before_pass_after_replay"},
            {"name": "L3_human_approved", "gateable": True, "set_by": "explicit_human_approval"},
        ],
        "deterministic_assertions": [
            json.loads(json.dumps(DETERMINISTIC_ASSERTION_DEFINITIONS[name], sort_keys=True))
            for name in DETERMINISTIC_ASSERTION_DEFINITIONS
        ],
        "assertion_presets": list_assertion_presets(),
        "judge": {
            "backend": "recorded_judgment",
            "invokes_model": False,
            "gateable": False,
            "external_command_supported": True,
            "external_command_invokes_model": "operator_controlled",
            "handoff_surfaces": [
                "cli:judge-command",
                "api:POST /api/judge-command",
                "dashboard:Run judge",
                "mcp:kyoko_run_judge_command",
            ],
            "recommended_use": [
                "subjective_quality_review",
                "rubric_scoring",
                "deterministic_assertion_gap",
            ],
            "autonomy_gate": "unsupported",
            "stdout_begin": BEGIN_JUDGE_RESULT_BLOCK,
            "stdout_end": END_JUDGE_RESULT_BLOCK,
            "pass_verdicts": sorted(JUDGE_PASS_VERDICTS),
            "fail_verdicts": sorted(JUDGE_FAIL_VERDICTS),
        },
        "replay": {
            "modes": list(REPLAY_MODES),
            "live_mode_supported": False,
            "side_effect_modes": [
                {
                    "name": mode,
                    "safe": mode in SAFE_REPLAY_SIDE_EFFECT_MODES,
                    "accepted_by_runtime": mode in SAFE_REPLAY_SIDE_EFFECT_MODES,
                }
                for mode in SCHEMA_SIDE_EFFECT_MODES
            ],
            "safe_side_effect_modes": [
                mode for mode in SCHEMA_SIDE_EFFECT_MODES if mode in SAFE_REPLAY_SIDE_EFFECT_MODES
            ],
            "unsafe_side_effect_modes": [
                mode for mode in SCHEMA_SIDE_EFFECT_MODES if mode not in SAFE_REPLAY_SIDE_EFFECT_MODES
            ],
        },
    }


def generate_checks_for_proposal(*, db_path: Path, proposal_id: str) -> CheckGenerationReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        proposal = _get_proposal(connection, proposal_id)
        profile_id = str(proposal["profile_id"])
        _ensure_check_write_allowed(connection, profile_id)
        _ensure_kyoko_source(connection, profile_id, {"checks": True, "replay": True})

        changes = _json_loads(proposal["proposed_changes_json"], [])
        if not isinstance(changes, list):
            changes = []
        check_changes = [
            change for change in changes if isinstance(change, dict) and change.get("type") == "check_spec"
        ]
        if not check_changes:
            check_changes = _fallback_check_changes(proposal, changes)
        if not check_changes:
            raise CheckError(f"no_check_spec_changes:{proposal_id}")

        created_ids: list[str] = []
        existing_ids: list[str] = []
        for index, change in enumerate(check_changes, start=1):
            check_spec_id = _check_spec_id(proposal_id, index, change)
            if _row_exists(connection, "check_specs", check_spec_id):
                existing_ids.append(check_spec_id)
                continue

            now = utc_now()
            target = _target_for_check(proposal, change)
            definition = _definition_for_check(proposal, change)
            connection.execute(
                """
                INSERT INTO check_specs (
                  id,
                  profile_id,
                  proposal_id,
                  name,
                  check_type,
                  trust_level,
                  side_effect_mode,
                  target_json,
                  definition_json,
                  status,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    check_spec_id,
                    profile_id,
                    proposal_id,
                    _required_string(change, "name"),
                    _required_string(change, "check_type"),
                    _required_string(change, "trust_level"),
                    _required_string(change, "side_effect_mode"),
                    _json_dumps(target),
                    _json_dumps(definition),
                    "active",
                    now,
                    now,
                ),
            )
            _insert_timeline_event(
                connection,
                event_id=f"event_{check_spec_id}_created",
                profile_id=profile_id,
                entity_type="check_spec",
                entity_id=check_spec_id,
                kind="check_spec_created",
                at=now,
                metadata={"proposal_id": proposal_id, "trust_level": change["trust_level"]},
            )
            created_ids.append(check_spec_id)

    return CheckGenerationReport(
        proposal_id=proposal_id,
        profile_id=profile_id,
        check_spec_ids=tuple(created_ids),
        existing_check_spec_ids=tuple(existing_ids),
    )


def create_replay_run(
    *,
    db_path: Path,
    check_spec_id: str,
    mode: str = "dry_run",
    side_effect_mode: Optional[str] = None,
    source_run_id: Optional[str] = None,
) -> ReplayRunReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        profile_id = str(check_spec["profile_id"])
        proposal_id = check_spec["proposal_id"] if check_spec["proposal_id"] is not None else None
        _ensure_kyoko_source(connection, profile_id, {"checks": True, "replay": True})
        selected_side_effect_mode = side_effect_mode or str(check_spec["side_effect_mode"])
        _validate_replay_boundary(mode=mode, side_effect_mode=selected_side_effect_mode)

        target = _json_loads(check_spec["target_json"], {})
        selected_source_run_id = source_run_id or _source_run_for_target(connection, target)
        if selected_source_run_id is not None and not _row_exists(connection, "runs", selected_source_run_id):
            raise CheckError(f"source_run_not_found:{selected_source_run_id}")

        now = utc_now()
        replay_run_id = _next_numbered_id(
            connection,
            table="replay_runs",
            prefix=f"replay_{check_spec_id}",
            where_column="check_spec_id",
            where_value=check_spec_id,
        )
        result = {
            "executed_agent": False,
            "mode": mode,
            "requested_side_effect_mode": selected_side_effect_mode,
            "actual_side_effect_mode": "none",
            "source_run_id": selected_source_run_id,
            "note": "v0 dry-run replay records the replay request and verifies source evidence without re-invoking tools.",
        }
        connection.execute(
            """
            INSERT INTO replay_runs (
              id,
              profile_id,
              proposal_id,
              check_spec_id,
              source_run_id,
              task_attempt_id,
              mode,
              side_effect_mode,
              status,
              started_at,
              ended_at,
              input_ref,
              output_ref,
              result_json,
              artifact_refs_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                replay_run_id,
                profile_id,
                proposal_id,
                check_spec_id,
                selected_source_run_id,
                _task_attempt_for_source_run(connection, selected_source_run_id),
                mode,
                selected_side_effect_mode,
                "passed",
                now,
                now,
                selected_source_run_id,
                None,
                _json_dumps(result),
                "[]",
                now,
                now,
            ),
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{replay_run_id}_completed",
            profile_id=profile_id,
            entity_type="replay_run",
            entity_id=replay_run_id,
            kind="replay_run_completed",
            at=now,
            metadata={"check_spec_id": check_spec_id, "mode": mode},
        )

    return ReplayRunReport(
        replay_run_id=replay_run_id,
        profile_id=profile_id,
        proposal_id=str(proposal_id) if proposal_id is not None else None,
        check_spec_id=check_spec_id,
        source_run_id=selected_source_run_id,
        mode=mode,
        side_effect_mode=selected_side_effect_mode,
        status="passed",
        result=result,
    )


def run_check(
    *,
    db_path: Path,
    check_spec_id: str,
    replay_run_id: Optional[str] = None,
) -> CheckRunReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        profile_id = str(check_spec["profile_id"])
        proposal_id = check_spec["proposal_id"] if check_spec["proposal_id"] is not None else None
        _ensure_kyoko_source(connection, profile_id, {"checks": True, "replay": True})

        replay_row = None
        if replay_run_id is not None:
            replay_row = _get_replay_run(connection, replay_run_id)
            if str(replay_row["check_spec_id"]) != check_spec_id:
                raise CheckError(f"replay_check_mismatch:{replay_run_id}:{check_spec_id}")

        now = utc_now()
        check_run_id = _next_numbered_id(
            connection,
            table="check_runs",
            prefix=f"checkrun_{check_spec_id}",
            where_column="check_spec_id",
            where_value=check_spec_id,
        )
        status, result = _evaluate(connection, check_spec, replay_row)
        connection.execute(
            """
            INSERT INTO check_runs (
              id,
              profile_id,
              check_spec_id,
              proposal_id,
              replay_run_id,
              status,
              started_at,
              ended_at,
              result_json,
              artifact_refs_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                check_run_id,
                profile_id,
                check_spec_id,
                proposal_id,
                replay_run_id,
                status,
                now,
                now,
                _json_dumps(result),
                "[]",
                now,
                now,
            ),
        )
        promoted_trust_level = _maybe_promote_trust_level(connection, check_spec, status, result, now)
        _insert_timeline_event(
            connection,
            event_id=f"event_{check_run_id}_{status}",
            profile_id=profile_id,
            entity_type="check_run",
            entity_id=check_run_id,
            kind=f"check_run_{status}",
            at=now,
            metadata={
                "check_spec_id": check_spec_id,
                "replay_run_id": replay_run_id,
                "promoted_trust_level": promoted_trust_level,
            },
        )

    return CheckRunReport(
        check_run_id=check_run_id,
        profile_id=profile_id,
        proposal_id=str(proposal_id) if proposal_id is not None else None,
        check_spec_id=check_spec_id,
        replay_run_id=replay_run_id,
        status=status,
        result=result,
        promoted_trust_level=promoted_trust_level,
    )


def complete_replay_from_fixture(
    *,
    db_path: Path,
    replay_run_id: str,
    fixture_path: Path,
) -> ReplayCompletionReport:
    initialize_database(db_path)
    return complete_replay_from_payload(
        db_path=db_path,
        replay_run_id=replay_run_id,
        fixture=_load_json(fixture_path),
        source_label=str(fixture_path),
    )


def complete_replay_from_payload(
    *,
    db_path: Path,
    replay_run_id: str,
    fixture: dict[str, Any],
    source_label: str,
) -> ReplayCompletionReport:
    initialize_database(db_path)
    replay_payload = fixture.get("replay")
    if not isinstance(replay_payload, dict):
        raise CheckError(f"{source_label}: missing replay object")

    expected_replay_run_id = replay_payload.get("replay_run_id")
    if isinstance(expected_replay_run_id, str) and expected_replay_run_id != replay_run_id:
        raise CheckError(f"replay_fixture_id_mismatch:{expected_replay_run_id}:{replay_run_id}")

    output_run_id = replay_payload.get("output_run_id")
    if not isinstance(output_run_id, str) or not output_run_id:
        raise CheckError("replay_output_run_id_required")

    actual_side_effect_mode = replay_payload.get("actual_side_effect_mode", "unknown")
    if actual_side_effect_mode not in SAFE_REPLAY_SIDE_EFFECT_MODES:
        raise CheckError(f"unsafe_replay_side_effect_mode:{actual_side_effect_mode}")

    with connect(db_path) as connection:
        replay_row = _get_replay_run(connection, replay_run_id)
        profile_id = str(replay_row["profile_id"])
        check_spec_id = str(replay_row["check_spec_id"])
        requested_side_effect_mode = str(replay_row["side_effect_mode"])
        _validate_actual_replay_side_effect_mode(
            requested_side_effect_mode=requested_side_effect_mode,
            actual_side_effect_mode=str(actual_side_effect_mode),
        )
        if fixture.get("profile", {}).get("id") != profile_id:
            raise CheckError(f"replay_profile_mismatch:{source_label}:{profile_id}")

    ingest_report = ingest_source_payload(
        db_path=db_path,
        fixture=fixture,
        source_label=source_label,
    )

    with connect(db_path) as connection:
        replay_row = _get_replay_run(connection, replay_run_id)
        if not _row_exists(connection, "runs", output_run_id):
            raise CheckError(f"replay_output_run_not_found:{output_run_id}")
        status = str(replay_payload.get("status") or "passed")
        if status not in {"passed", "failed", "errored", "cancelled"}:
            raise CheckError(f"unsupported_replay_completion_status:{status}")

        now = utc_now()
        previous_result = _json_loads(replay_row["result_json"], {})
        result = dict(previous_result) if isinstance(previous_result, dict) else {}
        result.update(
            {
                "executed_agent": bool(replay_payload.get("executed_agent", True)),
                "actual_side_effect_mode": actual_side_effect_mode,
                "output_run_id": output_run_id,
                "target_map": replay_payload.get("target_map", {}),
                "note": replay_payload.get("note", "controlled replay fixture completed"),
            }
        )
        connection.execute(
            """
            UPDATE replay_runs
            SET status = ?,
                ended_at = ?,
                output_ref = ?,
                result_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, now, output_run_id, _json_dumps(result), now, replay_run_id),
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{replay_run_id}_fixture_completed",
            profile_id=str(replay_row["profile_id"]),
            entity_type="replay_run",
            entity_id=replay_run_id,
            kind="replay_run_fixture_completed",
            at=now,
            metadata={"check_spec_id": replay_row["check_spec_id"], "output_run_id": output_run_id},
        )

    return ReplayCompletionReport(
        replay_run_id=replay_run_id,
        profile_id=str(replay_row["profile_id"]),
        check_spec_id=str(replay_row["check_spec_id"]),
        output_run_id=output_run_id,
        status=status,
        result=result,
        ingest_report=ingest_report,
    )


def complete_replay_from_server_response(
    *,
    db_path: Path,
    replay_run_id: str,
    response: dict[str, Any],
    source_label: str,
) -> ReplayCompletionReport:
    initialize_database(db_path)
    _validate_replay_server_response_identity(
        response=response,
        replay_run_id=replay_run_id,
        source_label=source_label,
    )
    if "replay" in response:
        return complete_replay_from_payload(
            db_path=db_path,
            replay_run_id=replay_run_id,
            fixture=response,
            source_label=source_label,
        )

    output_run_id = response.get("run_id") or response.get("output_run_id")
    if not isinstance(output_run_id, str) or not output_run_id:
        raise CheckError(f"{source_label}: replay server response missing run_id")

    actual_side_effect_mode = (
        response.get("actual_side_effect_mode")
        or response.get("side_effect_mode")
        or response.get("requested_side_effect_mode")
        or "unknown"
    )
    if actual_side_effect_mode not in SAFE_REPLAY_SIDE_EFFECT_MODES:
        raise CheckError(f"unsafe_replay_side_effect_mode:{actual_side_effect_mode}")

    raw_status = str(response.get("status") or "passed")
    status = {
        "done": "passed",
        "ok": "passed",
        "success": "passed",
        "succeeded": "passed",
    }.get(raw_status, raw_status)
    if status not in {"passed", "failed", "errored", "cancelled"}:
        raise CheckError(f"unsupported_replay_completion_status:{status}")
    if status != "passed":
        raise CheckError(f"replay_server_returned_status:{status}")

    with connect(db_path) as connection:
        replay_row = _get_replay_run(connection, replay_run_id)
        requested_side_effect_mode = str(replay_row["side_effect_mode"])
        _validate_actual_replay_side_effect_mode(
            requested_side_effect_mode=requested_side_effect_mode,
            actual_side_effect_mode=str(actual_side_effect_mode),
        )
        if not _row_exists(connection, "runs", output_run_id):
            raise CheckError(f"replay_output_run_not_found:{output_run_id}")

        profile_id = str(replay_row["profile_id"])
        check_spec_id = str(replay_row["check_spec_id"])
    response_blob = put_json_blob(
        db_path=db_path,
        payload=response,
        kind="replay_server_response",
        profile_id=profile_id,
        redaction_mode="redacted",
        metadata={
            "replay_run_id": replay_run_id,
            "check_spec_id": check_spec_id,
            "output_run_id": output_run_id,
            "source_label": source_label,
        },
    )

    with connect(db_path) as connection:
        replay_row = _get_replay_run(connection, replay_run_id)
        now = utc_now()
        previous_result = _json_loads(replay_row["result_json"], {})
        result = dict(previous_result) if isinstance(previous_result, dict) else {}
        result.update(
            {
                "executed_agent": bool(response.get("executed_agent", True)),
                "actual_side_effect_mode": actual_side_effect_mode,
                "output_run_id": output_run_id,
                "target_map": response.get("target_map", {}),
                "server_response_ref": response_blob.blob_id,
                "server_response_keys": _response_keys(response),
                "note": response.get("note", "replay server completed"),
            }
        )
        connection.execute(
            """
            UPDATE replay_runs
            SET status = ?,
                ended_at = ?,
                output_ref = ?,
                result_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (status, now, output_run_id, _json_dumps(result), now, replay_run_id),
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{replay_run_id}_server_completed",
            profile_id=profile_id,
            entity_type="replay_run",
            entity_id=replay_run_id,
            kind="replay_run_server_completed",
            at=now,
            metadata={"check_spec_id": check_spec_id, "output_run_id": output_run_id},
        )

    return ReplayCompletionReport(
        replay_run_id=replay_run_id,
        profile_id=profile_id,
        check_spec_id=check_spec_id,
        output_run_id=output_run_id,
        status=status,
        result=result,
        ingest_report=IngestReport(profile_id=profile_id, inserted_counts={}),
    )


def mark_replay_errored(*, db_path: Path, replay_run_id: str, error: str) -> None:
    _mark_replay_errored(db_path, replay_run_id, error)


def _response_keys(response: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in response.keys())


def _validate_replay_server_response_identity(
    *,
    response: dict[str, Any],
    replay_run_id: str,
    source_label: str,
) -> None:
    identities: list[tuple[str, str]] = []
    for key in ("replay_run_id", "idempotency_key"):
        value = response.get(key)
        if isinstance(value, str) and value:
            identities.append((key, value))

    replay_payload = response.get("replay")
    if isinstance(replay_payload, dict):
        for key in ("replay_run_id", "idempotency_key"):
            value = replay_payload.get(key)
            if isinstance(value, str) and value:
                identities.append((f"replay.{key}", value))

    if not identities:
        raise CheckError(f"{source_label}: replay_server_identity_required:{replay_run_id}")
    for key, value in identities:
        if value != replay_run_id:
            raise CheckError(f"replay_server_identity_mismatch:{key}:{value}:{replay_run_id}")


def run_replay_command(
    *,
    db_path: Path,
    check_spec_id: str,
    output_dir: Path,
    command: Sequence[str],
    mode: str = "dry_run",
    side_effect_mode: Optional[str] = None,
    source_run_id: Optional[str] = None,
    timeout_seconds: int = 120,
    run_check_after: bool = False,
) -> ReplayCommandReport:
    if not command:
        raise CheckError("replay_command_required")

    output_dir.mkdir(parents=True, exist_ok=True)
    replay = create_replay_run(
        db_path=db_path,
        check_spec_id=check_spec_id,
        mode=mode,
        side_effect_mode=side_effect_mode,
        source_run_id=source_run_id,
    )
    request = build_replay_request(
        db_path=db_path,
        replay_run_id=replay.replay_run_id,
        redaction_consumer="replay:command",
    )
    request_path = output_dir / "replay-request.json"
    raw_output_path = output_dir / "replay-command-output.txt"
    result_path = output_dir / "replay-result.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    _merge_replay_artifacts(
        db_path=db_path,
        replay_run_id=replay.replay_run_id,
        artifacts=[
            _artifact_ref("replay_request", request_path, "application/json"),
        ],
    )

    env = os.environ.copy()
    env["KYOKO_REPLAY_REQUEST_PATH"] = str(request_path)
    env["KYOKO_REPLAY_RUN_ID"] = replay.replay_run_id
    env["KYOKO_CHECK_SPEC_ID"] = check_spec_id
    if replay.source_run_id is not None:
        env["KYOKO_SOURCE_RUN_ID"] = replay.source_run_id

    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        _mark_replay_errored(db_path, replay.replay_run_id, f"replay_command_not_found:{command[0]}")
        raise CheckError(f"replay_command_not_found:{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        _mark_replay_errored(db_path, replay.replay_run_id, f"replay_command_timeout:{timeout_seconds}")
        raise CheckError(f"replay_command_timeout:{timeout_seconds}") from exc

    raw_output = completed.stdout
    if completed.stderr:
        raw_output += "\n--- stderr ---\n" + completed.stderr
    raw_output_path.write_text(raw_output)
    _merge_replay_artifacts(
        db_path=db_path,
        replay_run_id=replay.replay_run_id,
        artifacts=[
            _artifact_ref("replay_request", request_path, "application/json"),
            _artifact_ref("replay_command_output", raw_output_path, "text/plain"),
        ],
    )

    if completed.returncode != 0:
        _mark_replay_errored(db_path, replay.replay_run_id, f"replay_command_failed:{completed.returncode}")
        raise CheckError(f"replay_command_failed:{completed.returncode}")

    try:
        replay_result = extract_replay_result_from_output(completed.stdout)
        result_path.write_text(json.dumps(replay_result, indent=2, sort_keys=True) + "\n")
        _merge_replay_artifacts(
            db_path=db_path,
            replay_run_id=replay.replay_run_id,
            artifacts=[
                _artifact_ref("replay_request", request_path, "application/json"),
                _artifact_ref("replay_command_output", raw_output_path, "text/plain"),
                _artifact_ref("replay_result", result_path, "application/json"),
            ],
        )
        completion = complete_replay_from_payload(
            db_path=db_path,
            replay_run_id=replay.replay_run_id,
            fixture=replay_result,
            source_label=str(result_path),
        )
        check_run = (
            run_check(
                db_path=db_path,
                check_spec_id=check_spec_id,
                replay_run_id=replay.replay_run_id,
            )
            if run_check_after
            else None
        )
    except CheckError as exc:
        _mark_replay_errored(db_path, replay.replay_run_id, str(exc))
        raise

    return ReplayCommandReport(
        replay_run_id=replay.replay_run_id,
        profile_id=replay.profile_id,
        check_spec_id=check_spec_id,
        request_path=request_path,
        result_path=result_path,
        raw_output_path=raw_output_path,
        completion=completion,
        check_run=check_run,
    )


def run_judge_command(
    *,
    db_path: Path,
    check_spec_id: str,
    output_dir: Path,
    command: Sequence[str],
    replay_run_id: Optional[str] = None,
    timeout_seconds: int = 120,
) -> JudgeCommandReport:
    if not command:
        raise CheckError("judge_command_required")

    output_dir.mkdir(parents=True, exist_ok=True)
    request = build_judge_request(
        db_path=db_path,
        check_spec_id=check_spec_id,
        replay_run_id=replay_run_id,
        redaction_consumer="judge:command",
    )
    request_path = output_dir / "judge-request.json"
    raw_output_path = output_dir / "judge-command-output.txt"
    result_path = output_dir / "judge-result.json"
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")

    env = os.environ.copy()
    env["KYOKO_JUDGE_REQUEST_PATH"] = str(request_path)
    env["KYOKO_CHECK_SPEC_ID"] = check_spec_id
    env["KYOKO_PROFILE_ID"] = str(request["profile_id"])
    env["KYOKO_JUDGE_RESULT_BLOCK_BEGIN"] = BEGIN_JUDGE_RESULT_BLOCK
    env["KYOKO_JUDGE_RESULT_BLOCK_END"] = END_JUDGE_RESULT_BLOCK
    if replay_run_id is not None:
        env["KYOKO_REPLAY_RUN_ID"] = replay_run_id

    try:
        completed = subprocess.run(
            list(command),
            input=json.dumps(request, sort_keys=True),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        raise CheckError(f"judge_command_not_found:{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError(f"judge_command_timeout:{timeout_seconds}") from exc

    raw_output = completed.stdout
    if completed.stderr:
        raw_output += "\n--- stderr ---\n" + completed.stderr
    raw_output_path.write_text(raw_output)

    if completed.returncode != 0:
        raise CheckError(f"judge_command_failed:{completed.returncode}")

    judge_result = extract_judge_result_from_output(completed.stdout)
    result_path.write_text(json.dumps(judge_result, indent=2, sort_keys=True) + "\n")
    artifacts = [
        _artifact_ref("judge_request", request_path, "application/json"),
        _artifact_ref("judge_command_output", raw_output_path, "text/plain"),
        _artifact_ref("judge_result", result_path, "application/json"),
    ]
    judgment = record_external_judge_result(
        db_path=db_path,
        check_spec_id=check_spec_id,
        judge_result=judge_result,
        artifact_refs=artifacts,
    )
    check_run = run_check(
        db_path=db_path,
        check_spec_id=check_spec_id,
        replay_run_id=replay_run_id,
    )
    _merge_check_run_artifacts(
        db_path=db_path,
        check_run_id=check_run.check_run_id,
        artifacts=artifacts,
    )
    return JudgeCommandReport(
        profile_id=check_run.profile_id,
        proposal_id=check_run.proposal_id,
        check_spec_id=check_spec_id,
        request_path=request_path,
        result_path=result_path,
        raw_output_path=raw_output_path,
        judgment=judgment,
        check_run=check_run,
    )


def build_judge_request(
    *,
    db_path: Path,
    check_spec_id: str,
    replay_run_id: Optional[str] = None,
    redaction_consumer: str = "judge",
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        if str(check_spec["check_type"]) != "judge":
            raise CheckError(f"judge_command_requires_judge_check:{check_spec_id}")
        profile_id = str(check_spec["profile_id"])
        target = _json_loads(check_spec["target_json"], {})
        definition = _judge_definition(_json_loads(check_spec["definition_json"], {}))
        proposal_id = check_spec["proposal_id"] if check_spec["proposal_id"] is not None else None
        proposal = _decode_row(_get_proposal(connection, str(proposal_id))) if proposal_id is not None else None
        replay_row = None
        if replay_run_id is not None:
            replay_row = _get_replay_run(connection, replay_run_id)
            if str(replay_row["check_spec_id"]) != check_spec_id:
                raise CheckError(f"replay_check_mismatch:{replay_run_id}:{check_spec_id}")
        target_run_id = _target_run_id(connection, target)

    from .evidence import build_evidence_bundle

    evidence_bundle = build_evidence_bundle(
        db_path=db_path,
        profile_id=profile_id,
        run_id=target_run_id,
        consumer=redaction_consumer,
    )
    judge_request = {
        "schema_version": "kyoko.judge_request.v1",
        "profile_id": profile_id,
        "check_spec": _decode_row(check_spec),
        "target": target,
        "definition": definition,
        "proposal": proposal,
        "replay_run": _decode_row(replay_row) if replay_row is not None else None,
        "evidence_bundle": evidence_bundle,
        "judge_contract": {
            "stdout_begin": BEGIN_JUDGE_RESULT_BLOCK,
            "stdout_end": END_JUDGE_RESULT_BLOCK,
            "required_check_spec_id": check_spec_id,
            "result_schema_version": "kyoko.judge_result.v1",
        },
    }
    try:
        policy = get_redaction_policy(db_path=db_path, profile_id=profile_id)
        result = redact_evidence_bundle(judge_request, policy)
        redaction = result.payload.get("redaction")
        if isinstance(redaction, dict):
            redaction["consumer"] = redaction_consumer
    except RedactionError as exc:
        raise CheckError(str(exc)) from exc
    return result.payload


def record_external_judge_result(
    *,
    db_path: Path,
    check_spec_id: str,
    judge_result: dict[str, Any],
    artifact_refs: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    initialize_database(db_path)
    if not isinstance(judge_result, dict):
        raise CheckError("judge_result_must_be_object")
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        if str(check_spec["check_type"]) != "judge":
            raise CheckError(f"judge_result_requires_judge_check:{check_spec_id}")
        definition = _json_loads(check_spec["definition_json"], {})
        judgment = _external_judgment(judge_result)
        if _judge_verdict(judgment) is None:
            raise CheckError("judge_verdict_required")
        clean_artifacts = [
            artifact
            for artifact in artifact_refs
            if isinstance(artifact, dict)
            and isinstance(artifact.get("kind"), str)
            and isinstance(artifact.get("path"), str)
        ]
        if clean_artifacts:
            judgment["artifact_refs"] = clean_artifacts
        now = utc_now()
        definition["recorded_judgment"] = judgment
        if isinstance(definition.get("operator_definition"), dict):
            definition["operator_definition"]["recorded_judgment"] = judgment
        definition["external_judge"] = {
            "backend": "external_command",
            "result_schema_version": judge_result.get("schema_version", "kyoko.judge_result.v1"),
            "artifact_refs": clean_artifacts,
            "updated_at": now,
        }
        connection.execute(
            """
            UPDATE check_specs
            SET definition_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_json_dumps(definition), now, check_spec_id),
        )
    return judgment


def _artifact_ref(kind: str, path: Path, media_type: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": str(path),
        "media_type": media_type,
    }


def _merge_replay_artifacts(
    *,
    db_path: Path,
    replay_run_id: str,
    artifacts: Sequence[dict[str, Any]],
) -> None:
    with connect(db_path) as connection:
        replay_row = _get_replay_run(connection, replay_run_id)
        existing = _json_loads(replay_row["artifact_refs_json"], [])
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        if isinstance(existing, list):
            for artifact in existing:
                if not isinstance(artifact, dict):
                    continue
                kind = artifact.get("kind")
                path = artifact.get("path")
                if isinstance(kind, str) and isinstance(path, str):
                    merged[(kind, path)] = artifact
        for artifact in artifacts:
            kind = artifact.get("kind")
            path = artifact.get("path")
            if isinstance(kind, str) and isinstance(path, str):
                merged[(kind, path)] = artifact
        connection.execute(
            """
            UPDATE replay_runs
            SET artifact_refs_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_json_dumps(list(merged.values())), utc_now(), replay_run_id),
        )


def _merge_check_run_artifacts(
    *,
    db_path: Path,
    check_run_id: str,
    artifacts: Sequence[dict[str, Any]],
) -> None:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT artifact_refs_json FROM check_runs WHERE id = ?",
            (check_run_id,),
        ).fetchone()
        if row is None:
            raise CheckError(f"check_run_not_found:{check_run_id}")
        existing = _json_loads(row["artifact_refs_json"], [])
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        if isinstance(existing, list):
            for artifact in existing:
                if not isinstance(artifact, dict):
                    continue
                kind = artifact.get("kind")
                path = artifact.get("path")
                if isinstance(kind, str) and isinstance(path, str):
                    merged[(kind, path)] = artifact
        for artifact in artifacts:
            kind = artifact.get("kind")
            path = artifact.get("path")
            if isinstance(kind, str) and isinstance(path, str):
                merged[(kind, path)] = artifact
        connection.execute(
            """
            UPDATE check_runs
            SET artifact_refs_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (_json_dumps(list(merged.values())), utc_now(), check_run_id),
        )


def build_replay_request(
    *,
    db_path: Path,
    replay_run_id: str,
    redact_for_external: bool = True,
    redaction_consumer: str = "replay",
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        replay_row = _get_replay_run(connection, replay_run_id)
        check_spec = _get_check_spec(connection, str(replay_row["check_spec_id"]))
        profile_id = str(replay_row["profile_id"])
        source_run_id = replay_row["source_run_id"] if replay_row["source_run_id"] is not None else None
        source_run = _one(
            connection,
            "SELECT * FROM runs WHERE id = ?",
            (source_run_id,),
        ) if isinstance(source_run_id, str) else {}
        source_spans = _all(
            connection,
            "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id",
            (source_run_id,),
        ) if isinstance(source_run_id, str) else []
        handoffs = _all(
            connection,
            "SELECT * FROM handoffs WHERE run_id = ? ORDER BY created_at, id",
            (source_run_id,),
        ) if isinstance(source_run_id, str) else []

    replay_request = {
        "schema_version": "kyoko.replay_request.v1",
        "profile_id": profile_id,
        "replay_run": _decode_row(replay_row),
        "check_spec": _decode_row(check_spec),
        "source_run": source_run,
        "source_spans": source_spans,
        "handoffs": handoffs,
        "operator_contract": {
            "stdout_begin": BEGIN_REPLAY_RESULT_BLOCK,
            "stdout_end": END_REPLAY_RESULT_BLOCK,
            "required_replay_run_id": replay_run_id,
            "result_schema_version": "kyoko.replay_result.v1",
        },
    }
    if not redact_for_external:
        return replay_request
    try:
        policy = get_redaction_policy(db_path=db_path, profile_id=profile_id)
        result = redact_evidence_bundle(replay_request, policy)
        redaction = result.payload.get("redaction")
        if isinstance(redaction, dict):
            redaction["consumer"] = redaction_consumer
    except RedactionError as exc:
        raise CheckError(str(exc)) from exc
    return result.payload


def extract_replay_result_from_output(output: str) -> dict[str, Any]:
    if output.count(BEGIN_REPLAY_RESULT_BLOCK) != 1 or output.count(END_REPLAY_RESULT_BLOCK) != 1:
        raise CheckError("replay_output_must_contain_exactly_one_result_block")

    start = output.index(BEGIN_REPLAY_RESULT_BLOCK) + len(BEGIN_REPLAY_RESULT_BLOCK)
    end = output.index(END_REPLAY_RESULT_BLOCK)
    if end <= start:
        raise CheckError("replay_result_block_order_invalid")

    raw_json = output[start:end].strip()
    try:
        replay_result = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise CheckError(f"replay_result_json_invalid:{exc}") from exc
    if not isinstance(replay_result, dict):
        raise CheckError("replay_result_must_be_object")
    return replay_result


def extract_judge_result_from_output(output: str) -> dict[str, Any]:
    if output.count(BEGIN_JUDGE_RESULT_BLOCK) != 1 or output.count(END_JUDGE_RESULT_BLOCK) != 1:
        raise CheckError("judge_output_must_contain_exactly_one_result_block")

    start = output.index(BEGIN_JUDGE_RESULT_BLOCK) + len(BEGIN_JUDGE_RESULT_BLOCK)
    end = output.index(END_JUDGE_RESULT_BLOCK)
    if end <= start:
        raise CheckError("judge_result_block_order_invalid")

    raw_json = output[start:end].strip()
    try:
        judge_result = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise CheckError(f"judge_result_json_invalid:{exc}") from exc
    if not isinstance(judge_result, dict):
        raise CheckError("judge_result_must_be_object")
    return judge_result


def parse_replay_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise CheckError(f"invalid_replay_command:{exc}") from exc


def parse_judge_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise CheckError(f"invalid_judge_command:{exc}") from exc


def list_check_specs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT
                  check_specs.*,
                  COALESCE(check_locks.human_locked, 0) AS human_locked,
                  check_locks.reason AS human_lock_reason
                FROM check_specs
                LEFT JOIN check_locks
                  ON check_locks.check_spec_id = check_specs.id
                 AND check_locks.profile_id = check_specs.profile_id
                ORDER BY check_specs.created_at DESC, check_specs.id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    specs = [_decode_row(row) for row in rows]
    for spec in specs:
        spec["human_locked"] = bool(spec.get("human_locked"))
    return specs


def list_check_locks(
    db_path: Path,
    *,
    profile_id: Optional[str] = None,
    locked_only: bool = True,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    where = []
    params: list[Any] = []
    if profile_id is not None:
        where.append("profile_id = ?")
        params.append(profile_id)
    if locked_only:
        where.append("human_locked = 1")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT profile_id, check_spec_id, human_locked, reason, created_at, updated_at
                FROM check_locks
                {where_sql}
                ORDER BY updated_at DESC, check_spec_id ASC
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    locks = [_decode_row(row) for row in rows]
    for lock in locks:
        lock["human_locked"] = bool(lock.get("human_locked"))
    return locks


def set_check_lock(
    *,
    db_path: Path,
    check_spec_id: str,
    locked: bool,
    reason: Optional[str] = None,
    actor_agent_identity_id: Optional[str] = None,
) -> CheckSpecLockReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        profile_id = str(check_spec["profile_id"])
        now = utc_now()
        _ensure_kyoko_source(connection, profile_id, {"checks": True})
        clean_actor_agent_identity_id = _validate_actor_agent_identity_id(
            connection,
            profile_id,
            actor_agent_identity_id,
        )
        existing = connection.execute(
            """
            SELECT created_at
            FROM check_locks
            WHERE profile_id = ? AND check_spec_id = ?
            """,
            (profile_id, check_spec_id),
        ).fetchone()
        created_at = str(existing["created_at"]) if existing is not None else now
        selected_reason = reason
        connection.execute(
            """
            INSERT INTO check_locks (
              profile_id,
              check_spec_id,
              human_locked,
              reason,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, check_spec_id) DO UPDATE SET
              human_locked = excluded.human_locked,
              reason = excluded.reason,
              updated_at = excluded.updated_at
            """,
            (
                profile_id,
                check_spec_id,
                1 if locked else 0,
                selected_reason,
                created_at,
                now,
            ),
        )
        return CheckSpecLockReport(
            check_spec_id=check_spec_id,
            profile_id=profile_id,
            human_locked=locked,
            reason=selected_reason,
            actor_agent_identity_id=clean_actor_agent_identity_id,
        )


def approve_check_spec(
    *,
    db_path: Path,
    check_spec_id: str,
    reason: Optional[str] = None,
    actor_agent_identity_id: Optional[str] = None,
) -> CheckSpecApprovalReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        profile_id = str(check_spec["profile_id"])
        if _check_spec_is_human_locked(connection, check_spec_id):
            raise CheckError(f"human_locked_check_spec:{check_spec_id}")
        now = utc_now()
        _ensure_kyoko_source(connection, profile_id, {"checks": True})
        clean_actor_agent_identity_id = _validate_actor_agent_identity_id(
            connection,
            profile_id,
            actor_agent_identity_id,
        )
        previous_trust_level = str(check_spec["trust_level"])
        clean_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        connection.execute(
            "UPDATE check_specs SET trust_level = ?, updated_at = ? WHERE id = ?",
            ("L3_human_approved", now, check_spec_id),
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{check_spec_id}_human_approved_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
            entity_type="check_spec",
            entity_id=check_spec_id,
            kind="check_spec_human_approved",
            at=now,
            agent_identity_id=clean_actor_agent_identity_id,
            metadata={
                "previous_trust_level": previous_trust_level,
                "trust_level": "L3_human_approved",
                "reason": clean_reason,
                "actor_agent_identity_id": clean_actor_agent_identity_id,
            },
        )
        return CheckSpecApprovalReport(
            check_spec_id=check_spec_id,
            profile_id=profile_id,
            previous_trust_level=previous_trust_level,
            trust_level="L3_human_approved",
            reason=clean_reason,
            actor_agent_identity_id=clean_actor_agent_identity_id,
        )


def list_check_runs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM check_runs
                ORDER BY created_at DESC, id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_decode_row(row) for row in rows]


def list_replay_runs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM replay_runs
                ORDER BY created_at DESC, id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_decode_row(row) for row in rows]


def _get_proposal(connection: sqlite3.Connection, proposal_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM learning_proposals WHERE id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise CheckError(f"proposal_not_found:{proposal_id}")
    return row


def _get_check_spec(connection: sqlite3.Connection, check_spec_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM check_specs WHERE id = ?",
        (check_spec_id,),
    ).fetchone()
    if row is None:
        raise CheckError(f"check_spec_not_found:{check_spec_id}")
    return row


def _get_replay_run(connection: sqlite3.Connection, replay_run_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM replay_runs WHERE id = ?",
        (replay_run_id,),
    ).fetchone()
    if row is None:
        raise CheckError(f"replay_run_not_found:{replay_run_id}")
    return row


def _ensure_check_write_allowed(connection: sqlite3.Connection, profile_id: str) -> None:
    row = connection.execute(
        "SELECT allow_check_write FROM autonomy_policies WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise CheckError(f"autonomy_policy_not_found:{profile_id}")
    if int(row["allow_check_write"]) != 1:
        raise CheckError("check_write_not_allowed")


def _ensure_kyoko_source(
    connection: sqlite3.Connection,
    profile_id: str,
    capabilities: dict[str, Any],
) -> None:
    now = utc_now()
    connection.execute(
        """
        INSERT OR IGNORE INTO sources (
          id,
          profile_id,
          kind,
          display_name,
          status,
          adapter_version,
          config_json,
          capabilities_json,
          last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"source_kyoko_{profile_id}",
            profile_id,
            "kyoko_sdk",
            "Kyoko",
            "active",
            "kyoko.core.v0",
            "{}",
            _json_dumps(capabilities),
            now,
        ),
    )


def _insert_timeline_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    profile_id: str,
    entity_type: str,
    entity_id: str,
    kind: str,
    at: str,
    metadata: dict[str, Any],
    agent_identity_id: Optional[str] = None,
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO timeline_events (
          id,
          profile_id,
          source_id,
          entity_type,
          entity_id,
          kind,
          at,
          agent_identity_id,
          payload_ref,
          metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            profile_id,
            f"source_kyoko_{profile_id}",
            entity_type,
            entity_id,
            kind,
            at,
            agent_identity_id,
            None,
            _json_dumps(metadata),
        ),
    )


def _validate_actor_agent_identity_id(
    connection: sqlite3.Connection,
    profile_id: str,
    actor_agent_identity_id: Optional[str],
) -> Optional[str]:
    if actor_agent_identity_id is None:
        return None
    clean_actor_agent_identity_id = actor_agent_identity_id.strip()
    if not clean_actor_agent_identity_id:
        return None
    row = connection.execute(
        """
        SELECT id
        FROM agent_identities
        WHERE id = ? AND profile_id = ?
        """,
        (clean_actor_agent_identity_id, profile_id),
    ).fetchone()
    if row is None:
        raise CheckError(f"actor_agent_identity_not_found:{clean_actor_agent_identity_id}")
    return clean_actor_agent_identity_id


def _check_spec_id(proposal_id: str, index: int, change: dict[str, Any]) -> str:
    explicit_id = change.get("check_spec_id")
    if isinstance(explicit_id, str) and explicit_id:
        return explicit_id
    return f"check_{proposal_id}_{index}"


def _fallback_check_changes(proposal: sqlite3.Row, changes: list[Any]) -> list[dict[str, Any]]:
    context_change_types = {"skillbook_update", "context_delivery_rule"}
    has_context_change = any(
        isinstance(change, dict) and change.get("type") in context_change_types
        for change in changes
    )
    has_harness_change = any(
        isinstance(change, dict) and change.get("type") == "harness_patch"
        for change in changes
    )
    if not has_context_change and not has_harness_change:
        return []
    evidence_refs = _json_loads(proposal["evidence_refs_json"], [])
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return []
    section = str(proposal["section"])
    generated_by = (
        "kyoko_fallback_harness_check"
        if section == "harness" and has_harness_change
        else "kyoko_fallback_context_check"
    )
    return [
        {
            "type": "check_spec",
            "name": _fallback_check_name(str(proposal["title"] or proposal["id"])),
            "check_type": "deterministic_assertion",
            "trust_level": "L0_generated",
            "side_effect_mode": "network_mocked",
            "definition": {
                "generated_by": generated_by,
                "given": "proposal cites failure evidence but did not provide an explicit check spec",
                "expect": "the targeted failure is no longer failed after replay or a future run",
                "assertions": [{"type": "target_status_not_failed"}],
            },
        }
    ]


def _fallback_check_name(title: str) -> str:
    normalized = " ".join(title.strip().split())
    if not normalized:
        normalized = "context proposal"
    return f"generated gate for {normalized}"[:120]


def _target_for_check(proposal: sqlite3.Row, change: dict[str, Any]) -> dict[str, Any]:
    definition = change.get("definition")
    if isinstance(definition, dict):
        target = definition.get("target")
        if isinstance(target, dict):
            return target

    evidence_refs = _json_loads(proposal["evidence_refs_json"], [])
    if isinstance(evidence_refs, list):
        for ref in evidence_refs:
            if isinstance(ref, dict) and ref.get("role") == "failure":
                return _target_from_evidence_ref(ref, "failure_evidence")
        for ref in evidence_refs:
            if isinstance(ref, dict):
                return _target_from_evidence_ref(ref, "first_evidence")

    problem = _json_loads(proposal["problem_json"], {})
    if isinstance(problem, dict):
        target = problem.get("target")
        if isinstance(target, dict):
            return dict(target)

    raise CheckError(f"check_target_unavailable:{proposal['id']}")


def _target_from_evidence_ref(ref: dict[str, Any], source: str) -> dict[str, Any]:
    entity_type = ref.get("entity_type")
    entity_id = ref.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        raise CheckError("invalid_check_target_evidence")
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source": source,
        "role": ref.get("role"),
    }


def _definition_for_check(proposal: sqlite3.Row, change: dict[str, Any]) -> dict[str, Any]:
    definition = change.get("definition")
    if not isinstance(definition, dict):
        definition = {}
    assertion = definition.get("assertion", "target_status_not_failed")
    return {
        "operator_definition": definition,
        "assertion": assertion if isinstance(assertion, str) else "target_status_not_failed",
        "assertions": _assertion_specs(definition),
        "failure_statuses": sorted(FAILURE_STATUSES),
        "proposal_title": proposal["title"],
        "proposal_summary": proposal["summary"],
        "evidence_refs": _json_loads(proposal["evidence_refs_json"], []),
    }


def _validate_replay_boundary(*, mode: str, side_effect_mode: str) -> None:
    if mode not in {"dry_run", "sandbox", "live"}:
        raise CheckError(f"unsupported_replay_mode:{mode}")
    if side_effect_mode not in SAFE_REPLAY_SIDE_EFFECT_MODES:
        raise CheckError(f"unsafe_replay_side_effect_mode:{side_effect_mode}")
    if mode == "live":
        raise CheckError("live_replay_not_supported")


def _validate_actual_replay_side_effect_mode(
    *,
    requested_side_effect_mode: str,
    actual_side_effect_mode: str,
) -> None:
    allowed = ALLOWED_ACTUAL_SIDE_EFFECT_MODES_BY_REQUEST.get(requested_side_effect_mode)
    if allowed is None:
        raise CheckError(f"unsafe_replay_side_effect_mode:{requested_side_effect_mode}")
    if actual_side_effect_mode not in SAFE_REPLAY_SIDE_EFFECT_MODES:
        raise CheckError(f"unsafe_replay_side_effect_mode:{actual_side_effect_mode}")
    if actual_side_effect_mode not in allowed:
        raise CheckError(
            "replay_side_effect_mode_exceeds_request:"
            f"{actual_side_effect_mode}:{requested_side_effect_mode}"
        )


def _source_run_for_target(connection: sqlite3.Connection, target: dict[str, Any]) -> Optional[str]:
    entity_type = target.get("entity_type")
    entity_id = target.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return None
    if entity_type == "run":
        return entity_id
    if entity_type == "span":
        row = connection.execute("SELECT run_id FROM spans WHERE id = ?", (entity_id,)).fetchone()
        return str(row["run_id"]) if row is not None else None
    if entity_type == "task_attempt":
        row = connection.execute("SELECT run_id FROM task_attempts WHERE id = ?", (entity_id,)).fetchone()
        if row is not None and row["run_id"] is not None:
            return str(row["run_id"])
    return None


def _task_attempt_for_source_run(
    connection: sqlite3.Connection,
    source_run_id: Optional[str],
) -> Optional[str]:
    if source_run_id is None:
        return None
    row = connection.execute(
        "SELECT task_attempt_id FROM runs WHERE id = ?",
        (source_run_id,),
    ).fetchone()
    if row is not None and row["task_attempt_id"] is not None:
        return str(row["task_attempt_id"])
    row = connection.execute(
        "SELECT id FROM task_attempts WHERE run_id = ? ORDER BY started_at, id LIMIT 1",
        (source_run_id,),
    ).fetchone()
    return str(row["id"]) if row is not None else None


def _evaluate(
    connection: sqlite3.Connection,
    check_spec: sqlite3.Row,
    replay_row: Optional[sqlite3.Row],
) -> tuple[str, dict[str, Any]]:
    check_type = str(check_spec["check_type"])
    if check_type == "smoke_run":
        return _evaluate_smoke_run(connection, check_spec, replay_row)
    if check_type == "judge":
        return _evaluate_recorded_judge(check_spec)
    if check_type == "regression_replay":
        return _evaluate_regression_replay(connection, check_spec, replay_row)
    if check_type != "deterministic_assertion":
        return (
            "errored",
            {
                "error": f"unsupported_check_type:{check_type}",
                "supported_check_type": "deterministic_assertion",
                "supported_check_types": list(EXECUTABLE_CHECK_TYPES),
            },
        )

    return _evaluate_deterministic_assertions(connection, check_spec, replay_row)


def _evaluate_deterministic_assertions(
    connection: sqlite3.Connection,
    check_spec: sqlite3.Row,
    replay_row: Optional[sqlite3.Row],
    *,
    definition_override: Optional[dict[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    target = _json_loads(check_spec["target_json"], {})
    definition = definition_override or _json_loads(check_spec["definition_json"], {})
    observed_status = _target_status(connection, target)
    failure_statuses = set(definition.get("failure_statuses", sorted(FAILURE_STATUSES)))
    replay_result = _json_loads(replay_row["result_json"], {}) if replay_row is not None else None
    replay_target = _replay_target(target, replay_result)
    replay_observed_status = _target_status(connection, replay_target) if replay_target is not None else None

    context = {
        "target": target,
        "observed_status": observed_status,
        "failure_statuses": failure_statuses,
        "replay_row": replay_row,
        "replay_result": replay_result,
        "replay_target": replay_target,
        "replay_observed_status": replay_observed_status,
    }
    assertion_results = [
        _evaluate_assertion(connection, assertion, context)
        for assertion in _assertion_specs(definition)
    ]
    passed = all(result["passed"] for result in assertion_results)
    status_result = next(
        (result for result in assertion_results if result.get("type") == "target_status_not_failed"),
        assertion_results[0] if assertion_results else {},
    )
    comparison = status_result.get("comparison") or ("assertions_passed" if passed else "assertions_failed")
    reason = "all_assertions_passed" if passed else "one_or_more_assertions_failed"

    return (
        "passed" if passed else "failed",
        {
            "assertion": definition.get("assertion", "target_status_not_failed"),
            "target": target,
            "observed_status": observed_status,
            "baseline_status": observed_status,
            "replay_target": replay_target,
            "replay_observed_status": replay_observed_status,
            "failure_statuses": sorted(failure_statuses),
            "replay_run_id": replay_row["id"] if replay_row is not None else None,
            "replay_result": replay_result,
            "replay_side_effect_mode": replay_result.get("actual_side_effect_mode")
            if isinstance(replay_result, dict)
            else None,
            "assertions": assertion_results,
            "assertion_counts": {
                "total": len(assertion_results),
                "passed": len([result for result in assertion_results if result["passed"]]),
                "failed": len([result for result in assertion_results if not result["passed"]]),
            },
            "comparison": comparison,
            "reason": reason,
        },
    )


def _evaluate_regression_replay(
    connection: sqlite3.Connection,
    check_spec: sqlite3.Row,
    replay_row: Optional[sqlite3.Row],
) -> tuple[str, dict[str, Any]]:
    if replay_row is None:
        return (
            "errored",
            {
                "error": "replay_required",
                "check_type": "regression_replay",
                "required_replay": True,
                "gateable": True,
            },
        )

    definition = _json_loads(check_spec["definition_json"], {})
    assertion_specs = _assertion_specs(definition)
    if not _has_target_status_assertion(assertion_specs):
        definition = dict(definition)
        definition["assertions"] = [{"type": "target_status_not_failed"}] + assertion_specs

    status, result = _evaluate_deterministic_assertions(
        connection,
        check_spec,
        replay_row,
        definition_override=definition,
    )
    result["check_type"] = "regression_replay"
    result["required_replay"] = True
    result["gateable"] = True
    if str(replay_row["status"]) != "passed":
        result["reason"] = "replay_run_not_passed"
        result["comparison"] = "replay_not_passed"
        return "failed", result
    if result.get("comparison") != "fail_before_pass_after":
        result["reason"] = "regression_replay_requires_fail_before_pass_after"
        return "failed", result
    if result.get("replay_side_effect_mode") not in SAFE_REPLAY_SIDE_EFFECT_MODES:
        result["reason"] = "unsafe_replay_side_effect_mode"
        return "failed", result
    return status, result


def _has_target_status_assertion(assertions: list[dict[str, Any]]) -> bool:
    return any(
        assertion.get("type", "target_status_not_failed") == "target_status_not_failed"
        for assertion in assertions
    )


def _evaluate_recorded_judge(check_spec: sqlite3.Row) -> tuple[str, dict[str, Any]]:
    definition = _judge_definition(_json_loads(check_spec["definition_json"], {}))
    judgment = _recorded_judgment(definition)
    verdict = _judge_verdict(judgment)
    judge_backend = judgment.get("judge_backend", judgment.get("backend", "recorded_judgment"))
    if not isinstance(judge_backend, str) or not judge_backend:
        judge_backend = "recorded_judgment"
    external_judge = definition.get("external_judge") if isinstance(definition.get("external_judge"), dict) else {}
    result = {
        "check_type": "judge",
        "judge_backend": judge_backend,
        "target": _json_loads(check_spec["target_json"], {}),
        "rubric": judgment.get("rubric", definition.get("rubric")),
        "judge": judgment.get("judge", judgment.get("judge_name", definition.get("judge"))),
        "score": judgment.get("score", definition.get("score")),
        "reasoning": judgment.get("reasoning", judgment.get("reason", definition.get("reasoning"))),
        "evidence_refs": judgment.get("evidence_refs", definition.get("evidence_refs", [])),
        "artifact_refs": judgment.get("artifact_refs", external_judge.get("artifact_refs", [])),
        "gateable": False,
    }
    if verdict is None:
        result.update(
            {
                "error": "judge_verdict_required",
                "supported_verdicts": sorted(JUDGE_PASS_VERDICTS | JUDGE_FAIL_VERDICTS),
                "comparison": "judge_verdict_missing",
                "reason": "recorded_judge_verdict_missing",
            }
        )
        return "errored", result

    passed = verdict in JUDGE_PASS_VERDICTS
    result.update(
        {
            "verdict": verdict,
            "comparison": "judge_verdict_passed" if passed else "judge_verdict_failed",
            "reason": "recorded_judge_passed" if passed else "recorded_judge_failed",
            "assertions": [
                {
                    "type": "recorded_judge_verdict",
                    "passed": passed,
                    "reason": "verdict_passed" if passed else "verdict_failed",
                    "expected": sorted(JUDGE_PASS_VERDICTS),
                    "actual": verdict,
                }
            ],
            "assertion_counts": {"total": 1, "passed": 1 if passed else 0, "failed": 0 if passed else 1},
        }
    )
    return "passed" if passed else "failed", result


def _recorded_judgment(definition: dict[str, Any]) -> dict[str, Any]:
    judgment = definition.get("judgment", definition.get("recorded_judgment"))
    if isinstance(judgment, dict):
        return judgment
    return definition


def _judge_definition(definition: dict[str, Any]) -> dict[str, Any]:
    operator_definition = definition.get("operator_definition")
    if not isinstance(operator_definition, dict):
        return definition
    merged = dict(operator_definition)
    for key, value in definition.items():
        if key != "operator_definition" and key not in merged:
            merged[key] = value
    return merged


def _judge_verdict(judgment: dict[str, Any]) -> Optional[str]:
    for key in ("verdict", "judgment", "result"):
        value = judgment.get(key)
        if isinstance(value, bool):
            return "passed" if value else "failed"
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in JUDGE_PASS_VERDICTS or normalized in JUDGE_FAIL_VERDICTS:
                return normalized
    value = judgment.get("passed")
    if isinstance(value, bool):
        return "passed" if value else "failed"
    return None


def _external_judgment(judge_result: dict[str, Any]) -> dict[str, Any]:
    payload = judge_result.get("judgment")
    if not isinstance(payload, dict):
        payload = judge_result.get("recorded_judgment")
    if isinstance(payload, dict):
        judgment = dict(payload)
    else:
        judgment = dict(judge_result)
        judgment.pop("schema_version", None)
    judgment["judge_backend"] = "external_command"
    judgment["backend"] = "external_command"
    return judgment


def _target_run_id(connection: sqlite3.Connection, target: dict[str, Any]) -> Optional[str]:
    entity_type = target.get("entity_type")
    entity_id = target.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return None
    if entity_type == "run":
        return entity_id
    if entity_type == "span":
        row = connection.execute("SELECT run_id FROM spans WHERE id = ?", (entity_id,)).fetchone()
        return str(row["run_id"]) if row is not None and row["run_id"] is not None else None
    if entity_type == "task_attempt":
        row = connection.execute("SELECT run_id FROM task_attempts WHERE id = ?", (entity_id,)).fetchone()
        return str(row["run_id"]) if row is not None and row["run_id"] is not None else None
    return None


def _evaluate_smoke_run(
    connection: sqlite3.Connection,
    check_spec: sqlite3.Row,
    replay_row: Optional[sqlite3.Row],
) -> tuple[str, dict[str, Any]]:
    target = _json_loads(check_spec["target_json"], {})
    definition = _json_loads(check_spec["definition_json"], {})
    smoke_definition = _smoke_definition(definition)
    failure_statuses = set(smoke_definition.get("failure_statuses", sorted(FAILURE_STATUSES)))
    replay_result = _json_loads(replay_row["result_json"], {}) if replay_row is not None else None
    run_id, run_source = _smoke_run_id(connection, target, smoke_definition, replay_row, replay_result)
    run_row = _resolve_check_entity(connection, "run", run_id)
    run_status = run_row.get("status") if run_row is not None else None
    checks: list[dict[str, Any]] = []

    allowed_statuses = smoke_definition.get("allowed_run_statuses")
    if isinstance(allowed_statuses, list) and allowed_statuses:
        selected_allowed_statuses = [status for status in allowed_statuses if isinstance(status, str)]
        status_passed = run_status in selected_allowed_statuses and run_status not in failure_statuses
        checks.append(
            {
                "type": "smoke_run_status_allowed",
                "passed": status_passed,
                "reason": "run_status_allowed" if status_passed else "run_status_not_allowed_or_failed",
                "entity": {"id": run_id},
                "expected": selected_allowed_statuses,
                "actual": run_status,
                "observed_status": run_status,
            }
        )
    else:
        status_passed = run_status is not None and run_status not in failure_statuses
        checks.append(
            {
                "type": "smoke_run_status_not_failed",
                "passed": status_passed,
                "reason": "run_status_is_acceptable" if status_passed else "run_status_is_failure_or_missing",
                "entity": {"id": run_id},
                "expected": f"not in {sorted(failure_statuses)}",
                "actual": run_status,
                "observed_status": run_status,
            }
        )

    if replay_row is not None:
        replay_passed = str(replay_row["status"]) == "passed"
        checks.append(
            {
                "type": "smoke_replay_run_passed",
                "passed": replay_passed,
                "reason": "replay_run_passed" if replay_passed else "replay_run_not_passed",
                "entity": {"id": replay_row["id"]},
                "expected": "passed",
                "actual": str(replay_row["status"]),
            }
        )

    spans = _replay_spans(connection, run_id)
    if smoke_definition.get("no_failed_spans", True):
        failed_spans = [span for span in spans if span.get("status") in failure_statuses]
        no_failed_spans = run_id is not None and not failed_spans
        checks.append(
            {
                "type": "smoke_no_failed_spans",
                "passed": no_failed_spans,
                "reason": "no_failed_spans" if no_failed_spans else "failed_spans_present",
                "entity": {"id": run_id},
                "expected": 0,
                "actual": len(failed_spans),
                "failed_span_ids": [span.get("id") for span in failed_spans],
            }
        )

    minimum_spans = _definition_min_count(smoke_definition, "min_spans", "minimum_spans", default=1)
    if minimum_spans > 0:
        span_count_passed = run_id is not None and len(spans) >= minimum_spans
        checks.append(
            {
                "type": "smoke_span_count_at_least",
                "passed": span_count_passed,
                "reason": "span_count_sufficient" if span_count_passed else "span_count_too_low",
                "entity": {"id": run_id},
                "expected": minimum_spans,
                "actual": len(spans),
            }
        )

    minimum_handoffs = _definition_min_count(smoke_definition, "min_handoffs", "minimum_handoffs", default=0)
    if minimum_handoffs > 0:
        handoffs = _replay_handoffs(connection, run_id)
        handoff_count_passed = run_id is not None and len(handoffs) >= minimum_handoffs
        checks.append(
            {
                "type": "smoke_handoff_count_at_least",
                "passed": handoff_count_passed,
                "reason": "handoff_count_sufficient" if handoff_count_passed else "handoff_count_too_low",
                "entity": {"id": run_id},
                "expected": minimum_handoffs,
                "actual": len(handoffs),
            }
        )

    passed = all(check["passed"] for check in checks)
    comparison = "smoke_run_checks_passed" if passed else "smoke_run_checks_failed"
    return (
        "passed" if passed else "failed",
        {
            "target": target,
            "smoke_run_id": run_id,
            "smoke_run_source": run_source,
            "observed_status": run_status,
            "failure_statuses": sorted(failure_statuses),
            "replay_run_id": replay_row["id"] if replay_row is not None else None,
            "replay_result": replay_result,
            "replay_side_effect_mode": replay_result.get("actual_side_effect_mode")
            if isinstance(replay_result, dict)
            else None,
            "assertions": checks,
            "assertion_counts": {
                "total": len(checks),
                "passed": len([check for check in checks if check["passed"]]),
                "failed": len([check for check in checks if not check["passed"]]),
            },
            "comparison": comparison,
            "reason": "all_smoke_checks_passed" if passed else "one_or_more_smoke_checks_failed",
            "gateable": False,
        },
    )


def _smoke_definition(definition: dict[str, Any]) -> dict[str, Any]:
    operator_definition = definition.get("operator_definition")
    if not isinstance(operator_definition, dict):
        return definition
    merged = dict(operator_definition)
    merged.update(definition)
    return merged


def _smoke_run_id(
    connection: sqlite3.Connection,
    target: dict[str, Any],
    definition: dict[str, Any],
    replay_row: Optional[sqlite3.Row],
    replay_result: Optional[dict[str, Any]],
) -> tuple[Optional[str], str]:
    if replay_row is not None:
        output_ref = replay_row["output_ref"]
        if isinstance(output_ref, str) and output_ref:
            return output_ref, "replay_output"
        if isinstance(replay_result, dict):
            output_run_id = replay_result.get("output_run_id")
            if isinstance(output_run_id, str) and output_run_id:
                return output_run_id, "replay_result"
    definition_run_id = definition.get("run_id")
    if isinstance(definition_run_id, str) and definition_run_id:
        return definition_run_id, "definition"
    return _source_run_for_target(connection, target), "target"


def _assertion_specs(definition: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    assertions = definition.get("assertions")
    if isinstance(assertions, list):
        specs.extend(assertion for assertion in assertions if isinstance(assertion, dict))
    specs.extend(_assertion_preset_specs(definition))
    if specs:
        return specs
    assertion = definition.get("assertion", "target_status_not_failed")
    return [{"type": assertion if isinstance(assertion, str) else "target_status_not_failed"}]


def _assertion_preset_specs(definition: dict[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for preset in _assertion_preset_names(definition):
        if preset == "replay_success_shape":
            expected_status = definition.get("expected_run_status", definition.get("replay_run_status", "succeeded"))
            if not isinstance(expected_status, str) or not expected_status:
                expected_status = "succeeded"
            specs.extend(
                [
                    {"type": "replay_run_status_equals", "equals": expected_status},
                    {"type": "replay_no_failed_spans"},
                    {
                        "type": "replay_span_count_at_least",
                        "min": _definition_min_count(definition, "min_spans", "minimum_spans", default=1),
                    },
                ]
            )
            continue
        if preset == "replay_handoff_present":
            specs.append(
                {
                    "type": "replay_handoff_count_at_least",
                    "min": _definition_min_count(definition, "min_handoffs", "minimum_handoffs", default=1),
                }
            )
            continue
        specs.append({"type": "unsupported_assertion_preset", "preset": preset})
    return specs


def _assertion_preset_names(definition: dict[str, Any]) -> list[str]:
    raw_presets = definition.get("assertion_presets", definition.get("assertion_preset"))
    if isinstance(raw_presets, str):
        candidates = [raw_presets]
    elif isinstance(raw_presets, list):
        candidates = [preset for preset in raw_presets if isinstance(preset, str)]
    else:
        candidates = []
    names: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        name = candidate.strip()
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    return names


def _evaluate_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    assertion_type = assertion.get("type", "target_status_not_failed")
    if assertion_type == "target_status_not_failed":
        return _evaluate_status_assertion(assertion, context)
    if assertion_type == "replay_target_field_equals":
        return _evaluate_replay_target_field_assertion(connection, assertion, context)
    if assertion_type == "replay_entity_field_equals":
        return _evaluate_replay_entity_field_assertion(connection, assertion, context)
    if assertion_type == "replay_run_status_equals":
        return _evaluate_replay_run_status_assertion(connection, assertion, context)
    if assertion_type == "replay_no_failed_spans":
        return _evaluate_replay_no_failed_spans_assertion(connection, assertion, context)
    if assertion_type == "replay_span_count_at_least":
        return _evaluate_replay_span_count_assertion(connection, assertion, context)
    if assertion_type == "replay_handoff_count_at_least":
        return _evaluate_replay_handoff_count_assertion(connection, assertion, context)
    if assertion_type == "unsupported_assertion_preset":
        preset = assertion.get("preset")
        return {
            "type": "unsupported_assertion_preset",
            "passed": False,
            "reason": f"unsupported_assertion_preset:{preset}",
            "preset": preset,
            "supported_presets": list(SUPPORTED_ASSERTION_PRESETS),
        }
    return {
        "type": assertion_type,
        "passed": False,
        "reason": f"unsupported_assertion_type:{assertion_type}",
    }


def _evaluate_status_assertion(
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    observed_status = context["observed_status"]
    failure_statuses = context["failure_statuses"]
    replay_row = context["replay_row"]
    replay_target = context["replay_target"]
    replay_observed_status = context["replay_observed_status"]
    if replay_target is not None:
        passed = (
            observed_status in failure_statuses
            and replay_observed_status is not None
            and replay_observed_status not in failure_statuses
            and replay_row is not None
            and replay_row["status"] == "passed"
        )
        comparison = "fail_before_pass_after" if passed else "before_after_not_improved"
        reason = "replay_target_status_is_acceptable" if passed else "replay_target_status_is_failure_or_missing"
    else:
        passed = observed_status is not None and observed_status not in failure_statuses
        comparison = "single_target_status"
        reason = "target_status_is_acceptable" if passed else "target_status_is_failure_or_missing"
    return {
        "type": assertion.get("type", "target_status_not_failed"),
        "passed": passed,
        "reason": reason,
        "comparison": comparison,
        "observed_status": observed_status,
        "replay_observed_status": replay_observed_status,
    }


def _evaluate_replay_target_field_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    replay_target = context["replay_target"]
    if not isinstance(replay_target, dict):
        return {
            "type": "replay_target_field_equals",
            "passed": False,
            "reason": "replay_target_missing",
        }
    row = _resolve_check_entity(
        connection,
        replay_target.get("entity_type"),
        replay_target.get("entity_id"),
    )
    return _field_equals_result(
        assertion=assertion,
        assertion_type="replay_target_field_equals",
        row=row,
        missing_reason="replay_target_not_found",
    )


def _evaluate_replay_entity_field_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    entity_type = assertion.get("entity_type")
    if not isinstance(entity_type, str):
        return {
            "type": "replay_entity_field_equals",
            "passed": False,
            "reason": "entity_type_required",
        }
    entity_id = assertion.get("entity_id")
    output_run_id = _replay_output_run_id(context)
    candidates = _replay_entity_candidates(
        connection,
        entity_type=entity_type,
        output_run_id=output_run_id,
        entity_id=entity_id if isinstance(entity_id, str) else None,
    )
    match = assertion.get("match", {})
    if isinstance(match, dict) and match:
        candidates = [row for row in candidates if _matches_fields(row, match)]
    row = candidates[0] if candidates else None
    return _field_equals_result(
        assertion=assertion,
        assertion_type="replay_entity_field_equals",
        row=row,
        missing_reason=f"replay_entity_not_found:{entity_type}",
    )


def _evaluate_replay_run_status_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    expected = assertion.get("equals", "succeeded")
    output_run_id = _replay_output_run_id(context)
    row = _resolve_check_entity(connection, "run", output_run_id)
    actual = row.get("status") if row is not None else None
    passed = actual == expected
    return {
        "type": "replay_run_status_equals",
        "passed": passed,
        "reason": "run_status_equals" if passed else "run_status_mismatch",
        "entity": {"id": output_run_id},
        "expected": expected,
        "actual": actual,
    }


def _evaluate_replay_no_failed_spans_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    output_run_id = _replay_output_run_id(context)
    spans = _replay_spans(connection, output_run_id)
    failure_statuses = set(assertion.get("failure_statuses", sorted(FAILURE_STATUSES)))
    failed = [
        span
        for span in spans
        if span.get("status") in failure_statuses
    ]
    passed = output_run_id is not None and not failed
    return {
        "type": "replay_no_failed_spans",
        "passed": passed,
        "reason": "no_failed_spans" if passed else "failed_spans_present",
        "entity": {"id": output_run_id},
        "expected": 0,
        "actual": len(failed),
        "failed_span_ids": [span.get("id") for span in failed],
    }


def _evaluate_replay_span_count_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    output_run_id = _replay_output_run_id(context)
    minimum = _minimum_count(assertion, default=1)
    actual = len(_replay_spans(connection, output_run_id))
    passed = output_run_id is not None and actual >= minimum
    return {
        "type": "replay_span_count_at_least",
        "passed": passed,
        "reason": "span_count_sufficient" if passed else "span_count_too_low",
        "entity": {"id": output_run_id},
        "expected": minimum,
        "actual": actual,
    }


def _evaluate_replay_handoff_count_assertion(
    connection: sqlite3.Connection,
    assertion: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    output_run_id = _replay_output_run_id(context)
    minimum = _minimum_count(assertion, default=1)
    actual = len(_replay_handoffs(connection, output_run_id))
    passed = output_run_id is not None and actual >= minimum
    return {
        "type": "replay_handoff_count_at_least",
        "passed": passed,
        "reason": "handoff_count_sufficient" if passed else "handoff_count_too_low",
        "entity": {"id": output_run_id},
        "expected": minimum,
        "actual": actual,
    }


def _field_equals_result(
    *,
    assertion: dict[str, Any],
    assertion_type: str,
    row: Optional[dict[str, Any]],
    missing_reason: str,
) -> dict[str, Any]:
    path = assertion.get("path")
    if not isinstance(path, str) or not path:
        return {
            "type": assertion_type,
            "passed": False,
            "reason": "path_required",
        }
    expected = assertion.get("equals")
    if row is None:
        return {
            "type": assertion_type,
            "passed": False,
            "reason": missing_reason,
            "path": path,
            "expected": expected,
            "actual": None,
        }
    actual = _field_value(row, path)
    passed = actual == expected
    return {
        "type": assertion_type,
        "passed": passed,
        "reason": "field_equals" if passed else "field_mismatch",
        "entity": {
            "id": row.get("id"),
        },
        "path": path,
        "expected": expected,
        "actual": actual,
    }


def _replay_output_run_id(context: dict[str, Any]) -> Optional[str]:
    replay_row = context.get("replay_row")
    if replay_row is not None and replay_row["output_ref"] is not None:
        return str(replay_row["output_ref"])
    replay_result = context.get("replay_result")
    if isinstance(replay_result, dict):
        output_run_id = replay_result.get("output_run_id")
        return output_run_id if isinstance(output_run_id, str) else None
    return None


def _replay_entity_candidates(
    connection: sqlite3.Connection,
    *,
    entity_type: str,
    output_run_id: Optional[str],
    entity_id: Optional[str],
) -> list[dict[str, Any]]:
    if entity_id:
        row = _resolve_check_entity(connection, entity_type, entity_id)
        return [row] if row is not None else []
    if entity_type == "run":
        row = _resolve_check_entity(connection, "run", output_run_id)
        return [row] if row is not None else []
    if not isinstance(output_run_id, str) or not output_run_id:
        return []
    table = {
        "span": "spans",
        "handoff": "handoffs",
    }.get(entity_type)
    if table is None:
        return []
    return _all(
        connection,
        f"SELECT * FROM {table} WHERE run_id = ? ORDER BY id",
        (output_run_id,),
    )


def _replay_spans(connection: sqlite3.Connection, output_run_id: Optional[str]) -> list[dict[str, Any]]:
    if not isinstance(output_run_id, str) or not output_run_id:
        return []
    return _all(
        connection,
        "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id",
        (output_run_id,),
    )


def _replay_handoffs(connection: sqlite3.Connection, output_run_id: Optional[str]) -> list[dict[str, Any]]:
    if not isinstance(output_run_id, str) or not output_run_id:
        return []
    return _all(
        connection,
        "SELECT * FROM handoffs WHERE run_id = ? ORDER BY created_at, id",
        (output_run_id,),
    )


def _minimum_count(assertion: dict[str, Any], *, default: int) -> int:
    raw_value = assertion.get("min", assertion.get("minimum", default))
    if isinstance(raw_value, int) and raw_value >= 0:
        return raw_value
    return default


def _definition_min_count(
    definition: dict[str, Any],
    key: str,
    alternate_key: str,
    *,
    default: int,
) -> int:
    raw_value = definition.get(key, definition.get(alternate_key, default))
    if isinstance(raw_value, int) and raw_value >= 0:
        return raw_value
    return default


def _resolve_check_entity(
    connection: sqlite3.Connection,
    entity_type: Any,
    entity_id: Any,
) -> Optional[dict[str, Any]]:
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return None
    table = {
        "run": "runs",
        "span": "spans",
        "handoff": "handoffs",
        "task": "tasks",
        "task_attempt": "task_attempts",
    }.get(entity_type)
    if table is None:
        return None
    row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    return _decode_row(row) if row is not None else None


def _matches_fields(row: dict[str, Any], fields: dict[str, Any]) -> bool:
    return all(_field_value(row, path) == expected for path, expected in fields.items() if isinstance(path, str))


def _field_value(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if 0 <= index < len(current) else None
            continue
        return None
    return current


def _replay_target(
    target: dict[str, Any],
    replay_result: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    if not isinstance(replay_result, dict):
        return None
    target_map = replay_result.get("target_map")
    if not isinstance(target_map, dict):
        return None
    entity_id = target.get("entity_id")
    entity_type = target.get("entity_type")
    if not isinstance(entity_id, str) or not isinstance(entity_type, str):
        return None
    mapped = target_map.get(entity_id)
    if not isinstance(mapped, str) or not mapped:
        return None
    return {
        "entity_type": entity_type,
        "entity_id": mapped,
        "source": "replay_target_map",
        "baseline_entity_id": entity_id,
    }


def _target_status(connection: sqlite3.Connection, target: dict[str, Any]) -> Optional[str]:
    entity_type = target.get("entity_type")
    entity_id = target.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return None
    table_by_type = {
        "run": "runs",
        "span": "spans",
        "task": "tasks",
        "task_attempt": "task_attempts",
    }
    table = table_by_type.get(entity_type)
    if table is None:
        return None
    row = connection.execute(f"SELECT status FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    return str(row["status"]) if row is not None else None


def _one(connection: sqlite3.Connection, query: str, args: tuple[Any, ...]) -> dict[str, Any]:
    row = connection.execute(query, args).fetchone()
    return _decode_row(row) if row is not None else {}


def _all(connection: sqlite3.Connection, query: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [_decode_row(row) for row in connection.execute(query, args).fetchall()]


def _maybe_promote_trust_level(
    connection: sqlite3.Connection,
    check_spec: sqlite3.Row,
    latest_status: str,
    result: dict[str, Any],
    now: str,
) -> Optional[str]:
    check_type = str(check_spec["check_type"])
    if check_type not in GATEABLE_CHECK_TYPES:
        return None
    if _check_spec_is_human_locked(connection, str(check_spec["id"])):
        return None

    current_trust_level = str(check_spec["trust_level"])
    if (
        latest_status == "passed"
        and result.get("comparison") == "fail_before_pass_after"
        and result.get("replay_side_effect_mode") in SAFE_REPLAY_SIDE_EFFECT_MODES
        and current_trust_level not in {"L2_regression", "L3_human_approved"}
    ):
        connection.execute(
            "UPDATE check_specs SET trust_level = ?, updated_at = ? WHERE id = ?",
            ("L2_regression", now, check_spec["id"]),
        )
        return "L2_regression"

    if check_type != "deterministic_assertion":
        return None
    if current_trust_level != "L0_generated":
        return None
    if latest_status not in {"passed", "failed"}:
        return None

    rows = connection.execute(
        """
        SELECT status
        FROM check_runs
        WHERE check_spec_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 2
        """,
        (check_spec["id"],),
    ).fetchall()
    statuses = [str(row["status"]) for row in rows]
    if len(statuses) < 2 or any(status != latest_status for status in statuses):
        return None

    connection.execute(
        "UPDATE check_specs SET trust_level = ?, updated_at = ? WHERE id = ?",
        ("L1_repeated", now, check_spec["id"]),
    )
    return "L1_repeated"


def _check_spec_is_human_locked(connection: sqlite3.Connection, check_spec_id: str) -> bool:
    try:
        row = connection.execute(
            """
            SELECT human_locked
            FROM check_locks
            WHERE check_spec_id = ?
            """,
            (check_spec_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return False
    return row is not None and int(row["human_locked"]) == 1


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise CheckError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise CheckError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CheckError(f"{path}: expected JSON object")
    return payload


def _next_numbered_id(
    connection: sqlite3.Connection,
    *,
    table: str,
    prefix: str,
    where_column: str,
    where_value: str,
) -> str:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE {where_column} = ?",
        (where_value,),
    ).fetchone()
    count = int(row["count"]) if row is not None else 0
    return f"{prefix}_{count + 1:03d}"


def _row_exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (row_id,)).fetchone()
    return row is not None


def _mark_replay_errored(db_path: Path, replay_run_id: str, error: str) -> None:
    now = utc_now()
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT profile_id, result_json FROM replay_runs WHERE id = ?",
            (replay_run_id,),
        ).fetchone()
        if row is None:
            return
        result = _json_loads(row["result_json"], {})
        if not isinstance(result, dict):
            result = {}
        result["error"] = error
        connection.execute(
            """
            UPDATE replay_runs
            SET status = ?, ended_at = ?, result_json = ?, updated_at = ?
            WHERE id = ?
            """,
            ("errored", now, _json_dumps(result), now, replay_run_id),
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{replay_run_id}_errored",
            profile_id=str(row["profile_id"]),
            entity_type="replay_run",
            entity_id=replay_run_id,
            kind="replay_run_errored",
            at=now,
            metadata={"error": error},
        )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise CheckError(f"missing_required_string:{key}")
    return value


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key, value in list(payload.items()):
        if key.endswith("_json") and isinstance(value, str):
            payload[key[:-5]] = _json_loads(value, None)
            del payload[key]
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
