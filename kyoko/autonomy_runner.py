from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .apply import ApplyError, apply_context_proposal
from .autonomy import AutonomyError, get_autonomy_policy, is_autonomous
from .harness import (
    HarnessError,
    apply_patch_transaction,
    prepare_harness_proposal,
)
from .storage import StorageError, connect, initialize_database, utc_now


class AutonomyRunError(Exception):
    """Raised when an autonomy run cannot be started."""


@dataclass(frozen=True)
class AutonomyDecision:
    proposal_id: str
    profile_id: str
    section: str
    state_before: str
    state_after: str
    action: str
    reason: str
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
    """Automatic apply pass (autonomous gate #2).

    In ``hitl`` mode this applies nothing — every pending proposal is left untouched with an
    ``awaiting_human_review`` decision; a human applies via a separate entrypoint. In
    ``autonomous`` mode each pending proposal is auto-applied (gate #2 ``autonomous_auto_apply``).
    There is no check gate, no trust level, and no replay here; regression/rollback is handled
    by a separate guard monitor.
    """

    initialize_database(db_path)
    try:
        policy = get_autonomy_policy(db_path=db_path, profile_id=profile_id)
    except AutonomyError as exc:
        raise AutonomyRunError(str(exc)) from exc

    selected_profile_id = str(policy["profile_id"])
    decision_list: list[AutonomyDecision] = []
    for proposal_id in _candidate_proposal_ids(db_path, selected_profile_id):
        decision = _handle_proposal(
            db_path,
            proposal_id,
            policy=policy,
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
            "mode": policy["mode"],
            "recurrence_threshold": policy["recurrence_threshold"],
            "allow_repo_patch": policy["allow_repo_patch"],
        },
    }

    if state in {"applied", "rolled_back", "failed"}:
        return {
            **base,
            "action": f"already_{state}",
            "reason": f"terminal_state:{state}",
        }
    if section == "context":
        return _inspect_context_gate(policy, base)
    if section == "harness":
        return _inspect_harness_gate(policy, base)
    return {
        **base,
        "action": "skipped",
        "reason": f"unsupported_section:{section}",
    }


def _handle_proposal(
    db_path: Path,
    proposal_id: str,
    *,
    policy: dict[str, Any],
    harness_workspace_root: Optional[Path] = None,
) -> AutonomyDecision:
    proposal = _get_proposal(db_path, proposal_id)
    section = str(proposal["section"])
    if section == "context":
        return _handle_context_proposal(db_path, proposal, policy)
    if section == "harness":
        return _handle_harness_proposal(
            db_path,
            proposal,
            policy,
            harness_workspace_root=harness_workspace_root,
        )
    return _decision(
        proposal=proposal,
        state_after=str(proposal["state"]),
        action="skipped",
        reason=f"unsupported_section:{section}",
    )


def _handle_context_proposal(
    db_path: Path,
    proposal: dict[str, Any],
    policy: dict[str, Any],
) -> AutonomyDecision:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    state_before = str(proposal["state"])

    if not is_autonomous(policy):
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="awaiting_human_review",
            reason="hitl_awaiting_human_approve",
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
        )

    _record_autonomy_event(
        db_path,
        proposal_id=proposal_id,
        profile_id=profile_id,
        kind="autonomy_applied",
        metadata={
            "section": "context",
            "applied_skill_ids": list(report.applied_skill_ids),
            "applied_context_rule_ids": list(report.applied_context_rule_ids),
        },
    )
    return _decision(
        proposal=proposal,
        state_after=report.state,
        action="applied",
        reason="autonomous_auto_apply",
        applied_skill_ids=report.applied_skill_ids,
        applied_context_rule_ids=report.applied_context_rule_ids,
    )


