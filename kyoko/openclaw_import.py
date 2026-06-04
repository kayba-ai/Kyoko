from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .storage import IngestReport, StorageError, ingest_source_payload


ADAPTER_VERSION = "kyoko.openclaw_session_import.v0"


class OpenClawImportError(Exception):
    """Raised when OpenClaw session data cannot be normalized."""


@dataclass(frozen=True)
class OpenClawSessionImportReport:
    db_path: Path
    source_path: Path
    profile_id: str
    payload: dict[str, Any]
    ingested_counts: dict[str, int]
    normalized_path: Optional[Path]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "source_path": str(self.source_path),
            "normalized_path": str(self.normalized_path) if self.normalized_path else None,
            "ingested_counts": self.ingested_counts,
            "counts": _payload_counts(self.payload),
        }


def normalize_openclaw_sessions(
    *,
    source_path: Path,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    agent_id: Optional[str] = None,
    session_key: Optional[str] = None,
) -> dict[str, Any]:
    if not source_path.exists():
        raise OpenClawImportError(f"openclaw_source_not_found:{source_path}")

    selected_agent_id = agent_id or _infer_agent_id(source_path) or "main"
    agent_slug = _slug(selected_agent_id)
    selected_profile_id = profile_id or f"profile_openclaw_{agent_slug}"
    source_id = f"source_openclaw_sessions_{agent_slug}"
    queue_id = f"queue_openclaw_sessions_{agent_slug}"
    now = _utc_now()
    sessions = _discover_sessions(source_path, selected_agent_id=selected_agent_id, session_key=session_key)
    if not sessions:
        raise OpenClawImportError(f"openclaw_no_sessions_found:{source_path}")

    selected_profile_name = profile_name or f"OpenClaw {selected_agent_id} Sessions"
    selected_root_path = str(root_path or _infer_session_root_path(sessions) or _infer_root_path(source_path))
    agent_names = _agent_names(selected_agent_id, sessions)
    agent_ids = {name: f"agent_openclaw_{_slug(name)}" for name in sorted(agent_names)}
    node_ids = {name: f"node_openclaw_{_slug(name)}" for name in sorted(agent_names)}
    first_at = _first_session_time(sessions) or now
    last_at = _last_session_time(sessions) or now

    payload: dict[str, Any] = {
        "fixture_version": "kyoko.source_events.v1",
        "name": f"openclaw-sessions-{agent_slug}",
        "description": "Normalized OpenClaw session transcript import.",
        "profile": {
            "id": selected_profile_id,
            "name": selected_profile_name,
            "root_path": selected_root_path,
            "status": "active",
            "created_at": first_at,
            "updated_at": last_at,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": selected_profile_id,
                "kind": "openclaw_sessions",
                "display_name": f"OpenClaw sessions ({selected_agent_id})",
                "status": "active",
                "adapter_version": ADAPTER_VERSION,
                "config_json": {
                    "source_path": str(source_path),
                    "agent_id": selected_agent_id,
                    "session_key": session_key,
                },
                "capabilities_json": {
                    "sessions_json": True,
                    "jsonl_transcripts": True,
                    "handoffs": True,
                },
                "last_seen_at": last_at,
            }
        ],
        "agent_identities": [
            _agent_identity(
                agent_id=agent_ids[name],
                profile_id=selected_profile_id,
                source_id=source_id,
                name=name,
                workspace_path=selected_root_path,
                kind="human" if name == "user" else "agent",
            )
            for name in sorted(agent_names)
        ],
        "workflow_nodes": [
            {
                "id": node_ids[name],
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "external_id": name,
                "agent_identity_id": agent_ids[name],
                "kind": "human" if name == "user" else "agent",
                "name": name,
                "metadata_json": {"source": "openclaw_session"},
            }
            for name in sorted(agent_names)
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "external_id": selected_agent_id,
                "name": selected_agent_id,
                "kind": "openclaw_agent_sessions",
                "metadata_json": {"source_path": str(source_path)},
            }
        ],
        "tasks": [],
        "task_attempts": [],
        "runs": [],
        "spans": [],
        "handoffs": [],
        "timeline_events": [],
    }

    for session in sessions:
        _append_session(
            payload,
            session=session,
            profile_id=selected_profile_id,
            source_id=source_id,
            queue_id=queue_id,
            agent_ids=agent_ids,
            node_ids=node_ids,
            default_agent_id=selected_agent_id,
        )

    payload["timeline_events"].sort(key=lambda row: (row["at"], row["id"]))
    return payload


