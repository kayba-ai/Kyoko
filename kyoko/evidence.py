from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .apply import list_skills
from .checks import list_check_capabilities
from .redaction import (
    RedactionError,
    get_redaction_policy,
    redact_evidence_bundle,
)
from .storage import StorageError, connect, initialize_database


EVIDENCE_BUNDLE_VERSION = "kyoko.evidence_bundle.v1"


def build_evidence_bundle(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    consumer: str = "evidence_bundle",
) -> dict[str, Any]:
    if not db_path.exists():
        raise StorageError(f"{db_path}: database does not exist")
    initialize_database(db_path)

    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise StorageError("no profiles found")
        if not _row_exists(connection, "profiles", selected_profile_id):
            raise StorageError(f"profile_not_found:{selected_profile_id}")
        if run_id is not None and not _row_exists(connection, "runs", run_id):
            raise StorageError(f"run_not_found:{run_id}")

        bundle = {
            "schema_version": EVIDENCE_BUNDLE_VERSION,
            "profile_id": selected_profile_id,
            "run_id": run_id,
            "since": since,
            "profile": _one(
                connection,
                "SELECT * FROM profiles WHERE id = ?",
                (selected_profile_id,),
            ),
            "sources": _all(
                connection,
                "SELECT * FROM sources WHERE profile_id = ? ORDER BY id",
                (selected_profile_id,),
            ),
            "agent_identities": _all(
                connection,
                "SELECT * FROM agent_identities WHERE profile_id = ? ORDER BY id",
                (selected_profile_id,),
            ),
            "workflow_nodes": _all(
                connection,
                "SELECT * FROM workflow_nodes WHERE profile_id = ? ORDER BY id",
                (selected_profile_id,),
            ),
            "queues": _all(
                connection,
                "SELECT * FROM queues WHERE profile_id = ? ORDER BY id",
                (selected_profile_id,),
            ),
            "tasks": _profile_or_run_tasks(connection, selected_profile_id, run_id),
            "task_attempts": _profile_or_run_task_attempts(connection, selected_profile_id, run_id),
            "runs": _runs_rows(connection, selected_profile_id, run_id, since),
            "spans": _profile_or_run_spans(connection, selected_profile_id, run_id, since),
            "handoffs": _profile_or_run_handoffs(connection, selected_profile_id, run_id, since),
            "timeline_events": _profile_or_run_timeline_events(
                connection, selected_profile_id, run_id, since
            ),
            "learning_proposals": _profile_or_run_rows(
                connection,
                "learning_proposals",
                selected_profile_id,
                None,
            ),
            "check_specs": _profile_or_run_rows(connection, "check_specs", selected_profile_id, None),
            "check_runs": _profile_or_run_rows(connection, "check_runs", selected_profile_id, None),
            "replay_runs": _profile_or_run_rows(connection, "replay_runs", selected_profile_id, None),
            "replay_adapters": _profile_or_run_rows(connection, "replay_adapters", selected_profile_id, None),
            "operator_adapters": _profile_or_run_rows(connection, "operator_adapters", selected_profile_id, None),
            "operator_runs": _profile_or_run_rows(connection, "operator_runs", selected_profile_id, None),
            "patch_transactions": _profile_or_run_rows(
                connection,
                "patch_transactions",
                selected_profile_id,
                None,
            ),
            "skills": [
                skill
                for skill in list_skills(db_path)
                if skill["profile_id"] == selected_profile_id
            ],
            "check_capabilities": list_check_capabilities(),
        }

    bundle["summary"] = _bundle_summary(bundle)
    try:
        policy = get_redaction_policy(db_path=db_path, profile_id=str(bundle["profile_id"]))
        result = redact_evidence_bundle(bundle, policy)
        redaction = result.payload.get("redaction")
        if isinstance(redaction, dict):
            redaction["consumer"] = consumer
    except RedactionError as exc:
        raise StorageError(str(exc)) from exc
    return result.payload


def write_evidence_bundle(
    *,
    db_path: Path,
    output_path: Path,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    consumer: str = "cli:evidence",
) -> dict[str, Any]:
    bundle = build_evidence_bundle(
        db_path=db_path,
        profile_id=profile_id,
        run_id=run_id,
        consumer=consumer,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    return bundle


def _bundle_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    spans = bundle["spans"]
    failed_spans = [span for span in spans if span.get("status") == "failed"]
    return {
        "runs": len(bundle["runs"]),
        "spans": len(spans),
        "failed_spans": len(failed_spans),
        "tasks": len(bundle["tasks"]),
        "handoffs": len(bundle["handoffs"]),
        "learning_proposals": len(bundle["learning_proposals"]),
        "check_specs": len(bundle["check_specs"]),
        "check_runs": len(bundle["check_runs"]),
        "replay_runs": len(bundle["replay_runs"]),
        "replay_adapters": len(bundle["replay_adapters"]),
        "operator_adapters": len(bundle["operator_adapters"]),
        "operator_runs": len(bundle["operator_runs"]),
        "patch_transactions": len(bundle["patch_transactions"]),
        "skills": len(bundle["skills"]),
    }


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _row_exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (row_id,)).fetchone()
    return row is not None


def _one(connection: sqlite3.Connection, query: str, args: tuple[Any, ...]) -> dict[str, Any]:
    row = connection.execute(query, args).fetchone()
    return _decode_row(row) if row is not None else {}


