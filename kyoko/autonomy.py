from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .storage import StorageError, connect, initialize_database, utc_now


# v31 (spec 0018): two modes. `hitl` = a human approves both gates; `autonomous` = the
# loop approves gate #1 on production recurrence and gate #2 post-hoc (auto-apply, then the
# guard monitor rolls back on a confirmed regression).
VALID_MODES = {"hitl", "autonomous"}
VALID_DIRTY_WORKTREE_POLICIES = {"block", "allow_touched_only", "allow"}

# When True, a `high`-severity issue may clear autonomous gate #1 one recurrence early
# (but never at n=1 — a single sample never auto-applies). See spec 0018 Decision #2.
SEVERITY_OVERRIDE = True


class AutonomyError(Exception):
    """Raised when an autonomy policy cannot be read or updated."""


@dataclass(frozen=True)
class GateDecision:
    """The outcome of a gate evaluation (who/what may advance the pipeline)."""

    gate: str  # "gate1" | "gate2"
    mode: str
    allow: bool
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "mode": self.mode,
            "allow": self.allow,
            "reason": self.reason,
        }


def evaluate_gate1(
    *,
    issue: dict[str, Any],
    policy: dict[str, Any],
    severity_override: bool = SEVERITY_OVERRIDE,
) -> GateDecision:
    """Gate #1 — may this issue advance from *surfaced* to *propose a fix*?

    HITL: only once a human has accepted the issue (``status == "accepted"``).
    Autonomous: once the failure has recurred in production enough times
    (``recurrence_count >= recurrence_threshold``); a high-severity issue may clear one
    recurrence early but never at a single occurrence. An issue escalated to HITL after too
    many failed auto-fixes (``autonomy_blocked``) is never auto-accepted.
    """

    mode = str(policy.get("mode", "hitl"))
    status = str(issue.get("status") or "")
    if status == "dismissed":
        return GateDecision("gate1", mode, False, "issue_dismissed")

    if mode == "hitl":
        if status == "accepted":
            return GateDecision("gate1", mode, True, "hitl_human_accepted")
        return GateDecision("gate1", mode, False, "hitl_awaiting_human_accept")

    # autonomous
    if _truthy(issue.get("autonomy_blocked")):
        return GateDecision("gate1", mode, False, "autonomy_blocked_escalated_to_hitl")
    recurrence = int(issue.get("recurrence_count") or 1)
    threshold = int(policy.get("recurrence_threshold") or 3)
    if recurrence >= threshold:
        return GateDecision("gate1", mode, True, f"recurrence_met:{recurrence}>={threshold}")
    if (
        severity_override
        and str(issue.get("severity") or "") == "high"
        and recurrence >= max(2, threshold - 1)
    ):
        return GateDecision("gate1", mode, True, f"severity_override:{recurrence}")
    return GateDecision("gate1", mode, False, f"recurrence_below_threshold:{recurrence}<{threshold}")


def evaluate_gate2(*, policy: dict[str, Any], human_approved: bool = False) -> GateDecision:
    """Gate #2 — may this proposal be applied?

    HITL: only when a human triggers the apply action (``human_approved``). Autonomous:
    auto-apply (validation is post-hoc via the guard monitor). Repo/harness writes remain
    subject to the ``allow_repo_patch`` capability fence at apply time regardless of mode.
    """

    mode = str(policy.get("mode", "hitl"))
    if human_approved:
        return GateDecision("gate2", mode, True, "human_approved")
    if mode == "autonomous":
        return GateDecision("gate2", mode, True, "autonomous_auto_apply")
    return GateDecision("gate2", mode, False, "hitl_awaiting_human_approve")


def is_autonomous(policy: dict[str, Any]) -> bool:
    return str(policy.get("mode", "hitl")) == "autonomous"


