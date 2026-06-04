from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .analyze import (
    AnalyzeError,
    AnalyzeReport,
    analyze_with_command_operator,
    analyze_with_mock_operator,
)
from .autonomy import AutonomyError
from .autonomy_runner import AutonomyRunError, AutonomyRunReport, run_autonomy
from .checks import CheckError, generate_checks_for_proposal, list_check_specs
from .operator_adapters import OperatorAdapterError, run_registered_operator_adapter
from .replay_adapters import ReplayAdapterError, run_registered_replay_adapter
from .replay_servers import ReplayServerError
from .source_discovery import (
    DiscoveredSourceImportReport,
    SourceDiscoveryError,
    import_discovered_source,
)
from .storage import StorageError, connect, initialize_database, utc_now


class ImproveError(Exception):
    """Raised when the high-level improvement loop cannot continue."""


@dataclass(frozen=True)
class ImproveReport:
    profile_id: str
    proposal_id: str
    operator: Optional[str]
    analyze: Optional[AnalyzeReport]
    check_spec_ids: tuple[str, ...]
    generated_check_spec_ids: tuple[str, ...]
    existing_check_spec_ids: tuple[str, ...]
    replay_runs: tuple[dict[str, Any], ...]
    autonomy: Optional[AutonomyRunReport]
    source_import: Optional[DiscoveredSourceImportReport]
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "proposal_id": self.proposal_id,
            "operator": self.operator,
            "analyze": _analyze_report_json(self.analyze),
            "check_spec_ids": list(self.check_spec_ids),
            "generated_check_spec_ids": list(self.generated_check_spec_ids),
            "existing_check_spec_ids": list(self.existing_check_spec_ids),
            "replay_runs": list(self.replay_runs),
            "autonomy": self.autonomy.to_json() if self.autonomy is not None else None,
            "source_import": self.source_import.to_json() if self.source_import is not None else None,
            "notes": list(self.notes),
        }


