from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .apply import (
    ApplyError,
    apply_context_proposal,
    rollback_context_delivery_rule_revision,
    rollback_skill_revision,
)
from .autonomy import AutonomyError, get_autonomy_policy
from .checks import CheckError, GATEABLE_CHECK_TYPES, generate_checks_for_proposal
from .harness import (
    HarnessError,
    apply_patch_transaction,
    list_harness_target_locks,
    prepare_harness_proposal,
    rollback_patch_transaction,
)
from .storage import StorageError, connect, initialize_database, utc_now


TRUST_ORDER = {
    "L0_generated": 0,
    "L1_repeated": 1,
    "L2_regression": 2,
    "L3_human_approved": 3,
}


class AutonomyRunError(Exception):
    """Raised when an autonomy run cannot be started."""


@dataclass(frozen=True)
class CheckGateStatus:
    passed: bool
    reason: str
    required_check_level: str
    check_spec_ids: tuple[str, ...] = ()
    check_run_ids: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "required_check_level": self.required_check_level,
            "check_spec_ids": list(self.check_spec_ids),
            "check_run_ids": list(self.check_run_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class AutonomyDecision:
    proposal_id: str
    profile_id: str
    section: str
    state_before: str
    state_after: str
    action: str
    reason: str
    required_check_level: Optional[str] = None
    check_spec_ids: tuple[str, ...] = ()
    check_run_ids: tuple[str, ...] = ()
    applied_skill_ids: tuple[str, ...] = ()
    applied_context_rule_ids: tuple[str, ...] = ()
    patch_transaction_ids: tuple[str, ...] = ()
    detail: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "profile_id": self.profile_id,
            "section": self.section,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "action": self.action,
            "reason": self.reason,
            "required_check_level": self.required_check_level,
            "check_spec_ids": list(self.check_spec_ids),
            "check_run_ids": list(self.check_run_ids),
            "applied_skill_ids": list(self.applied_skill_ids),
            "applied_context_rule_ids": list(self.applied_context_rule_ids),
            "patch_transaction_ids": list(self.patch_transaction_ids),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class AutonomyRunReport:
    profile_id: str
    policy: dict[str, Any]
    decisions: tuple[AutonomyDecision, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "policy": self.policy,
            "decisions": [decision.to_json() for decision in self.decisions],
        }


def run_autonomy(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    harness_workspace_root: Optional[Path] = None,
) -> AutonomyRunReport:
    initialize_database(db_path)
    try:
        policy = get_autonomy_policy(db_path=db_path, profile_id=profile_id)
    except AutonomyError as exc:
        raise AutonomyRunError(str(exc)) from exc

    selected_profile_id = str(policy["profile_id"])
    decision_list = []
    if policy["rollback_on_regression"]:
        for proposal_id in _regressed_context_proposal_ids(db_path, selected_profile_id):
            decision = _handle_context_regression(db_path, proposal_id)
            _record_autonomy_decision(db_path, decision)
            decision_list.append(decision)
        for proposal_id in _regressed_harness_proposal_ids(db_path, selected_profile_id):
            decision = _handle_harness_regression(db_path, proposal_id)
            _record_autonomy_decision(db_path, decision)
            decision_list.append(decision)

    proposal_ids = _candidate_proposal_ids(db_path, selected_profile_id)
    for proposal_id in proposal_ids:
        decision = _handle_proposal(
            db_path,
            proposal_id,
            harness_workspace_root=harness_workspace_root,
        )
        _record_autonomy_decision(db_path, decision)
        decision_list.append(decision)
    decisions = tuple(decision_list)
    final_policy = get_autonomy_policy(db_path=db_path, profile_id=selected_profile_id)
    return AutonomyRunReport(
        profile_id=selected_profile_id,
        policy=final_policy,
        decisions=decisions,
    )


def inspect_proposal_autonomy_gate(*, db_path: Path, proposal_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    proposal = _get_proposal(db_path, proposal_id)
    profile_id = str(proposal["profile_id"])
    section = str(proposal["section"])
    state = str(proposal["state"])
    try:
        policy = get_autonomy_policy(db_path=db_path, profile_id=profile_id)
    except AutonomyError as exc:
        raise AutonomyRunError(str(exc)) from exc
    base = {
        "proposal_id": proposal_id,
        "profile_id": profile_id,
        "section": section,
        "state": state,
        "mutates": False,
        "policy": {
            "context_mode": policy["context_mode"],
            "harness_mode": policy["harness_mode"],
            "allow_skillbook_write": policy["allow_skillbook_write"],
            "allow_repo_patch": policy["allow_repo_patch"],
            "required_check_level_context": policy["required_check_level_context"],
            "required_check_level_harness": policy["required_check_level_harness"],
        },
    }

    if state in {"applied", "rolled_back", "failed"}:
        return {
            **base,
            "action": f"already_{state}",
            "reason": f"terminal_state:{state}",
        }
    if section == "context":
        return _inspect_context_gate(db_path, proposal, policy, base)
    if section == "harness":
        return _inspect_harness_gate(db_path, proposal, policy, base)
    return {
        **base,
        "action": "skipped",
        "reason": f"unsupported_section:{section}",
    }


def _handle_proposal(
    db_path: Path,
    proposal_id: str,
    *,
    harness_workspace_root: Optional[Path] = None,
) -> AutonomyDecision:
    proposal = _get_proposal(db_path, proposal_id)
    section = str(proposal["section"])
    if section == "context":
        return _handle_context_proposal(db_path, proposal)
    if section == "harness":
        return _handle_harness_proposal(
            db_path,
            proposal,
            harness_workspace_root=harness_workspace_root,
        )
    return _decision(
        proposal=proposal,
        state_after=str(proposal["state"]),
        action="skipped",
        reason=f"unsupported_section:{section}",
    )


def _handle_context_regression(db_path: Path, proposal_id: str) -> AutonomyDecision:
    proposal = _get_proposal(db_path, proposal_id)
    profile_id = str(proposal["profile_id"])
    regression = _latest_failed_check_run_for_proposal(db_path, proposal_id)
    if regression is None:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="skipped",
            reason="no_regression_check_failure",
        )

    check_spec_ids = (str(regression["check_spec_id"]),)
    check_run_ids = (str(regression["id"]),)
    revision_rows = _skill_revision_rows_for_proposal(db_path, proposal_id)
    revision_ids = tuple(str(row["id"]) for row in revision_rows)
    rule_revision_rows = _context_delivery_rule_revision_rows_for_proposal(db_path, proposal_id)
    rule_revision_ids = tuple(str(row["id"]) for row in rule_revision_rows)
    if not revision_rows and not rule_revision_rows:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="blocked",
            reason="no_context_revisions_to_rollback",
            check_spec_ids=check_spec_ids,
            check_run_ids=check_run_ids,
        )

    blocker = _skill_revision_rollback_blocker(db_path, revision_rows)
    if blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="blocked",
            reason=blocker,
            check_spec_ids=check_spec_ids,
            check_run_ids=check_run_ids,
            detail={"skill_revision_ids": list(revision_ids)},
        )
    rule_blocker = _context_delivery_rule_revision_rollback_blocker(db_path, rule_revision_rows)
    if rule_blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="blocked",
            reason=rule_blocker,
            check_spec_ids=check_spec_ids,
            check_run_ids=check_run_ids,
            detail={
                "skill_revision_ids": list(revision_ids),
                "context_delivery_rule_revision_ids": list(rule_revision_ids),
            },
        )

    rollback_revision_ids: list[str] = []
    rollback_rule_revision_ids: list[str] = []
    try:
        for row in rule_revision_rows:
            report = rollback_context_delivery_rule_revision(db_path=db_path, revision_id=str(row["id"]))
            rollback_rule_revision_ids.append(report.rollback_revision_id)
        for row in revision_rows:
            report = rollback_skill_revision(db_path=db_path, revision_id=str(row["id"]))
            rollback_revision_ids.append(report.rollback_revision_id)
    except (ApplyError, StorageError) as exc:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_regression_rollback_failed",
            metadata={
                "section": "context",
                "reason": str(exc),
                "check_spec_id": regression["check_spec_id"],
                "check_run_id": regression["id"],
                "skill_revision_ids": list(revision_ids),
                "context_delivery_rule_revision_ids": list(rule_revision_ids),
            },
        )
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="failed",
            reason=f"regression_rollback_failed:{exc}",
            check_spec_ids=check_spec_ids,
            check_run_ids=check_run_ids,
            detail={
                "skill_revision_ids": list(revision_ids),
                "context_delivery_rule_revision_ids": list(rule_revision_ids),
            },
        )

    state_after = _mark_proposal_failed_regression(
        db_path,
        proposal_id,
        section="context",
        check_spec_id=str(regression["check_spec_id"]),
        check_run_id=str(regression["id"]),
        patch_transaction_ids=(),
    )
    _record_autonomy_event(
        db_path,
        proposal_id=proposal_id,
        profile_id=profile_id,
        kind="autonomy_regression_rolled_back",
        metadata={
            "section": "context",
            "reason": "regression_check_failed",
            "check_spec_id": regression["check_spec_id"],
            "check_run_id": regression["id"],
            "skill_revision_ids": list(revision_ids),
            "rollback_revision_ids": rollback_revision_ids,
            "context_delivery_rule_revision_ids": list(rule_revision_ids),
            "rollback_context_delivery_rule_revision_ids": rollback_rule_revision_ids,
        },
    )
    return _decision(
        proposal=proposal,
        state_after=state_after,
        action="rolled_back",
        reason=f"regression_check_failed:{regression['id']}",
        check_spec_ids=check_spec_ids,
        check_run_ids=check_run_ids,
        detail={
            "regression": {
                "check_spec_id": str(regression["check_spec_id"]),
                "check_run_id": str(regression["id"]),
                "status": str(regression["status"]),
            },
            "skill_revision_ids": list(revision_ids),
            "rollback_revision_ids": rollback_revision_ids,
            "context_delivery_rule_revision_ids": list(rule_revision_ids),
            "rollback_context_delivery_rule_revision_ids": rollback_rule_revision_ids,
        },
    )


