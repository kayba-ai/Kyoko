from __future__ import annotations

import tempfile
import shlex
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .analyze import (
    AnalyzeError,
    AnalyzeReport,
    analyze_with_command_operator,
    analyze_with_mock_operator,
    expand_operator_command,
    list_operator_runs,
)
from .bundled_assets import AssetError, load_bundled_json
from .operator_adapters import OperatorAdapterError, list_operator_adapters, run_registered_operator_adapter
from .operator_prompts import BEGIN_PROPOSAL_BLOCK, END_PROPOSAL_BLOCK, write_operator_prompt_artifacts
from .operator_presets import OPERATOR_PRESETS, bootstrap_operator_adapters
from .storage import StorageError, ingest_source_payload, initialize_database


class OperatorSmokeError(Exception):
    """Raised when an operator smoke run cannot complete."""


@dataclass(frozen=True)
class OperatorSmokeReport:
    operator: str
    profile_id: str
    proposal_id: str
    operator_run_id: Optional[str]
    db_path: Path
    output_dir: Path
    used_demo_database: bool
    evidence_path: Path
    prompt_path: Path
    proposal_path: Path
    raw_output_path: Optional[Path]
    persisted: bool
    attempts: int
    live_operator_invoked: bool

    def to_json(self) -> dict[str, object]:
        return {
            "operator": self.operator,
            "profile_id": self.profile_id,
            "proposal_id": self.proposal_id,
            "operator_run_id": self.operator_run_id,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "used_demo_database": self.used_demo_database,
            "evidence_path": str(self.evidence_path),
            "prompt_path": str(self.prompt_path),
            "proposal_path": str(self.proposal_path),
            "raw_output_path": str(self.raw_output_path) if self.raw_output_path else None,
            "persisted": self.persisted,
            "attempts": self.attempts,
            "live_operator_invoked": self.live_operator_invoked,
        }


@dataclass(frozen=True)
class OperatorFailureSmokeReport:
    operator: str
    profile_id: Optional[str]
    db_path: Path
    output_dir: Path
    used_demo_database: bool
    evidence_path: Optional[Path]
    prompt_path: Optional[Path]
    raw_output_path: Optional[Path]
    operator_run_id: Optional[str]
    status: str
    error: Optional[str]
    failure_kind: Optional[str]
    last_attempt_status: Optional[str]
    attempts: int
    expected_failure_kind: Optional[str]
    prompt_failure_mode: str
    live_operator_invoked: bool
    proposal_id: Optional[str] = None
    persisted: bool = False

    @property
    def passed(self) -> bool:
        if self.status != "captured":
            return False
        if self.expected_failure_kind is None:
            return True
        return self.failure_kind == self.expected_failure_kind

    def to_json(self) -> dict[str, object]:
        return {
            "operator": self.operator,
            "profile_id": self.profile_id,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "used_demo_database": self.used_demo_database,
            "evidence_path": str(self.evidence_path) if self.evidence_path else None,
            "prompt_path": str(self.prompt_path) if self.prompt_path else None,
            "raw_output_path": str(self.raw_output_path) if self.raw_output_path else None,
            "operator_run_id": self.operator_run_id,
            "status": self.status,
            "error": self.error,
            "failure_kind": self.failure_kind,
            "last_attempt_status": self.last_attempt_status,
            "attempts": self.attempts,
            "expected_failure_kind": self.expected_failure_kind,
            "prompt_failure_mode": self.prompt_failure_mode,
            "live_operator_invoked": self.live_operator_invoked,
            "proposal_id": self.proposal_id,
            "persisted": self.persisted,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class OperatorSmokePlanReport:
    operator: str
    operator_kind: str
    profile_id: str
    db_path: Path
    output_dir: Path
    used_demo_database: bool
    evidence_path: Path
    prompt_path: Path
    raw_output_path: Optional[Path]
    command: tuple[str, ...]
    expanded_command: tuple[str, ...]
    shell_command: Optional[str]
    environment: dict[str, str]
    live_operator_invoked: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "operator": self.operator,
            "operator_kind": self.operator_kind,
            "profile_id": self.profile_id,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "used_demo_database": self.used_demo_database,
            "evidence_path": str(self.evidence_path),
            "prompt_path": str(self.prompt_path),
            "raw_output_path": str(self.raw_output_path) if self.raw_output_path else None,
            "command": list(self.command),
            "expanded_command": list(self.expanded_command),
            "shell_command": self.shell_command,
            "environment": dict(self.environment),
            "live_operator_invoked": self.live_operator_invoked,
        }