def ingest_openclaw_sessions(
    *,
    db_path: Path,
    source_path: Path,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    agent_id: Optional[str] = None,
    session_key: Optional[str] = None,
    output_path: Optional[Path] = None,
) -> OpenClawSessionImportReport:
    payload = normalize_openclaw_sessions(
        source_path=source_path,
        profile_id=profile_id,
        profile_name=profile_name,
        root_path=root_path,
        agent_id=agent_id,
        session_key=session_key,
    )
    normalized_path = None
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        normalized_path = output_path
    try:
        ingest_report: IngestReport = ingest_source_payload(
            db_path=db_path,
            fixture=payload,
            source_label=str(source_path),
        )
    except StorageError as exc:
        raise OpenClawImportError(str(exc)) from exc
    return OpenClawSessionImportReport(
        db_path=db_path,
        source_path=source_path,
        profile_id=ingest_report.profile_id,
        payload=payload,
        ingested_counts=ingest_report.inserted_counts,
        normalized_path=normalized_path,
    )


def _discover_sessions(
    source_path: Path,
    *,
    selected_agent_id: str,
    session_key: Optional[str],
) -> list[dict[str, Any]]:
    sessions_dir = source_path if source_path.is_dir() else source_path.parent
    store_path = source_path / "sessions.json" if source_path.is_dir() else source_path
    sessions: list[dict[str, Any]] = []
    if source_path.is_file() and source_path.suffix == ".jsonl":
        records = _read_jsonl(source_path)
        sessions.append(
            _session_payload(
                key=session_key or f"agent:{selected_agent_id}:{source_path.stem}",
                session_id=source_path.stem,
                transcript_path=source_path,
                store={},
                records=records,
            )
        )
        return sessions

    store = _read_store(store_path) if store_path.name == "sessions.json" and store_path.exists() else {}
    if store:
        for key, row in sorted(store.items()):
            if session_key and key != session_key:
                continue
            if not isinstance(row, dict):
                row = {}
            session_id = _string(row.get("sessionId")) or _string(row.get("id")) or _slug(key)
            transcript_path = _transcript_path(row, sessions_dir=sessions_dir, session_id=session_id)
            if transcript_path is None or not transcript_path.exists():
                continue
            sessions.append(
                _session_payload(
                    key=key,
                    session_id=session_id,
                    transcript_path=transcript_path,
                    store=row,
                    records=_read_jsonl(transcript_path),
                )
            )
        return sessions

    for path in sorted(sessions_dir.glob("*.jsonl")):
        if path.name.endswith(".trajectory-path.jsonl"):
            continue
        if session_key and _slug(session_key) != _slug(path.stem):
            continue
        sessions.append(
            _session_payload(
                key=f"agent:{selected_agent_id}:{path.stem}",
                session_id=path.stem,
                transcript_path=path,
                store={},
                records=_read_jsonl(path),
            )
        )
    return sessions


def _session_payload(
    *,
    key: str,
    session_id: str,
    transcript_path: Path,
    store: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "session_id": session_id,
        "transcript_path": transcript_path,
        "store": store,
        "records": records,
        "started_at": (
            _first_record_time(records)
            or _time(store.get("createdAt"))
            or _time(store.get("created_at"))
            or _time(store.get("startedAt"))
            or _time(store.get("started_at"))
        ),
        "ended_at": (
            _last_record_time(records)
            or _time(store.get("updatedAt"))
            or _time(store.get("updated_at"))
            or _time(store.get("endedAt"))
            or _time(store.get("ended_at"))
        ),
    }