def _handle_harness_regression(db_path: Path, proposal_id: str) -> AutonomyDecision:
    proposal = _get_proposal(db_path, proposal_id)
    profile_id = str(proposal["profile_id"])
    regression = _latest_failed_check_run_for_proposal(db_path, proposal_id)
    if regression is None:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="skipped",
            reason="no_regression_check_failure",
        )

    patch_rows = _rollbackable_patch_transactions_for_proposal(db_path, proposal_id)
    patch_transaction_ids = tuple(str(row["id"]) for row in patch_rows)
    if not patch_rows:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="blocked",
            reason="no_applied_patch_transactions_to_rollback",
            check_spec_ids=(str(regression["check_spec_id"]),),
            check_run_ids=(str(regression["id"]),),
        )

    lock_blocker = _harness_target_lock_blocker(db_path, profile_id, patch_rows)
    if lock_blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=str(proposal["state"]),
            action="blocked",
            reason=lock_blocker,
            check_spec_ids=(str(regression["check_spec_id"]),),
            check_run_ids=(str(regression["id"]),),
            patch_transaction_ids=patch_transaction_ids,
        )

    root_by_patch_id: dict[str, Path] = {}
    for row in patch_rows:
        if str(row["status"]) != "applied":
            return _decision(
                proposal=proposal,
                state_after=str(proposal["state"]),
                action="blocked",
                reason=f"patch_transaction_not_applied:{row['id']}:{row['status']}",
                check_spec_ids=(str(regression["check_spec_id"]),),
                check_run_ids=(str(regression["id"]),),
                patch_transaction_ids=patch_transaction_ids,
            )
        rollback = row.get("rollback")
        if not isinstance(rollback, dict) or rollback.get("available") is not True:
            return _decision(
                proposal=proposal,
                state_after=str(proposal["state"]),
                action="blocked",
                reason=f"rollback_not_available:{row['id']}",
                check_spec_ids=(str(regression["check_spec_id"]),),
                check_run_ids=(str(regression["id"]),),
                patch_transaction_ids=patch_transaction_ids,
            )
        workspace_root = rollback.get("workspace_root")
        if not isinstance(workspace_root, str) or not workspace_root:
            return _decision(
                proposal=proposal,
                state_after=str(proposal["state"]),
                action="blocked",
                reason=f"rollback_workspace_root_missing:{row['id']}",
                check_spec_ids=(str(regression["check_spec_id"]),),
                check_run_ids=(str(regression["id"]),),
                patch_transaction_ids=patch_transaction_ids,
            )
        root_by_patch_id[str(row["id"])] = Path(workspace_root)

    try:
        for row in reversed(patch_rows):
            rollback_patch_transaction(
                db_path=db_path,
                patch_transaction_id=str(row["id"]),
                workspace_root=root_by_patch_id[str(row["id"])],
            )
    except (HarnessError, StorageError) as exc:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_regression_rollback_failed",
            metadata={
                "section": "harness",
                "reason": str(exc),
                "check_spec_id": regression["check_spec_id"],
                "check_run_id": regression["id"],
                "patch_transaction_ids": list(patch_transaction_ids),
            },
        )
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="failed",
            reason=f"regression_rollback_failed:{exc}",
            check_spec_ids=(str(regression["check_spec_id"]),),
            check_run_ids=(str(regression["id"]),),
            patch_transaction_ids=patch_transaction_ids,
        )

    state_after = _mark_proposal_failed_regression(
        db_path,
        proposal_id,
        section="harness",
        check_spec_id=str(regression["check_spec_id"]),
        check_run_id=str(regression["id"]),
        patch_transaction_ids=patch_transaction_ids,
    )
    _record_autonomy_event(
        db_path,
        proposal_id=proposal_id,
        profile_id=profile_id,
        kind="autonomy_regression_rolled_back",
        metadata={
            "section": "harness",
            "reason": "regression_check_failed",
            "check_spec_id": regression["check_spec_id"],
            "check_run_id": regression["id"],
            "patch_transaction_ids": list(patch_transaction_ids),
        },
    )
    return _decision(
        proposal=proposal,
        state_after=state_after,
        action="rolled_back",
        reason=f"regression_check_failed:{regression['id']}",
        check_spec_ids=(str(regression["check_spec_id"]),),
        check_run_ids=(str(regression["id"]),),
        patch_transaction_ids=patch_transaction_ids,
        detail={
            "regression": {
                "check_spec_id": str(regression["check_spec_id"]),
                "check_run_id": str(regression["id"]),
                "status": str(regression["status"]),
            }
        },
    )


