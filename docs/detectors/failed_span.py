"""Flag spans that ended in a failed/error status.

A bundled example `eval` detector. Per-trace contract: ``detect(trace_data,
trace_id)`` is called once per exported run trace and returns a flat list of
``{event_id, has_problem}`` dicts (one per span). Kyoko aggregates across all
traces to a prevalence. Evidence only.
"""

DETECTOR = {
    "id": "failed_span",
    "name": "Failed span",
    "problem_statement": "A span in the run ended in a failed or error status.",
    "direction": "true_is_notable",
    "unit_type": "event",
    "output_type": "boolean",
    "version": 1,
}

_FAILED_STATUSES = {"failed", "error", "errored", "timeout", "cancelled", "canceled"}


def detect(trace_data, trace_id):
    events = []
    for span in trace_data.get("spans", []):
        status = str(span.get("status", "")).lower()
        events.append(
            {
                "event_id": span.get("id", ""),
                "has_problem": status in _FAILED_STATUSES,
            }
        )
    return events
