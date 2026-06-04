from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .storage import IngestReport, ingest_source_payload, utc_now


class OtlpNormalizeError(Exception):
    """Raised when OTLP-like JSON cannot be normalized into Kyoko source events."""


@dataclass(frozen=True)
class OtlpIngestReport:
    profile_id: str
    run_ids: tuple[str, ...]
    span_ids: tuple[str, ...]
    ingested_counts: dict[str, int]
    normalized_path: Optional[Path]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "run_ids": list(self.run_ids),
            "span_ids": list(self.span_ids),
            "ingested_counts": self.ingested_counts,
            "normalized_path": str(self.normalized_path) if self.normalized_path else None,
        }


def normalize_otlp_json(
    payload: dict[str, Any],
    *,
    profile_id: str,
    profile_name: Optional[str] = None,
    root_path: str = ".",
    source_kind: str = "otlp_http",
    source_name: str = "OpenTelemetry",
    adapter_version: str = "kyoko.otlp_json.v0",
) -> dict[str, Any]:
    spans = _extract_spans(payload)
    if not spans:
        raise OtlpNormalizeError("otlp_json_contains_no_spans")

    now = utc_now()
    selected_profile_name = profile_name or profile_id
    source_id = _stable_id("source", source_kind, profile_id)
    by_trace: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        by_trace.setdefault(span["trace_id"], []).append(span)

    agent_by_key: dict[str, dict[str, Any]] = {}
    node_by_key: dict[str, dict[str, Any]] = {}
    run_rows: list[dict[str, Any]] = []
    span_rows: list[dict[str, Any]] = []
    timeline_events: list[dict[str, Any]] = []

    for trace_id, trace_spans in by_trace.items():
        trace_spans = sorted(trace_spans, key=lambda span: (span["started_at"], span["span_id"]))
        span_id_map = {
            span["span_id"]: _stable_id("span", profile_id, trace_id, span["span_id"])
            for span in trace_spans
        }
        root = _root_span(trace_spans)
        root_attrs = root["attributes"]
        root_agent = _agent_key(root_attrs)
        agent_key_by_span_id: dict[str, str] = {root["span_id"]: root_agent}
        root_agent_id = _ensure_agent(
            agent_by_key=agent_by_key,
            node_by_key=node_by_key,
            key=root_agent,
            attrs=root_attrs,
            profile_id=profile_id,
            source_id=source_id,
            root_path=root_path,
        )
        root_node_id = node_by_key[root_agent]["id"]
        run_id = _stable_id("run", profile_id, trace_id)
        run_rows.append(
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": trace_id,
                "root_span_id": span_id_map[root["span_id"]],
                "agent_identity_id": root_agent_id,
                "task_attempt_id": None,
                "status": _run_status(root),
                "started_at": root["started_at"],
                "ended_at": _trace_ended_at(trace_spans),
                "input_ref": _attribute_ref(root_attrs, "kyoko.input_ref"),
                "output_ref": _attribute_ref(root_attrs, "kyoko.output_ref"),
                "summary": _summary_for_trace(root, trace_spans),
                "metadata_json": {
                    "trace_id": trace_id,
                    "framework": root_attrs.get("telemetry.sdk.name") or root_attrs.get("service.name"),
                    "source": "otlp_json",
                },
            }
        )

        for span in trace_spans:
            attrs = span["attributes"]
            explicit_agent_key = _explicit_agent_key(attrs)
            parent_span_id = span.get("parent_span_id")
            if explicit_agent_key is not None:
                agent_key = explicit_agent_key
            elif parent_span_id in agent_key_by_span_id:
                agent_key = agent_key_by_span_id[str(parent_span_id)]
            else:
                agent_key = _agent_key(attrs)
            agent_key_by_span_id[span["span_id"]] = agent_key
            agent_id = _ensure_agent(
                agent_by_key=agent_by_key,
                node_by_key=node_by_key,
                key=agent_key,
                attrs=attrs,
                profile_id=profile_id,
                source_id=source_id,
                root_path=root_path,
            )
            canonical_span_id = span_id_map[span["span_id"]]
            parent_id = span_id_map.get(span.get("parent_span_id"))
            span_status = _span_status(span)
            span_rows.append(
                {
                    "id": canonical_span_id,
                    "run_id": run_id,
                    "source_id": source_id,
                    "external_id": span["span_id"],
                    "parent_span_id": parent_id,
                    "workflow_node_id": node_by_key[agent_key]["id"],
                    "agent_identity_id": agent_id,
                    "kind": _span_kind(span),
                    "name": span["name"],
                    "status": span_status,
                    "started_at": span["started_at"],
                    "ended_at": span["ended_at"],
                    "input_ref": _attribute_ref(attrs, "kyoko.input_ref"),
                    "output_ref": _attribute_ref(attrs, "kyoko.output_ref"),
                    "usage_json": _usage(attrs),
                    "attributes_json": attrs,
                    "raw_ref": _attribute_ref(attrs, "kyoko.raw_ref"),
                }
            )
            if span_status == "failed":
                timeline_events.append(
                    {
                        "id": f"event_{canonical_span_id}_failed",
                        "profile_id": profile_id,
                        "source_id": source_id,
                        "entity_type": "span",
                        "entity_id": canonical_span_id,
                        "kind": "span_failed",
                        "at": span["ended_at"] or span["started_at"],
                        "agent_identity_id": agent_id,
                        "payload_ref": _attribute_ref(attrs, "kyoko.output_ref"),
                        "metadata_json": {
                            "error_type": attrs.get("error.type") or attrs.get("exception.type"),
                            "trace_id": trace_id,
                            "span_id": span["span_id"],
                        },
                    }
                )

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": f"{profile_id}-otlp-import",
        "description": "Source events normalized from OTLP-like JSON.",
        "profile": {
            "id": profile_id,
            "name": selected_profile_name,
            "root_path": root_path,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": source_kind,
                "display_name": source_name,
                "status": "active",
                "adapter_version": adapter_version,
                "config_json": {},
                "capabilities_json": {"runs": True, "spans": True, "otlp_json": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": list(agent_by_key.values()),
        "workflow_nodes": list(node_by_key.values()),
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": run_rows,
        "spans": _order_span_rows(span_rows),
        "handoffs": [],
        "timeline_events": timeline_events,
    }


def ingest_otlp_json(
    *,
    db_path: Path,
    payload_path: Path,
    profile_id: str,
    profile_name: Optional[str] = None,
    root_path: str = ".",
    source_kind: str = "otlp_http",
    source_name: str = "OpenTelemetry",
    output_path: Optional[Path] = None,
) -> OtlpIngestReport:
    payload = _load_json(payload_path)
    if not isinstance(payload, dict):
        raise OtlpNormalizeError(f"{payload_path}: OTLP JSON must be an object")
    return ingest_otlp_payload(
        db_path=db_path,
        payload=payload,
        profile_id=profile_id,
        profile_name=profile_name,
        root_path=root_path,
        source_kind=source_kind,
        source_name=source_name,
        output_path=output_path,
        source_label=str(payload_path),
    )


def ingest_otlp_payload(
    *,
    db_path: Path,
    payload: dict[str, Any],
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[str] = None,
    source_kind: str = "otlp_http",
    source_name: str = "OpenTelemetry",
    output_path: Optional[Path] = None,
    source_label: str = "OTLP/HTTP JSON",
) -> OtlpIngestReport:
    if not isinstance(payload, dict):
        raise OtlpNormalizeError("OTLP JSON must be an object")
    attrs = _first_otlp_attributes(payload)
    selected_profile_id = (
        profile_id
        or _string(attrs.get("kyoko.profile.id"))
        or _string(attrs.get("service.namespace"))
        or _profile_id_from_service(attrs)
    )
    selected_profile_name = (
        profile_name
        or _string(attrs.get("kyoko.profile.name"))
        or _string(attrs.get("service.name"))
        or selected_profile_id
    )
    selected_root_path = root_path or _string(attrs.get("kyoko.root_path")) or "."
    normalized = normalize_otlp_json(
        payload,
        profile_id=selected_profile_id,
        profile_name=selected_profile_name,
        root_path=selected_root_path,
        source_kind=source_kind,
        source_name=source_name,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    ingest_report = ingest_source_payload(
        db_path=db_path,
        fixture=normalized,
        source_label=source_label,
    )
    return OtlpIngestReport(
        profile_id=ingest_report.profile_id,
        run_ids=tuple(run["id"] for run in normalized["runs"]),
        span_ids=tuple(span["id"] for span in normalized["spans"]),
        ingested_counts=ingest_report.inserted_counts,
        normalized_path=output_path,
    )


def _first_otlp_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    spans = _extract_spans(payload)
    return spans[0]["attributes"] if spans else {}


def _profile_id_from_service(attrs: dict[str, Any]) -> str:
    service_name = _string(attrs.get("service.name"))
    if service_name:
        return f"profile_otlp_{_slug(service_name)}"
    return "profile_otlp_default"


def _extract_spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("spans"), list):
        return [_normalize_flat_span(span, {}, {}) for span in payload["spans"] if isinstance(span, dict)]

    resource_spans = payload.get("resourceSpans") or payload.get("resource_spans")
    if not isinstance(resource_spans, list):
        return []

    spans: list[dict[str, Any]] = []
    for resource_span in resource_spans:
        if not isinstance(resource_span, dict):
            continue
        resource = resource_span.get("resource") if isinstance(resource_span.get("resource"), dict) else {}
        resource_attrs = _decode_attributes(resource.get("attributes", []))
        scope_spans = resource_span.get("scopeSpans") or resource_span.get("instrumentationLibrarySpans") or []
        if not isinstance(scope_spans, list):
            continue
        for scope_span in scope_spans:
            if not isinstance(scope_span, dict):
                continue
            scope = scope_span.get("scope") if isinstance(scope_span.get("scope"), dict) else {}
            scope_attrs = _decode_attributes(scope.get("attributes", []))
            raw_spans = scope_span.get("spans", [])
            if not isinstance(raw_spans, list):
                continue
            for raw_span in raw_spans:
                if isinstance(raw_span, dict):
                    spans.append(_normalize_flat_span(raw_span, resource_attrs, scope_attrs))
    return spans


def _normalize_flat_span(
    raw_span: dict[str, Any],
    resource_attrs: dict[str, Any],
    scope_attrs: dict[str, Any],
) -> dict[str, Any]:
    span_attrs = _decode_attributes(raw_span.get("attributes", {}))
    attrs = dict(resource_attrs)
    attrs.update(scope_attrs)
    attrs.update(span_attrs)
    trace_id = _string(raw_span.get("traceId") or raw_span.get("trace_id") or attrs.get("trace_id"))
    span_id = _string(raw_span.get("spanId") or raw_span.get("span_id") or attrs.get("span_id"))
    if not trace_id:
        trace_id = _stable_hash("trace", json.dumps(raw_span, sort_keys=True, default=str))
    if not span_id:
        span_id = _stable_hash("span", json.dumps(raw_span, sort_keys=True, default=str))
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": _string(raw_span.get("parentSpanId") or raw_span.get("parent_span_id")),
        "name": _string(raw_span.get("name")) or _string(attrs.get("gen_ai.operation.name")) or "span",
        "started_at": _timestamp(raw_span.get("startTimeUnixNano") or raw_span.get("start_time_unix_nano") or raw_span.get("started_at")),
        "ended_at": _timestamp(raw_span.get("endTimeUnixNano") or raw_span.get("end_time_unix_nano") or raw_span.get("ended_at")),
        "status": raw_span.get("status") if isinstance(raw_span.get("status"), dict) else {},
        "kind": _string(raw_span.get("kind") or raw_span.get("spanKind")),
        "attributes": attrs,
    }