def _handle_context_proposal(db_path: Path, proposal: dict[str, Any]) -> AutonomyDecision:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    policy = get_autonomy_policy(db_path=db_path, profile_id=profile_id)
    state_before = str(proposal["state"])

    if policy["context_mode"] == "off":
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="skipped",
            reason="context_policy_off",
        )
    if policy["context_mode"] == "propose":
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="awaiting_human_review",
            reason="context_policy_propose",
        )
    if not policy["allow_skillbook_write"]:
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="blocked",
            reason="skillbook_write_not_allowed",
        )

    requirements = _gate_requirements(proposal, policy, section="context")
    if requirements["blocked_reason"] is not None:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_blocked",
            metadata={"reason": requirements["blocked_reason"], "section": "context"},
        )
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="blocked",
            reason=str(requirements["blocked_reason"]),
            required_check_level=str(requirements["required_check_level"]),
        )

    generated_check_spec_ids: tuple[str, ...] = ()
    existing_check_spec_ids: tuple[str, ...] = ()
    generated_check_spec_ids, existing_check_spec_ids, check_generation_blocker = (
        _generate_missing_check_specs(db_path, proposal_id)
    )
    if check_generation_blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason=check_generation_blocker,
            required_check_level=str(requirements["required_check_level"]),
        )

    gate = _evaluate_check_gate(
        db_path=db_path,
        proposal_id=proposal_id,
        required_check_level=str(requirements["required_check_level"]),
        requires_replay=bool(requirements["requires_replay"]),
    )
    check_spec_ids = tuple(dict.fromkeys(generated_check_spec_ids + existing_check_spec_ids + gate.check_spec_ids))
    if not gate.passed:
        state_after = _mark_proposal_gated(db_path, proposal_id, gate.reason, section="context")
        return _decision(
            proposal=proposal,
            state_after=state_after,
            action="gated",
            reason=gate.reason,
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            detail=gate.detail,
        )

    try:
        report = apply_context_proposal(
            db_path=db_path,
            proposal_id=proposal_id,
            allowed_states=("pending",),
        )
    except (ApplyError, StorageError) as exc:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_apply_failed",
            metadata={"reason": str(exc), "section": "context"},
        )
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="failed",
            reason=f"apply_failed:{exc}",
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
        )

    _record_autonomy_event(
        db_path,
        proposal_id=proposal_id,
        profile_id=profile_id,
        kind="autonomy_applied",
        metadata={
            "section": "context",
            "required_check_level": gate.required_check_level,
            "check_spec_ids": list(check_spec_ids),
            "check_run_ids": list(gate.check_run_ids),
            "applied_skill_ids": list(report.applied_skill_ids),
            "applied_context_rule_ids": list(report.applied_context_rule_ids),
        },
    )
    return _decision(
        proposal=proposal,
        state_after=report.state,
        action="applied",
        reason="check_gate_passed",
        required_check_level=gate.required_check_level,
        check_spec_ids=check_spec_ids,
        check_run_ids=gate.check_run_ids,
        applied_skill_ids=report.applied_skill_ids,
        applied_context_rule_ids=report.applied_context_rule_ids,
        detail=gate.detail,
    )


