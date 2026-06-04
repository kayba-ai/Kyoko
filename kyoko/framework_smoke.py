from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

from .autonomy import update_autonomy_policy
from .improve import ImproveError, ImproveReport, run_improvement_loop
from .integration_smoke import (
    IntegrationSmokeError,
    ReplayServerSmokeReport,
    SourceAdapterSmokeReport,
    run_replay_server_smoke,
    run_source_adapter_smoke,
)
from .replay_templates import (
    ReplayTemplateError,
    recommended_replay_server_filename,
    write_replay_server_template,
)
from .replay_adapters import ReplayAdapterError, ReplayAdapterRegisterReport, register_replay_adapter
from .source_templates import (
    SourceTemplateError,
    recommended_source_adapter_filename,
    write_source_adapter_template,
)
from .storage import StorageError, connect, get_database_status, initialize_database, status_to_json


DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK = "langgraph-python"
DEFAULT_INSTALLED_FRAMEWORK_SOURCE_PROFILE_ID = "profile_installed_langgraph_smoke"
DEFAULT_INSTALLED_FRAMEWORK_SOURCE_PROFILE_NAME = "Installed LangGraph Smoke"
DEFAULT_INSTALLED_FRAMEWORK_SOURCE_ID = "source_installed_langgraph_smoke"
DEFAULT_INSTALLED_FRAMEWORK_SOURCE_AGENT_ID = "agent_installed_langgraph_smoke"
DEFAULT_INSTALLED_FRAMEWORK_SOURCE_AGENT_NAME = "installed-langgraph-agent"


SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS = {
    "langgraph-python": {
        "package": "langgraph",
        "import_name": "langgraph",
        "display_name": "LangGraph Python workflow",
        "profile_id": DEFAULT_INSTALLED_FRAMEWORK_SOURCE_PROFILE_ID,
        "profile_name": DEFAULT_INSTALLED_FRAMEWORK_SOURCE_PROFILE_NAME,
        "source_id": DEFAULT_INSTALLED_FRAMEWORK_SOURCE_ID,
        "agent_id": DEFAULT_INSTALLED_FRAMEWORK_SOURCE_AGENT_ID,
        "agent_name": DEFAULT_INSTALLED_FRAMEWORK_SOURCE_AGENT_NAME,
        "hook_kind": "langgraph",
    },
    "pydantic-ai-python": {
        "package": "pydantic-ai",
        "import_name": "pydantic_ai",
        "display_name": "Pydantic AI Python agent",
        "profile_id": "profile_installed_pydantic_ai_smoke",
        "profile_name": "Installed Pydantic AI Smoke",
        "source_id": "source_installed_pydantic_ai_smoke",
        "agent_id": "agent_installed_pydantic_ai_smoke",
        "agent_name": "installed-pydantic-ai-agent",
        "hook_kind": "pydantic_ai",
    },
    "openai-agents-python": {
        "package": "openai-agents",
        "import_name": "agents",
        "display_name": "OpenAI Agents Python workflow",
        "profile_id": "profile_installed_openai_agents_smoke",
        "profile_name": "Installed OpenAI Agents Smoke",
        "source_id": "source_installed_openai_agents_smoke",
        "agent_id": "agent_installed_openai_agents_planner",
        "agent_name": "installed-openai-agents-planner",
        "hook_kind": "openai_agents",
    },
    "crewai-python": {
        "package": "crewai",
        "import_name": "crewai",
        "display_name": "CrewAI Python workflow",
        "profile_id": "profile_installed_crewai_smoke",
        "profile_name": "Installed CrewAI Smoke",
        "source_id": "source_installed_crewai_smoke",
        "agent_id": "agent_installed_crewai_manager",
        "agent_name": "installed-crewai-manager",
        "hook_kind": "crewai",
    },
}


class FrameworkSmokeError(Exception):
    """Raised when an installed framework source smoke cannot complete."""


@dataclass(frozen=True)
class InstalledFrameworkSourceSmokeReport:
    framework: str
    framework_package: str
    framework_version: str
    python_executable: Path
    db_path: Path
    output_dir: Path
    workspace_root: Path
    source_adapter_path: Path
    source_hook_path: Path
    source_smoke: SourceAdapterSmokeReport
    status: dict[str, Any]
    installed_framework_invoked: bool
    passed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "installed_framework_source_smoke",
            "framework": self.framework,
            "framework_package": self.framework_package,
            "framework_version": self.framework_version,
            "python_executable": str(self.python_executable),
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "workspace_root": str(self.workspace_root),
            "source_adapter_path": str(self.source_adapter_path),
            "source_hook_path": str(self.source_hook_path),
            "source_smoke": self.source_smoke.to_json(),
            "status": self.status,
            "installed_framework_invoked": self.installed_framework_invoked,
            "generated_source_adapter_invoked": True,
            "external_model_invoked": False,
            "live_operator_invoked": False,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class InstalledFrameworkReplaySmokeReport:
    framework: str
    framework_package: str
    framework_version: str
    python_executable: Path
    output_dir: Path
    workspace_root: Path
    replay_server_path: Path
    replay_hook_path: Path
    replay_server_url: str
    replay_smoke: ReplayServerSmokeReport
    installed_framework_invoked: bool
    passed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "installed_framework_replay_smoke",
            "framework": self.framework,
            "framework_package": self.framework_package,
            "framework_version": self.framework_version,
            "python_executable": str(self.python_executable),
            "output_dir": str(self.output_dir),
            "workspace_root": str(self.workspace_root),
            "replay_server_path": str(self.replay_server_path),
            "replay_hook_path": str(self.replay_hook_path),
            "replay_server_url": self.replay_server_url,
            "replay_smoke": self.replay_smoke.to_json(),
            "installed_framework_invoked": self.installed_framework_invoked,
            "generated_replay_server_invoked": True,
            "external_model_invoked": False,
            "live_operator_invoked": False,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class InstalledFrameworkImproveSmokeReport:
    framework: str
    framework_package: str
    framework_version: str
    python_executable: Path
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
    status: dict[str, Any]
    installed_framework_source_invoked: bool
    installed_framework_replay_invoked: bool
    passed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "installed_framework_improve_smoke",
            "framework": self.framework,
            "framework_package": self.framework_package,
            "framework_version": self.framework_version,
            "python_executable": str(self.python_executable),
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
            "installed_framework_invoked": (
                self.installed_framework_source_invoked
                and self.installed_framework_replay_invoked
            ),
            "installed_framework_source_invoked": self.installed_framework_source_invoked,
            "installed_framework_replay_invoked": self.installed_framework_replay_invoked,
            "generated_source_adapter_invoked": True,
            "generated_replay_server_invoked": True,
            "managed_replay_server_invoked": True,
            "external_model_invoked": False,
            "live_operator_invoked": False,
            "passed": self.passed,
        }


