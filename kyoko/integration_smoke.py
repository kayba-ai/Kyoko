from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib import error, request

from .replay_servers import (
    ReplayServerError,
    read_replay_server_process_logs,
    replay_server_process_status,
    start_replay_server_process,
    stop_replay_server_process,
)
from .storage import (
    IngestReport,
    StorageError,
    get_database_status,
    ingest_source_json,
    status_to_json,
)


class IntegrationSmokeError(Exception):
    """Raised when an integration smoke test cannot complete."""


@dataclass(frozen=True)
class SourceAdapterSmokeReport:
    db_path: Path
    adapter_path: Path
    hook: str
    output_dir: Path
    source_events_path: Path
    stdout_path: Path
    stderr_path: Path
    exit_code: int
    profile_id: str
    ingested_counts: dict[str, int]
    status: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "source_adapter",
            "db_path": str(self.db_path),
            "adapter_path": str(self.adapter_path),
            "hook": self.hook,
            "output_dir": str(self.output_dir),
            "source_events_path": str(self.source_events_path),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "exit_code": self.exit_code,
            "profile_id": self.profile_id,
            "ingested_counts": self.ingested_counts,
            "status": self.status,
        }


@dataclass(frozen=True)
class ReplayServerSmokeReport:
    command: tuple[str, ...]
    server_url: str
    health_path: str
    output_dir: Path
    state_path: Path
    stdout_path: Path
    stderr_path: Path
    pid: Optional[int]
    started: bool
    healthy: bool
    stopped: bool
    health: Optional[dict[str, Any]]
    replay_path: Optional[str]
    replay_request: Optional[dict[str, Any]]
    replay_response: Optional[dict[str, Any]]
    replay_ok: bool
    logs: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "replay_server",
            "command": list(self.command),
            "server_url": self.server_url,
            "health_path": self.health_path,
            "output_dir": str(self.output_dir),
            "state_path": str(self.state_path),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "pid": self.pid,
            "started": self.started,
            "healthy": self.healthy,
            "stopped": self.stopped,
            "health": self.health,
            "replay_path": self.replay_path,
            "replay_request": self.replay_request,
            "replay_response": self.replay_response,
            "replay_ok": self.replay_ok,
            "logs": self.logs,
        }


