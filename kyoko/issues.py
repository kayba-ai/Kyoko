"""First-class Issue entity for Kyoko — the central spine of the optimization loop.

An :class:`Issue` is a surfaced agent behavioral failure. It is the **only origin of a
LearningProposal**: analysis and the measurement planes (eval / llm_eval) both flow into
issues (job steps 02–04 "surface → prioritize → diagnose"), the issue then originates a
proposal (step 05) which is gated and applied (steps 06–07), and once resolved the issue
**owns a standing guard evaluator** that watches future traces for recurrence (step 08,
closing the loop). See ``docs/specs/0016-issue-centric-loop.md``.

The issue itself is still pure **evidence** — creating, prioritizing, diagnosing, or
resolving an issue never changes agent behavior. All behavior change happens downstream
through the proposal → check/replay → autonomy gate. Issues sit outside that gate.

Design notes (mirrors :mod:`kyoko.annotations`):

- Authored content (``title``/``body``/``root_cause``) is **not** redacted: it belongs to
  the single user. ``evidence_refs`` are stored verbatim but resolved/served through the
  standard detail path which redacts payloads on export.
- The implicit single profile is resolved when none is supplied (single-player tool).
- IDs look like ``issue_{uuid4().hex[:12]}``.

Enums (validated here, not in the DB):

- ``section`` ∈ {``context``, ``harness``} (nullable) — also selects which autonomy mode
  gates this issue's proposal (gate #1: ``context_mode`` / ``harness_mode``).
- ``severity`` ∈ {``low``, ``medium``, ``high``} (nullable)
- ``source`` ∈ {``analysis``, ``eval``, ``llm_eval``, ``manual``} (nullable) — provenance.
- ``status`` is the lifecycle state machine:
  ``open → prioritized → diagnosed → proposed → applied → resolved → guarded`` with
  ``dismissed`` as a terminal off-ramp from any state. ``open``/``resolved``/``dismissed``
  are retained for backward compatibility.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Optional

from .storage import connect, initialize_database, utc_now

ISSUE_SECTIONS = ("context", "harness")
ISSUE_SEVERITIES = ("low", "medium", "high")
ISSUE_SOURCES = ("analysis", "eval", "llm_eval", "manual")
ISSUE_STATUSES = (
    "open",
    "prioritized",
    "diagnosed",
    "proposed",
    "applied",
    "resolved",
    "guarded",
    "dismissed",
)
# Forward progression of the lifecycle (dismissed is reachable from any state and is
# omitted here). Used to validate monotonic advancement; plain `update_issue_status`
# stays permissive for manual triage/correction.
ISSUE_LIFECYCLE_ORDER = (
    "open",
    "prioritized",
    "diagnosed",
    "proposed",
    "applied",
    "resolved",
    "guarded",
)

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
        "rank": row["rank"] if "rank" in row.keys() else None,
        "root_cause": row["root_cause"] if "root_cause" in row.keys() else None,
        "source": row["source"] if "source" in row.keys() else None,
        "evaluator_id": row["evaluator_id"] if "evaluator_id" in row.keys() else None,
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
    source: Optional[str] = None,
    root_cause: Optional[str] = None,
    rank: Optional[int] = None,
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
    if source is not None and source not in ISSUE_SOURCES:
        raise IssueError(f"unsupported_source:{source}")
    resolved_status = str(status or "open")
    if resolved_status not in ISSUE_STATUSES:
        raise IssueError(f"unsupported_status:{resolved_status}")
    if rank is not None and not isinstance(rank, int):
        raise IssueError("rank_must_be_int")

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
              affected_span_ids_json, proposal_ids_json,
              source, root_cause, rank, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                source,
                root_cause,
                rank,
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
        "review_comment": None,
        "rank": rank,
        "root_cause": root_cause,
        "source": source,
        "evaluator_id": None,
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


def _apply_issue_update(
    *, db_path: Path, issue_id: str, assignments: dict[str, Any]
) -> dict:
    """Load an issue, apply column assignments (+ bump ``updated_at``), return the
    refreshed record. Shared by the lifecycle mutators below. Evidence only."""

    initialize_database(db_path)
    updated_at = utc_now()
    columns = list(assignments.keys())
    set_clause = ", ".join(f"{column} = ?" for column in columns)
    values = [assignments[column] for column in columns]
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if row is None:
            raise IssueError(f"issue_not_found:{issue_id}")
        connection.execute(
            f"UPDATE issues SET {set_clause}, updated_at = ? WHERE id = ?",
            (*values, updated_at, issue_id),
        )
        record = _row_to_dict(row)
    record.update(assignments)
    record["updated_at"] = updated_at
    return record


def set_issue_rank(*, db_path: Path, issue_id: str, rank: Optional[int]) -> dict:
    """Set (or clear) the prioritization rank (lower = more urgent). Job step 02.
    Advances ``open`` issues to ``prioritized``; otherwise leaves status untouched."""

    if rank is not None and not isinstance(rank, int):
        raise IssueError("rank_must_be_int")
    current = get_issue(db_path=db_path, issue_id=issue_id)
    assignments: dict[str, Any] = {"rank": rank}
    if current["status"] == "open" and rank is not None:
        assignments["status"] = "prioritized"
    return _apply_issue_update(db_path=db_path, issue_id=issue_id, assignments=assignments)


def set_issue_diagnosis(
    *,
    db_path: Path,
    issue_id: str,
    root_cause: str,
    section: Optional[str] = None,
) -> dict:
    """Record the diagnosed root cause (job step 04) and, optionally, the fix
    ``section`` (context|harness) that selects the gate-#1 autonomy mode. Advances the
    issue to ``diagnosed``."""

    normalized = str(root_cause or "").strip()
    if not normalized:
        raise IssueError("root_cause_required")
    if section is not None and section not in ISSUE_SECTIONS:
        raise IssueError(f"unsupported_section:{section}")
    get_issue(db_path=db_path, issue_id=issue_id)  # existence check
    assignments: dict[str, Any] = {"root_cause": normalized, "status": "diagnosed"}
    if section is not None:
        assignments["section"] = section
    return _apply_issue_update(db_path=db_path, issue_id=issue_id, assignments=assignments)


def link_proposal_to_issue(
    *, db_path: Path, issue_id: str, proposal_id: str, status: Optional[str] = "proposed"
) -> dict:
    """Backlink a proposal that this issue originated (job step 05). Idempotent — a
    proposal id is appended once. Advances the issue to ``proposed`` by default (pass
    ``status=None`` to leave the lifecycle state untouched)."""

    resolved_proposal_id = str(proposal_id or "").strip()
    if not resolved_proposal_id:
        raise IssueError("proposal_id_required")
    if status is not None and status not in ISSUE_STATUSES:
        raise IssueError(f"unsupported_status:{status}")
    current = get_issue(db_path=db_path, issue_id=issue_id)
    proposal_ids = list(current["proposal_ids"])
    if resolved_proposal_id not in proposal_ids:
        proposal_ids.append(resolved_proposal_id)
    assignments: dict[str, Any] = {"proposal_ids_json": _json_dump(proposal_ids)}
    if status is not None:
        assignments["status"] = status
    record = _apply_issue_update(
        db_path=db_path, issue_id=issue_id, assignments=assignments
    )
    record["proposal_ids"] = proposal_ids
    record.pop("proposal_ids_json", None)
    return record


def set_issue_evaluator(*, db_path: Path, issue_id: str, evaluator_id: str) -> dict:
    """Bind the standing guard evaluator that watches for recurrence of this fixed
    issue (job step 08) and advance the issue to ``guarded`` — the terminal "loop
    closed" state. The evaluator is an ``eval_definitions`` row (deterministic detector
    by strong preference; an llm_eval judge only when the failure cannot be expressed as
    code)."""

    resolved_evaluator_id = str(evaluator_id or "").strip()
    if not resolved_evaluator_id:
        raise IssueError("evaluator_id_required")
    get_issue(db_path=db_path, issue_id=issue_id)  # existence check
    return _apply_issue_update(
        db_path=db_path,
        issue_id=issue_id,
        assignments={"evaluator_id": resolved_evaluator_id, "status": "guarded"},
    )
