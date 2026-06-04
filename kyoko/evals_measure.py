"""Shared model for the measurement plane (`eval` + `llm_eval`).

A **measurement** scores a trace corpus to surface the prevalence/severity of a
problem. Two flavors share this module:

- ``eval`` — a deterministic Python detector run over a corpus (kind ``python``).
- ``llm_eval`` — an LLM-as-judge template scoring a unit (kind ``llm``).

Both are **evidence only**: nothing here writes a ``check_run``, mutates a skill,
or edits a harness file. This module owns the three tables
(``eval_definitions`` / ``eval_measure_runs`` / ``eval_measure_results``), the
corpus selector, and the shared aggregate math. The plane-specific runners
(Phase 2 ``eval_runner`` and Phase 3 judge-command runner) live elsewhere and
call into here; they decide what counts as the numerator for their plane.

Design mirrors :mod:`kyoko.issues` / :mod:`kyoko.annotations`: single implicit
profile resolved when none is supplied, stdlib-only, IDs look like
``<prefix>_{uuid4().hex[:12]}``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .storage import connect, initialize_database, utc_now

KINDS = ("python", "llm")
UNIT_TYPES = ("event", "llm_span", "run")
OUTPUT_TYPES = ("numeric", "boolean")
DIRECTIONS = (
    "lower_is_better",
    "higher_is_better",
    "true_is_notable",
    "false_is_notable",
)
DEFINITION_STATUSES = ("active", "archived")
RUN_STATUSES = ("pending", "running", "complete", "failed")
RESULT_STATUSES = ("scored", "skipped", "error")
DEFAULT_CORPUS_LIMIT = 500

# Histogram buckets for numeric aggregates (§5).
_HISTOGRAM_BUCKETS = (
    ("0-0.2", 0.0, 0.2),
    ("0.2-0.5", 0.2, 0.5),
    ("0.5-0.8", 0.5, 0.8),
    ("0.8-1", 0.8, 1.0001),
)


class EvalMeasureError(Exception):
    """Raised for invalid measurement input or missing targets."""


# --------------------------------------------------------------------------
# profile + id helpers
# --------------------------------------------------------------------------
def _resolve_profile_id(connection: Any, profile_id: Optional[str]) -> str:
    if profile_id:
        row = connection.execute(
            "SELECT 1 FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise EvalMeasureError(f"profile_not_found:{profile_id}")
        return profile_id
    row = connection.execute("SELECT id FROM profiles ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise EvalMeasureError("no_profiles_found")
    return str(row[0])


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


# --------------------------------------------------------------------------
# corpus selector (§2)
# --------------------------------------------------------------------------
@dataclass
class CorpusResolution:
    """The unit list a measurement run iterates, plus cap accounting.

    ``unit_refs`` are run_ids (``run``/``event`` units) or span_ids
    (``llm_span`` units). ``total_matched`` is the count before the limit cap;
    ``dropped`` units over the cap are reported, never silently truncated.
    """

    unit_type: str
    unit_refs: list[str]
    requested_limit: int
    total_matched: int
    over_cap: bool
    dropped: int

    def to_json(self) -> dict[str, Any]:
        return {
            "unit_type": self.unit_type,
            "unit_refs": list(self.unit_refs),
            "requested_limit": self.requested_limit,
            "total_matched": self.total_matched,
            "over_cap": self.over_cap,
            "dropped": self.dropped,
        }


def _normalize_corpus(corpus: Optional[dict[str, Any]], default_unit: str) -> dict[str, Any]:
    corpus = dict(corpus or {})
    unit = corpus.get("unit", default_unit)
    if unit not in UNIT_TYPES:
        raise EvalMeasureError(f"invalid_unit:{unit}")
    limit = corpus.get("limit", DEFAULT_CORPUS_LIMIT)
    if not isinstance(limit, int) or limit <= 0:
        raise EvalMeasureError(f"invalid_limit:{limit!r}")
    run_ids = corpus.get("run_ids")
    if run_ids is not None and not isinstance(run_ids, list):
        raise EvalMeasureError("run_ids_must_be_list")
    corpus["unit"] = unit
    corpus["limit"] = limit
    return corpus


def resolve_corpus(
    *,
    db_path: Path,
    corpus: Optional[dict[str, Any]],
    profile_id: Optional[str] = None,
    default_unit: str = "run",
) -> CorpusResolution:
    """Resolve a corpus selector to a concrete, ordered unit list.

    ``run``/``event`` units resolve to run ids (a Python detector iterates runs
    and emits its own event units); ``llm_span`` units resolve to span ids
    filtered by ``span_filter.kind`` (default ``llm``). Ordering is stable
    (started_at, then id) so before/after compares line up.
    """
    initialize_database(db_path)
    spec = _normalize_corpus(corpus, default_unit)
    unit = spec["unit"]
    limit = spec["limit"]

    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)

        run_clauses = ["r.profile_id = ?"]
        params: list[Any] = [resolved_profile_id]
        source_id = spec.get("source_id")
        if isinstance(source_id, str) and source_id:
            run_clauses.append("r.source_id = ?")
            params.append(source_id)
        run_ids = spec.get("run_ids")
        if isinstance(run_ids, list) and run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            run_clauses.append(f"r.id IN ({placeholders})")
            params.extend(str(rid) for rid in run_ids)
        since = spec.get("since")
        if isinstance(since, str) and since:
            run_clauses.append("r.started_at >= ?")
            params.append(since)
        until = spec.get("until")
        if isinstance(until, str) and until:
            run_clauses.append("r.started_at < ?")
            params.append(until)
        where = " AND ".join(run_clauses)

        if unit in ("run", "event"):
            rows = connection.execute(
                f"SELECT r.id FROM runs r WHERE {where} ORDER BY r.started_at ASC, r.id ASC",
                params,
            ).fetchall()
            refs = [str(row[0]) for row in rows]
        else:  # llm_span
            span_filter = spec.get("span_filter") or {}
            span_kind = span_filter.get("kind", "llm") if isinstance(span_filter, dict) else "llm"
            span_params = list(params)
            span_clause = where
            if isinstance(span_kind, str) and span_kind:
                span_clause = f"{where} AND s.kind = ?"
                span_params.append(span_kind)
            rows = connection.execute(
                f"""
                SELECT s.id FROM spans s JOIN runs r ON s.run_id = r.id
                WHERE {span_clause}
                ORDER BY s.started_at ASC, s.id ASC
                """,
                span_params,
            ).fetchall()
            refs = [str(row[0]) for row in rows]

    total = len(refs)
    over_cap = total > limit
    capped = refs[:limit]
    return CorpusResolution(
        unit_type=unit,
        unit_refs=capped,
        requested_limit=limit,
        total_matched=total,
        over_cap=over_cap,
        dropped=max(0, total - limit),
    )


# --------------------------------------------------------------------------
# definitions
# --------------------------------------------------------------------------
def upsert_eval_definition(
    *,
    db_path: Path,
    kind: str,
    name: str,
    version: int,
    unit_type: str,
    output_type: str,
    direction: str,
    source: str,
    definition_id: Optional[str] = None,
    partner: Optional[str] = None,
    problem_statement: Optional[str] = None,
    detector_ref: Optional[str] = None,
    prompt: Optional[str] = None,
    vars: Optional[list[str]] = None,
    bindings: Optional[dict[str, str]] = None,
    output: Optional[dict[str, Any]] = None,
    severity_bands: Optional[dict[str, float]] = None,
    status: str = "active",
    profile_id: Optional[str] = None,
) -> dict[str, Any]:
    """Insert or update a measurement definition. Bundled assets upsert by id."""
    if kind not in KINDS:
        raise EvalMeasureError(f"invalid_kind:{kind}")
    if unit_type not in UNIT_TYPES:
        raise EvalMeasureError(f"invalid_unit_type:{unit_type}")
    if output_type not in OUTPUT_TYPES:
        raise EvalMeasureError(f"invalid_output_type:{output_type}")
    if direction not in DIRECTIONS:
        raise EvalMeasureError(f"invalid_direction:{direction}")
    if status not in DEFINITION_STATUSES:
        raise EvalMeasureError(f"invalid_status:{status}")

    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        did = definition_id or _new_id("evaldef")
        existing = connection.execute(
            "SELECT created_at FROM eval_definitions WHERE id = ?", (did,)
        ).fetchone()
        created_at = str(existing[0]) if existing else now
        connection.execute(
            """
            INSERT INTO eval_definitions (
              id, profile_id, kind, name, version, partner, source, unit_type,
              output_type, direction, problem_statement, detector_ref, prompt,
              vars_json, bindings_json, output_json, severity_bands_json, status,
              created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              kind=excluded.kind, name=excluded.name, version=excluded.version,
              partner=excluded.partner, source=excluded.source,
              unit_type=excluded.unit_type, output_type=excluded.output_type,
              direction=excluded.direction, problem_statement=excluded.problem_statement,
              detector_ref=excluded.detector_ref, prompt=excluded.prompt,
              vars_json=excluded.vars_json, bindings_json=excluded.bindings_json,
              output_json=excluded.output_json, severity_bands_json=excluded.severity_bands_json,
              updated_at=excluded.updated_at
            """,
            # NOTE: `status` is intentionally NOT updated on conflict. Bundled
            # templates are re-seeded on every list/get; clobbering status here
            # would silently re-activate a judge the user archived. Status is
            # changed only through set_eval_definition_status.
            (
                did,
                resolved_profile_id,
                kind,
                name,
                int(version),
                partner,
                source,
                unit_type,
                output_type,
                direction,
                problem_statement,
                detector_ref,
                prompt,
                json.dumps(list(vars)) if vars is not None else None,
                json.dumps(dict(bindings)) if bindings is not None else None,
                json.dumps(output) if output is not None else None,
                json.dumps(severity_bands) if severity_bands is not None else None,
                status,
                created_at,
                now,
            ),
        )
    return get_eval_definition(db_path=db_path, definition_id=did)


def set_eval_definition_status(
    *,
    db_path: Path,
    definition_id: str,
    status: str,
    profile_id: Optional[str] = None,
) -> dict[str, Any]:
    """Activate or archive a measurement definition. Evidence-only configuration:
    it never changes agent behavior or touches the autonomy gate."""
    if status not in DEFINITION_STATUSES:
        raise EvalMeasureError(f"invalid_status:{status}")
    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        cursor = connection.execute(
            "UPDATE eval_definitions SET status = ?, updated_at = ? "
            "WHERE id = ? AND profile_id = ?",
            (status, now, definition_id, resolved_profile_id),
        )
        if cursor.rowcount == 0:
            raise EvalMeasureError(f"definition_not_found:{definition_id}")
    return get_eval_definition(db_path=db_path, definition_id=definition_id)


def _definition_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "kind": row["kind"],
        "name": row["name"],
        "version": row["version"],
        "partner": row["partner"],
        "source": row["source"],
        "unit_type": row["unit_type"],
        "output_type": row["output_type"],
        "direction": row["direction"],
        "problem_statement": row["problem_statement"],
        "detector_ref": row["detector_ref"],
        "prompt": row["prompt"],
        "vars": _json_loads(row["vars_json"], None),
        "bindings": _json_loads(row["bindings_json"], None),
        "output": _json_loads(row["output_json"], None),
        "severity_bands": _json_loads(row["severity_bands_json"], None),
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_eval_definition(*, db_path: Path, definition_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM eval_definitions WHERE id = ?", (definition_id,)
        ).fetchone()
        if row is None:
            raise EvalMeasureError(f"definition_not_found:{definition_id}")
        return _definition_row_to_dict(row)


def list_eval_definitions(
    *,
    db_path: Path,
    kind: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        clauses = ["profile_id = ?"]
        params: list[Any] = [resolved_profile_id]
        if kind is not None:
            if kind not in KINDS:
                raise EvalMeasureError(f"invalid_kind:{kind}")
            clauses.append("kind = ?")
            params.append(kind)
        rows = connection.execute(
            f"SELECT * FROM eval_definitions WHERE {' AND '.join(clauses)} "
            "ORDER BY kind ASC, name ASC, id ASC",
            params,
        ).fetchall()
        return [_definition_row_to_dict(row) for row in rows]


# --------------------------------------------------------------------------
# measurement runs + results
# --------------------------------------------------------------------------
def create_measure_run(
    *,
    db_path: Path,
    definition: dict[str, Any],
    corpus: dict[str, Any],
    baseline_run_id: Optional[str] = None,
    status: str = "running",
    profile_id: Optional[str] = None,
) -> str:
    """Open a measurement run, snapshotting the definition used. Returns its id."""
    if status not in RUN_STATUSES:
        raise EvalMeasureError(f"invalid_status:{status}")
    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        run_id = _new_id("evalrun")
        started_at = now if status == "running" else None
        connection.execute(
            """
            INSERT INTO eval_measure_runs (
              id, profile_id, eval_definition_id, kind, definition_snapshot_json,
              corpus_json, unit_type, status, unit_total, unit_scored, unit_skipped,
              aggregate_json, baseline_run_id, started_at, ended_at, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                resolved_profile_id,
                definition["id"],
                definition["kind"],
                json.dumps(definition, sort_keys=True),
                json.dumps(corpus, sort_keys=True),
                definition["unit_type"],
                status,
                0,
                0,
                0,
                None,
                baseline_run_id,
                started_at,
                None,
                now,
                now,
            ),
        )
        return run_id


