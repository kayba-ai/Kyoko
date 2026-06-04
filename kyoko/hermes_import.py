from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .storage import IngestReport, StorageError, ingest_source_payload


ADAPTER_VERSION = "kyoko.hermes_kanban_import.v0"


class HermesImportError(Exception):
    """Raised when a Hermes Kanban database cannot be normalized."""


@dataclass(frozen=True)
class HermesKanbanImportReport:
    db_path: Path
    kanban_db_path: Path
    profile_id: str
    payload: dict[str, Any]
    ingested_counts: dict[str, int]
    normalized_path: Optional[Path]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "kanban_db_path": str(self.kanban_db_path),
            "normalized_path": str(self.normalized_path) if self.normalized_path else None,
            "ingested_counts": self.ingested_counts,
            "counts": _payload_counts(self.payload),
        }


def normalize_hermes_kanban_db(
    *,
    kanban_db_path: Path,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    board: str = "default",
) -> dict[str, Any]:
    if not kanban_db_path.exists():
        raise HermesImportError(f"hermes_kanban_db_not_found:{kanban_db_path}")

    board_slug = _slug(board or "default")
    selected_profile_id = profile_id or f"profile_hermes_{board_slug}"
    selected_profile_name = profile_name or f"Hermes {board_slug} Kanban"
    selected_root_path = str(root_path) if root_path is not None else str(kanban_db_path.parent)
    source_id = f"source_hermes_kanban_{board_slug}"
    queue_id = f"queue_hermes_{board_slug}"
    now = _utc_now()

    with _connect_hermes(kanban_db_path) as connection:
        _require_tables(connection, ["tasks", "task_runs", "task_events", "task_links", "task_comments"])
        tasks = _select_all(connection, "tasks", "created_at ASC, id ASC")
        runs = _select_all(connection, "task_runs", "started_at ASC, id ASC")
        events = _select_all(connection, "task_events", "created_at ASC, id ASC")
        links = _select_all(connection, "task_links", "parent_id ASC, child_id ASC")
        comments = _select_all(connection, "task_comments", "created_at ASC, id ASC")

    task_by_id = {str(task["id"]): task for task in tasks}
    runs_by_task: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        runs_by_task.setdefault(str(run.get("task_id")), []).append(run)

    agent_names = _agent_names(tasks=tasks, runs=runs, comments=comments)
    agent_ids = {name: f"agent_hermes_{_slug(name)}" for name in sorted(agent_names)}
    node_ids = {name: f"node_hermes_{_slug(name)}" for name in sorted(agent_names)}

    payload: dict[str, Any] = {
        "fixture_version": "kyoko.source_events.v1",
        "name": f"hermes-kanban-{board_slug}",
        "description": "Normalized Hermes Kanban board import.",
        "profile": {
            "id": selected_profile_id,
            "name": selected_profile_name,
            "root_path": selected_root_path,
            "status": "active",
            "created_at": _first_time(tasks, "created_at") or now,
            "updated_at": _last_time(events, "created_at") or _last_time(tasks, "completed_at") or now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": selected_profile_id,
                "kind": "hermes_kanban",
                "display_name": f"Hermes Kanban ({board_slug})",
                "status": "active",
                "adapter_version": ADAPTER_VERSION,
                "config_json": {
                    "board": board_slug,
                    "kanban_db_path": str(kanban_db_path),
                },
                "capabilities_json": {
                    "tasks": True,
                    "task_runs": True,
                    "task_events": True,
                    "task_links": True,
                    "task_comments": True,
                    "handoffs": True,
                },
                "last_seen_at": _last_time(events, "created_at") or now,
            }
        ],
        "agent_identities": [
            _agent_identity(
                agent_id=agent_ids[name],
                profile_id=selected_profile_id,
                source_id=source_id,
                name=name,
                workspace_path=selected_root_path,
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
                "kind": "agent",
                "name": name,
                "metadata_json": {"source": "hermes_profile"},
            }
            for name in sorted(agent_names)
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "external_id": board_slug,
                "name": board_slug,
                "kind": "hermes_board",
                "metadata_json": {"kanban_db_path": str(kanban_db_path)},
            }
        ],
        "tasks": [],
        "task_attempts": [],
        "runs": [],
        "spans": [],
        "handoffs": [],
        "timeline_events": [],
    }

    for task in tasks:
        payload["tasks"].append(
            _task_row(
                task=task,
                profile_id=selected_profile_id,
                source_id=source_id,
                queue_id=queue_id,
                agent_ids=agent_ids,
            )
        )

    for run in runs:
        task = task_by_id.get(str(run.get("task_id")))
        if task is None:
            continue
        run_id = _run_id(run)
        attempt_id = _attempt_id(run)
        agent_name = str(run.get("profile") or task.get("assignee") or "unknown")
        agent_id = agent_ids.get(agent_name) or agent_ids["unknown"]
        payload["task_attempts"].append(
            {
                "id": attempt_id,
                "task_id": _task_id(str(run["task_id"])),
                "run_id": run_id,
                "agent_identity_id": agent_id,
                "status": _attempt_status(str(run.get("status") or "unknown"), str(run.get("outcome") or "")),
                "outcome": run.get("outcome"),
                "claim_token_hash": _ref_or_none(run.get("claim_lock")),
                "worker_pid": run.get("worker_pid"),
                "started_at": _time(run.get("started_at")),
                "ended_at": _time(run.get("ended_at")),
                "last_heartbeat_at": _time(run.get("last_heartbeat_at")),
                "summary_ref": _ref("task_run", run.get("id"), "summary") if run.get("summary") else None,
                "metadata_json": _run_metadata(run),
                "error_ref": _ref("task_run", run.get("id"), "error") if run.get("error") else None,
            }
        )
        root_span_id = _span_id(run)
        payload["runs"].append(
            {
                "id": run_id,
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "external_id": f"hermes-task-run-{run['id']}",
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": attempt_id,
                "status": _run_status(str(run.get("status") or "unknown"), str(run.get("outcome") or "")),
                "started_at": _time(run.get("started_at")),
                "ended_at": _time(run.get("ended_at")),
                "input_ref": _ref("task", run.get("task_id"), "body") if task.get("body") else None,
                "output_ref": _ref("task_run", run.get("id"), "summary") if run.get("summary") else None,
                "summary": run.get("summary") or task.get("result") or task.get("title"),
                "metadata_json": _run_metadata(run),
            }
        )
        payload["spans"].append(
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": f"hermes-task-run-{run['id']}:root",
                "parent_span_id": None,
                "workflow_node_id": node_ids.get(agent_name) or node_ids["unknown"],
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": task.get("title") or f"Hermes task {run.get('task_id')}",
                "status": _run_status(str(run.get("status") or "unknown"), str(run.get("outcome") or "")),
                "started_at": _time(run.get("started_at")),
                "ended_at": _time(run.get("ended_at")),
                "input_ref": _ref("task", run.get("task_id"), "body") if task.get("body") else None,
                "output_ref": _ref("task_run", run.get("id"), "summary") if run.get("summary") else None,
                "usage_json": {},
                "attributes_json": {
                    "hermes_task_id": run.get("task_id"),
                    "hermes_run_id": run.get("id"),
                    "outcome": run.get("outcome"),
                    "step_key": run.get("step_key"),
                },
                "raw_ref": _ref("task_run", run.get("id"), "row"),
            }
        )

    for link in links:
        parent = task_by_id.get(str(link.get("parent_id")))
        child = task_by_id.get(str(link.get("child_id")))
        if parent is None or child is None:
            continue
        parent_agent = str(parent.get("assignee") or parent.get("created_by") or "unknown")
        child_agent = str(child.get("assignee") or child.get("created_by") or "unknown")
        payload["handoffs"].append(
            {
                "id": f"handoff_hermes_link_{_slug(parent['id'])}_{_slug(child['id'])}",
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "from_agent_identity_id": agent_ids.get(parent_agent) or agent_ids["unknown"],
                "to_agent_identity_id": agent_ids.get(child_agent) or agent_ids["unknown"],
                "from_workflow_node_id": node_ids.get(parent_agent) or node_ids["unknown"],
                "to_workflow_node_id": node_ids.get(child_agent) or node_ids["unknown"],
                "from_task_id": _task_id(str(parent["id"])),
                "to_task_id": _task_id(str(child["id"])),
                "run_id": _latest_run_id(runs_by_task.get(str(parent["id"]), [])),
                "span_id": None,
                "kind": "queue_dependency",
                "reason_ref": _ref("task_link", f"{parent['id']}:{child['id']}", "reason"),
                "payload_ref": _ref("task_link", f"{parent['id']}:{child['id']}", "payload"),
                "created_at": _time(child.get("created_at")),
                "metadata_json": {"parent_id": parent["id"], "child_id": child["id"]},
            }
        )

    for event in events:
        task_id = str(event.get("task_id"))
        if task_id not in task_by_id:
            continue
        event_payload = _json_obj(event.get("payload"))
        actor = event_payload.get("author") if isinstance(event_payload.get("author"), str) else None
        payload["timeline_events"].append(
            {
                "id": f"event_hermes_{event['id']}",
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "entity_type": "task",
                "entity_id": _task_id(task_id),
                "kind": str(event.get("kind") or "unknown"),
                "at": _time(event.get("created_at")),
                "agent_identity_id": agent_ids.get(actor) if actor else None,
                "payload_ref": _ref("task_event", event.get("id"), "payload") if event.get("payload") else None,
                "metadata_json": {
                    "hermes_event_id": event.get("id"),
                    "run_id": event.get("run_id"),
                    "payload": event_payload,
                },
            }
        )

    for comment in comments:
        task_id = str(comment.get("task_id"))
        if task_id not in task_by_id:
            continue
        author = str(comment.get("author") or "unknown")
        payload["timeline_events"].append(
            {
                "id": f"event_hermes_comment_{comment['id']}",
                "profile_id": selected_profile_id,
                "source_id": source_id,
                "entity_type": "task",
                "entity_id": _task_id(task_id),
                "kind": "commented",
                "at": _time(comment.get("created_at")),
                "agent_identity_id": agent_ids.get(author) or agent_ids["unknown"],
                "payload_ref": _ref("task_comment", comment.get("id"), "body"),
                "metadata_json": {
                    "hermes_comment_id": comment.get("id"),
                    "author": author,
                    "body_ref": _ref("task_comment", comment.get("id"), "body"),
                },
            }
        )

    payload["timeline_events"].sort(key=lambda row: (row["at"], row["id"]))
    return payload


