"""MCP communication log — the agent ↔ Kyoko conversation.

Phase 1.5 of the Workshop integration (see
``docs/kyoko-workshop-integration-plan.md``). Records every JSON-RPC interaction on
Kyoko's stdio MCP server (``initialize`` / ``tools/list`` / ``tools/call`` and their
responses) so the user can watch and inspect what their coding agent asks Kyoko and
what Kyoko returns.

SCOPE alignment (``docs/SCOPE.md``):

- Single-user observability the user explicitly asked for — not multi-tenant ceremony.
  It is a plain append-only log with list/stream/one-read-tool surfaces; no state
  machine, audit-acknowledgement ledger, or per-profile settings.
- "Redact when it leaves the machine": the log is served over the dashboard API and a
  read tool, so request/response bodies are redacted via :mod:`kyoko.redaction` before
  they are stored/served.
- ``profile_id`` is an internal storage detail and is never surfaced as a choice.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from .live import EVENT_MCP_LOG, LiveBus, global_bus
from .redaction import RedactionError, get_redaction_policy, redact_evidence_bundle
from .storage import connect, initialize_database, utc_now

# Full redacted bodies are stored inline up to this cap (token-cheap, avoids a blob
# store + retention ledger for log entries). Oversized bodies are truncated and flagged.
MCP_LOG_PREVIEW_MAX_CHARS = 32768

# Used when no profile exists yet (so the log still redacts secrets before serving).
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


def _resolve_policy(db_path: Path) -> dict[str, Any]:
    try:
        return get_redaction_policy(db_path=db_path)
    except RedactionError:
        return dict(_FALLBACK_POLICY)


def _redacted_text(value: Any, policy: dict[str, Any]) -> tuple[Optional[str], bool]:
    if value is None:
        return None, False
    redacted = redact_evidence_bundle({"v": value}, policy).payload.get("v")
    if isinstance(redacted, str):
        text = redacted
    else:
        text = json.dumps(redacted, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    truncated = len(text) > MCP_LOG_PREVIEW_MAX_CHARS
    if truncated:
        text = text[:MCP_LOG_PREVIEW_MAX_CHARS]
    return text, truncated


def _row_to_dict(row: Any) -> dict[str, Any]:
    metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "seq": int(row["seq"]),
        "direction": row["direction"],
        "method": row["method"],
        "tool_name": row["tool_name"],
        "params_preview": row["params_preview"],
        "result_preview": row["result_preview"],
        "is_error": bool(row["is_error"]),
        "error_code": row["error_code"],
        "duration_ms": row["duration_ms"],
        "client_id": row["client_id"],
        "at": row["at"],
        "truncated": bool(metadata.get("truncated", False)),
        "metadata": metadata,
    }


def list_mcp_log(
    *,
    db_path: Path,
    session_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    after_seq: Optional[int] = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return recorded MCP log entries (oldest-first), filtered and capped."""

    initialize_database(db_path)
    bounded_limit = max(1, min(int(limit), 5000))
    clauses: list[str] = []
    params: list[Any] = []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if tool_name:
        clauses.append("tool_name = ?")
        params.append(tool_name)
    if after_seq is not None:
        clauses.append("seq > ?")
        params.append(int(after_seq))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect(db_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM mcp_log{where} ORDER BY at ASC, seq ASC LIMIT ?",
            (*params, bounded_limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def log_enabled_from_env(environ: dict[str, str]) -> bool:
    """Logging is on by default; ``KYOKO_MCP_LOG=0`` (or false/no/off) disables it."""

    value = str(environ.get("KYOKO_MCP_LOG", "1")).strip().lower()
    return value not in {"0", "false", "no", "off"}


class McpLogger:
    """Per-connection JSON-RPC traffic recorder for the MCP server.

    One instance lives for the lifetime of a single stdio connection. ``wrap`` records
    the incoming request, times the handler, and records the response.
    """

    def __init__(
        self,
        *,
        db_path: Path,
        session_id: Optional[str] = None,
        client_id: Optional[str] = None,
        bus: Optional[LiveBus] = None,
    ) -> None:
        self.db_path = db_path
        self.session_id = session_id or f"mcpsess_{uuid.uuid4().hex[:12]}"
        self.client_id = client_id
        self._bus = bus or global_bus()
        self._seq = 0
        self._policy: Optional[dict[str, Any]] = None

    def _policy_cached(self) -> dict[str, Any]:
        if self._policy is None:
            self._policy = _resolve_policy(self.db_path)
        return self._policy

    def _record(
        self,
        *,
        direction: str,
        method: Optional[str],
        tool_name: Optional[str],
        body: Any,
        is_error: bool = False,
        error_code: Optional[int] = None,
        duration_ms: Optional[float] = None,
    ) -> dict[str, Any]:
        preview, truncated = _redacted_text(body, self._policy_cached())
        self._seq += 1
        seq = self._seq
        entry_id = f"mcplog_{uuid.uuid4().hex[:12]}"
        at = utc_now()
        is_request = direction in {"request", "notification"}
        params_preview = preview if is_request else None
        result_preview = None if is_request else preview
        metadata: dict[str, Any] = {}
        if truncated:
            metadata["truncated"] = True
        initialize_database(self.db_path)
        with connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO mcp_log (
                  id, profile_id, session_id, seq, direction, method, tool_name,
                  params_preview, params_ref, result_preview, result_ref,
                  is_error, error_code, duration_ms, client_id, at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    None,
                    self.session_id,
                    seq,
                    direction,
                    method,
                    tool_name,
                    params_preview,
                    None,
                    result_preview,
                    None,
                    1 if is_error else 0,
                    error_code,
                    duration_ms,
                    self.client_id,
                    at,
                    json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                ),
            )
        record = {
            "id": entry_id,
            "session_id": self.session_id,
            "seq": seq,
            "direction": direction,
            "method": method,
            "tool_name": tool_name,
            "params_preview": params_preview,
            "result_preview": result_preview,
            "is_error": is_error,
            "error_code": error_code,
            "duration_ms": duration_ms,
            "client_id": self.client_id,
            "at": at,
            "truncated": truncated,
            "metadata": metadata,
        }
        self._bus.publish(EVENT_MCP_LOG, record)
        return record

    def wrap(
        self,
        message: Any,
        handler: Callable[[Any], Optional[dict[str, Any]]],
    ) -> Optional[dict[str, Any]]:
        method: Optional[str] = None
        params: Any = None
        tool_name: Optional[str] = None
        is_notification = isinstance(message, dict) and "id" not in message
        if isinstance(message, dict):
            method = message.get("method") if isinstance(message.get("method"), str) else None
            params = message.get("params")
            if method == "tools/call" and isinstance(params, dict):
                name = params.get("name")
                tool_name = name if isinstance(name, str) else None
            if method == "initialize" and isinstance(params, dict) and not self.client_id:
                client_info = params.get("clientInfo")
                if isinstance(client_info, dict) and isinstance(client_info.get("name"), str):
                    self.client_id = client_info["name"]

        self._record(
            direction="notification" if is_notification else "request",
            method=method,
            tool_name=tool_name,
            body=params if params is not None else message,
        )

        start = time.monotonic()
        response = handler(message)
        duration_ms = round((time.monotonic() - start) * 1000.0, 3)

        if response is not None:
            error = response.get("error") if isinstance(response, dict) else None
            result_body = response.get("result") if isinstance(response, dict) else response
            is_error = error is not None
            error_code = error.get("code") if isinstance(error, dict) else None
            # tools/call surfaces handler failures as a result with isError=true.
            if not is_error and isinstance(result_body, dict) and result_body.get("isError"):
                is_error = True
            self._record(
                direction="response",
                method=method,
                tool_name=tool_name,
                body=error if is_error and error is not None else result_body,
                is_error=is_error,
                error_code=error_code,
                duration_ms=duration_ms,
            )
        return response
