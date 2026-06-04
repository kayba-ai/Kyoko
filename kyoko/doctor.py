from __future__ import annotations

import importlib
import importlib.metadata
import configparser
import json
import shlex
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

from .ace_bridge import (
    ACE_NATIVE_RUN_REPORT_FILENAME,
    AceBridgeError,
    check_ace_compatibility,
    prepare_native_ace_command,
)
from .ace_smoke import run_legacy_ace_offline_adapter_smoke
from .analyze import list_operator_runs
from .bundled_assets import (
    AssetError,
    bundled_asset_exists,
    bundled_asset_path,
    load_bundled_json,
)
from .demo import DemoError, run_demo_setup
from .evals import EvalError, list_eval_runs
from .improve_smoke import ImproveSmokeError, run_generated_improve_smoke
from .integration_smoke import (
    IntegrationSmokeError,
    run_replay_server_smoke,
    run_source_adapter_smoke,
)
from .judge_smoke import JudgeSmokeError, run_judge_smoke
from .operator_smoke import OperatorSmokeError, run_operator_smoke_matrix
from .otlp_smoke import OtlpSmokeError, run_opentelemetry_sdk_smoke
from .proposals import list_learning_proposals
from .release_smoke import python_build_backend_reason
from .replay_templates import ReplayTemplateError, write_replay_server_template
from .source_templates import SourceTemplateError, write_source_adapter_template
from .storage import StorageError, ingest_source_fixture, initialize_database
from . import __version__


REQUIRED_ASSETS = (
    "source-events/hermes-news-research-minimal.json",
    "learning-proposals/hermes-one-shot-proposal.json",
    "learning-proposals/invalid-hallucinated-span.json",
    "learning-proposals/openclaw-local-operator-proposal.json",
    "learning-proposals/valid-context-proposal.json",
    "learning-proposals/valid-harness-generated-file-proposal.json",
    "learning-proposals/valid-harness-proposal.json",
    "replay-results/researcher-fetch-timeout-success.json",
    "schemas/learning-proposal.schema.json",
)
OPTIONAL_OPERATOR_COMMANDS = ("codex", "claude", "hermes", "openclaw")
RELEASE_PYTHON_TARGETS = ("3.12", "3.13")
MCP_CLIENT_COMMANDS = ("codex", "claude")
LOCAL_SAFE_SMOKE_CHECK_IDS = (
    "demo_smoke",
    "operator_smoke_prepare",
    "judge_smoke_prepare",
    "ace_native_prepare",
    "integration_smoke",
    "improve_smoke",
    "mcp_install_smoke",
)
EXTERNAL_EVIDENCE_CHECK_IDS = (
    "operator_commands",
    "release_python_targets",
    "mcp_clients",
)
EXTERNAL_EVIDENCE_COMMAND_PREFIXES = (
    "operator_smoke_live",
    "judge_smoke_live",
    "release_smoke",
    "mcp_install_smoke",
)
DEFAULT_SMOKE_EVIDENCE_DIR = Path(".kyoko/smoke")


class DoctorError(Exception):
    """Raised when the doctor command cannot run."""


@dataclass(frozen=True)
class DoctorCheck:
    id: str
    status: str
    message: str
    detail: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    checks: tuple[DoctorCheck, ...]
    suggested_commands: tuple[dict[str, Any], ...] = ()
    retained_external_evidence: tuple[dict[str, Any], ...] = ()

    def to_json(self) -> dict[str, Any]:
        summary = _doctor_check_summary(self.checks)
        return {
            "ok": self.ok,
            "checks": [check.to_json() for check in self.checks],
            "summary": summary,
            "readiness": _doctor_readiness_summary(
                checks=self.checks,
                suggested_commands=self.suggested_commands,
                retained_external_evidence=self.retained_external_evidence,
            ),
            "suggested_commands": list(self.suggested_commands),
            "retained_external_evidence": list(self.retained_external_evidence),
        }


def _doctor_check_summary(checks: tuple[DoctorCheck, ...]) -> dict[str, int]:
    return {
        "passed": len([check for check in checks if check.status == "pass"]),
        "warnings": len([check for check in checks if check.status == "warn"]),
        "failed": len([check for check in checks if check.status == "fail"]),
    }


