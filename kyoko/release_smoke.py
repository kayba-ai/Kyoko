from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence


ARTIFACT_CHOICES = ("wheel", "sdist")
DEFAULT_RELEASE_PYTHON_TARGETS = ("3.12", "3.13")
BUILD_BACKEND_REQUIREMENTS = ("setuptools>=58", "wheel>=0.37")
BUILD_BACKEND_CHECK_MODULES = ("setuptools.build_meta", "wheel.bdist_wheel")


class ReleaseSmokeError(Exception):
    """Raised when release install smoke cannot complete."""


@dataclass(frozen=True)
class CommandSmokeReport:
    name: str
    command: tuple[str, ...]
    cwd: Path
    returncode: int
    duration_ms: float
    stdout_tail: str

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": list(self.command),
            "cwd": str(self.cwd),
            "returncode": self.returncode,
            "duration_ms": self.duration_ms,
            "stdout_tail": self.stdout_tail,
        }


@dataclass(frozen=True)
class ArtifactInstallSmokeReport:
    artifact_type: str
    artifact_path: Path
    venv_path: Path
    run_cwd: Path
    installed_version: str
    doctor_ok: bool
    doctor_summary: dict[str, Any]
    dashboard_smoke_ok: Optional[bool]
    dashboard_smoke_summary: Optional[dict[str, Any]]
    commands: tuple[CommandSmokeReport, ...]

    def to_json(self) -> dict[str, Any]:
        modern_install = next(
            (
                command
                for command in self.commands
                if command.name == f"install_{self.artifact_type}"
            ),
            None,
        )
        legacy_fallback = next(
            (
                command
                for command in self.commands
                if command.name == "install_sdist_legacy_setup_py"
            ),
            None,
        )
        install_strategy = "legacy_setup_py" if legacy_fallback is not None else "pip"
        install_ok = (
            bool(modern_install and modern_install.returncode == 0)
            or bool(legacy_fallback and legacy_fallback.returncode == 0)
        )
        return {
            "artifact_type": self.artifact_type,
            "artifact_path": str(self.artifact_path),
            "venv_path": str(self.venv_path),
            "run_cwd": str(self.run_cwd),
            "installed_version": self.installed_version,
            "install_ok": install_ok,
            "install_strategy": install_strategy,
            "modern_install_returncode": (
                modern_install.returncode if modern_install is not None else None
            ),
            "legacy_fallback_used": legacy_fallback is not None,
            "doctor_ok": self.doctor_ok,
            "doctor_summary": self.doctor_summary,
            "dashboard_smoke_ok": self.dashboard_smoke_ok,
            "dashboard_smoke_summary": self.dashboard_smoke_summary,
            "commands": [command.to_json() for command in self.commands],
        }


@dataclass(frozen=True)
class ReleaseInstallSmokeReport:
    project_root: Path
    output_dir: Path
    artifact_dir: Path
    python_executable: str
    install_dependencies: bool
    run_demo: bool
    dashboard_smoke: bool
    artifacts: tuple[ArtifactInstallSmokeReport, ...]
    build_commands: tuple[CommandSmokeReport, ...]
    passed: bool
    duration_ms: float

    def to_json(self) -> dict[str, Any]:
        return {
            "project_root": str(self.project_root),
            "output_dir": str(self.output_dir),
            "artifact_dir": str(self.artifact_dir),
            "python_executable": self.python_executable,
            "install_dependencies": self.install_dependencies,
            "run_demo": self.run_demo,
            "dashboard_smoke": self.dashboard_smoke,
            "artifacts": [artifact.to_json() for artifact in self.artifacts],
            "build_commands": [command.to_json() for command in self.build_commands],
            "passed": self.passed,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True)
class PythonReleaseSmokeTargetReport:
    target: str
    python_executable: Optional[str]
    status: str
    reason: Optional[str]
    report: Optional[ReleaseInstallSmokeReport]

    def to_json(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "python_executable": self.python_executable,
            "status": self.status,
            "reason": self.reason,
            "report": self.report.to_json() if self.report is not None else None,
        }


