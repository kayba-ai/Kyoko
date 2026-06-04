from __future__ import annotations

import json
from typing import Any, Optional

# Single entry point for turning a captured span's raw attributes into a clean,
# SDK-agnostic view (llm | tool | other) so the dashboard / agent can read it
# without knowing each SDK's attribute layout. This mirrors Raindrop Workshop's
# span adapters (src/spans/adapters/*): a list of shape adapters is tried in a
# fixed order and the first match wins, with a no-match default of
# {"kind": "other"} so consumers always get *something* back.
#
# Adding a new SDK = add one private adapter function and one entry in the
# dispatch chain inside normalize_span().


def normalize_span(
    *,
    name: str,
    kind: Optional[str] = None,
    attributes: dict,
    input_payload: Any = None,
    output_payload: Any = None,
) -> dict:
    """Return a canonical view of a span.

    The result always carries a ``"kind"`` in {"llm", "tool", "other"} plus an
    ``"adapter"`` naming which shape matched. Adapters are tried in order and
    the first non-``None`` result wins; unknown shapes fall back to
    ``{"kind": "other", "adapter": "fallback"}``.
    """
    attrs = attributes if isinstance(attributes, dict) else {}
    ctx = _Context(
        name=name or "",
        kind=kind,
        attrs=attrs,
        input_payload=input_payload,
        output_payload=output_payload,
    )
    for adapter in (
        _ai_sdk_llm,
        _traceloop_llm,
        _claude_agent_sdk_llm,
        _ai_sdk_tool,
        _traceloop_tool,
        _gen_ai_llm,
        _gen_ai_tool,
    ):
        result = adapter(ctx)
        if result is not None:
            return result
    return {"kind": "other", "adapter": "fallback"}


class _Context:
    """The pre-coalesced inputs an adapter reads. Identical regardless of
    whether the span came from live ingest or a stored DB row."""

    __slots__ = ("name", "kind", "attrs", "input_payload", "output_payload")

    def __init__(
        self,
        *,
        name: str,
        kind: Optional[str],
        attrs: dict,
        input_payload: Any,
        output_payload: Any,
    ) -> None:
        self.name = name
        self.kind = kind
        self.attrs = attrs
        self.input_payload = input_payload
        self.output_payload = output_payload


# --- LLM adapters -----------------------------------------------------------


def _ai_sdk_llm(ctx: _Context) -> Optional[dict]:
    """Vercel AI SDK LLM spans.

    Signal: a JSON-encoded ``ai.prompt.messages`` (most common) or a
    JSON-encoded ``ai.prompt`` (older / Anthropic-shape calls). The JSON either
    decodes to a flat message array or to a ``{system, messages, prompt}``
    object. If ``ai.prompt`` is present but not valid JSON we return ``None`` so
    the claude-agent-sdk adapter (raw-string prompts) can claim it.
    """
    attrs = ctx.attrs
    parsed: Any = None
    found = False
    for key in ("ai.prompt.messages", "ai.prompt"):
        candidate = attrs.get(key)
        if not isinstance(candidate, str) or not candidate:
            if isinstance(candidate, (list, dict)):
                parsed = candidate
                found = True
                break
            continue
        decoded = _json_maybe(candidate)
        if not isinstance(decoded, str):  # successfully parsed JSON
            parsed = decoded
            found = True
            break
    if not found and attrs.get("ai.response.text") is None:
        return None
    if not found:
        return None

    messages: list = []
    system_parts: list = []

    if isinstance(parsed, list):
        for message in parsed:
            if not isinstance(message, dict):
                continue
            role = message.get("role") or "unknown"
            content = _extract_content(message.get("content"))
            if role == "system":
                if content:
                    system_parts.append(content)
            elif content or role == "tool":
                messages.append({"role": _role_or_unknown(role), "content": content})
    elif isinstance(parsed, dict):
        system_parts.append(_extract_content(parsed.get("system")))
        if isinstance(parsed.get("messages"), list):
            for message in parsed["messages"]:
                if not isinstance(message, dict):
                    continue
                role = message.get("role") or "unknown"
                content = _extract_content(message.get("content"))
                if content:
                    messages.append({"role": _role_or_unknown(role), "content": content})
        prompt = parsed.get("prompt")
        if isinstance(prompt, str) and prompt and not messages:
            messages.append({"role": "user", "content": prompt})
    else:
        return None

    system = "\n\n".join(part for part in system_parts if part) or None
    if not messages and system is None:
        return None

    model = _first_str(attrs, "ai.model.id", "gen_ai.request.model", "ai.response.model")
    output_text = _first_str(
        attrs,
        "ai.response.text",
        "ai.response.object",
        "gen_ai.completion.0.content",
    )
    return _llm_result(
        adapter="ai_sdk_llm",
        model=model,
        system=system,
        messages=messages or None,
        output_text=output_text,
        attrs=attrs,
    )