def run_installed_framework_source_smoke(
    *,
    db_path: Path,
    framework: str = DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
    python_executable: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> InstalledFrameworkSourceSmokeReport:
    if timeout_seconds <= 0:
        raise FrameworkSmokeError("timeout_seconds_must_be_positive")
    if framework not in SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS:
        raise FrameworkSmokeError(f"unsupported_installed_source_framework:{framework}")

    spec = SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS[framework]
    selected_python = _resolve_python_executable(python_executable)
    selected_output_dir = (
        output_dir if output_dir is not None else Path(tempfile.mkdtemp(prefix="kyoko-framework-source-smoke-"))
    ).resolve()
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = selected_output_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    source_adapter_path = (
        selected_output_dir
        / "source"
        / recommended_source_adapter_filename(framework)
    )
    source_hook_path = selected_output_dir / "hooks" / "source_hook.py"
    source_output_dir = selected_output_dir / "source-smoke"

    try:
        framework_version = _framework_package_version(
            python_executable=selected_python,
            package_name=spec["package"],
            import_name=spec["import_name"],
            cwd=selected_output_dir,
            timeout_seconds=timeout_seconds,
        )
        initialize_database(db_path)
        write_source_adapter_template(
            output_path=source_adapter_path,
            framework=framework,
            profile_name=spec["profile_name"],
            force=True,
        )
        _write_installed_framework_source_hook(
            source_hook_path,
            framework=framework,
            package_name=spec["package"],
            import_name=spec["import_name"],
        )
        source_smoke = run_source_adapter_smoke(
            db_path=db_path,
            adapter_path=source_adapter_path,
            hook=f"{source_hook_path}:collect",
            output_dir=source_output_dir,
            profile_id=spec["profile_id"],
            profile_name=spec["profile_name"],
            root_path=workspace_root,
            source_id=spec["source_id"],
            agent_id=spec["agent_id"],
            agent_name=spec["agent_name"],
            python_executable=selected_python,
            cwd=selected_output_dir,
            timeout_seconds=timeout_seconds,
        )
    except (
        IntegrationSmokeError,
        SourceTemplateError,
        StorageError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise FrameworkSmokeError(str(exc)) from exc

    payload = _read_source_events(source_smoke.source_events_path)
    installed_framework_invoked = _source_events_mark_installed_framework(
        payload,
        package_name=spec["package"],
    )
    status = status_to_json(get_database_status(db_path))
    passed = (
        installed_framework_invoked
        and source_smoke.exit_code == 0
        and status["counts"].get("runs", 0) >= 1
        and status["counts"].get("spans", 0) >= 2
    )
    return InstalledFrameworkSourceSmokeReport(
        framework=framework,
        framework_package=spec["package"],
        framework_version=framework_version,
        python_executable=selected_python,
        db_path=db_path,
        output_dir=selected_output_dir,
        workspace_root=workspace_root,
        source_adapter_path=source_adapter_path,
        source_hook_path=source_hook_path,
        source_smoke=source_smoke,
        status=status,
        installed_framework_invoked=installed_framework_invoked,
        passed=passed,
    )


def run_installed_framework_replay_smoke(
    *,
    framework: str = DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
    python_executable: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> InstalledFrameworkReplaySmokeReport:
    if timeout_seconds <= 0:
        raise FrameworkSmokeError("timeout_seconds_must_be_positive")
    if framework not in SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS:
        raise FrameworkSmokeError(f"unsupported_installed_replay_framework:{framework}")

    spec = SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS[framework]
    selected_python = _resolve_python_executable(python_executable)
    selected_output_dir = (
        output_dir if output_dir is not None else Path(tempfile.mkdtemp(prefix="kyoko-framework-replay-smoke-"))
    ).resolve()
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = selected_output_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    replay_server_path = (
        selected_output_dir
        / "replay"
        / recommended_replay_server_filename(framework)
    )
    replay_hook_path = selected_output_dir / "hooks" / "replay_hook.py"
    replay_output_dir = selected_output_dir / "replay-smoke"
    port = _free_port()
    server_url = f"http://127.0.0.1:{port}"

    try:
        framework_version = _framework_package_version(
            python_executable=selected_python,
            package_name=spec["package"],
            import_name=spec["import_name"],
            cwd=selected_output_dir,
            timeout_seconds=timeout_seconds,
        )
        write_replay_server_template(
            output_path=replay_server_path,
            framework=framework,
            profile_name=spec["profile_name"],
            force=True,
        )
        _write_installed_framework_replay_hook(
            replay_hook_path,
            framework=framework,
            package_name=spec["package"],
            import_name=spec["import_name"],
        )
        replay_smoke = run_replay_server_smoke(
            command=[str(selected_python), str(replay_server_path), "--port", str(port)],
            server_url=server_url,
            output_dir=replay_output_dir,
            replay_hook=f"{replay_hook_path}:replay",
            run_replay=True,
            replay_timeout_seconds=timeout_seconds,
            startup_timeout_seconds=min(timeout_seconds, 15),
            stop_timeout_seconds=min(timeout_seconds, 10),
            cwd=selected_output_dir,
        )
    except (
        IntegrationSmokeError,
        ReplayTemplateError,
        OSError,
    ) as exc:
        raise FrameworkSmokeError(str(exc)) from exc

    replay_response = replay_smoke.replay_response or {}
    installed_framework_invoked = _source_events_mark_installed_framework(
        replay_response,
        package_name=spec["package"],
    )
    passed = (
        replay_smoke.started
        and replay_smoke.healthy
        and replay_smoke.stopped
        and replay_smoke.replay_ok
        and installed_framework_invoked
    )
    return InstalledFrameworkReplaySmokeReport(
        framework=framework,
        framework_package=spec["package"],
        framework_version=framework_version,
        python_executable=selected_python,
        output_dir=selected_output_dir,
        workspace_root=workspace_root,
        replay_server_path=replay_server_path,
        replay_hook_path=replay_hook_path,
        replay_server_url=server_url,
        replay_smoke=replay_smoke,
        installed_framework_invoked=installed_framework_invoked,
        passed=passed,
    )


def run_installed_framework_improve_smoke(
    *,
    db_path: Path,
    framework: str = DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
    python_executable: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> InstalledFrameworkImproveSmokeReport:
    if timeout_seconds <= 0:
        raise FrameworkSmokeError("timeout_seconds_must_be_positive")
    if framework not in SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS:
        raise FrameworkSmokeError(f"unsupported_installed_improve_framework:{framework}")

    spec = SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS[framework]
    selected_python = _resolve_python_executable(python_executable)
    selected_output_dir = (
        output_dir
        if output_dir is not None
        else Path(tempfile.mkdtemp(prefix="kyoko-framework-improve-smoke-"))
    ).resolve()
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = selected_output_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)

    source_adapter_path = (
        selected_output_dir
        / "source"
        / recommended_source_adapter_filename(framework)
    )
    replay_server_path = (
        selected_output_dir
        / "replay"
        / recommended_replay_server_filename(framework)
    )
    source_hook_path = selected_output_dir / "hooks" / "source_hook.py"
    replay_hook_path = selected_output_dir / "hooks" / "replay_hook.py"
    source_output_dir = selected_output_dir / "source-smoke"
    replay_output_dir = selected_output_dir / "replay-runs"
    improve_output_dir = selected_output_dir / "improve"
    replay_adapter_id = _installed_framework_improve_adapter_id(framework)
    port = _free_port()
    server_url = f"http://127.0.0.1:{port}"

    try:
        framework_version = _framework_package_version(
            python_executable=selected_python,
            package_name=spec["package"],
            import_name=spec["import_name"],
            cwd=selected_output_dir,
            timeout_seconds=timeout_seconds,
        )
        initialize_database(db_path)
        write_source_adapter_template(
            output_path=source_adapter_path,
            framework=framework,
            profile_name=spec["profile_name"],
            force=True,
        )
        write_replay_server_template(
            output_path=replay_server_path,
            framework=framework,
            profile_name=spec["profile_name"],
            force=True,
        )
        _write_installed_framework_source_hook(
            source_hook_path,
            framework=framework,
            package_name=spec["package"],
            import_name=spec["import_name"],
        )
        _write_installed_framework_replay_hook(
            replay_hook_path,
            framework=framework,
            package_name=spec["package"],
            import_name=spec["import_name"],
        )
        source_smoke = run_source_adapter_smoke(
            db_path=db_path,
            adapter_path=source_adapter_path,
            hook=f"{source_hook_path}:collect",
            output_dir=source_output_dir,
            profile_id=spec["profile_id"],
            profile_name=spec["profile_name"],
            root_path=workspace_root,
            source_id=spec["source_id"],
            agent_id=spec["agent_id"],
            agent_name=spec["agent_name"],
            python_executable=selected_python,
            cwd=selected_output_dir,
            timeout_seconds=timeout_seconds,
        )
        source_payload = _read_source_events(source_smoke.source_events_path)
        installed_framework_source_invoked = _source_events_mark_installed_framework(
            source_payload,
            package_name=spec["package"],
        )
        replay_adapter = register_replay_adapter(
            db_path=db_path,
            adapter_id=replay_adapter_id,
            name=f"{spec['display_name']} improve replay",
            command=[str(selected_python), str(replay_server_path), "--port", str(port)],
            server_url=server_url,
            cwd=selected_output_dir,
            output_dir=replay_output_dir,
            profile_id=source_smoke.profile_id,
            default_side_effect_mode="network_mocked",
            timeout_seconds=timeout_seconds,
            startup_timeout_seconds=min(timeout_seconds, 15),
            metadata={
                "framework": framework,
                "framework_package": spec["package"],
                "framework_version": framework_version,
                "installed_framework_improve_smoke": True,
            },
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
        ReplayTemplateError,
        SourceTemplateError,
        StorageError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        raise FrameworkSmokeError(str(exc)) from exc

    installed_framework_replay_invoked = _improve_replay_output_marks_installed_framework(
        db_path=db_path,
        improve=improve,
        package_name=spec["package"],
    )
    status = status_to_json(get_database_status(db_path))
    passed = (
        installed_framework_source_invoked
        and installed_framework_replay_invoked
        and _improve_report_passed(improve)
    )
    return InstalledFrameworkImproveSmokeReport(
        framework=framework,
        framework_package=spec["package"],
        framework_version=framework_version,
        python_executable=selected_python,
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
        installed_framework_source_invoked=installed_framework_source_invoked,
        installed_framework_replay_invoked=installed_framework_replay_invoked,
        passed=passed,
    )


def _resolve_python_executable(python_executable: Optional[Path]) -> Path:
    selected = python_executable if python_executable is not None else Path(sys.executable)
    if selected.exists():
        return selected
    resolved = shutil.which(str(selected))
    if resolved is not None:
        return Path(resolved)
    raise FrameworkSmokeError(f"python_executable_not_found:{selected}")


def _framework_package_version(
    *,
    python_executable: Path,
    package_name: str,
    import_name: str,
    cwd: Path,
    timeout_seconds: int,
) -> str:
    code = (
        "import importlib, importlib.metadata as metadata\n"
        f"module = importlib.import_module({import_name!r})\n"
        "try:\n"
        f"    version = metadata.version({package_name!r})\n"
        "except metadata.PackageNotFoundError:\n"
        "    version = getattr(module, '__version__', 'unknown')\n"
        "print(version)\n"
    )
    try:
        completed = subprocess.run(
            [str(python_executable), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise FrameworkSmokeError(f"framework_package_check_timeout:{package_name}") from exc
    except OSError as exc:
        raise FrameworkSmokeError(f"framework_package_check_failed_to_start:{exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or str(completed.returncode)
        raise FrameworkSmokeError(f"framework_package_not_importable:{package_name}:{detail}")
    version = completed.stdout.strip()
    if not version:
        raise FrameworkSmokeError(f"framework_package_version_missing:{package_name}")
    return version


def _write_installed_framework_source_hook(
    path: Path,
    *,
    framework: str,
    package_name: str,
    import_name: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hook_template = _source_hook_template(framework)
    path.write_text(
        hook_template.replace("__PACKAGE_NAME__", package_name).replace(
            "__IMPORT_NAME__",
            import_name,
        ),
        encoding="utf-8",
    )


def _source_hook_template(framework: str) -> str:
    hook_kind = SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS[framework]["hook_kind"]
    if hook_kind == "langgraph":
        return LANGGRAPH_SOURCE_HOOK_TEMPLATE
    if hook_kind == "pydantic_ai":
        return PYDANTIC_AI_SOURCE_HOOK_TEMPLATE
    if hook_kind == "openai_agents":
        return OPENAI_AGENTS_SOURCE_HOOK_TEMPLATE
    if hook_kind == "crewai":
        return CREWAI_SOURCE_HOOK_TEMPLATE
    raise FrameworkSmokeError(f"unsupported_installed_source_hook:{framework}")


def _write_installed_framework_replay_hook(
    path: Path,
    *,
    framework: str,
    package_name: str,
    import_name: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hook_template = _replay_hook_template(framework)
    path.write_text(
        hook_template.replace("__PACKAGE_NAME__", package_name).replace(
            "__IMPORT_NAME__",
            import_name,
        ),
        encoding="utf-8",
    )


def _replay_hook_template(framework: str) -> str:
    hook_kind = SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS[framework]["hook_kind"]
    if hook_kind == "langgraph":
        return LANGGRAPH_REPLAY_HOOK_TEMPLATE
    if hook_kind == "pydantic_ai":
        return PYDANTIC_AI_REPLAY_HOOK_TEMPLATE
    if hook_kind == "openai_agents":
        return OPENAI_AGENTS_REPLAY_HOOK_TEMPLATE
    if hook_kind == "crewai":
        return CREWAI_REPLAY_HOOK_TEMPLATE
    raise FrameworkSmokeError(f"unsupported_installed_replay_hook:{framework}")


def _read_source_events(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FrameworkSmokeError(f"source_events_invalid_json:{path}") from exc
    if not isinstance(payload, dict):
        raise FrameworkSmokeError("source_events_must_be_object")
    return payload


def _source_events_mark_installed_framework(
    payload: dict[str, Any],
    *,
    package_name: str,
) -> bool:
    replay = payload.get("replay")
    source_events = payload.get("source_events")
    if isinstance(replay, dict) and isinstance(source_events, dict):
        return _source_events_mark_installed_framework(
            source_events,
            package_name=package_name,
        )
    sources = payload.get("sources")
    runs = payload.get("runs")
    spans = payload.get("spans")
    if not isinstance(sources, list) or not isinstance(runs, list) or not isinstance(spans, list):
        return False
    marker_found = False
    for item in [*sources, *runs, *spans]:
        if not isinstance(item, dict):
            continue
        metadata_json = item.get("metadata_json")
        config_json = item.get("config_json")
        attributes_json = item.get("attributes_json")
        for container in (metadata_json, config_json, attributes_json):
            if not isinstance(container, dict):
                continue
            if (
                container.get("installed_framework_invoked") is True
                and container.get("framework_package") == package_name
            ):
                marker_found = True
    return marker_found


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _installed_framework_improve_adapter_id(framework: str) -> str:
    return "installed_framework_improve_" + framework.replace("-", "_") + "_replay"


def _replay_adapter_json(report: ReplayAdapterRegisterReport) -> dict[str, Any]:
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


def _improve_report_passed(report: ImproveReport) -> bool:
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


def _improve_replay_output_marks_installed_framework(
    *,
    db_path: Path,
    improve: ImproveReport,
    package_name: str,
) -> bool:
    output_run_ids = [
        replay.get("output_run_id")
        for replay in improve.replay_runs
        if isinstance(replay.get("output_run_id"), str)
    ]
    return any(
        _stored_run_marks_installed_framework(
            db_path=db_path,
            run_id=str(output_run_id),
            package_name=package_name,
        )
        for output_run_id in output_run_ids
    )


def _stored_run_marks_installed_framework(
    *,
    db_path: Path,
    run_id: str,
    package_name: str,
) -> bool:
    with connect(db_path) as connection:
        run = connection.execute(
            "SELECT metadata_json FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        spans = connection.execute(
            "SELECT attributes_json FROM spans WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    if run is None:
        return False
    payload = {
        "sources": [],
        "runs": [{"metadata_json": _json_loads(run["metadata_json"], {})}],
        "spans": [
            {"attributes_json": _json_loads(row["attributes_json"], {})}
            for row in spans
        ],
    }
    return _source_events_mark_installed_framework(payload, package_name=package_name)


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


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


LANGGRAPH_SOURCE_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


class SmokeState(TypedDict, total=False):
    topic: str
    plan: str
    result: str


def collect(context: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    graph_result = run_langgraph_smoke()
    if graph_result.get("result") != "timeout":
        raise RuntimeError(f"unexpected LangGraph smoke result: {graph_result!r}")

    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    agent_id = context["agent_id"]
    node_id = "node_installed_langgraph_research"
    run_id = "run_installed_langgraph_smoke_001"
    root_span_id = "span_installed_langgraph_plan_001"
    tool_span_id = "span_installed_langgraph_fetch_001"
    framework_metadata = {
        "framework": context["framework"],
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
    }
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
                "display_name": "Installed LangGraph source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_source_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {
                    "runs": True,
                    "spans": True,
                    "installed_framework_smoke": True,
                },
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
                "metadata_json": dict(framework_metadata),
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "langgraph-plan-fetch",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "plan-fetch",
                "metadata_json": dict(framework_metadata),
            }
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-langgraph-smoke-001",
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": graph_result.get("topic")},
                    "kind": "agent_prompt",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"result": graph_result.get("result")},
                    "kind": "agent_error",
                },
                "summary": "Installed LangGraph smoke ran a deterministic graph and observed a mocked fetch timeout.",
                "metadata_json": {
                    **framework_metadata,
                    "graph_result": graph_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "langgraph-plan",
                "parent_span_id": None,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "plan",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": graph_result.get("topic")},
                    "kind": "span_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"plan": graph_result.get("plan")},
                    "kind": "span_output",
                },
                "usage_json": {},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "langgraph-fetch",
                "parent_span_id": root_span_id,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"plan": graph_result.get("plan")},
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "fetch_source timed out",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "error_type": "timeout",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [],
    }


def run_langgraph_smoke() -> dict[str, str]:
    def plan_node(state: SmokeState) -> dict[str, str]:
        topic = state.get("topic") or "framework-smoke"
        return {"plan": "fetch:" + topic}

    def fetch_node(state: SmokeState) -> dict[str, str]:
        return {"result": "timeout"}

    graph = StateGraph(SmokeState)
    graph.add_node("plan", plan_node)
    graph.add_node("fetch", fetch_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "fetch")
    graph.add_edge("fetch", END)
    app = graph.compile()
    result = app.invoke({"topic": "framework-smoke"})
    if not isinstance(result, dict):
        raise RuntimeError(f"LangGraph returned non-object state: {result!r}")
    return {
        "topic": str(result.get("topic", "")),
        "plan": str(result.get("plan", "")),
        "result": str(result.get("result", "")),
    }


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))
'''.lstrip()


LANGGRAPH_REPLAY_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


class SmokeState(TypedDict, total=False):
    topic: str
    plan: str
    result: str


def replay(request: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    graph_result = run_langgraph_replay()
    if graph_result.get("result") != "timeout":
        raise RuntimeError(f"unexpected LangGraph replay result: {graph_result!r}")

    source_events = build_source_events(
        request=request,
        framework_version=framework_version,
        graph_result=graph_result,
    )
    return {
        "status": "passed",
        "output_run_id": "run_installed_langgraph_replay_001",
        "actual_side_effect_mode": request.get("side_effect_mode", "network_mocked"),
        "target_map": {
            target_entity_id(request): "span_installed_langgraph_replay_fetch_001",
        },
        "executed_agent": True,
        "note": "installed LangGraph replay smoke completed without live model calls",
        "source_events": source_events,
    }


def build_source_events(
    *,
    request: dict[str, Any],
    framework_version: str,
    graph_result: dict[str, str],
) -> dict[str, Any]:
    now = "2026-01-01T00:00:00Z"
    profile_id = str(request.get("profile_id") or "profile_installed_langgraph_replay")
    source_id = "source_installed_langgraph_replay"
    agent_id = "agent_installed_langgraph_replay"
    node_id = "node_installed_langgraph_replay"
    run_id = "run_installed_langgraph_replay_001"
    root_span_id = "span_installed_langgraph_replay_plan_001"
    tool_span_id = "span_installed_langgraph_replay_fetch_001"
    framework_metadata = {
        "framework": "langgraph-python",
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "replay_smoke": True,
    }
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": "Installed LangGraph Replay Smoke",
            "root_path": ".",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "langgraph-python",
                "display_name": "Installed LangGraph replay source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_replay_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {"replay": True, "trace": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-langgraph-replay-agent",
                "name": "installed-langgraph-replay-agent",
                "kind": "agent",
                "role": "researcher",
                "model": None,
                "workspace_path": ".",
                "metadata_json": dict(framework_metadata),
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "langgraph-replay-plan-fetch",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "replay-plan-fetch",
                "metadata_json": dict(framework_metadata),
            }
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-langgraph-replay-001",
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": request, "kind": "replay_request"},
                "output_ref": None,
                "output_payload": {"content": graph_result, "kind": "replay_output"},
                "summary": "Installed LangGraph replay smoke ran a deterministic graph.",
                "metadata_json": {
                    **framework_metadata,
                    "graph_result": graph_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "langgraph-replay-plan",
                "parent_span_id": None,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "plan",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": graph_result.get("topic")}, "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": {"plan": graph_result.get("plan")}, "kind": "span_output"},
                "usage_json": {},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "langgraph-replay-fetch",
                "parent_span_id": root_span_id,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"plan": graph_result.get("plan")}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": "timeout mocked for replay", "kind": "tool_output"},
                "usage_json": {},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [],
    }


def run_langgraph_replay() -> dict[str, str]:
    def plan_node(state: SmokeState) -> dict[str, str]:
        topic = state.get("topic") or "framework-replay"
        return {"plan": "fetch:" + topic}

    def fetch_node(state: SmokeState) -> dict[str, str]:
        return {"result": "timeout"}

    graph = StateGraph(SmokeState)
    graph.add_node("plan", plan_node)
    graph.add_node("fetch", fetch_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "fetch")
    graph.add_edge("fetch", END)
    app = graph.compile()
    result = app.invoke({"topic": "framework-replay"})
    if not isinstance(result, dict):
        raise RuntimeError(f"LangGraph returned non-object state: {result!r}")
    return {
        "topic": str(result.get("topic", "")),
        "plan": str(result.get("plan", "")),
        "result": str(result.get("result", "")),
    }


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))


def target_entity_id(request: dict[str, Any]) -> str:
    input_payload = request.get("input")
    eval_spec = input_payload.get("eval_spec") if isinstance(input_payload, dict) else {}
    target = eval_spec.get("target") if isinstance(eval_spec, dict) else {}
    entity_id = target.get("entity_id") if isinstance(target, dict) else None
    return entity_id if isinstance(entity_id, str) and entity_id else "span_framework_source"
'''.lstrip()


PYDANTIC_AI_SOURCE_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


def collect(context: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    agent_result = run_pydantic_ai_smoke()
    if not agent_result.get("tool_called"):
        raise RuntimeError(f"Pydantic AI smoke did not call the test tool: {agent_result!r}")
    if "timeout" not in agent_result.get("output", ""):
        raise RuntimeError(f"unexpected Pydantic AI smoke output: {agent_result!r}")

    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    agent_id = context["agent_id"]
    node_id = "node_installed_pydantic_ai_research"
    run_id = "run_installed_pydantic_ai_smoke_001"
    root_span_id = "span_installed_pydantic_ai_agent_001"
    tool_span_id = "span_installed_pydantic_ai_fetch_001"
    framework_metadata = {
        "framework": context["framework"],
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "test_model_invoked": True,
    }
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
                "display_name": "Installed Pydantic AI source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_source_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {
                    "runs": True,
                    "spans": True,
                    "installed_framework_smoke": True,
                },
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
                "model": "pydantic_ai.models.test.TestModel",
                "workspace_path": context["root_path"],
                "metadata_json": dict(framework_metadata),
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-test-model",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "pydantic-ai-test-model",
                "metadata_json": dict(framework_metadata),
            }
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-pydantic-ai-smoke-001",
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"prompt": "Use fetch_source for framework-smoke"},
                    "kind": "agent_prompt",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"result": "fetch_source timed out"},
                    "kind": "agent_error",
                },
                "summary": "Installed Pydantic AI smoke used TestModel and observed a mocked fetch timeout.",
                "metadata_json": {
                    **framework_metadata,
                    "agent_result": agent_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-agent",
                "parent_span_id": None,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "pydantic-ai-agent",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"prompt": "Use fetch_source for framework-smoke"},
                    "kind": "span_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"output": agent_result.get("output")},
                    "kind": "span_output",
                },
                "usage_json": agent_result.get("usage", {}),
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-fetch-source",
                "parent_span_id": root_span_id,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": "framework-smoke"},
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "fetch_source timed out",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "error_type": "timeout",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [],
    }


