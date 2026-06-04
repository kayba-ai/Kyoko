"""User annotations for Kyoko runs and spans.

Annotations are lightweight, single-user markers attached to a run or span: an
``issue`` worth investigating, a ``good`` exemplar worth keeping, or a free-form
``note``. They are authored by the operator (or their own agent via MCP), not captured
from agent telemetry.

Design notes:

- Pure evidence/read-side. Annotations never change agent behavior and sit outside the
  safety gate.
- Authored content is **not** redacted: the note belongs to the single user who wrote
  it, so scrubbing their own text would be pointless ceremony.
- Mutations fan out over the process-local :class:`~kyoko.live.LiveBus` as
  :data:`~kyoko.live.EVENT_ANNOTATION` events so connected SSE subscribers see them live.
- ``run_id``/``span_id`` are free references so an annotation can target rows that have
  not been materialized yet.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from .live import EVENT_ANNOTATION, LiveBus, global_bus
from .storage import connect, initialize_database, utc_now

ANNOTATION_KINDS = ("issue", "good", "note")


class AnnotationError(Exception):
    """Raised for invalid annotation input or missing targets."""


def _resolve_profile_id(connection: Any, profile_id: Optional[str]) -> str:
    if profile_id:
        row = connection.execute(
            "SELECT 1 FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise AnnotationError(f"profile_not_found:{profile_id}")
        return profile_id
    row = connection.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise AnnotationError("no_profiles_found")
    return str(row[0])


def _row_to_dict(row: Any) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "run_id": row["run_id"],
        "span_id": row["span_id"],
        "kind": row["kind"],
        "note": row["note"],
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "metadata": metadata,
    }


def create_annotation(
    *,
    db_path: Path,
    kind: str,
    run_id: Optional[str] = None,
    span_id: Optional[str] = None,
    note: Optional[str] = None,
    source: str = "user",
    profile_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    bus: Optional[LiveBus] = None,
) -> dict:
    """Persist one annotation and publish it to the live bus.

    Returns the stored record (the ``--json``/API/SSE contract shape).
    """

    initialize_database(db_path)
    if kind not in ANNOTATION_KINDS:
        raise AnnotationError(f"unsupported_kind:{kind}")
    resolved_source = str(source or "user").strip() or "user"
    created_at = utc_now()
    metadata_json = json.dumps(metadata or {}, sort_keys=True, separators=(",", ":"))
    annotation_id = f"anno_{uuid.uuid4().hex[:12]}"

    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        connection.execute(
            """
            INSERT INTO annotations (
              id, profile_id, run_id, span_id, kind, note, source,
              created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                annotation_id,
                resolved_profile_id,
                run_id,
                span_id,
                kind,
                note,
                resolved_source,
                created_at,
                None,
                metadata_json,
            ),
        )
        record = {
            "id": annotation_id,
            "profile_id": resolved_profile_id,
            "run_id": run_id,
            "span_id": span_id,
            "kind": kind,
            "note": note,
            "source": resolved_source,
            "created_at": created_at,
            "updated_at": None,
            "metadata": metadata or {},
        }

    (bus or global_bus()).publish(EVENT_ANNOTATION, {"op": "create", "annotation": record})
    return record


def list_annotations(
    *,
    db_path: Path,
    run_id: Optional[str] = None,
    span_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Return stored annotations (oldest-first), filtered and capped."""

    initialize_database(db_path)
    bounded_limit = max(1, min(int(limit), 5000))
    clauses: list[str] = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if span_id:
        clauses.append("span_id = ?")
        params.append(span_id)
    if profile_id:
        clauses.append("profile_id = ?")
        params.append(profile_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM annotations{where} ORDER BY created_at ASC, id ASC LIMIT ?",
            (*params, bounded_limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def delete_annotation(
    *,
    db_path: Path,
    annotation_id: str,
    bus: Optional[LiveBus] = None,
) -> dict:
    """Delete one annotation and publish the removal to the live bus.

    Returns the deleted record. Raises :class:`AnnotationError` if it does not exist.
    """

    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM annotations WHERE id = ?", (annotation_id,)
        ).fetchone()
        if row is None:
            raise AnnotationError(f"annotation_not_found:{annotation_id}")
        record = _row_to_dict(row)
        connection.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))

    (bus or global_bus()).publish(EVENT_ANNOTATION, {"op": "delete", "annotation": record})
    return record