@dataclass(frozen=True)
class OperatorSmokeTargetReport:
    operator: str
    status: str
    reason: Optional[str]
    plan: Optional[OperatorSmokePlanReport] = None
    report: Optional[object] = None

    def to_json(self) -> dict[str, object]:
        return {
            "operator": self.operator,
            "status": self.status,
            "reason": self.reason,
            "plan": self.plan.to_json() if self.plan is not None else None,
            "report": self.report.to_json() if self.report is not None else None,
        }


@dataclass(frozen=True)
class OperatorSmokeMatrixReport:
    operators: tuple[str, ...]
    prepare_only: bool
    db_path: Path
    output_dir: Path
    used_demo_database: bool
    targets: tuple[OperatorSmokeTargetReport, ...]
    passed: bool

    def to_json(self) -> dict[str, object]:
        return {
            "operators": list(self.operators),
            "prepare_only": self.prepare_only,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "used_demo_database": self.used_demo_database,
            "targets": [target.to_json() for target in self.targets],
            "summary": _matrix_summary(self.targets),
            "passed": self.passed,
        }


@dataclass(frozen=True)
class OperatorFailureSmokeMatrixReport:
    operators: tuple[str, ...]
    db_path: Path
    output_dir: Path
    used_demo_database: bool
    expected_failure_kind: Optional[str]
    prompt_failure_mode: str
    targets: tuple[OperatorSmokeTargetReport, ...]
    passed: bool

    def to_json(self) -> dict[str, object]:
        return {
            "operators": list(self.operators),
            "expect_failure": True,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "used_demo_database": self.used_demo_database,
            "expected_failure_kind": self.expected_failure_kind,
            "prompt_failure_mode": self.prompt_failure_mode,
            "targets": [target.to_json() for target in self.targets],
            "summary": _matrix_summary(self.targets),
            "passed": self.passed,
        }


def build_operator_smoke_plan(
    *,
    operator: str,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    operator_command: Optional[Sequence[str]] = None,
    operator_adapter: Optional[str] = None,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    schema_path: Optional[Path] = None,
) -> OperatorSmokePlanReport:
    selected_output_dir, selected_db_path, used_demo_database = _prepare_smoke_workspace(
        db_path=db_path,
        output_dir=output_dir,
    )
    resolved = _resolve_operator_plan(
        operator=operator,
        db_path=selected_db_path,
        operator_command=operator_command,
        operator_adapter=operator_adapter,
        profile_id=profile_id,
    )
    prompt_report = write_operator_prompt_artifacts(
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        target=resolved["operator_kind"],
        profile_id=resolved.get("profile_id"),
        run_id=run_id,
        schema_path=schema_path,
    )
    command = tuple(str(part) for part in resolved["command"])
    raw_output_path = selected_output_dir / "operator-output.txt" if command else None
    environment = _operator_environment(
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        profile_id=prompt_report.profile_id,
        operator_kind=str(resolved["operator_kind"]),
        schema_path=prompt_report.schema_path,
        run_id=run_id,
    )
    prompt_text = prompt_report.prompt_path.read_text()
    expanded_command = tuple(
        expand_operator_command(
            command,
            prompt_text=prompt_text,
            evidence_path=prompt_report.evidence_path,
            prompt_path=prompt_report.prompt_path,
            profile_id=prompt_report.profile_id,
            schema_path=prompt_report.schema_path,
            run_id=run_id,
        )
    )

    return OperatorSmokePlanReport(
        operator=str(resolved["operator"]),
        operator_kind=str(resolved["operator_kind"]),
        profile_id=prompt_report.profile_id,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        used_demo_database=used_demo_database,
        evidence_path=prompt_report.evidence_path,
        prompt_path=prompt_report.prompt_path,
        raw_output_path=raw_output_path,
        command=command,
        expanded_command=expanded_command,
        shell_command=shlex.join(expanded_command) if expanded_command else None,
        environment=environment,
    )