def record_measure_result(
    *,
    db_path: Path,
    eval_run_id: str,
    unit_type: str,
    unit_ref: str,
    status: str,
    detail: dict[str, Any],
    score_numeric: Optional[float] = None,
    score_bool: Optional[bool] = None,
    reasoning: Optional[str] = None,
    degraded: bool = False,
    profile_id: Optional[str] = None,
) -> str:
    """Append one per-unit result and bump the run's scored/skipped counters."""
    if status not in RESULT_STATUSES:
        raise EvalMeasureError(f"invalid_result_status:{status}")
    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        run_row = connection.execute(
            "SELECT profile_id FROM eval_measure_runs WHERE id = ?", (eval_run_id,)
        ).fetchone()
        if run_row is None:
            raise EvalMeasureError(f"measure_run_not_found:{eval_run_id}")
        resolved_profile_id = profile_id or str(run_row[0])
        result_id = _new_id("evalres")
        connection.execute(
            """
            INSERT INTO eval_measure_results (
              id, eval_run_id, profile_id, unit_type, unit_ref, status,
              score_numeric, score_bool, reasoning, degraded, detail_json, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                result_id,
                eval_run_id,
                resolved_profile_id,
                unit_type,
                unit_ref,
                status,
                score_numeric,
                None if score_bool is None else int(bool(score_bool)),
                reasoning,
                int(bool(degraded)),
                json.dumps(detail, sort_keys=True),
                now,
            ),
        )
        scored_inc = 1 if status == "scored" else 0
        skipped_inc = 1 if status == "skipped" else 0
        connection.execute(
            """
            UPDATE eval_measure_runs
            SET unit_total = unit_total + 1,
                unit_scored = unit_scored + ?,
                unit_skipped = unit_skipped + ?,
                updated_at = ?
            WHERE id = ?
            """,
            (scored_inc, skipped_inc, now, eval_run_id),
        )
        return result_id


def complete_measure_run(
    *,
    db_path: Path,
    eval_run_id: str,
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        cur = connection.execute(
            """
            UPDATE eval_measure_runs
            SET status = 'complete', aggregate_json = ?, ended_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(aggregate, sort_keys=True), now, now, eval_run_id),
        )
        if cur.rowcount == 0:
            raise EvalMeasureError(f"measure_run_not_found:{eval_run_id}")
    return get_measure_run(db_path=db_path, eval_run_id=eval_run_id)


