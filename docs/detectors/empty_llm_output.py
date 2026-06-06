"""Flag LLM spans that produced an empty generation.

A bundled example `eval` detector. Per-trace contract: ``detect(trace_data,
trace_id)`` returns ``{event_id, has_problem}`` dicts for each LLM span, flagging
the ones whose normalized ``output_text`` is empty/whitespace. Evidence only.
"""

DETECTOR = {
    "id": "empty_llm_output",
    "name": "Empty LLM output",
    "problem_statement": "An LLM span produced an empty or whitespace-only generation.",
    "direction": "true_is_notable",
    "unit_type": "event",
    "output_type": "boolean",
    "version": 1,
}


def detect(trace_data, trace_id):
    events = []
    for span in trace_data.get("spans", []):
        normalized = span.get("normalized") or {}
        if normalized.get("kind") != "llm":
            continue
        output_text = normalized.get("output_text") or ""
        events.append(
            {
                "event_id": span.get("id", ""),
                "has_problem": not str(output_text).strip(),
            }
        )
    return events