def _append_session(
    payload: dict[str, Any],
    *,
    session: dict[str, Any],
    profile_id: str,
    source_id: str,
    queue_id: str,
    agent_ids: dict[str, str],
    node_ids: dict[str, str],
    default_agent_id: str,
) -> None:
    session_slug = _slug(str(session["session_id"]))
    task_id = f"task_openclaw_{session_slug}"
    attempt_id = f"attempt_openclaw_{session_slug}"
    run_id = f"run_openclaw_{session_slug}"
    root_span_id = f"span_openclaw_{session_slug}_root"
    records = list(session["records"])
    started_at = session.get("started_at") or _utc_now()
    ended_at = session.get("ended_at") or started_at
    failed = any(_record_failed(record) for record in records)
    run_status = "failed" if failed else "succeeded"
    owner_name = _record_agent_name(records[0], default_agent_id=default_agent_id) if records else default_agent_id
    owner_agent_id = agent_ids.get(owner_name) or agent_ids[default_agent_id]
    owner_node_id = node_ids.get(owner_name) or node_ids[default_agent_id]
    summary = _session_summary(session)

    payload["tasks"].append(
        {
            "id": task_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "queue_id": queue_id,
            "external_id": str(session["key"]),
            "title": summary,
            "body_ref": None,
            "status": "blocked" if failed else "done",
            "assignee_agent_identity_id": owner_agent_id,
            "created_by_agent_identity_id": agent_ids.get("user"),
            "priority": None,
            "workspace_kind": "openclaw_workspace",
            "workspace_path": payload["profile"]["root_path"],
            "created_at": started_at,
            "started_at": started_at,
            "completed_at": ended_at,
            "metadata_json": _session_metadata(session),
        }
    )
    payload["task_attempts"].append(
        {
            "id": attempt_id,
            "task_id": task_id,
            "run_id": run_id,
            "agent_identity_id": owner_agent_id,
            "status": "failed" if failed else "done",
            "outcome": "failed" if failed else "completed",
            "claim_token_hash": None,
            "worker_pid": None,
            "started_at": started_at,
            "ended_at": ended_at,
            "last_heartbeat_at": ended_at,
            "summary_ref": None,
            "metadata_json": _session_metadata(session),
            "error_ref": None,
            "error_payload": _first_record_error(records) if failed else None,
        }
    )
    payload["runs"].append(
        {
            "id": run_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": str(session["key"]),
            "root_span_id": root_span_id,
            "agent_identity_id": owner_agent_id,
            "task_attempt_id": attempt_id,
            "status": run_status,
            "started_at": started_at,
            "ended_at": ended_at,
            "input_ref": None,
            "output_ref": None,
            "summary": summary,
            "metadata_json": _session_metadata(session),
        }
    )
    payload["spans"].append(
        {
            "id": root_span_id,
            "run_id": run_id,
            "source_id": source_id,
            "external_id": f"{session['session_id']}:root",
            "parent_span_id": None,
            "workflow_node_id": owner_node_id,
            "agent_identity_id": owner_agent_id,
            "kind": "agent",
            "name": summary,
            "status": run_status,
            "started_at": started_at,
            "ended_at": ended_at,
            "input_ref": None,
            "output_ref": None,
            "usage_json": {},
            "attributes_json": _session_metadata(session),
            "raw_payload": session["store"],
        }
    )

    span_by_record_id: dict[str, str] = {}
    previous_span_id = root_span_id
    for index, record in enumerate(records, start=1):
        record_slug = _record_slug(record, index)
        span_id = f"span_openclaw_{session_slug}_{record_slug}"
        record_id = _string(record.get("id")) or record_slug
        parent_record_id = _string(record.get("parentId")) or _string(record.get("parent_id"))
        parent_span_id = span_by_record_id.get(parent_record_id or "") or root_span_id
        if parent_record_id is None and _record_kind(record) in {"tool_result", "tool_call"}:
            parent_span_id = previous_span_id
        agent_name = _record_agent_name(record, default_agent_id=default_agent_id)
        agent_id = agent_ids.get(agent_name) or agent_ids[default_agent_id]
        node_id = node_ids.get(agent_name) or node_ids[default_agent_id]
        status = "failed" if _record_failed(record) else "succeeded"
        at = _record_time(record) or started_at
        content = _record_text(record)
        kind = _span_kind(record)
        payload["spans"].append(
            {
                "id": span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": f"{session['session_id']}:{record_id}",
                "parent_span_id": parent_span_id,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": kind,
                "name": _record_name(record),
                "status": status,
                "started_at": at,
                "ended_at": at,
                "input_ref": None,
                "output_ref": None,
                "input_payload": content if kind in {"llm", "agent"} and _record_role(record) == "user" else None,
                "output_payload": content if kind in {"llm", "agent", "tool"} and _record_role(record) != "user" else None,
                "usage_json": _record_usage(record),
                "attributes_json": _record_attributes(record),
                "raw_payload": record,
            }
        )
        payload["timeline_events"].append(
            {
                "id": f"event_openclaw_{session_slug}_{record_slug}",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": span_id,
                "kind": f"openclaw_{_record_kind(record)}",
                "at": at,
                "agent_identity_id": agent_id,
                "payload": record,
                "metadata_json": {
                    "session_key": session["key"],
                    "session_id": session["session_id"],
                    "record_index": index,
                    "record_id": record_id,
                },
            }
        )
        _append_handoff(
            payload,
            session=session,
            record=record,
            profile_id=profile_id,
            source_id=source_id,
            agent_ids=agent_ids,
            node_ids=node_ids,
            run_id=run_id,
            span_id=span_id,
            record_slug=record_slug,
            at=at,
        )
        span_by_record_id[record_id] = span_id
        previous_span_id = span_id


