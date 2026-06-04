from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .autonomy_runner import AutonomyRunError, run_autonomy
from .evals import EvalError, generate_evals_for_proposal
from .operator_adapters import OperatorAdapterError, run_registered_operator_adapter
from .operator_prompts import write_operator_prompt_artifacts
from .profiles import list_profiles
from .replay_adapters import ReplayAdapterError, run_registered_replay_adapter
from .storage import StorageError, connect


class ProfileNextError(Exception):
    """Raised when a profile next-step action cannot be planned or run."""


@dataclass(frozen=True)
class ProfileNextReport:
    profile_id: str
    run_requested: bool
    action: str
    status: str
    reason: str
    routing_before: dict[str, Any]
    routing_after: dict[str, Any]
    result: Optional[dict[str, Any]]
    notes: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        suggested_commands = self.routing_after.get("suggested_commands")
        if not isinstance(suggested_commands, list):
            suggested_commands = []
        return {
            "profile_id": self.profile_id,
            "run_requested": self.run_requested,
            "action": self.action,
            "status": self.status,
            "reason": self.reason,
            "routing_before": self.routing_before,
            "routing_after": self.routing_after,
            "result": self.result,
            "notes": list(self.notes),
            "suggested_commands": suggested_commands,
        }


def run_profile_next_step(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    run: bool = False,
    replay_adapter_id: Optional[str] = None,
    replay_output_dir: Optional[Path] = None,
    replay_timeout_seconds: Optional[int] = None,
    harness_workspace_root: Optional[Path] = None,
    operator_adapter_id: Optional[str] = None,
    operator_target: Optional[str] = None,
    operator_output_dir: Optional[Path] = None,
    operator_timeout_seconds: Optional[int] = None,
    operator_max_retries: int = 0,
    schema_path: Optional[Path] = None,
) -> ProfileNextReport:
    selected_profile = _selected_profile(db_path, profile_id)
    selected_profile_id = str(selected_profile["id"])
    routing = selected_profile.get("routing") if isinstance(selected_profile.get("routing"), dict) else {}
    action = str(routing.get("next_action") or "unknown")

    if not run:
        return ProfileNextReport(
            profile_id=selected_profile_id,
            run_requested=False,
            action=action,
            status="planned",
            reason="dry_run",
            routing_before=routing,
            routing_after=routing,
            result=None,
        )

    state = str(routing.get("state") or "")
    if state == "needs_eval_generation":
        proposal_id = _required_routing_value(routing, "proposal_id")
        try:
            report = generate_evals_for_proposal(db_path=db_path, proposal_id=proposal_id)
        except (EvalError, StorageError) as exc:
            raise ProfileNextError(str(exc)) from exc
        return _executed_report(
            db_path=db_path,
            profile_id=selected_profile_id,
            action=action,
            routing_before=routing,
            reason="generated_eval_specs",
            result={
                "proposal_id": report.proposal_id,
                "profile_id": report.profile_id,
                "eval_spec_ids": list(report.eval_spec_ids),
                "existing_eval_spec_ids": list(report.existing_eval_spec_ids),
            },
        )

    if state == "needs_analysis":
        run_id = _optional_routing_value(routing, "run_id")
        selected_adapter_id = operator_adapter_id
        if selected_adapter_id is None and operator_target is None:
            selected_adapter_id = _default_operator_adapter_id(db_path, selected_profile_id)
        if selected_adapter_id is not None:
            try:
                report = run_registered_operator_adapter(
                    db_path=db_path,
                    adapter_id=selected_adapter_id,
                    output_dir=operator_output_dir,
                    profile_id=selected_profile_id,
                    run_id=run_id,
                    schema_path=schema_path,
                    timeout_seconds=operator_timeout_seconds,
                    max_retries=operator_max_retries,
                )
            except (OperatorAdapterError, StorageError) as exc:
                raise ProfileNextError(str(exc)) from exc
            return _executed_report(
                db_path=db_path,
                profile_id=selected_profile_id,
                action=action,
                routing_before=routing,
                reason="ran_operator_adapter",
                result=_operator_report_payload(report, adapter_id=selected_adapter_id),
            )

        resolved_operator_target = _resolve_operator_target(db_path, selected_profile_id, operator_target)
        try:
            report = write_operator_prompt_artifacts(
                db_path=db_path,
                output_dir=operator_output_dir or _operator_output_dir(db_path, selected_profile_id),
                target=resolved_operator_target,
                profile_id=selected_profile_id,
                run_id=run_id,
                schema_path=schema_path,
            )
        except StorageError as exc:
            raise ProfileNextError(str(exc)) from exc
        return _executed_report(
            db_path=db_path,
            profile_id=selected_profile_id,
            action=action,
            routing_before=routing,
            reason="prepared_operator_prompt",
            result={
                "target": report.target,
                "profile_id": report.profile_id,
                "evidence_path": str(report.evidence_path),
                "prompt_path": str(report.prompt_path),
                "schema_path": str(report.schema_path) if report.schema_path is not None else None,
            },
        )

    if state == "needs_replay_or_eval":
        eval_spec_id = _required_routing_value(routing, "eval_spec_id")
        adapter_id = replay_adapter_id or _default_replay_adapter_id(db_path, selected_profile_id)
        if adapter_id is None:
            return _blocked_report(
                db_path=db_path,
                profile_id=selected_profile_id,
                action=action,
                routing_before=routing,
                reason="replay_adapter_required",
                notes=("register a replay adapter or pass replay_adapter_id",),
            )
        try:
            report = run_registered_replay_adapter(
                db_path=db_path,
                adapter_id=adapter_id,
                eval_spec_id=eval_spec_id,
                output_dir=replay_output_dir,
                timeout_seconds=replay_timeout_seconds,
                run_eval_after=True,
            )
        except (EvalError, ReplayAdapterError, StorageError) as exc:
            raise ProfileNextError(str(exc)) from exc
        return _executed_report(
            db_path=db_path,
            profile_id=selected_profile_id,
            action=action,
            routing_before=routing,
            reason="ran_replay_adapter",
            result=_replay_report_payload(report, adapter_id=adapter_id),
        )

    if state == "ready_for_autonomy" and action == "run_autonomy":
        resolved_harness_workspace_root = harness_workspace_root
        if str(routing.get("proposal_section") or "") == "harness":
            if not bool(routing.get("harness_repo_patch_allowed", False)):
                return _blocked_report(
                    db_path=db_path,
                    profile_id=selected_profile_id,
                    action=action,
                    routing_before=routing,
                    reason="repo_patch_not_allowed",
                    notes=("enable repo patch policy with policy-set --repo-patch on",),
                )
            resolved_harness_workspace_root, workspace_blocker = _resolve_harness_workspace_root(
                selected_profile,
                harness_workspace_root,
            )
            if resolved_harness_workspace_root is None:
                return _blocked_report(
                    db_path=db_path,
                    profile_id=selected_profile_id,
                    action=action,
                    routing_before=routing,
                    reason=workspace_blocker or "harness_workspace_root_required",
                    notes=("pass --harness-workspace-root or set an existing profile root_path",),
                )
        try:
            report = run_autonomy(
                db_path=db_path,
                profile_id=selected_profile_id,
                harness_workspace_root=resolved_harness_workspace_root,
            )
        except (AutonomyRunError, StorageError) as exc:
            raise ProfileNextError(str(exc)) from exc
        return _executed_report(
            db_path=db_path,
            profile_id=selected_profile_id,
            action=action,
            routing_before=routing,
            reason="ran_autonomy",
            result=report.to_json(),
        )

    if state in {"loop_complete", "monitor"}:
        return _skipped_report(
            db_path=db_path,
            profile_id=selected_profile_id,
            action=action,
            routing_before=routing,
            reason="no_action_required",
        )

    return _blocked_report(
        db_path=db_path,
        profile_id=selected_profile_id,
        action=action,
        routing_before=routing,
        reason=_blocked_reason_for_state(state, action),
    )


