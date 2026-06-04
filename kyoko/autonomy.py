from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .storage import StorageError, connect, initialize_database, utc_now


VALID_MODES = {"off", "propose", "autonomous"}
VALID_DIRTY_WORKTREE_POLICIES = {"block", "allow_touched_only", "allow"}
VALID_EVAL_LEVELS = {"L0_generated", "L1_repeated", "L2_regression", "L3_human_approved"}


class AutonomyError(Exception):
    """Raised when an autonomy policy cannot be read or updated."""


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
    context_mode: Optional[str] = None,
    harness_mode: Optional[str] = None,
    allow_skillbook_write: Optional[bool] = None,
    allow_eval_write: Optional[bool] = None,
    allow_profile_config_write: Optional[bool] = None,
    allow_repo_patch: Optional[bool] = None,
    allow_replay_server_patch: Optional[bool] = None,
    dirty_worktree_policy: Optional[str] = None,
    required_eval_level_context: Optional[str] = None,
    required_eval_level_harness: Optional[str] = None,
    rollback_on_regression: Optional[bool] = None,
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
            context_mode=context_mode,
            harness_mode=harness_mode,
            allow_skillbook_write=allow_skillbook_write,
            allow_eval_write=allow_eval_write,
            allow_profile_config_write=allow_profile_config_write,
            allow_repo_patch=allow_repo_patch,
            allow_replay_server_patch=allow_replay_server_patch,
            dirty_worktree_policy=dirty_worktree_policy,
            required_eval_level_context=required_eval_level_context,
            required_eval_level_harness=required_eval_level_harness,
            rollback_on_regression=rollback_on_regression,
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
    context_mode: Optional[str],
    harness_mode: Optional[str],
    allow_skillbook_write: Optional[bool],
    allow_eval_write: Optional[bool],
    allow_profile_config_write: Optional[bool],
    allow_repo_patch: Optional[bool],
    allow_replay_server_patch: Optional[bool],
    dirty_worktree_policy: Optional[str],
    required_eval_level_context: Optional[str],
    required_eval_level_harness: Optional[str],
    rollback_on_regression: Optional[bool],
) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if context_mode is not None:
        _validate_value("context_mode", context_mode, VALID_MODES)
        updates["context_mode"] = context_mode
    if harness_mode is not None:
        _validate_value("harness_mode", harness_mode, VALID_MODES)
        updates["harness_mode"] = harness_mode
    if dirty_worktree_policy is not None:
        _validate_value("dirty_worktree_policy", dirty_worktree_policy, VALID_DIRTY_WORKTREE_POLICIES)
        updates["dirty_worktree_policy"] = dirty_worktree_policy
    if required_eval_level_context is not None:
        _validate_value("required_eval_level_context", required_eval_level_context, VALID_EVAL_LEVELS)
        updates["required_eval_level_context"] = required_eval_level_context
    if required_eval_level_harness is not None:
        _validate_value("required_eval_level_harness", required_eval_level_harness, VALID_EVAL_LEVELS)
        updates["required_eval_level_harness"] = required_eval_level_harness

    boolean_updates = {
        "allow_skillbook_write": allow_skillbook_write,
        "allow_eval_write": allow_eval_write,
        "allow_profile_config_write": allow_profile_config_write,
        "allow_repo_patch": allow_repo_patch,
        "allow_replay_server_patch": allow_replay_server_patch,
        "rollback_on_regression": rollback_on_regression,
    }
    for column, value in boolean_updates.items():
        if value is not None:
            updates[column] = 1 if value else 0
    return updates


def _validate_value(field: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise AutonomyError(f"invalid_{field}:{value}")


def _decode_policy(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["allow_skillbook_write"] = bool(payload["allow_skillbook_write"])
    payload["allow_eval_write"] = bool(payload["allow_eval_write"])
    payload["allow_profile_config_write"] = bool(payload["allow_profile_config_write"])
    payload["allow_repo_patch"] = bool(payload["allow_repo_patch"])
    payload["allow_replay_server_patch"] = bool(payload["allow_replay_server_patch"])
    payload["rollback_on_regression"] = bool(payload["rollback_on_regression"])
    payload["allowed_paths"] = _json_loads(payload.pop("allowed_paths_json"), [])
    payload["protected_paths"] = _json_loads(payload.pop("protected_paths_json"), [])
    return payload


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
