"""First-class Issue entity for Kyoko.

An :class:`Issue` is an operator-authored (or agent-proposed via MCP) record of a
problem worth tracking — independent from any learning proposal. Where a proposal is a
*proposed fix* gated by checks/replay, an issue is pure **evidence**: it describes a
category/severity of problem, links the affected canonical entities, and may backlink to
the proposals that address it. Creating, listing, or resolving an issue never changes
agent behavior, so issues sit entirely outside the autonomy/safety gate.

Design notes (mirrors :mod:`kyoko.annotations`):

- Pure evidence/read-propose side. Issues never mutate a skillbook, harness, or repo.
- Authored content (``title``/``body``) is **not** redacted: it belongs to the single
  user who wrote it. ``evidence_refs`` are stored verbatim but resolved/served through the
  standard detail path which redacts payloads on export.
- The implicit single profile is resolved when none is supplied, matching the rest of the
  single-player tool.
- IDs look like ``issue_{uuid4().hex[:12]}``.

Enums (validated here, not in the DB):

- ``section`` ∈ {``context``, ``harness``} (nullable)
- ``severity`` ∈ {``low``, ``medium``, ``high``} (nullable)
- ``status`` ∈ {``open``, ``resolved``, ``dismissed``} (default ``open``)
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from .storage import connect, initialize_database, utc_now

ISSUE_SECTIONS = ("context", "harness")
ISSUE_SEVERITIES = ("low", "medium", "high")
ISSUE_STATUSES = ("open", "resolved", "dismissed")

_LIST_FIELDS = (
    "evidence_refs",
    "affected_agent_identity_ids",
    "affected_workflow_node_ids",
    "affected_task_ids",
    "affected_span_ids",
    "proposal_ids",
)


class IssueError(Exception):
    """Raised for invalid issue input or missing targets."""


def _resolve_profile_id(connection: Any, profile_id: Optional[str]) -> str:
    if profile_id:
        row = connection.execute(
            "SELECT 1 FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise IssueError(f"profile_not_found:{profile_id}")
        return profile_id
    row = connection.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise IssueError("no_profiles_found")
    return str(row[0])


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "title": row["title"],
        "body": row["body"],
        "section": row["section"],
        "category": row["category"],
        "severity": row["severity"],
        "status": row["status"],
        "evidence_refs": _json_loads(row["evidence_refs_json"], []),
        "affected_agent_identity_ids": _json_loads(row["affected_agent_identity_ids_json"], []),
        "affected_workflow_node_ids": _json_loads(row["affected_workflow_node_ids_json"], []),
        "affected_task_ids": _json_loads(row["affected_task_ids_json"], []),
        "affected_span_ids": _json_loads(row["affected_span_ids_json"], []),
        "proposal_ids": _json_loads(row["proposal_ids_json"], []),
        "review_comment": row["review_comment"] if "review_comment" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _string_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise IssueError(f"{field}_must_be_string_list")
    return list(value)


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def create_issue(
    *,
    db_path: Path,
    title: str,
    body: Optional[str] = None,
    section: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    status: str = "open",
    evidence_refs: Optional[list] = None,
    affected_agent_identity_ids: Optional[list] = None,
    affected_workflow_node_ids: Optional[list] = None,
    affected_task_ids: Optional[list] = None,
    affected_span_ids: Optional[list] = None,
    proposal_ids: Optional[list] = None,
    profile_id: Optional[str] = None,
) -> dict:
    """Persist one issue (evidence only) and return its stored record."""

    initialize_database(db_path)
    resolved_title = str(title or "").strip()
    if not resolved_title:
        raise IssueError("title_required")
    if section is not None and section not in ISSUE_SECTIONS:
        raise IssueError(f"unsupported_section:{section}")
    if severity is not None and severity not in ISSUE_SEVERITIES:
        raise IssueError(f"unsupported_severity:{severity}")
    resolved_status = str(status or "open")
    if resolved_status not in ISSUE_STATUSES:
        raise IssueError(f"unsupported_status:{resolved_status}")

    if evidence_refs is not None and not isinstance(evidence_refs, list):
        raise IssueError("evidence_refs_must_be_list")
    agent_ids = _string_list(affected_agent_identity_ids, "affected_agent_identity_ids")
    node_ids = _string_list(affected_workflow_node_ids, "affected_workflow_node_ids")
    task_ids = _string_list(affected_task_ids, "affected_task_ids")
    span_ids = _string_list(affected_span_ids, "affected_span_ids")
    linked_proposal_ids = _string_list(proposal_ids, "proposal_ids")

    created_at = utc_now()
    issue_id = f"issue_{uuid.uuid4().hex[:12]}"

    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        connection.execute(
            """
            INSERT INTO issues (
              id, profile_id, title, body, section, category, severity, status,
              evidence_refs_json, affected_agent_identity_ids_json,
              affected_workflow_node_ids_json, affected_task_ids_json,
              affected_span_ids_json, proposal_ids_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                issue_id,
                resolved_profile_id,
                resolved_title,
                body,
                section,
                category,
                severity,
                resolved_status,
                _json_dump(evidence_refs or []),
                _json_dump(agent_ids),
                _json_dump(node_ids),
                _json_dump(task_ids),
                _json_dump(span_ids),
                _json_dump(linked_proposal_ids),
                created_at,
                None,
            ),
        )

    return {
        "id": issue_id,
        "profile_id": resolved_profile_id,
        "title": resolved_title,
        "body": body,
        "section": section,
        "category": category,
        "severity": severity,
        "status": resolved_status,
        "evidence_refs": evidence_refs or [],
        "affected_agent_identity_ids": agent_ids,
        "affected_workflow_node_ids": node_ids,
        "affected_task_ids": task_ids,
        "affected_span_ids": span_ids,
        "proposal_ids": linked_proposal_ids,
        "created_at": created_at,
        "updated_at": None,
    }