def run_pydantic_ai_smoke() -> dict[str, Any]:
    agent = Agent(TestModel(), system_prompt="Use tools for smoke validation.")

    @agent.tool_plain
    def fetch_source(topic: str) -> str:
        return "timeout"

    result = agent.run_sync("Use fetch_source for framework-smoke")
    output = str(getattr(result, "output", ""))
    all_messages = result.all_messages() if hasattr(result, "all_messages") else []
    usage = getattr(result, "usage", None)
    usage_json = {}
    if usage is not None:
        try:
            usage_json = dict(usage)
        except (TypeError, ValueError):
            usage_json = {"repr": repr(usage)}
    return {
        "output": output,
        "message_count": len(all_messages),
        "tool_called": "fetch_source" in output or any(
            "fetch_source" in repr(message) for message in all_messages
        ),
        "usage": usage_json,
    }


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))
'''.lstrip()


PYDANTIC_AI_REPLAY_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


def replay(request: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    agent_result = run_pydantic_ai_replay()
    if not agent_result.get("tool_called"):
        raise RuntimeError(f"Pydantic AI replay smoke did not call the test tool: {agent_result!r}")

    source_events = build_source_events(
        request=request,
        framework_version=framework_version,
        agent_result=agent_result,
    )
    return {
        "status": "passed",
        "output_run_id": "run_installed_pydantic_ai_replay_001",
        "actual_side_effect_mode": request.get("side_effect_mode", "network_mocked"),
        "target_map": {
            target_entity_id(request): "span_installed_pydantic_ai_replay_fetch_001",
        },
        "executed_agent": True,
        "note": "installed Pydantic AI replay smoke completed without live model calls",
        "source_events": source_events,
    }


def build_source_events(
    *,
    request: dict[str, Any],
    framework_version: str,
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    now = "2026-01-01T00:00:00Z"
    profile_id = str(request.get("profile_id") or "profile_installed_pydantic_ai_replay")
    source_id = "source_installed_pydantic_ai_replay"
    agent_id = "agent_installed_pydantic_ai_replay"
    node_id = "node_installed_pydantic_ai_replay"
    run_id = "run_installed_pydantic_ai_replay_001"
    root_span_id = "span_installed_pydantic_ai_replay_agent_001"
    tool_span_id = "span_installed_pydantic_ai_replay_fetch_001"
    framework_metadata = {
        "framework": "pydantic-ai-python",
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "test_model_invoked": True,
        "replay_smoke": True,
    }
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": "Installed Pydantic AI Replay Smoke",
            "root_path": ".",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "pydantic-ai-python",
                "display_name": "Installed Pydantic AI replay source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_replay_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {"replay": True, "trace": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-pydantic-ai-replay-agent",
                "name": "installed-pydantic-ai-replay-agent",
                "kind": "agent",
                "role": "researcher",
                "model": "pydantic_ai.models.test.TestModel",
                "workspace_path": ".",
                "metadata_json": dict(framework_metadata),
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-replay-test-model",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "pydantic-ai-replay-test-model",
                "metadata_json": dict(framework_metadata),
            }
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-pydantic-ai-replay-001",
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": request, "kind": "replay_request"},
                "output_ref": None,
                "output_payload": {"content": agent_result, "kind": "replay_output"},
                "summary": "Installed Pydantic AI replay smoke used TestModel and a mocked tool.",
                "metadata_json": {
                    **framework_metadata,
                    "agent_result": agent_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-replay-agent",
                "parent_span_id": None,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "pydantic-ai-agent",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"prompt": "Use fetch_source for framework-replay"}, "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": {"output": agent_result.get("output")}, "kind": "span_output"},
                "usage_json": agent_result.get("usage", {}),
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-replay-fetch-source",
                "parent_span_id": root_span_id,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework-replay"}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": "timeout mocked for replay", "kind": "tool_output"},
                "usage_json": {},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [],
    }


def run_pydantic_ai_replay() -> dict[str, Any]:
    agent = Agent(TestModel(), system_prompt="Use tools for replay smoke validation.")

    @agent.tool_plain
    def fetch_source(topic: str) -> str:
        return "timeout"

    result = agent.run_sync("Use fetch_source for framework-replay")
    output = str(getattr(result, "output", ""))
    all_messages = result.all_messages() if hasattr(result, "all_messages") else []
    usage = getattr(result, "usage", None)
    usage_json = {}
    if usage is not None:
        try:
            usage_json = dict(usage)
        except (TypeError, ValueError):
            usage_json = {"repr": repr(usage)}
    return {
        "output": output,
        "message_count": len(all_messages),
        "tool_called": "fetch_source" in output or any(
            "fetch_source" in repr(message) for message in all_messages
        ),
        "usage": usage_json,
    }


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))


def target_entity_id(request: dict[str, Any]) -> str:
    input_payload = request.get("input")
    eval_spec = input_payload.get("eval_spec") if isinstance(input_payload, dict) else {}
    target = eval_spec.get("target") if isinstance(eval_spec, dict) else {}
    entity_id = target.get("entity_id") if isinstance(target, dict) else None
    return entity_id if isinstance(entity_id, str) and entity_id else "span_framework_source"
'''.lstrip()


