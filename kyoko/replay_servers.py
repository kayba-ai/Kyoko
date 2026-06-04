from __future__ import annotations

import json
import os
import ipaddress
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib import error, parse, request

from .evals import (
    EvalError,
    EvalRunReport,
    ReplayCompletionReport,
    _artifact_ref,
    _merge_replay_artifacts,
    build_replay_request,
    complete_replay_from_server_response,
    create_replay_run,
    mark_replay_errored,
    run_eval,
)
from .storage import initialize_database


DEFAULT_HEALTH_PATH = "/health"
DEFAULT_REPLAY_PATH = "/replay"
DEFAULT_LOG_MAX_BYTES = 40000
MAX_LOG_MAX_BYTES = 200000


class ReplayServerError(Exception):
    """Raised when an HTTP replay server cannot be used."""


@dataclass(frozen=True)
class ReplayServerHealthReport:
    server_url: str
    health_path: str
    ok: bool
    response: dict[str, Any]


@dataclass(frozen=True)
class ReplayServerRunReport:
    replay_run_id: str
    profile_id: str
    eval_spec_id: str
    server_url: str
    replay_path: str
    request: dict[str, Any]
    response: dict[str, Any]
    health: Optional[ReplayServerHealthReport]
    completion: ReplayCompletionReport
    eval_run: Optional[EvalRunReport]


@dataclass(frozen=True)
class ManagedReplayServerRunReport:
    replay_run_id: str
    profile_id: str
    eval_spec_id: str
    server_url: str
    replay_path: str
    request: dict[str, Any]
    response: dict[str, Any]
    health: ReplayServerHealthReport
    completion: ReplayCompletionReport
    eval_run: Optional[EvalRunReport]
    command: tuple[str, ...]
    stdout_path: Path
    stderr_path: Path
    exit_code: Optional[int]


@dataclass(frozen=True)
class ReplayServerProcessReport:
    server_url: str
    health_path: str
    command: tuple[str, ...]
    output_dir: Path
    state_path: Path
    stdout_path: Path
    stderr_path: Path
    pid: Optional[int]
    running: bool
    healthy: bool
    started: bool
    stopped: bool
    health: Optional[ReplayServerHealthReport]
    error: Optional[str]


@dataclass(frozen=True)
class ReplayServerProcessLogsReport:
    output_dir: Path
    stdout_path: Path
    stderr_path: Path
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    max_bytes: int


def check_replay_server_health(
    *,
    server_url: str,
    health_path: str = DEFAULT_HEALTH_PATH,
    timeout_seconds: int = 10,
    allow_remote_server: bool = False,
) -> ReplayServerHealthReport:
    _validate_timeout(timeout_seconds)
    normalized_server_url = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )
    url = _join_url(
        normalized_server_url,
        health_path,
        allow_remote_server=allow_remote_server,
    )
    response = _request_json("GET", url, None, timeout_seconds)
    ok = bool(response.get("ok", False))
    if not ok:
        raise ReplayServerError(f"replay_server_unhealthy:{url}")
    return ReplayServerHealthReport(
        server_url=normalized_server_url,
        health_path=health_path,
        ok=ok,
        response=response,
    )


def start_replay_server_process(
    *,
    command: Sequence[str],
    server_url: str,
    output_dir: Path,
    health_path: str = DEFAULT_HEALTH_PATH,
    startup_timeout_seconds: int = 15,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    allow_remote_server: bool = False,
) -> ReplayServerProcessReport:
    _validate_command(command)
    _validate_timeout(startup_timeout_seconds)
    normalized_server_url = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )
    paths = _process_paths(output_dir)

    current = _process_report_from_state(
        server_url=normalized_server_url,
        health_path=health_path,
        output_dir=output_dir,
        allow_remote_server=allow_remote_server,
    )
    if current.running and current.healthy:
        return current

    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_file = paths["stdout_path"].open("a")
    stderr_file = paths["stderr_path"].open("a")
    try:
        try:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ReplayServerError(f"replay_server_command_not_found:{command[0]}") from exc
    finally:
        stdout_file.close()
        stderr_file.close()

    state = {
        "server_url": normalized_server_url,
        "health_path": health_path,
        "command": list(command),
        "cwd": str(cwd) if cwd is not None else None,
        "pid": process.pid,
        "stdout_path": str(paths["stdout_path"]),
        "stderr_path": str(paths["stderr_path"]),
        "started_at": time.time(),
    }
    _write_state(paths["state_path"], state)
    try:
        health = _wait_for_health(
            process=process,
            server_url=normalized_server_url,
            health_path=health_path,
            startup_timeout_seconds=startup_timeout_seconds,
            allow_remote_server=allow_remote_server,
        )
    except ReplayServerError:
        _stop_process(process)
        _write_state(paths["state_path"], {**state, "last_error": "health_check_failed"})
        raise
    _detach_process(process)

    return ReplayServerProcessReport(
        server_url=normalized_server_url,
        health_path=health_path,
        command=tuple(command),
        output_dir=output_dir,
        state_path=paths["state_path"],
        stdout_path=paths["stdout_path"],
        stderr_path=paths["stderr_path"],
        pid=process.pid,
        running=True,
        healthy=True,
        started=True,
        stopped=False,
        health=health,
        error=None,
    )


