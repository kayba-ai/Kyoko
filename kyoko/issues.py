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
  ``open → prioritized → diagnosed → accepted → proposed → applied → resolved → guarded``
  with ``dismissed`` as a terminal off-ramp from any state. ``open``/``resolved``/
  ``dismissed`` are retained for backward compatibility. ``accepted`` (v30, gate #1) marks
  an issue approved for a fix — analysis stops at ``diagnosed`` and a proposal is only
  authored once the issue is accepted (auto in ``autonomous`` mode, human in ``propose``).

Deterministic dedup (v30): analysis surfaces issues through :func:`surface_issue`, which
fingerprints each failure (:func:`compute_issue_signature` — run-independent: section +
affected span *names* + stable target ids) and folds a recurrence into the existing issue
(bumping ``recurrence_count`` and re-opening a resolved/guarded one) instead of spawning a
duplicate. Fuzzy/semantic bundling is layered on top later by the warm analysis agent.
"""

from __future__ import annotations

import hashlib
import json
import re
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
    "accepted",
    "proposed",
    "applied",
    "resolved",
    "guarded",
    "dismissed",
)
# Forward progression of the lifecycle (dismissed is reachable from any state and is
# omitted here). Used to validate monotonic advancement; plain `update_issue_status`
# stays permissive for manual triage/correction.
#
# `accepted` (v30) is gate #1: analysis only surfaces/diagnoses an issue — a proposal is
# authored once the issue is *accepted for a fix* (auto in `autonomous` mode, by a human
# in `propose` mode). It sits between `diagnosed` and `proposed`.
ISSUE_LIFECYCLE_ORDER = (
    "open",
    "prioritized",
    "diagnosed",
    "accepted",
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
        "signature": row["signature"] if "signature" in row.keys() else None,
        "recurrence_count": (
            row["recurrence_count"] if "recurrence_count" in row.keys() else None
        ),
        "accepted_at": row["accepted_at"] if "accepted_at" in row.keys() else None,
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
    signature: Optional[str] = None,
    recurrence_count: int = 1,
    profile_id: Optional[str] = None,
) -> dict:
    """Persist one issue (evidence only) and return its stored record.

    ``signature`` is the deterministic dedup fingerprint (normally supplied by
    :func:`surface_issue`); ``recurrence_count`` starts at 1. Neither changes behavior."""

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
              source, root_cause, rank, signature, recurrence_count,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                signature,
                int(recurrence_count),
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
        "signature": signature,
        "recurrence_count": int(recurrence_count),
        "accepted_at": None,
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


# --------------------------------------------------------------------------------------
# v30: deterministic dedup net + gate-#1 acceptance.
# --------------------------------------------------------------------------------------

# Statuses past which an issue is no longer "active" for bundling. A recurrence that
# matches a resolved/guarded issue is a regression and re-opens it (the guard didn't hold).
_REOPEN_FROM = ("resolved", "guarded")
_STOPWORDS = frozenset(
    {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "was"}
)


def _title_slug(title: Optional[str]) -> str:
    tokens = [
        tok
        for tok in re.findall(r"[a-z0-9]+", str(title or "").lower())
        if len(tok) >= 3 and tok not in _STOPWORDS
    ]
    return " ".join(sorted(set(tokens)))


def _resolve_span_names(connection: Any, span_ids: list[str]) -> list[str]:
    """Run-independent anchor: map per-run span ids to their span *names* (which recur
    across runs, unlike ids). Mirrors :func:`kyoko.issue_guard._affected_span_names`."""

    if not span_ids:
        return []
    placeholders = ",".join("?" for _ in span_ids)
    rows = connection.execute(
        f"SELECT DISTINCT name FROM spans WHERE id IN ({placeholders})",
        tuple(span_ids),
    ).fetchall()
    return sorted({str(row[0]) for row in rows if row[0]})


def compute_issue_signature(
    connection: Any,
    *,
    profile_id: str,
    section: Optional[str],
    affected_span_ids: Optional[list] = None,
    affected_agent_identity_ids: Optional[list] = None,
    affected_workflow_node_ids: Optional[list] = None,
    title: Optional[str] = None,
) -> str:
    """Deterministic fingerprint of a failure, stable across runs. Anchors on the section,
    the affected span *names* (not per-run ids), and stable target ids (agent identity /
    workflow node). When no structural anchors exist it falls back to a normalized title
    slug so distinct title-only issues do not collapse together."""

    span_names = _resolve_span_names(connection, list(affected_span_ids or []))
    agent_ids = sorted({str(x) for x in (affected_agent_identity_ids or [])})
    node_ids = sorted({str(x) for x in (affected_workflow_node_ids or [])})
    components: dict[str, Any] = {
        "profile_id": profile_id,
        "section": section or "",
        "span_names": span_names,
        "targets": agent_ids + node_ids,
    }
    if not span_names and not agent_ids and not node_ids:
        components["title_slug"] = _title_slug(title)
    payload = json.dumps(components, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def find_issue_by_signature(
    connection: Any,
    *,
    profile_id: str,
    signature: Optional[str],
    exclude_id: Optional[str] = None,
) -> Optional[dict]:
    """Return the most-recent non-dismissed issue in this profile carrying ``signature``
    (the bundling target), or ``None``."""

    if not signature:
        return None
    params: list[Any] = [profile_id, signature]
    clause = "profile_id = ? AND signature = ? AND status != 'dismissed'"
    if exclude_id:
        clause += " AND id != ?"
        params.append(exclude_id)
    row = connection.execute(
        f"SELECT * FROM issues WHERE {clause} ORDER BY created_at DESC, id ASC LIMIT 1",
        tuple(params),
    ).fetchone()
    return _row_to_dict(row) if row is not None else None


def bundle_into_issue(
    *,
    db_path: Path,
    issue_id: str,
    evidence_refs: Optional[list] = None,
    affected_span_ids: Optional[list] = None,
    reopen: bool = True,
) -> dict:
    """Fold a fresh recurrence into an existing issue: union its evidence and affected
    spans, bump ``recurrence_count``, and (when ``reopen``) re-open a resolved/guarded
    issue as a regression. Evidence only — never touches the gate."""

    current = get_issue(db_path=db_path, issue_id=issue_id)

    merged_evidence = list(current.get("evidence_refs") or [])
    seen = {json.dumps(ref, sort_keys=True) for ref in merged_evidence}
    for ref in evidence_refs or []:
        key = json.dumps(ref, sort_keys=True)
        if key not in seen:
            merged_evidence.append(ref)
            seen.add(key)

    merged_spans = list(current.get("affected_span_ids") or [])
    span_seen = set(merged_spans)
    for span_id in affected_span_ids or []:
        if span_id not in span_seen:
            merged_spans.append(span_id)
            span_seen.add(span_id)

    next_count = int(current.get("recurrence_count") or 1) + 1
    assignments: dict[str, Any] = {
        "evidence_refs_json": _json_dump(merged_evidence),
        "affected_span_ids_json": _json_dump(merged_spans),
        "recurrence_count": next_count,
    }
    if reopen and current.get("status") in _REOPEN_FROM:
        assignments["status"] = "open"

    record = _apply_issue_update(
        db_path=db_path, issue_id=issue_id, assignments=assignments
    )
    record["evidence_refs"] = merged_evidence
    record["affected_span_ids"] = merged_spans
    record["recurrence_count"] = next_count
    record.pop("evidence_refs_json", None)
    record.pop("affected_span_ids_json", None)
    return record


def surface_issue(
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
) -> tuple[dict, bool]:
    """Surface an issue through the deterministic dedup net (the v30 analysis entry point).

    Computes the failure signature; if a non-dismissed issue with the same signature
    already exists in this profile, the recurrence is folded into it (returns
    ``(issue, True)``). Otherwise a new issue is created with the signature stamped
    (returns ``(issue, False)``). Evidence only — surfacing never changes behavior."""

    initialize_database(db_path)
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        signature = compute_issue_signature(
            connection,
            profile_id=resolved_profile_id,
            section=section,
            affected_span_ids=affected_span_ids,
            affected_agent_identity_ids=affected_agent_identity_ids,
            affected_workflow_node_ids=affected_workflow_node_ids,
            title=title,
        )
        existing = find_issue_by_signature(
            connection, profile_id=resolved_profile_id, signature=signature
        )

    if existing is not None:
        bundled = bundle_into_issue(
            db_path=db_path,
            issue_id=existing["id"],
            evidence_refs=evidence_refs,
            affected_span_ids=affected_span_ids,
        )
        return bundled, True

    created = create_issue(
        db_path=db_path,
        title=title,
        body=body,
        section=section,
        category=category,
        severity=severity,
        status=status,
        evidence_refs=evidence_refs,
        affected_agent_identity_ids=affected_agent_identity_ids,
        affected_workflow_node_ids=affected_workflow_node_ids,
        affected_task_ids=affected_task_ids,
        affected_span_ids=affected_span_ids,
        proposal_ids=proposal_ids,
        source=source,
        root_cause=root_cause,
        rank=rank,
        signature=signature,
        profile_id=resolved_profile_id,
    )
    return created, False


def accept_issue(*, db_path: Path, issue_id: str) -> dict:
    """Gate #1: mark an issue accepted for a fix (job step "approve"), stamping
    ``accepted_at`` and advancing it to ``accepted``. This is the point a proposal is
    authorized to be authored (auto in ``autonomous`` mode, by a human in ``propose``).
    Permissive/idempotent; refuses only a ``dismissed`` issue."""

    current = get_issue(db_path=db_path, issue_id=issue_id)
    if current["status"] == "dismissed":
        raise IssueError(f"issue_dismissed:{issue_id}")
    return _apply_issue_update(
        db_path=db_path,
        issue_id=issue_id,
        assignments={"status": "accepted", "accepted_at": utc_now()},
    )