def _decode_attributes(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, list):
        return {}
    attrs: dict[str, Any] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not isinstance(key, str):
            continue
        attrs[key] = _decode_otlp_value(item.get("value"))
    return attrs


def _decode_otlp_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "boolValue", "intValue", "doubleValue", "bytesValue"):
        if key in value:
            decoded = value[key]
            if key == "intValue":
                try:
                    return int(decoded)
                except (TypeError, ValueError):
                    return decoded
            return decoded
    if "arrayValue" in value:
        values = value.get("arrayValue", {}).get("values", [])
        return [_decode_otlp_value(item) for item in values] if isinstance(values, list) else []
    if "kvlistValue" in value:
        return _decode_attributes(value.get("kvlistValue", {}).get("values", []))
    return value


def _ensure_agent(
    *,
    agent_by_key: dict[str, dict[str, Any]],
    node_by_key: dict[str, dict[str, Any]],
    key: str,
    attrs: dict[str, Any],
    profile_id: str,
    source_id: str,
    root_path: str,
) -> str:
    if key in agent_by_key:
        return str(agent_by_key[key]["id"])
    agent_name = _string(attrs.get("gen_ai.agent.name") or attrs.get("service.name") or key) or "agent"
    agent_id = _stable_id("agent", profile_id, key)
    node_id = _stable_id("node", profile_id, key)
    agent_by_key[key] = {
        "id": agent_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": _string(attrs.get("gen_ai.agent.id") or key),
        "name": agent_name,
        "kind": "framework_node",
        "role": _string(attrs.get("gen_ai.agent.description")),
        "model": _string(attrs.get("gen_ai.request.model") or attrs.get("gen_ai.response.model")),
        "workspace_path": root_path,
        "metadata_json": {
            "service_name": attrs.get("service.name"),
            "provider": attrs.get("gen_ai.provider.name"),
        },
    }
    node_by_key[key] = {
        "id": node_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": key,
        "agent_identity_id": agent_id,
        "kind": "agent",
        "name": agent_name,
        "metadata_json": {
            "workflow": attrs.get("gen_ai.workflow.name"),
        },
    }
    return agent_id


