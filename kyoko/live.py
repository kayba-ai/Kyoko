"""Live (push) observability for Kyoko.

This module backs Phase 1 of the Workshop integration (see
``docs/kyoko-workshop-integration-plan.md``): fine-grained, real-time events emitted
during agent execution (token deltas, tool start/result, status, messages) — the live
analogue of post-hoc span ingest.

Design notes:

- Pure evidence/read-side. Live events never change agent behavior and sit outside the
  safety gate.
- Content is **redacted by default** (via :mod:`kyoko.redaction`) before it is written
  to disk or served.
- A process-local :class:`LiveBus` fans newly ingested events out to connected SSE
  subscribers. Live *serving* is loopback-only (enforced by the web server).
- ``run_id``/``span_id`` are free references so events can arrive before the batch
  ``runs``/``spans`` rows are materialized.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from .redaction import get_redaction_policy, redact_evidence_bundle
from .storage import connect, initialize_database, utc_now

LIVE_EVENT_KINDS = (
    "token",
    "tool_start",
    "tool_result",
    "status",
    "message",
    "error",
    "other",
)

# Bus event names broadcast over SSE.
EVENT_LIVE = "live_event"
EVENT_RUN_UPSERT = "run_upsert"
EVENT_CLEAR = "clear"
EVENT_MCP_LOG = "mcp_log"
EVENT_ANNOTATION = "annotation"
EVENT_PING = "ping"

# Inline preview cap (characters) for redacted live content. Token deltas are small;
# larger tool payloads are truncated and flagged rather than blown into per-token blobs.
PREVIEW_MAX_CHARS = 8192


class LiveError(Exception):
    """Raised for invalid live-event ingest input."""


class LiveBus:
    """Thread-safe in-process publish/subscribe for SSE fan-out.

    Each subscriber gets a bounded queue. On overflow the oldest event is dropped so a
    slow client can never block ingest or pin memory.
    """

    def __init__(self, max_queue: int = 2000) -> None:
        self._lock = threading.Lock()
        self._subscribers: set["queue.Queue[dict[str, Any]]"] = set()
        self._max_queue = max_queue

    def subscribe(self) -> "queue.Queue[dict[str, Any]]":
        subscriber: "queue.Queue[dict[str, Any]]" = queue.Queue(maxsize=self._max_queue)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: "queue.Queue[dict[str, Any]]") -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event: str, data: Any) -> None:
        message = {"event": event, "data": data}
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            _offer(subscriber, message)

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def _offer(subscriber: "queue.Queue[dict[str, Any]]", message: dict[str, Any]) -> None:
    try:
        subscriber.put_nowait(message)
        return
    except queue.Full:
        pass
    # Drop the oldest queued message to make room; never block the publisher.
    try:
        subscriber.get_nowait()
    except queue.Empty:
        pass
    try:
        subscriber.put_nowait(message)
    except queue.Full:
        pass


_GLOBAL_BUS = LiveBus()


def global_bus() -> LiveBus:
    """Return the process-wide live bus used by ingest and the web SSE endpoint."""

    return _GLOBAL_BUS


def _coerce_kind(kind: Any) -> str:
    candidate = str(kind or "other").strip().lower()
    return candidate if candidate in LIVE_EVENT_KINDS else "other"


def _redacted_preview(content: Any, policy: dict[str, Any]) -> tuple[Optional[str], bool]:
    """Redact ``content`` and return ``(preview, truncated)``.

    ``content`` may be a string (token delta) or a JSON-serializable structure (tool
    arguments/results). Sensitive keys are redacted per policy; the result is rendered
    to text and capped at :data:`PREVIEW_MAX_CHARS`.
    """

    if content is None:
        return None, False
    redacted = redact_evidence_bundle({"content": content}, policy).payload.get("content")
    if isinstance(redacted, str):
        text = redacted
    else:
        text = json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    truncated = len(text) > PREVIEW_MAX_CHARS
    if truncated:
        text = text[:PREVIEW_MAX_CHARS]
    return text, truncated


def _resolve_profile_id(connection: Any, profile_id: Optional[str]) -> str:
    if profile_id:
        row = connection.execute(
            "SELECT 1 FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise LiveError(f"profile_not_found:{profile_id}")
        return profile_id
    row = connection.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise LiveError("no_profiles_found")
    return str(row[0])


def _next_seq(connection: Any, profile_id: str, run_id: Optional[str]) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(seq), 0) FROM live_events WHERE profile_id = ? AND run_id IS ?",
        (profile_id, run_id),
    ).fetchone()
    return int(row[0]) + 1


def _row_to_dict(row: Any) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "source_id": row["source_id"],
        "run_id": row["run_id"],
        "span_id": row["span_id"],
        "seq": int(row["seq"]),
        "kind": row["kind"],
        "content_preview": row["content_preview"],
        "content_ref": row["content_ref"],
        "content_truncated": bool(metadata.get("content_truncated", False)),
        "at": row["at"],
        "metadata": metadata,
    }


def ingest_live_event(
    *,
    db_path: Path,
    kind: str,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    span_id: Optional[str] = None,
    source_id: Optional[str] = None,
    content: Any = None,
    metadata: Optional[dict[str, Any]] = None,
    at: Optional[str] = None,
    bus: Optional[LiveBus] = None,
) -> dict[str, Any]:
    """Persist one redacted live event and publish it to the live bus.

    Returns the stored record (the ``--json``/API/SSE contract shape).
    """

    initialize_database(db_path)
    resolved_kind = _coerce_kind(kind)
    timestamp = at or utc_now()
    extra_metadata = dict(metadata or {})

    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        policy = get_redaction_policy(db_path=db_path, profile_id=resolved_profile_id)
        preview, truncated = _redacted_preview(content, policy)
        if truncated:
            extra_metadata["content_truncated"] = True
        seq = _next_seq(connection, resolved_profile_id, run_id)
        event_id = f"live_{uuid.uuid4().hex[:12]}"
        metadata_json = json.dumps(extra_metadata, sort_keys=True, separators=(",", ":"))
        connection.execute(
            """
            INSERT INTO live_events (
              id, profile_id, source_id, run_id, span_id, seq, kind,
              content_preview, content_ref, at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                resolved_profile_id,
                source_id,
                run_id,
                span_id,
                seq,
                resolved_kind,
                preview,
                None,
                timestamp,
                metadata_json,
            ),
        )
        record = {
            "id": event_id,
            "profile_id": resolved_profile_id,
            "source_id": source_id,
            "run_id": run_id,
            "span_id": span_id,
            "seq": seq,
            "kind": resolved_kind,
            "content_preview": preview,
            "content_ref": None,
            "content_truncated": truncated,
            "at": timestamp,
            "metadata": extra_metadata,
        }

    (bus or _GLOBAL_BUS).publish(EVENT_LIVE, record)
    return record