def run_operator_smoke(
    *,
    operator: str,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    operator_command: Optional[Sequence[str]] = None,
    operator_adapter: Optional[str] = None,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 120,
    max_retries: int = 0,
) -> OperatorSmokeReport:
    if timeout_seconds <= 0:
        raise OperatorSmokeError("timeout_seconds_must_be_positive")
    if max_retries < 0:
        raise OperatorSmokeError("operator_max_retries_must_be_non_negative")

    selected_output_dir, selected_db_path, used_demo_database = _prepare_smoke_workspace(
        db_path=db_path,
        output_dir=output_dir,
    )

    try:
        report = _run_operator(
            operator=operator,
            db_path=selected_db_path,
            output_dir=selected_output_dir,
            operator_command=operator_command,
            operator_adapter=operator_adapter,
            profile_id=profile_id,
            run_id=run_id,
            schema_path=schema_path,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            prompt_suffix=None,
        )
    except (AnalyzeError, OperatorAdapterError, StorageError) as exc:
        raise OperatorSmokeError(str(exc)) from exc

    return OperatorSmokeReport(
        operator=report.operator,
        profile_id=report.profile_id,
        proposal_id=report.proposal_id,
        operator_run_id=report.operator_run_id,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        used_demo_database=used_demo_database,
        evidence_path=report.evidence_path,
        prompt_path=report.prompt_path,
        proposal_path=report.proposal_path,
        raw_output_path=report.raw_output_path,
        persisted=report.persisted,
        attempts=report.attempts,
        live_operator_invoked=report.operator != "mock",
    )


def run_operator_failure_smoke(
    *,
    operator: str,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    operator_command: Optional[Sequence[str]] = None,
    operator_adapter: Optional[str] = None,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 120,
    max_retries: int = 0,
    expected_failure_kind: Optional[str] = "invalid_output",
    prompt_failure_mode: str = "invalid-output",
) -> OperatorFailureSmokeReport:
    if timeout_seconds <= 0:
        raise OperatorSmokeError("timeout_seconds_must_be_positive")
    if max_retries < 0:
        raise OperatorSmokeError("operator_max_retries_must_be_non_negative")

    selected_output_dir, selected_db_path, used_demo_database = _prepare_smoke_workspace(
        db_path=db_path,
        output_dir=output_dir,
    )
    prompt_suffix = _failure_prompt_suffix(prompt_failure_mode)

    try:
        success = _run_operator(
            operator=operator,
            db_path=selected_db_path,
            output_dir=selected_output_dir,
            operator_command=operator_command,
            operator_adapter=operator_adapter,
            profile_id=profile_id,
            run_id=run_id,
            schema_path=schema_path,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            prompt_suffix=prompt_suffix,
        )
    except (AnalyzeError, OperatorAdapterError, StorageError) as exc:
        run = _operator_run_for_output_dir(selected_db_path, selected_output_dir)
        return _failure_report_from_run(
            operator=operator,
            db_path=selected_db_path,
            output_dir=selected_output_dir,
            used_demo_database=used_demo_database,
            expected_failure_kind=expected_failure_kind,
            prompt_failure_mode=prompt_failure_mode,
            fallback_error=str(exc),
            run=run,
        )

    return OperatorFailureSmokeReport(
        operator=success.operator,
        profile_id=success.profile_id,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        used_demo_database=used_demo_database,
        evidence_path=success.evidence_path,
        prompt_path=success.prompt_path,
        raw_output_path=success.raw_output_path,
        operator_run_id=success.operator_run_id,
        status="unexpected_success",
        error="operator_failure_smoke_unexpected_success",
        failure_kind=None,
        last_attempt_status="succeeded",
        attempts=success.attempts,
        expected_failure_kind=expected_failure_kind,
        prompt_failure_mode=prompt_failure_mode,
        live_operator_invoked=success.operator != "mock",
        proposal_id=success.proposal_id,
        persisted=success.persisted,
    )


