from __future__ import annotations

"""Infer multi-agent / sub-agent groupings from the shape of a span tree.

When a source (such as OTLP/GenAI) does not emit explicit handoffs, the
structure of the span tree still carries enough signal to recover sub-agent
boundaries. This module mirrors the detection in Raindrop Workshop's
``src/agents.ts`` (the ``detectSubAgents`` routine), adapted to Kyoko's
lowercase ``kind`` strings and ``gen_ai.*`` attribute conventions.

Everything here is a pure function over decoded span dicts: no DB, no IO.
Each input span is treated defensively (any field may be missing). A span
``S`` is reported as a sub-agent root when any of the following hold:

* ``S`` is agent-like (``kind`` contains ``"agent"``, or attribute
  ``gen_ai.operation.name == "invoke_agent"``, or ``gen_ai.agent.name`` is
  present) -> trigger ``"agent_span"``.
* ``S`` has a direct child whose ``name`` contains ``"agent.subagent"``
  (the Claude Agent SDK pattern) -> trigger ``"agent_subagent_child"``.
* ``S`` contains an agentic loop: a descendant LLM-like span that itself has
  a tool-like descendant -> trigger ``"agentic_loop"``.

Only the outermost roots are reported; a candidate root nested under another
detected root is suppressed.
"""

from typing import Any, Optional

# Detection precedence: a span matching more than one trigger reports the
# first one in this order.
_TRIGGER_ORDER = ("agent_span", "agent_subagent_child", "agentic_loop")

_LLM_OPERATIONS = frozenset({"chat", "generate_content"})


def _attr(span: dict, key: str) -> Any:
    """Return ``span['attributes'][key]`` defensively, else ``None``."""
    attrs = span.get("attributes")
    if isinstance(attrs, dict):
        return attrs.get(key)
    return None


def _operation(span: dict) -> str:
    value = _attr(span, "gen_ai.operation.name")
    return str(value).strip().lower() if value is not None else ""


def _kind(span: dict) -> str:
    value = span.get("kind")
    return str(value).strip().lower() if value is not None else ""


def _name(span: dict) -> str:
    value = span.get("name")
    return str(value) if value is not None else ""


def _is_llm(span: dict) -> bool:
    """A span is LLM-like by kind ``llm`` or a chat/generate operation."""
    if "llm" in _kind(span):
        return True
    return _operation(span) in _LLM_OPERATIONS


def _is_tool(span: dict) -> bool:
    """A span is tool-like by kind ``tool`` or an ``execute_tool`` operation."""
    if "tool" in _kind(span):
        return True
    return _operation(span) == "execute_tool"


def _is_agent(span: dict) -> bool:
    """A span is agent-like by kind ``agent``, ``invoke_agent``, or agent name."""
    if "agent" in _kind(span):
        return True
    if _operation(span) == "invoke_agent":
        return True
    return _attr(span, "gen_ai.agent.name") is not None


def _model(span: dict) -> Optional[str]:
    """First model identifier found on a span, else ``None``."""
    for key in ("gen_ai.request.model", "gen_ai.response.model", "model"):
        value = _attr(span, key)
        if value is None and key == "model":
            value = span.get("model")
        if value:
            return str(value)
    return None


def _children_map(spans: list[dict]) -> dict[str, list[dict]]:
    """Map each parent span id to its list of direct child spans."""
    children: dict[str, list[dict]] = {}
    for span in spans:
        parent = span.get("parent_span_id")
        if parent is None:
            continue
        children.setdefault(str(parent), []).append(span)
    return children


def _descendants(root_id: str, children_map: dict[str, list[dict]]) -> list[dict]:
    """Return all descendant spans of ``root_id`` (excluding the root itself).

    Cycle-safe: a span id is visited at most once.
    """
    out: list[dict] = []
    seen: set[str] = {root_id}
    stack = list(children_map.get(root_id, ()))
    while stack:
        child = stack.pop()
        child_id = child.get("id")
        if child_id is None:
            continue
        child_id = str(child_id)
        if child_id in seen:
            continue
        seen.add(child_id)
        out.append(child)
        stack.extend(children_map.get(child_id, ()))
    return out