def _inspect_context_gate(
    db_path: Path,
    proposal: dict[str, Any],
    policy: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    if policy["context_mode"] == "off":
        return {**base, "action": "skipped", "reason": "context_policy_off"}
    if policy["context_mode"] == "propose":
        return {**base, "action": "awaiting_human_review", "reason": "context_policy_propose"}
    if not policy["allow_skillbook_write"]:
        return {**base, "action": "blocked", "reason": "skillbook_write_not_allowed"}

    requirements = _gate_requirements(proposal, policy, section="context")
    if requirements["blocked_reason"] is not None:
        return {
            **base,
            "action": "blocked",
            "reason": str(requirements["blocked_reason"]),
            "required_check_level": requirements["required_check_level"],
            "requires_replay": requirements["requires_replay"],
        }

    gate = _evaluate_check_gate(
        db_path=db_path,
        proposal_id=str(proposal["id"]),
        required_check_level=str(requirements["required_check_level"]),
        requires_replay=bool(requirements["requires_replay"]),
    )
    return {
        **base,
        "action": "would_apply" if gate.passed else "gated",
        "reason": "check_gate_passed" if gate.passed else gate.reason,
        "required_check_level": gate.required_check_level,
        "requires_replay": requirements["requires_replay"],
        "check_gate": gate.to_json(),
    }


def _inspect_harness_gate(
    db_path: Path,
    proposal: dict[str, Any],
    policy: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    if policy["harness_mode"] == "off":
        return {**base, "action": "skipped", "reason": "harness_policy_off"}
    if policy["harness_mode"] == "propose":
        return {**base, "action": "awaiting_human_review", "reason": "harness_policy_propose"}

    requirements = _gate_requirements(proposal, policy, section="harness")
    if requirements["blocked_reason"] is not None:
        return {
            **base,
            "action": "blocked",
            "reason": str(requirements["blocked_reason"]),
            "required_check_level": requirements["required_check_level"],
            "requires_replay": requirements["requires_replay"],
        }

    proposal_id = str(proposal["id"])
    patch_rows = _patch_transactions_for_proposal(db_path, proposal_id)
    patch_transaction_ids = tuple(str(row["id"]) for row in patch_rows)
    gate = _evaluate_check_gate(
        db_path=db_path,
        proposal_id=proposal_id,
        required_check_level=str(requirements["required_check_level"]),
        requires_replay=bool(requirements["requires_replay"]),
    )
    if not gate.passed:
        return {
            **base,
            "action": "gated",
            "reason": gate.reason,
            "required_check_level": gate.required_check_level,
            "requires_replay": requirements["requires_replay"],
            "check_gate": gate.to_json(),
            "patch_transaction_ids": list(patch_transaction_ids),
        }

    eligibility_reason = _harness_patch_apply_blocker(patch_rows) if patch_rows else None
    if eligibility_reason is not None:
        return {
            **base,
            "action": "blocked",
            "reason": eligibility_reason,
            "required_check_level": gate.required_check_level,
            "requires_replay": requirements["requires_replay"],
            "check_gate": gate.to_json(),
            "patch_transaction_ids": list(patch_transaction_ids),
        }
    lock_reason = _harness_target_lock_blocker(db_path, str(proposal["profile_id"]), patch_rows)
    if lock_reason is not None:
        return {
            **base,
            "action": "blocked",
            "reason": lock_reason,
            "required_check_level": gate.required_check_level,
            "requires_replay": requirements["requires_replay"],
            "check_gate": gate.to_json(),
            "patch_transaction_ids": list(patch_transaction_ids),
        }
    if not policy["allow_repo_patch"]:
        return {
            **base,
            "action": "blocked",
            "reason": "repo_patch_not_allowed",
            "required_check_level": gate.required_check_level,
            "requires_replay": requirements["requires_replay"],
            "check_gate": gate.to_json(),
            "patch_transaction_ids": list(patch_transaction_ids),
        }

    return {
        **base,
        "action": "would_apply" if patch_transaction_ids else "would_prepare_then_apply",
        "reason": "check_gate_passed",
        "required_check_level": gate.required_check_level,
        "requires_replay": requirements["requires_replay"],
        "check_gate": gate.to_json(),
        "patch_transaction_ids": list(patch_transaction_ids),
    }


def _handle_harness_proposal(
    db_path: Path,
    proposal: dict[str, Any],
    *,
    harness_workspace_root: Optional[Path] = None,
) -> AutonomyDecision:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    policy = get_autonomy_policy(db_path=db_path, profile_id=profile_id)
    state_before = str(proposal["state"])

    if policy["harness_mode"] == "off":
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="skipped",
            reason="harness_policy_off",
        )
    if policy["harness_mode"] == "propose":
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="awaiting_human_review",
            reason="harness_policy_propose",
        )

    requirements = _gate_requirements(proposal, policy, section="harness")
    if requirements["blocked_reason"] is not None:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_blocked",
            metadata={"reason": requirements["blocked_reason"], "section": "harness"},
        )
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="blocked",
            reason=str(requirements["blocked_reason"]),
            required_check_level=str(requirements["required_check_level"]),
        )

    generated_check_spec_ids: tuple[str, ...] = ()
    existing_check_spec_ids: tuple[str, ...] = ()
    generated_check_spec_ids, existing_check_spec_ids, check_generation_blocker = (
        _generate_missing_check_specs(db_path, proposal_id)
    )
    if check_generation_blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason=check_generation_blocker,
            required_check_level=str(requirements["required_check_level"]),
        )

    patch_transaction_ids = _patch_transaction_ids_for_proposal(db_path, proposal_id)
    if not patch_transaction_ids:
        try:
            report = prepare_harness_proposal(db_path=db_path, proposal_id=proposal_id)
        except (HarnessError, StorageError) as exc:
            return _decision(
                proposal=proposal,
                state_after=_proposal_state(db_path, proposal_id),
                action="blocked",
                reason=f"harness_prepare_failed:{exc}",
                required_check_level=str(requirements["required_check_level"]),
            )
        patch_transaction_ids = report.patch_transaction_ids
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_harness_prepared",
            metadata={
                "section": "harness",
                "patch_transaction_ids": list(report.patch_transaction_ids),
                "reason": "prepared_before_autonomous_harness_check_gate",
            },
        )

    gate = _evaluate_check_gate(
        db_path=db_path,
        proposal_id=proposal_id,
        required_check_level=str(requirements["required_check_level"]),
        requires_replay=bool(requirements["requires_replay"]),
    )
    check_spec_ids = tuple(dict.fromkeys(generated_check_spec_ids + existing_check_spec_ids + gate.check_spec_ids))
    if not gate.passed:
        state_after = _mark_proposal_gated(db_path, proposal_id, gate.reason, section="harness")
        return _decision(
            proposal=proposal,
            state_after=state_after,
            action="gated",
            reason=gate.reason,
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            patch_transaction_ids=patch_transaction_ids,
            detail=gate.detail,
        )

    if not policy["allow_repo_patch"]:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_blocked",
            metadata={"reason": "repo_patch_not_allowed", "section": "harness"},
        )
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason="repo_patch_not_allowed",
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            patch_transaction_ids=patch_transaction_ids,
            detail=gate.detail,
        )

    patch_rows = _patch_transactions_for_proposal(db_path, proposal_id)
    patch_blocker = _harness_patch_apply_blocker(patch_rows)
    if patch_blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason=patch_blocker,
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            patch_transaction_ids=patch_transaction_ids,
            detail=gate.detail,
        )

    lock_blocker = _harness_target_lock_blocker(db_path, profile_id, patch_rows)
    if lock_blocker is not None:
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason=lock_blocker,
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            patch_transaction_ids=patch_transaction_ids,
            detail=gate.detail,
        )

    workspace_root, workspace_blocker = _resolve_harness_workspace_root(
        db_path,
        profile_id,
        harness_workspace_root,
    )
    if workspace_root is None:
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason=str(workspace_blocker),
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            patch_transaction_ids=patch_transaction_ids,
            detail=gate.detail,
        )

    ready_patch_ids = tuple(str(row["id"]) for row in patch_rows if str(row["status"]) == "ready")
    try:
        for patch_transaction_id in ready_patch_ids:
            apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id=patch_transaction_id,
                workspace_root=workspace_root,
            )
    except (HarnessError, StorageError) as exc:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_apply_failed",
            metadata={"reason": str(exc), "section": "harness"},
        )
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="failed",
            reason=f"harness_apply_failed:{exc}",
            required_check_level=gate.required_check_level,
            check_spec_ids=check_spec_ids,
            check_run_ids=gate.check_run_ids,
            patch_transaction_ids=patch_transaction_ids,
            detail=gate.detail,
        )

    state_after = _mark_proposal_applied(db_path, proposal_id, section="harness")
    _record_autonomy_event(
        db_path,
        proposal_id=proposal_id,
        profile_id=profile_id,
        kind="autonomy_harness_applied",
        metadata={
            "section": "harness",
            "required_check_level": gate.required_check_level,
            "check_spec_ids": list(check_spec_ids),
            "check_run_ids": list(gate.check_run_ids),
            "patch_transaction_ids": list(patch_transaction_ids),
            "workspace_root": str(workspace_root.resolve()),
        },
    )
    return _decision(
        proposal=proposal,
        state_after=state_after,
        action="applied",
        reason="check_gate_passed",
        required_check_level=gate.required_check_level,
        check_spec_ids=check_spec_ids,
        check_run_ids=gate.check_run_ids,
        patch_transaction_ids=patch_transaction_ids,
        detail=gate.detail,
    )