def _append_handoff(
    payload: dict[str, Any],
    *,
    session: dict[str, Any],
    record: dict[str, Any],
    profile_id: str,
    source_id: str,
    agent_ids: dict[str, str],
    node_ids: dict[str, str],
    run_id: str,
    span_id: str,
    record_slug: str,
    at: str,
) -> None:
    from_agent = (
        _string(record.get("fromAgent"))
        or _string(record.get("from_agent"))
        or _string(record.get("sourceAgent"))
        or _string(record.get("source_agent"))
    )
    to_agent = (
        _string(record.get("toAgent"))
        or _string(record.get("to_agent"))
        or _string(record.get("targetAgent"))
        or _string(record.get("target_agent"))
        or _string(record.get("delegateTo"))
        or _string(record.get("delegate_to"))
    )
    if to_agent is None and _record_kind(record) in {"delegate", "handoff", "spawn"}:
        to_agent = _string(record.get("agent"))
    if not from_agent or not to_agent:
        return
    for name in (from_agent, to_agent):
        if name not in agent_ids:
            return
    payload["handoffs"].append(
        {
            "id": f"handoff_openclaw_{_slug(str(session['session_id']))}_{record_slug}",
            "profile_id": profile_id,
            "source_id": source_id,
            "from_agent_identity_id": agent_ids[from_agent],
            "to_agent_identity_id": agent_ids[to_agent],
            "from_workflow_node_id": node_ids[from_agent],
            "to_workflow_node_id": node_ids[to_agent],
            "from_task_id": None,
            "to_task_id": None,
            "run_id": run_id,
            "span_id": span_id,
            "kind": "agent_handoff",
            "reason_payload": _record_text(record) or _record_kind(record),
            "payload": record,
            "created_at": at,
            "metadata_json": {"session_key": session["key"], "record": record},
        }
    )


