from __future__ import annotations

import json
import os
import shutil
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Sequence, TextIO

from . import __version__
from .analyze import list_operator_runs
from .apply import (
    list_context_delivery_rules,
    list_context_delivery_rule_revisions,
    list_skill_revisions,
    list_skills,
    rollback_context_delivery_rule_revision,
    rollback_skill_revision,
)
from .autonomy import get_autonomy_policy
from .blobs import list_payload_blobs, prune_payload_blobs, storage_report
from .dashboard_metrics import get_dashboard_metrics
from .details import (
    get_check_detail,
    get_issue_detail,
    get_proposal_detail,
    get_replay_detail,
    get_run_detail,
    list_runs,
)
from .issues import (
    create_issue,
    link_proposal_to_issue,
    list_issues,
    surface_issue,
    validate_issue,
)
from .doctor import DEFAULT_SMOKE_EVIDENCE_DIR, DoctorError, run_doctor
from .evidence import build_evidence_bundle
from .checks import (
    generate_checks_for_proposal,
    list_assertion_presets,
    list_check_capabilities,
    list_check_runs,
    list_check_locks,
    list_check_specs,
    list_replay_runs,
    parse_judge_command,
    run_check,
    run_judge_command,
)
from .eval_detectors import DetectorError, list_detectors, run_detector
from .evals_measure import EvalMeasureError, compare_eval_runs, get_measure_results, get_measure_run, list_measure_runs
from .llm_evals import LlmEvalError, list_llm_evals, run_llm_eval
from .annotations import create_annotation, list_annotations
from .harness import list_harness_target_locks, list_patch_transactions
from .inspection import (
    get_current_run,
    get_run_outline,
    get_span_context,
    get_span_payload,
    search_run,
)
from .mcp_log import McpLogger, list_mcp_log, log_enabled_from_env
from .improve import ImproveError, run_improvement_loop
from .operator_adapters import list_operator_adapters
from .operator_smoke import OperatorSmokeError, run_operator_smoke_matrix
from .profile_next import ProfileNextError, run_profile_next_step
from .profiles import list_profiles
from .proposals import (
    list_learning_proposals,
    submit_learning_proposal_payload,
)
from .replay_adapters import list_replay_adapters, run_registered_replay_adapter
from .retention import prune_retained_data
from .skillbook import export_skillbook, mark_skills_used, render_skillbook_prompt
from .source_discovery import discover_local_sources
from .storage import default_db_path, get_database_status, initialize_database, status_to_json


MCP_PROTOCOL_VERSION = "2025-11-25"
JSONRPC_VERSION = "2.0"
MCP_INSTALL_SMOKE_TARGETS = ("codex", "claude", "hermes", "openclaw")
VERIFIED_NATIVE_MCP_INSTALL_TARGETS = {"codex", "claude"}
MCP_DIRECT_APPLY_TOOL_NAMES = frozenset(
    {
        "kyoko_apply",
        "kyoko_apply_proposal",
        "kyoko_apply_context_proposal",
        "kyoko_run_autonomy",
    }
)
MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES = frozenset(
    {
        "kyoko_apply_harness",
        "kyoko_apply_patch_transaction",
        "kyoko_rollback_harness",
    }
)
MCP_PROHIBITED_DEFAULT_TOOL_NAMES = (
    MCP_DIRECT_APPLY_TOOL_NAMES | MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES
)
MCP_AUTONOMY_DISABLED_TOOL_NAMES = frozenset({"kyoko_run_improve"})


class McpError(Exception):
    """Raised when MCP server setup or dispatch fails."""


@dataclass(frozen=True)
class McpTool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = True

    def to_protocol(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
            },
        }


@dataclass(frozen=True)
class McpClientInstallPlan:
    target: str
    server: str
    config: dict[str, Any]
    command: list[str]
    shell_command: Optional[str]
    config_path_hint: Optional[str]
    requires_manual_config: bool
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "server": self.server,
            "config": self.config,
            "command": list(self.command),
            "shell_command": self.shell_command,
            "config_path_hint": self.config_path_hint,
            "requires_manual_config": self.requires_manual_config,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class McpClientInstallSmokeReport:
    target: str
    server: str
    command: list[str]
    cwd: Path
    home: Path
    config_path_hint: Optional[str]
    config_exists: bool
    returncode: int
    stdout_tail: str
    list_command: Optional[list[str]]
    list_returncode: Optional[int]
    list_stdout_tail: Optional[str]
    list_verified: Optional[bool]
    duration_ms: float
    passed: bool
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "server": self.server,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "home": str(self.home),
            "config_path_hint": self.config_path_hint,
            "config_exists": self.config_exists,
            "returncode": self.returncode,
            "stdout_tail": self.stdout_tail,
            "list_command": list(self.list_command) if self.list_command is not None else None,
            "list_returncode": self.list_returncode,
            "list_stdout_tail": self.list_stdout_tail,
            "list_verified": self.list_verified,
            "duration_ms": self.duration_ms,
            "passed": self.passed,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class McpClientInstallSmokeTargetReport:
    target: str
    status: str
    reason: Optional[str]
    report: Optional[McpClientInstallSmokeReport] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "status": self.status,
            "reason": self.reason,
            "report": self.report.to_json() if self.report is not None else None,
        }


@dataclass(frozen=True)
class McpClientInstallSmokeMatrixReport:
    targets: tuple[str, ...]
    server: str
    output_dir: Path
    passed: bool
    results: tuple[McpClientInstallSmokeTargetReport, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "targets": list(self.targets),
            "server": self.server,
            "output_dir": str(self.output_dir),
            "passed": self.passed,
            "summary": _mcp_install_matrix_summary(self.results),
            "results": [result.to_json() for result in self.results],
        }


class KyokoMcpServer:
    def __init__(
        self,
        *,
        db_path: Path,
        schema_path: Optional[Path] = None,
        log_enabled: bool = True,
    ) -> None:
        initialize_database(db_path)
        self.db_path = db_path
        self.schema_path = schema_path
        self.tools = _build_tools(self)
        _assert_default_mcp_tool_safety(self.tools)
        self._logger = McpLogger(db_path=db_path) if log_enabled else None

    def handle_message(self, message: Any) -> Optional[dict[str, Any]]:
        if self._logger is None:
            return self._handle_message_inner(message)
        return self._logger.wrap(message, self._handle_message_inner)

    def _handle_message_inner(self, message: Any) -> Optional[dict[str, Any]]:
        if not isinstance(message, dict):
            return _error_response(None, -32600, "invalid_request")

        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error_response(request_id, -32600, "method_required")

        is_notification = "id" not in message
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {
                        "name": "kyoko",
                        "title": "Kyoko",
                        "version": __version__,
                    },
                    "instructions": (
                        "Kyoko exposes local-first agent optimization tools. "
                        "Default MCP tools are read/propose/check-request plus local "
                        "readiness and dry-run style checks; direct apply and harness "
                        "writes are intentionally not exposed."
                    ),
                }
                return _result_response(request_id, result)

            if method == "notifications/initialized":
                return None

            if method == "ping":
                return _result_response(request_id, {})

            if method == "tools/list":
                return _result_response(
                    request_id,
                    {"tools": [tool.to_protocol() for tool in self.tools.values()]},
                )

            if method == "tools/call":
                params = message.get("params")
                if not isinstance(params, dict):
                    return _error_response(request_id, -32602, "params_required")
                result = self._call_tool(params)
                return _result_response(request_id, result)

            if is_notification:
                return None
            return _error_response(request_id, -32601, f"method_not_found:{method}")
        except Exception as exc:
            if is_notification:
                return None
            return _error_response(request_id, -32603, str(exc))

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise McpError("tool_name_required")
        if not isinstance(arguments, dict):
            raise McpError("tool_arguments_must_be_object")

        tool = self.tools.get(name)
        if tool is None:
            raise McpError(f"tool_not_found:{name}")

        try:
            payload = tool.handler(arguments)
        except Exception as exc:
            return _tool_result({"error": str(exc)}, is_error=True)
        return _tool_result(payload)


def serve_stdio(
    *,
    db_path: Path,
    schema_path: Optional[Path] = None,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    log_enabled: Optional[bool] = None,
) -> None:
    initialize_database(db_path)
    enabled = log_enabled_from_env(os.environ) if log_enabled is None else log_enabled
    server = KyokoMcpServer(db_path=db_path, schema_path=schema_path, log_enabled=enabled)
    for line in stdin:
        raw = line.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            _write_jsonrpc(stdout, _error_response(None, -32700, f"parse_error:{exc}"))
            continue

        if isinstance(message, list):
            responses = [server.handle_message(item) for item in message]
            responses = [response for response in responses if response is not None]
            if responses:
                _write_jsonrpc(stdout, responses)
            continue

        response = server.handle_message(message)
        if response is not None:
            _write_jsonrpc(stdout, response)


def build_mcp_config(
    *,
    db_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    server_name: str = "kyoko",
    target: str = "generic",
) -> dict[str, Any]:
    selected_db_path = db_path or default_db_path()
    args = ["-m", "kyoko", "mcp", "serve", "--db", str(selected_db_path)]
    if schema_path is not None:
        args.extend(["--schema", str(schema_path.resolve())])
    server_config: dict[str, Any] = {
        "command": sys.executable,
        "args": args,
    }
    server_env = _mcp_server_env()
    if server_env:
        server_config["env"] = server_env
    return {
        "target": target,
        "mcpServers": {
            server_name: server_config,
        },
    }


