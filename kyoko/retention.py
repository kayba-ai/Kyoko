from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .storage import (
    StorageError,
    connect,
    initialize_database,
)


class RetentionError(Exception):
    """Raised when retention pruning cannot be completed."""


@dataclass(frozen=True)
class RetentionPruneReport:
    profile_id: str
    dry_run: bool
    cutoffs: dict[str, Optional[str]]
    pruned_rows: dict[str, list[str]]
    skipped_rows: list[dict[str, str]]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "dry_run": self.dry_run,
            "cutoffs": self.cutoffs,
            "pruned_rows": self.pruned_rows,
            "skipped_rows": self.skipped_rows,
            "summary": {
                "pruned_rows": sum(len(ids) for ids in self.pruned_rows.values()),
                "skipped_rows": len(self.skipped_rows),
            },
        }


def prune_retained_data(
    *,
    db_path: Path,
    profile_id: Optional[str] = None,
    trace_older_than_days: Optional[int] = None,
    replay_older_than_days: Optional[int] = None,
    operator_older_than_days: Optional[int] = None,
    dry_run: bool = True,
    now: Optional[datetime] = None,
) -> RetentionPruneReport:
    # SCOPE simplification: retention is a manual --older-than-days prune. There
    # is no per-profile policy; the explicit day params are the only inputs and
    # the default is dry-run (never auto-delete).
    current_time = now or datetime.now(timezone.utc)
    initialize_database(db_path)
    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise RetentionError("no_profiles_found")
        _ensure_profile_exists(connection, selected_profile_id)
    trace_days = _validate_retention_days("trace_older_than_days", trace_older_than_days)
    replay_days = _validate_retention_days("replay_older_than_days", replay_older_than_days)
    operator_days = _validate_retention_days("operator_older_than_days", operator_older_than_days)
    cutoffs = {
        "trace": _cutoff_for_days(trace_days, current_time),
        "replay": _cutoff_for_days(replay_days, current_time),
        "operator": _cutoff_for_days(operator_days, current_time),
    }

    with connect(db_path) as connection:
        candidates = _collect_candidates(
            connection,
            profile_id=selected_profile_id,
            trace_cutoff=cutoffs["trace"],
            replay_cutoff=cutoffs["replay"],
            operator_cutoff=cutoffs["operator"],
        )
        if not dry_run:
            _apply_prune(connection, candidates)

    return RetentionPruneReport(
        profile_id=selected_profile_id,
        dry_run=dry_run,
        cutoffs=cutoffs,
        pruned_rows={key: list(value) for key, value in candidates["pruned_rows"].items()},
        skipped_rows=list(candidates["skipped_rows"]),
    )


def _collect_candidates(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    trace_cutoff: Optional[str],
    replay_cutoff: Optional[str],
    operator_cutoff: Optional[str],
) -> dict[str, Any]:
    pruned_rows: dict[str, list[str]] = {
        "eval_runs": [],
        "replay_runs": [],
        "operator_runs": [],
        "runs": [],
        "spans": [],
        "handoffs": [],
        "task_attempts": [],
        "tasks": [],
        "timeline_events": [],
    }
    skipped_rows: list[dict[str, str]] = []

    if replay_cutoff is not None:
        replay_ids = _ids(
            connection,
            """
            SELECT id
            FROM replay_runs
            WHERE profile_id = ? AND created_at <= ?
            ORDER BY created_at, id
            """,
            (profile_id, replay_cutoff),
        )
        eval_ids = _ids(
            connection,
            """
            SELECT id
            FROM eval_runs
            WHERE profile_id = ? AND created_at <= ?
            ORDER BY created_at, id
            """,
            (profile_id, replay_cutoff),
        )
        if replay_ids:
            eval_ids.extend(
                _ids(
                    connection,
                    f"""
                    SELECT id
                    FROM eval_runs
                    WHERE replay_run_id IN ({_placeholders(replay_ids)})
                    ORDER BY created_at, id
                    """,
                    tuple(replay_ids),
                )
            )
        pruned_rows["replay_runs"] = _dedupe(replay_ids)
        pruned_rows["eval_runs"] = _dedupe(eval_ids)

    if operator_cutoff is not None:
        pruned_rows["operator_runs"] = _ids(
            connection,
            """
            SELECT id
            FROM operator_runs
            WHERE profile_id = ? AND created_at <= ?
            ORDER BY created_at, id
            """,
            (profile_id, operator_cutoff),
        )

    if trace_cutoff is not None:
        trace = _collect_trace_candidates(
            connection,
            profile_id=profile_id,
            trace_cutoff=trace_cutoff,
            replay_ids=set(pruned_rows["replay_runs"]),
        )
        for key, value in trace["pruned_rows"].items():
            pruned_rows[key] = value
        skipped_rows.extend(trace["skipped_rows"])

    timeline_ids = _timeline_ids_for_pruned_rows(connection, pruned_rows)
    pruned_rows["timeline_events"] = _dedupe(timeline_ids)
    return {"pruned_rows": pruned_rows, "skipped_rows": skipped_rows}