def run_improvement_loop(
    *,
    db_path: Path,
    output_dir: Optional[Path] = None,
    proposal_id: Optional[str] = None,
    operator: str = "mock",
    operator_command: Optional[Sequence[str]] = None,
    operator_adapter: Optional[str] = None,
    operator_timeout_seconds: int = 120,
    operator_max_retries: int = 0,
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    schema_path: Optional[Path] = None,
    replay_adapter_id: Optional[str] = None,
    replay_output_dir: Optional[Path] = None,
    replay_timeout_seconds: Optional[int] = None,
    run_autonomy_after: bool = True,
    harness_workspace_root: Optional[Path] = None,
    source_candidate_id: Optional[str] = None,
    source_home: Optional[Path] = None,
    source_import_output_dir: Optional[Path] = None,
    schedule_id: Optional[str] = None,
) -> ImproveReport:
    initialize_database(db_path)
    selected_output_dir = output_dir or _default_output_dir(db_path)
    selected_output_dir.mkdir(parents=True, exist_ok=True)

    source_import_report: Optional[DiscoveredSourceImportReport] = None
    if source_candidate_id is not None:
        try:
            source_import_report = import_discovered_source(
                db_path=db_path,
                candidate_id=source_candidate_id,
                home=source_home,
                profile_id=profile_id,
                root_path=None,
                output_dir=source_import_output_dir,
            )
        except SourceDiscoveryError as exc:
            raise ImproveError(str(exc)) from exc
        if profile_id is None:
            profile_id = source_import_report.import_report.profile_id

    analyze_report: Optional[AnalyzeReport] = None
    selected_operator: Optional[str] = None
    if proposal_id is None:
        selected_operator = operator
        analyze_report = _run_analysis(
            db_path=db_path,
            output_dir=selected_output_dir,
            operator=operator,
            operator_command=operator_command,
            operator_adapter=operator_adapter,
            operator_timeout_seconds=operator_timeout_seconds,
            operator_max_retries=operator_max_retries,
            profile_id=profile_id,
            run_id=run_id,
            since=since,
            schema_path=schema_path,
            schedule_id=schedule_id,
        )
        proposal_id = analyze_report.proposal_id
        profile_id = analyze_report.profile_id

    if proposal_id is None:
        raise ImproveError("proposal_id_required")
    if profile_id is None:
        profile_id = _proposal_profile_id(db_path, proposal_id)
    profile_harness_workspace_root = None
    if run_autonomy_after and harness_workspace_root is None:
        profile_harness_workspace_root = _profile_workspace_root_if_available(
            db_path,
            profile_id,
        )

    notes: list[str] = []
    generated_check_spec_ids: tuple[str, ...] = ()
    existing_check_spec_ids: tuple[str, ...] = ()
    try:
        check_generation = generate_checks_for_proposal(
            db_path=db_path,
            proposal_id=proposal_id,
        )
        generated_check_spec_ids = check_generation.check_spec_ids
        existing_check_spec_ids = check_generation.existing_check_spec_ids
        profile_id = check_generation.profile_id
    except CheckError as exc:
        if str(exc).startswith("no_check_spec_changes:"):
            notes.append(str(exc))
        else:
            raise ImproveError(str(exc)) from exc
    except StorageError as exc:
        raise ImproveError(str(exc)) from exc

    check_spec_ids = _check_spec_ids_for_proposal(db_path, proposal_id)
    replay_runs: list[dict[str, Any]] = []
    selected_replay_adapter_id = replay_adapter_id or _default_replay_adapter_id(db_path, profile_id)
    if selected_replay_adapter_id is not None:
        if not check_spec_ids:
            notes.append(f"replay_adapter_skipped_no_check_specs:{selected_replay_adapter_id}")
        for check_spec_id in check_spec_ids:
            try:
                replay_report = run_registered_replay_adapter(
                    db_path=db_path,
                    adapter_id=selected_replay_adapter_id,
                    check_spec_id=check_spec_id,
                    output_dir=replay_output_dir,
                    timeout_seconds=replay_timeout_seconds,
                    run_check_after=True,
                )
            except (CheckError, ReplayAdapterError, ReplayServerError, StorageError) as exc:
                raise ImproveError(str(exc)) from exc
            replay_runs.append(_replay_report_json(replay_report, selected_replay_adapter_id))

    autonomy_report: Optional[AutonomyRunReport] = None
    if run_autonomy_after:
        try:
            autonomy_report = run_autonomy(
                db_path=db_path,
                profile_id=profile_id,
                harness_workspace_root=harness_workspace_root or profile_harness_workspace_root,
            )
        except (AutonomyRunError, AutonomyError, StorageError) as exc:
            raise ImproveError(str(exc)) from exc

    if profile_id is None:
        profile_id = _profile_id_from_outputs(analyze_report, autonomy_report)
    if profile_id is None:
        raise ImproveError("profile_id_unresolved")

    return ImproveReport(
        profile_id=profile_id,
        proposal_id=proposal_id,
        operator=selected_operator,
        analyze=analyze_report,
        check_spec_ids=tuple(check_spec_ids),
        generated_check_spec_ids=generated_check_spec_ids,
        existing_check_spec_ids=existing_check_spec_ids,
        replay_runs=tuple(replay_runs),
        autonomy=autonomy_report,
        source_import=source_import_report,
        notes=tuple(notes),
    )


def _run_analysis(
    *,
    db_path: Path,
    output_dir: Path,
    operator: str,
    operator_command: Optional[Sequence[str]],
    operator_adapter: Optional[str],
    operator_timeout_seconds: int,
    operator_max_retries: int,
    profile_id: Optional[str],
    run_id: Optional[str],
    schema_path: Optional[Path],
    since: Optional[str] = None,
    schedule_id: Optional[str] = None,
) -> AnalyzeReport:
    if operator == "mock":
        return analyze_with_mock_operator(
            db_path=db_path,
            output_dir=output_dir,
            profile_id=profile_id,
            run_id=run_id,
            since=since,
            schema_path=schema_path,
            schedule_id=schedule_id,
        )
    if operator == "command":
        if operator_command is None:
            raise ImproveError("operator_command_required")
        try:
            return analyze_with_command_operator(
                db_path=db_path,
                output_dir=output_dir,
                command=operator_command,
                operator_label="command",
                profile_id=profile_id,
                run_id=run_id,
                since=since,
                schema_path=schema_path,
                timeout_seconds=operator_timeout_seconds,
                max_retries=operator_max_retries,
                schedule_id=schedule_id,
            )
        except AnalyzeError as exc:
            raise ImproveError(str(exc)) from exc

    adapter_id = operator_adapter if operator == "adapter" else operator
    if not adapter_id:
        raise ImproveError("operator_adapter_required")
    try:
        return run_registered_operator_adapter(
            db_path=db_path,
            adapter_id=adapter_id,
            output_dir=output_dir,
            profile_id=profile_id,
            run_id=run_id,
            since=since,
            schema_path=schema_path,
            timeout_seconds=operator_timeout_seconds,
            max_retries=operator_max_retries,
            schedule_id=schedule_id,
        )
    except OperatorAdapterError as exc:
        raise ImproveError(str(exc)) from exc