@dataclass(frozen=True)
class ReleaseInstallSmokeMatrixReport:
    project_root: Path
    output_dir: Path
    python_targets: tuple[str, ...]
    artifact_types: tuple[str, ...]
    install_dependencies: bool
    run_demo: bool
    dashboard_smoke: bool
    targets: tuple[PythonReleaseSmokeTargetReport, ...]
    passed: bool
    duration_ms: float

    def to_json(self) -> dict[str, Any]:
        summary = _matrix_summary(self.targets)
        return {
            "project_root": str(self.project_root),
            "output_dir": str(self.output_dir),
            "python_targets": list(self.python_targets),
            "artifact_types": list(self.artifact_types),
            "install_dependencies": self.install_dependencies,
            "run_demo": self.run_demo,
            "dashboard_smoke": self.dashboard_smoke,
            "targets": [target.to_json() for target in self.targets],
            "summary": summary,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
        }


def run_release_install_smoke(
    *,
    project_root: Path,
    output_dir: Path,
    artifact_types: Sequence[str] = ARTIFACT_CHOICES,
    install_dependencies: bool = False,
    run_demo: bool = True,
    dashboard_smoke: bool = False,
    python_executable: Optional[str] = None,
    timeout_seconds: int = 180,
) -> ReleaseInstallSmokeReport:
    start = time.perf_counter()
    root = project_root.resolve()
    _validate_project_root(root)
    selected_artifacts = _normalize_artifact_types(artifact_types)
    selected_python = python_executable or sys.executable
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_commands: list[CommandSmokeReport] = []
    build_backend_reason = python_build_backend_reason(
        python_executable=selected_python,
        timeout_seconds=timeout_seconds,
    )
    if build_backend_reason is not None:
        selected_python, build_backend_commands = _prepare_build_python_environment(
            python_executable=selected_python,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
        )
        build_commands.extend(build_backend_commands)
    artifact_dir = output_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    build_source = _copy_project_source(root, output_dir / f"source-{uuid.uuid4().hex[:8]}")

    built_artifacts: dict[str, Path] = {}
    if "wheel" in selected_artifacts:
        path, command_report = _build_wheel(
            project_root=build_source,
            artifact_dir=artifact_dir,
            python_executable=selected_python,
            timeout_seconds=timeout_seconds,
        )
        built_artifacts["wheel"] = path
        build_commands.append(command_report)
    if "sdist" in selected_artifacts:
        path, command_report = _build_sdist(
            project_root=build_source,
            artifact_dir=artifact_dir,
            python_executable=selected_python,
            timeout_seconds=timeout_seconds,
        )
        built_artifacts["sdist"] = path
        build_commands.append(command_report)

    install_reports = []
    for artifact_type in selected_artifacts:
        install_reports.append(
            _install_and_check_artifact(
                artifact_type=artifact_type,
                artifact_path=built_artifacts[artifact_type],
                output_dir=output_dir,
                python_executable=selected_python,
                install_dependencies=install_dependencies,
                run_demo=run_demo,
                dashboard_smoke=dashboard_smoke,
                timeout_seconds=timeout_seconds,
            )
        )

    passed = all(
        report.doctor_ok
        and (not dashboard_smoke or report.dashboard_smoke_ok is True)
        for report in install_reports
    )
    return ReleaseInstallSmokeReport(
        project_root=root,
        output_dir=output_dir,
        artifact_dir=artifact_dir,
        python_executable=selected_python,
        install_dependencies=install_dependencies,
        run_demo=run_demo,
        dashboard_smoke=dashboard_smoke,
        artifacts=tuple(install_reports),
        build_commands=tuple(build_commands),
        passed=passed,
        duration_ms=_elapsed_ms(start),
    )


