from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .analyze import (
    AnalyzeError,
    AnalyzeReport,
    ProposeForIssueReport,
    analyze_with_command_operator,
    analyze_with_mock_operator,
    propose_for_issue,
)
from .autonomy import AutonomyError, evaluate_issue_to_proposal_gate
from .autonomy_runner import AutonomyRunError, AutonomyRunReport, run_autonomy
from .checks import CheckError, generate_checks_for_proposal, list_check_specs
from .issue_guard import GuardError, GuardReport, mint_guard_for_issue
from .issues import IssueError, accept_issue, get_issue, update_issue_status
from .operator_adapters import (
    OperatorAdapterError,
    get_operator_adapter_command,
    run_registered_operator_adapter,
)
from .replay_adapters import ReplayAdapterError, run_registered_replay_adapter
from .replay_servers import ReplayServerError
from .skillbook_manager import (
    ConsolidationReport,
    SkillbookManagerError,
    run_skillbook_consolidation,
)
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
    # Back-compat: the first authored proposal id (or None when nothing was authored).
    proposal_id: Optional[str]
    # All proposals authored this run (gate #1 `autonomous` issues), in order.
    proposal_ids: tuple[str, ...]
    operator: Optional[str]
    analyze: Optional[AnalyzeReport]
    check_spec_ids: tuple[str, ...]
    generated_check_spec_ids: tuple[str, ...]
    existing_check_spec_ids: tuple[str, ...]
    replay_runs: tuple[dict[str, Any], ...]
    autonomy: Optional[AutonomyRunReport]
    source_import: Optional[DiscoveredSourceImportReport]
    notes: tuple[str, ...]
    # Per-issue gate #1 outcomes surfaced this run (issue_id -> mode), structured for the API.
    gate1_outcomes: tuple[dict[str, Any], ...] = ()
    guard_reports: tuple[GuardReport, ...] = ()
    # Phase 3: the post-analysis skillbook-consolidation turn (None when not run / no dups).
    consolidation: Optional[ConsolidationReport] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "proposal_id": self.proposal_id,
            "proposal_ids": list(self.proposal_ids),
            "operator": self.operator,
            "analyze": _analyze_report_json(self.analyze),
            "check_spec_ids": list(self.check_spec_ids),
            "generated_check_spec_ids": list(self.generated_check_spec_ids),
            "existing_check_spec_ids": list(self.existing_check_spec_ids),
            "replay_runs": list(self.replay_runs),
            "autonomy": self.autonomy.to_json() if self.autonomy is not None else None,
            "source_import": self.source_import.to_json() if self.source_import is not None else None,
            "guards": [guard.to_json() for guard in self.guard_reports],
            "gate1_outcomes": [dict(outcome) for outcome in self.gate1_outcomes],
            "consolidation": self.consolidation.to_json() if self.consolidation is not None else None,
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
    consolidate: bool = True,
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
    notes: list[str] = []
    gate1_outcomes: list[dict[str, Any]] = []
    authored_proposal_ids: list[str] = []

    if proposal_id is None:
        # ---- Diagnosis phase: analysis surfaces ISSUES only (no proposal). ----
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
        profile_id = analyze_report.profile_id

        # ---- Gate #1: per newly-surfaced issue, the section's autonomy mode decides
        # whether to author a proposal now (autonomous), leave it for a human to accept
        # (propose), or stop at diagnosed (off). ----
        for issue_id in analyze_report.new_issue_ids:
            try:
                issue = get_issue(db_path=db_path, issue_id=issue_id)
            except IssueError as exc:
                raise ImproveError(str(exc)) from exc
            section = issue.get("section")
            gate = evaluate_issue_to_proposal_gate(
                db_path=db_path, section=section, profile_id=profile_id
            )
            gate1_outcomes.append(
                {"issue_id": issue_id, "section": section, **gate.to_json()}
            )
            if gate.mode == "autonomous":
                try:
                    accept_issue(db_path=db_path, issue_id=issue_id)
                    propose_report = _propose_for_each(
                        db_path=db_path,
                        output_dir=selected_output_dir,
                        issue_id=issue_id,
                        operator=operator,
                        operator_command=operator_command,
                        operator_adapter=operator_adapter,
                        operator_timeout_seconds=operator_timeout_seconds,
                        operator_max_retries=operator_max_retries,
                        schema_path=schema_path,
                        profile_id=profile_id,
                    )
                except (AnalyzeError, IssueError, OperatorAdapterError) as exc:
                    raise ImproveError(str(exc)) from exc
                authored_proposal_ids.append(propose_report.proposal_id)
                notes.append(f"gate1_autonomous_authored:{issue_id}:{propose_report.proposal_id}")
            elif gate.mode == "propose":
                notes.append(f"gate1_propose_awaiting_acceptance:{issue_id}")
            else:
                notes.append(f"gate1_off_diagnosed:{issue_id}")

        if not authored_proposal_ids:
            # Nothing authored: every issue was diagnosed-only (off) or left for a human
            # to accept (propose). There is nothing to check/replay/apply this run, but the
            # skillbook may still carry duplicates from prior runs — consolidate it.
            if profile_id is None:
                profile_id = analyze_report.profile_id
            consolidation_report = _maybe_consolidate(
                db_path=db_path,
                output_dir=selected_output_dir,
                profile_id=profile_id,
                operator=operator,
                operator_command=operator_command,
                run_autonomy_after=run_autonomy_after,
                harness_workspace_root=harness_workspace_root,
                consolidate=consolidate,
                notes=notes,
            )
            return ImproveReport(
                profile_id=profile_id,
                proposal_id=None,
                proposal_ids=(),
                operator=selected_operator,
                analyze=analyze_report,
                check_spec_ids=(),
                generated_check_spec_ids=(),
                existing_check_spec_ids=(),
                replay_runs=(),
                autonomy=None,
                source_import=source_import_report,
                gate1_outcomes=tuple(gate1_outcomes),
                consolidation=consolidation_report,
                notes=tuple(notes),
            )
        target_proposal_ids = authored_proposal_ids
    else:
        # ---- Direct proposal path (skip analysis): gate #2 over this one proposal. ----
        target_proposal_ids = [proposal_id]

    if profile_id is None:
        profile_id = _proposal_profile_id(db_path, target_proposal_ids[0])
    profile_harness_workspace_root = None
    if run_autonomy_after and harness_workspace_root is None:
        profile_harness_workspace_root = _profile_workspace_root_if_available(
            db_path,
            profile_id,
        )

    # ---- Gate #2: generate checks + replay for every targeted proposal. ----
    generated_check_spec_ids: list[str] = []
    existing_check_spec_ids: list[str] = []
    check_spec_ids: list[str] = []
    replay_runs: list[dict[str, Any]] = []
    for target_proposal_id in target_proposal_ids:
        try:
            check_generation = generate_checks_for_proposal(
                db_path=db_path,
                proposal_id=target_proposal_id,
            )
            generated_check_spec_ids.extend(check_generation.check_spec_ids)
            existing_check_spec_ids.extend(check_generation.existing_check_spec_ids)
            profile_id = check_generation.profile_id
        except CheckError as exc:
            if str(exc).startswith("no_check_spec_changes:"):
                notes.append(str(exc))
            else:
                raise ImproveError(str(exc)) from exc
        except StorageError as exc:
            raise ImproveError(str(exc)) from exc

        proposal_check_spec_ids = _check_spec_ids_for_proposal(db_path, target_proposal_id)
        check_spec_ids.extend(proposal_check_spec_ids)
        selected_replay_adapter_id = replay_adapter_id or _default_replay_adapter_id(
            db_path, profile_id
        )
        if selected_replay_adapter_id is not None:
            if not proposal_check_spec_ids:
                notes.append(
                    f"replay_adapter_skipped_no_check_specs:{selected_replay_adapter_id}"
                )
            for check_spec_id in proposal_check_spec_ids:
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
                replay_runs.append(
                    _replay_report_json(replay_report, selected_replay_adapter_id)
                )

    autonomy_report: Optional[AutonomyRunReport] = None
    guard_reports: list[GuardReport] = []
    if run_autonomy_after:
        try:
            autonomy_report = run_autonomy(
                db_path=db_path,
                profile_id=profile_id,
                harness_workspace_root=harness_workspace_root or profile_harness_workspace_root,
            )
        except (AutonomyRunError, AutonomyError, StorageError) as exc:
            raise ImproveError(str(exc)) from exc

        # Close the loop (job step 08): for every proposal the gate just applied, resolve
        # its originating Issue and mint a standing deterministic guard evaluator that
        # watches future traces for recurrence.
        for decision in autonomy_report.decisions:
            if decision.state_after != "applied" or not decision.proposal_id:
                continue
            issue_id = _issue_id_for_proposal(db_path, decision.proposal_id)
            if not issue_id:
                continue
            try:
                update_issue_status(db_path=db_path, issue_id=issue_id, status="resolved")
                guard_reports.append(
                    mint_guard_for_issue(
                        db_path=db_path, issue_id=issue_id, profile_id=profile_id
                    )
                )
            except (GuardError, IssueError, StorageError) as exc:
                notes.append(f"guard_mint_failed:{issue_id}:{exc}")

    if profile_id is None:
        profile_id = _profile_id_from_outputs(analyze_report, autonomy_report)
    if profile_id is None:
        raise ImproveError("profile_id_unresolved")

    # ---- Phase 3: consolidate the skillbook (keep it live and tracked). Runs after the
    # gate + resolve/guard step; its proposals flow through the SAME gate as any proposal. ----
    consolidation_report = _maybe_consolidate(
        db_path=db_path,
        output_dir=selected_output_dir,
        profile_id=profile_id,
        operator=operator if proposal_id is None else "mock",
        operator_command=operator_command,
        run_autonomy_after=run_autonomy_after,
        harness_workspace_root=harness_workspace_root or profile_harness_workspace_root,
        consolidate=consolidate,
        notes=notes,
    )

    return ImproveReport(
        profile_id=profile_id,
        proposal_id=target_proposal_ids[0] if target_proposal_ids else None,
        proposal_ids=tuple(target_proposal_ids),
        operator=selected_operator,
        analyze=analyze_report,
        check_spec_ids=tuple(check_spec_ids),
        generated_check_spec_ids=tuple(generated_check_spec_ids),
        existing_check_spec_ids=tuple(existing_check_spec_ids),
        replay_runs=tuple(replay_runs),
        autonomy=autonomy_report,
        source_import=source_import_report,
        gate1_outcomes=tuple(gate1_outcomes),
        consolidation=consolidation_report,
        notes=tuple(notes),
        guard_reports=tuple(guard_reports),
    )