def write_mcp_config(
    *,
    output_path: Path,
    db_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    server_name: str = "kyoko",
    target: str = "generic",
) -> dict[str, Any]:
    payload = build_mcp_config(
        db_path=db_path,
        schema_path=schema_path,
        server_name=server_name,
        target=target,
    )
    payload = merge_mcp_config_file(output_path, payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return payload


def build_mcp_install_plan(
    *,
    db_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    server_name: str = "kyoko",
    target: str = "generic",
    scope: str = "local",
    home: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> McpClientInstallPlan:
    payload = build_mcp_config(
        db_path=db_path,
        schema_path=schema_path,
        server_name=server_name,
        target=target,
    )
    server_config = payload["mcpServers"][server_name]
    selected_home = home or Path.home()
    selected_env = env if env is not None else os.environ

    if target == "codex":
        env_flags = []
        for key, value in server_config.get("env", {}).items():
            env_flags.extend(["--env", f"{key}={value}"])
        command = [
            "codex",
            "mcp",
            "add",
            server_name,
            *env_flags,
            "--",
            str(server_config["command"]),
            *[str(arg) for arg in server_config.get("args", [])],
        ]
        codex_home = Path(selected_env.get("CODEX_HOME") or selected_home / ".codex")
        return McpClientInstallPlan(
            target=target,
            server=server_name,
            config=payload,
            command=command,
            shell_command=shlex.join(command),
            config_path_hint=str(codex_home / "config.toml"),
            requires_manual_config=False,
            notes=(
                "Run the command to let Codex add Kyoko to its MCP registry.",
                "Use `codex mcp list` after installation to verify the server.",
            ),
        )

    if target == "claude":
        compact_server_config = json.dumps(server_config, separators=(",", ":"))
        command = [
            "claude",
            "mcp",
            "add-json",
            "--scope",
            scope,
            server_name,
            compact_server_config,
        ]
        hint = str(selected_home / ".claude.json") if scope == "user" else None
        return McpClientInstallPlan(
            target=target,
            server=server_name,
            config=payload,
            command=command,
            shell_command=shlex.join(command),
            config_path_hint=hint,
            requires_manual_config=False,
            notes=(
                "Run the command to let Claude Code add Kyoko to its MCP registry.",
                "Use `claude mcp list` after installation to verify the server.",
            ),
        )

    return McpClientInstallPlan(
        target=target,
        server=server_name,
        config=payload,
        command=[],
        shell_command=None,
        config_path_hint=None,
        requires_manual_config=True,
        notes=(
            "No verified native MCP installer is registered for this target yet.",
            "Use `kyoko mcp install --output <path>` to write the generic JSON config.",
        ),
    )


def run_mcp_install_smoke(
    *,
    db_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    server_name: str = "kyoko",
    target: str,
    scope: str = "user",
    output_dir: Path,
    client_command: Optional[Path] = None,
    timeout_seconds: int = 30,
    verify_list: bool = True,
    env: Optional[dict[str, str]] = None,
) -> McpClientInstallSmokeReport:
    if target not in MCP_INSTALL_SMOKE_TARGETS:
        raise McpError(f"mcp_install_smoke_target_not_supported:{target}")
    if target not in VERIFIED_NATIVE_MCP_INSTALL_TARGETS:
        raise McpError(f"mcp_install_smoke_no_native_command:{target}")
    if timeout_seconds < 1:
        raise McpError("mcp_install_smoke_timeout_must_be_positive")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    home = output_dir / "home"
    codex_home = output_dir / "codex-home"
    xdg_config_home = output_dir / "xdg-config"
    cwd = output_dir / "workspace"
    for path in (home, codex_home, xdg_config_home, cwd):
        path.mkdir(parents=True, exist_ok=True)
    selected_db_path = (db_path or output_dir / "kyoko.db").expanduser().resolve()

    smoke_env = os.environ.copy()
    if env:
        smoke_env.update(env)
    smoke_env.update(
        {
            "HOME": str(home),
            "CODEX_HOME": str(codex_home),
            "XDG_CONFIG_HOME": str(xdg_config_home),
            "PYTHONNOUSERSITE": "1",
        }
    )
    plan = build_mcp_install_plan(
        db_path=selected_db_path,
        schema_path=schema_path,
        server_name=server_name,
        target=target,
        scope=scope,
        home=home,
        env=smoke_env,
    )
    if plan.requires_manual_config or not plan.command:
        raise McpError(f"mcp_install_smoke_no_native_command:{target}")

    command = list(plan.command)
    if client_command is not None:
        command[0] = str(client_command)

    start = time.perf_counter()
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=smoke_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        raise McpError(f"mcp_client_not_found:{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise McpError(f"mcp_install_smoke_timed_out:{target}:{timeout_seconds}") from exc
    duration_ms = (time.perf_counter() - start) * 1000.0
    config_path = Path(plan.config_path_hint) if plan.config_path_hint else None
    config_exists = bool(config_path and config_path.exists())
    list_command: Optional[list[str]] = None
    list_returncode: Optional[int] = None
    list_stdout_tail: Optional[str] = None
    list_verified: Optional[bool] = None
    if verify_list:
        list_command = _mcp_client_list_command(target=target, client_command=command[0])
        try:
            list_result = subprocess.run(
                list_command,
                cwd=cwd,
                env=smoke_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise McpError(f"mcp_client_not_found:{list_command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise McpError(f"mcp_list_smoke_timed_out:{target}:{timeout_seconds}") from exc
        list_returncode = list_result.returncode
        list_stdout_tail = list_result.stdout[-5000:]
        list_verified = _mcp_list_verified(
            server_name=server_name,
            returncode=list_result.returncode,
            stdout=list_result.stdout,
        )
        duration_ms = (time.perf_counter() - start) * 1000.0

    passed = (
        result.returncode == 0
        and (config_path is None or config_exists)
        and (list_verified is not False)
    )
    notes = list(plan.notes)
    if config_path is not None:
        notes.append(f"Isolated config path checked: {config_path}")
    if client_command is not None:
        notes.append(f"Client command override used: {client_command}")
    if verify_list:
        if list_verified:
            notes.append("Client MCP registry/list output verified for the server name.")
        else:
            notes.append("Client MCP registry/list output did not prove a healthy server entry.")
    else:
        notes.append("Client MCP registry/list verification skipped.")

    return McpClientInstallSmokeReport(
        target=target,
        server=server_name,
        command=command,
        cwd=cwd,
        home=home,
        config_path_hint=str(config_path) if config_path is not None else None,
        config_exists=config_exists,
        returncode=result.returncode,
        stdout_tail=result.stdout[-5000:],
        list_command=list_command,
        list_returncode=list_returncode,
        list_stdout_tail=list_stdout_tail,
        list_verified=list_verified,
        duration_ms=duration_ms,
        passed=passed,
        notes=tuple(notes),
    )


def run_mcp_install_smoke_matrix(
    *,
    db_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    server_name: str = "kyoko",
    targets: Sequence[str] = MCP_INSTALL_SMOKE_TARGETS,
    scope: str = "user",
    output_dir: Path,
    client_commands: Optional[dict[str, Path]] = None,
    timeout_seconds: int = 30,
    verify_list: bool = True,
    skip_missing: bool = True,
    env: Optional[dict[str, str]] = None,
) -> McpClientInstallSmokeMatrixReport:
    selected_targets = _normalize_mcp_install_targets(targets)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[McpClientInstallSmokeTargetReport] = []
    for target in selected_targets:
        client_command = client_commands.get(target) if client_commands else None
        if target not in VERIFIED_NATIVE_MCP_INSTALL_TARGETS:
            results.append(
                McpClientInstallSmokeTargetReport(
                    target=target,
                    status="skipped",
                    reason=f"mcp_install_smoke_no_native_command:{target}",
                )
            )
            continue
        if client_command is None and shutil.which(target) is None:
            status = "skipped" if skip_missing else "failed"
            results.append(
                McpClientInstallSmokeTargetReport(
                    target=target,
                    status=status,
                    reason=f"mcp_client_not_found:{target}",
                )
            )
            continue
        try:
            report = run_mcp_install_smoke(
                db_path=db_path,
                schema_path=schema_path,
                server_name=server_name,
                target=target,
                scope=scope,
                output_dir=output_dir / target,
                client_command=client_command,
                timeout_seconds=timeout_seconds,
                verify_list=verify_list,
                env=env,
            )
        except McpError as exc:
            reason = str(exc)
            status = "skipped" if skip_missing and reason.startswith("mcp_client_not_found:") else "failed"
            results.append(
                McpClientInstallSmokeTargetReport(
                    target=target,
                    status=status,
                    reason=reason,
                )
            )
            continue
        results.append(
            McpClientInstallSmokeTargetReport(
                target=target,
                status="passed" if report.passed else "failed",
                reason=None if report.passed else "mcp_install_smoke_failed",
                report=report,
            )
        )
    summary = _mcp_install_matrix_summary(tuple(results))
    passed = summary["failed"] == 0 and summary["passed"] > 0
    return McpClientInstallSmokeMatrixReport(
        targets=selected_targets,
        server=server_name,
        output_dir=output_dir,
        passed=passed,
        results=tuple(results),
    )


def mcp_safety_contract(tools: dict[str, McpTool]) -> dict[str, Any]:
    tool_names = set(tools)
    direct_apply = sorted(tool_names & MCP_DIRECT_APPLY_TOOL_NAMES)
    direct_harness_write = sorted(tool_names & MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES)
    destructive_tools = sorted(name for name, tool in tools.items() if tool.destructive)
    non_read_only_tools = sorted(name for name, tool in tools.items() if not tool.read_only)
    autonomy_disabled_tools = sorted(tool_names & MCP_AUTONOMY_DISABLED_TOOL_NAMES)
    passed = not direct_apply and not direct_harness_write and "kyoko_run_improve" in autonomy_disabled_tools
    return {
        "passed": passed,
        "default_surface": "read_propose_check_request_with_annotated_privileged_rollbacks",
        "tool_count": len(tools),
        "prohibited_tool_names": sorted(MCP_PROHIBITED_DEFAULT_TOOL_NAMES),
        "direct_apply_tools_exposed": direct_apply,
        "direct_harness_write_tools_exposed": direct_harness_write,
        "destructive_tools": destructive_tools,
        "non_read_only_tools": non_read_only_tools,
        "mcp_autonomy_disabled_tools": autonomy_disabled_tools,
        "notes": [
            "Default MCP tools do not expose direct apply, run-autonomy, or harness file write tools.",
            "Rollback tools are exposed only with destructive annotations.",
            "kyoko_run_improve is orchestration-only and forces run_autonomy_after=false.",
        ],
    }


def _assert_default_mcp_tool_safety(tools: dict[str, McpTool]) -> None:
    contract = mcp_safety_contract(tools)
    if contract["direct_apply_tools_exposed"] or contract["direct_harness_write_tools_exposed"]:
        exposed = sorted(
            set(contract["direct_apply_tools_exposed"])
            | set(contract["direct_harness_write_tools_exposed"])
        )
        raise McpError(f"mcp_default_surface_exposes_prohibited_tools:{','.join(exposed)}")
    if "kyoko_run_improve" not in contract["mcp_autonomy_disabled_tools"]:
        raise McpError("mcp_default_surface_missing_non_applying_improve_contract")


def _mcp_client_list_command(*, target: str, client_command: str) -> list[str]:
    if target in VERIFIED_NATIVE_MCP_INSTALL_TARGETS:
        return [client_command, "mcp", "list"]
    raise McpError(f"mcp_list_smoke_target_not_supported:{target}")


def _mcp_server_env() -> dict[str, str]:
    root = Path(__file__).resolve().parents[1]
    if (root / "pyproject.toml").exists() and (root / "kyoko").is_dir():
        return {"PYTHONPATH": str(root)}
    return {}


def _mcp_list_verified(*, server_name: str, returncode: int, stdout: str) -> bool:
    if returncode != 0 or server_name not in stdout:
        return False
    if "Failed to connect" in stdout:
        return False
    return True


def _normalize_mcp_install_targets(targets: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for target in targets:
        if target not in MCP_INSTALL_SMOKE_TARGETS:
            raise McpError(f"mcp_install_smoke_target_not_supported:{target}")
        if target not in selected:
            selected.append(target)
    if not selected:
        raise McpError("mcp_install_smoke_target_required")
    return tuple(selected)


def _mcp_install_matrix_summary(
    results: Sequence[McpClientInstallSmokeTargetReport],
) -> dict[str, int]:
    summary = {
        "total": len(results),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "available": 0,
    }
    for result in results:
        if result.status in {"passed", "failed", "skipped"}:
            summary[result.status] += 1
        if result.status != "skipped":
            summary["available"] += 1
    return summary


def merge_mcp_config_file(output_path: Path, generated: dict[str, Any]) -> dict[str, Any]:
    if not output_path.exists() or not output_path.read_text().strip():
        return generated
    try:
        existing = json.loads(output_path.read_text())
    except json.JSONDecodeError as exc:
        raise McpError(f"mcp_config_json_invalid:{output_path}:{exc}") from exc
    return merge_mcp_config(existing=existing, generated=generated)


def merge_mcp_config(*, existing: Any, generated: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(existing, dict):
        raise McpError("mcp_config_must_be_object")
    generated_servers = generated.get("mcpServers")
    if not isinstance(generated_servers, dict) or not generated_servers:
        raise McpError("generated_mcp_servers_missing")

    existing_servers = existing.get("mcpServers", {})
    if not isinstance(existing_servers, dict):
        raise McpError("mcp_config_servers_must_be_object")

    merged = dict(existing)
    merged["mcpServers"] = {**existing_servers, **generated_servers}
    if "target" in generated:
        merged["target"] = generated["target"]
    return merged


def _build_tools(server: KyokoMcpServer) -> dict[str, McpTool]:
    tools = [
        McpTool(
            name="kyoko_status",
            title="Kyoko Status",
            description="Return local Kyoko database status and table counts.",
            input_schema=_object_schema({}),
            handler=lambda _args: status_to_json(get_database_status(server.db_path)),
        ),
        McpTool(
            name="kyoko_mcp_safety_contract",
            title="Kyoko MCP Safety Contract",
            description=(
                "Report the default MCP tool safety contract, including prohibited "
                "direct-apply/harness-write tools and annotated privileged tools."
            ),
            input_schema=_object_schema({}),
            handler=lambda _args: mcp_safety_contract(server.tools),
        ),
        McpTool(
            name="kyoko_list_profiles",
            title="Kyoko Profiles",
            description=(
                "List local workflow profiles with counts, storage bytes, latest run, "
                "routing state, and suggested command vectors."
            ),
            input_schema=_object_schema({}),
            handler=lambda _args: {"profiles": list_profiles(server.db_path)},
        ),
        McpTool(
            name="kyoko_run_profile_next_step",
            title="Run Kyoko Profile Next Step",
            description=(
                "Plan or run the next local Kyoko step for a profile. Defaults to dry-run; "
                "set run=true before mutating check/replay/autonomy state."
            ),
            input_schema=_object_schema(
                {
                    "profile_id": {"type": "string"},
                    "run": {"type": "boolean"},
                    "replay_adapter_id": {"type": "string"},
                    "replay_output_dir": {"type": "string"},
                    "replay_timeout_seconds": {"type": "integer", "minimum": 1},
                    "harness_workspace_root": {"type": "string"},
                    "operator_adapter_id": {"type": "string"},
                    "operator_target": {"type": "string"},
                    "operator_output_dir": {"type": "string"},
                    "operator_timeout_seconds": {"type": "integer", "minimum": 1},
                    "operator_max_retries": {"type": "integer", "minimum": 0},
                    "schema_path": {"type": "string"},
                }
            ),
            handler=lambda args: _run_profile_next_step(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_get_dashboard_metrics",
            title="Kyoko Dashboard Metrics",
            description=(
                "Return bounded product-loop metrics for one profile: issues, proposal state, "
                "check pass/fail, replay result, autonomy actions, and before/after verification."
            ),
            input_schema=_object_schema({"profile_id": {"type": "string"}}),
            handler=lambda args: get_dashboard_metrics(
                db_path=server.db_path,
                profile_id=_optional_string(args, "profile_id"),
            ),
        ),
        McpTool(
            name="kyoko_get_mcp_log",
            title="Kyoko MCP Communication Log",
            description=(
                "Return recorded JSON-RPC traffic between coding agents and Kyoko's MCP "
                "server (initialize/tools-list/tools-call and responses, with timing and "
                "redacted bodies). Useful for an agent to inspect its own recent calls. "
                "Filter by session_id, tool_name, or after_seq."
            ),
            input_schema=_object_schema(
                {
                    "session_id": {"type": "string"},
                    "tool_name": {"type": "string"},
                    "after_seq": {"type": "integer", "minimum": 0},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                }
            ),
            handler=lambda args: {
                "events": list_mcp_log(
                    db_path=server.db_path,
                    session_id=_optional_string(args, "session_id"),
                    tool_name=_optional_string(args, "tool_name"),
                    after_seq=args.get("after_seq")
                    if isinstance(args.get("after_seq"), int)
                    else None,
                    limit=_optional_int(args, "limit", 200),
                )
            },
        ),
        McpTool(
            name="kyoko_get_current_run",
            title="Kyoko Current Run",
            description=(
                "Return the most recently active run (the one the agent most likely just "
                "produced). Use this to orient before deeper inspection."
            ),
            input_schema=_object_schema({}),
            handler=lambda _args: {"run": get_current_run(db_path=server.db_path)},
        ),
        McpTool(
            name="kyoko_get_run_outline",
            title="Kyoko Run Outline",
            description=(
                "Structural overview of a run: span-tree skeleton, counts, and short "
                "payload previews. No full payloads — call kyoko_get_span_payload for those."
            ),
            input_schema=_object_schema(
                {
                    "run_id": {"type": "string"},
                    "payload_preview_chars": {"type": "integer", "minimum": 0, "maximum": 2000},
                },
                required=["run_id"],
            ),
            handler=lambda args: get_run_outline(
                db_path=server.db_path,
                run_id=_required_string(args, "run_id"),
                payload_preview_chars=_optional_int(args, "payload_preview_chars", 200),
            ),
        ),
        McpTool(
            name="kyoko_search_run",
            title="Kyoko Search Run",
            description=(
                "Search a run's span names, attributes, payload previews, and live events "
                "for a substring or regex. Returns located matches with snippets."
            ),
            input_schema=_object_schema(
                {
                    "run_id": {"type": "string"},
                    "pattern": {"type": "string"},
                    "regex": {"type": "boolean"},
                    "case_sensitive": {"type": "boolean"},
                    "scope": {"type": "array", "items": {"type": "string"}},
                    "context_chars": {"type": "integer", "minimum": 0, "maximum": 1000},
                    "max_matches": {"type": "integer", "minimum": 1, "maximum": 1000},
                },
                required=["run_id", "pattern"],
            ),
            handler=lambda args: search_run(
                db_path=server.db_path,
                run_id=_required_string(args, "run_id"),
                pattern=_required_string(args, "pattern"),
                regex=bool(args.get("regex")),
                case_sensitive=bool(args.get("case_sensitive")),
                scope=list(_optional_string_list(args, "scope") or ()) or None,
                context_chars=_optional_int(args, "context_chars", 80),
                max_matches=_optional_int(args, "max_matches", 50),
            ),
        ),
        McpTool(
            name="kyoko_get_span_context",
            title="Kyoko Span Context",
            description=(
                "Return neighbour span skeletons (time-ordered) around a span, optionally "
                "including its parent — cheap structural context without payloads."
            ),
            input_schema=_object_schema(
                {
                    "span_id": {"type": "string"},
                    "before": {"type": "integer", "minimum": 0, "maximum": 50},
                    "after": {"type": "integer", "minimum": 0, "maximum": 50},
                    "include_parent": {"type": "boolean"},
                },
                required=["span_id"],
            ),
            handler=lambda args: get_span_context(
                db_path=server.db_path,
                span_id=_required_string(args, "span_id"),
                before=_optional_int(args, "before", 2),
                after=_optional_int(args, "after", 2),
                include_parent=args.get("include_parent", True) is not False,
            ),
        ),
        McpTool(
            name="kyoko_get_span_payload",
            title="Kyoko Span Payload",
            description=(
                "Return a span's input or output payload, redacted before it leaves the "
                "machine, with optional JSON path extraction (e.g. messages.0.content) and "
                "offset/max_chars slicing."
            ),
            input_schema=_object_schema(
                {
                    "span_id": {"type": "string"},
                    "target": {"type": "string", "enum": ["input", "output"]},
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000},
                    "offset": {"type": "integer", "minimum": 0},
                },
                required=["span_id"],
            ),
            handler=lambda args: get_span_payload(
                db_path=server.db_path,
                span_id=_required_string(args, "span_id"),
                target=_optional_string(args, "target") or "input",
                path=_optional_string(args, "path"),
                max_chars=_optional_int(args, "max_chars", 4000),
                offset=_optional_int(args, "offset", 0),
            ),
        ),
        McpTool(
            name="kyoko_annotate",
            title="Kyoko Annotate",
            description=(
                "Attach a durable annotation (issue|good|note) to a run or span. Evidence "
                "only — an annotation may seed a proposal but never changes agent behavior "
                "or bypasses the check/replay gate."
            ),
            input_schema=_object_schema(
                {
                    "kind": {"type": "string", "enum": ["issue", "good", "note"]},
                    "run_id": {"type": "string"},
                    "span_id": {"type": "string"},
                    "note": {"type": "string"},
                    "source": {"type": "string"},
                },
                required=["kind"],
            ),
            handler=lambda args: create_annotation(
                db_path=server.db_path,
                kind=_required_string(args, "kind"),
                run_id=_optional_string(args, "run_id"),
                span_id=_optional_string(args, "span_id"),
                note=_optional_string(args, "note"),
                source=_optional_string(args, "source") or "agent",
            ),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_annotations",
            title="Kyoko List Annotations",
            description="List annotations, optionally filtered by run_id or span_id.",
            input_schema=_object_schema(
                {
                    "run_id": {"type": "string"},
                    "span_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                }
            ),
            handler=lambda args: {
                "annotations": list_annotations(
                    db_path=server.db_path,
                    run_id=_optional_string(args, "run_id"),
                    span_id=_optional_string(args, "span_id"),
                    limit=_optional_int(args, "limit", 200),
                )
            },
        ),
        McpTool(
            name="kyoko_list_issues",
            title="Kyoko List Issues",
            description="List first-class issues, optionally filtered by status or section.",
            input_schema=_object_schema(
                {
                    "status": {"type": "string", "enum": ["open", "resolved", "dismissed"]},
                    "section": {"type": "string", "enum": ["context", "harness"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                }
            ),
            handler=lambda args: {
                "issues": list_issues(
                    db_path=server.db_path,
                    status=_optional_string(args, "status"),
                    section=_optional_string(args, "section"),
                    limit=_optional_int(args, "limit", 200),
                )
            },
        ),
        McpTool(
            name="kyoko_get_issue",
            title="Kyoko Issue Detail",
            description=(
                "Return one issue with resolved evidence, affected entities, and linked "
                "proposals. Issues are evidence only and never change agent behavior."
            ),
            input_schema=_object_schema(
                {"issue_id": {"type": "string"}},
                required=["issue_id"],
            ),
            handler=lambda args: get_issue_detail(
                db_path=server.db_path,
                issue_id=_required_string(args, "issue_id"),
            ),
        ),
        McpTool(
            name="kyoko_create_issue",
            title="Kyoko Create Issue",
            description=(
                "Create a first-class issue (category/severity/affected-entity links and "
                "optional proposal backlinks). Evidence only — an issue may seed a proposal "
                "but never changes agent behavior or bypasses the check/replay gate."
            ),
            input_schema=_object_schema(
                {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "section": {"type": "string", "enum": ["context", "harness"]},
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "status": {"type": "string", "enum": ["open", "resolved", "dismissed"]},
                    "evidence_refs": {"type": "array"},
                    "affected_agent_identity_ids": {"type": "array", "items": {"type": "string"}},
                    "affected_workflow_node_ids": {"type": "array", "items": {"type": "string"}},
                    "affected_task_ids": {"type": "array", "items": {"type": "string"}},
                    "affected_span_ids": {"type": "array", "items": {"type": "string"}},
                    "proposal_ids": {"type": "array", "items": {"type": "string"}},
                },
                required=["title"],
            ),
            handler=lambda args: {
                "issue": create_issue(
                    db_path=server.db_path,
                    title=_required_string(args, "title"),
                    body=_optional_string(args, "body"),
                    section=_optional_string(args, "section"),
                    category=_optional_string(args, "category"),
                    severity=_optional_string(args, "severity"),
                    status=_optional_string(args, "status") or "open",
                    evidence_refs=args.get("evidence_refs")
                    if isinstance(args.get("evidence_refs"), list)
                    else None,
                    affected_agent_identity_ids=args.get("affected_agent_identity_ids")
                    if isinstance(args.get("affected_agent_identity_ids"), list)
                    else None,
                    affected_workflow_node_ids=args.get("affected_workflow_node_ids")
                    if isinstance(args.get("affected_workflow_node_ids"), list)
                    else None,
                    affected_task_ids=args.get("affected_task_ids")
                    if isinstance(args.get("affected_task_ids"), list)
                    else None,
                    affected_span_ids=args.get("affected_span_ids")
                    if isinstance(args.get("affected_span_ids"), list)
                    else None,
                    proposal_ids=args.get("proposal_ids")
                    if isinstance(args.get("proposal_ids"), list)
                    else None,
                )
            },
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_submit_issue",
            title="Kyoko Submit Issue",
            description=(
                "Submit one diagnosed `kyoko.issue.v1` issue (the diagnosis-turn contract): "
                "Kyoko validates it (schema + referential integrity) and surfaces it through "
                "the deterministic dedup net (folding a recurrence into an existing issue). "
                "Evidence only — surfacing an issue never authors a proposal, applies a "
                "change, or bypasses the check/replay gate."
            ),
            input_schema=_object_schema(
                {"issue": {"type": "object"}},
                required=["issue"],
            ),
            handler=lambda args: _submit_issue(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_run_doctor",
            title="Run Kyoko Doctor",
            description=(
                "Run local first-run readiness checks and optional no-live-model smokes. "
                "Set safe_smokes=true to run the bundled demo, operator prepare-only, "
                "judge prepare-only, native ACE prepare-only, generated integration, "
                "generated improve, and isolated MCP install smokes."
                " Set opentelemetry_smoke=true to run the installed OpenTelemetry "
                "SDK smoke. Set ace_native_smoke=true to run the installed ACE "
                "Skillbook smoke. Set dashboard_smoke=true to run a browser "
                "smoke against the local dashboard."
            ),
            input_schema=_object_schema(
                {
                    "smoke_demo": {"type": "boolean"},
                    "operator_smoke_prepare": {"type": "boolean"},
                    "judge_smoke_prepare": {"type": "boolean"},
                    "ace_native_prepare": {"type": "boolean"},
                    "integration_smoke": {"type": "boolean"},
                    "improve_smoke": {"type": "boolean"},
                    "opentelemetry_smoke": {"type": "boolean"},
                    "opentelemetry_python_executable": {"type": "string"},
                    "ace_native_smoke": {"type": "boolean"},
                    "dashboard_smoke": {"type": "boolean"},
                    "dashboard_smoke_screenshot": {"type": "boolean"},
                    "dashboard_smoke_install_browser_deps": {"type": "boolean"},
                    "dashboard_smoke_timeout_seconds": {
                        "type": "integer",
                        "minimum": 1,
                    },
                    "safe_smokes": {"type": "boolean"},
                    "smoke_output_dir": {"type": "string"},
                    "smoke_evidence_dir": {"type": "string"},
                    "ace_path": {"type": "string"},
                    "host": {"type": "string"},
                    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                }
            ),
            handler=lambda args: _run_doctor(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_discover_sources",
            title="Kyoko Source Discovery",
            description="Find local Hermes Kanban and OpenClaw session stores and return import-ready commands without importing data.",
            input_schema=_object_schema(
                {
                    "home": {"type": "string"},
                    "profile_id": {"type": "string"},
                    "profile_name": {"type": "string"},
                    "root_path": {"type": "string"},
                    "include_missing": {"type": "boolean"},
                }
            ),
            handler=lambda args: discover_local_sources(
                db_path=server.db_path,
                home=_optional_path(args, "home"),
                profile_id=_optional_string(args, "profile_id"),
                profile_name=_optional_string(args, "profile_name"),
                root_path=_optional_path(args, "root_path"),
                include_missing=bool(args.get("include_missing") is True),
            ).to_json(),
        ),
        McpTool(
            name="kyoko_get_storage_report",
            title="Kyoko Storage Report",
            description="Return database size, registered payload blobs, missing blob files, and orphan blob files.",
            input_schema=_object_schema({}),
            handler=lambda _args: storage_report(server.db_path).to_json(),
        ),
        McpTool(
            name="kyoko_list_payload_blobs",
            title="Kyoko Payload Blobs",
            description="List registered content-addressed payload blobs and metadata.",
            input_schema=_object_schema({"profile_id": {"type": "string"}}),
            handler=lambda args: {
                "payload_blobs": list_payload_blobs(
                    server.db_path,
                    profile_id=_optional_string(args, "profile_id"),
                )
            },
        ),
        McpTool(
            name="kyoko_prune_payload_blobs_dry_run",
            title="Kyoko Payload Blob Prune Dry Run",
            description="Preview payload blobs that would be pruned without deleting files or database rows.",
            input_schema=_object_schema(
                {
                    "profile_id": {"type": "string"},
                    "older_than_days": {"type": "integer", "minimum": 0},
                }
            ),
            handler=lambda args: prune_payload_blobs(
                server.db_path,
                profile_id=_optional_string(args, "profile_id"),
                older_than_days=_optional_non_negative_int(args, "older_than_days"),
                dry_run=True,
            ).to_json(),
        ),
        McpTool(
            name="kyoko_get_evidence",
            title="Kyoko Evidence Bundle",
            description="Return canonical profile/run/task/span/handoff/check evidence for analysis.",
            input_schema=_object_schema(
                {
                    "profile_id": {"type": "string"},
                    "run_id": {"type": "string"},
                }
            ),
            handler=lambda args: build_evidence_bundle(
                db_path=server.db_path,
                profile_id=_optional_string(args, "profile_id"),
                run_id=_optional_string(args, "run_id"),
                consumer="mcp:kyoko_get_evidence",
            ),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_runs",
            title="Kyoko Runs",
            description="List recent local runs with span, failure, and handoff counts.",
            input_schema=_object_schema(
                {
                    "profile_id": {"type": "string"},
                    "limit": {"type": "integer"},
                }
            ),
            handler=lambda args: {
                "runs": list_runs(
                    db_path=server.db_path,
                    profile_id=_optional_string(args, "profile_id"),
                    limit=_optional_int(args, "limit", 50),
                )
            },
        ),
        McpTool(
            name="kyoko_get_run_detail",
            title="Kyoko Run Detail",
            description="Return spans, handoffs, task context, timeline, replay links, and related proposals for a run.",
            input_schema=_object_schema(
                {"run_id": {"type": "string"}},
                required=["run_id"],
            ),
            handler=lambda args: get_run_detail(
                db_path=server.db_path,
                run_id=_required_string(args, "run_id"),
            ),
        ),
        McpTool(
            name="kyoko_list_proposals",
            title="Kyoko Learning Proposals",
            description="List persisted learning proposals (optionally filtered by state).",
            input_schema=_object_schema(
                {
                    "profile_id": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["pending", "applied", "rolled_back", "failed"],
                    },
                }
            ),
            handler=lambda args: {
                "proposals": list_learning_proposals(
                    server.db_path,
                    profile_id=_optional_string(args, "profile_id"),
                    state=_optional_string(args, "state"),
                )
            },
        ),
        McpTool(
            name="kyoko_get_proposal_detail",
            title="Kyoko Proposal Detail",
            description="Return target, evidence, check, replay, patch, timeline, and autonomy gate detail for a proposal.",
            input_schema=_object_schema(
                {"proposal_id": {"type": "string"}},
                required=["proposal_id"],
            ),
            handler=lambda args: get_proposal_detail(
                db_path=server.db_path,
                proposal_id=_required_string(args, "proposal_id"),
            ),
        ),
        McpTool(
            name="kyoko_get_policy",
            title="Kyoko Autonomy Policy",
            description="Return the current context and harness autonomy policy.",
            input_schema=_object_schema({"profile_id": {"type": "string"}}),
            handler=lambda args: {
                "policy": get_autonomy_policy(
                    db_path=server.db_path,
                    profile_id=_optional_string(args, "profile_id"),
                )
            },
        ),
        McpTool(
            name="kyoko_prune_retention_dry_run",
            title="Kyoko Retention Prune Dry Run",
            description="Preview trace, replay, check, and operator rows that would be pruned without deleting data.",
            input_schema=_object_schema(
                {
                    "profile_id": {"type": "string"},
                    "trace_older_than_days": {"type": "integer", "minimum": 0},
                    "replay_older_than_days": {"type": "integer", "minimum": 0},
                    "operator_older_than_days": {"type": "integer", "minimum": 0},
                }
            ),
            handler=lambda args: prune_retained_data(
                db_path=server.db_path,
                profile_id=_optional_string(args, "profile_id"),
                trace_older_than_days=_optional_non_negative_int(args, "trace_older_than_days"),
                replay_older_than_days=_optional_non_negative_int(args, "replay_older_than_days"),
                operator_older_than_days=_optional_non_negative_int(args, "operator_older_than_days"),
                dry_run=True,
            ).to_json(),
        ),
        McpTool(
            name="kyoko_submit_proposal",
            title="Submit Kyoko Learning Proposal",
            description="Validate and persist one LearningProposal JSON object.",
            input_schema=_object_schema(
                {"proposal": {"type": "object"}},
                required=["proposal"],
            ),
            handler=lambda args: _submit_proposal(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_get_context",
            title="Kyoko Context",
            description="Render active skillbook context for an agent prompt.",
            input_schema=_object_schema(
                {
                    "section": {"type": "string", "enum": ["context", "harness", "all"]},
                    "include_inactive": {"type": "boolean"},
                    "target_type": {"type": "string"},
                    "target_id": {"type": "string"},
                }
            ),
            handler=lambda args: _get_context_payload(server, args),
        ),
        McpTool(
            name="kyoko_list_skills",
            title="Kyoko Skills",
            description="List ACE-compatible skillbook entries.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"skills": list_skills(server.db_path)},
        ),
        McpTool(
            name="kyoko_list_skill_revisions",
            title="Kyoko Skill Revisions",
            description="List skillbook write revisions with before/after snapshots.",
            input_schema=_object_schema({"skill_id": {"type": "string"}}),
            handler=lambda args: {
                "skill_revisions": list_skill_revisions(
                    server.db_path,
                    skill_id=str(args["skill_id"]) if args.get("skill_id") else None,
                )
            },
        ),
        McpTool(
            name="kyoko_rollback_skill_revision",
            title="Rollback Kyoko Skill Revision",
            description="Rollback the latest skillbook revision.",
            input_schema=_object_schema(
                {"revision_id": {"type": "string"}},
                required=["revision_id"],
            ),
            handler=lambda args: rollback_skill_revision(
                db_path=server.db_path,
                revision_id=str(args["revision_id"]),
            ).to_json(),
            read_only=False,
            destructive=True,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_context_rules",
            title="Kyoko Context Delivery Rules",
            description="List active context delivery rules.",
            input_schema=_object_schema({"include_inactive": {"type": "boolean"}}),
            handler=lambda args: {
                "context_delivery_rules": list_context_delivery_rules(
                    server.db_path,
                    active_only=not bool(args.get("include_inactive", False)),
                )
            },
        ),
        McpTool(
            name="kyoko_list_context_rule_revisions",
            title="Kyoko Context Rule Revisions",
            description="List context delivery rule write revisions with before/after snapshots.",
            input_schema=_object_schema({"rule_id": {"type": "string"}}),
            handler=lambda args: {
                "context_delivery_rule_revisions": list_context_delivery_rule_revisions(
                    server.db_path,
                    rule_id=str(args["rule_id"]) if args.get("rule_id") else None,
                )
            },
        ),
        McpTool(
            name="kyoko_rollback_context_rule_revision",
            title="Rollback Kyoko Context Rule Revision",
            description="Rollback the latest context delivery rule revision.",
            input_schema=_object_schema(
                {"revision_id": {"type": "string"}},
                required=["revision_id"],
            ),
            handler=lambda args: rollback_context_delivery_rule_revision(
                db_path=server.db_path,
                revision_id=str(args["revision_id"]),
            ).to_json(),
            read_only=False,
            destructive=True,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_checks",
            title="Kyoko Checks And Replay",
            description="List check specs, check runs, and replay runs.",
            input_schema=_object_schema({}),
            handler=lambda _args: {
                "check_specs": list_check_specs(server.db_path),
                "check_runs": list_check_runs(server.db_path),
                "replay_runs": list_replay_runs(server.db_path),
            },
        ),
        McpTool(
            name="kyoko_list_check_assertion_presets",
            title="Kyoko Check Assertion Presets",
            description="List supported check assertion presets and their concrete assertion expansions.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"assertion_presets": list_assertion_presets()},
        ),
        McpTool(
            name="kyoko_get_check_capabilities",
            title="Kyoko Check Capabilities",
            description="List supported check types, assertions, presets, replay modes, side-effect modes, and trust levels.",
            input_schema=_object_schema({}),
            handler=lambda _args: list_check_capabilities(),
        ),
        McpTool(
            name="kyoko_list_check_locks",
            title="Kyoko Check Spec Locks",
            description="List active human locks for check specs.",
            input_schema=_object_schema({"include_unlocked": {"type": "boolean"}}),
            handler=lambda args: {
                "check_locks": list_check_locks(
                    server.db_path,
                    locked_only=not bool(args.get("include_unlocked", False)),
                )
            },
        ),
        McpTool(
            name="kyoko_get_check_detail",
            title="Kyoko Check Detail",
            description="Return target, check runs, replay runs, and gate evidence for an check spec.",
            input_schema=_object_schema(
                {"check_spec_id": {"type": "string"}},
                required=["check_spec_id"],
            ),
            handler=lambda args: get_check_detail(
                db_path=server.db_path,
                check_spec_id=_required_string(args, "check_spec_id"),
            ),
        ),
        McpTool(
            name="kyoko_get_replay_detail",
            title="Kyoko Replay Detail",
            description="Return source/output runs, side-effect metadata, spans, and linked check runs for a replay run.",
            input_schema=_object_schema(
                {"replay_run_id": {"type": "string"}},
                required=["replay_run_id"],
            ),
            handler=lambda args: get_replay_detail(
                db_path=server.db_path,
                replay_run_id=_required_string(args, "replay_run_id"),
            ),
        ),
        McpTool(
            name="kyoko_generate_checks",
            title="Generate Kyoko Checks",
            description="Create check specs from a validated LearningProposal.",
            input_schema=_object_schema(
                {"proposal_id": {"type": "string"}},
                required=["proposal_id"],
            ),
            handler=lambda args: _generate_checks(server, args),
            read_only=False,
            idempotent=True,
        ),
        McpTool(
            name="kyoko_run_check",
            title="Run Kyoko Check",
            description="Run a Kyoko check spec.",
            input_schema=_object_schema(
                {
                    "check_spec_id": {"type": "string"},
                    "replay_run_id": {"type": "string"},
                },
                required=["check_spec_id"],
            ),
            handler=lambda args: _run_check(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_run_judge_command",
            title="Run Kyoko Judge Command",
            description=(
                "Run an explicit external judge command for a judge check. "
                "The command may invoke a live/provider model and the captured "
                "verdict remains non-gateable."
            ),
            input_schema=_object_schema(
                {
                    "check_spec_id": {"type": "string"},
                    "command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ]
                    },
                    "output_dir": {"type": "string"},
                    "replay_run_id": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                },
                required=["check_spec_id", "command", "output_dir"],
            ),
            handler=lambda args: _run_judge_command(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_replay_adapters",
            title="Kyoko Replay Adapters",
            description="List registered replay adapters available for gated replay.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"replay_adapters": list_replay_adapters(server.db_path)},
        ),
        McpTool(
            name="kyoko_run_replay_adapter",
            title="Run Kyoko Replay Adapter",
            description="Run a registered replay adapter for an check spec and optionally run the check.",
            input_schema=_object_schema(
                {
                    "adapter_id": {"type": "string"},
                    "check_spec_id": {"type": "string"},
                    "run_check": {"type": "boolean"},
                },
                required=["adapter_id", "check_spec_id"],
            ),
            handler=lambda args: _run_replay_adapter(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_run_improve",
            title="Run Kyoko Improve",
            description=(
                "Run the non-applying improvement pipeline: optional discovered-source import, "
                "operator proposal, check generation, and selected or latest enabled replay. "
                "MCP improve never runs autonomy/apply."
            ),
            input_schema=_object_schema(
                {
                    "proposal_id": {"type": "string"},
                    "operator": {"type": "string"},
                    "operator_adapter": {"type": "string"},
                    "profile_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "source_candidate_id": {"type": "string"},
                    "source_home": {"type": "string"},
                    "source_import_output_dir": {"type": "string"},
                    "replay_adapter_id": {"type": "string"},
                    "replay_output_dir": {"type": "string"},
                    "replay_timeout_seconds": {"type": "integer", "minimum": 1},
                    "operator_timeout_seconds": {"type": "integer", "minimum": 1},
                    "operator_max_retries": {"type": "integer", "minimum": 0},
                }
            ),
            handler=lambda args: _run_improve(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_operator_adapters",
            title="Kyoko Operator Adapters",
            description="List registered local operator-agent adapters.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"operator_adapters": list_operator_adapters(server.db_path)},
        ),
        McpTool(
            name="kyoko_prepare_operator_smoke_matrix",
            title="Prepare Kyoko Operator Smoke Matrix",
            description=(
                "Prepare evidence/prompt artifacts for built-in operator presets without invoking "
                "live operator CLIs. Missing preset executables are skipped unless fail_on_missing is true."
            ),
            input_schema=_object_schema(
                {
                    "operators": {"type": "array", "items": {"type": "string"}},
                    "output_dir": {"type": "string"},
                    "profile_id": {"type": "string"},
                    "run_id": {"type": "string"},
                    "schema_path": {"type": "string"},
                    "fail_on_missing": {"type": "boolean"},
                }
            ),
            handler=lambda args: _prepare_operator_smoke_matrix(server, args),
            read_only=False,
            idempotent=False,
        ),
        McpTool(
            name="kyoko_list_operator_runs",
            title="Kyoko Operator Runs",
            description="List recorded operator-agent analysis runs.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"operator_runs": list_operator_runs(server.db_path)},
        ),
        McpTool(
            name="kyoko_list_harness_patches",
            title="Kyoko Harness Patches",
            description="List prepared harness patch transactions.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"patch_transactions": list_patch_transactions(server.db_path)},
        ),
        McpTool(
            name="kyoko_list_harness_target_locks",
            title="Kyoko Harness Target Locks",
            description="List active human locks for harness target paths.",
            input_schema=_object_schema({}),
            handler=lambda _args: {"harness_target_locks": list_harness_target_locks(server.db_path)},
        ),
        # ---- eval (Python detector) measurement plane — evidence only ----
        McpTool(
            name="kyoko_list_evals",
            title="Kyoko List Evals",
            description=(
                "List registered and bundled Python detector definitions. "
                "Detectors are deterministic evidence-only tools that score a trace "
                "corpus; they never write a check_run, mutate a skill, or edit harness files."
            ),
            input_schema=_object_schema({"profile_id": {"type": "string"}}),
            handler=lambda args: {
                "detectors": list_detectors(
                    db_path=server.db_path,
                    profile_id=_optional_string(args, "profile_id"),
                )
            },
        ),
        McpTool(
            name="kyoko_eval_run_detail",
            title="Kyoko Eval Run Detail",
            description=(
                "Return one eval measurement run plus its per-event results. "
                "Evidence only — no gate or apply path."
            ),
            input_schema=_object_schema(
                {"eval_run_id": {"type": "string"}},
                required=["eval_run_id"],
            ),
            handler=lambda args: _eval_run_detail(server, args),
        ),
        McpTool(
            name="kyoko_run_eval",
            title="Run Kyoko Eval",
            description=(
                "Run a Python detector over a corpus of run traces and return "
                "numerator/denominator aggregate plus per-event hit flags. "
                "Evidence only — the result never writes a check_run, mutates a skill, "
                "or edits a harness file. Set persist=true to record the run in the database."
            ),
            input_schema=_object_schema(
                {
                    "detector_id": {"type": "string"},
                    "corpus": {
                        "type": "object",
                        "description": (
                            "Corpus selector: unit (event|run|llm_span), "
                            "source_id, run_ids, since, until, span_filter, limit."
                        ),
                    },
                    "persist": {"type": "boolean"},
                    "profile_id": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "raise_issues": {
                        "type": "boolean",
                        "description": "When true, create an Issue if the score crosses threshold. Requires threshold.",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Score threshold for raise_issues. Required when raise_issues=true.",
                    },
                },
                required=["detector_id", "corpus"],
            ),
            handler=lambda args: _run_eval(server, args),
            read_only=False,
            idempotent=False,
        ),
        # ---- eval compare — read-only, evidence only ----
        McpTool(
            name="kyoko_eval_compare",
            title="Kyoko Eval Compare",
            description=(
                "Compare two Python detector eval measurement runs and return delta, "
                "direction, and metric metadata. Evidence only — no gate or apply path."
            ),
            input_schema=_object_schema(
                {
                    "baseline_run_id": {"type": "string"},
                    "compare_run_id": {"type": "string"},
                },
                required=["baseline_run_id", "compare_run_id"],
            ),
            handler=lambda args: _eval_compare(server, args),
            read_only=True,
        ),
        # ---- llm_eval (LLM-as-judge) measurement plane — evidence only ----
        McpTool(
            name="kyoko_list_llm_evals",
            title="Kyoko List LLM Evals",
            description=(
                "List registered and bundled LLM-as-judge eval definitions. "
                "LLM evals are evidence-only tools that score a trace corpus using a "
                "model judge command; they never write a check_run, mutate a skill, or "
                "edit harness files."
            ),
            input_schema=_object_schema({"profile_id": {"type": "string"}}),
            handler=lambda args: {
                "llm_evals": list_llm_evals(
                    db_path=server.db_path,
                    profile_id=_optional_string(args, "profile_id"),
                )
            },
        ),
        McpTool(
            name="kyoko_llm_eval_run_detail",
            title="Kyoko LLM Eval Run Detail",
            description=(
                "Return one LLM eval measurement run plus its per-event results. "
                "Evidence only — no gate or apply path."
            ),
            input_schema=_object_schema(
                {"eval_run_id": {"type": "string"}},
                required=["eval_run_id"],
            ),
            handler=lambda args: _llm_eval_run_detail(server, args),
        ),
        McpTool(
            name="kyoko_run_llm_eval",
            title="Run Kyoko LLM Eval",
            description=(
                "Run an LLM-as-judge eval over a corpus of run traces and return "
                "aggregate score plus per-event results. Supply a BYO judge command "
                "or the eval definition's default will be used. "
                "Evidence only — the result never writes a check_run, mutates a skill, "
                "or edits a harness file. Set persist=true to record the run in the database."
            ),
            input_schema=_object_schema(
                {
                    "llm_eval_id": {"type": "string"},
                    "corpus": {
                        "type": "object",
                        "description": (
                            "Corpus selector: unit (llm_span|run), "
                            "source_id, run_ids, since, until, span_filter, limit."
                        ),
                    },
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "BYO judge command argv. Uses the eval definition default if absent.",
                    },
                    "persist": {"type": "boolean"},
                    "prepare_only": {"type": "boolean"},
                    "profile_id": {"type": "string"},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "raise_issues": {
                        "type": "boolean",
                        "description": "When true, create an Issue if the score crosses threshold. Requires threshold.",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Score threshold for raise_issues. Required when raise_issues=true.",
                    },
                },
                required=["llm_eval_id", "corpus"],
            ),
            handler=lambda args: _run_llm_eval(server, args),
            read_only=False,
            idempotent=False,
        ),
        # ---- llm_eval compare — read-only, evidence only ----
        McpTool(
            name="kyoko_llm_eval_compare",
            title="Kyoko LLM Eval Compare",
            description=(
                "Compare two LLM-as-judge eval measurement runs and return delta, "
                "direction, and metric metadata. Evidence only — no gate or apply path."
            ),
            input_schema=_object_schema(
                {
                    "baseline_run_id": {"type": "string"},
                    "compare_run_id": {"type": "string"},
                },
                required=["baseline_run_id", "compare_run_id"],
            ),
            handler=lambda args: _llm_eval_compare(server, args),
            read_only=True,
        ),
    ]
    return {tool.name: tool for tool in tools}


def _get_context_payload(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    """Render the active skillbook context for a prompt and, on a real (non-preview)
    fetch, bump ``used_count`` on the active entries injected (ACE ``mark_used``)."""

    section = str(args.get("section", "context"))
    include_inactive = bool(args.get("include_inactive", False))
    target_type = str(args["target_type"]) if args.get("target_type") else None
    target_id = str(args["target_id"]) if args.get("target_id") else None
    context = render_skillbook_prompt(
        server.db_path,
        section=section,
        include_inactive=include_inactive,
        target_entity_type=target_type,
        target_entity_id=target_id,
    )
    if not include_inactive:
        try:
            injected = export_skillbook(
                server.db_path, section=section if section in {"context", "harness"} else "all"
            )
            mark_skills_used(server.db_path, list(injected.get("skills", {}).keys()))
        except Exception:  # pragma: no cover - usage telemetry must never break a fetch
            pass
    return {
        "section": args.get("section", "context"),
        "target": {"entity_type": target_type, "entity_id": target_id}
        if target_type and target_id
        else None,
        "context": context,
    }


def _submit_proposal(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    proposal = args.get("proposal")
    if not isinstance(proposal, dict):
        raise McpError("proposal_object_required")
    # Issue-centric spine: every proposal originates from an Issue. If the agent did not
    # reference an existing issue, surface one now from the proposal's own evidence so a
    # proposal can never exist without an origin. Still pure propose — no apply.
    originated_issue = None
    if not proposal.get("issue_id"):
        originated_issue = _surface_issue_for_proposal(server.db_path, proposal)
        if originated_issue is not None:
            proposal["issue_id"] = originated_issue["id"]
    report = submit_learning_proposal_payload(
        db_path=server.db_path,
        proposal=proposal,
        schema_path=server.schema_path,
    )
    if originated_issue is not None:
        link_proposal_to_issue(
            db_path=server.db_path,
            issue_id=originated_issue["id"],
            proposal_id=report.proposal_id,
        )
    return {
        "proposal_id": report.proposal_id,
        "profile_id": report.profile_id,
        "state": report.state,
        "section": report.section,
        "title": report.title,
        "issue_id": proposal.get("issue_id"),
    }


def _submit_issue(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    issue = args.get("issue")
    if not isinstance(issue, dict):
        raise McpError("issue_object_required")
    from .storage import connect

    initialize_database(server.db_path)
    with connect(server.db_path) as connection:
        # Validate against the kyoko.issue.v1 schema (None => bundled issue schema), NOT
        # server.schema_path, which is the LearningProposal schema.
        result = validate_issue(
            connection=connection,
            issue=issue,
            schema_path=None,
        )
    if not result.ok:
        raise McpError("issue_invalid:" + ",".join(result.errors))

    section = issue.get("section")
    surfaced, bundled = surface_issue(
        db_path=server.db_path,
        title=str(issue.get("title")),
        body=issue.get("body") if isinstance(issue.get("body"), str) else None,
        section=section if section in ("context", "harness") else None,
        severity=issue.get("severity") if isinstance(issue.get("severity"), str) else None,
        status="diagnosed" if issue.get("root_cause") else "open",
        evidence_refs=issue.get("evidence_refs")
        if isinstance(issue.get("evidence_refs"), list)
        else None,
        affected_span_ids=issue.get("affected_span_ids")
        if isinstance(issue.get("affected_span_ids"), list)
        else None,
        affected_agent_identity_ids=issue.get("affected_agent_identity_ids")
        if isinstance(issue.get("affected_agent_identity_ids"), list)
        else None,
        root_cause=issue.get("root_cause") if isinstance(issue.get("root_cause"), str) else None,
        source=issue.get("source") if issue.get("source") in ("analysis", "eval", "llm_eval", "manual") else "analysis",
        profile_id=issue.get("profile_id") if isinstance(issue.get("profile_id"), str) else None,
    )
    return {"issue": surfaced, "bundled": bundled}


def _surface_issue_for_proposal(
    db_path: Path, proposal: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Surface the originating Issue for an agent-submitted proposal (deterministic dedup
    net). Mirrors the diagnosis-turn surfacing: section/evidence/root-cause are derived from
    the proposal's own problem block. Evidence only — never changes behavior."""

    problem = proposal.get("problem") if isinstance(proposal.get("problem"), dict) else {}
    raw_title = problem.get("issue") or proposal.get("title") or "Surfaced agent failure"
    title = str(raw_title).strip()[:500] or "Surfaced agent failure"
    section = proposal.get("section") if proposal.get("section") in ("context", "harness") else None
    evidence_refs = proposal.get("evidence_refs") if isinstance(proposal.get("evidence_refs"), list) else None
    root_cause = proposal.get("insight") if isinstance(proposal.get("insight"), str) else None
    if not root_cause:
        rc = problem.get("root_cause") if isinstance(problem, dict) else None
        root_cause = rc if isinstance(rc, str) and rc.strip() else None
    body = proposal.get("summary") if isinstance(proposal.get("summary"), str) else None

    span_ids: list[str] = []
    target = problem.get("target") if isinstance(problem, dict) else None
    if (
        isinstance(target, dict)
        and target.get("entity_type") == "span"
        and isinstance(target.get("entity_id"), str)
    ):
        span_ids = [target["entity_id"]]

    issue, _bundled = surface_issue(
        db_path=db_path,
        title=title,
        body=body,
        section=section,
        category="analysis",
        status="diagnosed" if root_cause else "open",
        evidence_refs=evidence_refs,
        affected_span_ids=span_ids or None,
        source="analysis",
        root_cause=root_cause,
        profile_id=proposal.get("profile_id"),
    )
    return issue


def _generate_checks(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    proposal_id = _required_string(args, "proposal_id")
    report = generate_checks_for_proposal(db_path=server.db_path, proposal_id=proposal_id)
    return {
        "proposal_id": report.proposal_id,
        "profile_id": report.profile_id,
        "check_spec_ids": list(report.check_spec_ids),
        "existing_check_spec_ids": list(report.existing_check_spec_ids),
    }


def _run_check(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    report = run_check(
        db_path=server.db_path,
        check_spec_id=_required_string(args, "check_spec_id"),
        replay_run_id=_optional_string(args, "replay_run_id"),
    )
    return {
        "check_run_id": report.check_run_id,
        "profile_id": report.profile_id,
        "proposal_id": report.proposal_id,
        "check_spec_id": report.check_spec_id,
        "replay_run_id": report.replay_run_id,
        "status": report.status,
        "result": report.result,
        "promoted_trust_level": report.promoted_trust_level,
    }


def _run_judge_command(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    output_dir = _optional_path(args, "output_dir")
    if output_dir is None:
        raise McpError("output_dir_required")
    report = run_judge_command(
        db_path=server.db_path,
        check_spec_id=_required_string(args, "check_spec_id"),
        output_dir=output_dir,
        command=_required_command(args, "command"),
        replay_run_id=_optional_string(args, "replay_run_id"),
        timeout_seconds=_optional_positive_int(args, "timeout_seconds", 120),
    )
    return _judge_command_payload(report)


def _run_replay_adapter(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    report = run_registered_replay_adapter(
        db_path=server.db_path,
        adapter_id=_required_string(args, "adapter_id"),
        check_spec_id=_required_string(args, "check_spec_id"),
        run_check_after=bool(args.get("run_check", True)),
    )
    return _replay_report_payload(report)


def _run_improve(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    try:
        report = run_improvement_loop(
            db_path=server.db_path,
            proposal_id=_optional_string(args, "proposal_id"),
            operator=_optional_string(args, "operator") or "mock",
            operator_adapter=_optional_string(args, "operator_adapter"),
            operator_timeout_seconds=_optional_positive_int(args, "operator_timeout_seconds", 120),
            operator_max_retries=_optional_non_negative_int(args, "operator_max_retries") or 0,
            profile_id=_optional_string(args, "profile_id"),
            run_id=_optional_string(args, "run_id"),
            schema_path=server.schema_path,
            run_autonomy_after=False,
            source_candidate_id=_optional_string(args, "source_candidate_id"),
            source_home=_optional_path(args, "source_home"),
            source_import_output_dir=_optional_path(args, "source_import_output_dir"),
        )
    except ImproveError as exc:
        raise McpError(str(exc)) from exc
    payload = report.to_json()
    payload["mcp_autonomy_disabled"] = True
    return payload


def _run_doctor(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    try:
        report = run_doctor(
            db_path=server.db_path,
            smoke_demo=bool(args.get("smoke_demo", False)),
            operator_smoke_prepare=bool(args.get("operator_smoke_prepare", False)),
            judge_smoke_prepare=bool(args.get("judge_smoke_prepare", False)),
            ace_native_prepare=bool(args.get("ace_native_prepare", False)),
            integration_smoke=bool(args.get("integration_smoke", False)),
            improve_smoke=bool(args.get("improve_smoke", False)),
            opentelemetry_smoke=bool(args.get("opentelemetry_smoke", False)),
            opentelemetry_python_executable=_optional_path(
                args, "opentelemetry_python_executable"
            ),
            ace_native_smoke=bool(args.get("ace_native_smoke", False)),
            dashboard_smoke=bool(args.get("dashboard_smoke", False)),
            dashboard_smoke_screenshot=bool(args.get("dashboard_smoke_screenshot", False)),
            dashboard_smoke_install_browser_deps=bool(
                args.get("dashboard_smoke_install_browser_deps", False)
            ),
            dashboard_smoke_timeout_seconds=int(
                args.get("dashboard_smoke_timeout_seconds") or 30
            ),
            safe_smokes=bool(args.get("safe_smokes", False)),
            smoke_output_dir=_optional_path(args, "smoke_output_dir"),
            smoke_evidence_dir=_optional_path(args, "smoke_evidence_dir")
            or DEFAULT_SMOKE_EVIDENCE_DIR,
            ace_path=_optional_path(args, "ace_path"),
            host=_optional_string(args, "host") or "127.0.0.1",
            port=_optional_port(args, "port", 8765),
        )
    except DoctorError as exc:
        raise McpError(str(exc)) from exc
    return report.to_json()


def _run_profile_next_step(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    try:
        report = run_profile_next_step(
            db_path=server.db_path,
            profile_id=_optional_string(args, "profile_id"),
            run=bool(args.get("run", False)),
            replay_adapter_id=_optional_string(args, "replay_adapter_id"),
            replay_output_dir=_optional_path(args, "replay_output_dir"),
            replay_timeout_seconds=_optional_positive_int_or_none(args, "replay_timeout_seconds"),
            harness_workspace_root=_optional_path(args, "harness_workspace_root"),
            operator_adapter_id=_optional_string(args, "operator_adapter_id"),
            operator_target=_optional_string(args, "operator_target"),
            operator_output_dir=_optional_path(args, "operator_output_dir"),
            operator_timeout_seconds=_optional_positive_int_or_none(args, "operator_timeout_seconds"),
            operator_max_retries=_optional_non_negative_int(args, "operator_max_retries") or 0,
            schema_path=_optional_path(args, "schema_path"),
        )
    except ProfileNextError as exc:
        raise McpError(str(exc)) from exc
    return report.to_json()


def _prepare_operator_smoke_matrix(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    try:
        report = run_operator_smoke_matrix(
            operators=_optional_string_list(args, "operators"),
            prepare_only=True,
            db_path=server.db_path,
            output_dir=_optional_path(args, "output_dir"),
            profile_id=_optional_string(args, "profile_id"),
            run_id=_optional_string(args, "run_id"),
            schema_path=_optional_path(args, "schema_path") or server.schema_path,
            skip_missing=not bool(args.get("fail_on_missing", False)),
        )
    except OperatorSmokeError as exc:
        raise McpError(str(exc)) from exc
    payload = report.to_json()
    payload["live_operator_invoked"] = False
    return payload


def _replay_report_payload(report: object) -> dict[str, Any]:
    completion = getattr(report, "completion")
    check_run = getattr(report, "check_run", None)
    payload: dict[str, Any] = {
        "replay_run_id": getattr(report, "replay_run_id"),
        "profile_id": getattr(report, "profile_id"),
        "check_spec_id": getattr(report, "check_spec_id"),
        "output_run_id": completion.output_run_id,
        "status": completion.status,
        "result": completion.result,
        "check_run": {
            "check_run_id": check_run.check_run_id,
            "status": check_run.status,
            "promoted_trust_level": check_run.promoted_trust_level,
            "result": check_run.result,
        }
        if check_run is not None
        else None,
    }
    for attr in (
        "request_path",
        "result_path",
        "raw_output_path",
        "server_url",
        "replay_path",
        "stdout_path",
        "stderr_path",
        "exit_code",
    ):
        if hasattr(report, attr):
            payload[attr] = str(getattr(report, attr))
    if hasattr(report, "command"):
        payload["command"] = list(getattr(report, "command"))
    health = getattr(report, "health", None)
    if health is not None:
        payload["health"] = {
            "server_url": health.server_url,
            "health_path": health.health_path,
            "ok": health.ok,
            "response": health.response,
        }
    return {
        **payload,
    }


def _judge_command_payload(report: object) -> dict[str, Any]:
    check_run = getattr(report, "check_run")
    return {
        "profile_id": getattr(report, "profile_id"),
        "proposal_id": getattr(report, "proposal_id"),
        "check_spec_id": getattr(report, "check_spec_id"),
        "request_path": str(getattr(report, "request_path")),
        "result_path": str(getattr(report, "result_path")),
        "raw_output_path": str(getattr(report, "raw_output_path")),
        "judgment": getattr(report, "judgment"),
        "check_run": {
            "check_run_id": check_run.check_run_id,
            "profile_id": check_run.profile_id,
            "proposal_id": check_run.proposal_id,
            "check_spec_id": check_run.check_spec_id,
            "replay_run_id": check_run.replay_run_id,
            "status": check_run.status,
            "result": check_run.result,
            "promoted_trust_level": check_run.promoted_trust_level,
        },
    }


def _eval_run_detail(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    eval_run_id = _required_string(args, "eval_run_id")
    return {
        "eval_run": get_measure_run(db_path=server.db_path, eval_run_id=eval_run_id),
        "results": get_measure_results(db_path=server.db_path, eval_run_id=eval_run_id),
    }


def _run_eval(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    corpus = args.get("corpus")
    if not isinstance(corpus, dict):
        raise McpError("corpus_object_required")
    raise_issues_raw = args.get("raise_issues")
    raise_issues = bool(raise_issues_raw) if raise_issues_raw is not None else False
    threshold_raw = args.get("threshold")
    issue_threshold = float(threshold_raw) if threshold_raw is not None else None
    report = run_detector(
        db_path=server.db_path,
        detector_id=_required_string(args, "detector_id"),
        corpus=corpus,
        persist=bool(args.get("persist", False)),
        profile_id=_optional_string(args, "profile_id"),
        timeout_seconds=_optional_positive_int(args, "timeout_seconds", 120),
        raise_issues=raise_issues,
        issue_threshold=issue_threshold,
    )
    return report.to_json()


def _eval_compare(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    return compare_eval_runs(
        db_path=server.db_path,
        baseline_run_id=_required_string(args, "baseline_run_id"),
        compare_run_id=_required_string(args, "compare_run_id"),
    )


def _llm_eval_run_detail(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    eval_run_id = _required_string(args, "eval_run_id")
    return {
        "eval_run": get_measure_run(db_path=server.db_path, eval_run_id=eval_run_id),
        "results": get_measure_results(db_path=server.db_path, eval_run_id=eval_run_id),
    }


def _run_llm_eval(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    corpus = args.get("corpus")
    if not isinstance(corpus, dict):
        raise McpError("corpus_object_required")
    command_raw = args.get("command")
    command: Optional[list[str]] = list(command_raw) if isinstance(command_raw, list) else None
    raise_issues_raw = args.get("raise_issues")
    raise_issues = bool(raise_issues_raw) if raise_issues_raw is not None else False
    threshold_raw = args.get("threshold")
    issue_threshold = float(threshold_raw) if threshold_raw is not None else None
    report = run_llm_eval(
        db_path=server.db_path,
        llm_eval_id=_required_string(args, "llm_eval_id"),
        corpus=corpus,
        command=command,
        persist=bool(args.get("persist", False)),
        prepare_only=bool(args.get("prepare_only", False)),
        output_dir=None,
        profile_id=_optional_string(args, "profile_id"),
        timeout_seconds=_optional_positive_int(args, "timeout_seconds", 120),
        raise_issues=raise_issues,
        issue_threshold=issue_threshold,
    )
    return report.to_json()


def _llm_eval_compare(server: KyokoMcpServer, args: dict[str, Any]) -> dict[str, Any]:
    return compare_eval_runs(
        db_path=server.db_path,
        baseline_run_id=_required_string(args, "baseline_run_id"),
        compare_run_id=_required_string(args, "compare_run_id"),
    )


def _object_schema(
    properties: dict[str, Any],
    *,
    required: Optional[list[str]] = None,
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _required_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise McpError(f"{key}_required")
    return value


def _required_command(args: dict[str, Any], key: str) -> list[str]:
    value = args.get(key)
    if isinstance(value, list) and all(isinstance(part, str) and part for part in value):
        return list(value)
    if isinstance(value, str) and value:
        try:
            return parse_judge_command(value)
        except Exception as exc:
            raise McpError(str(exc)) from exc
    raise McpError(f"{key}_required")


def _optional_string(args: dict[str, Any], key: str) -> Optional[str]:
    value = args.get(key)
    return value if isinstance(value, str) and value else None


def _optional_path(args: dict[str, Any], key: str) -> Optional[Path]:
    value = _optional_string(args, key)
    return Path(value).expanduser() if value else None


def _optional_string_list(args: dict[str, Any], key: str) -> Optional[tuple[str, ...]]:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise McpError(f"{key}_must_be_array")
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise McpError(f"{key}_items_must_be_strings")
        items.append(item)
    return tuple(items)


def _optional_int(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key)
    if isinstance(value, int):
        return value
    return default


def _optional_positive_int(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise McpError(f"{key}_must_be_positive_integer")


def _optional_positive_int_or_none(args: dict[str, Any], key: str) -> Optional[int]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise McpError(f"{key}_must_be_positive_integer")


def _optional_non_negative_int(args: dict[str, Any], key: str) -> Optional[int]:
    value = args.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise McpError(f"{key}_must_be_non_negative_integer")
    return value


def _optional_port(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise McpError(f"{key}_must_be_port_integer")
    return value


def _tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, sort_keys=True),
            }
        ],
        "structuredContent": payload,
        "isError": is_error,
    }


def _result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _write_jsonrpc(stdout: TextIO, payload: Any) -> None:
    stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    stdout.flush()