def fail_measure_run(
    *,
    db_path: Path,
    eval_run_id: str,
    detail: dict[str, Any],
) -> dict[str, Any]:
    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        cur = connection.execute(
            """
            UPDATE eval_measure_runs
            SET status = 'failed', aggregate_json = ?, ended_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps({"error": detail}, sort_keys=True), now, now, eval_run_id),
        )
        if cur.rowcount == 0:
            raise EvalMeasureError(f"measure_run_not_found:{eval_run_id}")
    return get_measure_run(db_path=db_path, eval_run_id=eval_run_id)


def _run_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "eval_definition_id": row["eval_definition_id"],
        "kind": row["kind"],
        "definition_snapshot": _json_loads(row["definition_snapshot_json"], None),
        "corpus": _json_loads(row["corpus_json"], None),
        "unit_type": row["unit_type"],
        "status": row["status"],
        "unit_total": row["unit_total"],
        "unit_scored": row["unit_scored"],
        "unit_skipped": row["unit_skipped"],
        "aggregate": _json_loads(row["aggregate_json"], None),
        "baseline_run_id": row["baseline_run_id"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_measure_run(*, db_path: Path, eval_run_id: str) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT * FROM eval_measure_runs WHERE id = ?", (eval_run_id,)
        ).fetchone()
        if row is None:
            raise EvalMeasureError(f"measure_run_not_found:{eval_run_id}")
        return _run_row_to_dict(row)


def list_measure_runs(
    *,
    db_path: Path,
    kind: Optional[str] = None,
    eval_definition_id: Optional[str] = None,
    profile_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        resolved_profile_id = _resolve_profile_id(connection, profile_id)
        clauses = ["profile_id = ?"]
        params: list[Any] = [resolved_profile_id]
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if eval_definition_id is not None:
            clauses.append("eval_definition_id = ?")
            params.append(eval_definition_id)
        rows = connection.execute(
            f"SELECT * FROM eval_measure_runs WHERE {' AND '.join(clauses)} "
            "ORDER BY created_at DESC, id DESC",
            params,
        ).fetchall()
        return [_run_row_to_dict(row) for row in rows]


def get_measure_results(*, db_path: Path, eval_run_id: str) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT * FROM eval_measure_results WHERE eval_run_id = ? "
            "ORDER BY created_at ASC, rowid ASC",
            (eval_run_id,),
        ).fetchall()
        return [
            {
                "id": row["id"],
                "eval_run_id": row["eval_run_id"],
                "profile_id": row["profile_id"],
                "unit_type": row["unit_type"],
                "unit_ref": row["unit_ref"],
                "status": row["status"],
                "score_numeric": row["score_numeric"],
                "score_bool": None if row["score_bool"] is None else bool(row["score_bool"]),
                "reasoning": row["reasoning"],
                "degraded": bool(row["degraded"]),
                "detail": _json_loads(row["detail_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]


# --------------------------------------------------------------------------
# aggregate math (§5) — shared by both planes
# --------------------------------------------------------------------------
def aggregate_boolean(numerator: int, denominator: int) -> dict[str, Any]:
    """Prevalence aggregate: value = numerator / denominator (0.0 when empty).

    The caller decides the numerator's meaning per its plane (e.g. a Python
    detector follows the kayba-style ``num`` convention; a boolean judge counts
    the notable polarity). This just stores the shape from §5.
    """
    num = int(numerator)
    den = int(denominator)
    value = (num / den) if den else 0.0
    return {"type": "boolean", "numerator": num, "denominator": den, "value": value}


# Directions where a LOWER value is better (less problem). Numeric
# `higher_is_better` is the only "up is good" case; everything else — including
# boolean *_is_notable and python detectors, whose value is problem prevalence —
# improves as the value falls. Used to orient before/after compare + severity.
_LOWER_IS_BETTER = {"lower_is_better", "true_is_notable", "false_is_notable"}
_COMPARE_EPSILON = 0.02


def compare_eval_runs(
    *,
    db_path: Path,
    baseline_run_id: str,
    compare_run_id: str,
) -> dict[str, Any]:
    """Before/after delta between two completed runs of the same definition.

    ``direction`` is ``improved|regressed|unchanged`` (``|delta| < 0.02`` →
    unchanged), oriented by the definition's ``direction``.
    """
    baseline = get_measure_run(db_path=db_path, eval_run_id=baseline_run_id)
    compare = get_measure_run(db_path=db_path, eval_run_id=compare_run_id)
    if baseline["eval_definition_id"] != compare["eval_definition_id"]:
        raise EvalMeasureError(
            f"compare_definition_mismatch:{baseline['eval_definition_id']}!={compare['eval_definition_id']}"
        )
    for run in (baseline, compare):
        if run["status"] != "complete":
            raise EvalMeasureError(f"compare_requires_complete_run:{run['id']}:{run['status']}")
    base_value = float((baseline.get("aggregate") or {}).get("value") or 0.0)
    comp_value = float((compare.get("aggregate") or {}).get("value") or 0.0)
    delta = comp_value - base_value
    metric_direction = (baseline.get("definition_snapshot") or {}).get("direction", "higher_is_better")
    if abs(delta) < _COMPARE_EPSILON:
        verdict = "unchanged"
    elif metric_direction in _LOWER_IS_BETTER:
        verdict = "improved" if delta < 0 else "regressed"
    else:
        verdict = "improved" if delta > 0 else "regressed"
    return {
        "eval_id": baseline["eval_definition_id"],
        "kind": baseline["kind"],
        "baseline": baseline_run_id,
        "compare": compare_run_id,
        "baseline_value": base_value,
        "compare_value": comp_value,
        "delta": delta,
        "direction": verdict,
        "metric_direction": metric_direction,
    }


def aggregate_numeric(scores: list[float], *, skipped: int = 0) -> dict[str, Any]:
    """Mean + histogram aggregate over numeric judge scores (§5)."""
    valid = [float(s) for s in scores if s is not None]
    scored = len(valid)
    value = (sum(valid) / scored) if scored else 0.0
    histogram = {label: 0 for label, _, _ in _HISTOGRAM_BUCKETS}
    for s in valid:
        for label, lo, hi in _HISTOGRAM_BUCKETS:
            if lo <= s < hi:
                histogram[label] += 1
                break
    return {
        "type": "numeric",
        "value": value,
        "scored": scored,
        "skipped": int(skipped),
        "histogram": histogram,
    }