def _check_spec_ids_for_proposal(db_path: Path, proposal_id: str) -> tuple[str, ...]:
    return tuple(
        str(spec["id"])
        for spec in list_check_specs(db_path)
        if spec.get("proposal_id") == proposal_id
    )


def _proposal_profile_id(db_path: Path, proposal_id: str) -> str:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT profile_id FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    if row is None:
        raise ImproveError(f"proposal_not_found:{proposal_id}")
    return str(row["profile_id"])


def _profile_workspace_root_if_available(db_path: Path, profile_id: str) -> Optional[Path]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT root_path FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
    if row is None:
        raise ImproveError(f"profile_not_found:{profile_id}")
    root_path = row["root_path"]
    if not isinstance(root_path, str) or not root_path:
        return None
    workspace_root = Path(root_path).expanduser()
    if workspace_root.exists() and workspace_root.is_dir():
        return workspace_root
    return None


def _default_replay_adapter_id(db_path: Path, profile_id: str) -> Optional[str]:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id
            FROM replay_adapters
            WHERE profile_id = ?
              AND enabled = 1
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (profile_id,),
        ).fetchone()
    return str(row["id"]) if row is not None else None


def _default_output_dir(db_path: Path) -> Path:
    safe_timestamp = (
        utc_now()
        .replace(":", "")
        .replace("-", "")
        .replace(".", "")
        .replace("+", "")
    )
    return db_path.parent / ".kyoko" / "improve-runs" / f"improve_{safe_timestamp}"


def _analyze_report_json(report: Optional[AnalyzeReport]) -> Optional[dict[str, Any]]:
    if report is None:
        return None
    return {
        "operator": report.operator,
        "profile_id": report.profile_id,
        "proposal_id": report.proposal_id,
        "operator_run_id": report.operator_run_id,
        "evidence_path": str(report.evidence_path),
        "prompt_path": str(report.prompt_path),
        "proposal_path": str(report.proposal_path),
        "persisted": report.persisted,
        "attempts": report.attempts,
        "raw_output_path": str(report.raw_output_path)
        if report.raw_output_path is not None
        else None,
    }


def _replay_report_json(report: object, adapter_id: str) -> dict[str, Any]:
    completion = getattr(report, "completion", None)
    check_run = getattr(report, "check_run", None)
    payload: dict[str, Any] = {
        "adapter_id": adapter_id,
        "replay_run_id": getattr(report, "replay_run_id", None),
        "profile_id": getattr(report, "profile_id", None),
        "check_spec_id": getattr(report, "check_spec_id", None),
        "status": getattr(completion, "status", None) if completion is not None else None,
        "output_run_id": getattr(completion, "output_run_id", None)
        if completion is not None
        else None,
        "check_run": {
            "check_run_id": check_run.check_run_id,
            "status": check_run.status,
            "promoted_trust_level": check_run.promoted_trust_level,
        }
        if check_run is not None
        else None,
    }
    for attr in ("request_path", "result_path", "raw_output_path", "server_url"):
        if hasattr(report, attr):
            value = getattr(report, attr)
            payload[attr] = str(value) if isinstance(value, Path) else value
    return payload


def _profile_id_from_outputs(
    analyze_report: Optional[AnalyzeReport],
    autonomy_report: Optional[AutonomyRunReport],
) -> Optional[str]:
    if analyze_report is not None:
        return analyze_report.profile_id
    if autonomy_report is not None:
        return autonomy_report.profile_id
    return None


def report_to_pretty_json(report: ImproveReport) -> str:
    return json.dumps(report.to_json(), sort_keys=True)