def ingest_hermes_kanban_db(
    *,
    db_path: Path,
    kanban_db_path: Path,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    board: str = "default",
    output_path: Optional[Path] = None,
) -> HermesKanbanImportReport:
    payload = normalize_hermes_kanban_db(
        kanban_db_path=kanban_db_path,
        profile_id=profile_id,
        profile_name=profile_name,
        root_path=root_path,
        board=board,
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
            source_label=str(kanban_db_path),
        )
    except StorageError as exc:
        raise HermesImportError(str(exc)) from exc
    return HermesKanbanImportReport(
        db_path=db_path,
        kanban_db_path=kanban_db_path,
        profile_id=ingest_report.profile_id,
        payload=payload,
        ingested_counts=ingest_report.inserted_counts,
        normalized_path=normalized_path,
    )


def _connect_hermes(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(str(path))
    except sqlite3.Error as exc:
        raise HermesImportError(f"hermes_kanban_db_open_failed:{path}:{exc}") from exc
    connection.row_factory = sqlite3.Row
    return connection


def _require_tables(connection: sqlite3.Connection, tables: list[str]) -> None:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    present = {str(row["name"]) for row in rows}
    missing = [table for table in tables if table not in present]
    if missing:
        raise HermesImportError(f"hermes_kanban_missing_tables:{','.join(missing)}")


def _select_all(connection: sqlite3.Connection, table: str, order_by: str) -> list[dict[str, Any]]:
    rows = connection.execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
    return [dict(row) for row in rows]


def _agent_names(
    *,
    tasks: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> set[str]:
    names = {"unknown"}
    for task in tasks:
        for key in ("assignee", "created_by"):
            if task.get(key):
                names.add(str(task[key]))
    for run in runs:
        if run.get("profile"):
            names.add(str(run["profile"]))
    for comment in comments:
        if comment.get("author"):
            names.add(str(comment["author"]))
    return names


def _agent_identity(
    *,
    agent_id: str,
    profile_id: str,
    source_id: str,
    name: str,
    workspace_path: str,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": name,
        "name": name,
        "kind": "unknown" if name == "unknown" else "hermes_profile",
        "role": None,
        "model": None,
        "workspace_path": workspace_path,
        "metadata_json": {"source": "hermes_kanban"},
    }


def _task_row(
    *,
    task: dict[str, Any],
    profile_id: str,
    source_id: str,
    queue_id: str,
    agent_ids: dict[str, str],
) -> dict[str, Any]:
    assignee = str(task.get("assignee") or "unknown")
    created_by = str(task.get("created_by") or "unknown")
    return {
        "id": _task_id(str(task["id"])),
        "profile_id": profile_id,
        "source_id": source_id,
        "queue_id": queue_id,
        "external_id": str(task["id"]),
        "title": str(task.get("title") or task["id"]),
        "body_ref": _ref("task", task.get("id"), "body") if task.get("body") else None,
        "status": _task_status(str(task.get("status") or "unknown")),
        "assignee_agent_identity_id": agent_ids.get(assignee) or agent_ids["unknown"],
        "created_by_agent_identity_id": agent_ids.get(created_by) or agent_ids["unknown"],
        "priority": str(task.get("priority") if task.get("priority") is not None else 0),
        "workspace_kind": _workspace_kind(str(task.get("workspace_kind") or "unknown")),
        "workspace_path": task.get("workspace_path"),
        "created_at": _time(task.get("created_at")),
        "started_at": _time(task.get("started_at")),
        "completed_at": _time(task.get("completed_at")),
        "metadata_json": _task_metadata(task),
    }


def _task_metadata(task: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "hermes_task_id": task.get("id"),
        "tenant": task.get("tenant"),
        "result_ref": _ref("task", task.get("id"), "result") if task.get("result") else None,
        "idempotency_key": task.get("idempotency_key"),
        "consecutive_failures": task.get("consecutive_failures"),
        "last_failure_error_ref": _ref("task", task.get("id"), "last_failure_error")
        if task.get("last_failure_error")
        else None,
        "current_run_id": task.get("current_run_id"),
        "workflow_template_id": task.get("workflow_template_id"),
        "current_step_key": task.get("current_step_key"),
        "skills": _json_any(task.get("skills")),
        "max_retries": task.get("max_retries"),
        "max_runtime_seconds": task.get("max_runtime_seconds"),
    }
    return {key: value for key, value in metadata.items() if value is not None}


def _run_metadata(run: dict[str, Any]) -> dict[str, Any]:
    metadata = _json_obj(run.get("metadata"))
    metadata.update(
        {
            "hermes_run_id": run.get("id"),
            "claim_expires": run.get("claim_expires"),
            "max_runtime_seconds": run.get("max_runtime_seconds"),
            "step_key": run.get("step_key"),
            "error_ref": _ref("task_run", run.get("id"), "error") if run.get("error") else None,
        }
    )
    return {key: value for key, value in metadata.items() if value is not None}


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


def _task_id(external_id: str) -> str:
    return f"task_hermes_{_slug(external_id)}"


def _attempt_id(run: dict[str, Any]) -> str:
    return f"attempt_hermes_{run['id']}"


def _run_id(run: dict[str, Any]) -> str:
    return f"run_hermes_{run['id']}"


def _span_id(run: dict[str, Any]) -> str:
    return f"span_hermes_{run['id']}_root"


def _latest_run_id(runs: list[dict[str, Any]]) -> Optional[str]:
    if not runs:
        return None
    ordered = sorted(runs, key=lambda row: (row.get("started_at") or 0, row.get("id") or 0))
    return _run_id(ordered[-1])


def _task_status(status: str) -> str:
    return status if status in {"triage", "todo", "ready", "running", "blocked", "done", "archived"} else "unknown"


def _attempt_status(status: str, outcome: str) -> str:
    selected = outcome or status
    if selected == "completed":
        return "done"
    if selected in {"running", "done", "blocked", "crashed", "timed_out", "failed", "released"}:
        return selected
    if status == "done":
        return "done"
    return "unknown"


def _run_status(status: str, outcome: str) -> str:
    selected = outcome or status
    if selected in {"completed", "done"}:
        return "succeeded"
    if selected == "running":
        return "running"
    if selected == "timed_out":
        return "timed_out"
    if selected in {"blocked", "crashed", "failed", "spawn_failed", "gave_up"}:
        return "failed"
    if selected == "released" or selected == "reclaimed":
        return "cancelled"
    return "unknown"


def _workspace_kind(kind: str) -> str:
    return {
        "scratch": "temp",
        "worktree": "repo",
        "dir": "external",
    }.get(kind, "unknown")


def _json_obj(value: Any) -> dict[str, Any]:
    parsed = _json_any(value)
    return parsed if isinstance(parsed, dict) else {}


def _json_any(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _time(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        if isinstance(value, str) and value:
            return value
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first_time(rows: list[dict[str, Any]], key: str) -> Optional[str]:
    values = [_time(row.get(key)) for row in rows if row.get(key) is not None]
    return min(values) if values else None


def _last_time(rows: list[dict[str, Any]], key: str) -> Optional[str]:
    values = [_time(row.get(key)) for row in rows if row.get(key) is not None]
    return max(values) if values else None


def _ref(kind: str, identifier: Any, field: str) -> str:
    return f"hermes://{kind}/{identifier}/{field}"


def _ref_or_none(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def _slug(value: Any) -> str:
    text = str(value).strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return cleaned or "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