def get_autonomy_policy(*, db_path: Path, profile_id: Optional[str] = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise AutonomyError("no_profiles_found")
        _ensure_profile_exists(connection, selected_profile_id)
        row = connection.execute(
            "SELECT * FROM autonomy_policies WHERE profile_id = ?",
            (selected_profile_id,),
        ).fetchone()
        if row is None:
            raise AutonomyError(f"autonomy_policy_not_found:{selected_profile_id}")
    return _decode_policy(row)


def update_autonomy_policy(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    mode: Optional[str] = None,
    recurrence_threshold: Optional[int] = None,
    regression_threshold: Optional[int] = None,
    auto_rollback_on_regression: Optional[bool] = None,
    max_auto_fix_attempts: Optional[int] = None,
    allow_repo_patch: Optional[bool] = None,
    dirty_worktree_policy: Optional[str] = None,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise AutonomyError("no_profiles_found")
        _ensure_profile_exists(connection, selected_profile_id)
        row = connection.execute(
            "SELECT * FROM autonomy_policies WHERE profile_id = ?",
            (selected_profile_id,),
        ).fetchone()
        if row is None:
            raise AutonomyError(f"autonomy_policy_not_found:{selected_profile_id}")

        updates = _policy_updates(
            mode=mode,
            recurrence_threshold=recurrence_threshold,
            regression_threshold=regression_threshold,
            auto_rollback_on_regression=auto_rollback_on_regression,
            max_auto_fix_attempts=max_auto_fix_attempts,
            allow_repo_patch=allow_repo_patch,
            dirty_worktree_policy=dirty_worktree_policy,
        )
        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            values = list(updates.values())
            values.extend([utc_now(), selected_profile_id])
            connection.execute(
                f"""
                UPDATE autonomy_policies
                SET {assignments}, updated_at = ?
                WHERE profile_id = ?
                """,
                values,
            )
        updated = connection.execute(
            "SELECT * FROM autonomy_policies WHERE profile_id = ?",
            (selected_profile_id,),
        ).fetchone()
    return _decode_policy(updated)


def _policy_updates(
    *,
    mode: Optional[str],
    recurrence_threshold: Optional[int],
    regression_threshold: Optional[int],
    auto_rollback_on_regression: Optional[bool],
    max_auto_fix_attempts: Optional[int],
    allow_repo_patch: Optional[bool],
    dirty_worktree_policy: Optional[str],
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if mode is not None:
        _validate_value("mode", mode, VALID_MODES)
        updates["mode"] = mode
    if dirty_worktree_policy is not None:
        _validate_value("dirty_worktree_policy", dirty_worktree_policy, VALID_DIRTY_WORKTREE_POLICIES)
        updates["dirty_worktree_policy"] = dirty_worktree_policy
    if recurrence_threshold is not None:
        updates["recurrence_threshold"] = _validate_positive_int("recurrence_threshold", recurrence_threshold)
    if regression_threshold is not None:
        updates["regression_threshold"] = _validate_positive_int("regression_threshold", regression_threshold)
    if max_auto_fix_attempts is not None:
        updates["max_auto_fix_attempts"] = _validate_nonneg_int("max_auto_fix_attempts", max_auto_fix_attempts)

    boolean_updates = {
        "auto_rollback_on_regression": auto_rollback_on_regression,
        "allow_repo_patch": allow_repo_patch,
    }
    for column, value in boolean_updates.items():
        if value is not None:
            updates[column] = 1 if value else 0
    return updates


def _validate_value(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise AutonomyError(f"invalid_{field}:{value}")


def _validate_positive_int(field: str, value: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        raise AutonomyError(f"invalid_{field}:{value}")
    if coerced < 1:
        raise AutonomyError(f"invalid_{field}:{value}")
    return coerced


def _validate_nonneg_int(field: str, value: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        raise AutonomyError(f"invalid_{field}:{value}")
    if coerced < 0:
        raise AutonomyError(f"invalid_{field}:{value}")
    return coerced


def _decode_policy(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["recurrence_threshold"] = int(payload["recurrence_threshold"])
    payload["regression_threshold"] = int(payload["regression_threshold"])
    payload["max_auto_fix_attempts"] = int(payload["max_auto_fix_attempts"])
    payload["auto_rollback_on_regression"] = bool(payload["auto_rollback_on_regression"])
    payload["allow_repo_patch"] = bool(payload["allow_repo_patch"])
    payload["allowed_paths"] = _json_loads(payload.pop("allowed_paths_json"), [])
    payload["protected_paths"] = _json_loads(payload.pop("protected_paths_json"), [])
    return payload


def _truthy(value: Any) -> bool:
    return bool(value) and value not in (0, "0", "", "false", "False")


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _ensure_profile_exists(connection: sqlite3.Connection, profile_id: str) -> None:
    row = connection.execute("SELECT 1 FROM profiles WHERE id = ? LIMIT 1", (profile_id,)).fetchone()
    if row is None:
        raise AutonomyError(f"profile_not_found:{profile_id}")


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