def _collect_trace_candidates(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    trace_cutoff: str,
    replay_ids: set[str],
) -> dict[str, Any]:
    run_rows = connection.execute(
        """
        SELECT id, task_attempt_id
        FROM runs
        WHERE profile_id = ?
          AND COALESCE(ended_at, started_at) <= ?
        ORDER BY started_at, id
        """,
        (profile_id, trace_cutoff),
    ).fetchall()
    candidate_run_ids = [str(row["id"]) for row in run_rows]
    pruned_rows = {
        "runs": [],
        "spans": [],
        "handoffs": [],
        "task_attempts": [],
        "tasks": [],
    }
    skipped_rows: list[dict[str, str]] = []
    if not candidate_run_ids:
        return {"pruned_rows": pruned_rows, "skipped_rows": skipped_rows}

    run_to_spans: dict[str, list[str]] = {run_id: [] for run_id in candidate_run_ids}
    run_to_attempt = {
        str(row["id"]): str(row["task_attempt_id"])
        for row in run_rows
        if row["task_attempt_id"] is not None
    }
    span_rows = connection.execute(
        f"""
        SELECT id, run_id
        FROM spans
        WHERE run_id IN ({_placeholders(candidate_run_ids)})
        ORDER BY started_at, id
        """,
        tuple(candidate_run_ids),
    ).fetchall()
    for row in span_rows:
        run_to_spans.setdefault(str(row["run_id"]), []).append(str(row["id"]))

    protected = _protected_trace_runs(
        connection,
        profile_id=profile_id,
        run_to_spans=run_to_spans,
        run_to_attempt=run_to_attempt,
        replay_ids=replay_ids,
    )
    for run_id, reason in protected.items():
        skipped_rows.append({"entity_type": "run", "entity_id": run_id, "reason": reason})

    run_ids = [run_id for run_id in candidate_run_ids if run_id not in protected]
    if not run_ids:
        return {"pruned_rows": pruned_rows, "skipped_rows": skipped_rows}

    span_ids = _ids(
        connection,
        f"SELECT id FROM spans WHERE run_id IN ({_placeholders(run_ids)}) ORDER BY started_at, id",
        tuple(run_ids),
    )
    handoff_ids = (
        _ids(
            connection,
            f"""
            SELECT id
            FROM handoffs
            WHERE run_id IN ({_placeholders(run_ids)})
               OR span_id IN ({_placeholders(span_ids)})
            ORDER BY created_at, id
            """,
            tuple(run_ids + span_ids),
        )
        if span_ids
        else _ids(
            connection,
            f"SELECT id FROM handoffs WHERE run_id IN ({_placeholders(run_ids)}) ORDER BY created_at, id",
            tuple(run_ids),
        )
    )
    attempt_ids = _ids(
        connection,
        f"""
        SELECT id
        FROM task_attempts
        WHERE run_id IN ({_placeholders(run_ids)})
        ORDER BY started_at, id
        """,
        tuple(run_ids),
    )
    task_ids = []
    if attempt_ids:
        task_rows = connection.execute(
            f"""
            SELECT task_id, COUNT(*) AS total_attempts,
                   SUM(CASE WHEN id IN ({_placeholders(attempt_ids)}) THEN 1 ELSE 0 END) AS pruned_attempts
            FROM task_attempts
            WHERE task_id IN (
              SELECT task_id FROM task_attempts WHERE id IN ({_placeholders(attempt_ids)})
            )
            GROUP BY task_id
            """,
            tuple(attempt_ids + attempt_ids),
        ).fetchall()
        task_ids = [
            str(row["task_id"])
            for row in task_rows
            if int(row["total_attempts"]) == int(row["pruned_attempts"])
        ]
    if task_ids:
        handoff_ids.extend(
            _ids(
                connection,
                f"""
                SELECT id
                FROM handoffs
                WHERE from_task_id IN ({_placeholders(task_ids)})
                   OR to_task_id IN ({_placeholders(task_ids)})
                ORDER BY created_at, id
                """,
                tuple(task_ids + task_ids),
            )
        )

    pruned_rows["runs"] = _dedupe(run_ids)
    pruned_rows["spans"] = _dedupe(span_ids)
    pruned_rows["handoffs"] = _dedupe(handoff_ids)
    pruned_rows["task_attempts"] = _dedupe(attempt_ids)
    pruned_rows["tasks"] = _dedupe(task_ids)
    return {"pruned_rows": pruned_rows, "skipped_rows": skipped_rows}