def _gate_requirements(
    proposal: dict[str, Any],
    policy: dict[str, Any],
    *,
    section: str,
) -> dict[str, Any]:
    expectations = _json_loads(proposal.get("gate_expectations_json"), {})
    if not isinstance(expectations, dict):
        expectations = {}

    blocked_reason = None
    allowed_section = expectations.get("allowed_autonomy_section")
    if allowed_section == "none":
        blocked_reason = "proposal_disallows_autonomy"
    elif isinstance(allowed_section, str) and allowed_section != section:
        blocked_reason = f"autonomy_section_mismatch:{allowed_section}"

    requires_human_review = expectations.get("requires_human_review") is True
    if requires_human_review:
        # No human-approval proposal state exists in the collapsed model; proposals that
        # demand human review are never auto-applied by the autonomy runner.
        blocked_reason = "human_review_required"

    policy_key = f"required_check_level_{section}"
    policy_level = str(policy.get(policy_key) or "L1_repeated")
    proposal_level = expectations.get("requires_check_level")
    required_check_level = _stricter_level(
        policy_level,
        proposal_level if isinstance(proposal_level, str) else None,
    )
    return {
        "blocked_reason": blocked_reason,
        "required_check_level": required_check_level,
        "requires_replay": expectations.get("requires_replay") is True,
    }