def run_source_adapter_smoke(
    *,
    db_path: Path,
    adapter_path: Path,
    hook: str,
    output_dir: Optional[Path] = None,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    source_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    python_executable: Optional[Path] = None,
    cwd: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> SourceAdapterSmokeReport:
    if timeout_seconds <= 0:
        raise IntegrationSmokeError("timeout_seconds_must_be_positive")
    if not adapter_path.exists():
        raise IntegrationSmokeError(f"source_adapter_not_found:{adapter_path}")
    if not hook:
        raise IntegrationSmokeError("source_hook_required")

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="kyoko-source-smoke-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    source_events_path = output_dir / "source-events.json"
    stdout_path = output_dir / "source-adapter.stdout.txt"
    stderr_path = output_dir / "source-adapter.stderr.txt"

    command = _source_adapter_command(
        adapter_path,
        python_executable=python_executable,
    ) + ["--output", str(source_events_path)]
    if profile_id:
        command.extend(["--profile-id", profile_id])
    if profile_name:
        command.extend(["--profile-name", profile_name])
    if root_path is not None:
        command.extend(["--root-path", str(root_path)])
    if source_id:
        command.extend(["--source-id", source_id])
    if agent_id:
        command.extend(["--agent-id", agent_id])
    if agent_name:
        command.extend(["--agent-name", agent_name])

    env = os.environ.copy()
    env["KYOKO_SOURCE_HOOK"] = hook
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise IntegrationSmokeError(f"source_adapter_timeout:{timeout_seconds}") from exc
    except OSError as exc:
        raise IntegrationSmokeError(f"source_adapter_failed_to_start:{exc}") from exc

    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise IntegrationSmokeError(f"source_adapter_failed:{completed.returncode}:{stderr_path}")
    if not source_events_path.exists():
        raise IntegrationSmokeError(f"source_adapter_output_missing:{source_events_path}")

    try:
        ingest_report: IngestReport = ingest_source_json(db_path, source_events_path)
    except StorageError as exc:
        raise IntegrationSmokeError(str(exc)) from exc

    return SourceAdapterSmokeReport(
        db_path=db_path,
        adapter_path=adapter_path,
        hook=hook,
        output_dir=output_dir,
        source_events_path=source_events_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        exit_code=completed.returncode,
        profile_id=ingest_report.profile_id,
        ingested_counts=ingest_report.inserted_counts,
        status=status_to_json(get_database_status(db_path)),
    )


def _source_adapter_command(
    adapter_path: Path,
    *,
    python_executable: Optional[Path] = None,
) -> list[str]:
    suffix = adapter_path.suffix.lower()
    if suffix == ".py":
        executable = str(python_executable) if python_executable is not None else sys.executable
        return [executable, str(adapter_path)]
    if suffix in {".js", ".mjs", ".cjs"}:
        node = shutil.which("node")
        if node is None:
            raise IntegrationSmokeError("node_not_found_for_source_adapter")
        return [node, str(adapter_path)]
    if suffix == ".ts":
        runner = shutil.which("tsx") or shutil.which("ts-node")
        if runner is None:
            raise IntegrationSmokeError("typescript_runner_not_found_for_source_adapter:tsx_or_ts-node")
        return [runner, str(adapter_path)]
    executable = str(python_executable) if python_executable is not None else sys.executable
    return [executable, str(adapter_path)]


def run_replay_server_smoke(
    *,
    command: Sequence[str],
    server_url: str,
    output_dir: Optional[Path] = None,
    health_path: str = "/health",
    run_replay: bool = False,
    replay_path: str = "/replay",
    replay_request: Optional[dict[str, Any]] = None,
    replay_hook: Optional[str] = None,
    replay_timeout_seconds: int = 10,
    startup_timeout_seconds: int = 10,
    stop_timeout_seconds: int = 5,
    cwd: Optional[Path] = None,
    log_max_bytes: int = 40000,
) -> ReplayServerSmokeReport:
    if startup_timeout_seconds <= 0:
        raise IntegrationSmokeError("startup_timeout_seconds_must_be_positive")
    if stop_timeout_seconds <= 0:
        raise IntegrationSmokeError("stop_timeout_seconds_must_be_positive")
    if replay_timeout_seconds <= 0:
        raise IntegrationSmokeError("replay_timeout_seconds_must_be_positive")
    if not command:
        raise IntegrationSmokeError("replay_server_command_required")

    if output_dir is None:
        output_dir = Path(tempfile.mkdtemp(prefix="kyoko-replay-smoke-"))

    env = os.environ.copy()
    if replay_hook:
        env["KYOKO_REPLAY_HOOK"] = replay_hook
    selected_replay_request = (
        _default_replay_request() if run_replay and replay_request is None else replay_request
    )

    try:
        current = replay_server_process_status(
            server_url=server_url,
            health_path=health_path,
            output_dir=output_dir,
        )
        if current.running:
            raise IntegrationSmokeError(f"replay_server_smoke_output_dir_in_use:{output_dir}")
        start_report = start_replay_server_process(
            command=command,
            server_url=server_url,
            output_dir=output_dir,
            health_path=health_path,
            startup_timeout_seconds=startup_timeout_seconds,
            cwd=cwd,
            env=env if replay_hook else None,
        )
    except ReplayServerError as exc:
        raise IntegrationSmokeError(str(exc)) from exc

    replay_response: Optional[dict[str, Any]] = None
    replay_error: Optional[str] = None
    stop_report = None
    stop_error: Optional[str] = None
    try:
        if selected_replay_request is not None:
            replay_response = _post_replay_request(
                server_url=start_report.server_url,
                replay_path=replay_path,
                payload=selected_replay_request,
                timeout_seconds=replay_timeout_seconds,
            )
    except IntegrationSmokeError as exc:
        replay_error = str(exc)

    try:
        stop_report = stop_replay_server_process(
            server_url=server_url,
            output_dir=output_dir,
            health_path=health_path,
            timeout_seconds=stop_timeout_seconds,
        )
    except ReplayServerError as exc:
        stop_error = str(exc)

    try:
        logs_report = read_replay_server_process_logs(
            output_dir=output_dir,
            max_bytes=log_max_bytes,
        )
    except ReplayServerError as exc:
        raise IntegrationSmokeError(str(exc)) from exc

    if replay_error is not None:
        raise IntegrationSmokeError(replay_error)
    if stop_error is not None:
        raise IntegrationSmokeError(f"replay_server_stop_failed:{stop_error}")

    health = start_report.health
    return ReplayServerSmokeReport(
        command=tuple(command),
        server_url=start_report.server_url,
        health_path=start_report.health_path,
        output_dir=output_dir,
        state_path=start_report.state_path,
        stdout_path=start_report.stdout_path,
        stderr_path=start_report.stderr_path,
        pid=start_report.pid,
        started=start_report.started,
        healthy=start_report.healthy,
        stopped=stop_report.stopped if stop_report is not None else False,
        health={
            "server_url": health.server_url,
            "health_path": health.health_path,
            "ok": health.ok,
            "response": health.response,
        }
        if health is not None
        else None,
        replay_path=replay_path if selected_replay_request is not None else None,
        replay_request=selected_replay_request,
        replay_response=replay_response,
        replay_ok=_replay_response_ok(replay_response),
        logs={
            "stdout_path": str(logs_report.stdout_path),
            "stderr_path": str(logs_report.stderr_path),
            "stdout": logs_report.stdout,
            "stderr": logs_report.stderr,
            "stdout_truncated": logs_report.stdout_truncated,
            "stderr_truncated": logs_report.stderr_truncated,
            "max_bytes": logs_report.max_bytes,
        },
    )


def _default_replay_request() -> dict[str, Any]:
    return {
        "replay_run_id": "replay_integration_smoke_001",
        "side_effect_mode": "network_mocked",
        "profile_id": "profile_integration_smoke",
        "eval_spec_id": "eval_spec_integration_smoke",
    }


def _post_replay_request(
    *,
    server_url: str,
    replay_path: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    if not replay_path.startswith("/"):
        replay_path = f"/{replay_path}"
    url = server_url.rstrip("/") + replay_path
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    http_request = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        exc.close()
        raise IntegrationSmokeError(
            f"replay_server_replay_failed:{exc.code}:{_shorten(detail)}"
        ) from exc
    except error.URLError as exc:
        raise IntegrationSmokeError(f"replay_server_replay_failed:{exc}") from exc
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntegrationSmokeError(f"replay_server_replay_invalid_json:{_shorten(raw)}") from exc
    if not isinstance(decoded, dict):
        raise IntegrationSmokeError("replay_server_replay_response_not_object")
    if not _replay_response_ok(decoded):
        raise IntegrationSmokeError(
            f"replay_server_replay_not_passed:{_shorten(json.dumps(decoded, sort_keys=True))}"
        )
    return decoded


def _replay_response_ok(response: Optional[dict[str, Any]]) -> bool:
    if response is None:
        return False
    replay = response.get("replay")
    if isinstance(replay, dict):
        return replay.get("status") == "passed"
    return response.get("status") == "passed"


def _shorten(value: str, *, max_chars: int = 500) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...<truncated>"