def _root_span(spans: list[dict[str, Any]]) -> dict[str, Any]:
    span_ids = {span["span_id"] for span in spans}
    for span in spans:
        parent_id = span.get("parent_span_id")
        if not parent_id or parent_id not in span_ids:
            return span
    return spans[0]


def _run_status(root: dict[str, Any]) -> str:
    return "failed" if _span_status(root) == "failed" else "succeeded"


def _span_status(span: dict[str, Any]) -> str:
    status = span.get("status") if isinstance(span.get("status"), dict) else {}
    code = status.get("code")
    attrs = span["attributes"]
    if code in {2, "2", "ERROR", "STATUS_CODE_ERROR"}:
        return "failed"
    if attrs.get("error.type") or attrs.get("exception.type"):
        return "failed"
    return "succeeded"


def _span_kind(span: dict[str, Any]) -> str:
    attrs = span["attributes"]
    operation = str(attrs.get("gen_ai.operation.name") or "").lower()
    name = str(span.get("name") or "").lower()
    if operation in {"execute_tool"} or attrs.get("gen_ai.tool.name") or "tool" in name:
        return "tool"
    if operation in {"retrieval"}:
        return "retrieval"
    if operation in {"chat", "generate_content", "text_completion", "embeddings"}:
        return "llm"
    if operation in {"invoke_agent", "create_agent", "execute_agent"} or attrs.get("gen_ai.agent.name"):
        return "agent"
    if attrs.get("gen_ai.workflow.name"):
        return "workflow"
    return "system"