def _read_store(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OpenClawImportError(f"openclaw_sessions_json_invalid:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise OpenClawImportError(f"openclaw_sessions_json_must_be_object:{path}")
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), dict) else payload
    return sessions if isinstance(sessions, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OpenClawImportError(f"openclaw_transcript_read_failed:{path}:{exc}") from exc
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OpenClawImportError(f"openclaw_transcript_json_invalid:{path}:{index}:{exc}") from exc
        if isinstance(payload, dict):
            records.append(payload)
        else:
            records.append({"type": "event", "content": payload, "line": index})
    return records


def _transcript_path(row: dict[str, Any], *, sessions_dir: Path, session_id: str) -> Optional[Path]:
    for key in (
        "transcriptPath",
        "transcript_path",
        "transcript",
        "transcriptFile",
        "transcript_file",
        "path",
        "file",
        "jsonlPath",
        "jsonl_path",
    ):
        value = _string(row.get(key))
        if value:
            path = Path(value).expanduser()
            return path if path.is_absolute() else sessions_dir / path
    candidate = sessions_dir / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


def _agent_names(default_agent_id: str, sessions: list[dict[str, Any]]) -> set[str]:
    names = {default_agent_id, "user"}
    for session in sessions:
        store = session.get("store") if isinstance(session.get("store"), dict) else {}
        for key in ("agentId", "agent_id", "agent"):
            value = _string(store.get(key))
            if value:
                names.add(value)
        for record in session["records"]:
            for key in (
                "agentId",
                "agent_id",
                "agent",
                "fromAgent",
                "from_agent",
                "sourceAgent",
                "source_agent",
                "toAgent",
                "to_agent",
                "targetAgent",
                "target_agent",
                "delegateTo",
                "delegate_to",
            ):
                value = _string(record.get(key))
                if value:
                    names.add(value)
            role = _record_role(record)
            if role == "user":
                names.add("user")
    return names


def _agent_identity(
    *,
    agent_id: str,
    profile_id: str,
    source_id: str,
    name: str,
    workspace_path: str,
    kind: str,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": name,
        "name": name,
        "kind": kind,
        "role": "user" if kind == "human" else "assistant",
        "model": None,
        "workspace_path": workspace_path,
        "metadata_json": {"source": "openclaw"},
    }


def _record_kind(record: dict[str, Any]) -> str:
    selected = _string(record.get("type")) or _string(record.get("kind")) or _record_role(record) or "event"
    normalized = selected.lower().replace("-", "_")
    if normalized in {"tool_call", "tool_result", "message", "assistant", "user", "system", "handoff", "delegate", "spawn"}:
        return normalized
    if "tool" in normalized and "result" in normalized:
        return "tool_result"
    if "tool" in normalized:
        return "tool_call"
    if "delegat" in normalized:
        return "delegate"
    return normalized


def _record_role(record: dict[str, Any]) -> Optional[str]:
    role = _string(record.get("role")) or _string(record.get("speaker"))
    return role.lower() if role else None


def _span_kind(record: dict[str, Any]) -> str:
    kind = _record_kind(record)
    role = _record_role(record)
    if kind in {"tool_call", "tool_result"}:
        return "tool"
    if role == "user":
        return "agent"
    if role in {"assistant", "system"} or kind in {"assistant", "message"}:
        return "llm"
    if kind in {"handoff", "delegate", "spawn"}:
        return "handoff"
    return "agent"


def _record_name(record: dict[str, Any]) -> str:
    return (
        _string(record.get("name"))
        or _string(record.get("toolName"))
        or _string(record.get("tool_name"))
        or _string(record.get("title"))
        or _record_kind(record)
    )


def _record_agent_name(record: dict[str, Any], *, default_agent_id: str) -> str:
    if _record_role(record) == "user":
        return "user"
    return _string(record.get("agentId")) or _string(record.get("agent_id")) or _string(record.get("agent")) or default_agent_id


def _record_text(record: dict[str, Any]) -> Optional[Any]:
    for key in ("content", "text", "message", "output", "result", "error"):
        if key in record and record[key] not in (None, ""):
            return record[key]
    delta = record.get("delta")
    if isinstance(delta, dict):
        return delta.get("content") or delta.get("text")
    return None


def _record_failed(record: dict[str, Any]) -> bool:
    status = (_string(record.get("status")) or "").lower()
    if status in {"failed", "error", "errored", "cancelled", "timed_out"}:
        return True
    kind = _record_kind(record)
    if "error" in kind or "fail" in kind:
        return True
    if record.get("error") not in (None, "", False):
        return True
    return False


def _first_record_error(records: list[dict[str, Any]]) -> Optional[Any]:
    for record in records:
        if _record_failed(record):
            return record.get("error") or _record_text(record) or record
    return None


def _record_usage(record: dict[str, Any]) -> dict[str, Any]:
    usage = record.get("usage")
    if isinstance(usage, dict):
        return usage
    result = {}
    for key in (
        "inputTokens",
        "input_tokens",
        "outputTokens",
        "output_tokens",
        "totalTokens",
        "total_tokens",
        "contextTokens",
        "context_tokens",
    ):
        if isinstance(record.get(key), int):
            result[key] = record[key]
    return result


def _record_attributes(record: dict[str, Any]) -> dict[str, Any]:
    attrs = {
        "openclaw_type": _record_kind(record),
        "role": _record_role(record),
        "status": record.get("status"),
        "tool_name": record.get("toolName") or record.get("tool_name") or record.get("name"),
        "provider": record.get("provider"),
        "model": record.get("model"),
    }
    return {key: value for key, value in attrs.items() if value is not None}


def _record_time(record: dict[str, Any]) -> Optional[str]:
    for key in ("timestamp", "createdAt", "created_at", "updatedAt", "updated_at", "time", "at"):
        parsed = _time(record.get(key))
        if parsed:
            return parsed
    return None


def _first_record_time(records: list[dict[str, Any]]) -> Optional[str]:
    for record in records:
        parsed = _record_time(record)
        if parsed:
            return parsed
    return None


def _last_record_time(records: list[dict[str, Any]]) -> Optional[str]:
    for record in reversed(records):
        parsed = _record_time(record)
        if parsed:
            return parsed
    return None


def _first_session_time(sessions: list[dict[str, Any]]) -> Optional[str]:
    values = [session.get("started_at") for session in sessions if session.get("started_at")]
    return min(values) if values else None


def _last_session_time(sessions: list[dict[str, Any]]) -> Optional[str]:
    values = [session.get("ended_at") for session in sessions if session.get("ended_at")]
    return max(values) if values else None


def _record_slug(record: dict[str, Any], index: int) -> str:
    return _slug(_string(record.get("id")) or _string(record.get("eventId")) or str(index))


def _session_summary(session: dict[str, Any]) -> str:
    store = session.get("store") if isinstance(session.get("store"), dict) else {}
    return (
        _string(store.get("displayName"))
        or _string(store.get("display_name"))
        or _string(store.get("subject"))
        or _string(store.get("title"))
        or _string(store.get("name"))
        or f"OpenClaw session {session['session_id']}"
    )


def _session_metadata(session: dict[str, Any]) -> dict[str, Any]:
    store = session.get("store") if isinstance(session.get("store"), dict) else {}
    return {
        "session_key": session["key"],
        "session_id": session["session_id"],
        "transcript_path": str(session["transcript_path"]),
        "store": store,
    }


def _infer_agent_id(source_path: Path) -> Optional[str]:
    parts = list(source_path.expanduser().parts)
    for index, part in enumerate(parts):
        if part == "agents" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def _infer_root_path(source_path: Path) -> Path:
    parts = list(source_path.expanduser().parts)
    for index, part in enumerate(parts):
        if part == "agents" and index + 2 < len(parts):
            return Path(*parts[: index + 2])
    return source_path.parent if source_path.is_file() else source_path


def _infer_session_root_path(sessions: list[dict[str, Any]]) -> Optional[Path]:
    for session in sessions:
        store = session.get("store") if isinstance(session.get("store"), dict) else {}
        for key in ("workspacePath", "workspace_path", "cwd", "rootPath", "root_path"):
            value = _string(store.get(key))
            if value:
                return Path(value).expanduser()
    return None


def _time(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000.0
        return _format_utc(datetime.fromtimestamp(timestamp, timezone.utc))
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return _format_utc(parsed)
    return None


def _utc_now() -> str:
    return _format_utc(datetime.now(timezone.utc))


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _string(value: Any) -> Optional[str]:
    if isinstance(value, str) and value:
        return value
    return None


def _slug(value: Any) -> str:
    text = str(value or "unknown").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def _payload_counts(payload: dict[str, Any]) -> dict[str, int]:
    return {
        key: len(payload.get(key, []))
        for key in (
            "sources",
            "agent_identities",
            "workflow_nodes",
            "queues",
            "tasks",
            "task_attempts",
            "runs",
            "spans",
            "handoffs",
            "timeline_events",
        )
    }
