from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Optional


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
    "eval_spec": "eval_specs",
    "eval_run": "eval_runs",
    "replay_run": "replay_runs",
    "patch_transaction": "patch_transactions",
}
TRUST_ORDER = {
    "L0_generated": 0,
    "L1_repeated": 1,
    "L2_regression": 2,
    "L3_human_approved": 3,
}
ACTIVE_STATES = {"pending", "ready", "review"}


def assess_proposal_confidence(
    *,
    connection: sqlite3.Connection,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """Return Kyoko's evidence-grounded confidence assessment for a proposal."""

    operator_confidence = _clamp_float(proposal.get("confidence"), default=0.0)
    evidence = _evidence_metrics(connection, proposal)
    verification = _verification_metrics(connection, proposal)
    duplicates = _duplicate_metrics(connection, proposal)
    validation_errors = proposal.get("validation_errors", [])
    if not isinstance(validation_errors, list):
        validation_errors = []

    factors: list[dict[str, Any]] = []
    score = 0.10
    factors.append(_factor("base", 0.10, "Starting confidence for a schema-valid stored proposal."))

    operator_contribution = round(operator_confidence * 0.25, 4)
    score += operator_contribution
    factors.append(
        _factor(
            "operator_reported_confidence",
            operator_contribution,
            f"Operator reported {operator_confidence:.2f}; Kyoko caps that signal at 25% of the score.",
        )
    )

    evidence_contribution = _evidence_contribution(evidence)
    score += evidence_contribution
    factors.append(_factor("evidence_coverage", evidence_contribution, evidence["note"]))

    verification_contribution = _verification_contribution(verification)
    score += verification_contribution
    factors.append(_factor("eval_replay_verification", verification_contribution, verification["note"]))

    duplicate_penalty = min(0.18, duplicates["similar_active_proposals"] * 0.06)
    if duplicate_penalty:
        score -= duplicate_penalty
        factors.append(
            _factor(
                "duplicate_penalty",
                -round(duplicate_penalty, 4),
                f"{duplicates['similar_active_proposals']} similar active proposal(s) reduce confidence.",
            )
        )

    validation_penalty = min(0.20, len(validation_errors) * 0.05)
    if validation_penalty:
        score -= validation_penalty
        factors.append(
            _factor(
                "validation_penalty",
                -round(validation_penalty, 4),
                f"{len(validation_errors)} stored validation warning(s) reduce confidence.",
            )
        )

    kyoko_confidence = round(max(0.0, min(0.99, score)), 2)
    return {
        "operator_confidence": operator_confidence,
        "kyoko_confidence": kyoko_confidence,
        "confidence_delta": round(kyoko_confidence - operator_confidence, 2),
        "level": _confidence_level(kyoko_confidence),
        "factors": factors,
        "evidence": evidence,
        "verification": verification,
        "duplicates": duplicates,
        "validation_errors": validation_errors,
    }


def _evidence_metrics(connection: sqlite3.Connection, proposal: dict[str, Any]) -> dict[str, Any]:
    refs = proposal.get("evidence_refs", [])
    refs = refs if isinstance(refs, list) else []
    resolved_refs = 0
    ref_types = set()
    roles = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        entity_type = ref.get("entity_type")
        entity_id = ref.get("entity_id")
        role = ref.get("role")
        if isinstance(entity_type, str):
            ref_types.add(entity_type)
        if isinstance(role, str):
            roles.add(role)
        if isinstance(entity_type, str) and isinstance(entity_id, str) and _entity_exists(
            connection,
            entity_type,
            entity_id,
        ):
            resolved_refs += 1

    target = proposal.get("problem", {}).get("target", {}) if isinstance(proposal.get("problem"), dict) else {}
    target_found = False
    if isinstance(target, dict):
        target_type = target.get("entity_type")
        target_id = target.get("entity_id")
        if isinstance(target_type, str) and isinstance(target_id, str):
            target_found = _entity_exists(connection, target_type, target_id)

    total_refs = len([ref for ref in refs if isinstance(ref, dict)])
    resolved_ratio = (resolved_refs / total_refs) if total_refs else 0.0
    has_failure_ref = "failure" in roles
    has_context_ref = bool({"context", "handoff", "supporting"} & roles)
    note = (
        f"{resolved_refs}/{total_refs} evidence refs resolve; "
        f"failure_ref={has_failure_ref}; target_found={target_found}."
    )
    return {
        "total_refs": total_refs,
        "resolved_refs": resolved_refs,
        "resolved_ratio": round(resolved_ratio, 3),
        "entity_types": sorted(ref_types),
        "roles": sorted(roles),
        "has_failure_ref": has_failure_ref,
        "has_context_ref": has_context_ref,
        "target_found": target_found,
        "note": note,
    }


def _verification_metrics(connection: sqlite3.Connection, proposal: dict[str, Any]) -> dict[str, Any]:
    proposal_id = str(proposal.get("id") or "")
    eval_specs = _rows(connection, "SELECT * FROM eval_specs WHERE proposal_id = ?", (proposal_id,))
    eval_runs = _rows(connection, "SELECT * FROM eval_runs WHERE proposal_id = ?", (proposal_id,))
    replay_runs = _rows(connection, "SELECT * FROM replay_runs WHERE proposal_id = ?", (proposal_id,))
    passed_eval_runs = [row for row in eval_runs if row.get("status") == "passed"]
    failed_eval_runs = [row for row in eval_runs if row.get("status") == "failed"]
    passed_replay_runs = [row for row in replay_runs if row.get("status") == "passed"]
    failed_replay_runs = [row for row in replay_runs if row.get("status") == "failed"]
    highest_trust_level = _highest_trust_level(eval_specs)
    verified_trust_level = _highest_verified_trust_level(eval_specs, passed_eval_runs)
    latest_eval_status = eval_runs[-1].get("status") if eval_runs else "not_run"
    latest_replay_status = replay_runs[-1].get("status") if replay_runs else "not_run"
    if passed_eval_runs or passed_replay_runs:
        note = (
            f"{len(passed_eval_runs)} passed eval run(s), "
            f"{len(passed_replay_runs)} passed replay run(s), verified trust {verified_trust_level or 'none'}."
        )
    elif failed_eval_runs or failed_replay_runs:
        note = (
            f"{len(failed_eval_runs)} failed eval run(s), "
            f"{len(failed_replay_runs)} failed replay run(s)."
        )
    else:
        note = "No eval or replay evidence has verified this proposal yet."
    return {
        "eval_specs": len(eval_specs),
        "eval_runs": len(eval_runs),
        "passed_eval_runs": len(passed_eval_runs),
        "failed_eval_runs": len(failed_eval_runs),
        "replay_runs": len(replay_runs),
        "passed_replay_runs": len(passed_replay_runs),
        "failed_replay_runs": len(failed_replay_runs),
        "highest_trust_level": highest_trust_level,
        "verified_trust_level": verified_trust_level,
        "latest_eval_status": latest_eval_status,
        "latest_replay_status": latest_replay_status,
        "note": note,
    }


def _duplicate_metrics(connection: sqlite3.Connection, proposal: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(proposal.get("profile_id") or "")
    proposal_id = str(proposal.get("id") or "")
    section = str(proposal.get("section") or "")
    key = _proposal_similarity_key(proposal)
    similar_active = 0
    similar_total = 0
    rows = _rows(
        connection,
        """
        SELECT id, state, section, title, problem_json
        FROM learning_proposals
        WHERE profile_id = ? AND id != ?
        """,
        (profile_id, proposal_id),
    )
    for row in rows:
        row_problem = _json_loads(row.pop("problem_json", "{}"), {})
        candidate = {**row, "problem": row_problem}
        if str(candidate.get("section") or "") != section:
            continue
        if _proposal_similarity_key(candidate) != key:
            continue
        similar_total += 1
        if str(candidate.get("state") or "") in ACTIVE_STATES:
            similar_active += 1
    return {
        "similarity_key": key,
        "similar_proposals": similar_total,
        "similar_active_proposals": similar_active,
    }


def _evidence_contribution(metrics: dict[str, Any]) -> float:
    contribution = 0.0
    contribution += 0.16 * float(metrics["resolved_ratio"])
    if metrics["total_refs"] >= 2:
        contribution += 0.04
    if metrics["has_failure_ref"]:
        contribution += 0.05
    if metrics["has_context_ref"]:
        contribution += 0.03
    if metrics["target_found"]:
        contribution += 0.05
    if len(metrics["entity_types"]) >= 2:
        contribution += 0.02
    return round(min(0.35, contribution), 4)


def _verification_contribution(metrics: dict[str, Any]) -> float:
    contribution = 0.0
    if metrics["passed_eval_runs"]:
        contribution += 0.12
        if metrics["passed_eval_runs"] >= 2:
            contribution += 0.04
    if metrics["failed_eval_runs"]:
        contribution -= 0.18
    if metrics["passed_replay_runs"]:
        contribution += 0.08
    if metrics["failed_replay_runs"]:
        contribution -= 0.12
    trust = metrics.get("verified_trust_level")
    if trust == "L1_repeated":
        contribution += 0.04
    elif trust == "L2_regression":
        contribution += 0.07
    elif trust == "L3_human_approved":
        contribution += 0.10
    return round(max(-0.30, min(0.35, contribution)), 4)


def _highest_trust_level(eval_specs: list[dict[str, Any]]) -> Optional[str]:
    levels = [str(row.get("trust_level")) for row in eval_specs if isinstance(row.get("trust_level"), str)]
    return max(levels, key=lambda level: TRUST_ORDER.get(level, -1), default=None)


def _highest_verified_trust_level(
    eval_specs: list[dict[str, Any]],
    passed_eval_runs: list[dict[str, Any]],
) -> Optional[str]:
    if not passed_eval_runs:
        return None
    spec_by_id = {str(row.get("id")): row for row in eval_specs}
    levels = []
    for run in passed_eval_runs:
        spec = spec_by_id.get(str(run.get("eval_spec_id")))
        if spec is not None and isinstance(spec.get("trust_level"), str):
            levels.append(str(spec["trust_level"]))
    return max(levels, key=lambda level: TRUST_ORDER.get(level, -1), default=None)


def _entity_exists(connection: sqlite3.Connection, entity_type: str, entity_id: str) -> bool:
    table = ENTITY_TABLES.get(entity_type)
    if table is None:
        return False
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (entity_id,)).fetchone()
    return row is not None


def _proposal_similarity_key(proposal: dict[str, Any]) -> str:
    problem = proposal.get("problem")
    issue = problem.get("issue") if isinstance(problem, dict) else None
    return _normalize_text(issue if isinstance(issue, str) else str(proposal.get("title") or ""))


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _confidence_level(score: float) -> str:
    if score < 0.45:
        return "low"
    if score < 0.75:
        return "medium"
    return "high"


def _factor(name: str, contribution: float, note: str) -> dict[str, Any]:
    return {"name": name, "contribution": round(contribution, 4), "note": note}


def _rows(connection: sqlite3.Connection, query: str, args: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [_decode_row(row) for row in connection.execute(query, args).fetchall()]


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key, value in list(payload.items()):
        if key.endswith("_json") and isinstance(value, str):
            decoded_key = key[: -len("_json")]
            payload[decoded_key] = _json_loads(value, [] if value.startswith("[") else {})
            del payload[key]
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _clamp_float(value: Any, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))