def _traceloop_llm(ctx: _Context) -> Optional[dict]:
    """Traceloop / OpenLLMetry LLM spans.

    Signal: indexed ``gen_ai.prompt.{i}.role`` / ``gen_ai.prompt.{i}.content``
    (and ``gen_ai.completion.{i}.content``), a ``traceloop.span.kind`` of
    ``"llm"``, or ``llm.request.type`` in {"chat", "completion"}.
    """
    attrs = ctx.attrs
    is_traceloop = attrs.get("traceloop.span.kind") == "llm"
    has_indexed = _has_prefixed(attrs, "gen_ai.prompt.") or _has_prefixed(attrs, "gen_ai.completion.")
    is_chat = attrs.get("llm.request.type") in ("chat", "completion")
    if not (is_traceloop or has_indexed or is_chat):
        return None

    messages: list = []
    system_parts: list = []
    for index in _indexed_numbers(attrs, "gen_ai.prompt."):
        role = attrs.get(f"gen_ai.prompt.{index}.role")
        if not isinstance(role, str):
            continue
        content = _extract_content(_json_maybe(attrs.get(f"gen_ai.prompt.{index}.content")))
        if role == "system":
            if content:
                system_parts.append(content)
        elif content or role == "tool":
            messages.append({"role": _role_or_unknown(role), "content": content})

    output_parts = []
    for index in _indexed_numbers(attrs, "gen_ai.completion."):
        content = _extract_content(_json_maybe(attrs.get(f"gen_ai.completion.{index}.content")))
        if content:
            output_parts.append(content)
    output_text = "\n\n".join(output_parts) or None

    system = "\n\n".join(part for part in system_parts if part) or None
    if not messages and system is None and output_text is None:
        return None

    model = _first_str(attrs, "gen_ai.response.model", "gen_ai.request.model", "llm.request.model")
    return _llm_result(
        adapter="traceloop_llm",
        model=model,
        system=system,
        messages=messages or None,
        output_text=output_text,
        attrs=attrs,
    )


def _claude_agent_sdk_llm(ctx: _Context) -> Optional[dict]:
    """``@raindrop-ai/claude-agent-sdk`` LLM spans.

    The Raindrop wrapper puts the whole user task into ``ai.prompt`` as a
    **raw string** (not JSON), with the system prompt on a sibling
    ``ai.prompt.system`` string. The AI SDK adapter runs first and only claims
    JSON ``ai.prompt`` values, so non-JSON prompts fall through to here. We may
    also match an Anthropic-ish ``gen_ai.system``.
    """
    attrs = ctx.attrs
    prompt = attrs.get("ai.prompt")
    system_raw = attrs.get("ai.prompt.system")
    gen_ai_system = attrs.get("gen_ai.system")

    if isinstance(prompt, str) and prompt:
        # Defer to the AI SDK adapter for JSON-shaped prompts.
        if not isinstance(_json_maybe(prompt), str):
            return None
        messages = [{"role": "user", "content": prompt}]
    elif isinstance(gen_ai_system, str) and gen_ai_system:
        messages = None
    else:
        return None

    system = system_raw if isinstance(system_raw, str) and system_raw else None
    if system is None and isinstance(gen_ai_system, str) and gen_ai_system:
        system = gen_ai_system

    model = _first_str(attrs, "ai.response.model", "ai.model.id", "gen_ai.request.model")
    output_text = _first_str(attrs, "ai.response.text", "ai.response.object")
    return _llm_result(
        adapter="claude_agent_sdk_llm",
        model=model,
        system=system,
        messages=messages,
        output_text=output_text,
        attrs=attrs,
    )


def _gen_ai_llm(ctx: _Context) -> Optional[dict]:
    """Generic GenAI semantic-convention LLM spans.

    Signal: ``gen_ai.operation.name`` in the chat-ish set, or a bare
    ``gen_ai.request.model``. Pulls model and token usage from the standard
    ``gen_ai.usage.*`` attributes.
    """
    attrs = ctx.attrs
    operation = str(attrs.get("gen_ai.operation.name") or "").lower()
    chat_ops = {"chat", "invoke_agent", "generate_content", "text_completion"}
    if operation not in chat_ops and not attrs.get("gen_ai.request.model"):
        return None

    model = _first_str(attrs, "gen_ai.request.model", "gen_ai.response.model")
    output_text = _first_str(attrs, "gen_ai.completion.0.content", "gen_ai.output.messages")
    return _llm_result(
        adapter="gen_ai_llm",
        model=model,
        system=_first_str(attrs, "gen_ai.system_instructions", "gen_ai.system"),
        messages=None,
        output_text=output_text,
        attrs=attrs,
    )


# --- tool adapters ----------------------------------------------------------