def run_release_install_smoke_matrix(
    *,
    project_root: Path,
    output_dir: Path,
    python_targets: Sequence[str] = DEFAULT_RELEASE_PYTHON_TARGETS,
    artifact_types: Sequence[str] = ARTIFACT_CHOICES,
    install_dependencies: bool = False,
    run_demo: bool = True,
    dashboard_smoke: bool = False,
    timeout_seconds: int = 180,
) -> ReleaseInstallSmokeMatrixReport:
    start = time.perf_counter()
    root = project_root.resolve()
    _validate_project_root(root)
    selected_targets = _normalize_python_targets(python_targets)
    selected_artifacts = _normalize_artifact_types(artifact_types)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    target_reports: list[PythonReleaseSmokeTargetReport] = []
    for target in selected_targets:
        resolved = _resolve_python_executable(target)
        if resolved is None:
            target_reports.append(
                PythonReleaseSmokeTargetReport(
                    target=target,
                    python_executable=None,
                    status="skipped",
                    reason="python_executable_not_found",
                    report=None,
                )
            )
            continue

        try:
            report = run_release_install_smoke(
                project_root=root,
                output_dir=output_dir / _target_slug(target),
                artifact_types=selected_artifacts,
                install_dependencies=install_dependencies,
                run_demo=run_demo,
                dashboard_smoke=dashboard_smoke,
                python_executable=resolved,
                timeout_seconds=timeout_seconds,
            )
        except ReleaseSmokeError as exc:
            target_reports.append(
                PythonReleaseSmokeTargetReport(
                    target=target,
                    python_executable=resolved,
                    status="failed",
                    reason=str(exc),
                    report=None,
                )
            )
            continue

        target_reports.append(
            PythonReleaseSmokeTargetReport(
                target=target,
                python_executable=resolved,
                status="passed" if report.passed else "failed",
                reason=None if report.passed else "release_smoke_failed",
                report=report,
            )
        )

    summary = _matrix_summary(tuple(target_reports))
    passed = summary["failed"] == 0 and summary["passed"] > 0
    return ReleaseInstallSmokeMatrixReport(
        project_root=root,
        output_dir=output_dir,
        python_targets=selected_targets,
        artifact_types=selected_artifacts,
        install_dependencies=install_dependencies,
        run_demo=run_demo,
        dashboard_smoke=dashboard_smoke,
        targets=tuple(target_reports),
        passed=passed,
        duration_ms=_elapsed_ms(start),
    )


def _build_wheel(
    *,
    project_root: Path,
    artifact_dir: Path,
    python_executable: str,
    timeout_seconds: int,
) -> tuple[Path, CommandSmokeReport]:
    before = set(artifact_dir.glob("kyoko-*.whl"))
    command = (
        python_executable,
        "-m",
        "pip",
        "wheel",
        str(project_root),
        "--no-deps",
        "--no-build-isolation",
        "--wheel-dir",
        str(artifact_dir),
    )
    report = _run_command(
        name="build_wheel",
        command=command,
        cwd=project_root,
        timeout_seconds=timeout_seconds,
    )
    after = set(artifact_dir.glob("kyoko-*.whl"))
    created = sorted(after - before, key=lambda path: path.stat().st_mtime)
    if not created:
        created = sorted(after, key=lambda path: path.stat().st_mtime)
    if not created:
        raise ReleaseSmokeError("wheel_not_created")
    return created[-1], report


def _prepare_build_python_environment(
    *,
    python_executable: str,
    output_dir: Path,
    timeout_seconds: int,
) -> tuple[str, tuple[CommandSmokeReport, ...]]:
    build_venv = output_dir / "build-venv"
    create = _run_command(
        name="create_build_venv",
        command=(python_executable, "-m", "venv", str(build_venv)),
        cwd=output_dir,
        timeout_seconds=timeout_seconds,
    )
    python = _venv_python(build_venv)
    install = _run_command(
        name="install_build_backend",
        command=(str(python), "-m", "pip", "install", *BUILD_BACKEND_REQUIREMENTS),
        cwd=output_dir,
        timeout_seconds=timeout_seconds,
    )
    check = _run_command(
        name="check_build_backend",
        command=(str(python), "-c", _build_backend_check_code()),
        cwd=output_dir,
        timeout_seconds=timeout_seconds,
    )
    return str(python), (create, install, check)


def _copy_project_source(project_root: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=False)
    for filename in ("LICENSE", "MANIFEST.in", "README.md", "pyproject.toml", "setup.cfg", "setup.py"):
        source = project_root / filename
        if source.exists():
            shutil.copy2(source, destination / filename)
    for dirname in ("kyoko", "docs", "examples", "scripts", "tests"):
        _copy_source_tree(project_root / dirname, destination / dirname)
    return destination


def _copy_source_tree(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.egg-info"),
    )


