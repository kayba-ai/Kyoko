from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


PAYLOAD_ACCESS_MODES = {"redacted", "refs_only", "unredacted"}
PAYLOAD_REF_KEYS = {
    "artifact_refs",
    "body_ref",
    "diff_ref",
    "error_ref",
    "evidence_ref",
    "input_ref",
    "output_ref",
    "payload_ref",
    "prompt_ref",
    "raw_output_ref",
    "raw_ref",
    "reason_ref",
    "summary_ref",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"sk-[A-Za-z0-9]{12,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|token|client[_-]?secret|secret|password)=[^&\s]+"),
)

# SCOPE simplification: redaction collapses to a single global "redact on
# export" default. Kyoko is single-user/local; there is no per-profile policy
# table and no audit ledger. Every export path redacts payload refs and known
# sensitive values by default.
DEFAULT_REDACTION_POLICY = {
    "profile_id": None,
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


class RedactionError(Exception):
    """Raised when evidence redaction operations fail."""


@dataclass(frozen=True)
class RedactionResult:
    payload: dict[str, Any]
    summary: dict[str, Any]


def get_redaction_policy(*, db_path: Optional[Path] = None, profile_id: Optional[str] = None) -> dict[str, Any]:
    # The global default is the only policy. Kwargs are accepted for caller
    # compatibility and intentionally ignored.
    return dict(DEFAULT_REDACTION_POLICY)


def redact_evidence_bundle(bundle: dict[str, Any], policy: dict[str, Any]) -> RedactionResult:
    payload = copy.deepcopy(bundle)
    payload_access = str(policy.get("payload_access") or "redacted")
    redact_sensitive_values = bool(policy.get("redact_sensitive_values", True))
    placeholder = str(policy.get("redacted_placeholder") or "[REDACTED]")
    patterns = _clean_patterns(policy.get("sensitive_key_patterns", []))
    hide_payload_refs = payload_access == "redacted"
    redact_values = payload_access != "unredacted" and redact_sensitive_values

    stats = {"redacted_count": 0, "redacted_paths": []}
    if hide_payload_refs or redact_values:
        _redact_value(
            payload,
            path="$",
            patterns=patterns,
            placeholder=placeholder,
            hide_payload_refs=hide_payload_refs,
            redact_values=redact_values,
            stats=stats,
        )

    summary = {
        "policy": {
            "profile_id": policy.get("profile_id"),
            "payload_access": payload_access,
            "redact_sensitive_values": redact_sensitive_values,
        },
        "redacted": hide_payload_refs or redact_values,
        "redacted_count": int(stats["redacted_count"]),
        "redacted_paths": list(stats["redacted_paths"])[:100],
        "redacted_paths_truncated": len(stats["redacted_paths"]) > 100,
    }
    payload["redaction"] = summary
    return RedactionResult(payload=payload, summary=summary)


def _redact_value(
    value: Any,
    *,
    path: str,
    patterns: list[str],
    placeholder: str,
    hide_payload_refs: bool,
    redact_values: bool,
    stats: dict[str, Any],
) -> Any:
    if isinstance(value, dict):
        for key in list(value.keys()):
            child_path = f"{path}.{key}"
            child = value[key]
            if hide_payload_refs and key in PAYLOAD_REF_KEYS and child is not None:
                value[key] = "[REDACTED:payload_ref]"
                _record_redaction(stats, child_path)
                continue
            if redact_values and _sensitive_key(key, patterns) and child not in (None, ""):
                value[key] = "[REDACTED:secret]"
                _record_redaction(stats, child_path)
                continue
            value[key] = _redact_value(
                child,
                path=child_path,
                patterns=patterns,
                placeholder=placeholder,
                hide_payload_refs=hide_payload_refs,
                redact_values=redact_values,
                stats=stats,
            )
        return value
    if isinstance(value, list):
        for index, child in enumerate(value):
            value[index] = _redact_value(
                child,
                path=f"{path}[{index}]",
                patterns=patterns,
                placeholder=placeholder,
                hide_payload_refs=hide_payload_refs,
                redact_values=redact_values,
                stats=stats,
            )
        return value
    if redact_values and isinstance(value, str):
        redacted = value
        for pattern in SECRET_VALUE_PATTERNS:
            redacted = pattern.sub(placeholder, redacted)
        if redacted != value:
            _record_redaction(stats, path)
        return redacted
    return value


def _record_redaction(stats: dict[str, Any], path: str) -> None:
    stats["redacted_count"] += 1
    stats["redacted_paths"].append(path)


def _sensitive_key(key: str, patterns: list[str]) -> bool:
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    return any(pattern in normalized for pattern in patterns)


def _clean_patterns(patterns: Any) -> list[str]:
    if not isinstance(patterns, list):
        return []
    cleaned = []
    seen = set()
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        value = pattern.strip().lower().replace("-", "_").replace(" ", "_")
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