def _ai_sdk_tool(ctx: _Context) -> Optional[dict]:
    """Vercel AI SDK tool-call spans.

    Signal: ``ai.toolCall.name`` plus JSON-encoded ``ai.toolCall.args`` /
    ``ai.toolCall.result``. Args / result are pre-parsed (left raw if not JSON).
    """
    attrs = ctx.attrs
    name = attrs.get("ai.toolCall.name")
    if not isinstance(name, str) or not name:
        return None
    error_message = attrs.get("otel.status.message")
    args = attrs.get("ai.toolCall.args")
    result = attrs.get("ai.toolCall.result")
    if result is None:
        result = error_message
    return {
        "kind": "tool",
        "adapter": "ai_sdk_tool",
        "tool_name": name,
        "args": _json_maybe(args),
        "result": _json_maybe(result),
        "is_error": bool(error_message),
    }


def _traceloop_tool(ctx: _Context) -> Optional[dict]:
    """Traceloop tool spans. Discriminator: ``traceloop.span.kind == "tool"``
    (or a ``tool.name`` attribute)."""
    attrs = ctx.attrs
    if attrs.get("traceloop.span.kind") != "tool" and not attrs.get("tool.name"):
        return None
    error_message = attrs.get("otel.status.message")
    args = attrs.get("traceloop.entity.input")
    result = attrs.get("traceloop.entity.output")
    if result is None:
        result = error_message
    name = _first_str(attrs, "tool.name", "traceloop.entity.name")
    if name is None and ctx.name:
        name = ctx.name[:-5] if ctx.name.endswith(".tool") else ctx.name
    return {
        "kind": "tool",
        "adapter": "traceloop_tool",
        "tool_name": name,
        "args": _json_maybe(args),
        "result": _json_maybe(result),
        "is_error": bool(error_message),
    }


def _gen_ai_tool(ctx: _Context) -> Optional[dict]:
    """Generic GenAI tool spans. Signal: ``gen_ai.operation.name ==
    "execute_tool"`` or a ``gen_ai.tool.name`` attribute."""
    attrs = ctx.attrs
    operation = str(attrs.get("gen_ai.operation.name") or "").lower()
    if operation != "execute_tool" and not attrs.get("gen_ai.tool.name"):
        return None
    error_message = _first_str(attrs, "error.type", "exception.type", "otel.status.message")
    return {
        "kind": "tool",
        "adapter": "gen_ai_tool",
        "tool_name": _first_str(attrs, "gen_ai.tool.name"),
        "args": _json_maybe(attrs.get("gen_ai.tool.call.arguments")),
        "result": _json_maybe(attrs.get("gen_ai.tool.call.result")),
        "is_error": bool(error_message),
    }


# --- result + helpers -------------------------------------------------------


def _llm_result(
    *,
    adapter: str,
    model: Optional[str],
    system: Optional[str],
    messages: Optional[list],
    output_text: Optional[str],
    attrs: dict,
) -> dict:
    return {
        "kind": "llm",
        "adapter": adapter,
        "model": model,
        "system": system,
        "messages": messages,
        "output_text": output_text,
        "input_tokens": _int_maybe(
            _first_present(attrs, "gen_ai.usage.input_tokens", "ai.usage.promptTokens", "llm.usage.prompt_tokens")
        ),
        "output_tokens": _int_maybe(
            _first_present(attrs, "gen_ai.usage.output_tokens", "ai.usage.completionTokens", "llm.usage.completion_tokens")
        ),
    }


def _json_maybe(value: Any) -> Any:
    """Parse a JSON-looking string, leaving it untouched on failure. Non-string
    values pass through unchanged (so already-decoded lists/dicts survive)."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _first_str(attributes: dict, *keys: str) -> Optional[str]:
    """First key whose value is a non-empty string."""
    for key in keys:
        value = attributes.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_present(attributes: dict, *keys: str) -> Any:
    """First key that is present with a non-None value."""
    for key in keys:
        value = attributes.get(key)
        if value is not None:
            return value
    return None


def _int_maybe(value: Any) -> Optional[int]:
    """Coerce to int when sensible, otherwise None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None
    return None


def _extract_content(content: Any) -> str:
    """Flatten a content value (string, content-block list, or {content}/{text}
    object) to a plain string. Non-text blocks are dropped."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(_extract_content_block(block) for block in content)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        inner = content.get("content")
        if isinstance(inner, str):
            return inner
    return ""


def _extract_content_block(block: Any) -> str:
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            return block["text"]
        if block.get("type") in ("tool_use", "tool_result"):
            return ""
        if isinstance(block.get("text"), str):
            return block["text"]
        if isinstance(block.get("content"), str):
            return block["content"]
    return ""


def _role_or_unknown(role: Any) -> str:
    if role in ("system", "user", "assistant", "tool"):
        return role
    return "user"


def _has_prefixed(attributes: dict, prefix: str) -> bool:
    return any(isinstance(key, str) and key.startswith(prefix) for key in attributes)


def _indexed_numbers(attributes: dict, prefix: str) -> list:
    """Sorted, de-duplicated indexes for ``prefix{i}.…`` attribute keys."""
    indexes = set()
    for key in attributes:
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        rest = key[len(prefix):].split(".", 1)[0]
        try:
            indexes.add(int(rest))
        except ValueError:
            continue
    return sorted(indexes)