def _has_agentic_loop(root_id: str, children_map: dict[str, list[dict]]) -> bool:
    """True when a descendant LLM-like span has a tool-like descendant."""
    for desc in _descendants(root_id, children_map):
        if not _is_llm(desc):
            continue
        desc_id = desc.get("id")
        if desc_id is None:
            continue
        for grand in _descendants(str(desc_id), children_map):
            if _is_tool(grand):
                return True
    return False


def _trigger_for(
    span: dict, children_map: dict[str, list[dict]]
) -> Optional[str]:
    """Return the detection trigger for ``span``, or ``None`` if not a root."""
    span_id = span.get("id")
    if span_id is None:
        return None
    span_id = str(span_id)

    if _is_agent(span):
        return "agent_span"

    for child in children_map.get(span_id, ()):
        if "agent.subagent" in _name(child):
            return "agent_subagent_child"

    if _has_agentic_loop(span_id, children_map):
        return "agentic_loop"

    return None


def _min_str(current: Optional[str], candidate: Any) -> Optional[str]:
    if candidate is None:
        return current
    candidate = str(candidate)
    if current is None or candidate < current:
        return candidate
    return current


def _max_str(current: Optional[str], candidate: Any) -> Optional[str]:
    if candidate is None:
        return current
    candidate = str(candidate)
    if current is None or candidate > current:
        return candidate
    return current


def detect_subagents(spans: list[dict]) -> list[dict]:
    """Infer sub-agent groupings from the shape of a span tree.

    Returns one dict per outermost sub-agent root, sorted by ``started_at``
    then ``root_span_id``. See module docstring for the detection rules.
    """
    if not spans:
        return []

    children_map = _children_map(spans)
    by_id: dict[str, dict] = {}
    for span in spans:
        span_id = span.get("id")
        if span_id is not None:
            by_id[str(span_id)] = span

    # Candidate roots in deterministic order.
    candidates: list[tuple[str, str]] = []
    for span in spans:
        trigger = _trigger_for(span, children_map)
        if trigger is None:
            continue
        span_id = str(span["id"])
        candidates.append((span_id, trigger))

    candidate_ids = {span_id for span_id, _ in candidates}

    results: list[dict] = []
    for root_id, trigger in candidates:
        # Skip nested roots: report only the outermost sub-agent.
        descendants = _descendants(root_id, children_map)
        if any(
            str(desc.get("id")) != root_id and str(desc.get("id")) in candidate_ids
            for desc in descendants
            if desc.get("id") is not None
        ):
            # This root is fine; nesting is handled by checking ancestors below.
            pass

        group = [by_id[root_id]] + [
            desc for desc in descendants if desc.get("id") is not None
        ]

        llm_count = sum(1 for s in group if _is_llm(s))
        tool_count = sum(1 for s in group if _is_tool(s))

        started_at: Optional[str] = None
        ended_at: Optional[str] = None
        model: Optional[str] = None
        span_ids: list[str] = []
        for s in group:
            sid = s.get("id")
            if sid is not None:
                span_ids.append(str(sid))
            started_at = _min_str(started_at, s.get("started_at"))
            ended_at = _max_str(ended_at, s.get("ended_at"))
            if model is None:
                model = _model(s)

        root_span = by_id[root_id]
        name = _attr(root_span, "gen_ai.agent.name")
        name = str(name) if name else _name(root_span)

        results.append(
            {
                "root_span_id": root_id,
                "name": name,
                "span_ids": span_ids,
                "llm_count": llm_count,
                "tool_count": tool_count,
                "started_at": started_at,
                "ended_at": ended_at,
                "model": model,
                "trigger": trigger,
            }
        )

    # Suppress roots that are descendants of another detected root.
    nested: set[str] = set()
    for root_id, _ in candidates:
        for desc in _descendants(root_id, children_map):
            desc_id = desc.get("id")
            if desc_id is None:
                continue
            desc_id = str(desc_id)
            if desc_id != root_id and desc_id in candidate_ids:
                nested.add(desc_id)

    results = [r for r in results if r["root_span_id"] not in nested]

    results.sort(key=lambda r: (r["started_at"] or "", r["root_span_id"]))
    return results