OPENAI_AGENTS_SOURCE_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import json
from typing import Any

from agents import (
    Agent,
    Model,
    ModelProvider,
    RunConfig,
    Runner,
    function_tool,
    handoff,
    set_tracing_disabled,
)
from agents.items import ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


def collect(context: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    agent_result = run_openai_agents_smoke("framework-smoke")
    validate_agent_result(agent_result)

    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    planner_agent_id = context["agent_id"]
    researcher_agent_id = "agent_installed_openai_agents_researcher"
    planner_node_id = "node_installed_openai_agents_planner"
    researcher_node_id = "node_installed_openai_agents_researcher"
    run_id = "run_installed_openai_agents_smoke_001"
    root_span_id = "span_installed_openai_agents_planner_001"
    handoff_span_id = "span_installed_openai_agents_handoff_001"
    tool_span_id = "span_installed_openai_agents_fetch_001"
    framework_metadata = {
        "framework": context["framework"],
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "local_model_provider_invoked": True,
        "sdk_handoff_invoked": bool(agent_result.get("handoff_invoked")),
        "sdk_tool_invoked": bool(agent_result.get("tool_called")),
    }
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
                "display_name": "Installed OpenAI Agents source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_source_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {
                    "runs": True,
                    "spans": True,
                    "handoffs": True,
                    "installed_framework_smoke": True,
                },
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": planner_agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": context["agent_name"],
                "name": context["agent_name"],
                "kind": "agent",
                "role": "planner",
                "model": "kyoko.local_openai_agents_smoke_model",
                "workspace_path": context["root_path"],
                "metadata_json": dict(framework_metadata),
            },
            {
                "id": researcher_agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-openai-agents-researcher",
                "name": "installed-openai-agents-researcher",
                "kind": "agent",
                "role": "researcher",
                "model": "kyoko.local_openai_agents_smoke_model",
                "workspace_path": context["root_path"],
                "metadata_json": dict(framework_metadata),
            },
        ],
        "workflow_nodes": [
            {
                "id": planner_node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "openai-agents-planner",
                "agent_identity_id": planner_agent_id,
                "kind": "agent",
                "name": "planner",
                "metadata_json": dict(framework_metadata),
            },
            {
                "id": researcher_node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "openai-agents-researcher",
                "agent_identity_id": researcher_agent_id,
                "kind": "agent",
                "name": "researcher",
                "metadata_json": dict(framework_metadata),
            },
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-openai-agents-smoke-001",
                "root_span_id": root_span_id,
                "agent_identity_id": planner_agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"prompt": "Use researcher to fetch source for framework-smoke"},
                    "kind": "agent_prompt",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"result": agent_result.get("output")},
                    "kind": "agent_error",
                },
                "summary": "Installed OpenAI Agents smoke used a local model provider, handoff, and mocked tool timeout.",
                "metadata_json": {
                    **framework_metadata,
                    "agent_result": agent_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openai-agents-planner",
                "parent_span_id": None,
                "workflow_node_id": planner_node_id,
                "agent_identity_id": planner_agent_id,
                "kind": "agent",
                "name": "planner",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"prompt": "Use researcher to fetch source for framework-smoke"},
                    "kind": "span_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"handoff_to": "researcher"},
                    "kind": "span_output",
                },
                "usage_json": {"model_call_count": agent_result.get("model_call_count")},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": handoff_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openai-agents-handoff",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "handoff",
                "name": "transfer_to_researcher",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"from": "planner", "to": "researcher"},
                    "kind": "handoff_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"assistant": "researcher"},
                    "kind": "handoff_output",
                },
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "openai_agents.handoff.to": "researcher",
                },
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openai-agents-fetch-source",
                "parent_span_id": handoff_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": "framework-smoke"},
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "fetch_source timed out",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "error_type": "timeout",
                    "gen_ai.tool.name": "fetch_source",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_installed_openai_agents_planner_to_researcher_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "run_id": run_id,
                "from_agent_identity_id": planner_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": planner_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": None,
                "to_task_id": None,
                "kind": "agent_handoff",
                "span_id": handoff_span_id,
                "reason_ref": None,
                "reason_payload": {
                    "content": "Planner delegated source lookup to researcher.",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": {"from": "planner", "to": "researcher"},
                    "kind": "handoff_payload",
                },
                "created_at": now,
                "metadata_json": dict(framework_metadata),
            }
        ],
        "timeline_events": [
            {
                "id": "event_installed_openai_agents_fetch_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "span_failed",
                "at": now,
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {
                    "content": "fetch_source timed out",
                    "kind": "tool_error",
                },
                "metadata_json": {
                    **framework_metadata,
                    "error_type": "timeout",
                },
            }
        ],
    }