def _selected_profile(db_path: Path, profile_id: Optional[str]) -> dict[str, Any]:
    profiles = list_profiles(db_path)
    if profile_id is None:
        if not profiles:
            raise ProfileNextError("no_profiles_found")
        return profiles[0]
    for profile in profiles:
        if profile.get("id") == profile_id:
            return profile
    raise ProfileNextError(f"profile_not_found:{profile_id}")


def _required_routing_value(routing: dict[str, Any], key: str) -> str:
    value = routing.get(key)
    if not isinstance(value, str) or not value:
        raise ProfileNextError(f"routing_{key}_missing")
    return value


def _optional_routing_value(routing: dict[str, Any], key: str) -> Optional[str]:
    value = routing.get(key)
    return value if isinstance(value, str) and value else None


def _default_replay_adapter_id(db_path: Path, profile_id: str) -> Optional[str]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM replay_adapters
            WHERE profile_id = ?
              AND enabled = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
    return str(row["id"]) if row is not None else None


def _default_operator_adapter_id(db_path: Path, profile_id: str) -> Optional[str]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM operator_adapters
            WHERE profile_id = ?
              AND enabled = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
    return str(row["id"]) if row is not None else None


def _resolve_operator_target(db_path: Path, profile_id: str, operator_target: Optional[str]) -> str:
    if isinstance(operator_target, str) and operator_target:
        return operator_target
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT operator_kind
            FROM operator_adapters
            WHERE profile_id = ?
              AND enabled = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
    if row is not None and isinstance(row["operator_kind"], str) and row["operator_kind"]:
        return str(row["operator_kind"])
    return "generic"


