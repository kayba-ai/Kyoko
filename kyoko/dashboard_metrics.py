from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .storage import connect, initialize_database


class DashboardMetricsError(Exception):
    """Raised when dashboard metrics cannot be assembled."""


def get_dashboard_metrics(*, db_path: Path, profile_id: Optional[str] = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        selected_profile = _selected_profile(connection, profile_id)
        if selected_profile is None:
            return _empty_metrics()
        selected_profile_id = str(selected_profile["id"])
        if profile_id is not None and selected_profile_id != profile_id:
            raise DashboardMetricsError(f"profile_not_found:{profile_id}")

        runs = {
            "total": _count(connection, "runs", selected_profile_id),
            "failed": _count_where(
                connection,
                "runs",
                selected_profile_id,
                "status IN ('failed', 'timed_out', 'errored')",
            ),
            "failed_spans": _failed_spans(connection, selected_profile_id),
            "latest": _latest_run(connection, selected_profile_id),
            "latest_failed": _latest_failed_run(connection, selected_profile_id),
        }
        issues = _issue_metrics(connection, selected_profile_id)
        checks = _check_metrics(connection, selected_profile_id)
        replay = _replay_metrics(connection, selected_profile_id)
        evals = _eval_metrics(connection, selected_profile_id)
        autonomy = _autonomy_metrics(connection, selected_profile_id)
        before_after = {
            "latest_failed_run_id": runs["latest_failed"]["id"] if runs["latest_failed"] else None,
            "latest_passed_replay_run_id": replay["latest_passed"]["id"] if replay["latest_passed"] else None,
            "latest_replay_output_run_id": replay["latest_passed"]["output_ref"] if replay["latest_passed"] else None,
            "verified_replay_improvement": bool(
                replay["latest_passed"] and replay["latest_passed"].get("output_ref")
            ),
        }

    cards = [
        {
            "id": "issues",
            "label": "Issues",
            "value": issues["total"],
            "detail": f"{issues['by_section'].get('context', 0)} context, {issues['by_section'].get('harness', 0)} harness",
        },
        {
            "id": "proposal_status",
            "label": "Proposal Status",
            "value": issues["active"],
            "detail": _status_detail(issues["by_state"]),
        },
        {
            "id": "checks",
            "label": "Check Pass/Fail",
            "value": f"{checks['passed']}/{checks['failed']}",
            "detail": f"{checks['specs']} specs, latest {checks['latest_status']}",
        },
        {
            "id": "replay",
            "label": "Replay Result",
            "value": f"{replay['passed']}/{replay['failed']}",
            "detail": f"{replay['total']} runs, latest {replay['latest_status']}",
        },
        {
            "id": "autonomy",
            "label": "Autonomy Actions",
            "value": autonomy["decisions"],
            "detail": _status_detail(autonomy["by_action"]) or "no actions yet",
        },
        {
            "id": "before_after",
            "label": "Before/After",
            "value": "verified" if before_after["verified_replay_improvement"] else "pending",
            "detail": _before_after_detail(before_after),
        },
    ]

    return {
        "profile_id": selected_profile_id,
        "profile_name": selected_profile["name"],
        "scope": "profile",
        "cards": cards,
        "runs": runs,
        "issues": issues,
        "checks": checks,
        "replay": replay,
        "evals": evals,
        "autonomy": autonomy,
        "before_after": before_after,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "profile_id": None,
        "profile_name": None,
        "scope": "empty",
        "cards": [],
        "runs": {"total": 0, "failed": 0, "failed_spans": 0, "latest": None, "latest_failed": None},
        "issues": {"total": 0, "active": 0, "by_state": {}, "by_section": {}},
        "checks": {"specs": 0, "runs": 0, "passed": 0, "failed": 0, "latest_status": "none"},
        "evals": {
            "definitions": 0,
            "measure_runs": 0,
            "scored_results": 0,
            "notable_results": 0,
            "evaluated_runs": 0,
            "failed_runs": 0,
            "failure_rate": None,
        },
        "replay": {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "latest_status": "none",
            "latest_passed": None,
        },
        "autonomy": {"events": 0, "decisions": 0, "by_action": {}},
        "before_after": {
            "latest_failed_run_id": None,
            "latest_passed_replay_run_id": None,
            "latest_replay_output_run_id": None,
            "verified_replay_improvement": False,
        },
    }


def _selected_profile(connection: Any, profile_id: Optional[str]) -> Optional[dict[str, Any]]:
    if profile_id is not None:
        row = connection.execute(
            "SELECT id, name FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if row is None:
            raise DashboardMetricsError(f"profile_not_found:{profile_id}")
    else:
        row = connection.execute("SELECT id, name FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return dict(row) if row is not None else None


def _count(connection: Any, table: str, profile_id: str) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    return int(row["count"])


def _count_where(connection: Any, table: str, profile_id: str, where_sql: str) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE profile_id = ? AND {where_sql}",
        (profile_id,),
    ).fetchone()
    return int(row["count"])


def _failed_spans(connection: Any, profile_id: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM spans
        JOIN runs ON runs.id = spans.run_id
        WHERE runs.profile_id = ?
          AND spans.status IN ('failed', 'timed_out', 'errored')
        """,
        (profile_id,),
    ).fetchone()
    return int(row["count"])


def _latest_run(connection: Any, profile_id: str) -> Optional[dict[str, Any]]:
    row = connection.execute(
        """
        SELECT id, status, started_at, ended_at, summary
        FROM runs
        WHERE profile_id = ?
        ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _latest_failed_run(connection: Any, profile_id: str) -> Optional[dict[str, Any]]:
    row = connection.execute(
        """
        SELECT id, status, started_at, ended_at, summary
        FROM runs
        WHERE profile_id = ?
          AND status IN ('failed', 'timed_out', 'errored')
        ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _issue_metrics(connection: Any, profile_id: str) -> dict[str, Any]:
    by_state = _group_counts(connection, "learning_proposals", profile_id, "state")
    by_section = _group_counts(connection, "learning_proposals", profile_id, "section")
    total = sum(by_state.values())
    active = sum(
        count
        for state, count in by_state.items()
        if state not in {"applied", "rolled_back", "failed"}
    )
    return {
        "total": total,
        "active": active,
        "by_state": by_state,
        "by_section": by_section,
    }


def _eval_metrics(connection: Any, profile_id: str) -> dict[str, Any]:
    """Eval-driven run outcomes. A run's success/failure is dictated by the
    measurement plane (judges/detectors), NOT by any status flag on the trace —
    traces carry no verdict. The run failure rate is the fraction of evaluated
    run-level units that tripped at least one eval's notable polarity.
    """

    rows = connection.execute(
        """
        SELECT r.unit_ref AS unit_ref, d.direction AS direction,
               r.score_bool AS score_bool, r.score_numeric AS score_numeric,
               d.severity_bands_json AS bands
        FROM eval_measure_results r
        JOIN eval_measure_runs mr ON mr.id = r.eval_run_id
        JOIN eval_definitions d ON d.id = mr.eval_definition_id
        WHERE r.profile_id = ?
          AND r.unit_type = 'run'
          AND r.status = 'scored'
        """,
        (profile_id,),
    ).fetchall()

    evaluated: set[str] = set()
    failed: set[str] = set()
    notable_results = 0
    for row in rows:
        unit_ref = str(row["unit_ref"])
        evaluated.add(unit_ref)
        if _is_notable(
            str(row["direction"] or ""),
            None if row["score_bool"] is None else bool(row["score_bool"]),
            row["score_numeric"],
            _json_loads(row["bands"], None),
        ):
            failed.add(unit_ref)
            notable_results += 1

    evaluated_runs = len(evaluated)
    failed_runs = len(failed)
    return {
        "definitions": _count(connection, "eval_definitions", profile_id),
        "measure_runs": _count(connection, "eval_measure_runs", profile_id),
        "scored_results": len(rows),
        "notable_results": notable_results,
        "evaluated_runs": evaluated_runs,
        "failed_runs": failed_runs,
        "failure_rate": (failed_runs / evaluated_runs) if evaluated_runs else None,
    }


def _is_notable(
    direction: str,
    score_bool: Optional[bool],
    score_numeric: Any,
    bands: Optional[dict[str, Any]],
) -> bool:
    """Whether a single measure result counts as a failure, given its definition's
    direction. Booleans use their notable polarity; numerics map to a direction-
    oriented problem level and trip at the definition's (or default) low band."""

    if score_bool is not None:
        if direction == "true_is_notable":
            return score_bool
        if direction == "false_is_notable":
            return not score_bool
        if direction == "lower_is_better":
            return score_bool
        if direction == "higher_is_better":
            return not score_bool
        return False
    if isinstance(score_numeric, (int, float)):
        value = float(score_numeric)
        if direction == "higher_is_better":
            problem = 1.0 - value
        else:
            problem = value
        threshold = bands.get("low", 0.2) if isinstance(bands, dict) else 0.2
        try:
            return problem >= float(threshold)
        except (TypeError, ValueError):
            return problem >= 0.2
    return False


def _check_metrics(connection: Any, profile_id: str) -> dict[str, Any]:
    by_status = _group_counts(connection, "check_runs", profile_id, "status")
    latest = _latest_status(connection, "check_runs", profile_id)
    return {
        "specs": _count(connection, "check_specs", profile_id),
        "runs": sum(by_status.values()),
        "passed": by_status.get("passed", 0),
        "failed": by_status.get("failed", 0),
        "by_status": by_status,
        "latest_status": latest or "none",
    }


def _replay_metrics(connection: Any, profile_id: str) -> dict[str, Any]:
    by_status = _group_counts(connection, "replay_runs", profile_id, "status")
    latest = _latest_status(connection, "replay_runs", profile_id)
    latest_passed = connection.execute(
        """
        SELECT id, status, output_ref, source_run_id, check_spec_id, proposal_id, side_effect_mode
        FROM replay_runs
        WHERE profile_id = ? AND status = 'passed'
        ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    return {
        "total": sum(by_status.values()),
        "passed": by_status.get("passed", 0),
        "failed": by_status.get("failed", 0),
        "by_status": by_status,
        "latest_status": latest or "none",
        "latest_passed": dict(latest_passed) if latest_passed is not None else None,
    }


def _autonomy_metrics(connection: Any, profile_id: str) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT kind, metadata_json
        FROM timeline_events
        WHERE profile_id = ?
          AND kind LIKE 'autonomy_%'
        ORDER BY at, id
        """,
        (profile_id,),
    ).fetchall()
    decision_rows = [row for row in rows if row["kind"] == "autonomy_decision"]
    action_rows = decision_rows if decision_rows else rows
    by_action: dict[str, int] = {}
    for row in action_rows:
        metadata = _json_loads(row["metadata_json"], {})
        action = metadata.get("action") if isinstance(metadata, dict) else None
        if not isinstance(action, str) or not action:
            action = _action_from_kind(str(row["kind"]))
        by_action[action] = by_action.get(action, 0) + 1
    return {
        "events": len(rows),
        "decisions": len(decision_rows),
        "by_action": by_action,
    }


def _group_counts(connection: Any, table: str, profile_id: str, column: str) -> dict[str, int]:
    rows = connection.execute(
        f"""
        SELECT {column} AS value, COUNT(*) AS count
        FROM {table}
        WHERE profile_id = ?
        GROUP BY {column}
        ORDER BY {column}
        """,
        (profile_id,),
    ).fetchall()
    return {str(row["value"]): int(row["count"]) for row in rows}


def _latest_status(connection: Any, table: str, profile_id: str) -> Optional[str]:
    row = connection.execute(
        f"""
        SELECT status
        FROM {table}
        WHERE profile_id = ?
        ORDER BY COALESCE(ended_at, started_at, created_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    return str(row["status"]) if row is not None else None


def _action_from_kind(kind: str) -> str:
    if kind == "autonomy_gated":
        return "gated"
    if kind == "autonomy_applied":
        return "applied"
    if kind == "autonomy_harness_prepared":
        return "prepared"
    if kind == "autonomy_regression_rolled_back":
        return "rolled_back"
    if kind.startswith("autonomy_regression"):
        return "failed"
    return kind.removeprefix("autonomy_") or "unknown"


def _status_detail(values: dict[str, int]) -> str:
    return ", ".join(f"{key} {value}" for key, value in sorted(values.items()))


def _before_after_detail(before_after: dict[str, Any]) -> str:
    failed = before_after.get("latest_failed_run_id") or "no failed run"
    replay = before_after.get("latest_passed_replay_run_id") or "no passed replay"
    return f"{failed} -> {replay}"


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