def run_operator_smoke_matrix(
    *,
    operators: Optional[Sequence[str]] = None,
    prepare_only: bool = False,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 120,
    max_retries: int = 0,
    skip_missing: bool = True,
) -> OperatorSmokeMatrixReport:
    selected_operators = _normalize_matrix_operators(operators)
    selected_output_dir, selected_db_path, used_demo_database = _prepare_smoke_workspace(
        db_path=db_path,
        output_dir=output_dir,
    )
    targets: list[OperatorSmokeTargetReport] = []
    for operator in selected_operators:
        target_output_dir = selected_output_dir / operator
        try:
            if prepare_only:
                plan = build_operator_smoke_plan(
                    operator=operator,
                    db_path=selected_db_path,
                    output_dir=target_output_dir,
                    profile_id=profile_id,
                    run_id=run_id,
                    schema_path=schema_path,
                )
                targets.append(
                    OperatorSmokeTargetReport(
                        operator=operator,
                        status="prepared",
                        reason=None,
                        plan=plan,
                    )
                )
            else:
                report = run_operator_smoke(
                    operator=operator,
                    db_path=selected_db_path,
                    output_dir=target_output_dir,
                    profile_id=profile_id,
                    run_id=run_id,
                    schema_path=schema_path,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                )
                targets.append(
                    OperatorSmokeTargetReport(
                        operator=operator,
                        status="passed",
                        reason=None,
                        report=report,
                    )
                )
        except (OperatorAdapterError, OperatorSmokeError, StorageError) as exc:
            reason = str(exc)
            if skip_missing and reason.startswith("operator_preset_command_not_found:"):
                targets.append(
                    OperatorSmokeTargetReport(
                        operator=operator,
                        status="skipped",
                        reason=reason,
                    )
                )
                continue
            targets.append(
                OperatorSmokeTargetReport(
                    operator=operator,
                    status="failed",
                    reason=reason,
                )
            )

    summary = _matrix_summary(tuple(targets))
    passed = summary["failed"] == 0 and summary["passed"] + summary["prepared"] > 0
    return OperatorSmokeMatrixReport(
        operators=selected_operators,
        prepare_only=prepare_only,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        used_demo_database=used_demo_database,
        targets=tuple(targets),
        passed=passed,
    )


def run_operator_failure_smoke_matrix(
    *,
    operators: Optional[Sequence[str]] = None,
    db_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 120,
    max_retries: int = 0,
    skip_missing: bool = True,
    expected_failure_kind: Optional[str] = "invalid_output",
    prompt_failure_mode: str = "invalid-output",
) -> OperatorFailureSmokeMatrixReport:
    selected_operators = _normalize_matrix_operators(operators)
    selected_output_dir, selected_db_path, used_demo_database = _prepare_smoke_workspace(
        db_path=db_path,
        output_dir=output_dir,
    )
    targets: list[OperatorSmokeTargetReport] = []
    for operator in selected_operators:
        target_output_dir = selected_output_dir / operator
        try:
            report = run_operator_failure_smoke(
                operator=operator,
                db_path=selected_db_path,
                output_dir=target_output_dir,
                profile_id=profile_id,
                run_id=run_id,
                schema_path=schema_path,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                expected_failure_kind=expected_failure_kind,
                prompt_failure_mode=prompt_failure_mode,
            )
            if (
                skip_missing
                and report.error is not None
                and report.error.startswith("operator_preset_command_not_found:")
            ):
                targets.append(
                    OperatorSmokeTargetReport(
                        operator=operator,
                        status="skipped",
                        reason=report.error,
                    )
                )
                continue
            targets.append(
                OperatorSmokeTargetReport(
                    operator=operator,
                    status="passed" if report.passed else "failed",
                    reason=None if report.passed else report.error,
                    report=report,
                )
            )
        except (OperatorAdapterError, OperatorSmokeError, StorageError) as exc:
            reason = str(exc)
            if skip_missing and reason.startswith("operator_preset_command_not_found:"):
                targets.append(
                    OperatorSmokeTargetReport(
                        operator=operator,
                        status="skipped",
                        reason=reason,
                    )
                )
                continue
            targets.append(
                OperatorSmokeTargetReport(
                    operator=operator,
                    status="failed",
                    reason=reason,
                )
            )

    summary = _matrix_summary(tuple(targets))
    passed = summary["failed"] == 0 and summary["passed"] > 0
    return OperatorFailureSmokeMatrixReport(
        operators=selected_operators,
        db_path=selected_db_path,
        output_dir=selected_output_dir,
        used_demo_database=used_demo_database,
        expected_failure_kind=expected_failure_kind,
        prompt_failure_mode=prompt_failure_mode,
        targets=tuple(targets),
        passed=passed,
    )


