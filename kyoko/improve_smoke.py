from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from .autonomy import update_autonomy_policy
from .improve import ImproveError, ImproveReport, run_improvement_loop
from .integration_smoke import (
    IntegrationSmokeError,
    SourceAdapterSmokeReport,
    run_source_adapter_smoke,
)
from .replay_adapters import ReplayAdapterError, ReplayAdapterRegisterReport, register_replay_adapter
from .replay_templates import recommended_replay_server_filename, write_replay_server_template
from .source_templates import recommended_source_adapter_filename, write_source_adapter_template
from .storage import StorageError, get_database_status, initialize_database, status_to_json


DEFAULT_IMPROVE_SMOKE_FRAMEWORK = "generic-python"
DEFAULT_IMPROVE_SMOKE_PROFILE_ID = "profile_framework_improve_smoke"
DEFAULT_IMPROVE_SMOKE_PROFILE_NAME = "Framework Improve Smoke"
DEFAULT_IMPROVE_SMOKE_SOURCE_ID = "source_framework_improve_smoke"
DEFAULT_IMPROVE_SMOKE_AGENT_ID = "agent_framework_improve_smoke"
DEFAULT_IMPROVE_SMOKE_AGENT_NAME = "framework-researcher"
DEFAULT_IMPROVE_SMOKE_ADAPTER_ID = "framework_improve_smoke_replay"


class ImproveSmokeError(Exception):
    """Raised when the generated adapter improvement smoke cannot complete."""


@dataclass(frozen=True)
class ImproveSmokeReport:
    framework: str
    db_path: Path
    output_dir: Path
    workspace_root: Path
    source_adapter_path: Path
    source_hook_path: Path
    replay_server_path: Path
    replay_hook_path: Path
    replay_server_url: str
    replay_adapter_id: str
    source_smoke: SourceAdapterSmokeReport
    replay_adapter: ReplayAdapterRegisterReport
    improve: ImproveReport
    status: dict[str, object]
    passed: bool

    def to_json(self) -> dict[str, object]:
        return {
            "kind": "improve_smoke",
            "framework": self.framework,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "workspace_root": str(self.workspace_root),
            "source_adapter_path": str(self.source_adapter_path),
            "source_hook_path": str(self.source_hook_path),
            "replay_server_path": str(self.replay_server_path),
            "replay_hook_path": str(self.replay_hook_path),
            "replay_server_url": self.replay_server_url,
            "replay_adapter_id": self.replay_adapter_id,
            "source_smoke": self.source_smoke.to_json(),
            "replay_adapter": _replay_adapter_json(self.replay_adapter),
            "improve": self.improve.to_json(),
            "status": self.status,
            "passed": self.passed,
            "live_operator_invoked": False,
            "external_model_invoked": False,
            "generated_source_adapter_invoked": True,
            "managed_replay_server_invoked": True,
        }


