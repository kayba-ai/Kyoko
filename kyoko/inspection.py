"""Trace-inspection ergonomics for coding agents (Phase 2 of the Workshop port).

See ``docs/kyoko-workshop-integration-plan.md``. These are read-only helpers an agent
(or the dashboard) uses to navigate a captured run without dumping whole payloads:

- :func:`get_current_run` — the most recently active run (SCOPE-aligned: no cross-process
  "viewing registry"; the agent's real need is "the run I just produced").
- :func:`get_run_outline` — structural skeleton (span tree, counts, short previews), no
  full payloads.
- :func:`search_run` — substring/regex search across span names, attributes, payload
  previews, and live events.
- :func:`get_span_context` — neighbour span skeletons around one span.
- :func:`get_span_payload` — a span's input/output payload, **redacted** before it leaves
  the machine, with optional path extraction and slicing.

All payload/attribute content served here is redacted by default (SCOPE: redact when
evidence leaves the machine). ``profile_id`` is an internal storage detail and is never a
user-facing choice.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from .redaction import RedactionError, get_redaction_policy, redact_evidence_bundle
from .span_normalize import normalize_span
from .storage import connect, initialize_database, spans_fts_ready
from .subagents import detect_subagents

_FAILED_STATUSES = {"failed", "timed_out", "errored", "error"}

# Used only when no profile/redaction policy is available (rare; runs always have one).
_FALLBACK_POLICY: dict[str, Any] = {
    "payload_access": "redacted",
    "redact_sensitive_values": True,
    "redacted_placeholder": "[REDACTED]",
    "sensitive_key_patterns": [
        "api_key",
        "apikey",
        "authorization",
        "client_secret",
        "access_key",
        "refresh_token",
        "secret",
        "password",
        "passwd",
        "pwd",
        "token",
        "credential",
        "private_key",
        "cookie",
    ],
}


class InspectionError(Exception):
    """Raised for invalid inspection input (missing run/span, bad target, etc.)."""


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str) or not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _decode_run(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["metadata"] = _json_loads(payload.pop("metadata_json", None), {})
    return payload


def _decode_span(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["attributes"] = _json_loads(payload.pop("attributes_json", None), {})
    payload["usage"] = _json_loads(payload.pop("usage_json", None), {})
    return payload


def _resolve_policy(db_path: Path, profile_id: Optional[str]) -> dict[str, Any]:
    try:
        return get_redaction_policy(db_path=db_path, profile_id=profile_id)
    except RedactionError:
        return dict(_FALLBACK_POLICY)


def _model_of(span: dict[str, Any]) -> Optional[str]:
    attributes = span.get("attributes") or {}
    for key in ("gen_ai.request.model", "gen_ai.response.model", "model", "kyoko.model"):
        value = attributes.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _span_skeleton(span: dict[str, Any], *, preview_chars: int = 0, previews: Optional[dict[str, str]] = None) -> dict[str, Any]:
    skeleton = {
        "id": span["id"],
        "parent_span_id": span.get("parent_span_id"),
        "name": span.get("name"),
        "kind": span.get("kind"),
        "status": span.get("status"),
        "started_at": span.get("started_at"),
        "ended_at": span.get("ended_at"),
        "agent_identity_id": span.get("agent_identity_id"),
        "model": _model_of(span),
        "usage": span.get("usage") or {},
        "normalized": normalize_span(
            name=str(span.get("name") or ""),
            kind=span.get("kind"),
            attributes=span.get("attributes") or {},
        ),
    }
    if preview_chars and previews is not None:
        skeleton["input_preview"] = (previews.get("input") or "")[:preview_chars] or None
        skeleton["output_preview"] = (previews.get("output") or "")[:preview_chars] or None
    return skeleton


def _tree(skeletons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes = [{**skeleton, "children": []} for skeleton in skeletons]
    by_id = {str(node["id"]): node for node in nodes}
    roots: list[dict[str, Any]] = []
    for node in nodes:
        parent_id = node.get("parent_span_id")
        parent = by_id.get(parent_id) if isinstance(parent_id, str) else None
        (roots if parent is None else parent["children"]).append(node)
    return roots


def _blob_previews(connection: Any, span: dict[str, Any]) -> dict[str, str]:
    previews: dict[str, str] = {}
    for target, ref_key in (("input", "input_ref"), ("output", "output_ref")):
        ref = span.get(ref_key)
        if not isinstance(ref, str) or not ref:
            continue
        row = connection.execute(
            "SELECT preview FROM payload_blobs WHERE id = ?", (ref,)
        ).fetchone()
        if row is not None and row["preview"]:
            previews[target] = str(row["preview"])
    return previews


def _get_run_row(connection: Any, run_id: str) -> Any:
    run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise InspectionError(f"run_not_found:{run_id}")
    return run


def get_current_run(*, db_path: Path, profile_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    """Return the most recently active run (or None if there are no runs).

    "Active" = latest by ``ended_at`` then ``started_at``. This is intentionally simple:
    for a single-user tool the agent's "current run" is the one it just produced.
    """

    initialize_database(db_path)
    clauses = []
    params: list[Any] = []
    if profile_id:
        clauses.append("profile_id = ?")
        params.append(profile_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as connection:
        run = connection.execute(
            f"SELECT * FROM runs{where} "
            "ORDER BY COALESCE(ended_at, started_at) DESC, started_at DESC, id DESC LIMIT 1",
            tuple(params),
        ).fetchone()
        if run is None:
            return None
        run_id = str(run["id"])
        span_count = connection.execute(
            "SELECT COUNT(*) FROM spans WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        decoded = _decode_run(run)
    decoded["span_count"] = int(span_count)
    return decoded


def get_run_outline(
    *,
    db_path: Path,
    run_id: str,
    payload_preview_chars: int = 200,
) -> dict[str, Any]:
    """Structural overview of a run: span tree skeleton + counts. No full payloads."""

    initialize_database(db_path)
    preview_chars = max(0, min(int(payload_preview_chars), 2000))
    with connect(db_path) as connection:
        run = _get_run_row(connection, run_id)
        span_rows = connection.execute(
            "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id", (run_id,)
        ).fetchall()
        spans = [_decode_span(row) for row in span_rows]
        skeletons = [
            _span_skeleton(
                span,
                preview_chars=preview_chars,
                previews=_blob_previews(connection, span) if preview_chars else None,
            )
            for span in spans
        ]
        handoff_count = connection.execute(
            "SELECT COUNT(*) FROM handoffs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        live_event_count = connection.execute(
            "SELECT COUNT(*) FROM live_events WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        annotation_count = connection.execute(
            "SELECT COUNT(*) FROM annotations WHERE run_id = ?", (run_id,)
        ).fetchone()[0]
        decoded_run = _decode_run(run)

    failed = [s for s in skeletons if str(s.get("status")) in _FAILED_STATUSES]
    detected_subagents = detect_subagents(spans)
    return {
        "run": {
            "id": decoded_run["id"],
            "status": decoded_run.get("status"),
            "started_at": decoded_run.get("started_at"),
            "ended_at": decoded_run.get("ended_at"),
            "summary": decoded_run.get("summary"),
        },
        "span_tree": _tree(skeletons),
        "subagents": detected_subagents,
        "summary": {
            "spans": len(skeletons),
            "failed_spans": len(failed),
            "handoffs": int(handoff_count),
            "live_events": int(live_event_count),
            "annotations": int(annotation_count),
            "subagents": len(detected_subagents),
        },
    }


# Characters that carry special meaning inside an FTS5 MATCH query, plus whitespace.
# A pattern containing any of these cannot be turned into a single safe token query.
_FTS_UNSAFE = set(' \t\r\n"\'()*:+-.,;/\\!?@#$%^&{}[]<>=~`|')


def _fts_token_query(pattern: str) -> Optional[str]:
    """Build a safe FTS5 prefix-MATCH query for ``pattern``, or None if unsafe.

    Returns ``"<pattern>"*`` (a quoted prefix query) for a single clean token with no
    FTS operators/whitespace; None otherwise (caller scans all spans).
    """

    if not pattern or any(ch in _FTS_UNSAFE for ch in pattern):
        return None
    return f'"{pattern}"*'


def _fts_candidate_span_ids(
    connection: Any, run_id: str, pattern: str, regex: bool, case_sensitive: bool
) -> Optional[set[str]]:
    """Return span_ids to restrict the scan to, or None meaning "scan all spans".

    FTS5 is token-based, so a token-prefix MATCH is **not** a guaranteed superset of
    every substring match: a pattern that appears only *mid-token* (e.g. ``model`` in
    ``submodel``) is missed by the prefix query. To stay exactly as correct as the old
    linear scan we therefore only use the FTS pre-filter when it is provably complete:

    * regex / case-sensitive / non-token patterns → None (FTS can't model them).
    * FTS5 unavailable or index missing → None.
    * prefix MATCH returns an empty set → None. An empty result can't distinguish "no
      matches" from "only mid-token matches", so we must rescan everything.
    * prefix MATCH returns candidates → cross-check completeness: count spans the
      prefix query missed that nonetheless contain the pattern as a bare substring
      (via FTS, cheaply, using a non-prefixed phrase the tokenizer still indexes). If
      any exist we abandon the pre-filter (None) and scan all; otherwise the candidate
      set is a true superset and we return it.

    The candidate set is always a *superset* (each span is still re-verified with the
    precise regex matcher), so this can only ever skip non-matching spans.
    """

    if regex or case_sensitive:
        return None
    if not spans_fts_ready(connection):
        return None
    query = _fts_token_query(pattern)
    if query is None:
        return None
    try:
        rows = connection.execute(
            "SELECT span_id FROM spans_fts WHERE run_id = ? AND spans_fts MATCH ?",
            (run_id, query),
        ).fetchall()
    except Exception:
        # Any FTS query error → fall back to the full scan rather than miss matches.
        return None
    candidates = {str(row["span_id"]) for row in rows}
    if not candidates:
        # Could be a genuine miss or a mid-token-only match; rescan everything.
        return None
    # Completeness guard against mid-token matches in spans the prefix query skipped.
    # A bare (non-prefixed) token MATCH still only finds token-boundary hits, so the
    # only spans the prefix query can miss are those where the pattern is purely
    # mid-token. We detect that by scanning the candidates' complement with a cheap
    # SQL substring test (LIKE) over the stored FTS text. If the complement has any
    # substring hit, the prefix set is not a superset → fall back to a full scan.
    placeholders = ",".join("?" for _ in candidates)
    like = "%" + pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    try:
        missed = connection.execute(
            f"SELECT 1 FROM spans_fts WHERE run_id = ? "
            f"AND span_id NOT IN ({placeholders}) "
            f"AND lower(text) LIKE lower(?) ESCAPE '\\' LIMIT 1",
            (run_id, *candidates, like),
        ).fetchone()
    except Exception:
        return None
    if missed is not None:
        return None
    return candidates


def _iter_search_targets(
    connection: Any,
    run_id: str,
    scope: Optional[set[str]],
    candidate_span_ids: Optional[set[str]] = None,
):
    """Yield (location, text) candidates for search.

    When ``candidate_span_ids`` is not None it is an FTS pre-filter: only those spans
    are scanned for name/attributes/payload targets. ``live_events`` are never part of
    the FTS index, so they are always scanned regardless of the pre-filter.
    """

    def allowed(name: str) -> bool:
        return scope is None or name in scope

    span_rows = connection.execute(
        "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id", (run_id,)
    ).fetchall()
    for row in span_rows:
        if candidate_span_ids is not None and str(row["id"]) not in candidate_span_ids:
            continue
        span = _decode_span(row)
        span_id = str(span["id"])
        if allowed("name") and span.get("name"):
            yield ({"kind": "span_name", "span_id": span_id}, str(span["name"]))
        if allowed("attributes") and span.get("attributes"):
            yield (
                {"kind": "span_attributes", "span_id": span_id},
                json.dumps(span["attributes"], ensure_ascii=False, sort_keys=True),
            )
        if allowed("payload"):
            for target, text in _blob_previews(connection, span).items():
                yield ({"kind": f"span_{target}", "span_id": span_id}, text)
    if allowed("live_events"):
        for row in connection.execute(
            "SELECT id, span_id, content_preview FROM live_events WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall():
            if row["content_preview"]:
                yield (
                    {"kind": "live_event", "live_event_id": row["id"], "span_id": row["span_id"]},
                    str(row["content_preview"]),
                )


def search_run(
    *,
    db_path: Path,
    run_id: str,
    pattern: str,
    regex: bool = False,
    case_sensitive: bool = False,
    scope: Optional[list[str]] = None,
    context_chars: int = 80,
    max_matches: int = 50,
) -> dict[str, Any]:
    """Search a run's spans/attributes/payload-previews/live-events for ``pattern``."""

    initialize_database(db_path)
    if not pattern:
        raise InspectionError("pattern_required")
    bounded_max = max(1, min(int(max_matches), 1000))
    ctx = max(0, min(int(context_chars), 1000))
    scope_set = set(scope) if scope else None

    flags = 0 if case_sensitive else re.IGNORECASE
    if regex:
        try:
            matcher = re.compile(pattern, flags)
        except re.error as exc:
            raise InspectionError(f"invalid_regex:{exc}") from exc
    else:
        matcher = re.compile(re.escape(pattern), flags)

    matches: list[dict[str, Any]] = []
    truncated = False
    with connect(db_path) as connection:
        _get_run_row(connection, run_id)
        # FTS5 pre-filter: when the pattern is a clean case-insensitive token and the
        # index is present, restrict the span-target scan to candidate spans. Every
        # candidate is still verified with the precise regex matcher below, so the
        # filter only ever needs to be a *superset* of matching spans (never exact).
        # Returns None (scan all spans) for regex/case-sensitive/non-token patterns or
        # when FTS5 is unavailable — preserving the original linear behaviour exactly.
        candidate_span_ids = _fts_candidate_span_ids(
            connection, run_id, pattern, regex, case_sensitive
        )
        for location, text in _iter_search_targets(
            connection, run_id, scope_set, candidate_span_ids
        ):
            for found in matcher.finditer(text):
                if len(matches) >= bounded_max:
                    truncated = True
                    break
                start = max(0, found.start() - ctx)
                end = min(len(text), found.end() + ctx)
                matches.append(
                    {
                        **location,
                        "match": found.group(0),
                        "snippet": text[start:end],
                        "offset": found.start(),
                    }
                )
            if truncated:
                break
    return {"run_id": run_id, "matches": matches, "match_count": len(matches), "truncated": truncated}


def get_span_context(
    *,
    db_path: Path,
    span_id: str,
    before: int = 2,
    after: int = 2,
    include_parent: bool = True,
) -> dict[str, Any]:
    """Return neighbour span skeletons (time-ordered) around ``span_id``."""

    initialize_database(db_path)
    before = max(0, min(int(before), 50))
    after = max(0, min(int(after), 50))
    with connect(db_path) as connection:
        target = connection.execute("SELECT * FROM spans WHERE id = ?", (span_id,)).fetchone()
        if target is None:
            raise InspectionError(f"span_not_found:{span_id}")
        run_id = str(target["run_id"])
        span_rows = connection.execute(
            "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id", (run_id,)
        ).fetchall()
        spans = [_decode_span(row) for row in span_rows]
        index = next((i for i, span in enumerate(spans) if str(span["id"]) == span_id), None)
        window = spans[max(0, index - before) : index + after + 1] if index is not None else []
        decoded_target = _decode_span(target)
        parent = None
        if include_parent and isinstance(decoded_target.get("parent_span_id"), str):
            parent_row = connection.execute(
                "SELECT * FROM spans WHERE id = ?", (decoded_target["parent_span_id"],)
            ).fetchone()
            if parent_row is not None:
                parent = _span_skeleton(_decode_span(parent_row))
    return {
        "span_id": span_id,
        "run_id": run_id,
        "target": _span_skeleton(decoded_target),
        "parent": parent,
        "context": [_span_skeleton(span) for span in window],
    }


def _extract_path(value: Any, path: str) -> Any:
    """Minimal dotted/bracket path extractor (e.g. ``messages.0.content`` or
    ``$.messages[0].content``). Not full JSONPath — intentionally lean."""

    cleaned = path.strip()
    if cleaned.startswith("$"):
        cleaned = cleaned[1:]
    cleaned = cleaned.replace("]", "").replace("[", ".").lstrip(".")
    if not cleaned:
        return value
    current = value
    for token in cleaned.split("."):
        if token == "":
            continue
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                raise InspectionError(f"path_not_found:{path}")
        elif isinstance(current, dict):
            if token not in current:
                raise InspectionError(f"path_not_found:{path}")
            current = current[token]
        else:
            raise InspectionError(f"path_not_found:{path}")
    return current


def get_span_payload(
    *,
    db_path: Path,
    span_id: str,
    target: str = "input",
    path: Optional[str] = None,
    max_chars: int = 4000,
    offset: int = 0,
) -> dict[str, Any]:
    """Return a span's input/output payload, redacted, with optional path + slicing."""

    initialize_database(db_path)
    if target not in {"input", "output"}:
        raise InspectionError(f"unsupported_target:{target}")
    bounded_max = max(1, min(int(max_chars), 200000))
    start = max(0, int(offset))
    with connect(db_path) as connection:
        span = connection.execute("SELECT * FROM spans WHERE id = ?", (span_id,)).fetchone()
        if span is None:
            raise InspectionError(f"span_not_found:{span_id}")
        run = connection.execute(
            "SELECT profile_id FROM runs WHERE id = ?", (span["run_id"],)
        ).fetchone()
        profile_id = str(run["profile_id"]) if run is not None else None
        ref = span["input_ref"] if target == "input" else span["output_ref"]
        if not isinstance(ref, str) or not ref:
            return {"span_id": span_id, "target": target, "available": False}
        blob = connection.execute(
            "SELECT * FROM payload_blobs WHERE id = ?", (ref,)
        ).fetchone()
        if blob is None:
            return {"span_id": span_id, "target": target, "available": False}
        media_type = str(blob["media_type"])
        size_bytes = int(blob["size_bytes"])
        try:
            raw = Path(blob["path"]).read_text(errors="replace")
        except OSError:
            raw = str(blob["preview"] or "")

    policy = _resolve_policy(db_path, profile_id)
    is_json = "json" in media_type
    parsed = _json_loads(raw, None) if is_json else None
    if parsed is not None:
        if path:
            parsed = _extract_path(parsed, path)
        redacted = redact_evidence_bundle({"v": parsed}, policy).payload.get("v")
        content = (
            redacted
            if isinstance(redacted, str)
            else json.dumps(redacted, ensure_ascii=False, sort_keys=True, indent=2)
        )
    else:
        if path:
            raise InspectionError("path_requires_json_payload")
        # Plain text: redaction works on key/value structures, so wrap+unwrap is a no-op
        # for free text but keeps behaviour uniform if the text is JSON-ish.
        content = raw

    sliced = content[start : start + bounded_max]
    truncated = (start + bounded_max) < len(content) or start > 0
    return {
        "span_id": span_id,
        "target": target,
        "available": True,
        "media_type": media_type,
        "size_bytes": size_bytes,
        "path_applied": path,
        "offset": start,
        "truncated": truncated,
        "content": sliced,
    }