def _evaluate_check_gate(
    *,
    db_path: Path,
    proposal_id: str,
    required_check_level: str,
    requires_replay: bool,
) -> CheckGateStatus:
    check_specs = _check_specs_for_proposal(db_path, proposal_id)
    if not check_specs:
        return CheckGateStatus(
            passed=False,
            reason="missing_check_specs",
            required_check_level=required_check_level,
        )

    accepted_run_ids: list[str] = []
    blocked: list[dict[str, Any]] = []
    with connect(db_path) as connection:
        for check_spec in check_specs:
            check_spec_id = str(check_spec["id"])
            check_type = str(check_spec["check_type"])
            if check_type not in GATEABLE_CHECK_TYPES:
                blocked.append(
                    {
                        "check_spec_id": check_spec_id,
                        "reason": f"unsupported_gate_check_type:{check_type}",
                    }
                )
                continue
            latest = connection.execute(
                """
                SELECT *
                FROM check_runs
                WHERE check_spec_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (check_spec_id,),
            ).fetchone()
            if latest is None:
                blocked.append({"check_spec_id": check_spec_id, "reason": "missing_check_run"})
                continue
            if str(latest["status"]) != "passed":
                blocked.append(
                    {
                        "check_spec_id": check_spec_id,
                        "check_run_id": latest["id"],
                        "reason": f"latest_check_not_passed:{latest['status']}",
                    }
                )
                continue
            trust_level = str(check_spec["trust_level"])
            if not _trust_at_least(trust_level, required_check_level):
                blocked.append(
                    {
                        "check_spec_id": check_spec_id,
                        "check_run_id": latest["id"],
                        "reason": f"insufficient_check_trust:{trust_level}",
                    }
                )
                continue
            if requires_replay:
                replay_run_id = latest["replay_run_id"]
                if replay_run_id is None:
                    blocked.append(
                        {
                            "check_spec_id": check_spec_id,
                            "check_run_id": latest["id"],
                            "reason": "replay_required",
                        }
                    )
                    continue
                replay = connection.execute(
                    "SELECT status FROM replay_runs WHERE id = ?",
                    (replay_run_id,),
                ).fetchone()
                if replay is None or str(replay["status"]) != "passed":
                    blocked.append(
                        {
                            "check_spec_id": check_spec_id,
                            "check_run_id": latest["id"],
                            "replay_run_id": replay_run_id,
                            "reason": "replay_not_passed",
                        }
                    )
                    continue
            accepted_run_ids.append(str(latest["id"]))

    if blocked:
        return CheckGateStatus(
            passed=False,
            reason=str(blocked[0]["reason"]),
            required_check_level=required_check_level,
            check_spec_ids=tuple(str(row["id"]) for row in check_specs),
            check_run_ids=tuple(
                str(item["check_run_id"])
                for item in blocked
                if isinstance(item.get("check_run_id"), str)
            ),
            detail={"blocked": blocked, "requires_replay": requires_replay},
        )
    return CheckGateStatus(
        passed=True,
        reason="check_gate_passed",
        required_check_level=required_check_level,
        check_spec_ids=tuple(str(row["id"]) for row in check_specs),
        check_run_ids=tuple(accepted_run_ids),
        detail={"requires_replay": requires_replay},
    )


def _candidate_proposal_ids(db_path: Path, profile_id: str) -> tuple[str, ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM learning_proposals
            WHERE profile_id = ?
              AND state = 'pending'
            ORDER BY created_at, id
            """,
            (profile_id,),
        ).fetchall()
    return tuple(str(row["id"]) for row in rows)


def _regressed_harness_proposal_ids(db_path: Path, profile_id: str) -> tuple[str, ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM learning_proposals
            WHERE profile_id = ?
              AND section = 'harness'
              AND state = 'applied'
            ORDER BY updated_at, id
            """,
            (profile_id,),
        ).fetchall()
    return tuple(
        str(row["id"])
        for row in rows
        if _latest_failed_check_run_for_proposal(db_path, str(row["id"])) is not None
    )


def _regressed_context_proposal_ids(db_path: Path, profile_id: str) -> tuple[str, ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM learning_proposals
            WHERE profile_id = ?
              AND section = 'context'
              AND state = 'applied'
            ORDER BY updated_at, id
            """,
            (profile_id,),
        ).fetchall()
    return tuple(
        str(row["id"])
        for row in rows
        if _latest_failed_check_run_for_proposal(db_path, str(row["id"])) is not None
    )


def _get_proposal(db_path: Path, proposal_id: str) -> dict[str, Any]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    if row is None:
        raise AutonomyRunError(f"proposal_not_found:{proposal_id}")
    return dict(row)


def _proposal_state(db_path: Path, proposal_id: str) -> str:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT state FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    if row is None:
        raise AutonomyRunError(f"proposal_not_found:{proposal_id}")
    return str(row["state"])


def _mark_proposal_gated(db_path: Path, proposal_id: str, reason: str, *, section: str) -> str:
    # The collapsed 3+1 model has no "gated" proposal state: a failed check gate is recorded
    # as evidence (autonomy event) but the proposal stays "pending" until it is applied,
    # rolled back, or failed. This records the gate event and returns the unchanged state.
    with connect(db_path) as connection:
        proposal = connection.execute(
            "SELECT id, profile_id, state FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise AutonomyRunError(f"proposal_not_found:{proposal_id}")
        profile_id = str(proposal["profile_id"])
        state = str(proposal["state"])
        now = utc_now()
        _insert_autonomy_event(
            connection,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_gated",
            at=now,
            metadata={"reason": reason, "section": section},
        )
    return state


def _mark_proposal_applied(db_path: Path, proposal_id: str, *, section: str) -> str:
    with connect(db_path) as connection:
        proposal = connection.execute(
            "SELECT id, profile_id FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise AutonomyRunError(f"proposal_not_found:{proposal_id}")
        now = utc_now()
        connection.execute(
            "UPDATE learning_proposals SET state = ?, updated_at = ? WHERE id = ?",
            ("applied", now, proposal_id),
        )
        _insert_autonomy_event(
            connection,
            proposal_id=proposal_id,
            profile_id=str(proposal["profile_id"]),
            kind="autonomy_applied",
            at=now,
            metadata={"section": section},
        )
    return "applied"


def _mark_proposal_failed_regression(
    db_path: Path,
    proposal_id: str,
    *,
    section: str,
    check_spec_id: str,
    check_run_id: str,
    patch_transaction_ids: tuple[str, ...],
) -> str:
    with connect(db_path) as connection:
        proposal = connection.execute(
            "SELECT id, profile_id FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if proposal is None:
            raise AutonomyRunError(f"proposal_not_found:{proposal_id}")
        now = utc_now()
        connection.execute(
            "UPDATE learning_proposals SET state = ?, updated_at = ? WHERE id = ?",
            ("failed", now, proposal_id),
        )
        _insert_autonomy_event(
            connection,
            proposal_id=proposal_id,
            profile_id=str(proposal["profile_id"]),
            kind="autonomy_regression_failed",
            at=now,
            metadata={
                "section": section,
                "check_spec_id": check_spec_id,
                "check_run_id": check_run_id,
                "patch_transaction_ids": list(patch_transaction_ids),
            },
        )
    return "failed"


def _record_autonomy_event(
    db_path: Path,
    *,
    proposal_id: str,
    profile_id: str,
    kind: str,
    metadata: dict[str, Any],
) -> None:
    with connect(db_path) as connection:
        _insert_autonomy_event(
            connection,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind=kind,
            at=utc_now(),
            metadata=metadata,
        )


def _record_autonomy_decision(db_path: Path, decision: AutonomyDecision) -> None:
    _record_autonomy_event(
        db_path,
        proposal_id=decision.proposal_id,
        profile_id=decision.profile_id,
        kind="autonomy_decision",
        metadata={
            **decision.to_json(),
            "decision_kind": "gate_decision",
        },
    )


def _insert_autonomy_event(
    connection: sqlite3.Connection,
    *,
    proposal_id: str,
    profile_id: str,
    kind: str,
    at: str,
    metadata: dict[str, Any],
) -> None:
    _ensure_kyoko_source(connection, profile_id)
    count_row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM timeline_events
        WHERE entity_type = 'learning_proposal'
          AND entity_id = ?
          AND kind LIKE 'autonomy_%'
        """,
        (proposal_id,),
    ).fetchone()
    count = int(count_row["count"]) if count_row is not None else 0
    connection.execute(
        """
        INSERT INTO timeline_events (
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
            f"event_{proposal_id}_autonomy_{count + 1:03d}",
            profile_id,
            f"source_kyoko_{profile_id}",
            "learning_proposal",
            proposal_id,
            kind,
            at,
            None,
            None,
            _json_dumps(metadata),
        ),
    )


def _ensure_kyoko_source(connection: sqlite3.Connection, profile_id: str) -> None:
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
            _json_dumps({"autonomy": True}),
            now,
        ),
    )