def run_openai_agents_smoke(topic: str) -> dict[str, Any]:
    set_tracing_disabled(True)
    model = LocalOpenAIAgentsModel(topic=topic)
    provider = LocalOpenAIAgentsModelProvider(model)

    @function_tool
    def fetch_source(topic: str) -> str:
        return "timeout"

    researcher = Agent(
        name="researcher",
        tools=[fetch_source],
        instructions="Fetch the requested source using tools.",
    )
    planner = Agent(
        name="planner",
        handoffs=[handoff(researcher)],
        instructions="Delegate source lookup to the researcher.",
    )
    result = Runner.run_sync(
        planner,
        f"Use researcher to fetch source for {topic}",
        max_turns=5,
        run_config=RunConfig(model_provider=provider, tracing_disabled=True),
    )
    new_items = list(getattr(result, "new_items", []) or [])
    item_types = [type(item).__name__ for item in new_items]
    item_reprs = [repr(getattr(item, "raw_item", item))[:500] for item in new_items]
    last_agent = getattr(getattr(result, "last_agent", None), "name", None)
    return {
        "output": str(getattr(result, "final_output", "")),
        "model_call_count": len(model.calls),
        "model_history": list(model.calls),
        "last_agent": last_agent,
        "new_item_types": item_types,
        "handoff_invoked": last_agent == "researcher" or any("Handoff" in item_type for item_type in item_types),
        "tool_called": any("fetch_source" in item_repr for item_repr in item_reprs)
        or any("ToolCall" in item_type for item_type in item_types),
    }


class LocalOpenAIAgentsModel(Model):
    def __init__(self, *, topic: str) -> None:
        self.topic = topic
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        system_instructions: Any,
        input: Any,
        model_settings: Any,
        tools: Any,
        output_schema: Any,
        handoffs: Any,
        tracing: Any,
        *,
        previous_response_id: Any = None,
        conversation_id: Any = None,
        prompt: Any = None,
    ) -> ModelResponse:
        tool_names = [_object_name(tool) for tool in list(tools or [])]
        handoff_names = [_object_name(handoff_item) for handoff_item in list(handoffs or [])]
        self.calls.append(
            {
                "system_instructions": str(system_instructions or ""),
                "tool_names": tool_names,
                "handoff_names": handoff_names,
            }
        )
        call_number = len(self.calls)
        if call_number == 1:
            if "transfer_to_researcher" not in handoff_names:
                raise RuntimeError(f"OpenAI Agents smoke missing handoff: {handoff_names!r}")
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        arguments="{}",
                        call_id="call_openai_agents_handoff",
                        name="transfer_to_researcher",
                        type="function_call",
                    )
                ],
                usage=Usage(requests=1, input_tokens=4, output_tokens=2),
                response_id="resp_openai_agents_handoff",
            )
        if call_number == 2:
            if "fetch_source" not in tool_names:
                raise RuntimeError(f"OpenAI Agents smoke missing fetch_source tool: {tool_names!r}")
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        arguments=json.dumps({"topic": self.topic}),
                        call_id="call_openai_agents_fetch",
                        name="fetch_source",
                        type="function_call",
                    )
                ],
                usage=Usage(requests=1, input_tokens=6, output_tokens=2),
                response_id="resp_openai_agents_fetch",
            )
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    id="msg_openai_agents_final",
                    content=[
                        ResponseOutputText(
                            annotations=[],
                            text="fetch_source timeout",
                            type="output_text",
                        )
                    ],
                    role="assistant",
                    status="completed",
                    type="message",
                )
            ],
            usage=Usage(requests=1, input_tokens=8, output_tokens=4),
            response_id="resp_openai_agents_final",
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("OpenAI Agents installed smoke does not use streaming")


class LocalOpenAIAgentsModelProvider(ModelProvider):
    def __init__(self, model: LocalOpenAIAgentsModel) -> None:
        self.model = model

    def get_model(self, model_name: Any) -> LocalOpenAIAgentsModel:
        return self.model


def _object_name(value: Any) -> str:
    return str(
        getattr(
            value,
            "name",
            getattr(value, "tool_name", getattr(value, "__name__", repr(value))),
        )
    )