def _operator_output_dir(db_path: Path, profile_id: str) -> Path:
    return db_path.parent / "operator-prompts" / profile_id


def _resolve_harness_workspace_root(
    profile: dict[str, Any],
    override: Optional[Path],
) -> tuple[Optional[Path], Optional[str]]:
    if override is not None:
        workspace_root = override.expanduser()
    else:
        root_path = profile.get("root_path")
        if not isinstance(root_path, str) or not root_path:
            return None, "harness_workspace_root_required"
        workspace_root = Path(root_path).expanduser()
    if not workspace_root.exists():
        return None, f"harness_workspace_root_not_found:{workspace_root}"
    if not workspace_root.is_dir():
        return None, f"harness_workspace_root_not_directory:{workspace_root}"
    return workspace_root, None


def _executed_report(
    *,
    db_path: Path,
    profile_id: str,
    action: str,
    routing_before: dict[str, Any],
    reason: str,
    result: dict[str, Any],
) -> ProfileNextReport:
    return ProfileNextReport(
        profile_id=profile_id,
        run_requested=True,
        action=action,
        status="executed",
        reason=reason,
        routing_before=routing_before,
        routing_after=_routing_for_profile(db_path, profile_id),
        result=result,
    )


def _blocked_report(
    *,
    db_path: Path,
    profile_id: str,
    action: str,
    routing_before: dict[str, Any],
    reason: str,
    notes: tuple[str, ...] = (),
) -> ProfileNextReport:
    return ProfileNextReport(
        profile_id=profile_id,
        run_requested=True,
        action=action,
        status="blocked",
        reason=reason,
        routing_before=routing_before,
        routing_after=_routing_for_profile(db_path, profile_id),
        result=None,
        notes=notes,
    )


def _skipped_report(
    *,
    db_path: Path,
    profile_id: str,
    action: str,
    routing_before: dict[str, Any],
    reason: str,
) -> ProfileNextReport:
    return ProfileNextReport(
        profile_id=profile_id,
        run_requested=True,
        action=action,
        status="skipped",
        reason=reason,
        routing_before=routing_before,
        routing_after=_routing_for_profile(db_path, profile_id),
        result=None,
    )


def _routing_for_profile(db_path: Path, profile_id: str) -> dict[str, Any]:
    return _selected_profile(db_path, profile_id).get("routing", {})


def _blocked_reason_for_state(state: str, action: str) -> str:
    if state == "setup_sources":
        return "source_import_required"
    if state == "needs_analysis":
        return "operator_analysis_required"
    if state == "ready_for_autonomy" and action == "review_proposal":
        return "human_review_required"
    return f"unsupported_next_step:{state or 'unknown'}:{action or 'unknown'}"


def _replay_report_payload(report: object, *, adapter_id: str) -> dict[str, Any]:
    completion = getattr(report, "completion")
    eval_run = getattr(report, "eval_run", None)
    proposal_id = getattr(report, "proposal_id", None)
    if proposal_id is None and eval_run is not None:
        proposal_id = getattr(eval_run, "proposal_id", None)
    return {
        "adapter_id": adapter_id,
        "replay_run_id": getattr(report, "replay_run_id"),
        "profile_id": getattr(report, "profile_id"),
        "proposal_id": proposal_id,
        "eval_spec_id": getattr(report, "eval_spec_id"),
        "output_run_id": completion.output_run_id,
        "status": completion.status,
        "eval_run": _eval_run_payload(eval_run) if eval_run is not None else None,
    }


def _operator_report_payload(report: object, *, adapter_id: str) -> dict[str, Any]:
    raw_output_path = getattr(report, "raw_output_path", None)
    return {
        "adapter_id": adapter_id,
        "operator": getattr(report, "operator"),
        "profile_id": getattr(report, "profile_id"),
        "proposal_id": getattr(report, "proposal_id"),
        "operator_run_id": getattr(report, "operator_run_id"),
        "evidence_path": str(getattr(report, "evidence_path")),
        "prompt_path": str(getattr(report, "prompt_path")),
        "proposal_path": str(getattr(report, "proposal_path")),
        "persisted": getattr(report, "persisted"),
        "attempts": getattr(report, "attempts"),
        "raw_output_path": str(raw_output_path) if raw_output_path is not None else None,
    }


def _eval_run_payload(eval_run: object) -> dict[str, Any]:
    return {
        "eval_run_id": getattr(eval_run, "eval_run_id"),
        "profile_id": getattr(eval_run, "profile_id"),
        "proposal_id": getattr(eval_run, "proposal_id"),
        "eval_spec_id": getattr(eval_run, "eval_spec_id"),
        "replay_run_id": getattr(eval_run, "replay_run_id"),
        "status": getattr(eval_run, "status"),
        "result": getattr(eval_run, "result"),
        "promoted_trust_level": getattr(eval_run, "promoted_trust_level"),
    }