def replay_server_process_status(
    *,
    server_url: str,
    output_dir: Path,
    health_path: str = DEFAULT_HEALTH_PATH,
    allow_remote_server: bool = False,
) -> ReplayServerProcessReport:
    normalized_server_url = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )
    return _process_report_from_state(
        server_url=normalized_server_url,
        health_path=health_path,
        output_dir=output_dir,
        allow_remote_server=allow_remote_server,
    )


def read_replay_server_process_logs(
    *,
    output_dir: Path,
    max_bytes: int = DEFAULT_LOG_MAX_BYTES,
) -> ReplayServerProcessLogsReport:
    selected_max_bytes = _validate_log_max_bytes(max_bytes)
    paths = _process_paths(output_dir)
    stdout, stdout_truncated = _read_tail_text(paths["stdout_path"], selected_max_bytes)
    stderr, stderr_truncated = _read_tail_text(paths["stderr_path"], selected_max_bytes)
    return ReplayServerProcessLogsReport(
        output_dir=output_dir,
        stdout_path=paths["stdout_path"],
        stderr_path=paths["stderr_path"],
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        max_bytes=selected_max_bytes,
    )


def stop_replay_server_process(
    *,
    server_url: str,
    output_dir: Path,
    health_path: str = DEFAULT_HEALTH_PATH,
    timeout_seconds: int = 5,
    allow_remote_server: bool = False,
) -> ReplayServerProcessReport:
    _validate_timeout(timeout_seconds)
    normalized_server_url = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )
    paths = _process_paths(output_dir)
    state = _read_state(paths["state_path"])
    pid = _state_pid(state)
    command = _state_command(state)
    if pid is None or not _pid_running(pid):
        return ReplayServerProcessReport(
            server_url=normalized_server_url,
            health_path=health_path,
            command=tuple(command),
            output_dir=output_dir,
            state_path=paths["state_path"],
            stdout_path=paths["stdout_path"],
            stderr_path=paths["stderr_path"],
            pid=pid,
            running=False,
            healthy=False,
            started=False,
            stopped=False,
            health=None,
            error=None if pid is None else "process_not_running",
        )

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _pid_running(pid):
            _write_state(paths["state_path"], {**state, "stopped_at": time.time()})
            return ReplayServerProcessReport(
                server_url=normalized_server_url,
                health_path=health_path,
                command=tuple(command),
                output_dir=output_dir,
                state_path=paths["state_path"],
                stdout_path=paths["stdout_path"],
                stderr_path=paths["stderr_path"],
                pid=pid,
                running=False,
                healthy=False,
                started=False,
                stopped=True,
                health=None,
                error=None,
            )
        time.sleep(0.1)

    os.kill(pid, signal.SIGKILL)
    while _pid_running(pid):
        time.sleep(0.1)
    _write_state(paths["state_path"], {**state, "stopped_at": time.time(), "forced": True})
    return ReplayServerProcessReport(
        server_url=normalized_server_url,
        health_path=health_path,
        command=tuple(command),
        output_dir=output_dir,
        state_path=paths["state_path"],
        stdout_path=paths["stdout_path"],
        stderr_path=paths["stderr_path"],
        pid=pid,
        running=False,
        healthy=False,
        started=False,
        stopped=True,
        health=None,
        error="forced_kill",
    )