def _run_operator(
    *,
    operator: str,
    db_path: Path,
    output_dir: Path,
    operator_command: Optional[Sequence[str]],
    operator_adapter: Optional[str],
    profile_id: Optional[str],
    run_id: Optional[str],
    schema_path: Optional[Path],
    timeout_seconds: int,
    max_retries: int,
    prompt_suffix: Optional[str],
) -> AnalyzeReport:
    if operator == "mock":
        return analyze_with_mock_operator(
            db_path=db_path,
            output_dir=output_dir,
            profile_id=profile_id,
            run_id=run_id,
            schema_path=schema_path,
        )
    if operator == "command":
        if not operator_command:
            raise OperatorSmokeError("operator_command_required")
        return analyze_with_command_operator(
            db_path=db_path,
            output_dir=output_dir,
            command=operator_command,
            operator_label="command",
            profile_id=profile_id,
            run_id=run_id,
            schema_path=schema_path,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            prompt_suffix=prompt_suffix,
        )

    adapter_id = operator_adapter if operator == "adapter" else operator
    if not adapter_id:
        raise OperatorSmokeError("operator_adapter_required")
    _ensure_preset_adapter_if_needed(db_path=db_path, adapter_id=adapter_id, profile_id=profile_id)
    return run_registered_operator_adapter(
        db_path=db_path,
        adapter_id=adapter_id,
        output_dir=output_dir,
        profile_id=profile_id,
        run_id=run_id,
        schema_path=schema_path,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        prompt_suffix=prompt_suffix,
    )


def _normalize_matrix_operators(operators: Optional[Sequence[str]]) -> tuple[str, ...]:
    raw = tuple(operators) if operators is not None else tuple(OPERATOR_PRESETS)
    selected: list[str] = []
    for operator in raw:
        if operator not in OPERATOR_PRESETS:
            raise OperatorSmokeError(f"operator_smoke_matrix_requires_preset:{operator}")
        if operator not in selected:
            selected.append(operator)
    if not selected:
        raise OperatorSmokeError("operator_smoke_matrix_operator_required")
    return tuple(selected)


def _matrix_summary(targets: Sequence[OperatorSmokeTargetReport]) -> dict[str, int]:
    summary = {
        "total": len(targets),
        "prepared": 0,
        "passed": 0,
        "failed": 0,
        "skipped": 0,
        "available": 0,
    }
    for target in targets:
        if target.status in {"prepared", "passed", "failed", "skipped"}:
            summary[target.status] += 1
        if target.status != "skipped":
            summary["available"] += 1
    return summary


def _ensure_preset_adapter_if_needed(
    *,
    db_path: Path,
    adapter_id: str,
    profile_id: Optional[str],
) -> None:
    if _adapter_exists(db_path, adapter_id):
        return
    if adapter_id not in OPERATOR_PRESETS:
        return
    bootstrap_operator_adapters(
        db_path=db_path,
        target=adapter_id,
        profile_id=profile_id,
    )