def validate_agent_result(agent_result: dict[str, Any]) -> None:
    if not agent_result.get("handoff_invoked"):
        raise RuntimeError(f"OpenAI Agents smoke did not perform handoff: {agent_result!r}")
    if not agent_result.get("tool_called"):
        raise RuntimeError(f"OpenAI Agents smoke did not call fetch_source: {agent_result!r}")
    if "timeout" not in str(agent_result.get("output", "")):
        raise RuntimeError(f"unexpected OpenAI Agents smoke output: {agent_result!r}")


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))
'''.lstrip()


OPENAI_AGENTS_REPLAY_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import json
from typing import Any

from agents import (
    Agent,
    Model,
    ModelProvider,
    RunConfig,
    Runner,
    function_tool,
    handoff,
    set_tracing_disabled,
)
from agents.items import ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


def replay(request: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    agent_result = run_openai_agents_smoke("framework-replay")
    validate_agent_result(agent_result)
    source_events = build_source_events(
        request=request,
        framework_version=framework_version,
        agent_result=agent_result,
    )
    return {
        "status": "passed",
        "output_run_id": "run_installed_openai_agents_replay_001",
        "actual_side_effect_mode": request.get("side_effect_mode", "network_mocked"),
        "target_map": {
            target_entity_id(request): "span_installed_openai_agents_replay_fetch_001",
        },
        "executed_agent": True,
        "note": "installed OpenAI Agents replay smoke completed with a local model provider",
        "source_events": source_events,
    }


def build_source_events(
    *,
    request: dict[str, Any],
    framework_version: str,
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    now = "2026-01-01T00:00:00Z"
    profile_id = str(request.get("profile_id") or "profile_installed_openai_agents_replay")
    source_id = "source_installed_openai_agents_replay"
    planner_agent_id = "agent_installed_openai_agents_replay_planner"
    researcher_agent_id = "agent_installed_openai_agents_replay_researcher"
    planner_node_id = "node_installed_openai_agents_replay_planner"
    researcher_node_id = "node_installed_openai_agents_replay_researcher"
    run_id = "run_installed_openai_agents_replay_001"
    root_span_id = "span_installed_openai_agents_replay_planner_001"
    handoff_span_id = "span_installed_openai_agents_replay_handoff_001"
    tool_span_id = "span_installed_openai_agents_replay_fetch_001"
    framework_metadata = {
        "framework": "openai-agents-python",
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "local_model_provider_invoked": True,
        "sdk_handoff_invoked": bool(agent_result.get("handoff_invoked")),
        "sdk_tool_invoked": bool(agent_result.get("tool_called")),
        "replay_smoke": True,
    }
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": "Installed OpenAI Agents Replay Smoke",
            "root_path": ".",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "openai-agents-python",
                "display_name": "Installed OpenAI Agents replay source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_replay_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {"replay": True, "trace": True, "handoffs": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            {
                "id": planner_agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-openai-agents-replay-planner",
                "name": "installed-openai-agents-replay-planner",
                "kind": "agent",
                "role": "planner",
                "model": "kyoko.local_openai_agents_smoke_model",
                "workspace_path": ".",
                "metadata_json": dict(framework_metadata),
            },
            {
                "id": researcher_agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-openai-agents-replay-researcher",
                "name": "installed-openai-agents-replay-researcher",
                "kind": "agent",
                "role": "researcher",
                "model": "kyoko.local_openai_agents_smoke_model",
                "workspace_path": ".",
                "metadata_json": dict(framework_metadata),
            },
        ],
        "workflow_nodes": [
            {
                "id": planner_node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-planner",
                "agent_identity_id": planner_agent_id,
                "kind": "agent",
                "name": "planner",
                "metadata_json": dict(framework_metadata),
            },
            {
                "id": researcher_node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-researcher",
                "agent_identity_id": researcher_agent_id,
                "kind": "agent",
                "name": "researcher",
                "metadata_json": dict(framework_metadata),
            },
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-openai-agents-replay-001",
                "root_span_id": root_span_id,
                "agent_identity_id": planner_agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": request, "kind": "replay_request"},
                "output_ref": None,
                "output_payload": {"content": agent_result, "kind": "replay_output"},
                "summary": "Installed OpenAI Agents replay smoke used a local model provider, handoff, and mocked tool.",
                "metadata_json": {
                    **framework_metadata,
                    "agent_result": agent_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-planner",
                "parent_span_id": None,
                "workflow_node_id": planner_node_id,
                "agent_identity_id": planner_agent_id,
                "kind": "agent",
                "name": "planner",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"prompt": "Use researcher to fetch source for framework-replay"}, "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": {"handoff_to": "researcher"}, "kind": "span_output"},
                "usage_json": {"model_call_count": agent_result.get("model_call_count")},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": handoff_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-handoff",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "handoff",
                "name": "transfer_to_researcher",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"from": "planner", "to": "researcher"}, "kind": "handoff_input"},
                "output_ref": None,
                "output_payload": {"content": {"assistant": "researcher"}, "kind": "handoff_output"},
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "openai_agents.handoff.to": "researcher",
                },
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-fetch-source",
                "parent_span_id": handoff_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework-replay"}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": "timeout mocked for replay", "kind": "tool_output"},
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "gen_ai.tool.name": "fetch_source",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_installed_openai_agents_replay_planner_to_researcher_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "run_id": run_id,
                "from_agent_identity_id": planner_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": planner_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": None,
                "to_task_id": None,
                "kind": "agent_handoff",
                "span_id": handoff_span_id,
                "reason_ref": None,
                "reason_payload": {
                    "content": "Planner delegated replay source lookup to researcher.",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": {"from": "planner", "to": "researcher"},
                    "kind": "handoff_payload",
                },
                "created_at": now,
                "metadata_json": dict(framework_metadata),
            }
        ],
        "timeline_events": [
            {
                "id": "event_installed_openai_agents_replay_fetch_success_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "tool_retry_succeeded",
                "at": now,
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {
                    "content": "fetch_source returned the mocked replay timeout payload",
                    "kind": "tool_output",
                },
                "metadata_json": dict(framework_metadata),
            }
        ],
    }


def run_openai_agents_smoke(topic: str) -> dict[str, Any]:
    set_tracing_disabled(True)
    model = LocalOpenAIAgentsModel(topic=topic)
    provider = LocalOpenAIAgentsModelProvider(model)

    @function_tool
    def fetch_source(topic: str) -> str:
        return "timeout"

    researcher = Agent(
        name="researcher",
        tools=[fetch_source],
        instructions="Fetch the requested source using tools.",
    )
    planner = Agent(
        name="planner",
        handoffs=[handoff(researcher)],
        instructions="Delegate source lookup to the researcher.",
    )
    result = Runner.run_sync(
        planner,
        f"Use researcher to fetch source for {topic}",
        max_turns=5,
        run_config=RunConfig(model_provider=provider, tracing_disabled=True),
    )
    new_items = list(getattr(result, "new_items", []) or [])
    item_types = [type(item).__name__ for item in new_items]
    item_reprs = [repr(getattr(item, "raw_item", item))[:500] for item in new_items]
    last_agent = getattr(getattr(result, "last_agent", None), "name", None)
    return {
        "output": str(getattr(result, "final_output", "")),
        "model_call_count": len(model.calls),
        "model_history": list(model.calls),
        "last_agent": last_agent,
        "new_item_types": item_types,
        "handoff_invoked": last_agent == "researcher" or any("Handoff" in item_type for item_type in item_types),
        "tool_called": any("fetch_source" in item_repr for item_repr in item_reprs)
        or any("ToolCall" in item_type for item_type in item_types),
    }


class LocalOpenAIAgentsModel(Model):
    def __init__(self, *, topic: str) -> None:
        self.topic = topic
        self.calls: list[dict[str, Any]] = []

    async def get_response(
        self,
        system_instructions: Any,
        input: Any,
        model_settings: Any,
        tools: Any,
        output_schema: Any,
        handoffs: Any,
        tracing: Any,
        *,
        previous_response_id: Any = None,
        conversation_id: Any = None,
        prompt: Any = None,
    ) -> ModelResponse:
        tool_names = [_object_name(tool) for tool in list(tools or [])]
        handoff_names = [_object_name(handoff_item) for handoff_item in list(handoffs or [])]
        self.calls.append(
            {
                "system_instructions": str(system_instructions or ""),
                "tool_names": tool_names,
                "handoff_names": handoff_names,
            }
        )
        call_number = len(self.calls)
        if call_number == 1:
            if "transfer_to_researcher" not in handoff_names:
                raise RuntimeError(f"OpenAI Agents replay smoke missing handoff: {handoff_names!r}")
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        arguments="{}",
                        call_id="call_openai_agents_replay_handoff",
                        name="transfer_to_researcher",
                        type="function_call",
                    )
                ],
                usage=Usage(requests=1, input_tokens=4, output_tokens=2),
                response_id="resp_openai_agents_replay_handoff",
            )
        if call_number == 2:
            if "fetch_source" not in tool_names:
                raise RuntimeError(f"OpenAI Agents replay smoke missing fetch_source tool: {tool_names!r}")
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        arguments=json.dumps({"topic": self.topic}),
                        call_id="call_openai_agents_replay_fetch",
                        name="fetch_source",
                        type="function_call",
                    )
                ],
                usage=Usage(requests=1, input_tokens=6, output_tokens=2),
                response_id="resp_openai_agents_replay_fetch",
            )
        return ModelResponse(
            output=[
                ResponseOutputMessage(
                    id="msg_openai_agents_replay_final",
                    content=[
                        ResponseOutputText(
                            annotations=[],
                            text="fetch_source timeout",
                            type="output_text",
                        )
                    ],
                    role="assistant",
                    status="completed",
                    type="message",
                )
            ],
            usage=Usage(requests=1, input_tokens=8, output_tokens=4),
            response_id="resp_openai_agents_replay_final",
        )

    def stream_response(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("OpenAI Agents installed replay smoke does not use streaming")


class LocalOpenAIAgentsModelProvider(ModelProvider):
    def __init__(self, model: LocalOpenAIAgentsModel) -> None:
        self.model = model

    def get_model(self, model_name: Any) -> LocalOpenAIAgentsModel:
        return self.model


def _object_name(value: Any) -> str:
    return str(
        getattr(
            value,
            "name",
            getattr(value, "tool_name", getattr(value, "__name__", repr(value))),
        )
    )


def validate_agent_result(agent_result: dict[str, Any]) -> None:
    if not agent_result.get("handoff_invoked"):
        raise RuntimeError(f"OpenAI Agents replay smoke did not perform handoff: {agent_result!r}")
    if not agent_result.get("tool_called"):
        raise RuntimeError(f"OpenAI Agents replay smoke did not call fetch_source: {agent_result!r}")
    if "timeout" not in str(agent_result.get("output", "")):
        raise RuntimeError(f"unexpected OpenAI Agents replay smoke output: {agent_result!r}")


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))


def target_entity_id(request: dict[str, Any]) -> str:
    input_payload = request.get("input")
    eval_spec = input_payload.get("eval_spec") if isinstance(input_payload, dict) else {}
    target = eval_spec.get("target") if isinstance(eval_spec, dict) else {}
    entity_id = target.get("entity_id") if isinstance(target, dict) else None
    return entity_id if isinstance(entity_id, str) and entity_id else "span_framework_source"
'''.lstrip()


CREWAI_SOURCE_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import os
from typing import Any

from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tools import tool


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


def collect(context: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    crew_result = run_crewai_smoke("framework-smoke")
    validate_crewai_result(crew_result)

    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    manager_agent_id = context["agent_id"]
    researcher_agent_id = "agent_installed_crewai_researcher"
    manager_node_id = "node_installed_crewai_manager"
    researcher_node_id = "node_installed_crewai_researcher"
    queue_id = "queue_installed_crewai_news_crew"
    research_task_id = "task_installed_crewai_research_001"
    writing_task_id = "task_installed_crewai_write_001"
    attempt_id = "attempt_installed_crewai_research_001"
    run_id = "run_installed_crewai_smoke_001"
    root_span_id = "span_installed_crewai_kickoff_001"
    task_span_id = "span_installed_crewai_research_task_001"
    tool_span_id = "span_installed_crewai_fetch_source_001"
    framework_metadata = {
        "framework": context["framework"],
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "local_llm_invoked": bool(crew_result.get("local_llm_invoked")),
        "crew_kickoff_invoked": bool(crew_result.get("crew_kickoff_invoked")),
        "crewai_tool_run_invoked": bool(crew_result.get("tool_run_invoked")),
    }
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
                "display_name": "Installed CrewAI source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_source_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {
                    "runs": True,
                    "spans": True,
                    "tasks": True,
                    "handoffs": True,
                    "installed_framework_smoke": True,
                },
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=manager_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                external_id=context["agent_name"],
                name=context["agent_name"],
                role="crew manager",
                workspace_path=context["root_path"],
                metadata=framework_metadata,
            ),
            _agent(
                agent_id=researcher_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                external_id="installed-crewai-researcher",
                name="installed-crewai-researcher",
                role="researcher",
                workspace_path=context["root_path"],
                metadata=framework_metadata,
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=manager_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=manager_agent_id,
                external_id="crewai-manager",
                name="crew.manager",
                metadata=framework_metadata,
            ),
            _node(
                node_id=researcher_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=researcher_agent_id,
                external_id="crewai-researcher",
                name="crew.researcher",
                metadata=framework_metadata,
            ),
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-crewai-news-crew",
                "name": "installed CrewAI news crew",
                "kind": "crewai_crew",
                "metadata_json": {
                    **framework_metadata,
                    "process": "sequential",
                },
            }
        ],
        "tasks": [
            _task(
                task_id=research_task_id,
                profile_id=profile_id,
                source_id=source_id,
                queue_id=queue_id,
                title="Research framework-smoke source",
                assignee_agent_id=researcher_agent_id,
                created_by_agent_id=manager_agent_id,
                workspace_path=context["root_path"],
                started_at=now,
                completed_at=now,
                status="failed",
                metadata=framework_metadata,
            ),
            _task(
                task_id=writing_task_id,
                profile_id=profile_id,
                source_id=source_id,
                queue_id=queue_id,
                title="Draft sourced brief",
                assignee_agent_id=manager_agent_id,
                created_by_agent_id=manager_agent_id,
                workspace_path=context["root_path"],
                started_at=None,
                completed_at=None,
                status="blocked",
                metadata=framework_metadata,
            ),
        ],
        "task_attempts": [
            {
                "id": attempt_id,
                "task_id": research_task_id,
                "run_id": run_id,
                "agent_identity_id": researcher_agent_id,
                "status": "failed",
                "outcome": "source_fetch_timeout",
                "claim_token_hash": "installed-crewai-smoke-claim",
                "worker_pid": None,
                "started_at": now,
                "ended_at": now,
                "last_heartbeat_at": now,
                "summary_ref": None,
                "summary_payload": {
                    "content": "CrewAI local LLM completed the task with a mocked fetch_source timeout.",
                    "kind": "task_attempt_summary",
                },
                "metadata_json": {
                    **framework_metadata,
                    "crew_result": crew_result,
                },
                "error_ref": None,
                "error_payload": {
                    "content": "fetch_source timed out",
                    "kind": "task_attempt_error",
                },
            }
        ],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-crewai-smoke-001",
                "root_span_id": root_span_id,
                "agent_identity_id": manager_agent_id,
                "task_attempt_id": attempt_id,
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": "framework-smoke"},
                    "kind": "crew_goal",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"result": crew_result.get("output")},
                    "kind": "crew_error",
                },
                "summary": "Installed CrewAI smoke ran a deterministic crew/task with a local LLM and mocked tool timeout.",
                "metadata_json": {
                    **framework_metadata,
                    "crew_result": crew_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-kickoff",
                "parent_span_id": None,
                "workflow_node_id": manager_node_id,
                "agent_identity_id": manager_agent_id,
                "kind": "agent",
                "name": "crew.kickoff",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework-smoke"}, "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": {"task": research_task_id}, "kind": "span_output"},
                "usage_json": {"llm_call_count": crew_result.get("llm_call_count")},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": task_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-research-task",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "agent",
                "name": "research_task",
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"task_id": research_task_id}, "kind": "task_input"},
                "output_ref": None,
                "output_payload": {"content": {"result": crew_result.get("output")}, "kind": "task_output"},
                "usage_json": {},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-fetch-source",
                "parent_span_id": task_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework-smoke"}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": crew_result.get("tool_output"), "kind": "tool_error"},
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "error_type": "timeout",
                    "crewai.tool.name": "fetch_source",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_installed_crewai_manager_to_researcher_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "run_id": run_id,
                "from_agent_identity_id": manager_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": manager_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": None,
                "to_task_id": research_task_id,
                "kind": "task_delegation",
                "span_id": task_span_id,
                "reason_ref": None,
                "reason_payload": {
                    "content": "Crew manager assigned the research task.",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": {"from": "manager", "to": "researcher", "task_id": research_task_id},
                    "kind": "handoff_payload",
                },
                "created_at": now,
                "metadata_json": dict(framework_metadata),
            }
        ],
        "timeline_events": [
            {
                "id": "event_installed_crewai_fetch_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "span_failed",
                "at": now,
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {"content": "fetch_source timed out", "kind": "tool_error"},
                "metadata_json": dict(framework_metadata),
            }
        ],
    }