def run_managed_replay_server(
    *,
    db_path: Path,
    eval_spec_id: str,
    command: Sequence[str],
    server_url: str,
    output_dir: Path,
    health_path: str = DEFAULT_HEALTH_PATH,
    replay_path: str = DEFAULT_REPLAY_PATH,
    mode: str = "dry_run",
    side_effect_mode: Optional[str] = None,
    source_run_id: Optional[str] = None,
    timeout_seconds: int = 120,
    startup_timeout_seconds: int = 15,
    trace_endpoint: Optional[str] = None,
    cwd: Optional[Path] = None,
    run_eval_after: bool = False,
    allow_remote_server: bool = False,
) -> ManagedReplayServerRunReport:
    initialize_database(db_path)
    _validate_command(command)
    _validate_timeout(timeout_seconds)
    _validate_timeout(startup_timeout_seconds)

    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "replay-server-stdout.txt"
    stderr_path = output_dir / "replay-server-stderr.txt"
    normalized_server_url = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )

    stdout_file = stdout_path.open("w")
    stderr_file = stderr_path.open("w")
    process: Optional[subprocess.Popen[str]] = None
    health: Optional[ReplayServerHealthReport] = None
    report: Optional[ReplayServerRunReport] = None
    try:
        try:
            process = subprocess.Popen(
                list(command),
                cwd=str(cwd) if cwd is not None else None,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ReplayServerError(f"replay_server_command_not_found:{command[0]}") from exc

        health = _wait_for_health(
            process=process,
            server_url=normalized_server_url,
            health_path=health_path,
            startup_timeout_seconds=startup_timeout_seconds,
            allow_remote_server=allow_remote_server,
        )
        report = run_replay_server(
            db_path=db_path,
            eval_spec_id=eval_spec_id,
            server_url=normalized_server_url,
            health_path=health_path,
            replay_path=replay_path,
            mode=mode,
            side_effect_mode=side_effect_mode,
            source_run_id=source_run_id,
            timeout_seconds=timeout_seconds,
            trace_endpoint=trace_endpoint,
            check_health=True,
            run_eval_after=run_eval_after,
            allow_remote_server=allow_remote_server,
        )
    finally:
        exit_code = _stop_process(process) if process is not None else None
        stdout_file.close()
        stderr_file.close()

    if report is None or health is None:
        raise ReplayServerError("managed_replay_server_run_failed")
    _merge_replay_artifacts(
        db_path=db_path,
        replay_run_id=report.replay_run_id,
        artifacts=[
            _artifact_ref("replay_server_stdout", stdout_path, "text/plain"),
            _artifact_ref("replay_server_stderr", stderr_path, "text/plain"),
        ],
    )
    return ManagedReplayServerRunReport(
        replay_run_id=report.replay_run_id,
        profile_id=report.profile_id,
        eval_spec_id=report.eval_spec_id,
        server_url=report.server_url,
        replay_path=report.replay_path,
        request=report.request,
        response=report.response,
        health=health,
        completion=report.completion,
        eval_run=report.eval_run,
        command=tuple(command),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        exit_code=exit_code,
    )


def run_replay_server(
    *,
    db_path: Path,
    eval_spec_id: str,
    server_url: str,
    health_path: str = DEFAULT_HEALTH_PATH,
    replay_path: str = DEFAULT_REPLAY_PATH,
    mode: str = "dry_run",
    side_effect_mode: Optional[str] = None,
    source_run_id: Optional[str] = None,
    timeout_seconds: int = 120,
    trace_endpoint: Optional[str] = None,
    check_health: bool = True,
    run_eval_after: bool = False,
    allow_remote_server: bool = False,
) -> ReplayServerRunReport:
    initialize_database(db_path)
    _validate_timeout(timeout_seconds)
    normalized_server_url = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )

    health = (
        check_replay_server_health(
            server_url=normalized_server_url,
            health_path=health_path,
            timeout_seconds=min(timeout_seconds, 10),
            allow_remote_server=allow_remote_server,
        )
        if check_health
        else None
    )

    replay = create_replay_run(
        db_path=db_path,
        eval_spec_id=eval_spec_id,
        mode=mode,
        side_effect_mode=side_effect_mode,
        source_run_id=source_run_id,
    )
    kyoko_request = build_replay_request(
        db_path=db_path,
        replay_run_id=replay.replay_run_id,
        redaction_consumer="replay:http_server",
    )
    server_request = _server_replay_request(
        kyoko_request=kyoko_request,
        server_url=normalized_server_url,
        replay_path=replay_path,
        trace_endpoint=trace_endpoint,
    )

    try:
        _validate_health_supports_replay(health=health)
        _validate_health_supports_side_effect_mode(
            health=health,
            requested_side_effect_mode=str(server_request.get("side_effect_mode") or ""),
        )
        response = _request_json(
            "POST",
            _join_url(
                normalized_server_url,
                replay_path,
                allow_remote_server=allow_remote_server,
            ),
            server_request,
            timeout_seconds,
        )
        completion = complete_replay_from_server_response(
            db_path=db_path,
            replay_run_id=replay.replay_run_id,
            response=response,
            source_label=_join_url(
                normalized_server_url,
                replay_path,
                allow_remote_server=allow_remote_server,
            ),
        )
        eval_run = (
            run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )
            if run_eval_after
            else None
        )
    except (EvalError, ReplayServerError) as exc:
        mark_replay_errored(db_path=db_path, replay_run_id=replay.replay_run_id, error=str(exc))
        raise

    return ReplayServerRunReport(
        replay_run_id=replay.replay_run_id,
        profile_id=replay.profile_id,
        eval_spec_id=eval_spec_id,
        server_url=normalized_server_url,
        replay_path=replay_path,
        request=server_request,
        response=response,
        health=health,
        completion=completion,
        eval_run=eval_run,
    )