def _maybe_consolidate(
    *,
    db_path: Path,
    output_dir: Path,
    profile_id: Optional[str],
    operator: str,
    operator_command: Optional[Sequence[str]],
    run_autonomy_after: bool,
    harness_workspace_root: Optional[Path],
    consolidate: bool,
    notes: list[str],
) -> Optional[ConsolidationReport]:
    """Run the skillbook-consolidation turn, returning ``None`` when disabled or when there
    are no duplicate skills (keeps the report — and the contract golden — empty in the
    common case). Consolidation proposals flow through the SAME gate as any proposal."""

    if not consolidate:
        return None
    try:
        report = run_skillbook_consolidation(
            db_path=db_path,
            output_dir=output_dir,
            profile_id=profile_id,
            operator=operator if operator in {"mock", "command"} else "mock",
            command=operator_command if operator == "command" else None,
            run_autonomy_after=run_autonomy_after,
            harness_workspace_root=harness_workspace_root,
        )
    except SkillbookManagerError as exc:
        notes.append(f"consolidation_failed:{exc}")
        return None
    if report.duplicate_group_count == 0:
        return None
    return report


def _propose_for_each(
    *,
    db_path: Path,
    output_dir: Path,
    issue_id: str,
    operator: str,
    operator_command: Optional[Sequence[str]],
    operator_adapter: Optional[str],
    operator_timeout_seconds: int,
    operator_max_retries: int,
    schema_path: Optional[Path],
    profile_id: Optional[str],
) -> ProposeForIssueReport:
    """Author one proposal from an accepted issue using the SAME operator as analysis."""

    if operator == "mock":
        return propose_for_issue(
            db_path=db_path,
            output_dir=output_dir,
            issue_id=issue_id,
            operator="mock",
            schema_path=schema_path,
            profile_id=profile_id,
        )
    if operator == "command":
        if operator_command is None:
            raise ImproveError("operator_command_required")
        return propose_for_issue(
            db_path=db_path,
            output_dir=output_dir,
            issue_id=issue_id,
            operator="command",
            command=operator_command,
            timeout_seconds=operator_timeout_seconds,
            max_retries=operator_max_retries,
            schema_path=schema_path,
            profile_id=profile_id,
        )

    # adapter / named-operator: resolve the registered adapter's command + kind.
    adapter_id = operator_adapter if operator == "adapter" else operator
    if not adapter_id:
        raise ImproveError("operator_adapter_required")
    command, operator_kind = get_operator_adapter_command(
        db_path=db_path, adapter_id=adapter_id
    )
    return propose_for_issue(
        db_path=db_path,
        output_dir=output_dir,
        issue_id=issue_id,
        operator="command",
        command=command,
        operator_kind=operator_kind,
        adapter_id=adapter_id,
        timeout_seconds=operator_timeout_seconds,
        max_retries=operator_max_retries,
        schema_path=schema_path,
        profile_id=profile_id,
    )


def _issue_id_for_proposal(db_path: Path, proposal_id: str) -> Optional[str]:
    """The originating issue id stamped on a proposal (issue-centric spine)."""
    try:
        with connect(db_path) as connection:
            row = connection.execute(
                "SELECT issue_id FROM learning_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
    except StorageError:
        return None
    if row is None:
        return None
    value = row["issue_id"] if "issue_id" in row.keys() else None
    return str(value) if value else None


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
        "issue_ids": list(report.issue_ids),
        "new_issue_ids": list(report.new_issue_ids),
        "bundled_issue_ids": list(report.bundled_issue_ids),
        "operator_run_id": report.operator_run_id,
        "evidence_path": str(report.evidence_path),
        "prompt_path": str(report.prompt_path),
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