def _adapter_exists(db_path: Path, adapter_id: str) -> bool:
    return any(adapter.get("id") == adapter_id for adapter in list_operator_adapters(db_path))


def _prepare_smoke_workspace(
    *,
    db_path: Optional[Path],
    output_dir: Optional[Path],
) -> tuple[Path, Path, bool]:
    selected_output_dir = output_dir or Path(tempfile.mkdtemp(prefix="kyoko-operator-smoke-"))
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    selected_db_path = db_path or _demo_db_path(selected_output_dir)
    used_demo_database = db_path is None

    if used_demo_database:
        _seed_demo_database(selected_db_path)
    else:
        initialize_database(selected_db_path)
    return selected_output_dir, selected_db_path, used_demo_database


def _resolve_operator_plan(
    *,
    operator: str,
    db_path: Path,
    operator_command: Optional[Sequence[str]],
    operator_adapter: Optional[str],
    profile_id: Optional[str],
) -> dict[str, object]:
    if operator == "mock":
        return {
            "operator": "mock",
            "operator_kind": "mock",
            "command": (),
            "profile_id": profile_id,
        }
    if operator == "command":
        if not operator_command:
            raise OperatorSmokeError("operator_command_required")
        return {
            "operator": "command",
            "operator_kind": "generic",
            "command": tuple(operator_command),
            "profile_id": profile_id,
        }

    adapter_id = operator_adapter if operator == "adapter" else operator
    if not adapter_id:
        raise OperatorSmokeError("operator_adapter_required")

    adapter = _find_adapter(db_path, adapter_id)
    if adapter is not None:
        if not bool(adapter.get("enabled")):
            raise OperatorSmokeError(f"operator_adapter_disabled:{adapter_id}")
        selected_profile_id = profile_id or str(adapter["profile_id"])
        if selected_profile_id != str(adapter["profile_id"]):
            raise OperatorSmokeError(f"operator_adapter_profile_mismatch:{adapter_id}:{selected_profile_id}")
        return {
            "operator": adapter_id,
            "operator_kind": str(adapter["operator_kind"]),
            "command": tuple(str(part) for part in adapter["command"]),
            "profile_id": selected_profile_id,
        }

    preset = OPERATOR_PRESETS.get(adapter_id)
    if preset is not None:
        if not shutil.which(preset.command[0]):
            raise OperatorSmokeError(f"operator_preset_command_not_found:{preset.command[0]}")
        return {
            "operator": preset.adapter_id,
            "operator_kind": preset.operator_kind,
            "command": preset.command,
            "profile_id": profile_id,
        }

    raise OperatorSmokeError(f"operator_adapter_not_found:{adapter_id}")


def _find_adapter(db_path: Path, adapter_id: str) -> Optional[dict[str, object]]:
    for adapter in list_operator_adapters(db_path):
        if adapter.get("id") == adapter_id:
            return adapter
    return None


def _operator_environment(
    *,
    evidence_path: Path,
    prompt_path: Path,
    profile_id: str,
    operator_kind: str,
    schema_path: Optional[Path],
    run_id: Optional[str],
) -> dict[str, str]:
    environment = {
        "KYOKO_EVIDENCE_PATH": str(evidence_path),
        "KYOKO_OPERATOR_PROMPT_PATH": str(prompt_path),
        "KYOKO_PROFILE_ID": profile_id,
        "KYOKO_OPERATOR_TARGET": operator_kind,
        "KYOKO_PROPOSAL_BLOCK_BEGIN": BEGIN_PROPOSAL_BLOCK,
        "KYOKO_PROPOSAL_BLOCK_END": END_PROPOSAL_BLOCK,
    }
    if schema_path is not None:
        environment["KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH"] = str(schema_path)
    if run_id is not None:
        environment["KYOKO_RUN_ID"] = run_id
    return environment