def run_crewai_smoke(topic: str) -> dict[str, Any]:
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    try:
        from crewai.events.listeners.tracing.utils import set_suppress_tracing_messages

        set_suppress_tracing_messages(True)
    except Exception:
        pass

    @tool("fetch_source")
    def fetch_source(topic: str) -> str:
        """Fetch a source for a topic."""
        return "timeout"

    llm = LocalCrewAILLM()
    researcher = Agent(
        role="researcher",
        goal="Fetch source",
        backstory="Local Kyoko installed CrewAI smoke agent.",
        llm=llm,
        tools=[fetch_source],
        verbose=False,
        max_iter=1,
    )
    task = Task(
        description=f"Research {topic} and report timeout",
        expected_output="timeout report",
        agent=researcher,
        tools=[fetch_source],
    )
    crew = Crew(
        agents=[researcher],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        memory=False,
        tracing=False,
    )
    output = crew.kickoff(inputs={"topic": topic})
    tool_output = fetch_source.run(topic=topic)
    raw_output = str(getattr(output, "raw", output))
    task_outputs = list(getattr(output, "tasks_output", []) or [])
    return {
        "output": raw_output,
        "tool_output": str(tool_output),
        "llm_call_count": len(llm.calls),
        "llm_calls": list(llm.calls),
        "task_output_count": len(task_outputs),
        "crew_kickoff_invoked": True,
        "local_llm_invoked": len(llm.calls) >= 1,
        "tool_run_invoked": str(tool_output) == "timeout",
    }


class LocalCrewAILLM(BaseLLM):
    def __init__(self) -> None:
        super().__init__(model="kyoko-local-crewai-smoke", provider="kyoko")
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        self.calls.append(
            {
                "message_count": len(messages) if isinstance(messages, list) else 1,
                "tools": [_object_name(item) for item in list(tools or [])],
                "available_functions": sorted((available_functions or {}).keys()),
                "task": str(getattr(from_task, "description", "")),
                "agent": str(getattr(from_agent, "role", "")),
            }
        )
        return "fetch_source timeout; writing task blocked"


def _agent(
    *,
    agent_id: str,
    profile_id: str,
    source_id: str,
    external_id: str,
    name: str,
    role: str,
    workspace_path: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": external_id,
        "name": name,
        "kind": "agent",
        "role": role,
        "model": "kyoko.local_crewai_smoke_llm",
        "workspace_path": workspace_path,
        "metadata_json": dict(metadata),
    }


def _node(
    *,
    node_id: str,
    profile_id: str,
    source_id: str,
    agent_id: str,
    external_id: str,
    name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": external_id,
        "agent_identity_id": agent_id,
        "kind": "agent",
        "name": name,
        "metadata_json": dict(metadata),
    }


def _task(
    *,
    task_id: str,
    profile_id: str,
    source_id: str,
    queue_id: str,
    title: str,
    assignee_agent_id: str,
    created_by_agent_id: str,
    workspace_path: str,
    started_at: str | None,
    completed_at: str | None,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": task_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "queue_id": queue_id,
        "parent_task_id": None,
        "external_id": task_id,
        "title": title,
        "body_ref": None,
        "status": status,
        "priority": "normal",
        "assignee_agent_identity_id": assignee_agent_id,
        "created_by_agent_identity_id": created_by_agent_id,
        "workspace_kind": "temp",
        "workspace_path": workspace_path,
        "input_ref": None,
        "input_payload": {"content": title, "kind": "task_input"},
        "output_ref": None,
        "output_payload": None,
        "created_at": started_at or "2026-01-01T00:00:00Z",
        "updated_at": completed_at or started_at or "2026-01-01T00:00:00Z",
        "started_at": started_at,
        "completed_at": completed_at,
        "metadata_json": dict(metadata),
    }


def _object_name(value: Any) -> str:
    return str(getattr(value, "name", getattr(value, "__name__", repr(value))))


def validate_crewai_result(crew_result: dict[str, Any]) -> None:
    if not crew_result.get("crew_kickoff_invoked"):
        raise RuntimeError(f"CrewAI smoke did not run crew kickoff: {crew_result!r}")
    if not crew_result.get("local_llm_invoked"):
        raise RuntimeError(f"CrewAI smoke did not invoke the local LLM: {crew_result!r}")
    if not crew_result.get("tool_run_invoked"):
        raise RuntimeError(f"CrewAI smoke did not invoke fetch_source tool wrapper: {crew_result!r}")
    if "timeout" not in str(crew_result.get("output", "")):
        raise RuntimeError(f"unexpected CrewAI smoke output: {crew_result!r}")


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))
'''.lstrip()


CREWAI_REPLAY_HOOK_TEMPLATE = r'''
from __future__ import annotations

import importlib
import importlib.metadata as metadata
import os
from typing import Any

from crewai import Agent, Crew, Process, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tools import tool


PACKAGE_NAME = "__PACKAGE_NAME__"
IMPORT_NAME = "__IMPORT_NAME__"


def replay(request: dict[str, Any]) -> dict[str, Any]:
    framework_version = package_version()
    crew_result = run_crewai_smoke("framework-replay")
    validate_crewai_result(crew_result)
    source_events = build_source_events(
        request=request,
        framework_version=framework_version,
        crew_result=crew_result,
    )
    return {
        "status": "passed",
        "output_run_id": "run_installed_crewai_replay_001",
        "actual_side_effect_mode": request.get("side_effect_mode", "network_mocked"),
        "target_map": {
            target_entity_id(request): "span_installed_crewai_replay_fetch_source_001",
        },
        "executed_agent": True,
        "note": "installed CrewAI replay smoke completed with a local LLM",
        "source_events": source_events,
    }