def _protected_trace_runs(
    connection: sqlite3.Connection,
    *,
    profile_id: str,
    run_to_spans: dict[str, list[str]],
    run_to_attempt: dict[str, str],
    replay_ids: set[str],
) -> dict[str, str]:
    protected: dict[str, str] = {}
    run_ids = set(run_to_spans)
    attempt_to_run = {attempt_id: run_id for run_id, attempt_id in run_to_attempt.items()}
    attempt_ids = set(attempt_to_run)
    span_to_run = {
        span_id: run_id
        for run_id, span_ids in run_to_spans.items()
        for span_id in span_ids
    }

    for row in connection.execute(
        f"""
        SELECT source_run_id
        FROM skills
        WHERE source_run_id IN ({_placeholders(run_ids)})
        """,
        tuple(run_ids),
    ).fetchall():
        protected[str(row["source_run_id"])] = "skill_source_run"

    replay_rows = []
    if run_ids:
        replay_rows.extend(
            connection.execute(
                f"""
                SELECT id, source_run_id, task_attempt_id
                FROM replay_runs
                WHERE source_run_id IN ({_placeholders(run_ids)})
                """,
                tuple(run_ids),
            ).fetchall()
        )
    if attempt_ids:
        replay_rows.extend(
            connection.execute(
                f"""
                SELECT id, source_run_id, task_attempt_id
                FROM replay_runs
                WHERE task_attempt_id IN ({_placeholders(attempt_ids)})
                """,
                tuple(attempt_ids),
            ).fetchall()
        )
    for row in replay_rows:
        replay_id = str(row["id"])
        if replay_id not in replay_ids:
            if row["source_run_id"] is not None:
                protected.setdefault(str(row["source_run_id"]), "active_replay_source_run")
            if row["task_attempt_id"] is not None:
                run_id = attempt_to_run.get(str(row["task_attempt_id"]))
                if run_id is not None:
                    protected.setdefault(run_id, "active_replay_task_attempt")

    references = connection.execute(
        """
        SELECT evidence_refs_json, problem_json, proposed_changes_json
        FROM learning_proposals
        WHERE profile_id = ?
        """,
        (profile_id,),
    ).fetchall()
    references.extend(
        connection.execute(
            """
            SELECT target_json AS evidence_refs_json, definition_json AS problem_json, '{}' AS proposed_changes_json
            FROM eval_specs
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchall()
    )
    references.extend(
        connection.execute(
            """
            SELECT occurrences_json AS evidence_refs_json, '{}' AS problem_json, '{}' AS proposed_changes_json
            FROM skills
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchall()
    )
    for row in references:
        text = " ".join(str(row[key] or "") for key in row.keys())
        for run_id in run_ids:
            if run_id in text:
                protected.setdefault(run_id, "referenced_by_learning_artifact")
        for span_id, run_id in span_to_run.items():
            if span_id in text:
                protected.setdefault(run_id, "referenced_by_learning_artifact")
    return protected


def _timeline_ids_for_pruned_rows(
    connection: sqlite3.Connection,
    pruned_rows: dict[str, list[str]],
) -> list[str]:
    refs = {
        "run": pruned_rows.get("runs", []),
        "span": pruned_rows.get("spans", []),
        "handoff": pruned_rows.get("handoffs", []),
        "task_attempt": pruned_rows.get("task_attempts", []),
        "task": pruned_rows.get("tasks", []),
        "replay_run": pruned_rows.get("replay_runs", []),
        "eval_run": pruned_rows.get("eval_runs", []),
        "operator_run": pruned_rows.get("operator_runs", []),
    }
    timeline_ids: list[str] = []
    for entity_type, entity_ids in refs.items():
        if not entity_ids:
            continue
        timeline_ids.extend(
            _ids(
                connection,
                f"""
                SELECT id
                FROM timeline_events
                WHERE entity_type = ? AND entity_id IN ({_placeholders(entity_ids)})
                ORDER BY at, id
                """,
                (entity_type, *entity_ids),
            )
        )
    return timeline_ids


def _apply_prune(connection: sqlite3.Connection, candidates: dict[str, Any]) -> None:
    rows: dict[str, list[str]] = candidates["pruned_rows"]
    _delete_timeline_events(connection, rows["timeline_events"])
    _delete_rows(connection, "eval_runs", rows["eval_runs"])
    _delete_rows(connection, "replay_runs", rows["replay_runs"])
    _delete_rows(connection, "operator_runs", rows["operator_runs"])

    if rows["runs"]:
        connection.execute(
            f"UPDATE runs SET task_attempt_id = NULL WHERE id IN ({_placeholders(rows['runs'])})",
            tuple(rows["runs"]),
        )
        connection.execute(
            f"UPDATE task_attempts SET run_id = NULL WHERE run_id IN ({_placeholders(rows['runs'])})",
            tuple(rows["runs"]),
        )
    if rows["spans"]:
        connection.execute(
            f"UPDATE spans SET parent_span_id = NULL WHERE id IN ({_placeholders(rows['spans'])})",
            tuple(rows["spans"]),
        )
    _delete_rows(connection, "handoffs", rows["handoffs"])
    _delete_rows(connection, "spans", rows["spans"])
    _delete_rows(connection, "runs", rows["runs"])
    _delete_rows(connection, "task_attempts", rows["task_attempts"])
    _delete_rows(connection, "tasks", rows["tasks"])


def _delete_timeline_events(connection: sqlite3.Connection, ids: list[str]) -> None:
    _delete_rows(connection, "timeline_events", ids)


def _delete_rows(connection: sqlite3.Connection, table: str, ids: list[str]) -> None:
    if not ids:
        return
    connection.execute(
        f"DELETE FROM {table} WHERE id IN ({_placeholders(ids)})",
        tuple(ids),
    )


def _validate_retention_days(name: str, value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetentionError(f"{name}_must_be_non_negative_integer_or_null")
    if value < 0:
        raise RetentionError(f"{name}_must_be_non_negative_integer_or_null")
    return value


def _cutoff_for_days(days: Optional[int], now: datetime) -> Optional[str]:
    if days is None:
        return None
    cutoff = now - timedelta(days=days)
    return _format_utc(cutoff)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _ensure_profile_exists(connection: sqlite3.Connection, profile_id: str) -> None:
    row = connection.execute("SELECT 1 FROM profiles WHERE id = ? LIMIT 1", (profile_id,)).fetchone()
    if row is None:
        raise RetentionError(f"profile_not_found:{profile_id}")


def _ids(connection: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[str]:
    return [str(row["id"]) for row in connection.execute(query, params).fetchall()]


def _placeholders(values: Any) -> str:
    count = len(values)
    if count == 0:
        raise StorageError("empty_placeholder_values")
    return ",".join("?" for _ in range(count))


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