def _server_replay_request(
    *,
    kyoko_request: dict[str, Any],
    server_url: str,
    replay_path: str,
    trace_endpoint: Optional[str],
) -> dict[str, Any]:
    replay_run = kyoko_request.get("replay_run", {})
    eval_spec = kyoko_request.get("eval_spec", {})
    source_run = kyoko_request.get("source_run", {})
    replay_run_id = replay_run.get("id")
    side_effect_mode = replay_run.get("side_effect_mode")
    return {
        "schema_version": "kyoko.replay_server_request.v1",
        "replay_run_id": replay_run_id,
        "source_run_id": replay_run.get("source_run_id") or source_run.get("id"),
        "eval_spec_id": eval_spec.get("id"),
        "profile_id": replay_run.get("profile_id") or kyoko_request.get("profile_id"),
        "side_effect_mode": side_effect_mode,
        "trace_endpoint": trace_endpoint,
        "idempotency_key": replay_run_id,
        "input": {
            "source_run": source_run,
            "source_spans": kyoko_request.get("source_spans", []),
            "handoffs": kyoko_request.get("handoffs", []),
            "eval_spec": eval_spec,
        },
        "kyoko_request": kyoko_request,
        "metadata": {
            "server_url": server_url,
            "replay_path": replay_path,
        },
    }


def _validate_health_supports_side_effect_mode(
    *,
    health: Optional[ReplayServerHealthReport],
    requested_side_effect_mode: str,
) -> None:
    if health is None:
        return
    raw_modes = health.response.get("side_effect_modes")
    if raw_modes is None:
        return
    if not isinstance(raw_modes, list) or any(not isinstance(mode, str) for mode in raw_modes):
        raise ReplayServerError("replay_server_health_side_effect_modes_invalid")
    supported_modes = set(raw_modes)
    if requested_side_effect_mode not in supported_modes:
        supported = ",".join(sorted(supported_modes)) if supported_modes else "none"
        raise ReplayServerError(
            "replay_server_side_effect_mode_unsupported:"
            f"{requested_side_effect_mode}:{supported}"
        )


def _validate_health_supports_replay(*, health: Optional[ReplayServerHealthReport]) -> None:
    if health is None:
        return
    raw_capabilities = health.response.get("capabilities")
    if raw_capabilities is None:
        return
    if not isinstance(raw_capabilities, list) or any(
        not isinstance(capability, str) for capability in raw_capabilities
    ):
        raise ReplayServerError("replay_server_health_capabilities_invalid")
    if "replay" not in set(raw_capabilities):
        supported = ",".join(sorted(raw_capabilities)) if raw_capabilities else "none"
        raise ReplayServerError(f"replay_server_capability_unsupported:replay:{supported}")


