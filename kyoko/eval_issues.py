"""Turn a measurement aggregate into a first-class Issue (evidence only).

Both planes funnel here when ``--raise-issues`` is set. A measurement score is
**evidence**: it can raise an :mod:`kyoko.issues` Issue (which the existing
improve/proposal flow may pick up), but it never writes a ``check_run`` or
satisfies the autonomy gate. Issue-raising is opt-in and threshold-gated
(manual ``--threshold`` in v1 — no baked-in per-metric defaults yet).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .evals_measure import _LOWER_IS_BETTER
from .issues import create_issue

DEFAULT_SEVERITY_BANDS = {"low": 0.2, "medium": 0.5, "high": 0.8}


def problem_value(value: float, direction: str) -> float:
    """Map an aggregate value to a 0-1 "badness" score, oriented by direction.

    For lower-is-better metrics (incl. boolean prevalence + detectors) the value
    *is* the problem level; for higher-is-better it is ``1 - value``.
    """
    value = max(0.0, min(1.0, float(value)))
    return value if direction in _LOWER_IS_BETTER else 1.0 - value


def severity_band(problem: float, severity_bands: Optional[dict[str, float]]) -> Optional[str]:
    bands = severity_bands or DEFAULT_SEVERITY_BANDS
    if problem >= bands.get("high", 0.8):
        return "high"
    if problem >= bands.get("medium", 0.5):
        return "medium"
    if problem >= bands.get("low", 0.2):
        return "low"
    return None


def raise_issue_for_run(
    *,
    db_path: Path,
    definition: dict[str, Any],
    eval_run_id: str,
    aggregate: dict[str, Any],
    worst_unit_refs: list[str],
    threshold: float,
    profile_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Create an Issue when the (direction-oriented) problem level >= threshold.

    Returns the created issue, or ``None`` when below threshold. The Issue carries
    the metric run + worst-scoring units as evidence; severity comes from the
    definition's severity bands.
    """
    value = float((aggregate or {}).get("value") or 0.0)
    problem = problem_value(value, definition["direction"])
    if problem < threshold:
        return None
    severity = severity_band(problem, definition.get("severity_bands")) or "low"
    unit_type = definition.get("unit_type")
    evidence_refs: list[dict[str, str]] = [{"entity_type": "eval_run", "entity_id": eval_run_id}]
    span_like = unit_type in ("event", "llm_span")
    for ref in worst_unit_refs:
        evidence_refs.append(
            {"entity_type": "span" if span_like else "run", "entity_id": ref}
        )
    issue = create_issue(
        db_path=db_path,
        title=f"{definition['name']}: problem level {problem:.2f} ({definition['kind']} eval)",
        body=(
            f"Measurement {definition['id']} ({definition['kind']}) scored "
            f"value={value:.3f} over run {eval_run_id}; direction-oriented problem "
            f"level {problem:.2f} >= threshold {threshold:.2f}."
        ),
        category="measurement",
        severity=severity,
        status="open",
        evidence_refs=evidence_refs,
        affected_span_ids=list(worst_unit_refs) if span_like else None,
        profile_id=profile_id,
    )
    return issue
