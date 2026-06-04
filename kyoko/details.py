from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .autonomy_runner import AutonomyRunError, inspect_proposal_autonomy_gate
from .confidence import assess_proposal_confidence
from .checks import list_check_capabilities
from .issues import get_issue
from .storage import StorageError, connect, initialize_database
from .vocabulary import section_description, section_label


ENTITY_TABLES = {
    "profile": "profiles",
    "source": "sources",
    "agent_identity": "agent_identities",
    "workflow_node": "workflow_nodes",
    "queue": "queues",
    "task": "tasks",
    "task_attempt": "task_attempts",
    "run": "runs",
    "span": "spans",
    "handoff": "handoffs",
    "timeline_event": "timeline_events",
    "learning_proposal": "learning_proposals",
    "proposal": "learning_proposals",
    "skill": "skills",
    "check_spec": "check_specs",
    "check_run": "check_runs",
    "replay_run": "replay_runs",
    "patch_transaction": "patch_transactions",
}
ARTIFACT_PREVIEW_BYTES = 12000


class DetailError(Exception):
    """Raised when a detail view cannot be built."""


def list_runs(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            return []
        if not _row_exists(connection, "profiles", selected_profile_id):
            raise DetailError(f"profile_not_found:{selected_profile_id}")
        rows = connection.execute(
            """
            SELECT runs.*,
                   agent_identities.name AS agent_name,
                   agent_identities.kind AS agent_kind,
                   COUNT(DISTINCT spans.id) AS span_count,
                   COUNT(DISTINCT CASE
                     WHEN spans.status IN ('failed', 'timed_out', 'errored') THEN spans.id
                     ELSE NULL
                   END) AS failed_span_count,
                   COUNT(DISTINCT handoffs.id) AS handoff_count
            FROM runs
            LEFT JOIN agent_identities ON agent_identities.id = runs.agent_identity_id
            LEFT JOIN spans ON spans.run_id = runs.id
            LEFT JOIN handoffs ON handoffs.run_id = runs.id
            WHERE runs.profile_id = ?
            GROUP BY runs.id
            ORDER BY runs.started_at DESC, runs.id DESC
            LIMIT ?
            """,
            (selected_profile_id, max(1, min(limit, 500))),
        ).fetchall()
    return [_decode_run_summary(row) for row in rows]


def get_run_detail(*, db_path: Path, run_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        run = _get_run(connection, run_id)
        decoded_run = _decode_row(run)
        profile_id = str(run["profile_id"])
        span_rows = connection.execute(
            "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id",
            (run_id,),
        ).fetchall()
        spans = [_decode_row(row) for row in span_rows]
        handoffs = _rows(
            connection,
            "SELECT * FROM handoffs WHERE run_id = ? ORDER BY created_at, id",
            (run_id,),
        )
        task_attempt = (
            _decode_row(
                connection.execute(
                    "SELECT * FROM task_attempts WHERE id = ?",
                    (run["task_attempt_id"],),
                ).fetchone()
            )
            if run["task_attempt_id"] is not None
            else None
        )
        task = (
            _decode_row(
                connection.execute(
                    "SELECT * FROM tasks WHERE id = ?",
                    (task_attempt["task_id"],),
                ).fetchone()
            )
            if isinstance(task_attempt, dict) and isinstance(task_attempt.get("task_id"), str)
            else None
        )
        entity_ids = {run_id}
        entity_ids.update(str(span["id"]) for span in spans)
        entity_ids.update(str(handoff["id"]) for handoff in handoffs)
        if isinstance(task_attempt, dict):
            entity_ids.add(str(task_attempt["id"]))
        if isinstance(task, dict):
            entity_ids.add(str(task["id"]))

        timeline_events = _timeline_events_for_entities(connection, profile_id, entity_ids)
        related_proposals = _related_proposals_for_entities(connection, profile_id, entity_ids)
        replay_runs = _rows(
            connection,
            """
            SELECT *
            FROM replay_runs
            WHERE source_run_id = ?
               OR output_ref = ?
               OR input_ref = ?
            ORDER BY created_at, id
            """,
            (run_id, run_id, run_id),
        )

        source = _resolve_entity(connection, "source", run["source_id"])
        agent_identity = (
            _resolve_entity(connection, "agent_identity", run["agent_identity_id"])
            if run["agent_identity_id"] is not None
            else None
        )

    return {
        "run": decoded_run,
        "source": source,
        "agent_identity": agent_identity,
        "task_attempt": task_attempt,
        "task": task,
        "spans": spans,
        "span_tree": _span_tree(spans),
        "handoffs": handoffs,
        "timeline_events": timeline_events,
        "related_proposals": related_proposals,
        "replay_runs": replay_runs,
        "summary": {
            "spans": len(spans),
            "failed_spans": len(
                [span for span in spans if span.get("status") in {"failed", "timed_out", "errored"}]
            ),
            "handoffs": len(handoffs),
            "timeline_events": len(timeline_events),
            "related_proposals": len(related_proposals),
            "replay_runs": len(replay_runs),
        },
    }


def get_check_detail(*, db_path: Path, check_spec_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        check_spec = _get_check_spec(connection, check_spec_id)
        decoded_check_spec = _decode_row(check_spec)
        decoded_check_spec.update(
            _check_lock_state(
                connection,
                profile_id=str(check_spec["profile_id"]),
                check_spec_id=check_spec_id,
            )
        )
        target = decoded_check_spec.get("target", {})
        resolved_target = _resolve_target_ref(connection, target)
        source_run_id = _source_run_id_for_target(connection, target)
        source_run = _resolve_entity(connection, "run", source_run_id) if source_run_id else None
        check_runs = _rows(
            connection,
            """
            SELECT *
            FROM check_runs
            WHERE check_spec_id = ?
            ORDER BY created_at, id
            """,
            (check_spec_id,),
        )
        replay_runs = _rows(
            connection,
            """
            SELECT *
            FROM replay_runs
            WHERE check_spec_id = ?
            ORDER BY created_at, id
            """,
            (check_spec_id,),
        )
        proposal = (
            _decode_row(
                connection.execute(
                    "SELECT * FROM learning_proposals WHERE id = ?",
                    (check_spec["proposal_id"],),
                ).fetchone()
            )
            if check_spec["proposal_id"] is not None
            else None
        )
        timeline_events = _timeline_events_for_entities(
            connection,
            str(check_spec["profile_id"]),
            {check_spec_id, *[str(row["id"]) for row in check_runs], *[str(row["id"]) for row in replay_runs]},
        )

    latest_check_run = check_runs[-1] if check_runs else None
    latest_replay_run = replay_runs[-1] if replay_runs else None
    return {
        "check_spec": decoded_check_spec,
        "proposal": proposal,
        "target": resolved_target,
        "source_run": source_run,
        "check_runs": check_runs,
        "latest_check_run": latest_check_run,
        "replay_runs": replay_runs,
        "latest_replay_run": latest_replay_run,
        "timeline_events": timeline_events,
        "summary": {
            "check_runs": len(check_runs),
            "passed_check_runs": len([run for run in check_runs if run.get("status") == "passed"]),
            "failed_check_runs": len([run for run in check_runs if run.get("status") == "failed"]),
            "replay_runs": len(replay_runs),
            "passed_replay_runs": len([run for run in replay_runs if run.get("status") == "passed"]),
            "latest_status": latest_check_run.get("status") if latest_check_run else "not_run",
            "latest_replay_status": latest_replay_run.get("status") if latest_replay_run else "none",
            "latest_comparison": _latest_check_comparison(latest_check_run),
            "latest_assertion_counts": _latest_assertion_counts(latest_check_run),
            "latest_assertions": _latest_assertions(latest_check_run),
            "trust_level": decoded_check_spec.get("trust_level"),
            "side_effect_mode": decoded_check_spec.get("side_effect_mode"),
        },
    }


def get_replay_detail(*, db_path: Path, replay_run_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        replay_run = _get_replay_run(connection, replay_run_id)
        decoded_replay = _decode_row(replay_run)
        check_spec = (
            _decode_row(
                connection.execute(
                    """
                    SELECT
                      check_specs.*,
                      COALESCE(check_locks.human_locked, 0) AS human_locked,
                      check_locks.reason AS human_lock_reason
                    FROM check_specs
                    LEFT JOIN check_locks
                      ON check_locks.check_spec_id = check_specs.id
                     AND check_locks.profile_id = check_specs.profile_id
                    WHERE check_specs.id = ?
                    """,
                    (replay_run["check_spec_id"],),
                ).fetchone()
            )
            if replay_run["check_spec_id"] is not None
            else None
        )
        if isinstance(check_spec, dict):
            check_spec["human_locked"] = bool(check_spec.get("human_locked"))
        proposal = (
            _decode_row(
                connection.execute(
                    "SELECT * FROM learning_proposals WHERE id = ?",
                    (replay_run["proposal_id"],),
                ).fetchone()
            )
            if replay_run["proposal_id"] is not None
            else None
        )
        source_run_id = replay_run["source_run_id"] if replay_run["source_run_id"] is not None else None
        output_run_id = replay_run["output_ref"] if replay_run["output_ref"] is not None else None
        source_run = _resolve_entity(connection, "run", source_run_id) if source_run_id else None
        output_run = _resolve_entity(connection, "run", output_run_id) if output_run_id else None
        source_spans = _spans_for_run(connection, source_run_id)
        output_spans = _spans_for_run(connection, output_run_id)
        check_runs = _rows(
            connection,
            """
            SELECT *
            FROM check_runs
            WHERE replay_run_id = ?
            ORDER BY created_at, id
            """,
            (replay_run_id,),
        )
        timeline_events = _timeline_events_for_entities(
            connection,
            str(replay_run["profile_id"]),
            {replay_run_id, *[str(row["id"]) for row in check_runs]},
        )

    result = decoded_replay.get("result", {})
    if not isinstance(result, dict):
        result = {}
    artifacts = _replay_artifact_details(decoded_replay.get("artifact_refs", []))
    return {
        "replay_run": decoded_replay,
        "check_spec": check_spec,
        "proposal": proposal,
        "source_run": source_run,
        "output_run": output_run,
        "source_spans": source_spans,
        "output_spans": output_spans,
        "check_runs": check_runs,
        "artifacts": artifacts,
        "timeline_events": timeline_events,
        "summary": {
            "status": decoded_replay.get("status"),
            "mode": decoded_replay.get("mode"),
            "side_effect_mode": decoded_replay.get("side_effect_mode"),
            "actual_side_effect_mode": result.get("actual_side_effect_mode"),
            "executed_agent": bool(result.get("executed_agent", False)),
            "source_run_id": source_run_id,
            "output_run_id": output_run_id,
            "source_spans": len(source_spans),
            "output_spans": len(output_spans),
            "check_runs": len(check_runs),
            "passed_check_runs": len([run for run in check_runs if run.get("status") == "passed"]),
            "artifacts": len(artifacts),
        },
    }


def get_proposal_detail(*, db_path: Path, proposal_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        proposal = _get_proposal(connection, proposal_id)
        decoded_proposal = _decode_row(proposal)
        decoded_proposal["section_label"] = section_label(decoded_proposal.get("section"))
        decoded_proposal["section_description"] = section_description(decoded_proposal.get("section"))
        evidence = _resolve_evidence_refs(connection, decoded_proposal.get("evidence_refs", []))
        target = _resolve_target(connection, decoded_proposal.get("problem", {}))
        check_specs = _rows(
            connection,
            """
            SELECT
              check_specs.*,
              COALESCE(check_locks.human_locked, 0) AS human_locked,
              check_locks.reason AS human_lock_reason
            FROM check_specs
            LEFT JOIN check_locks
              ON check_locks.check_spec_id = check_specs.id
             AND check_locks.profile_id = check_specs.profile_id
            WHERE check_specs.proposal_id = ?
            ORDER BY check_specs.created_at, check_specs.id
            """,
            (proposal_id,),
        )
        for check_spec_payload in check_specs:
            check_spec_payload["human_locked"] = bool(check_spec_payload.get("human_locked"))
        check_runs = _rows(
            connection,
            """
            SELECT *
            FROM check_runs
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        )
        replay_runs = _rows(
            connection,
            """
            SELECT *
            FROM replay_runs
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        )
        patch_transactions = _rows(
            connection,
            """
            SELECT *
            FROM patch_transactions
            WHERE proposal_id = ?
            ORDER BY created_at, id
            """,
            (proposal_id,),
        )
        timeline_events = _rows(
            connection,
            """
            SELECT *
            FROM timeline_events
            WHERE entity_type = 'learning_proposal'
              AND entity_id = ?
            ORDER BY at, id
            """,
            (proposal_id,),
        )
        confidence_assessment = assess_proposal_confidence(
            connection=connection,
            proposal=decoded_proposal,
        )

    try:
        autonomy_gate = inspect_proposal_autonomy_gate(db_path=db_path, proposal_id=proposal_id)
    except AutonomyRunError as exc:
        raise DetailError(str(exc)) from exc
    gate_history = _gate_history(timeline_events)
    evidence_chain = _proposal_evidence_chain(
        proposal=decoded_proposal,
        target=target,
        evidence=evidence,
        autonomy_gate=autonomy_gate,
        gate_history=gate_history,
        check_specs=check_specs,
        check_runs=check_runs,
        replay_runs=replay_runs,
        patch_transactions=patch_transactions,
    )

    return {
        "proposal": decoded_proposal,
        "confidence_assessment": confidence_assessment,
        "target": target,
        "evidence": evidence,
        "autonomy_gate": autonomy_gate,
        "gate_history": gate_history,
        "evidence_chain": evidence_chain,
        "check_guidance": _proposal_check_guidance(),
        "check_specs": check_specs,
        "check_runs": check_runs,
        "replay_runs": replay_runs,
        "patch_transactions": patch_transactions,
        "timeline_events": timeline_events,
    }


def get_issue_detail(*, db_path: Path, issue_id: str) -> dict[str, Any]:
    """Hydrate one issue: resolve evidence refs, affected entities, linked proposals.

    Issues are evidence (read/propose side). This view resolves the stored
    ``evidence_refs`` through :func:`_resolve_evidence_refs` (payload redaction on
    export happens in the standard resolution path), resolves each affected canonical
    entity, and surfaces the proposals that address the issue — both the explicitly
    stored ``proposal_ids`` and any proposal whose evidence references one of the
    affected entities (via :func:`_related_proposals_for_entities`).
    """

    issue = get_issue(db_path=db_path, issue_id=issue_id)
    with connect(db_path) as connection:
        profile_id = str(issue["profile_id"])
        evidence = _resolve_evidence_refs(connection, issue.get("evidence_refs", []))

        affected: dict[str, list[dict[str, Any]]] = {
            "agent_identities": _resolve_affected(
                connection, "agent_identity", issue.get("affected_agent_identity_ids", [])
            ),
            "workflow_nodes": _resolve_affected(
                connection, "workflow_node", issue.get("affected_workflow_node_ids", [])
            ),
            "tasks": _resolve_affected(connection, "task", issue.get("affected_task_ids", [])),
            "spans": _resolve_affected(connection, "span", issue.get("affected_span_ids", [])),
        }

        linked_proposals: list[dict[str, Any]] = []
        seen_proposal_ids: set[str] = set()
        for proposal_id in issue.get("proposal_ids", []):
            if not isinstance(proposal_id, str) or proposal_id in seen_proposal_ids:
                continue
            row = connection.execute(
                "SELECT * FROM learning_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                continue
            proposal = _decode_row(row)
            seen_proposal_ids.add(proposal_id)
            linked_proposals.append(
                {
                    "proposal": {
                        "id": proposal["id"],
                        "section": proposal.get("section"),
                        "state": proposal.get("state"),
                        "title": proposal.get("title"),
                        "summary": proposal.get("summary"),
                        "confidence": proposal.get("confidence"),
                        "created_at": proposal.get("created_at"),
                    },
                    "link": "explicit",
                    "matched_evidence_refs": [],
                }
            )

        affected_entity_ids: set[str] = set()
        for ids_key in (
            "affected_agent_identity_ids",
            "affected_workflow_node_ids",
            "affected_task_ids",
            "affected_span_ids",
        ):
            affected_entity_ids.update(
                str(value) for value in issue.get(ids_key, []) if isinstance(value, str)
            )
        for ref in issue.get("evidence_refs", []):
            if isinstance(ref, dict) and isinstance(ref.get("entity_id"), str):
                affected_entity_ids.add(ref["entity_id"])

        related = _related_proposals_for_entities(connection, profile_id, affected_entity_ids)
        for entry in related:
            proposal_id = entry.get("proposal", {}).get("id")
            if not isinstance(proposal_id, str) or proposal_id in seen_proposal_ids:
                continue
            seen_proposal_ids.add(proposal_id)
            linked_proposals.append(
                {
                    "proposal": entry["proposal"],
                    "link": "related",
                    "matched_evidence_refs": entry.get("matched_evidence_refs", []),
                }
            )

    return {
        "issue": issue,
        "section_label": section_label(issue.get("section")) if issue.get("section") else None,
        "section_description": (
            section_description(issue.get("section")) if issue.get("section") else None
        ),
        "evidence": evidence,
        "affected": affected,
        "linked_proposals": linked_proposals,
        "summary": {
            "evidence_refs": len(evidence),
            "resolved_evidence_refs": len([item for item in evidence if item.get("found")]),
            "affected_agent_identities": len(affected["agent_identities"]),
            "affected_workflow_nodes": len(affected["workflow_nodes"]),
            "affected_tasks": len(affected["tasks"]),
            "affected_spans": len(affected["spans"]),
            "linked_proposals": len(linked_proposals),
        },
    }


def _resolve_affected(
    connection: sqlite3.Connection,
    entity_type: str,
    entity_ids: Any,
) -> list[dict[str, Any]]:
    if not isinstance(entity_ids, list):
        return []
    resolved = []
    for entity_id in entity_ids:
        row = _resolve_entity(connection, entity_type, entity_id)
        resolved.append(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "resolved": row,
                "found": row is not None,
            }
        )
    return resolved


def _proposal_check_guidance() -> dict[str, Any]:
    capabilities = list_check_capabilities()
    check_types = capabilities.get("check_types") if isinstance(capabilities.get("check_types"), list) else []
    replay = capabilities.get("replay") if isinstance(capabilities.get("replay"), dict) else {}
    presets = capabilities.get("assertion_presets") if isinstance(capabilities.get("assertion_presets"), list) else []
    judge = capabilities.get("judge") if isinstance(capabilities.get("judge"), dict) else {}
    informational_check_types = [
        item.get("name")
        for item in check_types
        if isinstance(item, dict)
        and item.get("executable") is True
        and item.get("gateable") is False
        and isinstance(item.get("name"), str)
    ]
    return {
        "executable_check_types": _string_list(capabilities.get("executable_check_types")),
        "gateable_check_types": _string_list(capabilities.get("gateable_check_types")),
        "informational_check_types": informational_check_types,
        "safe_replay_side_effect_modes": _string_list(replay.get("safe_side_effect_modes")),
        "assertion_presets": [
            {
                "name": preset["name"],
                "assertions": _string_list(preset.get("assertions")),
                "gateable_check_types": _string_list(preset.get("gateable_check_types")),
            }
            for preset in presets
            if isinstance(preset, dict) and isinstance(preset.get("name"), str)
        ],
        "recorded_judge_only": judge.get("invokes_model") is False,
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _get_run(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("runs table is missing") from exc
    if row is None:
        raise DetailError(f"run_not_found:{run_id}")
    return row


def _get_check_spec(connection: sqlite3.Connection, check_spec_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM check_specs WHERE id = ?",
            (check_spec_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("check_specs table is missing") from exc
    if row is None:
        raise DetailError(f"check_spec_not_found:{check_spec_id}")
    return row


def _get_replay_run(connection: sqlite3.Connection, replay_run_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM replay_runs WHERE id = ?",
            (replay_run_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("replay_runs table is missing") from exc
    if row is None:
        raise DetailError(f"replay_run_not_found:{replay_run_id}")
    return row


def _check_lock_state(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    check_spec_id: str,
) -> dict[str, Any]:
    try:
        row = connection.execute(
            """
            SELECT human_locked, reason
            FROM check_locks
            WHERE profile_id = ? AND check_spec_id = ?
            """,
            (profile_id, check_spec_id),
        ).fetchone()
    except sqlite3.OperationalError:
        return {"human_locked": False, "human_lock_reason": None}
    if row is None:
        return {"human_locked": False, "human_lock_reason": None}
    return {
        "human_locked": int(row["human_locked"]) == 1,
        "human_lock_reason": row["reason"],
    }


def _get_proposal(connection: sqlite3.Connection, proposal_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("learning_proposals table is missing") from exc
    if row is None:
        raise DetailError(f"proposal_not_found:{proposal_id}")
    return row


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _row_exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (row_id,)).fetchone()
    return row is not None


def _timeline_events_for_entities(
    connection: sqlite3.Connection,
    profile_id: str,
    entity_ids: set[str],
) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    placeholders = ",".join("?" for _ in entity_ids)
    args: tuple[Any, ...] = (profile_id, *sorted(entity_ids))
    return _rows(
        connection,
        f"""
        SELECT *
        FROM timeline_events
        WHERE profile_id = ?
          AND entity_id IN ({placeholders})
        ORDER BY at, id
        """,
        args,
    )


def _related_proposals_for_entities(
    connection: sqlite3.Connection,
    profile_id: str,
    entity_ids: set[str],
) -> list[dict[str, Any]]:
    proposals = _rows(
        connection,
        """
        SELECT *
        FROM learning_proposals
        WHERE profile_id = ?
        ORDER BY created_at, id
        """,
        (profile_id,),
    )
    related = []
    for proposal in proposals:
        refs = proposal.get("evidence_refs", [])
        if not isinstance(refs, list):
            continue
        matched_refs = [
            ref
            for ref in refs
            if isinstance(ref, dict) and isinstance(ref.get("entity_id"), str) and ref["entity_id"] in entity_ids
        ]
        if not matched_refs:
            continue
        related.append(
            {
                "proposal": {
                    "id": proposal["id"],
                    "section": proposal["section"],
                    "state": proposal["state"],
                    "title": proposal["title"],
                    "summary": proposal["summary"],
                    "confidence": proposal["confidence"],
                    "kyoko_confidence": proposal.get("kyoko_confidence"),
                    "confidence_level": proposal.get("confidence_level"),
                    "created_at": proposal["created_at"],
                },
                "matched_evidence_refs": matched_refs,
            }
        )
    return related


def _span_tree(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = [{**span, "children": []} for span in spans]
    by_id = {str(node["id"]): node for node in nodes}
    roots = []
    for node in nodes:
        parent_id = node.get("parent_span_id")
        parent = by_id.get(parent_id) if isinstance(parent_id, str) else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)
    return roots


def _resolve_target_ref(connection: sqlite3.Connection, target: Any) -> dict[str, Any]:
    if not isinstance(target, dict):
        return {"ref": target, "resolved": None, "found": False}
    row = _resolve_entity(connection, target.get("entity_type"), target.get("entity_id"))
    return {
        "ref": target,
        "resolved": row,
        "found": row is not None,
    }


def _source_run_id_for_target(connection: sqlite3.Connection, target: Any) -> Optional[str]:
    if not isinstance(target, dict):
        return None
    entity_type = target.get("entity_type")
    entity_id = target.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return None
    if entity_type == "run":
        return entity_id
    if entity_type == "span":
        row = connection.execute("SELECT run_id FROM spans WHERE id = ?", (entity_id,)).fetchone()
        return str(row["run_id"]) if row is not None else None
    if entity_type == "task_attempt":
        row = connection.execute("SELECT run_id FROM task_attempts WHERE id = ?", (entity_id,)).fetchone()
        if row is not None and row["run_id"] is not None:
            return str(row["run_id"])
    return None


def _spans_for_run(connection: sqlite3.Connection, run_id: Any) -> list[dict[str, Any]]:
    if not isinstance(run_id, str) or not run_id:
        return []
    return _rows(
        connection,
        "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id",
        (run_id,),
    )


def _latest_check_comparison(latest_check_run: Optional[dict[str, Any]]) -> Optional[str]:
    if not isinstance(latest_check_run, dict):
        return None
    result = latest_check_run.get("result")
    if not isinstance(result, dict):
        return None
    comparison = result.get("comparison")
    return comparison if isinstance(comparison, str) else None


def _latest_assertion_counts(latest_check_run: Optional[dict[str, Any]]) -> dict[str, int]:
    if not isinstance(latest_check_run, dict):
        return {"total": 0, "passed": 0, "failed": 0}
    result = latest_check_run.get("result")
    if not isinstance(result, dict):
        return {"total": 0, "passed": 0, "failed": 0}
    counts = result.get("assertion_counts")
    if not isinstance(counts, dict):
        return {"total": 0, "passed": 0, "failed": 0}
    return {
        "total": int(counts.get("total") or 0),
        "passed": int(counts.get("passed") or 0),
        "failed": int(counts.get("failed") or 0),
    }


def _latest_assertions(latest_check_run: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(latest_check_run, dict):
        return []
    result = latest_check_run.get("result")
    if not isinstance(result, dict):
        return []
    assertions = result.get("assertions")
    if not isinstance(assertions, list):
        return []
    normalized = []
    for index, assertion in enumerate(assertions, start=1):
        if not isinstance(assertion, dict):
            continue
        normalized.append(
            {
                "index": index,
                "type": assertion.get("type"),
                "passed": bool(assertion.get("passed", False)),
                "reason": assertion.get("reason"),
                "comparison": assertion.get("comparison"),
                "path": assertion.get("path"),
                "expected": assertion.get("expected"),
                "actual": assertion.get("actual"),
                "entity": assertion.get("entity"),
                "observed_status": assertion.get("observed_status"),
                "replay_observed_status": assertion.get("replay_observed_status"),
                "preset": assertion.get("preset"),
                "supported_presets": assertion.get("supported_presets"),
            }
        )
    return normalized


def _replay_artifact_details(refs: Any) -> list[dict[str, Any]]:
    if not isinstance(refs, list):
        return []
    artifacts = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        path_value = ref.get("path")
        kind = ref.get("kind")
        if not isinstance(path_value, str) or not path_value:
            continue
        path = Path(path_value)
        artifact: dict[str, Any] = {
            "kind": kind if isinstance(kind, str) else "artifact",
            "path": path_value,
            "media_type": ref.get("media_type") if isinstance(ref.get("media_type"), str) else None,
            "exists": path.exists(),
            "size_bytes": None,
            "preview": "",
            "preview_truncated": False,
        }
        if path.exists() and path.is_file():
            size = path.stat().st_size
            artifact["size_bytes"] = size
            with path.open("rb") as handle:
                if size > ARTIFACT_PREVIEW_BYTES:
                    handle.seek(-ARTIFACT_PREVIEW_BYTES, 2)
                    artifact["preview_truncated"] = True
                artifact["preview"] = handle.read().decode("utf-8", errors="replace")
        artifacts.append(artifact)
    return artifacts


def _gate_history(timeline_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history = []
    for event in timeline_events:
        if not isinstance(event, dict):
            continue
        kind = event.get("kind")
        if not isinstance(kind, str) or not kind.startswith("autonomy_"):
            continue
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        action = metadata.get("action")
        if kind == "autonomy_gated" and not action:
            action = "gated"
        elif kind == "autonomy_applied" and not action:
            action = "applied"
        elif kind == "autonomy_harness_prepared" and not action:
            action = "prepared"
        elif kind == "autonomy_regression_rolled_back" and not action:
            action = "rolled_back"
        elif kind in {"autonomy_regression_failed", "autonomy_regression_rollback_failed"} and not action:
            action = "failed"
        history.append(
            {
                "event_id": event.get("id"),
                "at": event.get("at"),
                "kind": kind,
                "action": action,
                "reason": metadata.get("reason"),
                "state_before": metadata.get("state_before"),
                "state_after": metadata.get("state_after"),
                "required_check_level": metadata.get("required_check_level"),
                "check_spec_ids": metadata.get("check_spec_ids", []),
                "check_run_ids": metadata.get("check_run_ids", []),
                "applied_skill_ids": metadata.get("applied_skill_ids", []),
                "applied_context_rule_ids": metadata.get("applied_context_rule_ids", []),
                "patch_transaction_ids": metadata.get("patch_transaction_ids", []),
                "detail": metadata.get("detail", {}),
                "metadata": metadata,
            }
        )
    return history


def _proposal_evidence_chain(
    *,
    proposal: dict[str, Any],
    target: dict[str, Any],
    evidence: list[dict[str, Any]],
    autonomy_gate: dict[str, Any],
    gate_history: list[dict[str, Any]],
    check_specs: list[dict[str, Any]],
    check_runs: list[dict[str, Any]],
    replay_runs: list[dict[str, Any]],
    patch_transactions: list[dict[str, Any]],
) -> dict[str, Any]:
    resolved_evidence = [item for item in evidence if item.get("found")]
    missing_evidence = len(evidence) - len(resolved_evidence)
    problem = proposal.get("problem") if isinstance(proposal.get("problem"), dict) else {}
    gate_expectations = (
        proposal.get("gate_expectations") if isinstance(proposal.get("gate_expectations"), dict) else {}
    )
    target_ref = target.get("ref") if isinstance(target.get("ref"), dict) else {}
    target_label = _target_label(target_ref)
    latest_check_runs = _latest_rows_by_key(check_runs, "check_spec_id")
    latest_replay_runs = _latest_rows_by_key(replay_runs, "check_spec_id")
    check_status = _combined_status(latest_check_runs, empty_status="not_run")
    replay_status = _combined_status(latest_replay_runs, empty_status="not_run")
    if not check_specs:
        check_status = "not_generated"
    if not replay_runs and gate_expectations.get("requires_replay") is False:
        replay_status = "not_required"
    latest_check = latest_check_runs[-1] if latest_check_runs else None
    latest_replay = latest_replay_runs[-1] if latest_replay_runs else None
    autonomy_action = autonomy_gate.get("action") or "unknown"
    autonomy_reason = autonomy_gate.get("reason") or "unknown"

    steps: list[dict[str, Any]] = [
        {
            "stage": "observed_issue",
            "title": "Observed issue",
            "status": "resolved" if missing_evidence == 0 else "missing_evidence",
            "description": problem.get("issue") or proposal.get("summary") or "",
            "evidence_refs": len(evidence),
            "resolved_refs": len(resolved_evidence),
            "missing_refs": missing_evidence,
            "primary_evidence": _primary_evidence_summary(resolved_evidence),
        },
        {
            "stage": "proposed_fix",
            "title": "Proposed fix",
            "status": proposal.get("state") or "unknown",
            "description": proposal.get("insight") or proposal.get("summary") or "",
            "proposal_id": proposal.get("id"),
            "section": proposal.get("section"),
            "target": target_ref,
            "target_label": target_label,
            "change_count": _proposal_change_count(proposal),
        },
        {
            "stage": "check_gate",
            "title": "Check gate",
            "status": check_status,
            "description": _check_gate_description(check_status, latest_check),
            "required_check_level": autonomy_gate.get("required_check_level")
            or gate_expectations.get("requires_check_level"),
            "check_spec_ids": [spec.get("id") for spec in check_specs if spec.get("id")],
            "latest_check_run_id": latest_check.get("id") if isinstance(latest_check, dict) else None,
            "latest_check_status": latest_check.get("status") if isinstance(latest_check, dict) else None,
            "latest_trust_level": _latest_trust_level(check_specs),
            "latest_assertion_counts": _latest_assertion_counts(latest_check),
        },
        {
            "stage": "replay",
            "title": "Replay",
            "status": replay_status,
            "description": _replay_description(replay_status, latest_replay),
            "required": bool(gate_expectations.get("requires_replay", True)),
            "replay_run_ids": [run.get("id") for run in replay_runs if run.get("id")],
            "latest_replay_run_id": latest_replay.get("id") if isinstance(latest_replay, dict) else None,
            "latest_replay_status": latest_replay.get("status") if isinstance(latest_replay, dict) else None,
            "side_effect_mode": _latest_side_effect_mode(check_specs, latest_replay),
        },
    ]
    if patch_transactions:
        latest_patch = patch_transactions[-1]
        steps.append(
            {
                "stage": "harness_patch",
                "title": "Harness patch",
                "status": latest_patch.get("status") or "prepared",
                "description": f"{len(patch_transactions)} patch transaction(s) are linked to this proposal.",
                "patch_transaction_ids": [
                    patch.get("id") for patch in patch_transactions if patch.get("id")
                ],
                "latest_patch_transaction_id": latest_patch.get("id"),
            }
        )
    steps.append(
        {
            "stage": "autonomy",
            "title": "Autonomy decision",
            "status": autonomy_action,
            "description": _autonomy_description(autonomy_action, autonomy_reason),
            "reason": autonomy_reason,
            "gate_history_events": len(gate_history),
            "latest_gate_event_id": gate_history[-1].get("event_id") if gate_history else None,
        }
    )
    ready_to_apply = autonomy_action in {"would_apply", "applied"}
    return {
        "summary": _evidence_chain_summary(
            proposal=proposal,
            evidence_status=steps[0]["status"],
            check_status=check_status,
            replay_status=replay_status,
            autonomy_action=autonomy_action,
            autonomy_reason=autonomy_reason,
        ),
        "ready_to_apply": ready_to_apply,
        "blocking_reason": None if ready_to_apply else autonomy_reason,
        "steps": steps,
    }


def _latest_rows_by_key(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    fallback = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, str) and value:
            latest[value] = row
        else:
            fallback.append(row)
    return list(latest.values()) if latest else fallback


def _combined_status(rows: list[dict[str, Any]], *, empty_status: str) -> str:
    if not rows:
        return empty_status
    statuses = {str(row.get("status") or "unknown") for row in rows}
    if statuses == {"passed"}:
        return "passed"
    if statuses & {"failed", "errored", "timed_out"}:
        return "failed"
    if statuses == {"pending"}:
        return "pending"
    if len(statuses) == 1:
        return next(iter(statuses))
    return "mixed"


def _proposal_change_count(proposal: dict[str, Any]) -> int:
    changes = proposal.get("proposed_changes")
    return len(changes) if isinstance(changes, list) else 0


def _target_label(target_ref: dict[str, Any]) -> str:
    entity_type = target_ref.get("entity_type") or "unknown"
    entity_id = target_ref.get("entity_id") or "unknown"
    name = target_ref.get("name")
    return f"{name} ({entity_type}:{entity_id})" if isinstance(name, str) and name else f"{entity_type}:{entity_id}"


def _primary_evidence_summary(resolved_evidence: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not resolved_evidence:
        return None
    item = resolved_evidence[0]
    ref = item.get("ref") if isinstance(item.get("ref"), dict) else {}
    resolved = item.get("resolved") if isinstance(item.get("resolved"), dict) else {}
    return {
        "entity_type": ref.get("entity_type"),
        "entity_id": ref.get("entity_id"),
        "role": ref.get("role"),
        "status": resolved.get("status"),
        "name": resolved.get("name") or resolved.get("kind"),
        "summary": resolved.get("summary") or ref.get("note"),
    }


def _latest_trust_level(check_specs: list[dict[str, Any]]) -> Optional[str]:
    if not check_specs:
        return None
    trust_levels = [spec.get("trust_level") for spec in check_specs if isinstance(spec.get("trust_level"), str)]
    return trust_levels[-1] if trust_levels else None


def _latest_side_effect_mode(
    check_specs: list[dict[str, Any]],
    latest_replay: Optional[dict[str, Any]],
) -> Optional[str]:
    if isinstance(latest_replay, dict) and isinstance(latest_replay.get("side_effect_mode"), str):
        return latest_replay["side_effect_mode"]
    if check_specs and isinstance(check_specs[-1].get("side_effect_mode"), str):
        return check_specs[-1]["side_effect_mode"]
    return None


def _check_gate_description(status: str, latest_check: Optional[dict[str, Any]]) -> str:
    if status == "not_generated":
        return "No check spec has been generated for this proposal yet."
    if status == "not_run":
        return "Check specs exist, but no check run has completed yet."
    if status == "passed":
        trust = latest_check.get("promoted_trust_level") if isinstance(latest_check, dict) else None
        suffix = f" with {trust}" if isinstance(trust, str) and trust else ""
        return f"The latest check gate passed{suffix}."
    if status == "failed":
        return "At least one latest check run failed."
    return f"Check gate status is {status}."


def _replay_description(status: str, latest_replay: Optional[dict[str, Any]]) -> str:
    if status == "not_required":
        return "This proposal does not require replay."
    if status == "not_run":
        return "No replay run has completed for this proposal yet."
    if status == "passed":
        mode = _latest_side_effect_mode([], latest_replay)
        suffix = f" under {mode}" if isinstance(mode, str) and mode else ""
        return f"The latest replay passed{suffix}."
    if status == "failed":
        return "At least one latest replay run failed."
    return f"Replay status is {status}."


def _autonomy_description(action: str, reason: str) -> str:
    if action == "would_apply":
        return "The proposal satisfies the current gate and would apply in autonomous mode."
    if action == "applied":
        return "The proposal has been applied."
    if action == "awaiting_human_review":
        return "The current policy requires a human decision before applying."
    if action == "gated":
        return f"The proposal is gated by {reason}."
    if action == "prepared":
        return "The harness change has been prepared for review or apply."
    return f"Autonomy action is {action} because {reason}."


def _evidence_chain_summary(
    *,
    proposal: dict[str, Any],
    evidence_status: str,
    check_status: str,
    replay_status: str,
    autonomy_action: str,
    autonomy_reason: str,
) -> str:
    title = proposal.get("title") or proposal.get("id") or "proposal"
    return (
        f"{title}: evidence {evidence_status}, check {check_status}, "
        f"replay {replay_status}, autonomy {autonomy_action} ({autonomy_reason})."
    )


def _resolve_evidence_refs(connection: sqlite3.Connection, refs: Any) -> list[dict[str, Any]]:
    if not isinstance(refs, list):
        return []
    resolved = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        entity_type = ref.get("entity_type")
        entity_id = ref.get("entity_id")
        row = _resolve_entity(connection, entity_type, entity_id)
        resolved.append(
            {
                "ref": ref,
                "resolved": row,
                "found": row is not None,
            }
        )
    return resolved


def _resolve_target(connection: sqlite3.Connection, problem: Any) -> dict[str, Any]:
    if not isinstance(problem, dict):
        return {"ref": None, "resolved": None, "found": False}
    target = problem.get("target")
    if not isinstance(target, dict):
        return {"ref": None, "resolved": None, "found": False}
    entity_type = target.get("entity_type")
    entity_id = target.get("entity_id")
    row = _resolve_entity(connection, entity_type, entity_id)
    return {
        "ref": target,
        "resolved": row,
        "found": row is not None,
    }


def _resolve_entity(
    connection: sqlite3.Connection,
    entity_type: Any,
    entity_id: Any,
) -> Optional[dict[str, Any]]:
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return None
    table = ENTITY_TABLES.get(entity_type)
    if table is None:
        return None
    try:
        row = connection.execute(f"SELECT * FROM {table} WHERE id = ?", (entity_id,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return _decode_row(row) if row is not None else None


def _rows(connection: sqlite3.Connection, query: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [_decode_row(row) for row in connection.execute(query, args).fetchall()]


def _decode_row(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        return {}
    payload = dict(row)
    for key, value in list(payload.items()):
        if key.endswith("_json") and isinstance(value, str):
            payload[key[:-5]] = _json_loads(value, None)
            del payload[key]
    return payload


def _decode_run_summary(row: sqlite3.Row) -> dict[str, Any]:
    payload = _decode_row(row)
    payload["span_count"] = int(payload.get("span_count") or 0)
    payload["failed_span_count"] = int(payload.get("failed_span_count") or 0)
    payload["handoff_count"] = int(payload.get("handoff_count") or 0)
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
