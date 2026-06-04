"""Guard evaluators — closing the loop (job step 08).

When an Issue is fixed and applied, Kyoko mints a **standing deterministic detector**
bound to that issue and advances it to ``guarded``. The guard runs over future traces;
if the failure recurs it raises a fresh Issue (via the existing measurement → issue
path), which re-enters the spine. A resolved issue is not truly closed until it owns a
guard.

Deterministic by strong preference: the guard is generated as Python (a ``detect``
detector that flags recurrence of the failure signature in the same operations). An
LLM-judge guard is a deliberate last resort, only when the failure genuinely cannot be
expressed as code (``prefer_llm=True``) — see :mod:`kyoko.llm_evals`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .eval_detectors import DetectorError, register_detector_source
from .issues import IssueError, get_issue, set_issue_evaluator
from .storage import connect, initialize_database

# Statuses that mean a span did not succeed. Mirrors the bundled ``failed_span`` detector.
_FAILED_STATUSES = ("failed", "error", "errored", "timeout", "cancelled", "canceled")


class GuardError(Exception):
    """Raised when a guard evaluator cannot be generated or bound."""


@dataclass(frozen=True)
class GuardReport:
    issue_id: str
    evaluator_id: str
    evaluator_kind: str  # "python" (deterministic) | "llm" (fallback)
    deterministic: bool
    affected_span_names: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "evaluator_id": self.evaluator_id,
            "evaluator_kind": self.evaluator_kind,
            "deterministic": self.deterministic,
            "affected_span_names": list(self.affected_span_names),
        }


def _affected_span_names(connection: Any, span_ids: list[str]) -> list[str]:
    if not span_ids:
        return []
    placeholders = ",".join("?" for _ in span_ids)
    rows = connection.execute(
        f"SELECT DISTINCT name FROM spans WHERE id IN ({placeholders})",
        tuple(span_ids),
    ).fetchall()
    return sorted({str(row[0]) for row in rows if row[0]})


def generate_guard_detector_source(
    *, issue_id: str, title: Optional[str], span_names: list[str]
) -> str:
    """Codegen a deterministic ``detect`` detector that flags recurrence of the resolved
    failure. It re-flags spans that fail in the originally-affected operations (scoped by
    span name); with no known names it degrades to a generic failed-span guard."""

    detector_id = f"guard_{issue_id}"
    display_title = (title or "agent failure").strip() or "agent failure"
    names_literal = json.dumps(sorted(span_names))
    failed_literal = json.dumps(list(_FAILED_STATUSES))
    id_literal = json.dumps(detector_id)
    name_literal = json.dumps(("Guard: " + display_title)[:120])
    problem_literal = json.dumps(
        ("Recurrence of resolved issue: " + display_title)[:240]
    )
    return f'''"""Auto-generated deterministic guard for {detector_id}.

Watches future traces for recurrence of a resolved failure. Per-trace contract:
``detect(trace_data, trace_id)`` returns ``[{{"event_id", "has_problem"}}]`` per span.
Evidence only — flagging a recurrence raises a fresh Issue, it never changes behavior.
"""

DETECTOR = {{
    "id": {id_literal},
    "name": {name_literal},
    "problem_statement": {problem_literal},
    "direction": "true_is_notable",
    "unit_type": "event",
    "output_type": "boolean",
    "version": 1,
}}

_FAILED_STATUSES = set({failed_literal})
# The operations this issue originally affected. Empty => generic failed-span guard.
_AFFECTED_SPAN_NAMES = set({names_literal})


def detect(trace_data, trace_id):
    events = []
    for span in trace_data.get("spans", []):
        name = str(span.get("name", ""))
        status = str(span.get("status", "")).lower()
        failed = status in _FAILED_STATUSES
        scoped = (not _AFFECTED_SPAN_NAMES) or (name in _AFFECTED_SPAN_NAMES)
        events.append({{
            "event_id": span.get("id", ""),
            "has_problem": bool(failed and scoped),
        }})
    return events
'''


def mint_guard_for_issue(
    *,
    db_path: Path,
    issue_id: str,
    profile_id: Optional[str] = None,
) -> GuardReport:
    """Generate + register a deterministic guard detector for ``issue_id``, bind it to the
    issue, and advance the issue to ``guarded``. Idempotent: re-minting upserts the same
    ``guard_<issue_id>`` definition."""

    initialize_database(db_path)
    issue = get_issue(db_path=db_path, issue_id=issue_id)
    with connect(db_path) as connection:
        span_names = _affected_span_names(
            connection, list(issue.get("affected_span_ids") or [])
        )

    code = generate_guard_detector_source(
        issue_id=issue_id, title=issue.get("title"), span_names=span_names
    )
    try:
        definition = register_detector_source(
            db_path=db_path,
            code=code,
            source="guard",
            default_id=f"guard_{issue_id}",
            issue_id=issue_id,
            profile_id=profile_id or issue.get("profile_id"),
        )
    except DetectorError as exc:
        raise GuardError(f"guard_generation_failed:{exc}") from exc

    try:
        set_issue_evaluator(
            db_path=db_path, issue_id=issue_id, evaluator_id=str(definition["id"])
        )
    except IssueError as exc:
        raise GuardError(str(exc)) from exc

    return GuardReport(
        issue_id=issue_id,
        evaluator_id=str(definition["id"]),
        evaluator_kind="python",
        deterministic=True,
        affected_span_names=tuple(span_names),
    )