def _all(connection: sqlite3.Connection, query: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [_decode_row(row) for row in connection.execute(query, args).fetchall()]


def _profile_or_run_rows(
    connection: sqlite3.Connection,
    table: str,
    profile_id: str,
    run_id: Optional[str],
) -> list[dict[str, Any]]:
    if run_id is None:
        return _all(connection, f"SELECT * FROM {table} WHERE profile_id = ? ORDER BY id", (profile_id,))
    return _all(connection, f"SELECT * FROM {table} WHERE id = ? ORDER BY id", (run_id,))


def _runs_rows(
    connection: sqlite3.Connection,
    profile_id: str,
    run_id: Optional[str],
    since: Optional[str],
) -> list[dict[str, Any]]:
    if run_id is not None:
        return _all(connection, "SELECT * FROM runs WHERE id = ? ORDER BY id", (run_id,))
    if since:
        return _all(
            connection,
            "SELECT * FROM runs WHERE profile_id = ? AND started_at > ? ORDER BY id",
            (profile_id, since),
        )
    return _all(connection, "SELECT * FROM runs WHERE profile_id = ? ORDER BY id", (profile_id,))


def _profile_or_run_spans(
    connection: sqlite3.Connection,
    profile_id: str,
    run_id: Optional[str],
    since: Optional[str] = None,
) -> list[dict[str, Any]]:
    if run_id is not None:
        return _all(connection, "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id", (run_id,))
    if since:
        return _all(
            connection,
            """
            SELECT spans.*
            FROM spans
            JOIN runs ON runs.id = spans.run_id
            WHERE runs.profile_id = ? AND runs.started_at > ?
            ORDER BY spans.started_at, spans.id
            """,
            (profile_id, since),
        )
    return _all(
        connection,
        """
        SELECT spans.*
        FROM spans
        JOIN runs ON runs.id = spans.run_id
        WHERE runs.profile_id = ?
        ORDER BY spans.started_at, spans.id
        """,
        (profile_id,),
    )


def _profile_or_run_handoffs(
    connection: sqlite3.Connection,
    profile_id: str,
    run_id: Optional[str],
    since: Optional[str] = None,
) -> list[dict[str, Any]]:
    if run_id is not None:
        return _all(
            connection,
            "SELECT * FROM handoffs WHERE run_id = ? ORDER BY created_at, id",
            (run_id,),
        )
    if since:
        return _all(
            connection,
            """
            SELECT * FROM handoffs
            WHERE profile_id = ?
              AND run_id IN (SELECT id FROM runs WHERE profile_id = ? AND started_at > ?)
            ORDER BY created_at, id
            """,
            (profile_id, profile_id, since),
        )
    return _all(
        connection,
        "SELECT * FROM handoffs WHERE profile_id = ? ORDER BY created_at, id",
        (profile_id,),
    )


def _profile_or_run_tasks(
    connection: sqlite3.Connection,
    profile_id: str,
    run_id: Optional[str],
) -> list[dict[str, Any]]:
    if run_id is not None:
        return _all(
            connection,
            """
            SELECT tasks.*
            FROM tasks
            JOIN task_attempts ON task_attempts.task_id = tasks.id
            WHERE task_attempts.run_id = ?
            ORDER BY tasks.created_at, tasks.id
            """,
            (run_id,),
        )
    return _all(
        connection,
        "SELECT * FROM tasks WHERE profile_id = ? ORDER BY created_at, id",
        (profile_id,),
    )


def _profile_or_run_task_attempts(
    connection: sqlite3.Connection,
    profile_id: str,
    run_id: Optional[str],
) -> list[dict[str, Any]]:
    if run_id is not None:
        return _all(
            connection,
            "SELECT * FROM task_attempts WHERE run_id = ? ORDER BY started_at, id",
            (run_id,),
        )
    return _all(
        connection,
        """
        SELECT task_attempts.*
        FROM task_attempts
        JOIN tasks ON tasks.id = task_attempts.task_id
        WHERE tasks.profile_id = ?
        ORDER BY task_attempts.started_at, task_attempts.id
        """,
        (profile_id,),
    )


def _profile_or_run_timeline_events(
    connection: sqlite3.Connection,
    profile_id: str,
    run_id: Optional[str],
    since: Optional[str] = None,
) -> list[dict[str, Any]]:
    if run_id is None:
        if since:
            return _all(
                connection,
                """
                SELECT *
                FROM timeline_events
                WHERE profile_id = ?
                  AND (
                    (entity_type = 'run' AND entity_id IN (
                       SELECT id FROM runs WHERE profile_id = ? AND started_at > ?))
                    OR (entity_type = 'span' AND entity_id IN (
                       SELECT spans.id FROM spans JOIN runs ON runs.id = spans.run_id
                       WHERE runs.profile_id = ? AND runs.started_at > ?))
                    OR (entity_type = 'handoff' AND entity_id IN (
                       SELECT handoffs.id FROM handoffs JOIN runs ON runs.id = handoffs.run_id
                       WHERE runs.profile_id = ? AND runs.started_at > ?))
                  )
                ORDER BY at, id
                """,
                (profile_id, profile_id, since, profile_id, since, profile_id, since),
            )
        return _all(
            connection,
            "SELECT * FROM timeline_events WHERE profile_id = ? ORDER BY at, id",
            (profile_id,),
        )
    return _all(
        connection,
        """
        SELECT *
        FROM timeline_events
        WHERE profile_id = ?
          AND (
            (entity_type = 'run' AND entity_id = ?)
            OR (entity_type = 'span' AND entity_id IN (SELECT id FROM spans WHERE run_id = ?))
            OR (entity_type = 'handoff' AND entity_id IN (SELECT id FROM handoffs WHERE run_id = ?))
          )
        ORDER BY at, id
        """,
        (profile_id, run_id, run_id, run_id),
    )


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key, value in list(payload.items()):
        if key.endswith("_json") and isinstance(value, str):
            try:
                payload[key] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return payload
