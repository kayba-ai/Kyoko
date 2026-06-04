from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .checks import (
    SAFE_REPLAY_SIDE_EFFECT_MODES,
    CheckError,
    ReplayCommandReport,
    parse_replay_command,
    run_replay_command,
)
from .replay_servers import (
    DEFAULT_HEALTH_PATH,
    DEFAULT_REPLAY_PATH,
    ManagedReplayServerRunReport,
    ReplayServerProcessReport,
    ReplayServerProcessLogsReport,
    ReplayServerRunReport,
    normalize_replay_server_url,
    replay_server_process_status,
    read_replay_server_process_logs,
    run_managed_replay_server,
    run_replay_server,
    start_replay_server_process,
    stop_replay_server_process,
)
from .storage import StorageError, connect, initialize_database, utc_now


DEFAULT_REPLAY_ARTIFACT_DIR = ".kyoko/replay-runs"


class ReplayAdapterError(Exception):
    """Raised when a registered replay adapter cannot be used."""


@dataclass(frozen=True)
class ReplayAdapterRegisterReport:
    adapter_id: str
    profile_id: str
    name: str
    adapter_kind: str
    command: tuple[str, ...]
    server_url: Optional[str]
    health_path: Optional[str]
    replay_path: Optional[str]
    startup_timeout_seconds: Optional[int]
    cwd: Optional[str]
    output_dir: Optional[str]
    default_mode: str
    default_side_effect_mode: str
    timeout_seconds: int
    enabled: bool
    allow_remote_server: bool