def _build_sdist(
    *,
    project_root: Path,
    artifact_dir: Path,
    python_executable: str,
    timeout_seconds: int,
) -> tuple[Path, CommandSmokeReport]:
    command = (
        python_executable,
        "-c",
        (
            "import setuptools.build_meta as build_meta; "
            f"print(build_meta.build_sdist({str(artifact_dir)!r}))"
        ),
    )
    report = _run_command(
        name="build_sdist",
        command=command,
        cwd=project_root,
        timeout_seconds=timeout_seconds,
    )
    output_lines = [line.strip() for line in report.stdout_tail.splitlines() if line.strip()]
    if not output_lines:
        raise ReleaseSmokeError("sdist_build_did_not_report_filename")
    sdist_path = artifact_dir / output_lines[-1]
    if not sdist_path.exists():
        candidates = sorted(artifact_dir.glob("kyoko-*.tar.gz"), key=lambda path: path.stat().st_mtime)
        if not candidates:
            raise ReleaseSmokeError("sdist_not_created")
        sdist_path = candidates[-1]
    return sdist_path, report


def _install_and_check_artifact(
    *,
    artifact_type: str,
    artifact_path: Path,
    output_dir: Path,
    python_executable: str,
    install_dependencies: bool,
    run_demo: bool,
    dashboard_smoke: bool,
    timeout_seconds: int,
) -> ArtifactInstallSmokeReport:
    suffix = uuid.uuid4().hex[:8]
    venv_path = output_dir / "venvs" / f"{artifact_type}-{suffix}"
    run_cwd = output_dir / "run" / f"{artifact_type}-{suffix}"
    run_cwd.mkdir(parents=True, exist_ok=True)
    _create_venv(
        python_executable=python_executable,
        venv_path=venv_path,
        cwd=run_cwd,
        timeout_seconds=timeout_seconds,
    )
    python = _venv_python(venv_path)
    console = _venv_console_script(venv_path, "kyoko")
    commands: list[CommandSmokeReport] = []

    if artifact_type == "sdist":
        build_backend_install = _ensure_install_venv_build_backend(
            python=python,
            run_cwd=run_cwd,
            strict=install_dependencies,
            timeout_seconds=timeout_seconds,
        )
        if build_backend_install is not None:
            commands.append(build_backend_install)

    install_command = [str(python), "-m", "pip", "install"]
    if not install_dependencies:
        install_command.append("--no-deps")
    if artifact_type == "sdist":
        install_command.append("--no-build-isolation")
    install_command.append(str(artifact_path))
    install_report = _run_command(
        name=f"install_{artifact_type}",
        command=tuple(install_command),
        cwd=run_cwd,
        timeout_seconds=timeout_seconds,
        check=artifact_type != "sdist",
    )
    commands.append(install_report)
    if artifact_type == "sdist" and install_report.returncode != 0:
        if install_dependencies:
            raise ReleaseSmokeError(
                f"command_failed:install_sdist:{install_report.returncode}:{install_report.stdout_tail}"
            )
        commands.append(
            _install_sdist_legacy(
                python=python,
                artifact_path=artifact_path,
                run_cwd=run_cwd,
                timeout_seconds=timeout_seconds,
            )
        )

    commands.append(
        _run_command(
            name=f"{artifact_type}_console_help",
            command=(str(console), "--help"),
            cwd=run_cwd,
            timeout_seconds=timeout_seconds,
        )
    )
    commands.append(
        _run_command(
            name=f"{artifact_type}_bundled_assets",
            command=(str(console), "bundled-assets", "--json"),
            cwd=run_cwd,
            timeout_seconds=timeout_seconds,
        )
    )
    metadata = _run_command(
        name=f"{artifact_type}_metadata",
        command=(
            str(python),
            "-c",
            (
                "import json, importlib.metadata as metadata; "
                "import kyoko; "
                "print(json.dumps({'version': metadata.version('kyoko'), "
                "'module_version': kyoko.__version__}, sort_keys=True))"
            ),
        ),
        cwd=run_cwd,
        timeout_seconds=timeout_seconds,
    )
    commands.append(metadata)
    metadata_payload = json.loads(metadata.stdout_tail.splitlines()[-1])
    commands.append(
        _run_command(
            name=f"{artifact_type}_fixture_replay_server_help",
            command=(str(python), "-m", "kyoko.fixture_replay_server", "--help"),
            cwd=run_cwd,
            timeout_seconds=timeout_seconds,
        )
    )
    doctor_command = [
        str(python),
        "-m",
        "kyoko",
        "doctor",
        "--json",
    ]
    if run_demo:
        doctor_command.append("--smoke-demo")
    doctor = _run_command(
        name=f"{artifact_type}_doctor",
        command=tuple(doctor_command),
        cwd=run_cwd,
        timeout_seconds=timeout_seconds,
        tail_max_chars=20000,
    )
    commands.append(doctor)
    doctor_payload = json.loads(doctor.stdout_tail.splitlines()[-1])
    dashboard_smoke_ok = None
    dashboard_smoke_summary = None
    if dashboard_smoke:
        dashboard_output_dir = run_cwd / "doctor-dashboard-smoke"
        dashboard_doctor = _run_command(
            name=f"{artifact_type}_doctor_dashboard_smoke",
            command=(
                str(python),
                "-m",
                "kyoko",
                "doctor",
                "--dashboard-smoke",
                "--smoke-output-dir",
                str(dashboard_output_dir),
                "--dashboard-smoke-screenshot",
                "--dashboard-smoke-install-browser-deps",
                "--json",
            ),
            cwd=run_cwd,
            timeout_seconds=timeout_seconds,
            tail_max_chars=20000,
        )
        commands.append(dashboard_doctor)
        dashboard_payload = json.loads(dashboard_doctor.stdout_tail.splitlines()[-1])
        dashboard_smoke_ok = bool(dashboard_payload.get("ok"))
        dashboard_check = next(
            (
                check
                for check in dashboard_payload.get("checks", [])
                if isinstance(check, dict) and check.get("id") == "dashboard_smoke"
            ),
            {},
        )
        dashboard_detail = (
            dashboard_check.get("detail") if isinstance(dashboard_check, dict) else {}
        )
        dashboard_smoke_summary = {
            "failed": dashboard_payload.get("summary", {}).get("failed"),
            "passed": dashboard_payload.get("summary", {}).get("passed"),
            "warnings": dashboard_payload.get("summary", {}).get("warnings"),
            "browser_backend": (
                dashboard_detail.get("browser_backend")
                if isinstance(dashboard_detail, dict)
                else None
            ),
            "viewport_count": (
                len(dashboard_detail.get("viewports") or [])
                if isinstance(dashboard_detail, dict)
                else 0
            ),
        }
    return ArtifactInstallSmokeReport(
        artifact_type=artifact_type,
        artifact_path=artifact_path,
        venv_path=venv_path,
        run_cwd=run_cwd,
        installed_version=str(metadata_payload["version"]),
        doctor_ok=bool(doctor_payload.get("ok")),
        doctor_summary=doctor_payload.get("summary", {}),
        dashboard_smoke_ok=dashboard_smoke_ok,
        dashboard_smoke_summary=dashboard_smoke_summary,
        commands=tuple(commands),
    )