def _handle_harness_proposal(
    db_path: Path,
    proposal: dict[str, Any],
    policy: dict[str, Any],
    *,
    harness_workspace_root: Optional[Path] = None,
) -> AutonomyDecision:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    state_before = str(proposal["state"])

    if not is_autonomous(policy):
        return _decision(
            proposal=proposal,
            state_after=state_before,
            action="awaiting_human_review",
            reason="hitl_awaiting_human_approve",
        )

    # Prepare patch transactions if they don't exist yet.
    patch_transaction_ids = _patch_transaction_ids_for_proposal(db_path, proposal_id)
    if not patch_transaction_ids:
        try:
            prepare_report = prepare_harness_proposal(db_path=db_path, proposal_id=proposal_id)
        except (HarnessError, StorageError) as exc:
            return _decision(
                proposal=proposal,
                state_after=_proposal_state(db_path, proposal_id),
                action="blocked",
                reason=f"harness_prepare_failed:{exc}",
            )
        patch_transaction_ids = prepare_report.patch_transaction_ids
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_harness_prepared",
            metadata={
                "section": "harness",
                "patch_transaction_ids": list(patch_transaction_ids),
            },
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
            patch_transaction_ids=patch_transaction_ids,
        )

    # apply_patch_transaction enforces the repo_patch capability fence, path/protected-path
    # fence, harness-target locks, and the dirty-worktree policy internally (harness.py).
    ready_patch_ids = _ready_patch_transaction_ids(db_path, proposal_id)
    try:
        for patch_transaction_id in ready_patch_ids:
            apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id=patch_transaction_id,
                workspace_root=workspace_root,
            )
    except HarnessError as exc:
        _record_autonomy_event(
            db_path,
            proposal_id=proposal_id,
            profile_id=profile_id,
            kind="autonomy_blocked",
            metadata={"reason": str(exc), "section": "harness"},
        )
        return _decision(
            proposal=proposal,
            state_after=_proposal_state(db_path, proposal_id),
            action="blocked",
            reason=str(exc),
            patch_transaction_ids=patch_transaction_ids,
        )
    except StorageError as exc:
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
            patch_transaction_ids=patch_transaction_ids,
        )

    state_after = _mark_proposal_applied(db_path, proposal_id, section="harness")
    _record_autonomy_event(
        db_path,
        proposal_id=proposal_id,
        profile_id=profile_id,
        kind="autonomy_harness_applied",
        metadata={
            "section": "harness",
            "patch_transaction_ids": list(patch_transaction_ids),
            "workspace_root": str(workspace_root.resolve()),
        },
    )
    return _decision(
        proposal=proposal,
        state_after=state_after,
        action="applied",
        reason="autonomous_auto_apply",
        patch_transaction_ids=patch_transaction_ids,
    )


def _inspect_context_gate(
    policy: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    if is_autonomous(policy):
        return {
            **base,
            "mutates": True,
            "action": "would_apply",
            "reason": "autonomous_auto_apply",
        }
    return {
        **base,
        "action": "awaiting_human_review",
        "reason": "hitl_awaiting_human_approve",
    }


def _inspect_harness_gate(
    policy: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    if not is_autonomous(policy):
        return {
            **base,
            "action": "awaiting_human_review",
            "reason": "hitl_awaiting_human_approve",
        }
    if not policy["allow_repo_patch"]:
        return {
            **base,
            "action": "blocked",
            "reason": "repo_patch_not_allowed",
        }
    return {
        **base,
        "mutates": True,
        "action": "would_apply",
        "reason": "autonomous_auto_apply",
    }


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


def _ready_patch_transaction_ids(db_path: Path, proposal_id: str) -> tuple[str, ...]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id
            FROM patch_transactions
            WHERE proposal_id = ?
              AND status = 'ready'
            ORDER BY created_at, id
            """,
            (proposal_id,),
        ).fetchall()
    return tuple(str(row["id"]) for row in rows)


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


def _decision(
    *,
    proposal: dict[str, Any],
    state_after: str,
    action: str,
    reason: str,
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
        applied_skill_ids=applied_skill_ids,
        applied_context_rule_ids=applied_context_rule_ids,
        patch_transaction_ids=patch_transaction_ids,
        detail=detail or {},
    )


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