def list_issues(
    *,
    db_path: Path,
    status: Optional[str] = None,
    section: Optional[str] = None,
    profile_id: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Return stored issues (newest-first), filtered and capped."""

    initialize_database(db_path)
    if status is not None and status not in ISSUE_STATUSES:
        raise IssueError(f"unsupported_status:{status}")
    if section is not None and section not in ISSUE_SECTIONS:
        raise IssueError(f"unsupported_section:{section}")
    bounded_limit = max(1, min(int(limit), 5000))
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if section:
        clauses.append("section = ?")
        params.append(section)
    if profile_id:
        clauses.append("profile_id = ?")
        params.append(profile_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM issues{where} ORDER BY created_at DESC, id ASC LIMIT ?",
            (*params, bounded_limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_issue(*, db_path: Path, issue_id: str) -> dict:
    """Return one stored issue. Raises :class:`IssueError` if it does not exist."""

    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if row is None:
            raise IssueError(f"issue_not_found:{issue_id}")
        return _row_to_dict(row)


def update_issue_status(*, db_path: Path, issue_id: str, status: str) -> dict:
    """Move an issue through its lifecycle (open → resolved/dismissed and back)."""

    initialize_database(db_path)
    if status not in ISSUE_STATUSES:
        raise IssueError(f"unsupported_status:{status}")
    updated_at = utc_now()
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if row is None:
            raise IssueError(f"issue_not_found:{issue_id}")
        connection.execute(
            "UPDATE issues SET status = ?, updated_at = ? WHERE id = ?",
            (status, updated_at, issue_id),
        )
        record = _row_to_dict(row)
    record["status"] = status
    record["updated_at"] = updated_at
    return record


def set_issue_comment(*, db_path: Path, issue_id: str, comment: Optional[str]) -> dict:
    """Set (or clear) the free-text review comment on an issue. Evidence triage
    only — it never changes agent behavior or touches the check/replay gate."""

    initialize_database(db_path)
    normalized = comment.strip() if isinstance(comment, str) and comment.strip() else None
    updated_at = utc_now()
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if row is None:
            raise IssueError(f"issue_not_found:{issue_id}")
        connection.execute(
            "UPDATE issues SET review_comment = ?, updated_at = ? WHERE id = ?",
            (normalized, updated_at, issue_id),
        )
        record = _row_to_dict(row)
    record["review_comment"] = normalized
    record["updated_at"] = updated_at
    return record