def ingest_live_events(
    *,
    db_path: Path,
    events: list[dict[str, Any]],
    profile_id: Optional[str] = None,
    bus: Optional[LiveBus] = None,
) -> list[dict[str, Any]]:
    """Ingest a batch of live events. Each item mirrors :func:`ingest_live_event`."""

    if not isinstance(events, list):
        raise LiveError("events_must_be_a_list")
    records: list[dict[str, Any]] = []
    for item in events:
        if not isinstance(item, dict):
            raise LiveError("event_must_be_an_object")
        records.append(
            ingest_live_event(
                db_path=db_path,
                kind=item.get("kind", "other"),
                profile_id=item.get("profile_id", profile_id),
                run_id=item.get("run_id"),
                span_id=item.get("span_id"),
                source_id=item.get("source_id"),
                content=item.get("content"),
                metadata=item.get("metadata"),
                at=item.get("at"),
                bus=bus,
            )
        )
    return records


def list_live_events(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    after_seq: Optional[int] = None,
    kinds: Optional[list[str]] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return stored live events (oldest-first), filtered and capped."""

    initialize_database(db_path)
    bounded_limit = max(1, min(int(limit), 5000))
    clauses: list[str] = []
    params: list[Any] = []
    if profile_id:
        clauses.append("profile_id = ?")
        params.append(profile_id)
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if after_seq is not None:
        clauses.append("seq > ?")
        params.append(int(after_seq))
    if kinds:
        normalized = [_coerce_kind(k) for k in kinds]
        placeholders = ",".join("?" for _ in normalized)
        clauses.append(f"kind IN ({placeholders})")
        params.extend(normalized)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM live_events{where} ORDER BY at ASC, seq ASC LIMIT ?",
            (*params, bounded_limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]