def _run_command(
    *,
    name: str,
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    check: bool = True,
    tail_max_chars: int = 5000,
) -> CommandSmokeReport:
    start = time.perf_counter()
    result = subprocess.run(
        list(command),
        cwd=cwd,
        env=_clean_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    report = CommandSmokeReport(
        name=name,
        command=command,
        cwd=cwd,
        returncode=result.returncode,
        duration_ms=_elapsed_ms(start),
        stdout_tail=_tail(result.stdout, max_chars=tail_max_chars),
    )
    if check and result.returncode != 0:
        raise ReleaseSmokeError(
            f"command_failed:{name}:{result.returncode}:{report.stdout_tail}"
        )
    return report


def _create_venv(
    *,
    python_executable: str,
    venv_path: Path,
    cwd: Path,
    timeout_seconds: int,
) -> None:
    _run_command(
        name="create_venv",
        command=(python_executable, "-m", "venv", str(venv_path)),
        cwd=cwd,
        timeout_seconds=timeout_seconds,
    )


def _ensure_install_venv_build_backend(
    *,
    python: Path,
    run_cwd: Path,
    strict: bool = True,
    timeout_seconds: int,
) -> Optional[CommandSmokeReport]:
    check = _run_command(
        name="check_sdist_build_backend",
        command=(str(python), "-c", _build_backend_check_code()),
        cwd=run_cwd,
        timeout_seconds=timeout_seconds,
        check=False,
    )
    if check.returncode == 0:
        return None
    return _run_command(
        name="install_sdist_build_backend",
        command=(str(python), "-m", "pip", "install", *BUILD_BACKEND_REQUIREMENTS),
        cwd=run_cwd,
        timeout_seconds=timeout_seconds,
        check=strict,
    )


def _install_sdist_legacy(
    *,
    python: Path,
    artifact_path: Path,
    run_cwd: Path,
    timeout_seconds: int,
) -> CommandSmokeReport:
    extract_dir = run_cwd / "sdist-extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(artifact_path, "r:gz") as archive:
        archive.extractall(extract_dir)
    candidates = [path for path in extract_dir.iterdir() if path.is_dir()]
    if not candidates:
        raise ReleaseSmokeError("sdist_extract_missing_project_dir")
    source_dir = sorted(candidates)[0]
    setup_py = source_dir / "setup.py"
    if not setup_py.exists():
        raise ReleaseSmokeError("sdist_legacy_install_requires_setup_py")
    record_path = run_cwd / "sdist-install-record.txt"
    return _run_command(
        name="install_sdist_legacy_setup_py",
        command=(
            str(python),
            str(setup_py),
            "install",
            "--single-version-externally-managed",
            "--record",
            str(record_path),
        ),
        cwd=source_dir,
        timeout_seconds=timeout_seconds,
    )


def _normalize_artifact_types(artifact_types: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for artifact_type in artifact_types:
        if artifact_type not in ARTIFACT_CHOICES:
            raise ReleaseSmokeError(f"unsupported_artifact_type:{artifact_type}")
        if artifact_type not in selected:
            selected.append(artifact_type)
    if not selected:
        raise ReleaseSmokeError("artifact_type_required")
    return tuple(selected)


def _normalize_python_targets(python_targets: Sequence[str]) -> tuple[str, ...]:
    selected: list[str] = []
    for target in python_targets:
        normalized = str(target).strip()
        if not normalized:
            raise ReleaseSmokeError("python_target_required")
        if normalized not in selected:
            selected.append(normalized)
    if not selected:
        raise ReleaseSmokeError("python_target_required")
    return tuple(selected)


def _resolve_python_executable(target: str) -> Optional[str]:
    if target in {"current", "sys.executable"}:
        return sys.executable
    command = f"python{target}" if target[0].isdigit() else target
    expanded = Path(command).expanduser()
    if any(separator in command for separator in ("/", "\\")):
        return str(expanded) if expanded.exists() else None
    resolved = shutil.which(command)
    return resolved


def python_build_backend_reason(
    *,
    python_executable: str,
    timeout_seconds: int = 30,
) -> Optional[str]:
    try:
        result = subprocess.run(
            [
                python_executable,
                "-c",
                _build_backend_check_code(),
            ],
            env=_clean_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return "python_executable_not_found"
    except subprocess.TimeoutExpired:
        return "python_build_backend_check_timeout"
    if result.returncode != 0:
        missing = result.stdout.splitlines()[0].strip() if result.stdout else ""
        if missing not in BUILD_BACKEND_CHECK_MODULES:
            missing = ",".join(BUILD_BACKEND_CHECK_MODULES)
        return f"python_build_backend_unavailable:{missing}"
    return None


def _build_backend_check_code() -> str:
    modules = ", ".join(repr(module) for module in BUILD_BACKEND_CHECK_MODULES)
    return (
        "import importlib, sys\n"
        f"for name in ({modules}):\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception:\n"
        "        print(name)\n"
        "        raise SystemExit(1)\n"
    )


def _target_slug(target: str) -> str:
    chars = [char if char.isalnum() else "-" for char in target]
    slug = "".join(chars).strip("-").lower()
    return slug or "python"


def _matrix_summary(targets: Sequence[PythonReleaseSmokeTargetReport]) -> dict[str, int]:
    summary = {
        "total": len(targets),
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "available": 0,
    }
    for target in targets:
        if target.status in {"passed", "failed", "skipped"}:
            summary[target.status] += 1
        if target.status != "skipped":
            summary["available"] += 1
    return summary


def _validate_project_root(project_root: Path) -> None:
    required = ("pyproject.toml", "setup.cfg", "kyoko")
    missing = [name for name in required if not (project_root / name).exists()]
    if missing:
        raise ReleaseSmokeError(f"project_root_missing:{','.join(missing)}")


def _venv_python(venv_path: Path) -> Path:
    if sys.platform == "win32":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _venv_console_script(venv_path: Path, name: str) -> Path:
    if sys.platform == "win32":
        return venv_path / "Scripts" / f"{name}.exe"
    return venv_path / "bin" / name


def _clean_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _tail(output: str, *, max_chars: int = 5000) -> str:
    return output[-max_chars:]


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
