from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mcp import write_mcp_config
from .operator_adapters import OperatorAdapterError
from .operator_presets import OperatorBootstrapReport, bootstrap_operator_adapters
from .replay_templates import (
    ReplayTemplateError,
    ReplayTemplateReport,
    recommended_replay_server_filename,
    write_replay_server_template,
)
from .source_templates import (
    SourceTemplateError,
    SourceTemplateReport,
    recommended_source_adapter_filename,
    write_source_adapter_template,
)
from .storage import StorageError, ingest_source_payload, initialize_database, utc_now


class ProjectBootstrapError(Exception):
    """Raised when project bootstrap cannot complete."""


@dataclass(frozen=True)
class ProjectBootstrapReport:
    project_dir: Path
    db_path: Path
    source_adapter: SourceTemplateReport
    replay_server: ReplayTemplateReport
    mcp_config_path: Path
    mcp_config: dict[str, Any]
    operator_bootstrap: OperatorBootstrapReport
    next_steps_path: Path
    commands: dict[str, str]

    def to_json(self) -> dict[str, Any]:
        return {
            "project_dir": str(self.project_dir),
            "db_path": str(self.db_path),
            "source_adapter": {
                "output_path": str(self.source_adapter.output_path),
                "framework": self.source_adapter.framework,
                "profile_name": self.source_adapter.profile_name,
                "wrote": self.source_adapter.wrote,
            },
            "replay_server": {
                "output_path": str(self.replay_server.output_path),
                "framework": self.replay_server.framework,
                "profile_name": self.replay_server.profile_name,
                "wrote": self.replay_server.wrote,
            },
            "mcp_config_path": str(self.mcp_config_path),
            "mcp_config": self.mcp_config,
            "operator_bootstrap": self.operator_bootstrap.to_json(),
            "next_steps_path": str(self.next_steps_path),
            "commands": self.commands,
        }


def bootstrap_project(
    *,
    project_dir: Path,
    profile_name: str = "kyoko-agent",
    source_framework: str = "generic-python",
    replay_framework: str = "generic-python",
    force: bool = False,
    bootstrap_operators: bool = True,
    operator_target: str = "all",
    mcp_target: str = "generic",
) -> ProjectBootstrapReport:
    if not profile_name:
        raise ProjectBootstrapError("profile_name_required")

    selected_project_dir = project_dir.resolve()
    kyoko_dir = selected_project_dir / ".kyoko"
    scripts_dir = kyoko_dir / "scripts"
    config_dir = kyoko_dir / "config"
    db_path = kyoko_dir / "kyoko.db"
    source_path = scripts_dir / recommended_source_adapter_filename(source_framework)
    replay_path = scripts_dir / recommended_replay_server_filename(replay_framework)
    mcp_config_path = config_dir / "mcp.json"
    next_steps_path = kyoko_dir / "NEXT_STEPS.md"
    profile_id = f"profile_{_slug(profile_name)}"

    try:
        initialize_database(db_path)
        _seed_profile(
            db_path=db_path,
            profile_id=profile_id,
            profile_name=profile_name,
            project_dir=selected_project_dir,
        )
        source_report = write_source_adapter_template(
            output_path=source_path,
            framework=source_framework,
            profile_name=profile_name,
            force=force,
        )
        replay_report = write_replay_server_template(
            output_path=replay_path,
            framework=replay_framework,
            profile_name=profile_name,
            force=force,
        )
        mcp_config = write_mcp_config(
            output_path=mcp_config_path,
            db_path=db_path,
            server_name="kyoko",
            target=mcp_target,
        )
        operator_report = (
            bootstrap_operator_adapters(
                db_path=db_path,
                target=operator_target,
                output_dir=kyoko_dir / "operator-runs",
            )
            if bootstrap_operators
            else OperatorBootstrapReport(registered=(), skipped=())
        )
        commands = _bootstrap_commands(
            db_path=db_path,
            source_path=source_path,
            replay_path=replay_path,
            mcp_config_path=mcp_config_path,
            profile_id=profile_id,
            profile_name=profile_name,
            project_dir=selected_project_dir,
        )
        next_steps_path.write_text(_next_steps(commands=commands), encoding="utf-8")
    except (OSError, StorageError, OperatorAdapterError, ReplayTemplateError, SourceTemplateError) as exc:
        raise ProjectBootstrapError(str(exc)) from exc

    return ProjectBootstrapReport(
        project_dir=selected_project_dir,
        db_path=db_path,
        source_adapter=source_report,
        replay_server=replay_report,
        mcp_config_path=mcp_config_path,
        mcp_config=mcp_config,
        operator_bootstrap=operator_report,
        next_steps_path=next_steps_path,
        commands=commands,
    )