def register_replay_adapter(
    *,
    db_path: Path,
    adapter_id: str,
    name: str,
    command: Optional[Sequence[str]] = None,
    server_url: Optional[str] = None,
    health_path: str = DEFAULT_HEALTH_PATH,
    replay_path: str = DEFAULT_REPLAY_PATH,
    startup_timeout_seconds: int = 15,
    cwd: Optional[Path] = None,
    profile_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    default_mode: str = "dry_run",
    default_side_effect_mode: str = "network_mocked",
    timeout_seconds: int = 120,
    enabled: bool = True,
    allow_remote_server: bool = False,
    metadata: Optional[dict[str, Any]] = None,
) -> ReplayAdapterRegisterReport:
    initialize_database(db_path)
    _validate_adapter_id(adapter_id)
    adapter_kind = _adapter_kind(command=command, server_url=server_url)
    if adapter_kind in {"command", "managed_http_server"}:
        _validate_command(command)
    if adapter_kind in {"http_server", "managed_http_server"}:
        _validate_server_url(server_url, allow_remote_server=allow_remote_server)
    _validate_boundary(default_mode, default_side_effect_mode)
    if timeout_seconds <= 0:
        raise ReplayAdapterError("timeout_seconds_must_be_positive")
    if startup_timeout_seconds <= 0:
        raise ReplayAdapterError("startup_timeout_seconds_must_be_positive")

    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise ReplayAdapterError("profile_required")
        if not _row_exists(connection, "profiles", selected_profile_id):
            raise ReplayAdapterError(f"profile_not_found:{selected_profile_id}")

        now = utc_now()
        selected_metadata = dict(metadata or {})
        selected_metadata.update(
            {
                "kind": adapter_kind,
                "server_url": server_url if adapter_kind in {"http_server", "managed_http_server"} else None,
                "health_path": health_path if adapter_kind in {"http_server", "managed_http_server"} else None,
                "replay_path": replay_path if adapter_kind in {"http_server", "managed_http_server"} else None,
                "startup_timeout_seconds": startup_timeout_seconds
                if adapter_kind == "managed_http_server"
                else None,
                "cwd": str(cwd) if cwd is not None and adapter_kind == "managed_http_server" else None,
                "allow_remote_server": bool(allow_remote_server)
                if adapter_kind in {"http_server", "managed_http_server"}
                else False,
            }
        )
        connection.execute(
            """
            INSERT INTO replay_adapters (
              id,
              profile_id,
              name,
              command_json,
              output_dir,
              default_mode,
              default_side_effect_mode,
              timeout_seconds,
              enabled,
              metadata_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              profile_id = excluded.profile_id,
              name = excluded.name,
              command_json = excluded.command_json,
              output_dir = excluded.output_dir,
              default_mode = excluded.default_mode,
              default_side_effect_mode = excluded.default_side_effect_mode,
              timeout_seconds = excluded.timeout_seconds,
              enabled = excluded.enabled,
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                adapter_id,
                selected_profile_id,
                name,
                _json_dumps(list(command or [])),
                str(output_dir) if output_dir is not None else None,
                default_mode,
                default_side_effect_mode,
                timeout_seconds,
                1 if enabled else 0,
                _json_dumps(selected_metadata),
                now,
                now,
            ),
        )

    return ReplayAdapterRegisterReport(
        adapter_id=adapter_id,
        profile_id=selected_profile_id,
        name=name,
        adapter_kind=adapter_kind,
        command=tuple(command or ()),
        server_url=server_url if adapter_kind in {"http_server", "managed_http_server"} else None,
        health_path=health_path if adapter_kind in {"http_server", "managed_http_server"} else None,
        replay_path=replay_path if adapter_kind in {"http_server", "managed_http_server"} else None,
        startup_timeout_seconds=startup_timeout_seconds if adapter_kind == "managed_http_server" else None,
        cwd=str(cwd) if cwd is not None and adapter_kind == "managed_http_server" else None,
        output_dir=str(output_dir) if output_dir is not None else None,
        default_mode=default_mode,
        default_side_effect_mode=default_side_effect_mode,
        timeout_seconds=timeout_seconds,
        enabled=enabled,
        allow_remote_server=bool(allow_remote_server)
        if adapter_kind in {"http_server", "managed_http_server"}
        else False,
    )


def list_replay_adapters(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM replay_adapters
                ORDER BY created_at DESC, id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_decode_adapter(row) for row in rows]


def run_registered_replay_adapter(
    *,
    db_path: Path,
    adapter_id: str,
    check_spec_id: str,
    output_dir: Optional[Path] = None,
    mode: Optional[str] = None,
    side_effect_mode: Optional[str] = None,
    source_run_id: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    run_check_after: bool = False,
) -> ReplayCommandReport | ReplayServerRunReport | ManagedReplayServerRunReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        adapter = _get_adapter(connection, adapter_id)
        if int(adapter["enabled"]) != 1:
            raise ReplayAdapterError(f"replay_adapter_disabled:{adapter_id}")
        check_profile_id = _check_spec_profile_id(connection, check_spec_id)
        if check_profile_id != str(adapter["profile_id"]):
            raise ReplayAdapterError(f"replay_adapter_profile_mismatch:{adapter_id}:{check_spec_id}")

    metadata = _json_loads(adapter["metadata_json"], {})
    adapter_kind = _kind_from_metadata(metadata)
    allow_remote_server = _metadata_bool(metadata, "allow_remote_server", False)

    selected_mode = mode or str(adapter["default_mode"])
    selected_side_effect_mode = side_effect_mode or str(adapter["default_side_effect_mode"])
    _validate_boundary(selected_mode, selected_side_effect_mode)
    selected_timeout = timeout_seconds or int(adapter["timeout_seconds"])

    if adapter_kind == "http_server":
        server_url = metadata.get("server_url")
        if not isinstance(server_url, str) or not server_url:
            raise ReplayAdapterError(f"replay_adapter_server_url_missing:{adapter_id}")
        return run_replay_server(
            db_path=db_path,
            check_spec_id=check_spec_id,
            server_url=server_url,
            health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
            replay_path=_metadata_path(metadata, "replay_path", DEFAULT_REPLAY_PATH),
            mode=selected_mode,
            side_effect_mode=selected_side_effect_mode,
            source_run_id=source_run_id,
            timeout_seconds=selected_timeout,
            run_check_after=run_check_after,
            allow_remote_server=allow_remote_server,
        )

    if adapter_kind == "managed_http_server":
        server_url = metadata.get("server_url")
        if not isinstance(server_url, str) or not server_url:
            raise ReplayAdapterError(f"replay_adapter_server_url_missing:{adapter_id}")
        command = _json_loads(adapter["command_json"], [])
        _validate_command(command)
        server_output_dir = output_dir or _adapter_output_dir(db_path, adapter, "server")
        server_status = replay_server_process_status(
            server_url=server_url,
            output_dir=server_output_dir,
            health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
            allow_remote_server=allow_remote_server,
        )
        if server_status.running and server_status.healthy:
            return run_replay_server(
                db_path=db_path,
                check_spec_id=check_spec_id,
                server_url=server_url,
                health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
                replay_path=_metadata_path(metadata, "replay_path", DEFAULT_REPLAY_PATH),
                mode=selected_mode,
                side_effect_mode=selected_side_effect_mode,
                source_run_id=source_run_id,
                timeout_seconds=selected_timeout,
                run_check_after=run_check_after,
                allow_remote_server=allow_remote_server,
            )
        selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter, check_spec_id)
        return run_managed_replay_server(
            db_path=db_path,
            check_spec_id=check_spec_id,
            command=[str(part) for part in command],
            server_url=server_url,
            output_dir=selected_output_dir,
            health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
            replay_path=_metadata_path(metadata, "replay_path", DEFAULT_REPLAY_PATH),
            mode=selected_mode,
            side_effect_mode=selected_side_effect_mode,
            source_run_id=source_run_id,
            timeout_seconds=selected_timeout,
            startup_timeout_seconds=_metadata_int(metadata, "startup_timeout_seconds", 15),
            cwd=_metadata_path_optional(metadata, "cwd"),
            run_check_after=run_check_after,
            allow_remote_server=allow_remote_server,
        )

    command = _json_loads(adapter["command_json"], [])
    _validate_command(command)
    selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter, check_spec_id)

    return run_replay_command(
        db_path=db_path,
        check_spec_id=check_spec_id,
        output_dir=selected_output_dir,
        command=[str(part) for part in command],
        mode=selected_mode,
        side_effect_mode=selected_side_effect_mode,
        source_run_id=source_run_id,
        timeout_seconds=selected_timeout,
        run_check_after=run_check_after,
    )


def start_registered_replay_server_adapter(
    *,
    db_path: Path,
    adapter_id: str,
    output_dir: Optional[Path] = None,
) -> ReplayServerProcessReport:
    adapter, metadata = _managed_server_adapter(db_path=db_path, adapter_id=adapter_id)
    command = _json_loads(adapter["command_json"], [])
    _validate_command(command)
    server_url = _required_metadata_string(metadata, "server_url", adapter_id)
    selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter, "server")
    return start_replay_server_process(
        command=[str(part) for part in command],
        server_url=server_url,
        output_dir=selected_output_dir,
        health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
        startup_timeout_seconds=_metadata_int(metadata, "startup_timeout_seconds", 15),
        cwd=_metadata_path_optional(metadata, "cwd"),
        allow_remote_server=_metadata_bool(metadata, "allow_remote_server", False),
    )


def registered_replay_server_status(
    *,
    db_path: Path,
    adapter_id: str,
    output_dir: Optional[Path] = None,
) -> ReplayServerProcessReport:
    adapter, metadata = _server_adapter(db_path=db_path, adapter_id=adapter_id)
    server_url = _required_metadata_string(metadata, "server_url", adapter_id)
    selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter, "server")
    return replay_server_process_status(
        server_url=server_url,
        output_dir=selected_output_dir,
        health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
        allow_remote_server=_metadata_bool(metadata, "allow_remote_server", False),
    )


def registered_replay_server_logs(
    *,
    db_path: Path,
    adapter_id: str,
    output_dir: Optional[Path] = None,
    max_bytes: int = 40000,
) -> ReplayServerProcessLogsReport:
    adapter, _metadata = _managed_server_adapter(db_path=db_path, adapter_id=adapter_id)
    selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter, "server")
    return read_replay_server_process_logs(
        output_dir=selected_output_dir,
        max_bytes=max_bytes,
    )


def stop_registered_replay_server_adapter(
    *,
    db_path: Path,
    adapter_id: str,
    output_dir: Optional[Path] = None,
) -> ReplayServerProcessReport:
    adapter, metadata = _managed_server_adapter(db_path=db_path, adapter_id=adapter_id)
    server_url = _required_metadata_string(metadata, "server_url", adapter_id)
    selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter, "server")
    return stop_replay_server_process(
        server_url=server_url,
        output_dir=selected_output_dir,
        health_path=_metadata_path(metadata, "health_path", DEFAULT_HEALTH_PATH),
        allow_remote_server=_metadata_bool(metadata, "allow_remote_server", False),
    )


def parse_adapter_command(command: str) -> list[str]:
    try:
        return parse_replay_command(command)
    except CheckError as exc:
        raise ReplayAdapterError(str(exc)) from exc


def _get_adapter(connection: sqlite3.Connection, adapter_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM replay_adapters WHERE id = ?",
        (adapter_id,),
    ).fetchone()
    if row is None:
        raise ReplayAdapterError(f"replay_adapter_not_found:{adapter_id}")
    return row


def _check_spec_profile_id(connection: sqlite3.Connection, check_spec_id: str) -> str:
    row = connection.execute(
        "SELECT profile_id FROM check_specs WHERE id = ?",
        (check_spec_id,),
    ).fetchone()
    if row is None:
        raise ReplayAdapterError(f"check_spec_not_found:{check_spec_id}")
    return str(row["profile_id"])


def _server_adapter(*, db_path: Path, adapter_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        adapter = _get_adapter(connection, adapter_id)
        if int(adapter["enabled"]) != 1:
            raise ReplayAdapterError(f"replay_adapter_disabled:{adapter_id}")
    metadata = _json_loads(adapter["metadata_json"], {})
    if _kind_from_metadata(metadata) not in {"http_server", "managed_http_server"}:
        raise ReplayAdapterError(f"replay_adapter_not_http_server:{adapter_id}")
    return adapter, metadata


def _managed_server_adapter(*, db_path: Path, adapter_id: str) -> tuple[sqlite3.Row, dict[str, Any]]:
    adapter, metadata = _server_adapter(db_path=db_path, adapter_id=adapter_id)
    if _kind_from_metadata(metadata) != "managed_http_server":
        raise ReplayAdapterError(f"replay_adapter_not_managed_http_server:{adapter_id}")
    return adapter, metadata


def _adapter_output_dir(db_path: Path, adapter: sqlite3.Row, check_spec_id: str) -> Path:
    configured = adapter["output_dir"]
    if isinstance(configured, str) and configured:
        base = Path(configured)
    else:
        base = db_path.parent / DEFAULT_REPLAY_ARTIFACT_DIR
    return base / str(adapter["id"]) / check_spec_id


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _row_exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (row_id,)).fetchone()
    return row is not None


def _validate_adapter_id(adapter_id: str) -> None:
    if not adapter_id or not adapter_id.replace("_", "").replace("-", "").isalnum():
        raise ReplayAdapterError("invalid_replay_adapter_id")


def _validate_command(command: Sequence[Any]) -> None:
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise ReplayAdapterError("replay_adapter_command_required")


def _validate_server_url(server_url: Optional[str], *, allow_remote_server: bool = False) -> None:
    if not isinstance(server_url, str) or not server_url.startswith(("http://", "https://")):
        raise ReplayAdapterError("replay_adapter_server_url_required")
    try:
        normalize_replay_server_url(server_url, allow_remote_server=allow_remote_server)
    except Exception as exc:
        raise ReplayAdapterError(str(exc)) from exc


def _adapter_kind(*, command: Optional[Sequence[str]], server_url: Optional[str]) -> str:
    has_command = bool(command)
    has_server_url = isinstance(server_url, str) and bool(server_url)
    if has_command and has_server_url:
        return "managed_http_server"
    if has_command:
        return "command"
    if has_server_url:
        return "http_server"
    raise ReplayAdapterError("replay_adapter_requires_command_or_server_url")


def _kind_from_metadata(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return "command"
    kind = metadata.get("kind")
    if kind in {"command", "http_server", "managed_http_server"}:
        return str(kind)
    return "command"


def _metadata_path(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else default


def _required_metadata_string(metadata: dict[str, Any], key: str, adapter_id: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value:
        raise ReplayAdapterError(f"replay_adapter_{key}_missing:{adapter_id}")
    return value


def _metadata_path_optional(metadata: dict[str, Any], key: str) -> Optional[Path]:
    value = metadata.get(key)
    return Path(value) if isinstance(value, str) and value else None


def _metadata_int(metadata: dict[str, Any], key: str, default: int) -> int:
    value = metadata.get(key)
    return int(value) if isinstance(value, int) and value > 0 else default


def _metadata_bool(metadata: dict[str, Any], key: str, default: bool) -> bool:
    value = metadata.get(key)
    return bool(value) if isinstance(value, bool) else default


def _validate_boundary(mode: str, side_effect_mode: str) -> None:
    if mode not in {"dry_run", "sandbox", "live"}:
        raise ReplayAdapterError(f"unsupported_replay_mode:{mode}")
    if mode == "live":
        raise ReplayAdapterError("live_replay_not_supported")
    if side_effect_mode not in SAFE_REPLAY_SIDE_EFFECT_MODES:
        raise ReplayAdapterError(f"unsafe_replay_side_effect_mode:{side_effect_mode}")


def _decode_adapter(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["command"] = _json_loads(payload.pop("command_json"), [])
    payload["metadata"] = _json_loads(payload.pop("metadata_json"), {})
    payload["kind"] = _kind_from_metadata(payload["metadata"])
    payload["server_url"] = payload["metadata"].get("server_url") if isinstance(payload["metadata"], dict) else None
    payload["health_path"] = payload["metadata"].get("health_path") if isinstance(payload["metadata"], dict) else None
    payload["replay_path"] = payload["metadata"].get("replay_path") if isinstance(payload["metadata"], dict) else None
    payload["startup_timeout_seconds"] = (
        payload["metadata"].get("startup_timeout_seconds") if isinstance(payload["metadata"], dict) else None
    )
    payload["cwd"] = payload["metadata"].get("cwd") if isinstance(payload["metadata"], dict) else None
    payload["allow_remote_server"] = (
        bool(payload["metadata"].get("allow_remote_server"))
        if isinstance(payload["metadata"], dict)
        else False
    )
    payload["enabled"] = bool(payload["enabled"])
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