def _seed_demo_database(db_path: Path) -> None:
    try:
        payload = load_bundled_json("source-events/hermes-news-research-minimal.json")
    except AssetError as exc:
        raise OperatorSmokeError(str(exc)) from exc
    ingest_source_payload(
        db_path=db_path,
        fixture=payload,
        source_label="bundled:source-events/hermes-news-research-minimal.json",
    )


def _demo_db_path(output_dir: Path) -> Path:
    default_path = output_dir / "smoke.db"
    if not default_path.exists():
        return default_path
    return output_dir / f"smoke-{uuid.uuid4().hex[:8]}.db"


def _failure_prompt_suffix(prompt_failure_mode: str) -> str:
    if prompt_failure_mode != "invalid-output":
        raise OperatorSmokeError(f"unsupported_operator_failure_mode:{prompt_failure_mode}")
    return "\n".join(
        [
            "## Expected Failure Capture",
            "",
            "This is a Kyoko negative-path smoke. Ignore the proposal-output instructions above for this run.",
            "Write exactly this single line to stdout and nothing else:",
            "",
            "KYOKO_EXPECTED_INVALID_OPERATOR_OUTPUT",
            "",
            f"Do not include `{BEGIN_PROPOSAL_BLOCK}` or `{END_PROPOSAL_BLOCK}`.",
        ]
    )


def _operator_run_for_output_dir(db_path: Path, output_dir: Path) -> Optional[dict[str, object]]:
    expected_raw_output = output_dir / "operator-output.txt"
    for run in list_operator_runs(db_path):
        raw_output_ref = run.get("raw_output_ref")
        if isinstance(raw_output_ref, str) and Path(raw_output_ref) == expected_raw_output:
            return run
    return None


def _failure_report_from_run(
    *,
    operator: str,
    db_path: Path,
    output_dir: Path,
    used_demo_database: bool,
    expected_failure_kind: Optional[str],
    prompt_failure_mode: str,
    fallback_error: str,
    run: Optional[dict[str, object]],
) -> OperatorFailureSmokeReport:
    if run is None:
        return OperatorFailureSmokeReport(
            operator=operator,
            profile_id=None,
            db_path=db_path,
            output_dir=output_dir,
            used_demo_database=used_demo_database,
            evidence_path=None,
            prompt_path=None,
            raw_output_path=None,
            operator_run_id=None,
            status="uncaptured_failure",
            error=fallback_error,
            failure_kind=None,
            last_attempt_status=None,
            attempts=0,
            expected_failure_kind=expected_failure_kind,
            prompt_failure_mode=prompt_failure_mode,
            live_operator_invoked=operator != "mock",
        )

    status = str(run.get("status") or "")
    return OperatorFailureSmokeReport(
        operator=str(run.get("operator_label") or operator),
        profile_id=str(run["profile_id"]) if run.get("profile_id") is not None else None,
        db_path=db_path,
        output_dir=output_dir,
        used_demo_database=used_demo_database,
        evidence_path=_path_or_none(run.get("evidence_ref")),
        prompt_path=_path_or_none(run.get("prompt_ref")),
        raw_output_path=_path_or_none(run.get("raw_output_ref")),
        operator_run_id=str(run["id"]) if run.get("id") is not None else None,
        status="captured" if status == "failed" else "uncaptured_failure",
        error=str(run["error"]) if run.get("error") is not None else fallback_error,
        failure_kind=str(run["failure_kind"]) if run.get("failure_kind") is not None else None,
        last_attempt_status=(
            str(run["last_attempt_status"]) if run.get("last_attempt_status") is not None else None
        ),
        attempts=int(run.get("attempt_count") or 0),
        expected_failure_kind=expected_failure_kind,
        prompt_failure_mode=prompt_failure_mode,
        live_operator_invoked=str(run.get("operator_label") or operator) != "mock",
        proposal_id=str(run["proposal_id"]) if run.get("proposal_id") is not None else None,
        persisted=run.get("proposal_id") is not None,
    )


def _path_or_none(value: object) -> Optional[Path]:
    if not isinstance(value, str) or not value:
        return None
    return Path(value)