def _bootstrap_commands(
    *,
    db_path: Path,
    source_path: Path,
    replay_path: Path,
    mcp_config_path: Path,
    profile_id: str,
    profile_name: str,
    project_dir: Path,
) -> dict[str, str]:
    return {
        "doctor": f"kyoko doctor --db {_quote(db_path)} --json",
        "doctor_safe_smokes": (
            f"kyoko doctor --db {_quote(db_path)} --safe-smokes "
            f"--smoke-output-dir {_quote(project_dir / '.kyoko' / 'smoke' / 'doctor')} --json"
        ),
        "profile_next": f"kyoko profile-next --db {_quote(db_path)} --json",
        "source": _source_command_for_path(source_path),
        "ingest": f"kyoko ingest --db {_quote(db_path)} /tmp/kyoko-source-events.json --json",
        "discover_sources": (
            f"kyoko discover-sources --db {_quote(db_path)} "
            f"--profile-id {shlex.quote(profile_id)} "
            f"--profile-name {shlex.quote(profile_name)} "
            f"--root-path {_quote(project_dir)} --json"
        ),
        "serve": f"kyoko serve --db {_quote(db_path)}",
        "mcp": f"Use MCP config: {_quote(mcp_config_path)}",
        "replay_adapter_register": (
            f"kyoko replay-adapter-register --db {_quote(db_path)} "
            f"{shlex.quote(_replay_adapter_id(profile_id))} "
            f"--name {shlex.quote(profile_name + ' replay')} "
            f"--command {_quote(_replay_server_command(replay_path))} "
            "--server-url http://127.0.0.1:61200 "
            f"--cwd {_quote(project_dir)} "
            f"--output-dir {_quote(project_dir / '.kyoko' / 'replay-runs')} "
            "--mode dry_run --side-effect-mode network_mocked "
            f"--profile-id {shlex.quote(profile_id)} --json"
        ),
        "replay_smoke": (
            "kyoko integration-smoke replay-server "
            f"--command {_quote(_replay_server_start_command(replay_path))} "
            "--server-url http://127.0.0.1:61200 "
            f"--output-dir {_quote(project_dir / '.kyoko' / 'smoke' / 'replay')} "
            f"--hook {shlex.quote(_replay_hook_placeholder(replay_path))} "
            "--run-replay --json"
        ),
        "replay": _replay_command_for_path(replay_path),
        "import_hermes_kanban": (
            f"kyoko import-hermes-kanban --db {_quote(db_path)} "
            "~/.hermes/kanban.db --board default "
            f"--profile-id {shlex.quote(profile_id)} "
            f"--profile-name {shlex.quote(profile_name)} "
            f"--root-path {_quote(project_dir)} --json"
        ),
        "import_openclaw_sessions": (
            f"kyoko import-openclaw-sessions --db {_quote(db_path)} "
            "~/.openclaw/agents/main/sessions --agent-id main "
            f"--profile-id {shlex.quote(profile_id)} "
            f"--profile-name {shlex.quote(profile_name)} "
            f"--root-path {_quote(project_dir)} --json"
        ),
    }