def _request_json(
    method: str,
    url: str,
    payload: Optional[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ReplayServerError(f"replay_server_http_error:{exc.code}:{body}") from exc
    except error.URLError as exc:
        raise ReplayServerError(f"replay_server_unreachable:{url}:{exc.reason}") from exc
    except TimeoutError as exc:
        raise ReplayServerError(f"replay_server_timeout:{timeout_seconds}") from exc

    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReplayServerError(f"replay_server_json_invalid:{exc}") from exc
    if not isinstance(decoded, dict):
        raise ReplayServerError("replay_server_response_must_be_object")
    return decoded


def normalize_replay_server_url(
    server_url: str,
    *,
    allow_remote_server: bool = False,
) -> str:
    if not isinstance(server_url, str) or not server_url:
        raise ReplayServerError("replay_server_url_required")
    parsed = parse.urlparse(server_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReplayServerError(f"invalid_replay_server_url:{server_url}")
    if not allow_remote_server and not _is_loopback_replay_host(parsed.hostname):
        raise ReplayServerError(f"remote_replay_server_requires_opt_in:{server_url}")
    return server_url.rstrip("/")


def _join_url(
    server_url: str,
    path: str,
    *,
    allow_remote_server: bool = False,
) -> str:
    normalized = normalize_replay_server_url(
        server_url,
        allow_remote_server=allow_remote_server,
    )
    selected_path = path if path.startswith("/") else f"/{path}"
    return normalized + selected_path


def _is_loopback_replay_host(hostname: Optional[str]) -> bool:
    if not hostname:
        return False
    normalized = hostname.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _validate_timeout(timeout_seconds: int) -> None:
    if timeout_seconds <= 0:
        raise ReplayServerError("timeout_seconds_must_be_positive")


def _validate_log_max_bytes(max_bytes: int) -> int:
    if max_bytes <= 0:
        raise ReplayServerError("log_max_bytes_must_be_positive")
    if max_bytes > MAX_LOG_MAX_BYTES:
        raise ReplayServerError(f"log_max_bytes_too_large:{MAX_LOG_MAX_BYTES}")
    return max_bytes


def _read_tail_text(path: Path, max_bytes: int) -> tuple[str, bool]:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return "", False
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            return handle.read().decode("utf-8", errors="replace"), True
        return handle.read().decode("utf-8", errors="replace"), False


def _process_report_from_state(
    *,
    server_url: str,
    health_path: str,
    output_dir: Path,
    allow_remote_server: bool = False,
) -> ReplayServerProcessReport:
    paths = _process_paths(output_dir)
    state = _read_state(paths["state_path"])
    pid = _state_pid(state)
    command = _state_command(state)
    running = pid is not None and _pid_running(pid)
    health = None
    healthy = False
    error_text = None
    if running:
        try:
            health = check_replay_server_health(
                server_url=server_url,
                health_path=health_path,
                timeout_seconds=1,
                allow_remote_server=allow_remote_server,
            )
            healthy = True
        except ReplayServerError as exc:
            error_text = str(exc)
    return ReplayServerProcessReport(
        server_url=server_url,
        health_path=health_path,
        command=tuple(command),
        output_dir=output_dir,
        state_path=paths["state_path"],
        stdout_path=paths["stdout_path"],
        stderr_path=paths["stderr_path"],
        pid=pid,
        running=running,
        healthy=healthy,
        started=False,
        stopped=False,
        health=health,
        error=error_text,
    )


def _process_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "state_path": output_dir / "replay-server-state.json",
        "stdout_path": output_dir / "replay-server-stdout.txt",
        "stderr_path": output_dir / "replay-server-stderr.txt",
    }


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _state_pid(state: dict[str, Any]) -> Optional[int]:
    pid = state.get("pid")
    return int(pid) if isinstance(pid, int) and pid > 0 else None


def _state_command(state: dict[str, Any]) -> list[str]:
    command = state.get("command")
    if isinstance(command, list) and all(isinstance(part, str) for part in command):
        return command
    return []


def _pid_running(pid: int) -> bool:
    try:
        waited_pid, _status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _validate_command(command: Sequence[str]) -> None:
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ReplayServerError("replay_server_command_required")


def _wait_for_health(
    *,
    process: subprocess.Popen[str],
    server_url: str,
    health_path: str,
    startup_timeout_seconds: int,
    allow_remote_server: bool = False,
) -> ReplayServerHealthReport:
    deadline = time.monotonic() + startup_timeout_seconds
    last_error: Optional[str] = None
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            raise ReplayServerError(f"replay_server_exited_before_health:{exit_code}")
        try:
            return check_replay_server_health(
                server_url=server_url,
                health_path=health_path,
                timeout_seconds=1,
                allow_remote_server=allow_remote_server,
            )
        except ReplayServerError as exc:
            last_error = str(exc)
            time.sleep(0.2)
    suffix = f":{last_error}" if last_error else ""
    raise ReplayServerError(f"replay_server_health_timeout:{startup_timeout_seconds}{suffix}")


def _stop_process(process: subprocess.Popen[str]) -> Optional[int]:
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    try:
        return process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait(timeout=5)


def _detach_process(process: subprocess.Popen[str]) -> None:
    # Popen warns on garbage collection for intentionally long-lived children.
    # We keep the pid in state and manage shutdown explicitly through stop.
    if hasattr(process, "_child_created"):
        process._child_created = False
