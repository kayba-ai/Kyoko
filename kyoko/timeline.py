from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional, Sequence

from .storage import connect


AUTONOMY_EVENT_KINDS: tuple[str, ...] = (
    "autonomy_decision",
    "autonomy_gated",
    "autonomy_applied",
    "autonomy_harness_applied",
    "autonomy_harness_prepared",
    "autonomy_blocked",
    "autonomy_apply_failed",
    "autonomy_regression_failed",
    "autonomy_regression_rolled_back",
    "autonomy_regression_rollback_failed",
)


def list_timeline_events(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    kinds: Optional[Sequence[str]] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    selected_limit = min(max(int(limit), 1), 200)
    where: list[str] = []
    params: list[Any] = []
    if profile_id:
        where.append("profile_id = ?")
        params.append(profile_id)
    selected_kinds = tuple(kind for kind in (kinds or ()) if kind)
    if selected_kinds:
        placeholders = ",".join("?" for _ in selected_kinds)
        where.append(f"kind IN ({placeholders})")
        params.extend(selected_kinds)
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if entity_id:
        where.append("entity_id = ?")
        params.append(entity_id)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(selected_limit)

    try:
        with connect(db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM timeline_events
                {where_sql}
                ORDER BY at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [_decode_timeline_event(row) for row in rows]


def _decode_timeline_event(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    metadata = payload.pop("metadata_json", "{}")
    payload["metadata"] = _json_loads(metadata, {})
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