def _next_steps(*, commands: dict[str, str]) -> str:
    return "\n".join(
        [
            "# Kyoko Next Steps",
            "",
            "Generated local project bootstrap artifacts.",
            "",
            "1. Verify the local runtime and generated database:",
            "",
            "```bash",
            commands["doctor"],
            commands["doctor_safe_smokes"],
            commands["profile_next"],
            "```",
            "",
            "`doctor --safe-smokes` runs the no-live-model demo, operator prepare, native ACE prepare, integration, improve, and MCP install smoke checks while retaining artifacts under `.kyoko/smoke/doctor`.",
            "",
            "2. Bring telemetry into Kyoko. Easiest path: install the coding-agent skill and let your agent wire it for you:",
            "",
            "```bash",
            "kyoko install-skill   # then run /kyoko-instrument in your coding agent",
            "```",
            "",
            "Or do it by hand with the generated adapter, discover local sources, or import local Hermes/OpenClaw state directly:",
            "",
            "```bash",
            commands["discover_sources"],
            commands["source"],
            commands["ingest"],
            commands["import_hermes_kanban"],
            commands["import_openclaw_sessions"],
            "```",
            "",
            "3. Start the dashboard or wire the generated replay server when ready:",
            "",
            "```bash",
            commands["serve"],
            commands["replay_smoke"],
            commands["replay_adapter_register"],
            commands["replay"],
            "```",
            "",
            commands["mcp"],
            "",
            "No live operator model, replay, autonomy, or apply action ran during bootstrap.",
            "",
            "Machine-readable commands:",
            "",
            "```json",
            json.dumps(commands, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )


def _source_command_for_path(source_path: Path) -> str:
    if source_path.suffix == ".mjs":
        return (
            "KYOKO_SOURCE_HOOK=/absolute/path/to/source_hook.mjs:collect "
            f"node {_quote(source_path)} --output /tmp/kyoko-source-events.json"
        )
    return (
        "KYOKO_SOURCE_HOOK=/absolute/path/to/source_hook.py:collect "
        f"python3 {_quote(source_path)} --output /tmp/kyoko-source-events.json"
    )


def _replay_adapter_id(profile_id: str) -> str:
    return f"{profile_id}_replay"


def _replay_server_command(replay_path: Path) -> str:
    if replay_path.suffix == ".mjs":
        return shlex.join(
            [
                "env",
                "KYOKO_REPLAY_HOOK=/absolute/path/to/replay_hook.mjs:replay",
                "node",
                str(replay_path),
                "--port",
                "61200",
            ]
        )
    return shlex.join(
        [
            "env",
            "KYOKO_REPLAY_HOOK=/absolute/path/to/replay_hook.py:replay",
            "python3",
            str(replay_path),
            "--port",
            "61200",
        ]
    )


def _replay_server_start_command(replay_path: Path) -> str:
    if replay_path.suffix == ".mjs":
        return shlex.join(["node", str(replay_path), "--port", "61200"])
    return shlex.join(["python3", str(replay_path), "--port", "61200"])


def _replay_hook_placeholder(replay_path: Path) -> str:
    if replay_path.suffix == ".mjs":
        return "/absolute/path/to/replay_hook.mjs:replay"
    return "/absolute/path/to/replay_hook.py:replay"


def _replay_command_for_path(replay_path: Path) -> str:
    if replay_path.suffix == ".mjs":
        return (
            "KYOKO_REPLAY_HOOK=/absolute/path/to/replay_hook.mjs:replay "
            f"node {_quote(replay_path)} --port 61200"
        )
    return (
        "KYOKO_REPLAY_HOOK=/absolute/path/to/replay_hook.py:replay "
        f"python3 {_quote(replay_path)} --port 61200"
    )


def _seed_profile(*, db_path: Path, profile_id: str, profile_name: str, project_dir: Path) -> None:
    now = utc_now()
    ingest_source_payload(
        db_path=db_path,
        fixture={
            "fixture_version": "kyoko.source_events.v1",
            "profile": {
                "id": profile_id,
                "name": profile_name,
                "root_path": str(project_dir),
                "status": "active",
                "created_at": now,
                "updated_at": now,
            },
        },
        source_label="project-bootstrap",
    )


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")
    return cleaned or "kyoko_agent"


def _quote(value: Any) -> str:
    return shlex.quote(str(value))