def build_source_events(
    *,
    request: dict[str, Any],
    framework_version: str,
    crew_result: dict[str, Any],
) -> dict[str, Any]:
    now = "2026-01-01T00:00:00Z"
    profile_id = str(request.get("profile_id") or "profile_installed_crewai_replay")
    source_id = "source_installed_crewai_replay"
    manager_agent_id = "agent_installed_crewai_replay_manager"
    researcher_agent_id = "agent_installed_crewai_replay_researcher"
    manager_node_id = "node_installed_crewai_replay_manager"
    researcher_node_id = "node_installed_crewai_replay_researcher"
    queue_id = "queue_installed_crewai_replay_crew"
    research_task_id = "task_installed_crewai_replay_research_001"
    writing_task_id = "task_installed_crewai_replay_write_001"
    attempt_id = "attempt_installed_crewai_replay_research_001"
    run_id = "run_installed_crewai_replay_001"
    root_span_id = "span_installed_crewai_replay_kickoff_001"
    task_span_id = "span_installed_crewai_replay_research_task_001"
    tool_span_id = "span_installed_crewai_replay_fetch_source_001"
    framework_metadata = {
        "framework": "crewai-python",
        "framework_package": PACKAGE_NAME,
        "framework_version": framework_version,
        "installed_framework_invoked": True,
        "external_model_invoked": False,
        "live_operator_invoked": False,
        "local_llm_invoked": bool(crew_result.get("local_llm_invoked")),
        "crew_kickoff_invoked": bool(crew_result.get("crew_kickoff_invoked")),
        "crewai_tool_run_invoked": bool(crew_result.get("tool_run_invoked")),
        "replay_smoke": True,
    }
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": "Installed CrewAI Replay Smoke",
            "root_path": ".",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "crewai-python",
                "display_name": "Installed CrewAI replay source",
                "status": "active",
                "adapter_version": "kyoko.installed_framework_replay_smoke.v0",
                "config_json": dict(framework_metadata),
                "capabilities_json": {"replay": True, "trace": True, "tasks": True, "handoffs": True},
                "last_seen_at": now,
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=manager_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                external_id="installed-crewai-replay-manager",
                name="installed-crewai-replay-manager",
                role="crew manager",
                workspace_path=".",
                metadata=framework_metadata,
            ),
            _agent(
                agent_id=researcher_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                external_id="installed-crewai-replay-researcher",
                name="installed-crewai-replay-researcher",
                role="researcher",
                workspace_path=".",
                metadata=framework_metadata,
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=manager_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=manager_agent_id,
                external_id="crewai-replay-manager",
                name="crew.manager",
                metadata=framework_metadata,
            ),
            _node(
                node_id=researcher_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=researcher_agent_id,
                external_id="crewai-replay-researcher",
                name="crew.researcher",
                metadata=framework_metadata,
            ),
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-crewai-replay-crew",
                "name": "installed CrewAI replay crew",
                "kind": "crewai_crew",
                "metadata_json": {
                    **framework_metadata,
                    "process": "sequential",
                },
            }
        ],
        "tasks": [
            _task(
                task_id=research_task_id,
                profile_id=profile_id,
                source_id=source_id,
                queue_id=queue_id,
                title="Replay research source fetch",
                assignee_agent_id=researcher_agent_id,
                created_by_agent_id=manager_agent_id,
                workspace_path=".",
                started_at=now,
                completed_at=now,
                status="succeeded",
                metadata=framework_metadata,
            ),
            _task(
                task_id=writing_task_id,
                profile_id=profile_id,
                source_id=source_id,
                queue_id=queue_id,
                title="Draft replay brief",
                assignee_agent_id=manager_agent_id,
                created_by_agent_id=manager_agent_id,
                workspace_path=".",
                started_at=None,
                completed_at=None,
                status="blocked",
                metadata=framework_metadata,
            ),
        ],
        "task_attempts": [
            {
                "id": attempt_id,
                "task_id": research_task_id,
                "run_id": run_id,
                "agent_identity_id": researcher_agent_id,
                "status": "succeeded",
                "outcome": "mocked_source_fetch_timeout_replayed",
                "claim_token_hash": "installed-crewai-replay-claim",
                "worker_pid": None,
                "started_at": now,
                "ended_at": now,
                "last_heartbeat_at": now,
                "summary_ref": None,
                "summary_payload": {
                    "content": "CrewAI replay completed with local LLM and mocked fetch_source tool.",
                    "kind": "task_attempt_summary",
                },
                "metadata_json": {
                    **framework_metadata,
                    "crew_result": crew_result,
                },
                "error_ref": None,
                "error_payload": None,
            }
        ],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "installed-crewai-replay-001",
                "root_span_id": root_span_id,
                "agent_identity_id": manager_agent_id,
                "task_attempt_id": attempt_id,
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": request, "kind": "replay_request"},
                "output_ref": None,
                "output_payload": {"content": crew_result, "kind": "replay_output"},
                "summary": "Installed CrewAI replay smoke ran a deterministic crew/task with local LLM and mocked tool.",
                "metadata_json": {
                    **framework_metadata,
                    "crew_result": crew_result,
                },
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-replay-kickoff",
                "parent_span_id": None,
                "workflow_node_id": manager_node_id,
                "agent_identity_id": manager_agent_id,
                "kind": "agent",
                "name": "crew.kickoff",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework-replay"}, "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": {"task": research_task_id}, "kind": "span_output"},
                "usage_json": {"llm_call_count": crew_result.get("llm_call_count")},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": task_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-replay-research-task",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "agent",
                "name": "research_task",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"task_id": research_task_id}, "kind": "task_input"},
                "output_ref": None,
                "output_payload": {"content": {"result": crew_result.get("output")}, "kind": "task_output"},
                "usage_json": {},
                "attributes_json": dict(framework_metadata),
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-replay-fetch-source",
                "parent_span_id": task_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": now,
                "ended_at": now,
                "input_ref": None,
                "input_payload": {"content": {"topic": "framework-replay"}, "kind": "tool_args"},
                "output_ref": None,
                "output_payload": {"content": "timeout mocked for replay", "kind": "tool_output"},
                "usage_json": {},
                "attributes_json": {
                    **framework_metadata,
                    "crewai.tool.name": "fetch_source",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_installed_crewai_replay_manager_to_researcher_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "run_id": run_id,
                "from_agent_identity_id": manager_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": manager_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": None,
                "to_task_id": research_task_id,
                "kind": "task_delegation",
                "span_id": task_span_id,
                "reason_ref": None,
                "reason_payload": {
                    "content": "Crew manager assigned the replay research task.",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": {"from": "manager", "to": "researcher", "task_id": research_task_id},
                    "kind": "handoff_payload",
                },
                "created_at": now,
                "metadata_json": dict(framework_metadata),
            }
        ],
        "timeline_events": [
            {
                "id": "event_installed_crewai_replay_fetch_success_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "tool_retry_succeeded",
                "at": now,
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {"content": "fetch_source returned mocked replay timeout", "kind": "tool_output"},
                "metadata_json": dict(framework_metadata),
            }
        ],
    }


def run_crewai_smoke(topic: str) -> dict[str, Any]:
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    try:
        from crewai.events.listeners.tracing.utils import set_suppress_tracing_messages

        set_suppress_tracing_messages(True)
    except Exception:
        pass

    @tool("fetch_source")
    def fetch_source(topic: str) -> str:
        """Fetch a source for a topic."""
        return "timeout"

    llm = LocalCrewAILLM()
    researcher = Agent(
        role="researcher",
        goal="Fetch source",
        backstory="Local Kyoko installed CrewAI replay smoke agent.",
        llm=llm,
        tools=[fetch_source],
        verbose=False,
        max_iter=1,
    )
    task = Task(
        description=f"Research {topic} and report timeout",
        expected_output="timeout report",
        agent=researcher,
        tools=[fetch_source],
    )
    crew = Crew(
        agents=[researcher],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
        memory=False,
        tracing=False,
    )
    output = crew.kickoff(inputs={"topic": topic})
    tool_output = fetch_source.run(topic=topic)
    raw_output = str(getattr(output, "raw", output))
    task_outputs = list(getattr(output, "tasks_output", []) or [])
    return {
        "output": raw_output,
        "tool_output": str(tool_output),
        "llm_call_count": len(llm.calls),
        "llm_calls": list(llm.calls),
        "task_output_count": len(task_outputs),
        "crew_kickoff_invoked": True,
        "local_llm_invoked": len(llm.calls) >= 1,
        "tool_run_invoked": str(tool_output) == "timeout",
    }


class LocalCrewAILLM(BaseLLM):
    def __init__(self) -> None:
        super().__init__(model="kyoko-local-crewai-replay-smoke", provider="kyoko")
        self.calls: list[dict[str, Any]] = []

    def call(
        self,
        messages: Any,
        tools: Any = None,
        callbacks: Any = None,
        available_functions: Any = None,
        from_task: Any = None,
        from_agent: Any = None,
        response_model: Any = None,
    ) -> str:
        self.calls.append(
            {
                "message_count": len(messages) if isinstance(messages, list) else 1,
                "tools": [_object_name(item) for item in list(tools or [])],
                "available_functions": sorted((available_functions or {}).keys()),
                "task": str(getattr(from_task, "description", "")),
                "agent": str(getattr(from_agent, "role", "")),
            }
        )
        return "fetch_source timeout; writing task blocked"


def _agent(
    *,
    agent_id: str,
    profile_id: str,
    source_id: str,
    external_id: str,
    name: str,
    role: str,
    workspace_path: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": external_id,
        "name": name,
        "kind": "agent",
        "role": role,
        "model": "kyoko.local_crewai_smoke_llm",
        "workspace_path": workspace_path,
        "metadata_json": dict(metadata),
    }


def _node(
    *,
    node_id: str,
    profile_id: str,
    source_id: str,
    agent_id: str,
    external_id: str,
    name: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": external_id,
        "agent_identity_id": agent_id,
        "kind": "agent",
        "name": name,
        "metadata_json": dict(metadata),
    }


def _task(
    *,
    task_id: str,
    profile_id: str,
    source_id: str,
    queue_id: str,
    title: str,
    assignee_agent_id: str,
    created_by_agent_id: str,
    workspace_path: str,
    started_at: str | None,
    completed_at: str | None,
    status: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": task_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "queue_id": queue_id,
        "parent_task_id": None,
        "external_id": task_id,
        "title": title,
        "body_ref": None,
        "status": status,
        "priority": "normal",
        "assignee_agent_identity_id": assignee_agent_id,
        "created_by_agent_identity_id": created_by_agent_id,
        "workspace_kind": "temp",
        "workspace_path": workspace_path,
        "input_ref": None,
        "input_payload": {"content": title, "kind": "task_input"},
        "output_ref": None,
        "output_payload": None,
        "created_at": started_at or "2026-01-01T00:00:00Z",
        "updated_at": completed_at or started_at or "2026-01-01T00:00:00Z",
        "started_at": started_at,
        "completed_at": completed_at,
        "metadata_json": dict(metadata),
    }


def _object_name(value: Any) -> str:
    return str(getattr(value, "name", getattr(value, "__name__", repr(value))))


def validate_crewai_result(crew_result: dict[str, Any]) -> None:
    if not crew_result.get("crew_kickoff_invoked"):
        raise RuntimeError(f"CrewAI replay smoke did not run crew kickoff: {crew_result!r}")
    if not crew_result.get("local_llm_invoked"):
        raise RuntimeError(f"CrewAI replay smoke did not invoke the local LLM: {crew_result!r}")
    if not crew_result.get("tool_run_invoked"):
        raise RuntimeError(f"CrewAI replay smoke did not invoke fetch_source tool wrapper: {crew_result!r}")
    if "timeout" not in str(crew_result.get("output", "")):
        raise RuntimeError(f"unexpected CrewAI replay smoke output: {crew_result!r}")


def package_version() -> str:
    try:
        return metadata.version(PACKAGE_NAME)
    except metadata.PackageNotFoundError:
        module = importlib.import_module(IMPORT_NAME)
        return str(getattr(module, "__version__", "unknown"))


def target_entity_id(request: dict[str, Any]) -> str:
    input_payload = request.get("input")
    eval_spec = input_payload.get("eval_spec") if isinstance(input_payload, dict) else {}
    target = eval_spec.get("target") if isinstance(eval_spec, dict) else {}
    entity_id = target.get("entity_id") if isinstance(target, dict) else None
    return entity_id if isinstance(entity_id, str) and entity_id else "span_framework_source"
'''.lstrip()