def _doctor_readiness_summary(
    *,
    checks: tuple[DoctorCheck, ...],
    suggested_commands: tuple[dict[str, Any], ...],
    retained_external_evidence: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    check_ids = {check.id for check in checks}
    blocking_checks = [check.id for check in checks if check.status == "fail"]
    warning_checks = [check.id for check in checks if check.status == "warn"]
    pending_safe_smoke_checks = [
        check_id for check_id in LOCAL_SAFE_SMOKE_CHECK_IDS if check_id not in check_ids
    ]
    safe_smokes_complete = not pending_safe_smoke_checks
    external_evidence_warnings = [
        check.id
        for check in checks
        if check.id in EXTERNAL_EVIDENCE_CHECK_IDS and check.status == "warn"
    ]
    satisfied_external_evidence_commands = [
        intent
        for evidence in retained_external_evidence
        if evidence.get("status") == "satisfied"
        and isinstance((intent := evidence.get("intent")), str)
    ]
    satisfied_external_evidence = set(satisfied_external_evidence_commands)
    pending_external_evidence_commands = [
        intent
        for command in suggested_commands
        if isinstance((intent := command.get("intent")), str)
        and intent.startswith(EXTERNAL_EVIDENCE_COMMAND_PREFIXES)
        and intent not in satisfied_external_evidence
    ]
    local_runtime_ready = not blocking_checks
    return {
        "local_runtime_ready": local_runtime_ready,
        "local_v0_ready": local_runtime_ready and safe_smokes_complete,
        "safe_smokes_complete": safe_smokes_complete,
        "pending_safe_smoke_checks": pending_safe_smoke_checks,
        "blocking_checks": blocking_checks,
        "warning_checks": warning_checks,
        "external_evidence_warnings": external_evidence_warnings,
        "satisfied_external_evidence_commands": satisfied_external_evidence_commands,
        "pending_external_evidence_commands": pending_external_evidence_commands,
    }


def run_doctor(
    *,
    db_path: Optional[Path] = None,
    smoke_demo: bool = False,
    operator_smoke_prepare: bool = False,
    judge_smoke_prepare: bool = False,
    ace_native_prepare: bool = False,
    integration_smoke: bool = False,
    improve_smoke: bool = False,
    opentelemetry_smoke: bool = False,
    opentelemetry_python_executable: Optional[Path] = None,
    ace_native_smoke: bool = False,
    dashboard_smoke: bool = False,
    dashboard_smoke_screenshot: bool = False,
    dashboard_smoke_install_browser_deps: bool = False,
    dashboard_smoke_timeout_seconds: int = 30,
    safe_smokes: bool = False,
    smoke_output_dir: Optional[Path] = None,
    smoke_evidence_dir: Optional[Path] = None,
    ace_path: Optional[Path] = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> DoctorReport:
    smoke_demo = smoke_demo or safe_smokes
    operator_smoke_prepare = operator_smoke_prepare or safe_smokes
    judge_smoke_prepare = judge_smoke_prepare or safe_smokes
    ace_native_prepare = ace_native_prepare or safe_smokes
    integration_smoke = integration_smoke or safe_smokes
    improve_smoke = improve_smoke or safe_smokes
    mcp_install_smoke = safe_smokes
    checks = [
        _check_python_version(),
        _check_sqlite(db_path),
        _check_jsonschema(),
        _check_assets(),
        _check_fixture_replay_module(),
        _check_fixture_replay_server_module(),
        _check_package_metadata(),
        _check_operator_commands(),
        _check_release_python_targets(),
        _check_mcp_clients(),
        _check_port(host=host, port=port),
    ]
    if ace_path is not None:
        checks.append(_check_ace(db_path=db_path, ace_path=ace_path))
    if smoke_demo:
        checks.append(_check_demo_smoke(output_dir=_smoke_output_dir(smoke_output_dir, "demo")))
    if operator_smoke_prepare:
        checks.append(
            _check_operator_smoke_prepare(
                output_dir=_smoke_output_dir(smoke_output_dir, "operator-smoke-prepare"),
            )
        )
    if judge_smoke_prepare:
        checks.append(
            _check_judge_smoke_prepare(
                output_dir=_smoke_output_dir(smoke_output_dir, "judge-smoke-prepare"),
            )
        )
    if ace_native_prepare:
        checks.append(
            _check_ace_native_prepare(
                output_dir=_smoke_output_dir(smoke_output_dir, "ace-native-prepare"),
            )
        )
    if integration_smoke:
        checks.append(
            _check_integration_smoke(
                output_dir=_smoke_output_dir(smoke_output_dir, "integration-smoke"),
            )
        )
    if improve_smoke:
        checks.append(
            _check_improve_smoke(
                output_dir=_smoke_output_dir(smoke_output_dir, "improve-smoke"),
            )
        )
    if opentelemetry_smoke:
        checks.append(
            _check_opentelemetry_smoke(
                output_dir=_smoke_output_dir(smoke_output_dir, "opentelemetry-smoke"),
                python_executable=opentelemetry_python_executable,
            )
        )
    if ace_native_smoke:
        checks.append(
            _check_ace_native_smoke(
                output_dir=_smoke_output_dir(smoke_output_dir, "ace-native-smoke"),
            )
        )
    if dashboard_smoke:
        checks.append(
            _check_dashboard_smoke(
                output_dir=_smoke_output_dir(smoke_output_dir, "dashboard-smoke"),
                screenshot=dashboard_smoke_screenshot,
                install_browser_deps=dashboard_smoke_install_browser_deps,
                timeout_seconds=dashboard_smoke_timeout_seconds,
            )
        )
    if mcp_install_smoke:
        checks.append(
            _check_mcp_install_smoke(
                output_dir=_smoke_output_dir(smoke_output_dir, "mcp-install-smoke"),
            )
        )
    retained_external_evidence = _retained_external_evidence(
        smoke_evidence_dir=smoke_evidence_dir,
        checks=checks,
    )

    return DoctorReport(
        ok=not any(check.status == "fail" for check in checks),
        checks=tuple(checks),
        suggested_commands=tuple(
            _doctor_suggested_commands(
                checks=checks,
                retained_external_evidence=retained_external_evidence,
                smoke_demo=smoke_demo,
                operator_smoke_prepare=operator_smoke_prepare,
                judge_smoke_prepare=judge_smoke_prepare,
                ace_native_prepare=ace_native_prepare,
                integration_smoke=integration_smoke,
                improve_smoke=improve_smoke,
                opentelemetry_smoke=opentelemetry_smoke,
                ace_native_smoke=ace_native_smoke,
                dashboard_smoke=dashboard_smoke,
                mcp_install_smoke=mcp_install_smoke,
                safe_smokes=safe_smokes,
            )
        ),
        retained_external_evidence=retained_external_evidence,
    )


def _doctor_suggested_commands(
    *,
    checks: list[DoctorCheck],
    retained_external_evidence: tuple[dict[str, Any], ...],
    smoke_demo: bool,
    operator_smoke_prepare: bool,
    judge_smoke_prepare: bool,
    ace_native_prepare: bool,
    integration_smoke: bool,
    improve_smoke: bool,
    opentelemetry_smoke: bool,
    ace_native_smoke: bool,
    dashboard_smoke: bool,
    mcp_install_smoke: bool,
    safe_smokes: bool,
) -> list[dict[str, Any]]:
    by_id = {check.id: check for check in checks}
    commands: list[dict[str, Any]] = []
    satisfied_external_evidence = {
        str(evidence["intent"])
        for evidence in retained_external_evidence
        if evidence.get("status") == "satisfied" and isinstance(evidence.get("intent"), str)
    }

    if not safe_smokes and not (
        smoke_demo
        and operator_smoke_prepare
        and judge_smoke_prepare
        and ace_native_prepare
        and integration_smoke
        and improve_smoke
        and mcp_install_smoke
    ):
        commands.append(
            _doctor_command(
                "doctor_safe_smokes",
                "Run all safe no-live-model doctor smokes",
                ["doctor", "--safe-smokes", "--json"],
                mutating=False,
            )
        )
    if not smoke_demo:
        commands.append(
            _doctor_command(
                "doctor_smoke_demo",
                "Run bundled demo smoke",
                ["doctor", "--smoke-demo", "--json"],
                mutating=False,
            )
        )
    if not operator_smoke_prepare:
        commands.append(
            _doctor_command(
                "doctor_operator_smoke_prepare",
                "Prepare all operator handoffs",
                ["doctor", "--operator-smoke-prepare", "--json"],
                mutating=False,
            )
        )
    if not judge_smoke_prepare:
        commands.append(
            _doctor_command(
                "doctor_judge_smoke_prepare",
                "Prepare judge-command handoff",
                ["doctor", "--judge-smoke-prepare", "--json"],
                mutating=False,
            )
        )
    if not ace_native_prepare:
        commands.append(
            _doctor_command(
                "doctor_ace_native_prepare",
                "Prepare native ACE command handoff",
                ["doctor", "--ace-native-prepare", "--json"],
                mutating=False,
            )
        )
    if not integration_smoke:
        commands.append(
            _doctor_command(
                "doctor_integration_smoke",
                "Run generated integration smoke",
                ["doctor", "--integration-smoke", "--json"],
                mutating=False,
            )
        )
    if not improve_smoke:
        commands.append(
            _doctor_command(
                "doctor_improve_smoke",
                "Run generated improve smoke",
                ["doctor", "--improve-smoke", "--json"],
                mutating=False,
            )
        )
    if not opentelemetry_smoke:
        commands.append(
            _doctor_command(
                "doctor_opentelemetry_smoke",
                "Run installed OpenTelemetry SDK smoke",
                ["doctor", "--opentelemetry-smoke", "--json"],
                mutating=False,
                requires=[
                    "Python environment with opentelemetry-sdk installed",
                    "no live model provider is invoked",
                ],
            )
        )
    if not ace_native_smoke:
        commands.append(
            _doctor_command(
                "doctor_ace_native_smoke",
                "Run installed ACE Skillbook smoke",
                ["doctor", "--ace-native-smoke", "--json"],
                mutating=False,
                requires=[
                    "installed ace-framework package exposing the Skillbook v2 API",
                    "no live model provider is invoked",
                ],
            )
        )
    if not dashboard_smoke:
        commands.append(
            _doctor_command(
                "doctor_dashboard_smoke",
                "Run dashboard browser smoke",
                ["doctor", "--dashboard-smoke", "--json"],
                mutating=False,
                requires=[
                    "Python Playwright, or Node.js with @playwright/test already installed",
                    "use --dashboard-smoke-install-browser-deps to install isolated browser test dependencies under --smoke-output-dir",
                    "no live model provider is invoked",
                ],
            )
        )

    operator_check = by_id.get("operator_commands")
    commands.extend(_operator_live_smoke_suggested_commands(operator_check))
    commands.append(
        _doctor_command(
            "judge_smoke_live_provider_backed",
            "Run retained provider-backed judge smoke",
            [
                "judge-smoke",
                "--command",
                "python /path/to/provider-judge.py",
                "--provider-backed",
                "--output-dir",
                ".kyoko/smoke/judge-provider-live",
                "--json",
            ],
            mutating=True,
            requires=[
                "user-supplied provider/model-backed judge command",
                "invokes the configured judge provider/model",
                "writes smoke artifacts under .kyoko/smoke/judge-provider-live",
            ],
        )
    )

    release_check = by_id.get("release_python_targets")
    if release_check is not None and release_check.status != "pass":
        commands.append(
            _doctor_command(
                "release_smoke_matrix",
                "Run release install smoke matrix",
                ["release-smoke", "--python-matrix", "--artifact", "both", "--json"],
                mutating=False,
                requires=[
                    "Python matrix interpreters; build backends are bootstrapped in isolated venvs when needed"
                ],
            )
        )
        commands.extend(_release_python_target_suggested_commands(release_check))

    mcp_check = by_id.get("mcp_clients")
    if mcp_check is not None and not mcp_install_smoke:
        commands.append(
            _doctor_command(
                "mcp_install_smoke_matrix",
                "Run isolated MCP client install smoke",
                ["mcp", "install-smoke", "--all-targets", "--json"],
                mutating=False,
                requires=["installed Codex or Claude CLI for non-skipped targets"],
            )
        )

    return [
        command
        for command in commands
        if command.get("intent") not in satisfied_external_evidence
    ]


def _retained_external_evidence(
    *,
    smoke_evidence_dir: Optional[Path],
    checks: list[DoctorCheck],
) -> tuple[dict[str, Any], ...]:
    if smoke_evidence_dir is None or not smoke_evidence_dir.exists():
        return ()
    by_id = {check.id: check for check in checks}
    available_operators = _available_operator_commands(by_id.get("operator_commands"))
    evidence: list[dict[str, Any]] = []
    operator_live = _retained_operator_live_evidence(
        smoke_evidence_dir,
        available_operators=available_operators,
    )
    if operator_live is not None:
        evidence.append(operator_live)
    operator_failure = _retained_operator_failure_evidence(
        smoke_evidence_dir,
        available_operators=available_operators,
    )
    if operator_failure is not None:
        evidence.append(operator_failure)
    judge_live = _retained_judge_provider_evidence(smoke_evidence_dir)
    if judge_live is not None:
        evidence.append(judge_live)
    ace_live = _retained_ace_native_provider_evidence(smoke_evidence_dir)
    if ace_live is not None:
        evidence.append(ace_live)
    return tuple(evidence)


def _available_operator_commands(check: Optional[DoctorCheck]) -> tuple[str, ...]:
    if check is None or not isinstance(check.detail, dict):
        return ()
    commands = check.detail.get("commands")
    if not isinstance(commands, dict):
        return ()
    return tuple(sorted(str(command) for command, path in commands.items() if path))


def _retained_operator_live_evidence(
    smoke_evidence_dir: Path,
    *,
    available_operators: tuple[str, ...],
) -> Optional[dict[str, Any]]:
    if not available_operators:
        return None
    for candidate in _candidate_smoke_dirs(smoke_evidence_dir, "operator-live"):
        db_path = candidate / "smoke.db"
        runs = _safe_operator_runs(db_path)
        proposals = {proposal.get("id") for proposal in _safe_learning_proposals(db_path)}
        matched: dict[str, dict[str, Any]] = {}
        for operator in available_operators:
            run = _matching_operator_success_run(
                runs,
                operator=operator,
                proposal_ids=proposals,
                artifact_base=candidate,
            )
            if run is None:
                break
            matched[operator] = run
        if len(matched) == len(available_operators):
            return _retained_evidence(
                "operator_smoke_live_installed_presets",
                candidate,
                {
                    "db_path": str(db_path),
                    "operators": list(available_operators),
                    "operator_run_ids": {
                        operator: str(run.get("id")) for operator, run in matched.items()
                    },
                    "proposal_ids": {
                        operator: str(run.get("proposal_id")) for operator, run in matched.items()
                    },
                },
            )
    return None


def _retained_operator_failure_evidence(
    smoke_evidence_dir: Path,
    *,
    available_operators: tuple[str, ...],
) -> Optional[dict[str, Any]]:
    if not available_operators:
        return None
    for candidate in _candidate_smoke_dirs(smoke_evidence_dir, "operator-failure-live"):
        db_path = candidate / "smoke.db"
        runs = _safe_operator_runs(db_path)
        matched: dict[str, dict[str, Any]] = {}
        for operator in available_operators:
            run = _matching_operator_failure_run(
                runs,
                operator=operator,
                artifact_base=candidate,
            )
            if run is None:
                break
            matched[operator] = run
        if len(matched) == len(available_operators):
            return _retained_evidence(
                "operator_smoke_live_expected_failure_installed_presets",
                candidate,
                {
                    "db_path": str(db_path),
                    "operators": list(available_operators),
                    "operator_run_ids": {
                        operator: str(run.get("id")) for operator, run in matched.items()
                    },
                    "failure_kinds": {
                        operator: str(run.get("failure_kind")) for operator, run in matched.items()
                    },
                },
            )
    return None


def _retained_judge_provider_evidence(smoke_evidence_dir: Path) -> Optional[dict[str, Any]]:
    for candidate in _candidate_smoke_dirs(smoke_evidence_dir, "judge-provider-live"):
        handoff_path = candidate / "judge-command.handoff.json"
        result_path = candidate / "judge-result.json"
        request_path = candidate / "judge-request.json"
        raw_output_path = candidate / "judge-command-output.txt"
        handoff = _safe_json_object(handoff_path)
        result = _safe_json_object(result_path)
        if not all(path.exists() for path in (handoff_path, result_path, request_path, raw_output_path)):
            continue
        if handoff.get("prepare_only") is not False:
            continue
        if handoff.get("provider_backed") is not True:
            continue
        if handoff.get("external_model_invoked") is not True:
            continue
        judgment = result.get("judgment") if isinstance(result.get("judgment"), dict) else {}
        if str(judgment.get("verdict", "")).lower() not in {"pass", "passed", "accept", "accepted"}:
            continue
        db_path = _handoff_db_path(handoff, candidate)
        eval_runs = _safe_eval_runs(db_path)
        passed_judge_run = next(
            (
                run
                for run in eval_runs
                if run.get("status") == "passed"
                and isinstance(run.get("result"), dict)
                and run["result"].get("eval_type") == "judge"
            ),
            None,
        )
        if passed_judge_run is None:
            continue
        return _retained_evidence(
            "judge_smoke_live_provider_backed",
            candidate,
            {
                "db_path": str(db_path),
                "eval_run_id": str(passed_judge_run.get("id")),
                "eval_spec_id": str(passed_judge_run.get("eval_spec_id")),
                "judge": str(judgment.get("judge")),
                "score": judgment.get("score"),
            },
        )
    return None


def _retained_ace_native_provider_evidence(smoke_evidence_dir: Path) -> Optional[dict[str, Any]]:
    candidates = [
        *_candidate_smoke_dirs(smoke_evidence_dir, "ace-provider-live"),
        *_candidate_smoke_dirs(smoke_evidence_dir, "ace-native-provider-live"),
    ]
    unique_candidates = {
        candidate.resolve(): candidate for candidate in candidates
    }
    for candidate in sorted(
        unique_candidates.values(),
        key=lambda path: (_safe_mtime(path), str(path)),
        reverse=True,
    ):
        report_path = candidate / ACE_NATIVE_RUN_REPORT_FILENAME
        report = _safe_json_object(report_path)
        diff = report.get("diff") if isinstance(report.get("diff"), dict) else {}
        proposal_ids = diff.get("proposal_ids") if isinstance(diff.get("proposal_ids"), list) else []
        proposal_ids = [str(proposal_id) for proposal_id in proposal_ids if proposal_id]
        if not proposal_ids:
            continue
        if report.get("prepare_only") is not False:
            continue
        if report.get("passed") is not True or report.get("returncode") != 0:
            continue
        if report.get("external_command_invoked") is not True:
            continue
        if report.get("provider_backed") is not True:
            continue
        if report.get("external_model_invoked") is not True:
            continue
        if report.get("canonical_mutation") is not False:
            continue
        if diff.get("persisted") is not True:
            continue

        db_path = _existing_path_from_ref(report.get("db_path"), candidate)
        if db_path is None:
            continue
        required_artifacts = (
            report_path,
            _existing_path_from_ref(report.get("before_path"), candidate),
            _existing_path_from_ref(report.get("after_path"), candidate),
            _existing_path_from_ref(report.get("handoff_path"), candidate),
            _existing_path_from_ref(report.get("stdout_path"), candidate),
            _existing_path_from_ref(report.get("stderr_path"), candidate),
            _existing_path_from_ref(report.get("proposal_output_dir"), candidate),
        )
        if any(path is None or not path.exists() for path in required_artifacts):
            continue
        persisted_proposals = {
            str(proposal.get("id")) for proposal in _safe_learning_proposals(db_path)
        }
        if not set(proposal_ids).issubset(persisted_proposals):
            continue
        return _retained_evidence(
            "ace_native_run_provider_backed",
            candidate,
            {
                "db_path": str(db_path),
                "report_path": str(report_path),
                "proposal_ids": proposal_ids,
                "stdout_path": str(_existing_path_from_ref(report.get("stdout_path"), candidate)),
                "stderr_path": str(_existing_path_from_ref(report.get("stderr_path"), candidate)),
            },
        )
    return None


def _matching_operator_success_run(
    runs: list[dict[str, Any]],
    *,
    operator: str,
    proposal_ids: set[Any],
    artifact_base: Path,
) -> Optional[dict[str, Any]]:
    for run in runs:
        proposal_id = run.get("proposal_id")
        if _operator_run_kind(run) != operator:
            continue
        if run.get("status") != "succeeded":
            continue
        if not proposal_id or proposal_id not in proposal_ids:
            continue
        if not _path_ref_exists(run.get("raw_output_ref"), artifact_base):
            continue
        return run
    return None


def _matching_operator_failure_run(
    runs: list[dict[str, Any]],
    *,
    operator: str,
    artifact_base: Path,
) -> Optional[dict[str, Any]]:
    for run in runs:
        if _operator_run_kind(run) != operator:
            continue
        if run.get("status") != "failed":
            continue
        if run.get("failure_kind") != "invalid_output":
            continue
        if not _path_ref_exists(run.get("raw_output_ref"), artifact_base):
            continue
        return run
    return None


def _operator_run_kind(run: dict[str, Any]) -> Optional[str]:
    for key in ("operator_kind", "adapter_id", "operator_label"):
        value = run.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _candidate_smoke_dirs(root: Path, prefix: str) -> tuple[Path, ...]:
    candidates: list[Path] = []
    if root.is_dir() and (root.name == prefix or root.name.startswith(f"{prefix}-")):
        candidates.append(root)
    if root.is_dir():
        try:
            children = list(root.iterdir())
        except OSError:
            children = []
        for child in children:
            if child.is_dir() and (child.name == prefix or child.name.startswith(f"{prefix}-")):
                candidates.append(child)
    unique = {candidate.resolve(): candidate for candidate in candidates}
    return tuple(
        sorted(
            unique.values(),
            key=lambda path: (_safe_mtime(path), str(path)),
            reverse=True,
        )
    )


def _safe_operator_runs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        return list_operator_runs(db_path)
    except Exception:
        return []


def _safe_learning_proposals(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        return list_learning_proposals(db_path)
    except Exception:
        return []


def _safe_eval_runs(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    try:
        return list_eval_runs(db_path)
    except Exception:
        return []


def _safe_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _handoff_db_path(handoff: dict[str, Any], artifact_base: Path) -> Path:
    raw_path = handoff.get("db_path")
    if isinstance(raw_path, str) and raw_path:
        db_path = Path(raw_path)
        if db_path.is_absolute() or db_path.exists():
            return db_path
        candidate = artifact_base / db_path
        if candidate.exists():
            return candidate
    return artifact_base / "smoke.db"


def _path_ref_exists(path_ref: Any, artifact_base: Path) -> bool:
    if not isinstance(path_ref, str) or not path_ref:
        return False
    path = Path(path_ref)
    if path.exists():
        return True
    if not path.is_absolute() and (artifact_base / path).exists():
        return True
    return False


def _existing_path_from_ref(path_ref: Any, artifact_base: Path) -> Optional[Path]:
    if not isinstance(path_ref, str) or not path_ref:
        return None
    path = Path(path_ref)
    if path.exists():
        return path
    if not path.is_absolute():
        candidate = artifact_base / path
        if candidate.exists():
            return candidate
    return None


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _retained_evidence(intent: str, path: Path, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "intent": intent,
        "status": "satisfied",
        "path": str(path),
        "detail": detail,
    }


def _operator_live_smoke_suggested_commands(
    check: Optional[DoctorCheck],
) -> list[dict[str, Any]]:
    if check is None:
        return []
    commands = check.detail.get("commands") if isinstance(check.detail, dict) else None
    if not isinstance(commands, dict):
        return []
    available = sorted(str(command) for command, path in commands.items() if path)
    if not available:
        return []
    return [
        _doctor_command(
            "operator_smoke_live_installed_presets",
            "Run live operator proposal smoke for installed presets",
            [
                "operator-smoke",
                "--all-presets",
                "--output-dir",
                ".kyoko/smoke/operator-live",
                "--json",
            ],
            mutating=True,
            requires=[
                f"installed/authenticated operator CLI: {', '.join(available)}",
                "invokes live operator model/subscription",
                "writes smoke artifacts under .kyoko/smoke/operator-live",
            ],
        ),
        _doctor_command(
            "operator_smoke_live_expected_failure_installed_presets",
            "Run live operator expected-failure smoke for installed presets",
            [
                "operator-smoke",
                "--all-presets",
                "--expect-failure",
                "--output-dir",
                ".kyoko/smoke/operator-failure-live",
                "--json",
            ],
            mutating=True,
            requires=[
                f"installed/authenticated operator CLI: {', '.join(available)}",
                "invokes live operator model/subscription",
                "writes smoke artifacts under .kyoko/smoke/operator-failure-live",
                "passes only when the expected failure kind is captured",
            ],
        ),
    ]


def _release_python_target_suggested_commands(check: DoctorCheck) -> list[dict[str, Any]]:
    detail = check.detail if isinstance(check.detail, dict) else {}
    commands: list[dict[str, Any]] = []

    ready_targets = detail.get("ready_targets")
    if isinstance(ready_targets, list) and ready_targets:
        args = ["python3", "-m", "kyoko", "release-smoke"]
        for target in ready_targets:
            args.extend(["--python-target", str(target)])
        args.extend(["--artifact", "both", "--json"])
        commands.append(
            _suggested_command(
                "release_smoke_ready_targets",
                "Run release install smoke for available Python targets",
                args,
                mutating=False,
                requires=[
                    "available Python interpreters; build backends are bootstrapped in isolated venvs when needed"
                ],
            )
        )

    return commands


def _doctor_command(
    intent: str,
    label: str,
    args: list[str],
    *,
    mutating: bool,
    requires: Optional[list[str]] = None,
) -> dict[str, Any]:
    return _suggested_command(
        intent,
        label,
        ["python3", "-m", "kyoko", *args],
        mutating=mutating,
        requires=requires,
    )


def _suggested_command(
    intent: str,
    label: str,
    cli_args: list[str],
    *,
    mutating: bool,
    requires: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "label": label,
        "cli_args": cli_args,
        "mutating": mutating,
        "requires": requires or [],
    }


def _intent_slug(value: str) -> str:
    chars = [char.lower() if char.isalnum() else "_" for char in value]
    slug = "".join(chars).strip("_")
    return slug or "target"


def _smoke_output_dir(root: Optional[Path], name: str) -> Optional[Path]:
    if root is None:
        return None
    return root / name


def _check_python_version() -> DoctorCheck:
    version = sys.version_info
    passed = version >= (3, 12)
    return DoctorCheck(
        id="python",
        status="pass" if passed else "fail",
        message=f"Python {version.major}.{version.minor}.{version.micro}",
        detail={"required": ">=3.12", "executable": sys.executable},
    )


def _check_sqlite(db_path: Optional[Path]) -> DoctorCheck:
    try:
        if db_path is not None:
            initialize_database(db_path)
            detail = {"db_path": str(db_path)}
        else:
            with TemporaryDirectory() as tmpdir:
                temp_db = Path(tmpdir) / "doctor.db"
                initialize_database(temp_db)
                detail = {"db_path": str(temp_db), "temporary": True}
    except StorageError as exc:
        return DoctorCheck(
            id="sqlite",
            status="fail",
            message=f"SQLite initialization failed: {exc}",
            detail={},
        )
    return DoctorCheck(
        id="sqlite",
        status="pass",
        message="SQLite database initialization works.",
        detail=detail,
    )


def _check_jsonschema() -> DoctorCheck:
    try:
        importlib.import_module("jsonschema")
    except ImportError:
        return DoctorCheck(
            id="jsonschema",
            status="warn",
            message="jsonschema is not installed; schema validation will be skipped unless required.",
            detail={"package": "jsonschema>=4.0"},
        )
    return DoctorCheck(
        id="jsonschema",
        status="pass",
        message="jsonschema is importable.",
        detail={"package": "jsonschema"},
    )


def _check_assets() -> DoctorCheck:
    missing = [path for path in REQUIRED_ASSETS if not bundled_asset_exists(path)]
    invalid: list[str] = []
    for path in REQUIRED_ASSETS:
        if path in missing:
            continue
        try:
            load_bundled_json(path)
        except AssetError as exc:
            invalid.append(str(exc))
    if missing or invalid:
        return DoctorCheck(
            id="bundled_assets",
            status="fail",
            message="Bundled schema/demo/proposal assets are missing or invalid.",
            detail={"missing": missing, "invalid": invalid},
        )
    return DoctorCheck(
        id="bundled_assets",
        status="pass",
        message="Bundled schema/demo/proposal assets are available.",
        detail={"assets": list(REQUIRED_ASSETS)},
    )


def _check_fixture_replay_module() -> DoctorCheck:
    try:
        module = importlib.import_module("kyoko.fixture_replay")
    except ImportError as exc:
        return DoctorCheck(
            id="fixture_replay",
            status="fail",
            message=f"Fixture replay module is not importable: {exc}",
            detail={},
        )
    return DoctorCheck(
        id="fixture_replay",
        status="pass",
        message="Fixture replay module is importable.",
        detail={"module": getattr(module, "__name__", "kyoko.fixture_replay")},
    )


def _check_fixture_replay_server_module() -> DoctorCheck:
    try:
        module = importlib.import_module("kyoko.fixture_replay_server")
    except ImportError as exc:
        return DoctorCheck(
            id="fixture_replay_server",
            status="fail",
            message=f"Fixture replay server module is not importable: {exc}",
            detail={},
        )
    return DoctorCheck(
        id="fixture_replay_server",
        status="pass",
        message="Fixture replay server module is importable.",
        detail={"module": getattr(module, "__name__", "kyoko.fixture_replay_server")},
    )


def _check_package_metadata() -> DoctorCheck:
    try:
        version = importlib.metadata.version("kyoko")
    except importlib.metadata.PackageNotFoundError:
        source_metadata = _source_checkout_package_metadata()
        if source_metadata is not None:
            detail = {
                "source": "source_checkout",
                **source_metadata,
                "module_version": __version__,
            }
            if source_metadata["version"] != __version__:
                return DoctorCheck(
                    id="package_metadata",
                    status="warn",
                    message=(
                        "Kyoko source metadata version does not match "
                        "kyoko.__version__."
                    ),
                    detail=detail,
                )
            return DoctorCheck(
                id="package_metadata",
                status="pass",
                message=f"Kyoko source checkout metadata found: {source_metadata['version']}",
                detail=detail,
            )
        return DoctorCheck(
            id="package_metadata",
            status="warn",
            message="Kyoko is running from a source checkout, not installed package metadata.",
            detail={},
        )
    return DoctorCheck(
        id="package_metadata",
        status="pass",
        message=f"Installed Kyoko package metadata found: {version}",
        detail={"version": version},
    )


def _source_checkout_package_metadata() -> Optional[dict[str, str]]:
    setup_cfg = Path(__file__).resolve().parents[1] / "setup.cfg"
    if not setup_cfg.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(setup_cfg)
    try:
        name = parser["metadata"]["name"]
        version = parser["metadata"]["version"]
    except KeyError:
        return None
    if name != "kyoko":
        return None
    return {"name": name, "version": version}


def _check_operator_commands() -> DoctorCheck:
    found = {command: shutil.which(command) for command in OPTIONAL_OPERATOR_COMMANDS}
    available = {key: value for key, value in found.items() if value}
    status = "pass" if available else "warn"
    message = (
        "At least one optional operator command is available."
        if available
        else "No optional operator CLI was found on PATH; registered adapters can still be added later."
    )
    return DoctorCheck(
        id="operator_commands",
        status=status,
        message=message,
        detail={"commands": found},
    )


def _check_release_python_targets() -> DoctorCheck:
    commands = {
        target: shutil.which(f"python{target}")
        for target in RELEASE_PYTHON_TARGETS
    }
    available = {target: path for target, path in commands.items() if path}
    build_backends = {
        target: (
            None
            if path is None
            else python_build_backend_reason(python_executable=path, timeout_seconds=10)
        )
        for target, path in commands.items()
    }
    missing_targets = [target for target, path in commands.items() if path is None]
    bootstrap_required_targets = [
        target
        for target, path in commands.items()
        if path is not None and build_backends[target] is not None
    ]
    ready_targets = [
        target
        for target, path in commands.items()
        if path is not None
    ]
    ready_matrix_command = (
        "python3 -m kyoko release-smoke "
        + " ".join(f"--python-target {shlex.quote(target)}" for target in ready_targets)
        + " --artifact both --json"
        if ready_targets
        else None
    )
    build_backend_install_commands: dict[str, list[str]] = {}
    status = "pass" if set(available) == set(RELEASE_PYTHON_TARGETS) else "warn"
    message = (
        "Python release-smoke matrix targets are available."
        if status == "pass"
        else (
            "Some Python release-smoke matrix targets are missing; available "
            "targets can run with isolated build-backend bootstrap."
        )
    )
    return DoctorCheck(
        id="release_python_targets",
        status=status,
        message=message,
        detail={
            "targets": commands,
            "build_backend_reasons": build_backends,
            "missing_targets": missing_targets,
            "ready_targets": ready_targets,
            "bootstrap_required_targets": bootstrap_required_targets,
            "unready_targets": {},
            "ready_matrix_command": ready_matrix_command,
            "build_backend_install_commands": build_backend_install_commands,
            "matrix_command": "python3 -m kyoko release-smoke --python-matrix --artifact both --json",
        },
    )


def _check_mcp_clients() -> DoctorCheck:
    commands = {
        command: shutil.which(command)
        for command in MCP_CLIENT_COMMANDS
    }
    available = {command: path for command, path in commands.items() if path}
    status = "pass" if set(available) == set(MCP_CLIENT_COMMANDS) else "warn"
    message = (
        "Codex and Claude MCP clients are available for install smoke checks."
        if status == "pass"
        else (
            "One or more native MCP clients are missing; "
            "install-smoke matrix will skip missing clients by default."
        )
    )
    return DoctorCheck(
        id="mcp_clients",
        status=status,
        message=message,
        detail={
            "clients": commands,
            "matrix_command": "python3 -m kyoko mcp install-smoke --all-targets --json",
        },
    )


def _check_port(*, host: str, port: int) -> DoctorCheck:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
    if result == 0:
        return DoctorCheck(
            id="serve_port",
            status="warn",
            message=f"{host}:{port} is already in use; kyoko serve must use another port.",
            detail={"host": host, "port": port},
        )
    return DoctorCheck(
        id="serve_port",
        status="pass",
        message=f"{host}:{port} is available for kyoko serve.",
        detail={"host": host, "port": port},
    )


def _check_ace(*, db_path: Optional[Path], ace_path: Path) -> DoctorCheck:
    with TemporaryDirectory() as tmpdir:
        selected_db = db_path or Path(tmpdir) / "doctor-ace.db"
        initialize_database(selected_db)
        report = check_ace_compatibility(db_path=selected_db, ace_path=ace_path)
    return DoctorCheck(
        id="ace_compat",
        status="pass" if report.get("available") else "warn",
        message="ACE compatibility import succeeded."
        if report.get("available")
        else "ACE compatibility import is not currently available.",
        detail=report,
    )


def _check_demo_smoke(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_demo_smoke_check(
                db_path=Path(tmpdir) / "doctor-demo.db",
                output_dir=None,
                temporary=True,
            )
    output_dir.mkdir(parents=True, exist_ok=True)
    return _run_demo_smoke_check(
        db_path=output_dir / "doctor-demo.db",
        output_dir=output_dir,
        temporary=False,
    )


def _run_demo_smoke_check(
    *,
    db_path: Path,
    output_dir: Optional[Path],
    temporary: bool,
) -> DoctorCheck:
    try:
        report = run_demo_setup(db_path=db_path)
    except DemoError as exc:
        return DoctorCheck(
            id="demo_smoke",
            status="fail",
            message=f"Bundled demo smoke failed: {exc}",
            detail={
                "db_path": str(db_path),
                "output_dir": str(output_dir) if output_dir is not None else None,
                "temporary": temporary,
                "artifacts_retained": not temporary,
            },
        )
    return DoctorCheck(
        id="demo_smoke",
        status="pass",
        message="Bundled demo loop completed.",
        detail={
            "db_path": str(db_path),
            "output_dir": str(output_dir) if output_dir is not None else None,
            "temporary": temporary,
            "artifacts_retained": not temporary,
            "eval_status": report.eval_status,
            "promoted_trust_level": report.promoted_trust_level,
            "applied_skill_ids": list(report.applied_skill_ids),
        },
    )


def _check_operator_smoke_prepare(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_operator_smoke_prepare_check(
                output_dir=Path(tmpdir) / "operator-smoke-prepare",
                temporary=True,
            )
    return _run_operator_smoke_prepare_check(output_dir=output_dir, temporary=False)


def _run_operator_smoke_prepare_check(*, output_dir: Path, temporary: bool) -> DoctorCheck:
    try:
        report = run_operator_smoke_matrix(
            prepare_only=True,
            output_dir=output_dir,
        )
    except (OperatorSmokeError, StorageError) as exc:
        return DoctorCheck(
            id="operator_smoke_prepare",
            status="fail",
            message=f"Operator prepare-only smoke failed: {exc}",
            detail={
                "output_dir": str(output_dir),
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "live_operator_invoked": False,
            },
        )
    payload = report.to_json()

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    failed = int(summary.get("failed", 0))
    prepared = int(summary.get("prepared", 0))
    passed = int(summary.get("passed", 0))
    status = "fail" if failed else "pass" if prepared + passed > 0 else "warn"
    if status == "pass":
        message = "Operator prepare-only smoke generated prompt/evidence handoffs."
    elif status == "warn":
        message = "No installed operator preset was available for prepare-only smoke."
    else:
        message = "One or more operator prepare-only smoke targets failed."
    return DoctorCheck(
        id="operator_smoke_prepare",
        status=status,
        message=message,
        detail={
            **payload,
            "temporary": temporary,
            "artifacts_retained": not temporary,
            "live_operator_invoked": False,
            "matrix_command": (
                "python3 -m kyoko operator-smoke "
                "--all-presets --prepare-only --json"
            ),
        },
    )


def _check_judge_smoke_prepare(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_judge_smoke_prepare_check(
                output_dir=Path(tmpdir) / "judge-smoke-prepare",
                temporary=True,
            )
    return _run_judge_smoke_prepare_check(output_dir=output_dir, temporary=False)


def _run_judge_smoke_prepare_check(*, output_dir: Path, temporary: bool) -> DoctorCheck:
    try:
        report = run_judge_smoke(
            output_dir=output_dir,
            prepare_only=True,
            provider_backed=True,
        )
    except (JudgeSmokeError, EvalError, StorageError) as exc:
        return DoctorCheck(
            id="judge_smoke_prepare",
            status="fail",
            message=f"Judge prepare-only smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(output_dir),
                "external_command_invoked": False,
                "provider_backed": True,
                "external_model_invoked": False,
            },
        )
    payload = report.to_json()
    return DoctorCheck(
        id="judge_smoke_prepare",
        status="pass",
        message="Judge prepare-only smoke generated request and handoff artifacts.",
        detail={
            **payload,
            "temporary": temporary,
            "artifacts_retained": not temporary,
            "commands": {
                "judge_smoke_prepare": (
                    "python3 -m kyoko judge-smoke --prepare-only --provider-backed "
                    "--output-dir /tmp/kyoko-judge-smoke --json"
                ),
                "judge_smoke_live_provider": (
                    "python3 -m kyoko judge-smoke --command "
                    "'python /path/to/provider-judge.py' --provider-backed "
                    "--output-dir .kyoko/smoke/judge-provider-live --json"
                ),
            },
        },
    )


def _check_ace_native_prepare(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_ace_native_prepare_check(
                root=Path(tmpdir) / "ace-native-prepare",
                temporary=True,
            )
    return _run_ace_native_prepare_check(root=output_dir, temporary=False)


def _run_ace_native_prepare_check(*, root: Path, temporary: bool) -> DoctorCheck:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "doctor-ace-native-prepare.db"
    source_fixture_path = bundled_asset_path("source-events/hermes-news-research-minimal.json")
    schema_path = bundled_asset_path("schemas/learning-proposal.schema.json")
    try:
        ingest_source_fixture(db_path, source_fixture_path)
        report = prepare_native_ace_command(
            db_path,
            command=[
                sys.executable,
                "-m",
                "kyoko.ace_legacy_smoke_command",
                "--after",
                "{after_path}",
            ],
            profile_id="profile_news_research_001",
            output_dir=root,
            schema_path=schema_path,
            provider_backed=True,
            timeout_seconds=30,
        )
    except (AceBridgeError, StorageError, OSError) as exc:
        return DoctorCheck(
            id="ace_native_prepare",
            status="fail",
            message=f"Native ACE prepare-only smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(root),
                "db_path": str(db_path),
                "external_command_invoked": False,
                "provider_backed": False,
                "live_operator_invoked": False,
                "external_model_invoked": False,
                "canonical_mutation": False,
            },
        )

    payload = report.to_json()
    return DoctorCheck(
        id="ace_native_prepare",
        status="pass",
        message="Native ACE prepare-only smoke generated cloned Skillbook handoff artifacts.",
        detail={
            "temporary": temporary,
            "artifacts_retained": not temporary,
            "output_dir": str(root),
            "db_path": str(db_path),
            "profile_id": payload.get("profile_id"),
            "before_path": payload.get("before_path"),
            "after_path": payload.get("after_path"),
            "handoff_path": payload.get("handoff_path"),
            "proposal_output_dir": payload.get("proposal_output_dir"),
            "command": payload.get("command"),
            "original_command": payload.get("original_command"),
            "shell_command": payload.get("shell_command"),
            "environment_keys": payload.get("environment_keys"),
            "before_schema_version": payload.get("before_schema_version"),
            "before_skill_count": payload.get("before_skill_count"),
            "after_initialized_from_before": payload.get("after_initialized_from_before"),
            "prepare_only": payload.get("prepare_only"),
            "prepared": payload.get("prepared"),
            "passed": payload.get("passed"),
            "external_command_invoked": payload.get("external_command_invoked"),
            "provider_backed": payload.get("provider_backed"),
            "live_operator_invoked": payload.get("live_operator_invoked"),
            "external_model_invoked": payload.get("external_model_invoked"),
            "canonical_mutation": payload.get("canonical_mutation"),
            "commands": {
                "ace_native_prepare": (
                    "python3 -m kyoko ace-native-run --db /tmp/kyoko.db "
                    "--command 'python /path/to/provider-backed-ace.py --after {after_path}' "
                    "--output-dir /tmp/kyoko-ace-native --prepare-only --provider-backed --json"
                ),
            },
        },
    )


def _check_integration_smoke(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_integration_smoke_check(root=Path(tmpdir), temporary=True)
    return _run_integration_smoke_check(root=output_dir, temporary=False)


def _check_improve_smoke(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_improve_smoke_check(
                root=Path(tmpdir) / "improve-smoke",
                temporary=True,
            )
    return _run_improve_smoke_check(root=output_dir, temporary=False)


def _check_opentelemetry_smoke(
    *,
    output_dir: Optional[Path] = None,
    python_executable: Optional[Path] = None,
) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_opentelemetry_smoke_check(
                root=Path(tmpdir) / "opentelemetry-smoke",
                temporary=True,
                python_executable=python_executable,
            )
    return _run_opentelemetry_smoke_check(
        root=output_dir,
        temporary=False,
        python_executable=python_executable,
    )


def _check_mcp_install_smoke(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_mcp_install_smoke_check(
                output_dir=Path(tmpdir) / "mcp-install-smoke",
                temporary=True,
            )
    return _run_mcp_install_smoke_check(output_dir=output_dir, temporary=False)


def _check_ace_native_smoke(*, output_dir: Optional[Path] = None) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_ace_native_smoke_check(
                root=Path(tmpdir) / "ace-native-smoke",
                temporary=True,
            )
    return _run_ace_native_smoke_check(root=output_dir, temporary=False)


def _check_dashboard_smoke(
    *,
    output_dir: Optional[Path] = None,
    screenshot: bool = False,
    install_browser_deps: bool = False,
    timeout_seconds: int = 30,
) -> DoctorCheck:
    if output_dir is None:
        with TemporaryDirectory() as tmpdir:
            return _run_dashboard_smoke_check(
                root=Path(tmpdir) / "dashboard-smoke",
                temporary=True,
                screenshot=False,
                install_browser_deps=install_browser_deps,
                timeout_seconds=timeout_seconds,
            )
    return _run_dashboard_smoke_check(
        root=output_dir,
        temporary=False,
        screenshot=screenshot,
        install_browser_deps=install_browser_deps,
        timeout_seconds=timeout_seconds,
    )


def _run_dashboard_smoke_check(
    *,
    root: Path,
    temporary: bool,
    screenshot: bool,
    install_browser_deps: bool,
    timeout_seconds: int,
) -> DoctorCheck:
    from .dashboard_smoke import DashboardSmokeError, run_dashboard_browser_smoke

    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "dashboard-smoke.db"
    try:
        report = run_dashboard_browser_smoke(
            db_path=db_path,
            output_dir=root,
            seed_demo=True,
            screenshot=screenshot,
            install_browser_deps=install_browser_deps,
            timeout_seconds=timeout_seconds,
        )
    except (DashboardSmokeError, StorageError, OSError) as exc:
        return DoctorCheck(
            id="dashboard_smoke",
            status="fail",
            message=f"Dashboard browser smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(root),
                "db_path": str(db_path),
                "seeded_demo": True,
                "screenshot": screenshot,
                "install_browser_deps": install_browser_deps,
                "timeout_seconds": timeout_seconds,
                "browser_backend": None,
                "passed": False,
                "live_operator_invoked": False,
                "external_model_invoked": False,
            },
        )

    payload = report.to_json()
    viewports = payload.get("viewports") if isinstance(payload.get("viewports"), list) else []
    passed = bool(payload.get("passed"))
    detail = {
        "temporary": temporary,
        "artifacts_retained": not temporary,
        "output_dir": str(root),
        "db_path": str(db_path),
        "seeded_demo": bool(payload.get("seeded_demo")),
        "screenshot": screenshot,
        "install_browser_deps": install_browser_deps,
        "timeout_seconds": timeout_seconds,
        "passed": passed,
        "browser_backend": payload.get("browser_backend"),
        "server_url": payload.get("server_url"),
        "api_profiles_count": payload.get("api_profiles_count"),
        "api_metric_cards_count": payload.get("api_metric_cards_count"),
        "console_errors": payload.get("console_errors"),
        "page_errors": payload.get("page_errors"),
        "request_failures": payload.get("request_failures"),
        "viewports": [
            {
                "name": viewport.get("name"),
                "width": viewport.get("width"),
                "height": viewport.get("height"),
                "metric_count": viewport.get("metric_count"),
                "metric_overflow_count": len(viewport.get("metric_overflows") or []),
                "screenshot_path": viewport.get("screenshot_path"),
                "passed": viewport.get("passed"),
            }
            for viewport in viewports
            if isinstance(viewport, dict)
        ],
        "live_operator_invoked": False,
        "external_model_invoked": False,
        "commands": {
            "dashboard_smoke": (
                "python3 -m kyoko dashboard-smoke "
                "--output-dir /tmp/kyoko-dashboard-smoke --screenshot --json"
            ),
        },
    }
    return DoctorCheck(
        id="dashboard_smoke",
        status="pass" if passed else "fail",
        message=(
            "Dashboard browser smoke passed on desktop and mobile viewports."
            if passed
            else "Dashboard browser smoke completed but did not pass."
        ),
        detail=detail,
    )


def _run_ace_native_smoke_check(*, root: Path, temporary: bool) -> DoctorCheck:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "doctor-ace-native.db"
    try:
        report = run_legacy_ace_offline_adapter_smoke(
            db_path=db_path,
            output_dir=root,
            persist=True,
            schema_path=bundled_asset_path("schemas/learning-proposal.schema.json"),
            timeout_seconds=30,
        )
    except (AceBridgeError, StorageError, OSError) as exc:
        return DoctorCheck(
            id="ace_native_smoke",
            status="fail",
            message=f"Installed ACE Skillbook smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(root),
                "db_path": str(db_path),
                "external_command_invoked": True,
                "installed_ace_package_invoked": False,
                "provider_backed": False,
                "live_operator_invoked": False,
                "external_model_invoked": False,
            },
        )

    payload = report.to_json(include_proposals=False)
    native = payload.get("native_run") if isinstance(payload.get("native_run"), dict) else {}
    diff = native.get("diff") if isinstance(native.get("diff"), dict) else {}
    passed = bool(payload.get("passed"))
    detail = {
        "temporary": temporary,
        "artifacts_retained": not temporary,
        "output_dir": str(root),
        "db_path": str(db_path),
        "source_fixture_path": payload.get("source_fixture_path"),
        "command_path": payload.get("command_path"),
        "profile_id": payload.get("profile_id"),
        "passed": passed,
        "external_command_invoked": bool(payload.get("external_command_invoked")),
        "installed_ace_package_invoked": bool(payload.get("installed_ace_package_invoked")),
        "provider_backed": bool(payload.get("provider_backed")),
        "live_operator_invoked": bool(payload.get("live_operator_invoked")),
        "external_model_invoked": bool(payload.get("external_model_invoked")),
        "proposal_ids": diff.get("proposal_ids"),
        "unsupported_changes": diff.get("unsupported_changes"),
        "stdout_tail": native.get("stdout_tail"),
        "stderr_tail": native.get("stderr_tail"),
        "commands": {
            "ace_native_smoke": (
                "python3 -m kyoko ace-native-smoke "
                "--db /tmp/kyoko.db --output-dir /tmp/kyoko-ace-native-smoke --json"
            ),
        },
    }
    return DoctorCheck(
        id="ace_native_smoke",
        status="pass" if passed else "fail",
        message=(
            "Installed ACE Skillbook smoke passed through clone/diff proposal import."
            if passed
            else "Installed ACE Skillbook smoke completed but produced no importable proposal."
        ),
        detail=detail,
    )


def _run_improve_smoke_check(*, root: Path, temporary: bool) -> DoctorCheck:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "doctor-improve.db"
    try:
        report = run_generated_improve_smoke(
            db_path=db_path,
            output_dir=root,
            schema_path=bundled_asset_path("schemas/learning-proposal.schema.json"),
            timeout_seconds=20,
        )
    except (ImproveSmokeError, StorageError, OSError) as exc:
        return DoctorCheck(
            id="improve_smoke",
            status="fail",
            message=f"Generated improve smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(root),
                "db_path": str(db_path),
                "live_operator_invoked": False,
                "external_model_invoked": False,
            },
        )

    payload = report.to_json()
    improve = payload.get("improve") if isinstance(payload.get("improve"), dict) else {}
    source_smoke = (
        payload.get("source_smoke") if isinstance(payload.get("source_smoke"), dict) else {}
    )
    source_status = (
        source_smoke.get("status") if isinstance(source_smoke.get("status"), dict) else {}
    )
    final_status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    replay_runs = improve.get("replay_runs") if isinstance(improve.get("replay_runs"), list) else []
    autonomy = improve.get("autonomy") if isinstance(improve.get("autonomy"), dict) else {}
    decisions = autonomy.get("decisions") if isinstance(autonomy.get("decisions"), list) else []
    passed = bool(payload.get("passed"))

    detail = {
        "temporary": temporary,
        "artifacts_retained": not temporary,
        "output_dir": str(root),
        "db_path": str(db_path),
        "framework": payload.get("framework"),
        "profile_id": improve.get("profile_id") or source_smoke.get("profile_id"),
        "proposal_id": improve.get("proposal_id"),
        "replay_adapter_id": payload.get("replay_adapter_id"),
        "passed": passed,
        "live_operator_invoked": bool(payload.get("live_operator_invoked")),
        "external_model_invoked": bool(payload.get("external_model_invoked")),
        "generated_source_adapter_invoked": bool(
            payload.get("generated_source_adapter_invoked")
        ),
        "managed_replay_server_invoked": bool(
            payload.get("managed_replay_server_invoked")
        ),
        "source_adapter": {
            "kind": source_smoke.get("kind"),
            "profile_id": source_smoke.get("profile_id"),
            "ingested_counts": source_smoke.get("ingested_counts"),
            "status_counts": source_status.get("counts"),
        },
        "improve": {
            "operator": improve.get("operator"),
            "generated_eval_spec_ids": improve.get("generated_eval_spec_ids"),
            "replay_run_count": len(replay_runs),
            "replay_statuses": [
                replay.get("status")
                for replay in replay_runs
                if isinstance(replay, dict)
            ],
            "autonomy_actions": [
                decision.get("action")
                for decision in decisions
                if isinstance(decision, dict)
            ],
        },
        "status_counts": final_status.get("counts"),
        "commands": {
            "improve_smoke": (
                "python3 -m kyoko integration-smoke improve "
                "--db /tmp/kyoko.db --output-dir /tmp/kyoko-improve-smoke --json"
            ),
        },
    }
    return DoctorCheck(
        id="improve_smoke",
        status="pass" if passed else "fail",
        message=(
            "Generated improve smoke passed through replay/eval/autonomy apply."
            if passed
            else "Generated improve smoke completed but did not pass."
        ),
        detail=detail,
    )


def _run_opentelemetry_smoke_check(
    *,
    root: Path,
    temporary: bool,
    python_executable: Optional[Path],
) -> DoctorCheck:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "doctor-opentelemetry.db"
    try:
        report = run_opentelemetry_sdk_smoke(
            db_path=db_path,
            output_dir=root,
            python_executable=python_executable,
            timeout_seconds=30,
        )
    except (OtlpSmokeError, StorageError, OSError) as exc:
        return DoctorCheck(
            id="opentelemetry_smoke",
            status="fail",
            message=f"OpenTelemetry SDK smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(root),
                "db_path": str(db_path),
                "python_executable": str(python_executable) if python_executable else None,
                "opentelemetry_sdk_invoked": False,
                "live_operator_invoked": False,
                "external_model_invoked": False,
            },
        )

    payload = report.to_json()
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    passed = bool(payload.get("passed"))
    detail = {
        "temporary": temporary,
        "artifacts_retained": not temporary,
        "output_dir": str(root),
        "db_path": str(db_path),
        "python_executable": payload.get("python_executable"),
        "opentelemetry_sdk_version": payload.get("opentelemetry_sdk_version"),
        "profile_id": payload.get("profile_id"),
        "passed": passed,
        "opentelemetry_sdk_invoked": bool(payload.get("opentelemetry_sdk_invoked")),
        "live_operator_invoked": bool(payload.get("live_operator_invoked")),
        "external_model_invoked": bool(payload.get("external_model_invoked")),
        "run_count": len(payload.get("run_ids") or []),
        "span_count": len(payload.get("span_ids") or []),
        "ingested_counts": payload.get("ingested_counts"),
        "status_counts": status.get("counts"),
        "paths": {
            "script_path": payload.get("script_path"),
            "otlp_payload_path": payload.get("otlp_payload_path"),
            "normalized_path": payload.get("normalized_path"),
            "stdout_path": payload.get("stdout_path"),
            "stderr_path": payload.get("stderr_path"),
        },
        "commands": {
            "opentelemetry_smoke": (
                "python3 -m kyoko integration-smoke opentelemetry-python "
                "--db /tmp/kyoko.db --python-executable /path/to/venv/bin/python "
                "--output-dir /tmp/kyoko-opentelemetry-smoke --json"
            ),
        },
    }
    return DoctorCheck(
        id="opentelemetry_smoke",
        status="pass" if passed else "fail",
        message=(
            "OpenTelemetry SDK smoke emitted and ingested OTLP JSON."
            if passed
            else "OpenTelemetry SDK smoke completed but did not pass."
        ),
        detail=detail,
    )


def _run_mcp_install_smoke_check(*, output_dir: Path, temporary: bool) -> DoctorCheck:
    from .mcp import McpError, run_mcp_install_smoke_matrix

    try:
        report = run_mcp_install_smoke_matrix(
            output_dir=output_dir,
            schema_path=bundled_asset_path("schemas/learning-proposal.schema.json"),
        )
    except (McpError, StorageError) as exc:
        return DoctorCheck(
            id="mcp_install_smoke",
            status="fail",
            message=f"Isolated MCP client install smoke failed: {exc}",
            detail={
                "output_dir": str(output_dir),
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "live_operator_invoked": False,
            },
        )
    payload = report.to_json()
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    failed = int(summary.get("failed", 0))
    passed = int(summary.get("passed", 0))
    status = "fail" if failed else "pass" if passed > 0 else "warn"
    if status == "pass":
        message = "Isolated MCP client install smoke passed."
    elif status == "warn":
        message = "No native MCP client was available for isolated install smoke."
    else:
        message = "One or more isolated MCP client install smoke targets failed."
    return DoctorCheck(
        id="mcp_install_smoke",
        status=status,
        message=message,
        detail={
            **payload,
            "temporary": temporary,
            "artifacts_retained": not temporary,
            "live_operator_invoked": False,
            "matrix_command": "python3 -m kyoko mcp install-smoke --all-targets --json",
        },
    )


def _run_integration_smoke_check(*, root: Path, temporary: bool) -> DoctorCheck:
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "doctor-integration.db"
    source_adapter_path = root / "kyoko_source_adapter.py"
    source_hook_path = root / "doctor_source_hook.py"
    source_output_dir = root / "source-smoke"
    replay_server_path = root / "kyoko_replay_server.py"
    replay_hook_path = root / "doctor_replay_hook.py"
    replay_output_dir = root / "replay-smoke"
    try:
        write_source_adapter_template(
            output_path=source_adapter_path,
            framework="langgraph-python",
            profile_name="doctor-smoke",
            force=True,
        )
        source_hook_path.write_text(_DOCTOR_SOURCE_HOOK, encoding="utf-8")
        source_report = run_source_adapter_smoke(
            db_path=db_path,
            adapter_path=source_adapter_path,
            hook=f"{source_hook_path}:collect",
            output_dir=source_output_dir,
            profile_id="profile_doctor_integration_smoke",
            source_id="source_doctor_integration_smoke",
            agent_id="agent_doctor_integration_smoke",
            agent_name="doctor-smoke-agent",
            timeout_seconds=20,
        )

        write_replay_server_template(
            output_path=replay_server_path,
            framework="generic-python",
            profile_name="doctor-smoke",
            force=True,
        )
        replay_hook_path.write_text(_DOCTOR_REPLAY_HOOK, encoding="utf-8")
        replay_port = _free_loopback_port()
        replay_report = run_replay_server_smoke(
            command=[sys.executable, str(replay_server_path), "--port", str(replay_port)],
            server_url=f"http://127.0.0.1:{replay_port}",
            output_dir=replay_output_dir,
            replay_hook=f"{replay_hook_path}:replay",
            run_replay=True,
            startup_timeout_seconds=5,
        )
    except (
        IntegrationSmokeError,
        ReplayTemplateError,
        SourceTemplateError,
        StorageError,
        OSError,
    ) as exc:
        return DoctorCheck(
            id="integration_smoke",
            status="fail",
            message=f"Generated integration smoke failed: {exc}",
            detail={
                "temporary": temporary,
                "artifacts_retained": not temporary,
                "output_dir": str(root),
                "db_path": str(db_path),
                "source_adapter_path": str(source_adapter_path),
                "source_hook_path": str(source_hook_path),
                "replay_server_path": str(replay_server_path),
                "replay_hook_path": str(replay_hook_path),
            },
        )

    source_payload = source_report.to_json()
    replay_payload = replay_report.to_json()

    source_counts = (
        source_payload.get("status", {}).get("counts", {})
        if isinstance(source_payload.get("status"), dict)
        else {}
    )
    return DoctorCheck(
        id="integration_smoke",
        status="pass",
        message="Generated source-adapter and replay-server integration smokes passed.",
        detail={
            "temporary": temporary,
            "artifacts_retained": not temporary,
            "output_dir": str(root),
            "db_path": str(db_path),
            "source_adapter_path": str(source_adapter_path),
            "source_hook_path": str(source_hook_path),
            "replay_server_path": str(replay_server_path),
            "replay_hook_path": str(replay_hook_path),
            "source_adapter": {
                "kind": source_payload.get("kind"),
                "profile_id": source_payload.get("profile_id"),
                "ingested_counts": source_payload.get("ingested_counts"),
                "status_counts": source_counts,
                "source_events_path": source_payload.get("source_events_path"),
                "stdout_path": source_payload.get("stdout_path"),
                "stderr_path": source_payload.get("stderr_path"),
            },
            "replay_server": {
                "kind": replay_payload.get("kind"),
                "started": replay_payload.get("started"),
                "healthy": replay_payload.get("healthy"),
                "replay_ok": replay_payload.get("replay_ok"),
                "replay_path": replay_payload.get("replay_path"),
                "replay_request": replay_payload.get("replay_request"),
                "replay_response": replay_payload.get("replay_response"),
                "stopped": replay_payload.get("stopped"),
                "health": replay_payload.get("health"),
                "state_path": replay_payload.get("state_path"),
                "stdout_path": replay_payload.get("stdout_path"),
                "stderr_path": replay_payload.get("stderr_path"),
            },
            "live_operator_invoked": False,
            "commands": {
                "source_template": "python3 -m kyoko source-adapter-template /tmp/kyoko_source_adapter.py --framework langgraph-python --json",
                "source_smoke": "python3 -m kyoko integration-smoke source --db /tmp/kyoko.db /tmp/kyoko_source_adapter.py --hook /tmp/source_hook.py:collect --json",
                "replay_template": "python3 -m kyoko replay-server-template /tmp/kyoko_replay_server.py --framework generic-python --json",
                "replay_smoke": "python3 -m kyoko integration-smoke replay-server --command 'python3 /tmp/kyoko_replay_server.py --port 61200' --server-url http://127.0.0.1:61200 --hook /tmp/replay_hook.py:replay --run-replay --json",
            },
        },
    )


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


_DOCTOR_SOURCE_HOOK = '''
def collect(context):
    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    agent_id = context["agent_id"]
    node_id = "node_doctor_integration_smoke"
    run_id = "run_doctor_integration_smoke_001"
    span_id = "span_doctor_integration_smoke_001"
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
        "sources": [{
            "id": source_id,
            "profile_id": profile_id,
            "kind": context["framework"],
            "display_name": "Doctor integration smoke",
            "status": "active",
            "adapter_version": "kyoko.doctor.integration_smoke.v0",
            "config_json": {},
            "capabilities_json": ["trace"],
            "last_seen_at": now,
        }],
        "agent_identities": [{
            "id": agent_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": "doctor-smoke-agent",
            "name": context["agent_name"],
            "kind": "agent",
            "role": None,
            "model": None,
            "workspace_path": context["root_path"],
            "metadata_json": {},
        }],
        "workflow_nodes": [{
            "id": node_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": "doctor-smoke-agent",
            "agent_identity_id": agent_id,
            "kind": "agent",
            "name": context["agent_name"],
            "metadata_json": {},
        }],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [{
            "id": run_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": run_id,
            "root_span_id": span_id,
            "agent_identity_id": agent_id,
            "task_attempt_id": None,
            "status": "succeeded",
            "started_at": now,
            "ended_at": now,
            "input_ref": "input://doctor-smoke",
            "output_ref": "output://doctor-smoke",
            "summary": "Doctor integration smoke run",
            "metadata_json": {},
        }],
        "spans": [{
            "id": span_id,
            "run_id": run_id,
            "source_id": source_id,
            "external_id": span_id,
            "parent_span_id": None,
            "workflow_node_id": node_id,
            "agent_identity_id": agent_id,
            "kind": "agent",
            "name": "Doctor integration smoke",
            "status": "succeeded",
            "started_at": now,
            "ended_at": now,
            "input_ref": "input://doctor-smoke",
            "output_ref": "output://doctor-smoke",
            "usage_json": {},
            "attributes_json": {},
            "raw_ref": None,
        }],
        "handoffs": [],
        "timeline_events": [],
    }
'''


_DOCTOR_REPLAY_HOOK = '''
def replay(request):
    return {
        "status": "passed",
        "output_run_id": "run_doctor_replay_smoke_001",
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {},
        "executed_agent": False,
        "note": "doctor generated replay smoke completed without live model calls",
    }
'''


def doctor_report_text(report: DoctorReport) -> str:
    lines = []
    for check in report.checks:
        lines.append(f"{check.status.upper()}: {check.id}: {check.message}")
        if check.status != "pass" and check.detail:
            lines.append(f"  {json.dumps(check.detail, sort_keys=True)}")
    readiness = _doctor_readiness_summary(
        checks=report.checks,
        suggested_commands=report.suggested_commands,
        retained_external_evidence=report.retained_external_evidence,
    )
    lines.append(
        "readiness: "
        f"local_runtime_ready={_text_bool(readiness['local_runtime_ready'])} "
        f"local_v0_ready={_text_bool(readiness['local_v0_ready'])} "
        f"safe_smokes_complete={_text_bool(readiness['safe_smokes_complete'])}"
    )
    _append_readiness_list(lines, "blocking_checks", readiness["blocking_checks"])
    _append_readiness_list(lines, "warning_checks", readiness["warning_checks"])
    _append_readiness_list(
        lines,
        "pending_safe_smoke_checks",
        readiness["pending_safe_smoke_checks"],
    )
    _append_readiness_list(
        lines,
        "external_evidence_warnings",
        readiness["external_evidence_warnings"],
    )
    _append_readiness_list(
        lines,
        "satisfied_external_evidence_commands",
        readiness["satisfied_external_evidence_commands"],
    )
    _append_readiness_list(
        lines,
        "pending_external_evidence_commands",
        readiness["pending_external_evidence_commands"],
    )
    if report.suggested_commands:
        lines.append("suggested_commands:")
        for command in report.suggested_commands:
            if not isinstance(command, dict):
                continue
            intent = command.get("intent") or "command"
            cli_args = _format_suggested_cli_args(command.get("cli_args"))
            if cli_args is None:
                continue
            lines.append(f"  {intent}: {cli_args}")
            requires = command.get("requires")
            if isinstance(requires, list) and requires:
                lines.append(f"    requires: {', '.join(str(item) for item in requires)}")
    lines.append(f"overall: {'ok' if report.ok else 'failed'}")
    return "\n".join(lines)


def _append_readiness_list(lines: list[str], label: str, values: Any) -> None:
    if not isinstance(values, list) or not values:
        return
    lines.append(f"  {label}: {', '.join(str(value) for value in values)}")


def _text_bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _format_suggested_cli_args(value: Any) -> Optional[str]:
    if not isinstance(value, list):
        return None
    return shlex.join(str(item) for item in value)