def _check_specs_for_proposal(db_path: Path, proposal_id: str) -> tuple[dict[str, Any], ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM check_specs
            WHERE proposal_id = ?
              AND status = 'active'
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _patch_transaction_ids_for_proposal(db_path: Path, proposal_id: str) -> tuple[str, ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM patch_transactions
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(str(row["id"]) for row in rows)


def _patch_transactions_for_proposal(db_path: Path, proposal_id: str) -> tuple[dict[str, Any], ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, status, patch_kind, target_paths_json
            FROM patch_transactions
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(
        {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "patch_kind": str(row["patch_kind"]),
            "target_paths": _json_loads(row["target_paths_json"], []),
        }
        for row in rows
    )


def _rollbackable_patch_transactions_for_proposal(
    db_path: Path,
    proposal_id: str,
) -> tuple[dict[str, Any], ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, status, patch_kind, target_paths_json, rollback_json
            FROM patch_transactions
            WHERE proposal_id = ?
              AND status = 'applied'
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(
        {
            "id": str(row["id"]),
            "status": str(row["status"]),
            "patch_kind": str(row["patch_kind"]),
            "target_paths": _json_loads(row["target_paths_json"], []),
            "rollback": _json_loads(row["rollback_json"], {}),
        }
        for row in rows
    )


def _skill_revision_rows_for_proposal(db_path: Path, proposal_id: str) -> tuple[dict[str, Any], ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT rowid, id, skill_id, operation, before_json
            FROM skill_revisions
            WHERE proposal_id = ?
              AND operation != 'rollback'
            ORDER BY rowid DESC
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _context_delivery_rule_revision_rows_for_proposal(
    db_path: Path,
    proposal_id: str,
) -> tuple[dict[str, Any], ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT rowid, id, rule_id, operation, before_json
            FROM context_delivery_rule_revisions
            WHERE proposal_id = ?
              AND operation != 'rollback'
            ORDER BY rowid DESC
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(dict(row) for row in rows)


def _skill_revision_rollback_blocker(
    db_path: Path,
    revision_rows: tuple[dict[str, Any], ...],
) -> Optional[str]:
    with connect(db_path) as connection:
        seen_skill_ids: set[str] = set()
        for row in revision_rows:
            revision_id = str(row["id"])
            skill_id = str(row["skill_id"])
            if skill_id in seen_skill_ids:
                return f"multiple_skill_revisions_for_skill:{skill_id}"
            seen_skill_ids.add(skill_id)
            latest = connection.execute(
                "SELECT id FROM skill_revisions WHERE skill_id = ? ORDER BY rowid DESC LIMIT 1",
                (skill_id,),
            ).fetchone()
            if latest is None or str(latest["id"]) != revision_id:
                return f"skill_revision_not_latest:{revision_id}"
            skill = connection.execute(
                "SELECT human_locked FROM skills WHERE id = ?",
                (skill_id,),
            ).fetchone()
            if skill is None:
                return f"skill_not_found:{skill_id}"
            if int(skill["human_locked"]) == 1:
                return f"human_locked_skill:{skill_id}"
            if str(row["operation"]) != "create":
                before = _json_loads(row.get("before_json"), None)
                if not isinstance(before, dict):
                    return f"skill_revision_before_missing:{revision_id}"
    return None


def _context_delivery_rule_revision_rollback_blocker(
    db_path: Path,
    revision_rows: tuple[dict[str, Any], ...],
) -> Optional[str]:
    with connect(db_path) as connection:
        seen_rule_ids: set[str] = set()
        for row in revision_rows:
            revision_id = str(row["id"])
            rule_id = str(row["rule_id"])
            if rule_id in seen_rule_ids:
                return f"multiple_context_delivery_rule_revisions_for_rule:{rule_id}"
            seen_rule_ids.add(rule_id)
            latest = connection.execute(
                """
                SELECT id
                FROM context_delivery_rule_revisions
                WHERE rule_id = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (rule_id,),
            ).fetchone()
            if latest is None or str(latest["id"]) != revision_id:
                return f"context_delivery_rule_revision_not_latest:{revision_id}"
            rule = connection.execute(
                "SELECT human_locked FROM context_delivery_rules WHERE id = ?",
                (rule_id,),
            ).fetchone()
            if rule is None:
                return f"context_delivery_rule_not_found:{rule_id}"
            if int(rule["human_locked"]) == 1:
                return f"human_locked_context_delivery_rule:{rule_id}"
            if str(row["operation"]) != "create":
                before = _json_loads(row.get("before_json"), None)
                if not isinstance(before, dict):
                    return f"context_delivery_rule_revision_before_missing:{revision_id}"
    return None


def _latest_failed_check_run_for_proposal(db_path: Path, proposal_id: str) -> Optional[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
              er.*,
              es.id AS linked_check_spec_id
            FROM check_specs AS es
            JOIN check_runs AS er ON er.check_spec_id = es.id
            WHERE es.proposal_id = ?
              AND es.status = 'active'
              AND er.id = (
                SELECT latest.id
                FROM check_runs AS latest
                WHERE latest.check_spec_id = es.id
                ORDER BY latest.created_at DESC, latest.id DESC
                LIMIT 1
              )
            ORDER BY er.created_at DESC, er.id DESC
            """,
            (proposal_id,),
        ).fetchall()
    for row in rows:
        if str(row["status"]) == "failed":
            payload = dict(row)
            payload["check_spec_id"] = str(row["linked_check_spec_id"])
            return payload
    return None


def _harness_patch_apply_blocker(patch_rows: tuple[dict[str, Any], ...]) -> Optional[str]:
    if not patch_rows:
        return "harness_patch_transaction_missing"
    for row in patch_rows:
        patch_id = str(row["id"])
        status = str(row["status"])
        patch_kind = str(row["patch_kind"])
        if status not in {"ready", "applied"}:
            return f"harness_patch_transaction_not_ready:{patch_id}:{status}"
        if status == "ready" and patch_kind not in {"generated_file", "unified_diff"}:
            return f"harness_patch_kind_requires_manual_review:{patch_kind}"
    return None


def _harness_target_lock_blocker(
    db_path: Path,
    profile_id: str,
    patch_rows: tuple[dict[str, Any], ...],
) -> Optional[str]:
    locked_paths = {
        str(row["target_path"])
        for row in list_harness_target_locks(db_path, profile_id=profile_id)
        if row.get("human_locked")
    }
    if not locked_paths:
        return None
    for row in patch_rows:
        target_paths = row.get("target_paths")
        if not isinstance(target_paths, list):
            continue
        for target_path in target_paths:
            if str(target_path) in locked_paths:
                return f"human_locked_harness_target:{target_path}"
    return None


def _resolve_harness_workspace_root(
    db_path: Path,
    profile_id: str,
    override: Optional[Path],
) -> tuple[Optional[Path], Optional[str]]:
    if override is not None:
        workspace_root = override.expanduser()
    else:
        root_path = _profile_root_path(db_path, profile_id)
        if not root_path:
            return None, "harness_workspace_root_required"
        workspace_root = Path(root_path).expanduser()

    if not workspace_root.exists():
        return None, f"harness_workspace_root_not_found:{workspace_root}"
    if not workspace_root.is_dir():
        return None, f"harness_workspace_root_not_directory:{workspace_root}"
    return workspace_root, None


def _profile_root_path(db_path: Path, profile_id: str) -> Optional[str]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT root_path FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
    if row is None:
        raise AutonomyRunError(f"profile_not_found:{profile_id}")
    root_path = row["root_path"]
    if isinstance(root_path, str) and root_path:
        return root_path
    return None


def _generate_missing_check_specs(
    db_path: Path,
    proposal_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...], Optional[str]]:
    if _check_specs_for_proposal(db_path, proposal_id):
        return (), (), None
    try:
        generated = generate_checks_for_proposal(db_path=db_path, proposal_id=proposal_id)
    except CheckError as exc:
        if str(exc).startswith("no_check_spec_changes:"):
            return (), (), None
        return (), (), f"check_generation_failed:{exc}"
    except StorageError as exc:
        return (), (), f"check_generation_failed:{exc}"
    return generated.check_spec_ids, generated.existing_check_spec_ids, None


def _decision(
    *,
    proposal: dict[str, Any],
    state_after: str,
    action: str,
    reason: str,
    required_check_level: Optional[str] = None,
    check_spec_ids: tuple[str, ...] = (),
    check_run_ids: tuple[str, ...] = (),
    applied_skill_ids: tuple[str, ...] = (),
    applied_context_rule_ids: tuple[str, ...] = (),
    patch_transaction_ids: tuple[str, ...] = (),
    detail: Optional[dict[str, Any]] = None,
) -> AutonomyDecision:
    return AutonomyDecision(
        proposal_id=str(proposal["id"]),
        profile_id=str(proposal["profile_id"]),
        section=str(proposal["section"]),
        state_before=str(proposal["state"]),
        state_after=state_after,
        action=action,
        reason=reason,
        required_check_level=required_check_level,
        check_spec_ids=check_spec_ids,
        check_run_ids=check_run_ids,
        applied_skill_ids=applied_skill_ids,
        applied_context_rule_ids=applied_context_rule_ids,
        patch_transaction_ids=patch_transaction_ids,
        detail=detail or {},
    )


def _stricter_level(left: str, right: Optional[str]) -> str:
    normalized_left = left if left in TRUST_ORDER else "L1_repeated"
    if right is None or right not in TRUST_ORDER:
        return normalized_left
    left_score = TRUST_ORDER[normalized_left]
    right_score = TRUST_ORDER[right]
    return normalized_left if left_score >= right_score else right


def _trust_at_least(actual: str, required: str) -> bool:
    return TRUST_ORDER.get(actual, -1) >= TRUST_ORDER.get(required, TRUST_ORDER["L1_repeated"])


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
