from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .analyze import AnalyzeError, AnalyzeReport, analyze_with_command_operator, parse_operator_command
from .storage import StorageError, connect, initialize_database, utc_now


DEFAULT_OPERATOR_ARTIFACT_DIR = ".kyoko/operator-runs"
SUPPORTED_OPERATOR_KINDS = {"generic", "codex", "claude", "hermes", "openclaw"}


class OperatorAdapterError(Exception):
    """Raised when a registered operator adapter cannot be used."""


@dataclass(frozen=True)
class OperatorAdapterRegisterReport:
    adapter_id: str
    profile_id: str
    name: str
    operator_kind: str
    command: tuple[str, ...]
    output_dir: Optional[str]
    timeout_seconds: int
    enabled: bool


def register_operator_adapter(
    *,
    db_path: Path,
    adapter_id: str,
    name: str,
    command: Sequence[str],
    profile_id: Optional[str] = None,
    operator_kind: str = "generic",
    output_dir: Optional[Path] = None,
    timeout_seconds: int = 120,
    enabled: bool = True,
    metadata: Optional[dict[str, Any]] = None,
) -> OperatorAdapterRegisterReport:
    initialize_database(db_path)
    _validate_adapter_id(adapter_id)
    _validate_operator_kind(operator_kind)
    _validate_command(command)
    if timeout_seconds <= 0:
        raise OperatorAdapterError("timeout_seconds_must_be_positive")

    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise OperatorAdapterError("profile_required")
        if not _row_exists(connection, "profiles", selected_profile_id):
            raise OperatorAdapterError(f"profile_not_found:{selected_profile_id}")

        now = utc_now()
        connection.execute(
            """
            INSERT INTO operator_adapters (
              id,
              profile_id,
              name,
              operator_kind,
              command_json,
              output_dir,
              timeout_seconds,
              enabled,
              metadata_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              profile_id = excluded.profile_id,
              name = excluded.name,
              operator_kind = excluded.operator_kind,
              command_json = excluded.command_json,
              output_dir = excluded.output_dir,
              timeout_seconds = excluded.timeout_seconds,
              enabled = excluded.enabled,
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                adapter_id,
                selected_profile_id,
                name,
                operator_kind,
                _json_dumps(list(command)),
                str(output_dir) if output_dir is not None else None,
                timeout_seconds,
                1 if enabled else 0,
                _json_dumps(metadata or {}),
                now,
                now,
            ),
        )

    return OperatorAdapterRegisterReport(
        adapter_id=adapter_id,
        profile_id=selected_profile_id,
        name=name,
        operator_kind=operator_kind,
        command=tuple(command),
        output_dir=str(output_dir) if output_dir is not None else None,
        timeout_seconds=timeout_seconds,
        enabled=enabled,
    )


def list_operator_adapters(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM operator_adapters
                ORDER BY created_at DESC, id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [_decode_adapter(row) for row in rows]


def run_registered_operator_adapter(
    *,
    db_path: Path,
    adapter_id: str,
    output_dir: Optional[Path] = None,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: Optional[int] = None,
    max_retries: int = 0,
    prompt_suffix: Optional[str] = None,
) -> AnalyzeReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        adapter = _get_adapter(connection, adapter_id)
        if int(adapter["enabled"]) != 1:
            raise OperatorAdapterError(f"operator_adapter_disabled:{adapter_id}")
        selected_profile_id = profile_id or str(adapter["profile_id"])
        if selected_profile_id != str(adapter["profile_id"]):
            raise OperatorAdapterError(f"operator_adapter_profile_mismatch:{adapter_id}:{selected_profile_id}")

    command = _json_loads(adapter["command_json"], [])
    _validate_command(command)
    selected_output_dir = output_dir or _adapter_output_dir(db_path, adapter)
    selected_timeout = timeout_seconds or int(adapter["timeout_seconds"])

    try:
        return analyze_with_command_operator(
            db_path=db_path,
            output_dir=selected_output_dir,
            command=[str(part) for part in command],
            operator_label=adapter_id,
            profile_id=selected_profile_id,
            run_id=run_id,
            schema_path=schema_path,
            timeout_seconds=selected_timeout,
            operator_kind=str(adapter["operator_kind"]),
            adapter_id=adapter_id,
            max_retries=max_retries,
            prompt_suffix=prompt_suffix,
        )
    except AnalyzeError as exc:
        raise OperatorAdapterError(str(exc)) from exc


def parse_adapter_command(command: str) -> list[str]:
    try:
        return parse_operator_command(command)
    except AnalyzeError as exc:
        raise OperatorAdapterError(str(exc)) from exc


def _get_adapter(connection: sqlite3.Connection, adapter_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM operator_adapters WHERE id = ?",
        (adapter_id,),
    ).fetchone()
    if row is None:
        raise OperatorAdapterError(f"operator_adapter_not_found:{adapter_id}")
    return row


def _adapter_output_dir(db_path: Path, adapter: sqlite3.Row) -> Path:
    configured = adapter["output_dir"]
    if isinstance(configured, str) and configured:
        return Path(configured)
    return db_path.parent / DEFAULT_OPERATOR_ARTIFACT_DIR / str(adapter["id"])


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _row_exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (row_id,)).fetchone()
    return row is not None


def _validate_adapter_id(adapter_id: str) -> None:
    if not adapter_id or not adapter_id.replace("_", "").replace("-", "").isalnum():
        raise OperatorAdapterError("invalid_operator_adapter_id")


def _validate_operator_kind(operator_kind: str) -> None:
    if operator_kind not in SUPPORTED_OPERATOR_KINDS:
        raise OperatorAdapterError(f"unsupported_operator_kind:{operator_kind}")


def _validate_command(command: Sequence[Any]) -> None:
    if not command or any(not isinstance(part, str) or not part for part in command):
        raise OperatorAdapterError("operator_adapter_command_required")


def _decode_adapter(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["command"] = _json_loads(payload.pop("command_json"), [])
    payload["metadata"] = _json_loads(payload.pop("metadata_json"), {})
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