def run_generated_improve_smoke(
    *,
    db_path: Path,
    output_dir: Optional[Path] = None,
    framework: str = DEFAULT_IMPROVE_SMOKE_FRAMEWORK,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> ImproveSmokeReport:
    if timeout_seconds <= 0:
        raise ImproveSmokeError("timeout_seconds_must_be_positive")

    initialize_database(db_path)
    selected_output_dir = output_dir or Path(tempfile.mkdtemp(prefix="kyoko-improve-smoke-"))
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = selected_output_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    source_adapter_path = selected_output_dir / "source" / recommended_source_adapter_filename(framework)
    replay_server_path = selected_output_dir / "replay" / recommended_replay_server_filename(framework)
    source_hook_path = selected_output_dir / "hooks" / "source_hook.py"
    replay_hook_path = selected_output_dir / "hooks" / "replay_hook.py"
    source_output_dir = selected_output_dir / "source-smoke"
    replay_output_dir = selected_output_dir / "replay-runs"
    improve_output_dir = selected_output_dir / "improve"
    port = _free_port()
    server_url = f"http://127.0.0.1:{port}"

    try:
        write_source_adapter_template(
            output_path=source_adapter_path,
            framework=framework,
            profile_name=DEFAULT_IMPROVE_SMOKE_PROFILE_NAME,
            force=True,
        )
        write_replay_server_template(
            output_path=replay_server_path,
            framework=framework,
            profile_name=DEFAULT_IMPROVE_SMOKE_PROFILE_NAME,
            force=True,
        )
        _write_source_hook(source_hook_path, framework=framework)
        _write_replay_hook(replay_hook_path, framework=framework)
        source_smoke = run_source_adapter_smoke(
            db_path=db_path,
            adapter_path=source_adapter_path,
            hook=f"{source_hook_path}:collect",
            output_dir=source_output_dir,
            profile_id=DEFAULT_IMPROVE_SMOKE_PROFILE_ID,
            profile_name=DEFAULT_IMPROVE_SMOKE_PROFILE_NAME,
            root_path=workspace_root,
            source_id=DEFAULT_IMPROVE_SMOKE_SOURCE_ID,
            agent_id=DEFAULT_IMPROVE_SMOKE_AGENT_ID,
            agent_name=DEFAULT_IMPROVE_SMOKE_AGENT_NAME,
            timeout_seconds=timeout_seconds,
        )
        replay_adapter = register_replay_adapter(
            db_path=db_path,
            adapter_id=DEFAULT_IMPROVE_SMOKE_ADAPTER_ID,
            name="Generated framework improve smoke replay",
            command=[sys.executable, str(replay_server_path), "--port", str(port)],
            server_url=server_url,
            output_dir=replay_output_dir,
            profile_id=source_smoke.profile_id,
            default_side_effect_mode="network_mocked",
            timeout_seconds=timeout_seconds,
            startup_timeout_seconds=min(timeout_seconds, 15),
        )
        update_autonomy_policy(
            db_path=db_path,
            profile_id=source_smoke.profile_id,
            context_mode="autonomous",
        )
        with _temporary_env("KYOKO_REPLAY_HOOK", f"{replay_hook_path}:replay"):
            improve = run_improvement_loop(
                db_path=db_path,
                output_dir=improve_output_dir,
                operator="mock",
                profile_id=source_smoke.profile_id,
                schema_path=schema_path,
                replay_adapter_id=replay_adapter.adapter_id,
                replay_output_dir=replay_output_dir,
                replay_timeout_seconds=timeout_seconds,
                run_autonomy_after=True,
            )
    except (
        ImproveError,
        IntegrationSmokeError,
        ReplayAdapterError,
        StorageError,
        OSError,
    ) as exc:
        raise ImproveSmokeError(str(exc)) from exc

    status = status_to_json(get_database_status(db_path))
    return ImproveSmokeReport(
        framework=framework,
        db_path=db_path,
        output_dir=selected_output_dir,
        workspace_root=workspace_root,
        source_adapter_path=source_adapter_path,
        source_hook_path=source_hook_path,
        replay_server_path=replay_server_path,
        replay_hook_path=replay_hook_path,
        replay_server_url=server_url,
        replay_adapter_id=replay_adapter.adapter_id,
        source_smoke=source_smoke,
        replay_adapter=replay_adapter,
        improve=improve,
        status=status,
        passed=_improve_smoke_passed(improve),
    )


def _write_source_hook(path: Path, *, framework: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        SOURCE_HOOK_TEMPLATE.replace("__FRAMEWORK__", framework),
        encoding="utf-8",
    )


def _write_replay_hook(path: Path, *, framework: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        REPLAY_HOOK_TEMPLATE.replace("__FRAMEWORK__", framework),
        encoding="utf-8",
    )


def _improve_smoke_passed(report: ImproveReport) -> bool:
    if not report.replay_runs:
        return False
    if not report.autonomy or not report.autonomy.decisions:
        return False
    replay_passed = all(
        replay.get("status") == "passed"
        and isinstance(replay.get("eval_run"), dict)
        and replay["eval_run"].get("status") == "passed"
        for replay in report.replay_runs
    )
    applied = any(decision.action == "applied" for decision in report.autonomy.decisions)
    return replay_passed and applied


def _replay_adapter_json(report: ReplayAdapterRegisterReport) -> dict[str, object]:
    return {
        "adapter_id": report.adapter_id,
        "profile_id": report.profile_id,
        "name": report.name,
        "kind": report.adapter_kind,
        "command": list(report.command),
        "server_url": report.server_url,
        "health_path": report.health_path,
        "replay_path": report.replay_path,
        "startup_timeout_seconds": report.startup_timeout_seconds,
        "cwd": report.cwd,
        "output_dir": report.output_dir,
        "default_mode": report.default_mode,
        "default_side_effect_mode": report.default_side_effect_mode,
        "timeout_seconds": report.timeout_seconds,
        "enabled": report.enabled,
    }


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def _temporary_env(name: str, value: str) -> Iterator[None]:
    previous = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


SOURCE_HOOK_TEMPLATE = r'''
from __future__ import annotations

from typing import Any


FRAMEWORK = "__FRAMEWORK__"


def collect(context: dict[str, Any]) -> dict[str, Any]:
    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    agent_id = context["agent_id"]
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": f"{FRAMEWORK} improve smoke source",
                "status": "active",
                "adapter_version": "kyoko.improve_smoke.source.v0",
                "config_json": {"smoke": True},
                "capabilities_json": {"runs": True, "spans": True, "replay": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": context["agent_name"],
                "name": context["agent_name"],
                "kind": "agent",
                "role": "researcher",
                "model": None,
                "workspace_path": context["root_path"],
                "metadata_json": {"framework": context["framework"], "smoke": True},
            }
        ],
        "workflow_nodes": [
            {
                "id": "node_framework_improve_smoke_research",
                "profile_id": profile_id,
                "source_id": source_id,
                "agent_identity_id": agent_id,
                "external_id": "research",
                "name": "research",
                "kind": "agent",
                "parent_node_id": None,
                "metadata_json": {"framework": context["framework"]},
            }
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": "run_framework_improve_smoke_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "framework-improve-smoke-001",
                "root_span_id": "span_framework_improve_smoke_root_001",
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": "research a topic", "kind": "agent_prompt"},
                "output_ref": None,
                "output_payload": {"content": "fetch timed out", "kind": "agent_error"},
                "summary": "Generated framework smoke run failed on a fetch timeout.",
                "metadata_json": {"smoke": True},
            }
        ],
        "spans": [
            {
                "id": "span_framework_improve_smoke_root_001",
                "run_id": "run_framework_improve_smoke_001",
                "source_id": source_id,
                "external_id": "framework-root",
                "parent_span_id": None,
                "workflow_node_id": "node_framework_improve_smoke_research",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "research",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": "research a topic", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": "call fetch_source", "kind": "span_output"},
                "usage_json": {},
                "attributes_json": {"smoke": True},
                "raw_ref": None,
            },
            {
                "id": "span_framework_fetch_timeout_001",
                "run_id": "run_framework_improve_smoke_001",
                "source_id": source_id,
                "external_id": "fetch-timeout",
                "parent_span_id": "span_framework_improve_smoke_root_001",
                "workflow_node_id": "node_framework_improve_smoke_research",
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework smoke"}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": "fetch_source timed out", "kind": "tool_error"},
                "usage_json": {},
                "attributes_json": {"error_type": "timeout", "smoke": True},
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [],
    }
'''.lstrip()


REPLAY_HOOK_TEMPLATE = r'''
from __future__ import annotations

from typing import Any


FRAMEWORK = "__FRAMEWORK__"


def replay(request: dict[str, Any]) -> dict[str, Any]:
    target = request["input"]["eval_spec"]["target"]
    source_span_id = target["entity_id"]
    output_span_id = "span_framework_fetch_retry_success_001"
    side_effect_mode = request["side_effect_mode"]
    return {
        "status": "passed",
        "output_run_id": "run_framework_improve_smoke_replay_001",
        "actual_side_effect_mode": side_effect_mode,
        "target_map": {source_span_id: output_span_id},
        "source_events": _source_events(
            profile_id=request["profile_id"],
            output_span_id=output_span_id,
            framework=FRAMEWORK,
        ),
        "note": "Generated framework smoke replay retried the failed fetch under mocked network behavior.",
    }


def _source_events(*, profile_id: str, output_span_id: str, framework: str) -> dict[str, Any]:
    now = "2026-01-01T00:01:00Z"
    source_id = "source_framework_improve_smoke_replay"
    agent_id = "agent_framework_improve_smoke"
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": "Framework Improve Smoke",
            "root_path": ".",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": framework,
                "display_name": f"{framework} improve smoke replay",
                "status": "active",
                "adapter_version": "kyoko.improve_smoke.replay.v0",
                "config_json": {"smoke": True},
                "capabilities_json": {"runs": True, "spans": True, "replay": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "framework-researcher",
                "name": "framework-researcher",
                "kind": "agent",
                "role": "researcher",
                "model": None,
                "workspace_path": ".",
                "metadata_json": {"framework": framework, "smoke": True},
            }
        ],
        "workflow_nodes": [
            {
                "id": "node_framework_improve_smoke_research",
                "profile_id": profile_id,
                "source_id": source_id,
                "agent_identity_id": agent_id,
                "external_id": "research",
                "name": "research",
                "kind": "agent",
                "parent_node_id": None,
                "metadata_json": {"framework": framework},
            }
        ],
        "runs": [
            {
                "id": "run_framework_improve_smoke_replay_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "framework-improve-smoke-replay-001",
                "root_span_id": "span_framework_improve_smoke_replay_root_001",
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": "research a topic", "kind": "agent_prompt"},
                "output_ref": None,
                "output_payload": {"content": "fetch succeeded after retry", "kind": "agent_output"},
                "summary": "Generated framework smoke replay succeeded after retry.",
                "metadata_json": {"smoke": True},
            }
        ],
        "spans": [
            {
                "id": "span_framework_improve_smoke_replay_root_001",
                "run_id": "run_framework_improve_smoke_replay_001",
                "source_id": source_id,
                "external_id": "framework-replay-root",
                "parent_span_id": None,
                "workflow_node_id": "node_framework_improve_smoke_research",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "research",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": "research a topic", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": "call fetch_source with retry", "kind": "span_output"},
                "usage_json": {},
                "attributes_json": {"smoke": True},
                "raw_ref": None,
            },
            {
                "id": output_span_id,
                "run_id": "run_framework_improve_smoke_replay_001",
                "source_id": source_id,
                "external_id": "fetch-retry-success",
                "parent_span_id": "span_framework_improve_smoke_replay_root_001",
                "workflow_node_id": "node_framework_improve_smoke_research",
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework smoke"}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": "source fetched after retry", "kind": "tool_output"},
                "usage_json": {},
                "attributes_json": {"retry_count": 1, "smoke": True},
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [],
    }
'''.lstrip()
