from __future__ import annotations

import json
import sys
import traceback
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Optional, Type

from .storage import utc_now


class KyokoSdkError(Exception):
    """Raised when the local SDK cannot create or send source events."""


@dataclass
class SpanHandle:
    recorder: "KyokoRecorder"
    run: "RunHandle"
    span_id: str
    name: str
    kind: str
    parent_span_id: Optional[str]
    workflow_node_id: Optional[str]
    agent_identity_id: Optional[str]
    started_at: str
    external_id: Optional[str] = None
    input_ref: Optional[str] = None
    output_ref: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    raw_ref: Optional[str] = None
    status: str = "running"
    ended_at: Optional[str] = None

    def __enter__(self) -> "SpanHandle":
        self.run._span_stack.append(self.span_id)
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        if exc is not None:
            self.fail(exc)
        else:
            self.finish()
        if self.run._span_stack and self.run._span_stack[-1] == self.span_id:
            self.run._span_stack.pop()
        return False

    def finish(self, *, status: str = "succeeded", output_ref: Optional[str] = None) -> None:
        if self.ended_at is not None:
            return
        self.status = status
        self.ended_at = utc_now()
        if output_ref is not None:
            self.output_ref = output_ref
        self.recorder._spans.append(self._to_payload())

    def fail(self, exc: BaseException, *, output_ref: Optional[str] = None) -> None:
        if self.ended_at is not None:
            return
        self.status = "failed"
        self.ended_at = utc_now()
        if output_ref is not None:
            self.output_ref = output_ref
        self.attributes.setdefault("error_type", exc.__class__.__name__)
        self.attributes.setdefault("error_message", str(exc))
        self.attributes.setdefault("traceback", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        self.recorder._spans.append(self._to_payload())

    def _to_payload(self) -> dict[str, Any]:
        return {
            "id": self.span_id,
            "run_id": self.run.run_id,
            "source_id": self.recorder.source_id,
            "external_id": self.external_id,
            "parent_span_id": self.parent_span_id,
            "workflow_node_id": self.workflow_node_id,
            "agent_identity_id": self.agent_identity_id,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "usage_json": self.usage,
            "attributes_json": self.attributes,
            "raw_ref": self.raw_ref,
        }


@dataclass
class RunHandle:
    recorder: "KyokoRecorder"
    run_id: str
    name: str
    started_at: str
    agent_identity_id: str
    workflow_node_id: str
    external_id: Optional[str] = None
    input_ref: Optional[str] = None
    output_ref: Optional[str] = None
    summary: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "running"
    ended_at: Optional[str] = None
    root_span_id: Optional[str] = None
    _span_stack: list[str] = field(default_factory=list)

    def __enter__(self) -> "RunHandle":
        self.recorder._active_runs.append(self.run_id)
        self.root_span_id = self.recorder._new_id("span", self.name)
        root_span = SpanHandle(
            recorder=self.recorder,
            run=self,
            span_id=self.root_span_id,
            name=self.name,
            kind="agent",
            parent_span_id=None,
            workflow_node_id=self.workflow_node_id,
            agent_identity_id=self.agent_identity_id,
            started_at=self.started_at,
            input_ref=self.input_ref,
        )
        root_span.__enter__()
        self._root_span = root_span
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool:
        if exc is not None:
            self.fail(exc)
        else:
            self.finish()
        self._span_stack.clear()
        if self.recorder._active_runs and self.recorder._active_runs[-1] == self.run_id:
            self.recorder._active_runs.pop()
        return False

    def span(
        self,
        name: str,
        *,
        kind: str = "tool",
        external_id: Optional[str] = None,
        input_ref: Optional[str] = None,
        workflow_node_id: Optional[str] = None,
        agent_identity_id: Optional[str] = None,
        usage: Optional[dict[str, Any]] = None,
        attributes: Optional[dict[str, Any]] = None,
        raw_ref: Optional[str] = None,
    ) -> SpanHandle:
        parent_span_id = self._span_stack[-1] if self._span_stack else self.root_span_id
        return SpanHandle(
            recorder=self.recorder,
            run=self,
            span_id=self.recorder._new_id("span", name),
            name=name,
            kind=kind,
            parent_span_id=parent_span_id,
            workflow_node_id=workflow_node_id or self.workflow_node_id,
            agent_identity_id=agent_identity_id or self.agent_identity_id,
            started_at=utc_now(),
            external_id=external_id,
            input_ref=input_ref,
            usage=usage or {},
            attributes=attributes or {},
            raw_ref=raw_ref,
        )

    def finish(
        self,
        *,
        status: str = "succeeded",
        output_ref: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> None:
        if self.ended_at is not None:
            return
        self.status = status
        self.ended_at = utc_now()
        if output_ref is not None:
            self.output_ref = output_ref
        if summary is not None:
            self.summary = summary
        self._finish_root_span(status=status)
        self.recorder._runs.append(self._to_payload())

    def fail(self, exc: BaseException, *, output_ref: Optional[str] = None) -> None:
        if self.ended_at is not None:
            return
        self.status = "failed"
        self.ended_at = utc_now()
        if output_ref is not None:
            self.output_ref = output_ref
        self.metadata.setdefault("error_type", exc.__class__.__name__)
        self.metadata.setdefault("error_message", str(exc))
        root_span = getattr(self, "_root_span", None)
        if root_span is not None:
            root_span.attributes.setdefault("error_type", exc.__class__.__name__)
            root_span.attributes.setdefault("error_message", str(exc))
        self._finish_root_span(status="failed")
        self.recorder._runs.append(self._to_payload())

    def _finish_root_span(self, *, status: str) -> None:
        root_span = getattr(self, "_root_span", None)
        if root_span is not None and root_span.ended_at is None:
            root_span.finish(status=status, output_ref=self.output_ref)

    def _to_payload(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "profile_id": self.recorder.profile_id,
            "source_id": self.recorder.source_id,
            "external_id": self.external_id,
            "root_span_id": self.root_span_id,
            "agent_identity_id": self.agent_identity_id,
            "task_attempt_id": None,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "input_ref": self.input_ref,
            "output_ref": self.output_ref,
            "summary": self.summary,
            "metadata_json": self.metadata,
        }


class KyokoRecorder:
    def __init__(
        self,
        *,
        profile_id: str,
        profile_name: str,
        root_path: str,
        source_id: Optional[str] = None,
        source_kind: str = "kyoko_sdk",
        source_name: str = "Kyoko SDK",
        agent_id: Optional[str] = None,
        agent_name: str = "agent",
        agent_kind: str = "agent",
        agent_role: Optional[str] = None,
        model: Optional[str] = None,
        adapter_version: str = "kyoko.python_sdk.v0",
    ) -> None:
        now = utc_now()
        self.profile_id = profile_id
        self.profile_name = profile_name
        self.root_path = root_path
        self.source_id = source_id or f"source_{_slug(source_kind)}_{_short_id()}"
        self.source_kind = source_kind
        self.source_name = source_name
        self.agent_id = agent_id or f"agent_{_slug(agent_name)}_{_short_id()}"
        self.agent_name = agent_name
        self.agent_kind = agent_kind
        self.agent_role = agent_role
        self.model = model
        self.adapter_version = adapter_version
        self.created_at = now
        self.updated_at = now
        self._workflow_node_id = f"node_{_slug(agent_name)}_{_short_id()}"
        self._runs: list[dict[str, Any]] = []
        self._spans: list[dict[str, Any]] = []
        self._active_runs: list[str] = []

    def run(
        self,
        name: str,
        *,
        external_id: Optional[str] = None,
        input_ref: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> RunHandle:
        return RunHandle(
            recorder=self,
            run_id=self._new_id("run", name),
            name=name,
            started_at=utc_now(),
            agent_identity_id=self.agent_id,
            workflow_node_id=self._workflow_node_id,
            external_id=external_id,
            input_ref=input_ref,
            metadata=metadata or {},
        )

    def to_source_events(self) -> dict[str, Any]:
        return {
            "fixture_version": "kyoko.source_events.v1",
            "name": f"{self.profile_id}-sdk-events",
            "description": "Source events recorded with the Kyoko Python SDK.",
            "profile": {
                "id": self.profile_id,
                "name": self.profile_name,
                "root_path": self.root_path,
                "status": "active",
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            },
            "sources": [
                {
                    "id": self.source_id,
                    "profile_id": self.profile_id,
                    "kind": self.source_kind,
                    "display_name": self.source_name,
                    "status": "active",
                    "adapter_version": self.adapter_version,
                    "config_json": {},
                    "capabilities_json": {"runs": True, "spans": True},
                    "last_seen_at": utc_now(),
                }
            ],
            "agent_identities": [
                {
                    "id": self.agent_id,
                    "profile_id": self.profile_id,
                    "source_id": self.source_id,
                    "external_id": self.agent_name,
                    "name": self.agent_name,
                    "kind": self.agent_kind,
                    "role": self.agent_role,
                    "model": self.model,
                    "workspace_path": self.root_path,
                    "metadata_json": {},
                }
            ],
            "workflow_nodes": [
                {
                    "id": self._workflow_node_id,
                    "profile_id": self.profile_id,
                    "source_id": self.source_id,
                    "external_id": self.agent_name,
                    "agent_identity_id": self.agent_id,
                    "kind": "agent",
                    "name": self.agent_name,
                    "metadata_json": {},
                }
            ],
            "queues": [],
            "tasks": [],
            "task_attempts": [],
            "runs": list(self._runs),
            "spans": self._ordered_spans(),
            "handoffs": [],
            "timeline_events": self._timeline_events(),
        }

    def write_json(self, output_path: Path | str) -> dict[str, Any]:
        payload = self.to_source_events()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return payload

    def _timeline_events(self) -> list[dict[str, Any]]:
        events = []
        for span in self._spans:
            if span["status"] != "failed":
                continue
            events.append(
                {
                    "id": f"event_{span['id']}_failed",
                    "profile_id": self.profile_id,
                    "source_id": self.source_id,
                    "entity_type": "span",
                    "entity_id": span["id"],
                    "kind": "span_failed",
                    "at": span["ended_at"] or utc_now(),
                    "agent_identity_id": span["agent_identity_id"],
                    "payload_ref": span["output_ref"],
                    "metadata_json": span["attributes_json"],
                }
            )
        return events

    def _ordered_spans(self) -> list[dict[str, Any]]:
        remaining = {span["id"]: span for span in self._spans}
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

    def _new_id(self, prefix: str, name: str) -> str:
        return f"{prefix}_{_slug(name)}_{_short_id()}"


class KyokoClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8765") -> None:
        self.base_url = base_url.rstrip("/")

    def ingest(
        self,
        source_events: dict[str, Any],
        *,
        timeout_seconds: int = 10,
        strict: bool = False,
    ) -> dict[str, Any]:
        """POST a source-events fixture to a running local Kyoko server.

        By default this is best-effort: if the server is not running (the most
        common first-run case), it does not raise into the calling agent. It
        prints a one-line hint to stderr and returns
        ``{"delivered": False, "unreachable": True, ...}`` so telemetry never
        crashes the workflow it is observing. Pass ``strict=True`` to raise on an
        unreachable server instead.

        A reachable server that rejects the payload (an HTTP error) always
        raises, regardless of ``strict`` -- that is a real data problem worth
        surfacing, not a missing viewer.
        """
        body = json.dumps(source_events).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/ingest",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
                result.setdefault("delivered", True)
                return result
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise KyokoSdkError(f"kyoko_ingest_failed:{exc.code}:{detail}") from exc
        except urllib.error.URLError as exc:
            if strict:
                raise KyokoSdkError(f"kyoko_ingest_unreachable:{exc.reason}") from exc
            print(
                f"kyoko: telemetry not delivered -- no server reachable at {self.base_url} "
                f"({exc.reason}). Start `kyoko serve` to view live, or write events to a "
                f"file and run `kyoko ingest` offline.",
                file=sys.stderr,
            )
            return {"delivered": False, "unreachable": True, "detail": str(exc.reason)}


def _slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value)
    return "_".join(part for part in slug.split("_") if part) or "item"


def _short_id() -> str:
    return uuid.uuid4().hex[:10]