def _trace_ended_at(spans: list[dict[str, Any]]) -> Optional[str]:
    ended = [span["ended_at"] for span in spans if span.get("ended_at")]
    return max(ended) if ended else None


def _summary_for_trace(root: dict[str, Any], spans: list[dict[str, Any]]) -> str:
    failed_count = sum(1 for span in spans if _span_status(span) == "failed")
    if failed_count:
        return f"Imported OTLP trace {root['trace_id']} with {failed_count} failed span(s)."
    return f"Imported OTLP trace {root['trace_id']}."


def _agent_key(attrs: dict[str, Any]) -> str:
    return _explicit_agent_key(attrs) or _string(attrs.get("service.name")) or "agent"


def _explicit_agent_key(attrs: dict[str, Any]) -> Optional[str]:
    return _string(attrs.get("gen_ai.agent.id") or attrs.get("gen_ai.agent.name"))


def _usage(attrs: dict[str, Any]) -> dict[str, Any]:
    usage = {}
    for source, target in (
        ("gen_ai.usage.input_tokens", "input_tokens"),
        ("gen_ai.usage.output_tokens", "output_tokens"),
        ("gen_ai.usage.total_tokens", "total_tokens"),
    ):
        if source in attrs:
            usage[target] = attrs[source]
    return usage


def _attribute_ref(attrs: dict[str, Any], key: str) -> Optional[str]:
    value = attrs.get(key)
    return value if isinstance(value, str) and value else None


def _order_span_rows(spans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    remaining = {span["id"]: span for span in spans}
    ordered: list[dict[str, Any]] = []
    emitted: set[str] = set()
    while remaining:
        progressed = False
        for span_id, span in list(remaining.items()):
            parent_id = span.get("parent_span_id")
            if parent_id is None or parent_id in emitted or parent_id not in remaining:
                ordered.append(span)
                emitted.add(span_id)
                del remaining[span_id]
                progressed = True
        if not progressed:
            ordered.extend(remaining.values())
            break
    return ordered


def _timestamp(value: Any) -> str:
    if isinstance(value, int):
        return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        if value.isdigit():
            return _timestamp(int(value))
        return value
    return utc_now()


def _stable_id(prefix: str, *parts: Any) -> str:
    slug = _slug("_".join(_string(part) or "none" for part in parts))
    digest = _stable_hash(prefix, "|".join(_string(part) or "" for part in parts))
    return f"{prefix}_{slug[:40]}_{digest[:10]}"


def _stable_hash(prefix: str, value: str) -> str:
    return hashlib.sha1(f"{prefix}:{value}".encode("utf-8")).hexdigest()


def _slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in slug.split("_") if part) or "item"


def _string(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value
    if value is None:
        return None
    return str(value)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise OtlpNormalizeError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise OtlpNormalizeError(f"{path}: invalid JSON: {exc}") from exc
