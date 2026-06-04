"""Resolve `llm_eval` template variables from Kyoko's span/run model.

A template's ``bindings`` map each ``{{var}}`` to a source string:

- ``unit.output_text`` / ``unit.user_query`` — for ``llm_span`` units, off the
  normalized span (``span_normalize.normalize_span``).
- ``run.transcript`` / ``run.last_user_message`` / ``run.first_user_message`` /
  ``run.system_prompt`` / ``run.final_output`` — for ``run`` units, derived from
  the run's normalized LLM spans.
- ``annotation.<label>|<fallback>`` — try a ``note`` annotation on the run whose
  ``metadata.label_type`` matches ``<label>``; if absent, fall back to the
  ``<fallback>`` source and mark the result **degraded** (e.g. Goal Accuracy's
  ``desired_outcome`` degrades to the user goal — a documented limitation, since
  Kyoko has no ground-truth plane).

A var that resolves to ``None``/empty makes the unit **skipped**
(``missing_var:<name>``) — never silently scored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .annotations import list_annotations
from .eval_detectors import export_run_trace
from .span_normalize import normalize_span
from .storage import connect, initialize_database


class BindingError(Exception):
    """Raised for a malformed binding spec."""


@dataclass
class BindingResolution:
    values: dict[str, str]
    missing: list[str] = field(default_factory=list)
    degraded: bool = False
    run_id: Optional[str] = None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _messages(normalized: dict[str, Any]) -> list[dict[str, Any]]:
    msgs = normalized.get("messages")
    return msgs if isinstance(msgs, list) else []


def _role(message: Any) -> str:
    return str(message.get("role", "")).lower() if isinstance(message, dict) else ""


def _content(message: Any) -> str:
    if isinstance(message, dict):
        return _text(message.get("content"))
    return _text(message)


def _last_user(messages: list[dict[str, Any]]) -> Optional[str]:
    for message in reversed(messages):
        if _role(message) == "user":
            text = _content(message).strip()
            if text:
                return text
    return None


def _first_user(messages: list[dict[str, Any]]) -> Optional[str]:
    for message in messages:
        if _role(message) == "user":
            text = _content(message).strip()
            if text:
                return text
    return None


def _llm_span_context(connection: Any, span_id: str) -> tuple[dict[str, Any], Optional[str]]:
    import json as _json

    row = connection.execute("SELECT * FROM spans WHERE id = ?", (span_id,)).fetchone()
    if row is None:
        return {}, None
    try:
        attributes = _json.loads(row["attributes_json"] or "{}")
    except (ValueError, TypeError):
        attributes = {}
    normalized = normalize_span(
        name=row["name"],
        kind=row["kind"],
        attributes=attributes if isinstance(attributes, dict) else {},
    )
    messages = _messages(normalized)
    ctx = {
        "unit.output_text": _text(normalized.get("output_text")).strip() or None,
        "unit.user_query": _last_user(messages),
    }
    return ctx, row["run_id"]


def _run_context(db_path: Path, run_id: str) -> dict[str, Any]:
    trace = export_run_trace(db_path=db_path, run_id=run_id)
    llm_spans = [s for s in trace["spans"] if (s.get("normalized") or {}).get("kind") == "llm"]
    all_messages: list[dict[str, Any]] = []
    system_prompt: Optional[str] = None
    final_output: Optional[str] = None
    transcript_lines: list[str] = []
    for span in llm_spans:
        norm = span["normalized"]
        if system_prompt is None and _text(norm.get("system")).strip():
            system_prompt = _text(norm.get("system")).strip()
        for message in _messages(norm):
            all_messages.append(message)
            role = _role(message) or "?"
            content = _content(message).strip()
            if content:
                transcript_lines.append(f"{role}: {content}")
        output_text = _text(norm.get("output_text")).strip()
        if output_text:
            final_output = output_text
            transcript_lines.append(f"assistant: {output_text}")
    return {
        "run.transcript": "\n".join(transcript_lines) or None,
        "run.last_user_message": _last_user(all_messages),
        "run.first_user_message": _first_user(all_messages),
        "run.system_prompt": system_prompt,
        "run.final_output": final_output,
    }


def _annotation_value(db_path: Path, run_id: Optional[str], label: str) -> Optional[str]:
    if not run_id:
        return None
    for annotation in list_annotations(db_path=db_path, run_id=run_id):
        if annotation.get("kind") != "note":
            continue
        metadata = annotation.get("metadata") or {}
        if isinstance(metadata, dict) and metadata.get("label_type") == label:
            text = _text(annotation.get("body") or annotation.get("note")).strip()
            if text:
                return text
    return None


def resolve_bindings(
    *,
    db_path: Path,
    unit_type: str,
    unit_ref: str,
    bindings: dict[str, str],
    profile_id: Optional[str] = None,
) -> BindingResolution:
    initialize_database(db_path)
    degraded = False

    if unit_type == "llm_span":
        with connect(db_path) as connection:
            ctx, run_id = _llm_span_context(connection, unit_ref)
    elif unit_type == "run":
        run_id = unit_ref
        ctx = _run_context(db_path, unit_ref)
    else:
        raise BindingError(f"unsupported_unit_type:{unit_type}")

    values: dict[str, str] = {}
    missing: list[str] = []
    for var, spec in bindings.items():
        value: Optional[str] = None
        for alternative in str(spec).split("|"):
            alternative = alternative.strip()
            if alternative.startswith("annotation."):
                label = alternative.split(".", 1)[1]
                value = _annotation_value(db_path, run_id, label)
                if value is None:
                    continue  # try the fallback source
            else:
                resolved = ctx.get(alternative)
                value = resolved if (resolved is None or str(resolved).strip()) else None
                if value is None:
                    continue
            # a later alternative supplied the value -> degraded resolution
            if alternative != str(spec).split("|")[0].strip():
                degraded = True
            break
        if value is None or not str(value).strip():
            missing.append(var)
        else:
            values[var] = str(value)
    return BindingResolution(values=values, missing=missing, degraded=degraded, run_id=run_id)
