from __future__ import annotations

import argparse
import json
import os
import secrets
import shlex
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional, Sequence

from . import __version__
from .ace_bridge import (
    AceBridgeError,
    check_ace_compatibility,
    diff_ace_skillbook_files,
    prepare_native_ace_command,
    run_native_ace_command,
)
from .ace_smoke import run_legacy_ace_offline_adapter_smoke
from .analyze import (
    AnalyzeError,
    analyze_with_command_operator,
    analyze_with_mock_operator,
    list_operator_runs,
    parse_operator_command,
)
from .apply import (
    ApplyError,
    apply_context_proposal,
    list_context_delivery_rules,
    list_context_delivery_rule_revisions,
    list_skill_revisions,
    list_skills,
    rollback_context_delivery_rule_revision,
    rollback_skill_revision,
    set_context_delivery_rule_lock,
    set_skill_lock,
)
from .autonomy import AutonomyError, get_autonomy_policy, update_autonomy_policy
from .autonomy_runner import AutonomyRunError, run_autonomy
from .blobs import (
    list_payload_blobs,
    prune_payload_blobs,
    put_blob,
    retained_until_for_days,
    storage_report,
)
from .bundled_assets import (
    AssetError,
    export_bundled_asset,
    export_bundled_assets,
    list_bundled_assets,
)
from .dashboard_metrics import DashboardMetricsError, get_dashboard_metrics
from .dashboard_smoke import DashboardSmokeError, run_dashboard_browser_smoke
from .details import (
    DetailError,
    get_check_detail,
    get_issue_detail,
    get_proposal_detail,
    get_replay_detail,
    get_run_detail,
    list_runs,
)
from .issues import IssueError, create_issue, list_issues, set_issue_comment, update_issue_status
from .eval_detectors import (
    DetectorError,
    get_detector,
    list_detectors,
    parse_corpus,
    register_detector,
    run_detector,
)
from .evals_measure import (
    EvalMeasureError,
    compare_eval_runs,
    get_measure_results,
    get_measure_run,
    list_measure_runs,
)
from .llm_evals import LlmEvalError, get_llm_eval, list_llm_evals, run_llm_eval
from .demo import DemoError, run_demo_setup
from .doctor import DEFAULT_SMOKE_EVIDENCE_DIR, DoctorError, doctor_report_text, run_doctor
from .evidence import write_evidence_bundle
from .checks import (
    CheckError,
    approve_check_spec,
    complete_replay_from_fixture,
    create_replay_run,
    run_judge_command,
    generate_checks_for_proposal,
    list_assertion_presets,
    list_check_capabilities,
    list_check_runs,
    list_check_locks,
    list_check_specs,
    list_replay_runs,
    parse_judge_command,
    parse_replay_command,
    run_check,
    run_replay_command,
    set_check_lock,
)
from .framework_smoke import (
    DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
    SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS,
    FrameworkSmokeError,
    run_installed_framework_improve_smoke,
    run_installed_framework_replay_smoke,
    run_installed_framework_source_smoke,
)
from .gates import ValidationError, validate_gate_artifacts
from .harness import (
    HarnessError,
    apply_patch_transaction,
    list_harness_target_locks,
    list_patch_transactions,
    prepare_harness_proposal,
    rollback_patch_transaction,
    set_harness_target_lock,
)
from .hermes_import import HermesImportError, ingest_hermes_kanban_db
from .improve import ImproveError, run_improvement_loop
from .improve_smoke import ImproveSmokeError, run_generated_improve_smoke
from .integration_smoke import (
    IntegrationSmokeError,
    run_replay_server_smoke,
    run_source_adapter_smoke,
)
from .judge_smoke import JudgeSmokeError, run_judge_smoke
from .load_smoke import (
    DEFAULT_EXPIRED_BLOB_COUNT,
    DEFAULT_READ_ITERATIONS,
    DEFAULT_READ_WORKERS,
    DEFAULT_RUN_COUNT,
    DEFAULT_SPANS_PER_RUN,
    LoadSmokeError,
    run_load_smoke,
)
from .mcp import (
    McpError,
    build_mcp_config,
    build_mcp_install_plan,
    run_mcp_install_smoke,
    run_mcp_install_smoke_matrix,
    serve_stdio,
    write_mcp_config,
)
from .annotations import AnnotationError, create_annotation, delete_annotation, list_annotations
from .inspection import (
    InspectionError,
    get_current_run,
    get_run_outline,
    get_span_context,
    get_span_payload,
    search_run,
)
from .live import LiveError, ingest_live_events, list_live_events
from .mcp_log import list_mcp_log
from .otlp import OtlpNormalizeError, ingest_otlp_payload
from .otlp_protobuf import OtlpProtobufError, decode_export_trace_service_request
from .otlp_smoke import OtlpSmokeError, run_opentelemetry_sdk_smoke
from .operator_adapters import (
    OperatorAdapterError,
    list_operator_adapters,
    parse_adapter_command as parse_operator_adapter_command,
    register_operator_adapter,
    run_registered_operator_adapter,
)
from .operator_prompts import (
    BEGIN_PROPOSAL_BLOCK,
    END_PROPOSAL_BLOCK,
    write_operator_prompt_artifacts,
)
from .operator_presets import bootstrap_operator_adapters, list_operator_presets, operator_preset_choices
from .operator_smoke import (
    OperatorSmokeError,
    build_operator_smoke_plan,
    run_operator_failure_smoke,
    run_operator_failure_smoke_matrix,
    run_operator_smoke,
    run_operator_smoke_matrix,
)
from .openclaw_import import OpenClawImportError, ingest_openclaw_sessions
from .profile_next import ProfileNextError, run_profile_next_step
from .project_bootstrap import ProjectBootstrapError, bootstrap_project
from .proposals import ProposalError, list_learning_proposals, submit_learning_proposal
from .release_smoke import (
    DEFAULT_RELEASE_PYTHON_TARGETS,
    ReleaseSmokeError,
    run_release_install_smoke,
    run_release_install_smoke_matrix,
)
from .retention import (
    RetentionError,
    prune_retained_data,
)
from .replay_adapters import (
    ReplayAdapterError,
    list_replay_adapters,
    parse_adapter_command,
    register_replay_adapter,
    registered_replay_server_logs,
    registered_replay_server_status,
    run_registered_replay_adapter,
    start_registered_replay_server_adapter,
    stop_registered_replay_server_adapter,
)
from .replay_servers import ReplayServerError, check_replay_server_health, run_replay_server
from .replay_templates import ReplayTemplateError, SUPPORTED_FRAMEWORKS, write_replay_server_template
from .skillbook import export_skillbook, render_skillbook_prompt, write_skillbook_export
from .source_discovery import SourceDiscoveryError, discover_local_sources, import_discovered_source
from .source_templates import (
    SUPPORTED_SOURCE_FRAMEWORKS,
    SourceTemplateError,
    write_source_adapter_template,
)
from .storage import (
    StorageError,
    checkpoint_database,
    create_analysis_schedule,
    default_db_path,
    delete_analysis_schedule,
    get_database_status,
    ingest_source_json,
    ingest_source_fixture,
    initialize_database,
    list_analysis_schedules,
    status_to_json,
)
from .analysis_runner import (
    SCHEDULABLE_ANALYZERS,
    AnalysisJob,
    AnalysisRunError,
    execute_analysis_job,
    job_from_schedule,
    next_run_at_iso,
)
from .timeline import AUTONOMY_EVENT_KINDS, list_timeline_events
from .web import DEFAULT_HOST, DEFAULT_PORT, WebError, serve


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kyoko",
        description="Local, self-hosted optimization loop for agentic workflows.",
    )
    parser.add_argument("--version", action="version", version=f"kyoko {__version__}")

    subcommands = parser.add_subparsers(dest="command")

    validate = subcommands.add_parser(
        "validate-gates",
        help="Validate current pre-build gate artifacts.",
    )
    validate.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing docs/ and scripts/.",
    )
    validate.add_argument(
        "--strict-schema",
        action="store_true",
        help="Fail if jsonschema is not installed.",
    )

    bundled_assets = subcommands.add_parser(
        "bundled-assets",
        help="List or export packaged Kyoko JSON assets for installed-package manual flows.",
    )
    bundled_assets.add_argument(
        "--asset",
        help="Relative bundled asset path to export, such as source-events/hermes-news-research-minimal.json.",
    )
    bundled_assets.add_argument(
        "--output",
        type=Path,
        help="Output file path for --asset.",
    )
    bundled_assets.add_argument(
        "--output-dir",
        type=Path,
        help="Directory to export all bundled JSON assets into.",
    )
    bundled_assets.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    demo = subcommands.add_parser(
        "demo",
        help="Run the bundled first-run demo loop with mocked replay.",
    )
    _add_db_argument(demo)
    demo.add_argument(
        "--output-dir",
        type=Path,
        help="Replay artifact directory. Defaults to <db-parent>/.kyoko/demo-replay.",
    )
    demo.add_argument(
        "--setup-only",
        action="store_true",
        help="Only initialize fixtures, proposal, check, and replay adapter.",
    )
    demo.add_argument(
        "--no-apply",
        action="store_true",
        help="Run replay/check without applying the context skillbook update.",
    )
    demo.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    doctor = subcommands.add_parser(
        "doctor",
        help="Check local first-run readiness and optional integrations.",
    )
    doctor.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional database path to check. Defaults to a temporary database.",
    )
    doctor.add_argument(
        "--smoke-demo",
        action="store_true",
        help="Run the bundled demo loop against a temporary database.",
    )
    doctor.add_argument(
        "--safe-smokes",
        action="store_true",
        help=(
            "Run all no-live-model doctor smokes: bundled demo, operator "
            "prepare-only, judge prepare-only, native ACE prepare-only, "
            "generated integration checks, generated improve smoke, and "
            "isolated MCP client install smoke."
        ),
    )
    doctor.add_argument(
        "--operator-smoke-prepare",
        action="store_true",
        help="Run all-preset operator prepare-only smoke against a temporary database.",
    )
    doctor.add_argument(
        "--judge-smoke-prepare",
        action="store_true",
        help="Prepare a judge-command handoff without invoking a provider.",
    )
    doctor.add_argument(
        "--ace-native-prepare",
        action="store_true",
        help="Prepare a native ACE clone/diff handoff without invoking ACE or a provider.",
    )
    doctor.add_argument(
        "--integration-smoke",
        action="store_true",
        help=(
            "Run generated source-adapter and replay-server integration smokes "
            "against temporary files."
        ),
    )
    doctor.add_argument(
        "--improve-smoke",
        action="store_true",
        help=(
            "Run generated source/replay adapters through the high-level "
            "improve loop without live model CLIs."
        ),
    )
    doctor.add_argument(
        "--opentelemetry-smoke",
        action="store_true",
        help=(
            "Run the installed OpenTelemetry Python SDK through Kyoko OTLP "
            "ingest without live model providers."
        ),
    )
    doctor.add_argument(
        "--opentelemetry-python-executable",
        type=Path,
        help="Python executable that has opentelemetry-sdk installed.",
    )
    doctor.add_argument(
        "--eval-smoke",
        action="store_true",
        help=(
            "Run the bundled failed_span `eval` detector over a seeded corpus "
            "(deterministic; no live model)."
        ),
    )
    doctor.add_argument(
        "--llm-eval-smoke",
        action="store_true",
        help=(
            "Run the bundled hallucination `llm_eval` template through a mock judge "
            "command (deterministic; no live model)."
        ),
    )
    doctor.add_argument(
        "--ace-native-smoke",
        action="store_true",
        help=(
            "Run the installed ACE Skillbook smoke through Kyoko's "
            "clone/diff native ACE boundary without live model providers."
        ),
    )
    doctor.add_argument(
        "--dashboard-smoke",
        action="store_true",
        help="Run a real browser smoke against the local dashboard.",
    )
    doctor.add_argument(
        "--dashboard-smoke-screenshot",
        action="store_true",
        help="Retain dashboard-smoke screenshots when --smoke-output-dir is set.",
    )
    doctor.add_argument(
        "--dashboard-smoke-install-browser-deps",
        action="store_true",
        help=(
            "Install isolated @playwright/test/Chromium browser smoke dependencies "
            "under the dashboard smoke output directory when Python Playwright is missing."
        ),
    )
    doctor.add_argument(
        "--dashboard-smoke-timeout",
        type=int,
        default=30,
        help="Dashboard browser smoke timeout in seconds.",
    )
    doctor.add_argument(
        "--smoke-output-dir",
        type=Path,
        help="Retain optional doctor smoke artifacts under this directory.",
    )
    doctor.add_argument(
        "--smoke-evidence-dir",
        type=Path,
        default=DEFAULT_SMOKE_EVIDENCE_DIR,
        help=(
            "Directory to scan for retained live smoke evidence. Defaults to "
            ".kyoko/smoke; pass a non-existent path to ignore retained evidence."
        ),
    )
    doctor.add_argument(
        "--ace-path",
        type=Path,
        help="Optional ACE checkout/package path for compatibility import diagnostics.",
    )
    doctor.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Host to check for kyoko serve availability.",
    )
    doctor.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to check for kyoko serve availability.",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    release_smoke = subcommands.add_parser(
        "release-smoke",
        help="Build release artifacts, install them into clean venvs, and run package smoke checks.",
    )
    release_smoke.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project root containing pyproject.toml and setup.cfg.",
    )
    release_smoke.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for artifacts and virtual environments. Defaults to a temporary directory.",
    )
    release_smoke.add_argument(
        "--artifact",
        choices=["wheel", "sdist", "both"],
        default="both",
        help="Release artifact type to build and install.",
    )
    release_smoke.add_argument(
        "--install-deps",
        action="store_true",
        help="Install runtime dependencies during artifact install. Defaults to offline --no-deps.",
    )
    release_smoke.add_argument(
        "--skip-demo",
        action="store_true",
        help="Run doctor without the bundled demo loop.",
    )
    release_smoke.add_argument(
        "--dashboard-smoke",
        action="store_true",
        help=(
            "After installing each artifact, run installed-package doctor "
            "--dashboard-smoke with isolated browser dependencies."
        ),
    )
    release_smoke.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Timeout for each build/install/check command.",
    )
    release_smoke.add_argument(
        "--python-executable",
        help="Python executable for the normal single-interpreter release smoke.",
    )
    release_smoke.add_argument(
        "--python-matrix",
        action="store_true",
        help="Run release smoke across Python targets. Defaults to Python 3.12 and 3.13.",
    )
    release_smoke.add_argument(
        "--python-target",
        action="append",
        default=[],
        help="Python executable, command, or version target for --python-matrix. Repeat as needed.",
    )
    release_smoke.add_argument(
        "--python-version",
        action="append",
        default=[],
        help="Python version target for --python-matrix, for example 3.12. Repeat as needed.",
    )
    release_smoke.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    project_bootstrap = subcommands.add_parser(
        "project-bootstrap",
        help="Create local Kyoko project artifacts: DB, templates, MCP config, and operator presets.",
    )
    project_bootstrap.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
        help="Project directory where .kyoko artifacts are created.",
    )
    project_bootstrap.add_argument(
        "--profile-name",
        default="kyoko-agent",
        help="Profile name embedded in generated templates.",
    )
    project_bootstrap.add_argument(
        "--source-framework",
        choices=sorted(SUPPORTED_SOURCE_FRAMEWORKS),
        default="generic-python",
        help="Source adapter framework scaffold.",
    )
    project_bootstrap.add_argument(
        "--replay-framework",
        choices=sorted(SUPPORTED_FRAMEWORKS),
        default="generic-python",
        help="Replay server framework scaffold.",
    )
    project_bootstrap.add_argument(
        "--operator-target",
        choices=operator_preset_choices(),
        default="all",
        help="Operator preset target to bootstrap.",
    )
    project_bootstrap.add_argument(
        "--mcp-target",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        default="generic",
        help="Target label embedded in MCP config.",
    )
    project_bootstrap.add_argument(
        "--skip-operators",
        action="store_true",
        help="Do not register local operator presets.",
    )
    project_bootstrap.add_argument(
        "--force",
        action="store_true",
        help="Overwrite generated source/replay template files.",
    )
    project_bootstrap.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    init = subcommands.add_parser(
        "init",
        help="Initialize a local Kyoko SQLite database.",
    )
    _add_db_argument(init)

    profile_next = subcommands.add_parser(
        "profile-next",
        help="Plan or run the next safe local Kyoko step for a profile.",
    )
    _add_db_argument(profile_next)
    profile_next.add_argument("--profile-id", help="Profile id. Defaults to the implicit workflow profile.")
    profile_next.add_argument(
        "--run",
        action="store_true",
        help="Execute the next local step when Kyoko can do so through registered local adapters or internal gates.",
    )
    profile_next.add_argument(
        "--replay-adapter",
        help="Replay adapter id to use for a replay/check next step.",
    )
    profile_next.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Optional replay artifact output directory.",
    )
    profile_next.add_argument(
        "--replay-timeout",
        type=int,
        help="Optional replay adapter timeout in seconds.",
    )
    profile_next.add_argument(
        "--harness-workspace-root",
        type=Path,
        help="Workspace root for eligible autonomous harness patch application.",
    )
    profile_next.add_argument(
        "--operator-adapter",
        help=(
            "Operator adapter id to run for an analysis next step. Defaults to the latest "
            "enabled profile adapter when --operator-target is not supplied."
        ),
    )
    profile_next.add_argument(
        "--operator-target",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        help=(
            "Operator prompt target used when the next step prepares analysis artifacts. "
            "Supplying this keeps the analysis step prompt-only."
        ),
    )
    profile_next.add_argument(
        "--operator-output-dir",
        type=Path,
        help="Directory for prepared operator evidence/prompt artifacts.",
    )
    profile_next.add_argument(
        "--operator-timeout",
        type=int,
        help="Optional operator adapter timeout in seconds for an analysis next step.",
    )
    profile_next.add_argument(
        "--operator-max-retries",
        type=int,
        default=0,
        help="Retry malformed or invalid operator output up to this many times.",
    )
    profile_next.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema for prepared operator prompts.",
    )
    profile_next.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    discover_sources = subcommands.add_parser(
        "discover-sources",
        help="Find local Hermes/OpenClaw source stores and print import-ready commands.",
    )
    _add_db_argument(discover_sources)
    discover_sources.add_argument(
        "--home",
        type=Path,
        help="Home directory to inspect. Defaults to the current user's home.",
    )
    discover_sources.add_argument("--profile-id", help="Profile id to include in generated import commands.")
    discover_sources.add_argument("--profile-name", help="Profile name to include in generated import commands.")
    discover_sources.add_argument(
        "--root-path",
        type=Path,
        help="Workspace/root path to include in generated import commands.",
    )
    discover_sources.add_argument(
        "--include-missing",
        action="store_true",
        help="Include default candidate paths even when they do not exist.",
    )
    discover_sources.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    import_discovered = subcommands.add_parser(
        "import-discovered-source",
        help="Import one local Hermes/OpenClaw source candidate returned by discover-sources.",
    )
    _add_db_argument(import_discovered)
    import_discovered.add_argument("candidate_id", help="Candidate id from discover-sources, such as hermes_default.")
    import_discovered.add_argument(
        "--home",
        type=Path,
        help="Home directory to inspect. Defaults to the current user's home.",
    )
    import_discovered.add_argument("--profile-id", help="Profile id for the imported source.")
    import_discovered.add_argument("--profile-name", help="Profile name for the imported source.")
    import_discovered.add_argument("--root-path", type=Path, help="Workspace/root path for the imported source.")
    import_discovered.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory to write normalized Kyoko source-event JSON.",
    )
    import_discovered.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    ingest_fixture = subcommands.add_parser(
        "ingest-fixture",
        help="Ingest a Kyoko source fixture into the local database.",
    )
    _add_db_argument(ingest_fixture)
    ingest_fixture.add_argument(
        "fixture",
        type=Path,
        help="Path to a source fixture JSON file.",
    )

    ingest = subcommands.add_parser(
        "ingest",
        help="Ingest canonical Kyoko source-event JSON from a framework or adapter.",
    )
    _add_db_argument(ingest)
    ingest.add_argument(
        "payload",
        type=Path,
        help="Path to a canonical source-event JSON payload.",
    )
    ingest.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    ingest_otlp = subcommands.add_parser(
        "ingest-otlp",
        help="Normalize and ingest OTLP/GenAI JSON into canonical Kyoko source events.",
    )
    _add_db_argument(ingest_otlp)
    ingest_otlp.add_argument(
        "payload",
        type=Path,
        help="Path to an OTLP trace payload (JSON, or binary protobuf — auto-detected).",
    )
    ingest_otlp.add_argument(
        "--protobuf",
        action="store_true",
        help="Force decoding the payload as binary OTLP protobuf (default: auto-detect).",
    )
    ingest_otlp.add_argument(
        "--profile-id",
        required=True,
        help="Kyoko profile id to import into.",
    )
    ingest_otlp.add_argument(
        "--profile-name",
        help="Human-readable Kyoko profile name. Defaults to --profile-id.",
    )
    ingest_otlp.add_argument(
        "--root-path",
        default=".",
        help="Workspace/root path for the imported profile.",
    )
    ingest_otlp.add_argument(
        "--source-kind",
        default="otlp_http",
        choices=[
            "otlp_http",
            "ai_sdk",
            "pydantic_ai",
            "openai_agents",
            "langgraph",
            "crewai",
            "unknown",
        ],
        help="Canonical Kyoko source kind for the import.",
    )
    ingest_otlp.add_argument(
        "--source-name",
        default="OpenTelemetry",
        help="Display name for the imported source.",
    )
    ingest_otlp.add_argument(
        "--output",
        type=Path,
        help="Optional path to write normalized Kyoko source-event JSON.",
    )
    ingest_otlp.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    ingest_live = subcommands.add_parser(
        "ingest-live",
        help="Ingest live events (token/tool/status) from a JSON file or stdin.",
    )
    _add_db_argument(ingest_live)
    ingest_live.add_argument(
        "payload",
        type=Path,
        nargs="?",
        help="JSON file with an 'events' list, a bare list, or one event object. "
        "Reads stdin when omitted.",
    )
    ingest_live.add_argument(
        "--profile-id",
        help="Default profile id for events that do not specify one.",
    )
    ingest_live.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    live_tail = subcommands.add_parser(
        "live-tail",
        help="Read recorded live events for a run (Workshop-style live tail).",
    )
    _add_db_argument(live_tail)
    live_tail.add_argument(
        "run_id",
        nargs="?",
        help="Run id to tail. Omit to list across runs.",
    )
    live_tail.add_argument("--profile-id", help="Restrict to a profile.")
    live_tail.add_argument(
        "--after-seq",
        type=int,
        help="Only return events with seq greater than this value.",
    )
    live_tail.add_argument(
        "--kinds",
        help="Comma-separated kinds filter (e.g. token,tool_start,tool_result).",
    )
    live_tail.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of events to return.",
    )
    live_tail.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    mcp_log = subcommands.add_parser(
        "mcp-log",
        help="Show recorded MCP JSON-RPC traffic between coding agents and Kyoko.",
    )
    _add_db_argument(mcp_log)
    mcp_log.add_argument("--session-id", help="Restrict to one MCP session.")
    mcp_log.add_argument("--tool-name", help="Restrict to one tool name.")
    mcp_log.add_argument(
        "--after-seq",
        type=int,
        help="Only return entries with seq greater than this value.",
    )
    mcp_log.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of entries to return.",
    )
    mcp_log.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    current_run = subcommands.add_parser(
        "current-run",
        help="Show the most recently active run (the one you most likely just produced).",
    )
    _add_db_argument(current_run)
    current_run.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    run_outline = subcommands.add_parser(
        "run-outline",
        help="Show a run's structural outline (span tree, counts) without full payloads.",
    )
    _add_db_argument(run_outline)
    run_outline.add_argument("run_id", help="Run id to outline.")
    run_outline.add_argument(
        "--preview-chars", type=int, default=200, help="Per-span payload preview length."
    )
    run_outline.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    search_run_cmd = subcommands.add_parser(
        "search-run",
        help="Search a run's spans, attributes, payload previews, and live events.",
    )
    _add_db_argument(search_run_cmd)
    search_run_cmd.add_argument("run_id", help="Run id to search.")
    search_run_cmd.add_argument("pattern", help="Substring (or regex with --regex) to find.")
    search_run_cmd.add_argument("--regex", action="store_true", help="Treat pattern as a regex.")
    search_run_cmd.add_argument(
        "--case-sensitive", action="store_true", help="Match case-sensitively."
    )
    search_run_cmd.add_argument(
        "--scope", help="Comma-separated scopes (name,attributes,payload,live_events)."
    )
    search_run_cmd.add_argument("--max-matches", type=int, default=50, help="Max matches.")
    search_run_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    span_context = subcommands.add_parser(
        "span-context",
        help="Show neighbour span skeletons around a span.",
    )
    _add_db_argument(span_context)
    span_context.add_argument("span_id", help="Span id.")
    span_context.add_argument("--before", type=int, default=2, help="Spans before.")
    span_context.add_argument("--after", type=int, default=2, help="Spans after.")
    span_context.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    span_payload = subcommands.add_parser(
        "span-payload",
        help="Show a span's input/output payload (redacted), with optional path and slicing.",
    )
    _add_db_argument(span_payload)
    span_payload.add_argument("span_id", help="Span id.")
    span_payload.add_argument(
        "--target", choices=["input", "output"], default="input", help="Which payload."
    )
    span_payload.add_argument("--path", help="JSON path (e.g. messages.0.content).")
    span_payload.add_argument("--max-chars", type=int, default=4000, help="Max characters.")
    span_payload.add_argument("--offset", type=int, default=0, help="Start character offset.")
    span_payload.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    annotate = subcommands.add_parser(
        "annotate",
        help="Attach a durable annotation (issue|good|note) to a run or span.",
    )
    _add_db_argument(annotate)
    annotate.add_argument("kind", choices=["issue", "good", "note"], help="Annotation kind.")
    annotate.add_argument("--run-id", help="Run id to annotate.")
    annotate.add_argument("--span-id", help="Span id to annotate.")
    annotate.add_argument("--note", help="Free-text note.")
    annotate.add_argument("--source", default="user", help="Annotation source (default: user).")
    annotate.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    annotations_cmd = subcommands.add_parser(
        "annotations",
        help="List annotations, optionally filtered by run or span.",
    )
    _add_db_argument(annotations_cmd)
    annotations_cmd.add_argument("--run-id", help="Filter by run id.")
    annotations_cmd.add_argument("--span-id", help="Filter by span id.")
    annotations_cmd.add_argument("--limit", type=int, default=200, help="Max entries.")
    annotations_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    issues_cmd = subcommands.add_parser(
        "issues",
        help="List first-class issues, optionally filtered by status or section.",
    )
    _add_db_argument(issues_cmd)
    issues_cmd.add_argument(
        "--status", choices=["open", "resolved", "dismissed"], help="Filter by status."
    )
    issues_cmd.add_argument(
        "--section", choices=["context", "harness"], help="Filter by section."
    )
    issues_cmd.add_argument("--limit", type=int, default=200, help="Max entries.")
    issues_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    issue_detail = subcommands.add_parser(
        "issue-detail",
        help="Show one issue with resolved evidence, affected entities, and linked proposals.",
    )
    _add_db_argument(issue_detail)
    issue_detail.add_argument("issue_id", help="Issue id to inspect.")
    issue_detail.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    issue_create = subcommands.add_parser(
        "issue-create",
        help="Create a first-class issue (evidence only; never changes agent behavior).",
    )
    _add_db_argument(issue_create)
    issue_create.add_argument("title", help="Issue title.")
    issue_create.add_argument("--body", help="Issue body / details.")
    issue_create.add_argument(
        "--section", choices=["context", "harness"], help="Issue section."
    )
    issue_create.add_argument("--category", help="Free-text category.")
    issue_create.add_argument(
        "--severity", choices=["low", "medium", "high"], help="Issue severity."
    )
    issue_create.add_argument(
        "--proposal-id",
        dest="proposal_ids",
        action="append",
        default=[],
        help="Backlink to a proposal that addresses this issue (repeatable).",
    )
    issue_create.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    issue_status = subcommands.add_parser(
        "issue-status",
        help="Set an issue's triage status (evidence only; never changes agent behavior).",
    )
    _add_db_argument(issue_status)
    issue_status.add_argument("issue_id", help="Issue id to update.")
    issue_status.add_argument(
        "status", choices=["open", "resolved", "dismissed"], help="New triage status."
    )
    issue_status.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    issue_comment = subcommands.add_parser(
        "issue-comment",
        help="Set an issue's review comment (evidence only; never changes agent behavior).",
    )
    _add_db_argument(issue_comment)
    issue_comment.add_argument("issue_id", help="Issue id to comment on.")
    issue_comment.add_argument(
        "comment", help="Review comment text (empty string clears it)."
    )
    issue_comment.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    # --- measurement plane: `eval` (deterministic Python detectors) ---------
    evals_cmd = subcommands.add_parser(
        "evals",
        help="List registered + bundled `eval` detectors (evidence-only measurements).",
    )
    _add_db_argument(evals_cmd)
    evals_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    eval_detail = subcommands.add_parser(
        "eval-detail",
        help="Show one detector's contract and problem statement.",
    )
    _add_db_argument(eval_detail)
    eval_detail.add_argument("detector_id", help="Detector id to inspect.")
    eval_detail.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    eval_register = subcommands.add_parser(
        "eval-register",
        help="Register a user detector .py (stored in the blob store; evidence only).",
    )
    _add_db_argument(eval_register)
    eval_register.add_argument("path", type=Path, help="Path to a detector .py defining detect().")
    eval_register.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    run_eval = subcommands.add_parser(
        "run-eval",
        help="Run a detector over a corpus of run traces (evidence only).",
    )
    _add_db_argument(run_eval)
    run_eval.add_argument("detector_id", help="Detector id to run.")
    run_eval.add_argument(
        "--corpus",
        help="Corpus selector as a JSON file path or inline JSON "
        '(e.g. \'{"unit":"event","limit":100}\'). Defaults to all runs.',
    )
    run_eval.add_argument(
        "--persist",
        action="store_true",
        help="Record the run + per-event results (default: ephemeral).",
    )
    run_eval.add_argument(
        "--raise-issues",
        action="store_true",
        help="Raise a first-class Issue when the problem level exceeds --threshold (implies --persist; evidence only).",
    )
    run_eval.add_argument(
        "--threshold", type=float, help="Manual problem-level threshold (0-1) for --raise-issues."
    )
    run_eval.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    eval_compare = subcommands.add_parser(
        "eval-compare",
        help="Before/after delta between two detector measurement runs of the same detector.",
    )
    _add_db_argument(eval_compare)
    eval_compare.add_argument("baseline_run_id", help="Baseline measurement run id.")
    eval_compare.add_argument("compare_run_id", help="Comparison measurement run id.")
    eval_compare.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    eval_runs = subcommands.add_parser(
        "eval-runs",
        help="List persisted detector measurement runs (history).",
    )
    _add_db_argument(eval_runs)
    eval_runs.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    eval_run_detail = subcommands.add_parser(
        "eval-run-detail",
        help="Show one measurement run with its per-event results and aggregate.",
    )
    _add_db_argument(eval_run_detail)
    eval_run_detail.add_argument("eval_run_id", help="Measurement run id to inspect.")
    eval_run_detail.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    # --- measurement plane: `llm_eval` (LLM-as-judge templates) ------------
    llm_evals_cmd = subcommands.add_parser(
        "llm-evals",
        help="List the bundled `llm_eval` judge templates (evidence-only measurements).",
    )
    _add_db_argument(llm_evals_cmd)
    llm_evals_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    llm_eval_detail = subcommands.add_parser(
        "llm-eval-detail",
        help="Show one judge template (prompt, vars, bindings, output).",
    )
    _add_db_argument(llm_eval_detail)
    llm_eval_detail.add_argument("llm_eval_id", help="Template id to inspect.")
    llm_eval_detail.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    run_llm_eval_cmd = subcommands.add_parser(
        "run-llm-eval",
        help="Run a judge template over a corpus via an external --command (model outside core).",
    )
    _add_db_argument(run_llm_eval_cmd)
    run_llm_eval_cmd.add_argument("llm_eval_id", help="Template id to run.")
    run_llm_eval_cmd.add_argument(
        "--corpus",
        help="Corpus selector as a JSON file path or inline JSON. Defaults to the template unit.",
    )
    run_llm_eval_cmd.add_argument(
        "--command",
        dest="judge_command",
        help="Judge command (BYO model CLI); required unless --prepare-only.",
    )
    run_llm_eval_cmd.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write per-unit redacted requests + a handoff and stop (no model call).",
    )
    run_llm_eval_cmd.add_argument(
        "--output-dir", type=Path, help="Directory for --prepare-only request artifacts."
    )
    run_llm_eval_cmd.add_argument(
        "--persist", action="store_true", help="Record the run + per-unit results."
    )
    run_llm_eval_cmd.add_argument(
        "--raise-issues",
        action="store_true",
        help="Raise a first-class Issue when the problem level exceeds --threshold (implies --persist; evidence only).",
    )
    run_llm_eval_cmd.add_argument(
        "--threshold", type=float, help="Manual problem-level threshold (0-1) for --raise-issues."
    )
    run_llm_eval_cmd.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    llm_eval_compare = subcommands.add_parser(
        "llm-eval-compare",
        help="Before/after delta between two judge measurement runs of the same template.",
    )
    _add_db_argument(llm_eval_compare)
    llm_eval_compare.add_argument("baseline_run_id", help="Baseline measurement run id.")
    llm_eval_compare.add_argument("compare_run_id", help="Comparison measurement run id.")
    llm_eval_compare.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    llm_eval_runs = subcommands.add_parser(
        "llm-eval-runs",
        help="List persisted judge measurement runs (history).",
    )
    _add_db_argument(llm_eval_runs)
    llm_eval_runs.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    llm_eval_run_detail = subcommands.add_parser(
        "llm-eval-run-detail",
        help="Show one judge measurement run with per-unit scores and aggregate.",
    )
    _add_db_argument(llm_eval_run_detail)
    llm_eval_run_detail.add_argument("eval_run_id", help="Measurement run id to inspect.")
    llm_eval_run_detail.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    import_hermes = subcommands.add_parser(
        "import-hermes-kanban",
        help="Import a Hermes Kanban SQLite board into Kyoko canonical source events.",
    )
    _add_db_argument(import_hermes)
    import_hermes.add_argument(
        "kanban_db",
        type=Path,
        help="Path to a Hermes kanban.db file.",
    )
    import_hermes.add_argument(
        "--profile-id",
        help="Kyoko profile id. Defaults to profile_hermes_<board>.",
    )
    import_hermes.add_argument(
        "--profile-name",
        help="Kyoko profile name. Defaults to 'Hermes <board> Kanban'.",
    )
    import_hermes.add_argument(
        "--root-path",
        type=Path,
        help="Workspace/root path for the imported profile. Defaults to the kanban DB parent.",
    )
    import_hermes.add_argument(
        "--board",
        default="default",
        help="Hermes board slug used for Kyoko source and queue identity.",
    )
    import_hermes.add_argument(
        "--output",
        type=Path,
        help="Optional path to write normalized Kyoko source-event JSON.",
    )
    import_hermes.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    import_openclaw = subcommands.add_parser(
        "import-openclaw-sessions",
        help="Import OpenClaw session JSONL transcripts into Kyoko canonical source events.",
    )
    _add_db_argument(import_openclaw)
    import_openclaw.add_argument(
        "session_path",
        type=Path,
        help="Path to an OpenClaw sessions directory, sessions.json file, or JSONL transcript.",
    )
    import_openclaw.add_argument(
        "--agent-id",
        help="OpenClaw agent id. Defaults to the id inferred from ~/.openclaw/agents/<id>/sessions or main.",
    )
    import_openclaw.add_argument(
        "--session-key",
        help="Optional sessions.json key or JSONL stem to import only one session.",
    )
    import_openclaw.add_argument(
        "--profile-id",
        help="Kyoko profile id. Defaults to profile_openclaw_<agent>.",
    )
    import_openclaw.add_argument(
        "--profile-name",
        help="Kyoko profile name. Defaults to 'OpenClaw <agent> Sessions'.",
    )
    import_openclaw.add_argument(
        "--root-path",
        type=Path,
        help="Workspace/root path for the imported profile. Defaults to session workspace metadata or the session path.",
    )
    import_openclaw.add_argument(
        "--output",
        type=Path,
        help="Optional path to write normalized Kyoko source-event JSON.",
    )
    import_openclaw.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    status = subcommands.add_parser(
        "status",
        help="Show local Kyoko database status.",
    )
    _add_db_argument(status)
    status.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    dashboard_metrics = subcommands.add_parser(
        "dashboard-metrics",
        help="Show product-loop dashboard metrics for a workflow profile.",
    )
    _add_db_argument(dashboard_metrics)
    dashboard_metrics.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    dashboard_metrics.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    storage_report_parser = subcommands.add_parser(
        "storage-report",
        help="Show local database and payload blob storage status.",
    )
    _add_db_argument(storage_report_parser)
    storage_report_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    prune_retention = subcommands.add_parser(
        "prune-retention",
        help="Dry-run or apply relational retention pruning for traces, replay/check, and operator runs.",
    )
    _add_db_argument(prune_retention)
    prune_retention.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    prune_retention.add_argument("--trace-older-than-days", type=int, help="Trace retention cutoff in days.")
    prune_retention.add_argument("--replay-older-than-days", type=int, help="Replay/check retention cutoff in days.")
    prune_retention.add_argument("--operator-older-than-days", type=int, help="Operator-run retention cutoff in days.")
    prune_retention.add_argument(
        "--apply",
        action="store_true",
        help="Delete eligible relational rows. Defaults to dry-run.",
    )
    prune_retention.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    wal_checkpoint = subcommands.add_parser(
        "wal-checkpoint",
        help="Run a SQLite WAL checkpoint for the local Kyoko database.",
    )
    _add_db_argument(wal_checkpoint)
    wal_checkpoint.add_argument(
        "--mode",
        choices=["PASSIVE", "FULL", "RESTART", "TRUNCATE"],
        default="PASSIVE",
        help="SQLite checkpoint mode. Use TRUNCATE to reclaim the WAL file when safe.",
    )
    wal_checkpoint.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    load_smoke = subcommands.add_parser(
        "load-smoke",
        help="Run a timed local load smoke against UI-style read paths.",
    )
    _add_db_argument(load_smoke)
    load_smoke.add_argument(
        "--use-db",
        action="store_true",
        help="Use --db and seed a load-smoke profile there. Defaults to a temporary database.",
    )
    load_smoke.add_argument(
        "--profile-id",
        default="profile_load_smoke",
        help="Profile id used for generated load-smoke data.",
    )
    load_smoke.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUN_COUNT,
        help="Number of generated runs to seed.",
    )
    load_smoke.add_argument(
        "--spans-per-run",
        type=int,
        default=DEFAULT_SPANS_PER_RUN,
        help="Number of generated spans per run.",
    )
    load_smoke.add_argument(
        "--read-workers",
        type=int,
        default=DEFAULT_READ_WORKERS,
        help="Number of concurrent UI-read workers.",
    )
    load_smoke.add_argument(
        "--read-iterations",
        type=int,
        default=DEFAULT_READ_ITERATIONS,
        help="Number of read iterations per worker.",
    )
    load_smoke.add_argument(
        "--expired-blobs",
        type=int,
        default=DEFAULT_EXPIRED_BLOB_COUNT,
        help="Number of expired payload blobs to create for retention dry-run timing.",
    )
    load_smoke.add_argument(
        "--checkpoint-mode",
        choices=["PASSIVE", "FULL", "RESTART", "TRUNCATE"],
        default="PASSIVE",
        help="WAL checkpoint mode to run after concurrent reads.",
    )
    load_smoke.add_argument(
        "--max-p95-ms",
        type=float,
        help="Optional failure threshold for overall p95 read latency.",
    )
    load_smoke.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    blobs = subcommands.add_parser(
        "blobs",
        help="List registered payload blobs.",
    )
    _add_db_argument(blobs)
    blobs.add_argument("--profile-id", help="Only list blobs for one profile.")
    blobs.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    blob_put = subcommands.add_parser(
        "blob-put",
        help="Store a file in Kyoko's content-addressed payload blob store.",
    )
    _add_db_argument(blob_put)
    blob_put.add_argument("path", type=Path, help="File to store.")
    blob_put.add_argument("--profile-id", help="Optional owning profile id.")
    blob_put.add_argument("--kind", default="payload", help="Blob kind label.")
    blob_put.add_argument(
        "--media-type",
        default="application/octet-stream",
        help="Blob media type.",
    )
    blob_put.add_argument(
        "--retention-days",
        type=int,
        help="Optional days before this blob becomes eligible for prune.",
    )
    blob_put.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    prune = subcommands.add_parser(
        "prune",
        help="Dry-run or apply local payload blob pruning.",
    )
    _add_db_argument(prune)
    prune.add_argument("--profile-id", help="Only prune blobs for one profile.")
    prune.add_argument(
        "--older-than-days",
        type=int,
        help="Also prune blobs created at least this many days ago.",
    )
    prune.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete eligible blob files and registry rows. Defaults to dry-run.",
    )
    prune.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    runs = subcommands.add_parser(
        "runs",
        help="List recent runs for the active profile.",
    )
    _add_db_argument(runs)
    runs.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    runs.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of runs to return.",
    )
    runs.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    run_detail = subcommands.add_parser(
        "run-detail",
        help="Show spans, handoffs, task context, timeline, and linked proposals for a run.",
    )
    _add_db_argument(run_detail)
    run_detail.add_argument("run_id", help="Run id to inspect.")
    run_detail.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    policy = subcommands.add_parser(
        "policy",
        help="Show the active autonomy policy for a profile.",
    )
    _add_db_argument(policy)
    policy.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    policy.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    policy_set = subcommands.add_parser(
        "policy-set",
        help="Update context/harness autonomy policy settings.",
    )
    _add_db_argument(policy_set)
    policy_set.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    policy_set.add_argument(
        "--context-mode",
        choices=["off", "propose", "autonomous"],
        help="Context autonomy mode.",
    )
    policy_set.add_argument(
        "--harness-mode",
        choices=["off", "propose", "autonomous"],
        help="Harness autonomy mode.",
    )
    policy_set.add_argument(
        "--repo-patch",
        choices=["on", "off"],
        help="Allow generated harness file writes through apply-harness.",
    )
    policy_set.add_argument(
        "--check-write",
        choices=["on", "off"],
        help="Allow Kyoko check spec writes.",
    )
    policy_set.add_argument(
        "--skillbook-write",
        choices=["on", "off"],
        help="Allow Kyoko skillbook/context writes.",
    )
    policy_set.add_argument(
        "--profile-config-write",
        choices=["on", "off"],
        help="Allow Kyoko profile config writes.",
    )
    policy_set.add_argument(
        "--replay-server-patch",
        choices=["on", "off"],
        help="Allow replay server patch writes.",
    )
    policy_set.add_argument(
        "--dirty-worktree-policy",
        choices=["block", "allow_touched_only", "allow"],
        help="Dirty worktree behavior for harness apply.",
    )
    policy_set.add_argument(
        "--required-check-level-context",
        choices=["L0_generated", "L1_repeated", "L2_regression", "L3_human_approved"],
        help="Minimum check trust level required for context autonomy.",
    )
    policy_set.add_argument(
        "--required-check-level-harness",
        choices=["L0_generated", "L1_repeated", "L2_regression", "L3_human_approved"],
        help="Minimum check trust level required for harness autonomy.",
    )
    policy_set.add_argument(
        "--rollback-on-regression",
        choices=["on", "off"],
        help="Roll back autonomous harness writes when replay regresses.",
    )
    policy_set.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    run_autonomy_parser = subcommands.add_parser(
        "run-autonomy",
        help="Evaluate proposal gates and apply eligible autonomous changes.",
    )
    _add_db_argument(run_autonomy_parser)
    run_autonomy_parser.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    run_autonomy_parser.add_argument(
        "--harness-workspace-root",
        type=Path,
        help="Workspace root for eligible autonomous harness patch application.",
    )
    run_autonomy_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    autonomy_events = subcommands.add_parser(
        "autonomy-events",
        help="List recent autonomy timeline events.",
    )
    _add_db_argument(autonomy_events)
    autonomy_events.add_argument("--profile-id", help="Optional profile id to filter events.")
    autonomy_events.add_argument(
        "--kind",
        choices=AUTONOMY_EVENT_KINDS,
        help="Optional autonomy event kind to filter.",
    )
    autonomy_events.add_argument(
        "--entity-type",
        help="Optional timeline entity type filter, for example learning_proposal.",
    )
    autonomy_events.add_argument(
        "--entity-id",
        help="Optional exact timeline entity id filter, for example a proposal id.",
    )
    autonomy_events.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum events to return, clamped to 1..200.",
    )
    autonomy_events.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    propose = subcommands.add_parser(
        "propose",
        help="Validate and persist a LearningProposal JSON file.",
    )
    _add_db_argument(propose)
    propose.add_argument(
        "proposal",
        type=Path,
        help="Path to a LearningProposal JSON file.",
    )
    propose.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    propose.add_argument(
        "--strict-schema",
        action="store_true",
        help="Fail if jsonschema is not installed or the schema is unavailable.",
    )

    proposals = subcommands.add_parser(
        "proposals",
        help="List persisted LearningProposal records.",
    )
    _add_db_argument(proposals)
    proposals.add_argument("--profile-id", help="Optional profile id to filter proposals.")
    proposals.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    proposal_detail = subcommands.add_parser(
        "proposal-detail",
        help="Show evidence, check, replay, patch, timeline, and autonomy detail for a proposal.",
    )
    _add_db_argument(proposal_detail)
    proposal_detail.add_argument("proposal_id", help="LearningProposal id to inspect.")
    proposal_detail.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    apply = subcommands.add_parser(
        "apply",
        help="Apply a validated context LearningProposal into the skillbook.",
    )
    _add_db_argument(apply)
    apply.add_argument(
        "proposal_id",
        help="LearningProposal id to apply.",
    )

    prepare_harness = subcommands.add_parser(
        "prepare-harness",
        help="Prepare a reviewable harness patch transaction from a harness proposal.",
    )
    _add_db_argument(prepare_harness)
    prepare_harness.add_argument(
        "proposal_id",
        help="Harness LearningProposal id to prepare.",
    )
    prepare_harness.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    harness_patches = subcommands.add_parser(
        "harness-patches",
        help="List prepared harness patch transactions.",
    )
    _add_db_argument(harness_patches)
    harness_patches.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    harness_target_locks = subcommands.add_parser(
        "harness-target-locks",
        help="List human locks for harness target paths.",
    )
    _add_db_argument(harness_target_locks)
    harness_target_locks.add_argument("--profile-id", help="Optional profile id filter.")
    harness_target_locks.add_argument(
        "--include-unlocked",
        action="store_true",
        help="Include previously unlocked target paths.",
    )
    harness_target_locks.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    harness_target_lock = subcommands.add_parser(
        "harness-target-lock",
        help="Mark a harness target path as human-locked.",
    )
    _add_db_argument(harness_target_lock)
    harness_target_lock.add_argument("target_path", help="Harness target path to lock.")
    harness_target_lock.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    harness_target_lock.add_argument("--reason", help="Optional human-readable lock reason.")
    harness_target_lock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the lock event to.",
    )
    harness_target_lock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    harness_target_unlock = subcommands.add_parser(
        "harness-target-unlock",
        help="Remove the human lock from a harness target path.",
    )
    _add_db_argument(harness_target_unlock)
    harness_target_unlock.add_argument("target_path", help="Harness target path to unlock.")
    harness_target_unlock.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    harness_target_unlock.add_argument("--reason", help="Optional human-readable unlock reason.")
    harness_target_unlock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the unlock event to.",
    )
    harness_target_unlock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    apply_harness = subcommands.add_parser(
        "apply-harness",
        help="Apply a generated-file harness patch transaction to an explicit workspace root.",
    )
    _add_db_argument(apply_harness)
    apply_harness.add_argument("patch_transaction_id", help="Patch transaction id to apply.")
    apply_harness.add_argument(
        "--workspace-root",
        type=Path,
        required=True,
        help="Workspace root where generated files may be written.",
    )
    apply_harness.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    rollback_harness = subcommands.add_parser(
        "rollback-harness",
        help="Rollback an applied generated-file harness patch transaction.",
    )
    _add_db_argument(rollback_harness)
    rollback_harness.add_argument("patch_transaction_id", help="Patch transaction id to rollback.")
    rollback_harness.add_argument(
        "--workspace-root",
        type=Path,
        required=True,
        help="Workspace root used when the patch transaction was applied.",
    )
    rollback_harness.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    skills = subcommands.add_parser(
        "skills",
        help="List ACE-compatible skillbook entries.",
    )
    _add_db_argument(skills)
    skills.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    skill_revisions = subcommands.add_parser(
        "skill-revisions",
        help="List skillbook write revisions.",
    )
    _add_db_argument(skill_revisions)
    skill_revisions.add_argument(
        "--skill-id",
        help="Optional skill id filter.",
    )
    skill_revisions.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    skill_rollback = subcommands.add_parser(
        "skill-rollback",
        help="Rollback the latest skill revision.",
    )
    _add_db_argument(skill_rollback)
    skill_rollback.add_argument("revision_id", help="Skill revision id to rollback.")
    skill_rollback.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    context_rules = subcommands.add_parser(
        "context-rules",
        help="List active context delivery rules.",
    )
    _add_db_argument(context_rules)
    context_rules.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive delivery rules.",
    )
    context_rules.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    context_rule_revisions = subcommands.add_parser(
        "context-rule-revisions",
        help="List context delivery rule write revisions.",
    )
    _add_db_argument(context_rule_revisions)
    context_rule_revisions.add_argument(
        "--rule-id",
        help="Optional context delivery rule id filter.",
    )
    context_rule_revisions.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    context_rule_rollback = subcommands.add_parser(
        "context-rule-rollback",
        help="Rollback the latest context delivery rule revision.",
    )
    _add_db_argument(context_rule_rollback)
    context_rule_rollback.add_argument(
        "revision_id",
        help="Context delivery rule revision id to rollback.",
    )
    context_rule_rollback.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    context_rule_lock = subcommands.add_parser(
        "context-rule-lock",
        help="Mark a context delivery rule as human-locked.",
    )
    _add_db_argument(context_rule_lock)
    context_rule_lock.add_argument("rule_id", help="Context delivery rule id to lock.")
    context_rule_lock.add_argument("--reason", help="Optional human-readable lock reason.")
    context_rule_lock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the lock event to.",
    )
    context_rule_lock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    context_rule_unlock = subcommands.add_parser(
        "context-rule-unlock",
        help="Remove the human lock from a context delivery rule.",
    )
    _add_db_argument(context_rule_unlock)
    context_rule_unlock.add_argument("rule_id", help="Context delivery rule id to unlock.")
    context_rule_unlock.add_argument("--reason", help="Optional human-readable unlock reason.")
    context_rule_unlock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the unlock event to.",
    )
    context_rule_unlock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    skill_lock = subcommands.add_parser(
        "skill-lock",
        help="Mark an applied skill as human-locked.",
    )
    _add_db_argument(skill_lock)
    skill_lock.add_argument("skill_id", help="Skill id to lock.")
    skill_lock.add_argument("--reason", help="Optional human-readable lock reason.")
    skill_lock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the lock event to.",
    )
    skill_lock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    skill_unlock = subcommands.add_parser(
        "skill-unlock",
        help="Remove the human lock from an applied skill.",
    )
    _add_db_argument(skill_unlock)
    skill_unlock.add_argument("skill_id", help="Skill id to unlock.")
    skill_unlock.add_argument("--reason", help="Optional human-readable unlock reason.")
    skill_unlock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the unlock event to.",
    )
    skill_unlock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    context = subcommands.add_parser(
        "context",
        help="Render active skillbook context for an agent prompt.",
    )
    _add_db_argument(context)
    context.add_argument(
        "--section",
        choices=["context", "harness", "all"],
        default="context",
        help="Skill section to render.",
    )
    context.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive skills.",
    )
    context.add_argument(
        "--profile-id",
        help="Optional profile id. If omitted, Kyoko infers it from the target when possible.",
    )
    context.add_argument(
        "--target-type",
        help="Optional target entity type for scoped context delivery.",
    )
    context.add_argument(
        "--target-id",
        help="Optional target entity id for scoped context delivery.",
    )

    export_skillbook_parser = subcommands.add_parser(
        "export-skillbook",
        help="Export active skills as ACE Skillbook v2 JSON or prompt text.",
    )
    _add_db_argument(export_skillbook_parser)
    export_skillbook_parser.add_argument(
        "--format",
        choices=["json", "prompt"],
        default="json",
        help="Export format.",
    )
    export_skillbook_parser.add_argument(
        "--section",
        choices=["context", "harness", "all"],
        default="all",
        help="Skill section to export.",
    )
    export_skillbook_parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive skills.",
    )
    export_skillbook_parser.add_argument(
        "--profile-id",
        help="Optional profile id to export. Defaults to all profiles.",
    )
    export_skillbook_parser.add_argument(
        "--output",
        type=Path,
        help="Optional output path. Defaults to stdout.",
    )

    ace_compat = subcommands.add_parser(
        "ace-compat",
        help="Check whether the current Skillbook export loads through ACE's public Skillbook API.",
    )
    _add_db_argument(ace_compat)
    ace_compat.add_argument(
        "--ace-path",
        type=Path,
        help="Optional local agentic-context-engine checkout or installed package root.",
    )
    ace_compat.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive Kyoko skills in the exported compatibility check.",
    )
    ace_compat.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    ace_diff = subcommands.add_parser(
        "ace-diff-proposals",
        help="Convert a cloned ACE Skillbook before/after diff into Kyoko LearningProposals.",
    )
    _add_db_argument(ace_diff)
    ace_diff.add_argument("--before", type=Path, required=True, help="ACE Skillbook v2 JSON before ACE mutation.")
    ace_diff.add_argument("--after", type=Path, required=True, help="ACE Skillbook v2 JSON after ACE mutation.")
    ace_diff.add_argument("--profile-id", help="Kyoko profile id. Defaults to the first profile.")
    ace_diff.add_argument(
        "--evidence-run-id",
        help="Fallback Kyoko run id to use if ACE occurrences cannot be resolved.",
    )
    ace_diff.add_argument(
        "--evidence-span-id",
        help="Fallback Kyoko span id to use if ACE occurrences cannot be resolved.",
    )
    ace_diff.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory where proposal JSON files should be written.",
    )
    ace_diff.add_argument(
        "--persist",
        action="store_true",
        help="Persist generated proposals into Kyoko after validation.",
    )
    ace_diff.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema used when --persist is set.",
    )
    ace_diff.add_argument(
        "--producer-name",
        default="native_ace",
        help="Producer name recorded on generated proposals.",
    )
    ace_diff.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    ace_native = subcommands.add_parser(
        "ace-native-run",
        help="Run an external native ACE command against a cloned Skillbook and import the diff.",
    )
    _add_db_argument(ace_native)
    ace_native.add_argument(
        "--command",
        dest="ace_command",
        required=True,
        help=(
            "External ACE command. Kyoko expands {before_path}, {after_path}, "
            "{output_dir}, {db_path}, {profile_id}, and {schema_path}; the same "
            "values are also provided through KYOKO_ACE_* environment variables."
        ),
    )
    ace_native.add_argument("--profile-id", help="Kyoko profile id. Defaults to the first profile.")
    ace_native.add_argument(
        "--evidence-run-id",
        help="Fallback Kyoko run id to use if ACE occurrences cannot be resolved.",
    )
    ace_native.add_argument(
        "--evidence-span-id",
        help="Fallback Kyoko span id to use if ACE occurrences cannot be resolved.",
    )
    ace_native.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for before/after Skillbook, command logs, and proposal artifacts.",
    )
    ace_native.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive Kyoko skills in the cloned Skillbook snapshot.",
    )
    ace_native.add_argument(
        "--persist",
        action="store_true",
        help="Persist generated proposals into Kyoko after validation.",
    )
    ace_native.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write the cloned Skillbook and command handoff without invoking the external ACE command.",
    )
    ace_native.add_argument(
        "--provider-backed",
        action="store_true",
        help="Mark the external ACE command as provider/model-backed in JSON reports and handoffs.",
    )
    ace_native.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema used when --persist is set.",
    )
    ace_native.add_argument(
        "--producer-name",
        default="native_ace",
        help="Producer name recorded on generated proposals.",
    )
    ace_native.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="External ACE command timeout in seconds.",
    )
    ace_native.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    ace_native_smoke = subcommands.add_parser(
        "ace-native-smoke",
        help="Run a deterministic installed ACE Skillbook smoke through ace-native-run.",
    )
    _add_db_argument(ace_native_smoke)
    ace_native_smoke.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for before/after Skillbook, ACE command logs, and proposal artifacts.",
    )
    ace_native_smoke.add_argument(
        "--persist",
        action="store_true",
        help="Persist the generated native_ace proposal into Kyoko after validation.",
    )
    ace_native_smoke.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema used when --persist is set.",
    )
    ace_native_smoke.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="External ACE smoke command timeout in seconds.",
    )
    ace_native_smoke.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    evidence = subcommands.add_parser(
        "evidence",
        help="Write an operator-facing evidence bundle from the local database.",
    )
    _add_db_argument(evidence)
    evidence.add_argument(
        "--profile-id",
        help="Profile id to include. Defaults to the first profile.",
    )
    evidence.add_argument(
        "--run-id",
        help="Optional run id to narrow the bundle.",
    )
    evidence.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output path for the evidence bundle JSON.",
    )

    operator_prompt = subcommands.add_parser(
        "operator-prompt",
        help="Write an evidence bundle and strict prompt for a local operator agent.",
    )
    _add_db_argument(operator_prompt)
    operator_prompt.add_argument(
        "--target",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        default="generic",
        help="Operator target label used for prompt guidance.",
    )
    operator_prompt.add_argument(
        "--profile-id",
        help="Profile id to analyze. Defaults to the first profile.",
    )
    operator_prompt.add_argument(
        "--run-id",
        help="Optional run id to analyze.",
    )
    operator_prompt.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where evidence and operator prompt artifacts are written.",
    )
    operator_prompt.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    operator_prompt.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    analyze = subcommands.add_parser(
        "analyze",
        help="Run an operator-agent analysis flow.",
    )
    _add_db_argument(analyze)
    analyze.add_argument(
        "--operator",
        default="mock",
        help=(
            "Operator agent to run. Use mock, command, adapter with "
            "--operator-adapter, or a registered adapter id such as codex."
        ),
    )
    analyze.add_argument(
        "--operator-adapter",
        help="Registered operator adapter id to use when --operator adapter is selected.",
    )
    analyze.add_argument(
        "--command",
        dest="operator_command",
        help="External operator command for --operator command. Receives KYOKO_EVIDENCE_PATH.",
    )
    analyze.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="External operator timeout in seconds.",
    )
    analyze.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Retry malformed or semantically invalid operator output this many times.",
    )
    analyze.add_argument(
        "--profile-id",
        help="Profile id to analyze. Defaults to the first profile.",
    )
    analyze.add_argument(
        "--run-id",
        help="Optional run id to analyze.",
    )
    analyze.add_argument(
        "--since",
        help=(
            "Only analyze traces newer than this ISO timestamp (scopes the evidence "
            "bundle to runs with started_at > SINCE). Ignored when --run-id is set."
        ),
    )
    analyze.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where evidence and proposal artifacts are written.",
    )
    analyze.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    analyze.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    improve = subcommands.add_parser(
        "improve",
        help="Run the agent-optimized improvement loop: analyze, generate checks, replay, and run autonomy.",
    )
    _add_db_argument(improve)
    improve.add_argument(
        "--proposal-id",
        help="Use an existing LearningProposal instead of running an operator.",
    )
    improve.add_argument(
        "--operator",
        default="mock",
        help=(
            "Operator agent to run when --proposal-id is omitted. Use mock, "
            "command, adapter, or a registered adapter id such as codex."
        ),
    )
    improve.add_argument(
        "--operator-adapter",
        help="Registered operator adapter id to use when --operator adapter is selected.",
    )
    improve.add_argument(
        "--command",
        dest="operator_command",
        help="External operator command for --operator command.",
    )
    improve.add_argument(
        "--operator-timeout",
        type=int,
        default=120,
        help="External operator timeout in seconds.",
    )
    improve.add_argument(
        "--operator-max-retries",
        type=int,
        default=0,
        help="Retry malformed or semantically invalid operator output this many times.",
    )
    improve.add_argument("--profile-id", help="Profile id to analyze.")
    improve.add_argument("--run-id", help="Optional run id to analyze.")
    improve.add_argument(
        "--source-candidate-id",
        help="Optional discover-sources candidate id to import before analysis.",
    )
    improve.add_argument(
        "--source-home",
        type=Path,
        help="Home directory to inspect when --source-candidate-id is used.",
    )
    improve.add_argument(
        "--source-import-output-dir",
        type=Path,
        help="Optional directory to write normalized source events for the pre-imported candidate.",
    )
    improve.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for operator/improve artifacts. Defaults under <db-parent>/.kyoko/improve-runs.",
    )
    improve.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    improve.add_argument(
        "--replay-adapter",
        help=(
            "Registered replay adapter id used to replay every check spec and run checks. "
            "Defaults to the latest enabled profile adapter."
        ),
    )
    improve.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Override replay artifact output directory.",
    )
    improve.add_argument(
        "--replay-timeout",
        type=int,
        help="Override replay adapter timeout in seconds.",
    )
    improve.add_argument(
        "--no-autonomy",
        action="store_true",
        help="Stop before running the policy-gated autonomy evaluator.",
    )
    improve.add_argument(
        "--harness-workspace-root",
        type=Path,
        help="Workspace root for eligible autonomous harness patch application.",
    )
    improve.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    analysis_run = subcommands.add_parser(
        "analysis-run",
        help="Run a dashboard-style analysis (ace/codex/claude/openclaw/hermes) through the gate.",
    )
    _add_db_argument(analysis_run)
    analysis_run.add_argument(
        "--analyzer",
        required=True,
        help="ace | codex | claude | openclaw | hermes (or mock/command for testing).",
    )
    analysis_run.add_argument("--adapter-id", help="Operator adapter id (defaults to the analyzer name).")
    analysis_run.add_argument(
        "--scope", choices=("all", "new", "run"), default="all", help="Trace scope to analyze."
    )
    analysis_run.add_argument("--run-id", help="Run id when --scope run.")
    analysis_run.add_argument("--since", help="Cutoff ISO timestamp when --scope new.")
    analysis_run.add_argument(
        "--refresh-import", action="store_true", help="Re-import from --source-path before analyzing."
    )
    analysis_run.add_argument("--source-kind", choices=("openclaw_sessions", "hermes_kanban"))
    analysis_run.add_argument("--source-path", help="Source path to re-import when --refresh-import.")
    analysis_run.add_argument(
        "--no-autonomy", action="store_true", help="Stop before the policy-gated autonomy evaluator."
    )
    analysis_run.add_argument(
        "--ace-command", help="External ACE command (required when --analyzer ace), e.g. 'ace run'."
    )
    analysis_run.add_argument("--command", dest="operator_command", help="Command for --analyzer command.")
    analysis_run.add_argument("--timeout", type=int, default=120, help="External operator timeout (seconds).")
    analysis_run.add_argument("--max-retries", type=int, default=0, help="Retry invalid operator output N times.")
    analysis_run.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    analysis_run.add_argument("--output-dir", type=Path, help="Artifact output directory.")
    analysis_run.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    analysis_schedule_add = subcommands.add_parser(
        "analysis-schedule-add",
        help="Create a recurring openclaw/hermes analysis schedule (fires while `kyoko serve` runs).",
    )
    _add_db_argument(analysis_schedule_add)
    analysis_schedule_add.add_argument(
        "--analyzer", required=True, choices=tuple(SCHEDULABLE_ANALYZERS), help="openclaw | hermes."
    )
    analysis_schedule_add.add_argument("--adapter-id", help="Operator adapter id (defaults to the analyzer).")
    analysis_schedule_add.add_argument("--source-path", help="Source path re-imported on each fire.")
    analysis_schedule_add.add_argument("--interval-hours", type=int, default=24, help="Cadence in hours.")
    analysis_schedule_add.add_argument("--at-time", help="Local anchor time 'HH:MM' (e.g. 03:30).")
    analysis_schedule_add.add_argument(
        "--no-refresh-import", action="store_true", help="Do not re-import before analyzing."
    )
    analysis_schedule_add.add_argument(
        "--no-autonomy", action="store_true", help="Scheduled runs stop before autonomy."
    )
    analysis_schedule_add.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    analysis_schedule_add.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    analysis_schedules = subcommands.add_parser(
        "analysis-schedules", help="List recurring analysis schedules."
    )
    _add_db_argument(analysis_schedules)
    analysis_schedules.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    analysis_schedule_remove = subcommands.add_parser(
        "analysis-schedule-remove", help="Delete a recurring analysis schedule."
    )
    _add_db_argument(analysis_schedule_remove)
    analysis_schedule_remove.add_argument("schedule_id", help="Schedule id to delete.")
    analysis_schedule_remove.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    analysis_schedule_run = subcommands.add_parser(
        "analysis-schedule-run", help="Fire a recurring analysis schedule immediately."
    )
    _add_db_argument(analysis_schedule_run)
    analysis_schedule_run.add_argument("schedule_id", help="Schedule id to run now.")
    analysis_schedule_run.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

    operator_adapter_register = subcommands.add_parser(
        "operator-adapter-register",
        help="Register a named local operator-agent command.",
    )
    _add_db_argument(operator_adapter_register)
    operator_adapter_register.add_argument("adapter_id", help="Operator adapter id, for example codex.")
    operator_adapter_register.add_argument("--name", required=True, help="Human-readable adapter name.")
    operator_adapter_register.add_argument(
        "--kind",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        default="generic",
        help="Operator family for UI and diagnostics.",
    )
    operator_adapter_register.add_argument(
        "--command",
        dest="adapter_command",
        required=True,
        help="Operator command. Receives KYOKO_EVIDENCE_PATH when run.",
    )
    operator_adapter_register.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    operator_adapter_register.add_argument(
        "--output-dir",
        type=Path,
        help="Default artifact output directory for this adapter.",
    )
    operator_adapter_register.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Default adapter timeout in seconds.",
    )
    operator_adapter_register.add_argument(
        "--disabled",
        action="store_true",
        help="Register adapter as disabled.",
    )
    operator_adapter_register.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    operator_adapter_bootstrap = subcommands.add_parser(
        "operator-adapter-bootstrap",
        help="Register safe default operator adapters for installed local agent CLIs.",
    )
    _add_db_argument(operator_adapter_bootstrap)
    operator_adapter_bootstrap.add_argument(
        "target",
        nargs="?",
        default="all",
        choices=operator_preset_choices(),
        help="Operator preset to register. Defaults to every available preset.",
    )
    operator_adapter_bootstrap.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    operator_adapter_bootstrap.add_argument(
        "--output-dir",
        type=Path,
        help="Default artifact output directory for bootstrapped adapters.",
    )
    operator_adapter_bootstrap.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Default adapter timeout in seconds.",
    )
    operator_adapter_bootstrap.add_argument(
        "--disabled",
        action="store_true",
        help="Register adapters as disabled.",
    )
    operator_adapter_bootstrap.add_argument(
        "--list-presets",
        action="store_true",
        help="List built-in operator presets without registering them.",
    )
    operator_adapter_bootstrap.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    operator_adapters = subcommands.add_parser(
        "operator-adapters",
        help="List registered operator adapters.",
    )
    _add_db_argument(operator_adapters)
    operator_adapters.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    operator_runs = subcommands.add_parser(
        "operator-runs",
        help="List recorded operator-agent analysis runs.",
    )
    _add_db_argument(operator_runs)
    operator_runs.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    operator_adapter_run = subcommands.add_parser(
        "operator-adapter-run",
        help="Run a registered operator adapter by id.",
    )
    _add_db_argument(operator_adapter_run)
    operator_adapter_run.add_argument("adapter_id", help="Operator adapter id.")
    operator_adapter_run.add_argument("--output-dir", type=Path, help="Override artifact output directory.")
    operator_adapter_run.add_argument("--profile-id", help="Profile id to analyze.")
    operator_adapter_run.add_argument("--run-id", help="Optional run id to analyze.")
    operator_adapter_run.add_argument("--timeout", type=int, help="Override timeout in seconds.")
    operator_adapter_run.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Retry malformed or semantically invalid operator output this many times.",
    )
    operator_adapter_run.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    operator_adapter_run.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    operator_smoke = subcommands.add_parser(
        "operator-smoke",
        help="Run a safe proposal-output smoke test for an operator agent.",
    )
    operator_smoke.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional database path to use. Defaults to a demo database under --output-dir.",
    )
    operator_smoke.add_argument(
        "--operator",
        default="mock",
        help=(
            "Operator to smoke test. Use mock, command, adapter with "
            "--operator-adapter, or a registered/preset adapter id such as codex."
        ),
    )
    operator_smoke.add_argument(
        "--all-presets",
        action="store_true",
        help="Prepare or run smoke checks for every built-in operator preset.",
    )
    operator_smoke.add_argument(
        "--operator-adapter",
        help="Registered operator adapter id to use when --operator adapter is selected.",
    )
    operator_smoke.add_argument(
        "--command",
        dest="operator_command",
        help="External operator command for --operator command.",
    )
    operator_smoke.add_argument(
        "--profile-id",
        help="Profile id to analyze. Defaults to the first profile.",
    )
    operator_smoke.add_argument("--run-id", help="Optional run id to analyze.")
    operator_smoke.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for smoke artifacts. Defaults to a temporary directory that is kept.",
    )
    operator_smoke.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema. The bundled schema is used when this default is unavailable.",
    )
    operator_smoke.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="External operator timeout in seconds.",
    )
    operator_smoke.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help="Retry malformed or semantically invalid operator output this many times.",
    )
    operator_smoke.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write smoke evidence/prompt artifacts and print the operator command without running it.",
    )
    operator_smoke.add_argument(
        "--expect-failure",
        action="store_true",
        help="Run a negative-path smoke and pass when the operator output failure is captured.",
    )
    operator_smoke.add_argument(
        "--failure-mode",
        default="invalid-output",
        choices=("invalid-output",),
        help="Expected-failure prompt mode for --expect-failure.",
    )
    operator_smoke.add_argument(
        "--expected-failure-kind",
        default="invalid_output",
        help="Required captured failure kind for --expect-failure; use any to accept any captured failure.",
    )
    operator_smoke.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Treat missing preset executables as failures in --all-presets mode.",
    )
    operator_smoke.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    mcp = subcommands.add_parser(
        "mcp",
        help="Run or configure the Kyoko MCP server for operator agents.",
    )
    mcp_subcommands = mcp.add_subparsers(dest="mcp_command")

    mcp_serve = mcp_subcommands.add_parser(
        "serve",
        help="Run the Kyoko MCP server over stdio.",
    )
    _add_db_argument(mcp_serve)
    mcp_serve.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )

    mcp_config = mcp_subcommands.add_parser(
        "config",
        help="Print an MCP server config block.",
    )
    _add_db_argument(mcp_config)
    mcp_config.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    mcp_config.add_argument(
        "--name",
        default="kyoko",
        help="MCP server name in the generated config.",
    )
    mcp_config.add_argument(
        "--target",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        default="generic",
        help="Client target label for the generated config.",
    )

    mcp_install_plan = mcp_subcommands.add_parser(
        "install-plan",
        help="Print a target-specific MCP install command or manual config plan.",
    )
    _add_db_argument(mcp_install_plan)
    mcp_install_plan.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    mcp_install_plan.add_argument(
        "--name",
        default="kyoko",
        help="MCP server name in the generated config.",
    )
    mcp_install_plan.add_argument(
        "--target",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        default="generic",
        help="Client target label for the install plan.",
    )
    mcp_install_plan.add_argument(
        "--scope",
        choices=["local", "user", "project"],
        default="local",
        help="Claude Code MCP scope for Claude install plans.",
    )
    mcp_install_plan.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable install plan metadata.",
    )

    mcp_install_smoke = mcp_subcommands.add_parser(
        "install-smoke",
        help="Run a native MCP client install command in an isolated temp home.",
    )
    mcp_install_smoke.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional database path to configure. Defaults to an isolated smoke database.",
    )
    mcp_install_smoke.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    mcp_install_smoke.add_argument(
        "--name",
        default="kyoko",
        help="MCP server name in the generated config.",
    )
    mcp_install_smoke.add_argument(
        "--target",
        choices=["codex", "claude", "hermes", "openclaw"],
        help="Native MCP client target to smoke.",
    )
    mcp_install_smoke.add_argument(
        "--all-targets",
        action="store_true",
        help="Run isolated install smokes for all verified native MCP client targets.",
    )
    mcp_install_smoke.add_argument(
        "--scope",
        choices=["local", "user", "project"],
        default="user",
        help="Claude Code MCP scope for Claude install smokes.",
    )
    mcp_install_smoke.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for isolated HOME/CODEX_HOME and smoke artifacts. Defaults to a temporary directory.",
    )
    mcp_install_smoke.add_argument(
        "--client-command",
        type=Path,
        help="Optional client executable override, useful for non-standard install paths.",
    )
    mcp_install_smoke.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Timeout for the native client install command.",
    )
    mcp_install_smoke.add_argument(
        "--skip-list-verify",
        action="store_true",
        help="Skip post-install `mcp list` verification.",
    )
    mcp_install_smoke.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Treat missing native MCP clients as failures in --all-targets mode.",
    )
    mcp_install_smoke.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable smoke metadata.",
    )

    mcp_install = mcp_subcommands.add_parser(
        "install",
        help="Write an MCP server config block to a file.",
    )
    _add_db_argument(mcp_install)
    mcp_install.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    mcp_install.add_argument(
        "--name",
        default="kyoko",
        help="MCP server name in the generated config.",
    )
    mcp_install.add_argument(
        "--target",
        choices=["generic", "codex", "claude", "hermes", "openclaw"],
        default="generic",
        help="Client target label for the generated config.",
    )
    mcp_install.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path where the MCP config JSON should be written.",
    )
    mcp_install.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable install metadata.",
    )

    generate_checks = subcommands.add_parser(
        "generate-checks",
        help="Create Kyoko check specs from a LearningProposal.",
    )
    _add_db_argument(generate_checks)
    generate_checks.add_argument(
        "proposal_id",
        help="LearningProposal id to inspect for check_spec changes.",
    )
    generate_checks.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    checks = subcommands.add_parser(
        "checks",
        help="List Kyoko check specs and check runs.",
    )
    _add_db_argument(checks)
    checks.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_assertion_presets = subcommands.add_parser(
        "check-assertion-presets",
        help="List supported check assertion presets.",
    )
    check_assertion_presets.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_capabilities = subcommands.add_parser(
        "check-capabilities",
        help="List supported check types, assertions, presets, replay modes, and trust levels.",
    )
    check_capabilities.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_locks = subcommands.add_parser(
        "check-locks",
        help="List human locks for check specs.",
    )
    _add_db_argument(check_locks)
    check_locks.add_argument("--profile-id", help="Optional profile id filter.")
    check_locks.add_argument(
        "--include-unlocked",
        action="store_true",
        help="Include previously unlocked check specs.",
    )
    check_locks.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_lock = subcommands.add_parser(
        "check-lock",
        help="Mark an check spec as human-locked.",
    )
    _add_db_argument(check_lock)
    check_lock.add_argument("check_spec_id", help="Check spec id to lock.")
    check_lock.add_argument("--reason", help="Optional human-readable lock reason.")
    check_lock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the lock event to.",
    )
    check_lock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_unlock = subcommands.add_parser(
        "check-unlock",
        help="Remove the human lock from an check spec.",
    )
    _add_db_argument(check_unlock)
    check_unlock.add_argument("check_spec_id", help="Check spec id to unlock.")
    check_unlock.add_argument("--reason", help="Optional human-readable unlock reason.")
    check_unlock.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the unlock event to.",
    )
    check_unlock.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_approve = subcommands.add_parser(
        "check-approve",
        help="Mark an check spec as human-approved L3 trust.",
    )
    _add_db_argument(check_approve)
    check_approve.add_argument("check_spec_id", help="Check spec id to approve.")
    check_approve.add_argument("--reason", help="Optional human-readable approval reason.")
    check_approve.add_argument(
        "--actor-agent-identity-id",
        help="Optional agent identity id to attribute the approval event to.",
    )
    check_approve.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    check_detail = subcommands.add_parser(
        "check-detail",
        help="Show target, check runs, replay runs, and gate evidence for an check spec.",
    )
    _add_db_argument(check_detail)
    check_detail.add_argument("check_spec_id", help="Check spec id to inspect.")
    check_detail.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_detail = subcommands.add_parser(
        "replay-detail",
        help="Show source run, output run, side effects, and linked check runs for a replay run.",
    )
    _add_db_argument(replay_detail)
    replay_detail.add_argument("replay_run_id", help="Replay run id to inspect.")
    replay_detail.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay = subcommands.add_parser(
        "replay",
        help="Create a bounded replay run for an check spec.",
    )
    _add_db_argument(replay)
    replay.add_argument(
        "check_spec_id",
        help="Check spec id to replay.",
    )
    replay.add_argument(
        "--mode",
        choices=["dry_run", "sandbox", "live"],
        default="dry_run",
        help="Replay mode. v0 rejects live mode.",
    )
    replay.add_argument(
        "--side-effect-mode",
        choices=[
            "none",
            "filesystem_read",
            "sandboxed_filesystem",
            "network_mocked",
            "live_network",
            "unknown",
        ],
        help="Optional replay side-effect mode. Defaults to the check spec mode.",
    )
    replay.add_argument(
        "--source-run-id",
        help="Optional source run id override.",
    )
    replay.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    complete_replay = subcommands.add_parser(
        "complete-replay",
        help="Complete a replay run by ingesting a controlled replay result fixture.",
    )
    _add_db_argument(complete_replay)
    complete_replay.add_argument(
        "replay_run_id",
        help="Replay run id to complete.",
    )
    complete_replay.add_argument(
        "fixture",
        type=Path,
        help="Path to a replay result fixture JSON file.",
    )
    complete_replay.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_command = subcommands.add_parser(
        "replay-command",
        help="Run an external replay command and ingest its replay-result block.",
    )
    _add_db_argument(replay_command)
    replay_command.add_argument(
        "check_spec_id",
        help="Check spec id to replay.",
    )
    replay_command.add_argument(
        "--command",
        dest="replay_command",
        required=True,
        help="External replay command. Receives KYOKO_REPLAY_REQUEST_PATH.",
    )
    replay_command.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where replay request/result artifacts are written.",
    )
    replay_command.add_argument(
        "--mode",
        choices=["dry_run", "sandbox", "live"],
        default="dry_run",
        help="Replay mode. v0 rejects live mode.",
    )
    replay_command.add_argument(
        "--side-effect-mode",
        choices=[
            "none",
            "filesystem_read",
            "sandboxed_filesystem",
            "network_mocked",
            "live_network",
            "unknown",
        ],
        help="Optional replay side-effect mode. Defaults to the check spec mode.",
    )
    replay_command.add_argument(
        "--source-run-id",
        help="Optional source run id override.",
    )
    replay_command.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="External replay command timeout in seconds.",
    )
    replay_command.add_argument(
        "--run-check",
        action="store_true",
        help="Run the check after the replay result is ingested.",
    )
    replay_command.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_health = subcommands.add_parser(
        "replay-server-health",
        help="Check a Workshop-style HTTP replay server.",
    )
    replay_server_health.add_argument("server_url", help="Replay server base URL.")
    replay_server_health.add_argument(
        "--health-path",
        default="/health",
        help="Health endpoint path.",
    )
    replay_server_health.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="HTTP timeout in seconds.",
    )
    replay_server_health.add_argument(
        "--allow-remote-server",
        action="store_true",
        help="Allow a non-loopback replay server URL. Defaults to loopback-only.",
    )
    replay_server_health.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_run = subcommands.add_parser(
        "replay-server-run",
        help="Run an check through a Workshop-style HTTP replay server.",
    )
    _add_db_argument(replay_server_run)
    replay_server_run.add_argument("server_url", help="Replay server base URL.")
    replay_server_run.add_argument("check_spec_id", help="Check spec id to replay.")
    replay_server_run.add_argument(
        "--health-path",
        default="/health",
        help="Health endpoint path.",
    )
    replay_server_run.add_argument(
        "--replay-path",
        default="/replay",
        help="Replay endpoint path.",
    )
    replay_server_run.add_argument(
        "--mode",
        choices=["dry_run", "sandbox", "live"],
        default="dry_run",
        help="Replay mode. v0 rejects live mode.",
    )
    replay_server_run.add_argument(
        "--side-effect-mode",
        choices=[
            "none",
            "filesystem_read",
            "sandboxed_filesystem",
            "network_mocked",
            "live_network",
            "unknown",
        ],
        default=None,
        help="Replay side-effect mode. Defaults to the check spec mode.",
    )
    replay_server_run.add_argument("--source-run-id", help="Optional source run id override.")
    replay_server_run.add_argument("--trace-endpoint", help="Kyoko ingest endpoint for replay traces.")
    replay_server_run.add_argument("--timeout", type=int, default=120, help="HTTP timeout in seconds.")
    replay_server_run.add_argument(
        "--allow-remote-server",
        action="store_true",
        help="Allow a non-loopback replay server URL. Defaults to loopback-only.",
    )
    replay_server_run.add_argument(
        "--skip-health",
        action="store_true",
        help="Skip the replay server health check before POST /replay.",
    )
    replay_server_run.add_argument(
        "--run-check",
        action="store_true",
        help="Run the check after the replay result is ingested.",
    )
    replay_server_run.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_template = subcommands.add_parser(
        "replay-server-template",
        help="Write a framework-specific HTTP replay server scaffold.",
    )
    replay_server_template.add_argument(
        "output_path",
        type=Path,
        help="Path to write, for example scripts/kyoko_replay_server.py.",
    )
    replay_server_template.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_FRAMEWORKS),
        default="generic-python",
        help="Agent framework template to generate.",
    )
    replay_server_template.add_argument(
        "--profile-name",
        default="kyoko-agent",
        help="Profile name exposed by GET /health.",
    )
    replay_server_template.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing template file.",
    )
    replay_server_template.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    source_adapter_template = subcommands.add_parser(
        "source-adapter-template",
        help="Write a framework-specific source telemetry adapter scaffold.",
    )
    source_adapter_template.add_argument(
        "output",
        type=Path,
        help="Output Python file for the source adapter template.",
    )
    source_adapter_template.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_SOURCE_FRAMEWORKS),
        default="generic-python",
        help="Agent framework template to generate.",
    )
    source_adapter_template.add_argument(
        "--profile-name",
        default="kyoko-agent",
        help="Default Kyoko profile name embedded in the template.",
    )
    source_adapter_template.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing template file.",
    )
    source_adapter_template.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_smoke = subcommands.add_parser(
        "integration-smoke",
        help=(
            "Validate generated source adapters, replay servers, or improve "
            "smokes before wiring them into Kyoko."
        ),
    )
    integration_subcommands = integration_smoke.add_subparsers(dest="integration_command")

    integration_source = integration_subcommands.add_parser(
        "source",
        help="Run a source adapter hook, ingest its output, and report DB status.",
    )
    _add_db_argument(integration_source)
    integration_source.add_argument(
        "adapter_path",
        type=Path,
        help="Generated source adapter Python file.",
    )
    integration_source.add_argument(
        "--hook",
        required=True,
        help="Source hook module_or_path:function for KYOKO_SOURCE_HOOK.",
    )
    integration_source.add_argument(
        "--python-executable",
        type=Path,
        help="Python executable used when running a Python source adapter.",
    )
    integration_source.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for source-events.json and adapter stdout/stderr.",
    )
    integration_source.add_argument("--profile-id", help="Profile id passed to the adapter.")
    integration_source.add_argument("--profile-name", help="Profile name passed to the adapter.")
    integration_source.add_argument("--root-path", type=Path, help="Root path passed to the adapter.")
    integration_source.add_argument("--source-id", help="Source id passed to the adapter.")
    integration_source.add_argument("--agent-id", help="Agent identity id passed to the adapter.")
    integration_source.add_argument("--agent-name", help="Agent name passed to the adapter.")
    integration_source.add_argument(
        "--cwd",
        type=Path,
        help="Working directory for the adapter subprocess.",
    )
    integration_source.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Adapter subprocess timeout in seconds.",
    )
    integration_source.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_framework_source = integration_subcommands.add_parser(
        "framework-source",
        help="Run an installed framework through a generated source adapter smoke.",
    )
    _add_db_argument(integration_framework_source)
    integration_framework_source.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS),
        default=DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
        help="Installed framework source smoke to run.",
    )
    integration_framework_source.add_argument(
        "--python-executable",
        type=Path,
        help="Python executable that has the framework package installed.",
    )
    integration_framework_source.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated adapters, hooks, and smoke artifacts.",
    )
    integration_framework_source.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for package checks and source adapter execution.",
    )
    integration_framework_source.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_framework_replay = integration_subcommands.add_parser(
        "framework-replay",
        help="Run an installed framework through a generated replay-server smoke.",
    )
    integration_framework_replay.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS),
        default=DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
        help="Installed framework replay smoke to run.",
    )
    integration_framework_replay.add_argument(
        "--python-executable",
        type=Path,
        help="Python executable that has the framework package installed.",
    )
    integration_framework_replay.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated replay server, hook, and smoke artifacts.",
    )
    integration_framework_replay.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for package checks, server startup, and replay execution.",
    )
    integration_framework_replay.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_framework_improve = integration_subcommands.add_parser(
        "framework-improve",
        help="Run an installed framework through source, replay, check, and improve apply.",
    )
    _add_db_argument(integration_framework_improve)
    integration_framework_improve.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_INSTALLED_SOURCE_FRAMEWORKS),
        default=DEFAULT_INSTALLED_FRAMEWORK_SOURCE_FRAMEWORK,
        help="Installed framework improve smoke to run.",
    )
    integration_framework_improve.add_argument(
        "--python-executable",
        type=Path,
        help="Python executable that has the framework package installed.",
    )
    integration_framework_improve.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated adapters, hooks, replay logs, and improve artifacts.",
    )
    integration_framework_improve.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    integration_framework_improve.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for package checks, source adapter, replay server, and improve execution.",
    )
    integration_framework_improve.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_opentelemetry = integration_subcommands.add_parser(
        "opentelemetry-python",
        help="Run the installed OpenTelemetry Python SDK through Kyoko OTLP ingest.",
    )
    _add_db_argument(integration_opentelemetry)
    integration_opentelemetry.add_argument(
        "--python-executable",
        type=Path,
        help="Python executable that has opentelemetry-sdk installed.",
    )
    integration_opentelemetry.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated OTLP JSON, normalized source events, and logs.",
    )
    integration_opentelemetry.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for package checks and OpenTelemetry SDK execution.",
    )
    integration_opentelemetry.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_replay = integration_subcommands.add_parser(
        "replay-server",
        help="Start a replay server command, check health, capture logs, and stop it.",
    )
    integration_replay.add_argument(
        "--command",
        dest="integration_replay_command",
        required=True,
        help="Replay server command string, for example 'python3 scripts/kyoko_replay_server.py --port 61200'.",
    )
    integration_replay.add_argument(
        "--server-url",
        required=True,
        help="Replay server base URL to health check.",
    )
    integration_replay.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for replay server state and stdout/stderr.",
    )
    integration_replay.add_argument(
        "--health-path",
        default="/health",
        help="Health endpoint path.",
    )
    integration_replay.add_argument(
        "--hook",
        help="Replay hook module_or_path:function to expose as KYOKO_REPLAY_HOOK for the server subprocess.",
    )
    integration_replay.add_argument(
        "--run-replay",
        action="store_true",
        help="After health succeeds, POST a bounded replay request to the replay endpoint.",
    )
    integration_replay.add_argument(
        "--replay-path",
        default="/replay",
        help="Replay endpoint path used with --run-replay.",
    )
    integration_replay.add_argument(
        "--replay-request-json",
        help="JSON object to POST with --run-replay. Defaults to a generated smoke request.",
    )
    integration_replay.add_argument(
        "--replay-timeout",
        type=int,
        default=10,
        help="Replay POST timeout in seconds.",
    )
    integration_replay.add_argument(
        "--startup-timeout",
        type=int,
        default=10,
        help="Startup health timeout in seconds.",
    )
    integration_replay.add_argument(
        "--stop-timeout",
        type=int,
        default=5,
        help="Shutdown timeout in seconds.",
    )
    integration_replay.add_argument(
        "--log-max-bytes",
        type=int,
        default=40000,
        help="Maximum bytes to include from each replay server log.",
    )
    integration_replay.add_argument(
        "--cwd",
        type=Path,
        help="Working directory for the replay server subprocess.",
    )
    integration_replay.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    integration_improve = integration_subcommands.add_parser(
        "improve",
        help="Run generated source/replay adapters through the high-level improve loop.",
    )
    _add_db_argument(integration_improve)
    integration_improve.add_argument(
        "--framework",
        choices=sorted(SUPPORTED_FRAMEWORKS),
        default="generic-python",
        help="Generated adapter framework template to smoke.",
    )
    integration_improve.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for generated adapters, hooks, replay logs, and improve artifacts.",
    )
    integration_improve.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema.",
    )
    integration_improve.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Timeout in seconds for generated source/replay subprocesses.",
    )
    integration_improve.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_start = subcommands.add_parser(
        "replay-server-start",
        help="Start a registered managed HTTP replay server adapter.",
    )
    _add_db_argument(replay_server_start)
    replay_server_start.add_argument("adapter_id", help="Replay adapter id.")
    replay_server_start.add_argument("--output-dir", type=Path, help="Override server state/log directory.")
    replay_server_start.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_status = subcommands.add_parser(
        "replay-server-status",
        help="Show status for a registered HTTP replay server adapter.",
    )
    _add_db_argument(replay_server_status)
    replay_server_status.add_argument("adapter_id", help="Replay adapter id.")
    replay_server_status.add_argument("--output-dir", type=Path, help="Override server state/log directory.")
    replay_server_status.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_logs = subcommands.add_parser(
        "replay-server-logs",
        help="Show stdout/stderr logs for a registered managed HTTP replay server adapter.",
    )
    _add_db_argument(replay_server_logs)
    replay_server_logs.add_argument("adapter_id", help="Replay adapter id.")
    replay_server_logs.add_argument("--output-dir", type=Path, help="Override server state/log directory.")
    replay_server_logs.add_argument(
        "--max-bytes",
        type=int,
        default=40000,
        help="Maximum bytes to read from each log stream.",
    )
    replay_server_logs.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_server_stop = subcommands.add_parser(
        "replay-server-stop",
        help="Stop a registered managed HTTP replay server adapter.",
    )
    _add_db_argument(replay_server_stop)
    replay_server_stop.add_argument("adapter_id", help="Replay adapter id.")
    replay_server_stop.add_argument("--output-dir", type=Path, help="Override server state/log directory.")
    replay_server_stop.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_adapter_register = subcommands.add_parser(
        "replay-adapter-register",
        help="Register a named replay adapter command or HTTP replay server.",
    )
    _add_db_argument(replay_adapter_register)
    replay_adapter_register.add_argument("adapter_id", help="Replay adapter id.")
    replay_adapter_register.add_argument("--name", required=True, help="Human-readable adapter name.")
    replay_adapter_register.add_argument(
        "--command",
        dest="adapter_command",
        help=(
            "Replay command. Used alone, it receives KYOKO_REPLAY_REQUEST_PATH. "
            "Used with --server-url, it starts a managed HTTP replay server."
        ),
    )
    replay_adapter_register.add_argument(
        "--server-url",
        help="HTTP replay server base URL. Defaults to loopback-only unless --allow-remote-server is set.",
    )
    replay_adapter_register.add_argument(
        "--health-path",
        default="/health",
        help="HTTP replay server health path.",
    )
    replay_adapter_register.add_argument(
        "--replay-path",
        default="/replay",
        help="HTTP replay server replay path.",
    )
    replay_adapter_register.add_argument(
        "--startup-timeout",
        type=int,
        default=15,
        help="Managed HTTP replay server startup timeout in seconds.",
    )
    replay_adapter_register.add_argument(
        "--cwd",
        type=Path,
        help="Working directory for a managed HTTP replay server command.",
    )
    replay_adapter_register.add_argument("--profile-id", help="Profile id. Defaults to the first profile.")
    replay_adapter_register.add_argument(
        "--output-dir",
        type=Path,
        help="Default artifact output directory for this adapter.",
    )
    replay_adapter_register.add_argument(
        "--mode",
        choices=["dry_run", "sandbox", "live"],
        default="dry_run",
        help="Default replay mode. v0 rejects live mode.",
    )
    replay_adapter_register.add_argument(
        "--side-effect-mode",
        choices=[
            "none",
            "filesystem_read",
            "sandboxed_filesystem",
            "network_mocked",
            "live_network",
            "unknown",
        ],
        default="network_mocked",
        help="Default replay side-effect mode.",
    )
    replay_adapter_register.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Default adapter timeout in seconds.",
    )
    replay_adapter_register.add_argument(
        "--disabled",
        action="store_true",
        help="Register adapter as disabled.",
    )
    replay_adapter_register.add_argument(
        "--allow-remote-server",
        action="store_true",
        help="Allow a non-loopback replay server URL for this adapter.",
    )
    replay_adapter_register.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_adapters = subcommands.add_parser(
        "replay-adapters",
        help="List registered replay adapters.",
    )
    _add_db_argument(replay_adapters)
    replay_adapters.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    replay_adapter_run = subcommands.add_parser(
        "replay-adapter-run",
        help="Run a registered replay adapter by id.",
    )
    _add_db_argument(replay_adapter_run)
    replay_adapter_run.add_argument("adapter_id", help="Replay adapter id.")
    replay_adapter_run.add_argument("check_spec_id", help="Check spec id to replay.")
    replay_adapter_run.add_argument("--output-dir", type=Path, help="Override artifact output directory.")
    replay_adapter_run.add_argument(
        "--mode",
        choices=["dry_run", "sandbox", "live"],
        help="Override replay mode. v0 rejects live mode.",
    )
    replay_adapter_run.add_argument(
        "--side-effect-mode",
        choices=[
            "none",
            "filesystem_read",
            "sandboxed_filesystem",
            "network_mocked",
            "live_network",
            "unknown",
        ],
        help="Override replay side-effect mode.",
    )
    replay_adapter_run.add_argument("--source-run-id", help="Optional source run id override.")
    replay_adapter_run.add_argument("--timeout", type=int, help="Override timeout in seconds.")
    replay_adapter_run.add_argument(
        "--run-check",
        action="store_true",
        help="Run the check after the replay result is ingested.",
    )
    replay_adapter_run.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    run_check_parser = subcommands.add_parser(
        "run-check",
        help="Run a Kyoko check spec.",
    )
    _add_db_argument(run_check_parser)
    run_check_parser.add_argument(
        "check_spec_id",
        help="Check spec id to run.",
    )
    run_check_parser.add_argument(
        "--replay-run-id",
        help="Optional replay run id to link to this check run.",
    )
    run_check_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    judge_command_parser = subcommands.add_parser(
        "judge-command",
        help="Run an external judge command and capture its verdict into a judge check.",
    )
    _add_db_argument(judge_command_parser)
    judge_command_parser.add_argument(
        "check_spec_id",
        help="Judge check spec id to run.",
    )
    judge_command_parser.add_argument(
        "--command",
        dest="judge_command",
        required=True,
        help="External judge command. Receives the redacted request on stdin and KYOKO_JUDGE_REQUEST_PATH.",
    )
    judge_command_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory for judge request, raw output, and parsed result artifacts.",
    )
    judge_command_parser.add_argument(
        "--replay-run-id",
        help="Optional replay run id to include and link to this judge check run.",
    )
    judge_command_parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="External judge timeout in seconds.",
    )
    judge_command_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    judge_smoke_parser = subcommands.add_parser(
        "judge-smoke",
        help="Prepare or run a judge-command smoke against the bundled demo evidence.",
    )
    judge_smoke_parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional database path to use. Defaults to a demo database under --output-dir.",
    )
    judge_smoke_parser.add_argument(
        "--command",
        dest="judge_command",
        help="External judge command. Required unless --prepare-only is used.",
    )
    judge_smoke_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for judge smoke artifacts. Defaults to a temporary directory that is kept.",
    )
    judge_smoke_parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Write judge request/handoff artifacts without invoking the external command.",
    )
    judge_smoke_parser.add_argument(
        "--provider-backed",
        action="store_true",
        help="Mark the invoked judge command as provider/model-backed in the smoke report.",
    )
    judge_smoke_parser.add_argument(
        "--schema",
        type=Path,
        default=Path("docs/schemas/learning-proposal.schema.json"),
        help="Path to the LearningProposal JSON Schema. The bundled schema is used when this default is unavailable.",
    )
    judge_smoke_parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="External judge timeout in seconds.",
    )
    judge_smoke_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    dashboard_smoke_parser = subcommands.add_parser(
        "dashboard-smoke",
        help="Run an optional Playwright browser smoke against the dashboard.",
    )
    dashboard_smoke_parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Optional database path. Defaults to a temporary demo database or --output-dir/dashboard-smoke.db.",
    )
    dashboard_smoke_parser.add_argument(
        "--output-dir",
        type=Path,
        help="Directory for retained smoke database and optional screenshots.",
    )
    dashboard_smoke_parser.add_argument(
        "--no-seed-demo",
        action="store_true",
        help="Do not seed the bundled demo before opening the dashboard.",
    )
    dashboard_smoke_parser.add_argument(
        "--screenshot",
        action="store_true",
        help="Write desktop and mobile dashboard screenshots when --output-dir is supplied.",
    )
    dashboard_smoke_parser.add_argument(
        "--install-browser-deps",
        action="store_true",
        help="Install @playwright/test and Chromium under --output-dir when Python Playwright is unavailable.",
    )
    dashboard_smoke_parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Browser navigation and readiness timeout in seconds.",
    )
    dashboard_smoke_parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON.",
    )

    serve_parser = subcommands.add_parser(
        "serve",
        help="Run the local Kyoko dashboard and JSON API.",
    )
    _add_db_argument(serve_parser)
    serve_parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Host interface to bind.",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to bind.",
    )
    serve_parser.add_argument(
        "--auth-token",
        default=None,
        help="Bearer token for dashboard/API access. Defaults to KYOKO_AUTH_TOKEN.",
    )
    serve_parser.add_argument(
        "--default-lock-actor-agent-identity-id",
        default=None,
        help=(
            "Default agent identity id for dashboard/API human-lock and approval events. "
            "Defaults to KYOKO_DEFAULT_LOCK_ACTOR_AGENT_IDENTITY_ID."
        ),
    )

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate-gates":
        try:
            report = validate_gate_artifacts(
                root=args.root,
                require_jsonschema=args.strict_schema,
            )
        except ValidationError as exc:
            print(f"validation failed: {exc}", file=sys.stderr)
            return 1

        for line in report.messages:
            print(line)
        return 0

    if args.command == "bundled-assets":
        if args.asset and args.output_dir:
            print("bundled-assets failed: --asset cannot be combined with --output-dir", file=sys.stderr)
            return 1
        if args.output and not args.asset:
            print("bundled-assets failed: --output requires --asset", file=sys.stderr)
            return 1
        try:
            assets = _bundled_asset_entries()
            exported: tuple[dict[str, str], ...] = ()
            if args.output_dir:
                exported = export_bundled_assets(output_dir=args.output_dir)
            elif args.asset:
                if args.output is None:
                    print("bundled-assets failed: --asset requires --output", file=sys.stderr)
                    return 1
                output_path = export_bundled_asset(
                    relative_path=args.asset,
                    output_path=args.output,
                )
                exported = ({"asset": args.asset, "output_path": str(output_path)},)
        except (AssetError, OSError) as exc:
            print(f"bundled-assets failed: {exc}", file=sys.stderr)
            return 1

        payload = {
            "assets": assets,
            "exported": list(exported),
        }
        if args.output_dir:
            payload["output_dir"] = str(args.output_dir)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        elif exported:
            for item in exported:
                print(f"exported {item['asset']}: {item['output_path']}")
        else:
            for item in assets:
                print(item["path"])
        return 0

    if args.command == "demo":
        try:
            report = run_demo_setup(
                db_path=args.db,
                output_dir=args.output_dir,
                run_loop=not args.setup_only,
                apply_context=(not args.setup_only and not args.no_apply),
            )
        except DemoError as exc:
            print(f"demo failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True))
        else:
            print(f"demo complete: {report.profile_id}")
            print(f"db: {report.db_path}")
            print(f"proposal: {report.proposal_id}")
            for check_spec_id in report.check_spec_ids:
                print(f"check_spec: {check_spec_id}")
            print(f"replay_adapter: {report.adapter_id}")
            if report.replay_run_id:
                print(f"replay_run: {report.replay_run_id}")
            if report.check_status:
                print(f"check_status: {report.check_status}")
            if report.promoted_trust_level:
                print(f"promoted_trust_level: {report.promoted_trust_level}")
            for skill_id in report.applied_skill_ids:
                print(f"skill: {skill_id}")
            for rule_id in getattr(report, "applied_context_rule_ids", ()):
                print(f"context_rule: {rule_id}")
        return 0

    if args.command == "doctor":
        try:
            report = run_doctor(
                db_path=args.db,
                smoke_demo=args.smoke_demo,
                operator_smoke_prepare=args.operator_smoke_prepare,
                judge_smoke_prepare=args.judge_smoke_prepare,
                ace_native_prepare=args.ace_native_prepare,
                integration_smoke=args.integration_smoke,
                improve_smoke=args.improve_smoke,
                opentelemetry_smoke=args.opentelemetry_smoke,
                opentelemetry_python_executable=args.opentelemetry_python_executable,
                eval_smoke=args.eval_smoke,
                llm_eval_smoke=args.llm_eval_smoke,
                ace_native_smoke=args.ace_native_smoke,
                dashboard_smoke=args.dashboard_smoke,
                dashboard_smoke_screenshot=args.dashboard_smoke_screenshot,
                dashboard_smoke_install_browser_deps=args.dashboard_smoke_install_browser_deps,
                dashboard_smoke_timeout_seconds=args.dashboard_smoke_timeout,
                safe_smokes=args.safe_smokes,
                smoke_output_dir=args.smoke_output_dir,
                smoke_evidence_dir=args.smoke_evidence_dir,
                ace_path=args.ace_path,
                host=args.host,
                port=args.port,
            )
        except DoctorError as exc:
            print(f"doctor failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True))
        else:
            print(doctor_report_text(report))
        return 0 if report.ok else 1

    if args.command == "release-smoke":
        artifact_types = ("wheel", "sdist") if args.artifact == "both" else (args.artifact,)
        try:
            use_python_matrix = args.python_matrix or bool(args.python_target) or bool(args.python_version)
            if use_python_matrix and args.python_executable:
                raise ReleaseSmokeError("python_executable_not_allowed_with_python_matrix")
            if use_python_matrix:
                python_targets = tuple(args.python_target + args.python_version) or DEFAULT_RELEASE_PYTHON_TARGETS
                if args.output_dir:
                    report = run_release_install_smoke_matrix(
                        project_root=args.project_root,
                        output_dir=args.output_dir,
                        python_targets=python_targets,
                        artifact_types=artifact_types,
                        install_dependencies=args.install_deps,
                        run_demo=not args.skip_demo,
                        dashboard_smoke=args.dashboard_smoke,
                        timeout_seconds=args.timeout_seconds,
                    )
                    temporary = False
                else:
                    with TemporaryDirectory() as tmpdir:
                        report = run_release_install_smoke_matrix(
                            project_root=args.project_root,
                            output_dir=Path(tmpdir) / "release-smoke",
                            python_targets=python_targets,
                            artifact_types=artifact_types,
                            install_dependencies=args.install_deps,
                            run_demo=not args.skip_demo,
                            dashboard_smoke=args.dashboard_smoke,
                            timeout_seconds=args.timeout_seconds,
                        )
                    temporary = True
            elif args.output_dir:
                report = run_release_install_smoke(
                    project_root=args.project_root,
                    output_dir=args.output_dir,
                    artifact_types=artifact_types,
                    install_dependencies=args.install_deps,
                    run_demo=not args.skip_demo,
                    dashboard_smoke=args.dashboard_smoke,
                    python_executable=args.python_executable,
                    timeout_seconds=args.timeout_seconds,
                )
                temporary = False
            else:
                with TemporaryDirectory() as tmpdir:
                    report = run_release_install_smoke(
                        project_root=args.project_root,
                        output_dir=Path(tmpdir) / "release-smoke",
                        artifact_types=artifact_types,
                        install_dependencies=args.install_deps,
                        run_demo=not args.skip_demo,
                        dashboard_smoke=args.dashboard_smoke,
                        python_executable=args.python_executable,
                        timeout_seconds=args.timeout_seconds,
                    )
                temporary = True
        except ReleaseSmokeError as exc:
            print(f"release smoke failed: {exc}", file=sys.stderr)
            return 1

        payload = report.to_json()
        payload["temporary"] = temporary
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"project_root: {payload['project_root']}")
            print(f"output_dir: {payload['output_dir']}")
            print(f"temporary: {temporary}")
            print(f"passed: {payload['passed']}")
            print(f"install_dependencies: {payload['install_dependencies']}")
            print(f"run_demo: {payload['run_demo']}")
            print(f"dashboard_smoke: {payload['dashboard_smoke']}")
            print(f"duration_ms: {payload['duration_ms']:.3f}")
            if use_python_matrix:
                print(f"summary: {payload['summary']}")
                for target in payload["targets"]:
                    reason = f" reason={target['reason']}" if target["reason"] else ""
                    print(
                        f"{target['target']}: {target['status']} "
                        f"python={target['python_executable']}{reason}"
                    )
            else:
                for artifact in payload["artifacts"]:
                    print(
                        f"{artifact['artifact_type']}: "
                        f"version={artifact['installed_version']} "
                        f"doctor_ok={artifact['doctor_ok']} "
                        f"dashboard_smoke_ok={artifact['dashboard_smoke_ok']} "
                        f"artifact={artifact['artifact_path']}"
                    )
        return 0 if report.passed else 1

    if args.command == "project-bootstrap":
        try:
            report = bootstrap_project(
                project_dir=args.project_dir,
                profile_name=args.profile_name,
                source_framework=args.source_framework,
                replay_framework=args.replay_framework,
                force=args.force,
                bootstrap_operators=not args.skip_operators,
                operator_target=args.operator_target,
                mcp_target=args.mcp_target,
            )
        except ProjectBootstrapError as exc:
            print(f"project bootstrap failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"project bootstrap complete: {report.project_dir}")
            print(f"db: {report.db_path}")
            print(f"source_adapter: {report.source_adapter.output_path}")
            print(f"replay_server: {report.replay_server.output_path}")
            print(f"mcp_config: {report.mcp_config_path}")
            print(f"next_steps: {report.next_steps_path}")
            for registered in report.operator_bootstrap.registered:
                print(f"operator_adapter: {registered.adapter_id}")
            for skipped in report.operator_bootstrap.skipped:
                print(f"operator_skipped: {skipped['adapter_id']} ({skipped['reason']})")
        return 0

    if args.command == "init":
        try:
            initialize_database(args.db)
        except StorageError as exc:
            print(f"init failed: {exc}", file=sys.stderr)
            return 1
        print(f"initialized Kyoko database: {args.db}")
        return 0

    if args.command == "profile-next":
        try:
            report = run_profile_next_step(
                db_path=args.db,
                profile_id=args.profile_id,
                run=args.run,
                replay_adapter_id=args.replay_adapter,
                replay_output_dir=args.replay_output_dir,
                replay_timeout_seconds=args.replay_timeout,
                harness_workspace_root=args.harness_workspace_root,
                operator_adapter_id=args.operator_adapter,
                operator_target=args.operator_target,
                operator_output_dir=args.operator_output_dir,
                operator_timeout_seconds=args.operator_timeout,
                operator_max_retries=args.operator_max_retries,
                schema_path=args.schema,
            )
        except ProfileNextError as exc:
            print(f"profile next failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"profile: {report.profile_id}")
            print(f"action: {report.action}")
            print(f"status: {report.status}")
            print(f"reason: {report.reason}")
            if report.result is not None:
                print(f"result: {report.result}")
            suggestions = report.routing_after.get("suggested_commands", [])
            if isinstance(suggestions, list) and suggestions:
                print("suggested_commands:")
                for suggestion in suggestions:
                    if isinstance(suggestion, dict):
                        print(f"  {suggestion.get('intent')}: {_format_cli_args(suggestion.get('cli_args', []))}")
        return 0

    if args.command == "discover-sources":
        report = discover_local_sources(
            db_path=args.db,
            home=args.home,
            profile_id=args.profile_id,
            profile_name=args.profile_name,
            root_path=args.root_path,
            include_missing=args.include_missing,
        )
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            if not report.candidates:
                print("no local Hermes/OpenClaw sources discovered")
            for candidate in report.candidates:
                print(
                    f"{candidate['id']} [{candidate['kind']}/{candidate['status']}] "
                    f"{candidate['path']}"
                )
                print(f"  {candidate['import_command']}")
        return 0

    if args.command == "import-discovered-source":
        try:
            report = import_discovered_source(
                db_path=args.db,
                candidate_id=args.candidate_id,
                home=args.home,
                profile_id=args.profile_id,
                profile_name=args.profile_name,
                root_path=args.root_path,
                output_dir=args.output_dir,
            )
        except SourceDiscoveryError as exc:
            print(f"discovered source import failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            imported = payload["import"]
            print(f"imported discovered source: {report.candidate['id']}")
            print(f"profile: {imported['profile_id']}")
            for table, count in imported["ingested_counts"].items():
                print(f"{table}: {count}")
            if imported.get("normalized_path"):
                print(f"normalized: {imported['normalized_path']}")
        return 0

    if args.command == "ingest-fixture":
        try:
            report = ingest_source_fixture(args.db, args.fixture)
        except StorageError as exc:
            print(f"ingest failed: {exc}", file=sys.stderr)
            return 1
        print(f"ingested fixture for profile {report.profile_id}: {args.fixture}")
        for table, count in report.inserted_counts.items():
            print(f"{table}: {count}")
        return 0

    if args.command == "ingest":
        try:
            report = ingest_source_json(args.db, args.payload)
        except StorageError as exc:
            print(f"ingest failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "profile_id": report.profile_id,
            "ingested_counts": report.inserted_counts,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"ingested source events for profile {report.profile_id}: {args.payload}")
            for table, count in report.inserted_counts.items():
                print(f"{table}: {count}")
        return 0

    if args.command == "ingest-otlp":
        try:
            raw = args.payload.read_bytes()
            use_protobuf = args.protobuf
            otlp_payload = None
            if not use_protobuf:
                try:
                    otlp_payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    use_protobuf = True
            if use_protobuf:
                otlp_payload = decode_export_trace_service_request(raw)
            report = ingest_otlp_payload(
                db_path=args.db,
                payload=otlp_payload,
                profile_id=args.profile_id,
                profile_name=args.profile_name,
                root_path=args.root_path,
                source_kind=args.source_kind,
                source_name=args.source_name,
                output_path=args.output,
                source_label=f"OTLP {'protobuf' if use_protobuf else 'JSON'} {args.payload}",
            )
        except (OtlpNormalizeError, OtlpProtobufError, OSError, StorageError) as exc:
            print(f"otlp ingest failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "profile_id": report.profile_id,
            "run_ids": list(report.run_ids),
            "span_ids": list(report.span_ids),
            "ingested_counts": report.ingested_counts,
            "normalized_path": str(report.normalized_path) if report.normalized_path else None,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"ingested OTLP JSON for profile {report.profile_id}: {args.payload}")
            for run_id in report.run_ids:
                print(f"run: {run_id}")
            for table, count in report.ingested_counts.items():
                print(f"{table}: {count}")
            if report.normalized_path:
                print(f"normalized: {report.normalized_path}")
        return 0

    if args.command == "ingest-live":
        try:
            raw = args.payload.read_text() if args.payload else sys.stdin.read()
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ingest-live failed: {exc}", file=sys.stderr)
            return 1
        if isinstance(data, dict) and isinstance(data.get("events"), list):
            events = data["events"]
        elif isinstance(data, list):
            events = data
        elif isinstance(data, dict):
            events = [data]
        else:
            print("ingest-live failed: payload must be a JSON object or list", file=sys.stderr)
            return 1
        try:
            records = ingest_live_events(
                db_path=args.db,
                events=events,
                profile_id=args.profile_id,
            )
        except (LiveError, StorageError) as exc:
            print(f"ingest-live failed: {exc}", file=sys.stderr)
            return 1
        payload = {"ingested_count": len(records), "events": records}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"ingested {len(records)} live event(s)")
        return 0

    if args.command == "live-tail":
        kinds = (
            [k.strip() for k in args.kinds.split(",") if k.strip()]
            if args.kinds
            else None
        )
        try:
            events = list_live_events(
                db_path=args.db,
                profile_id=args.profile_id,
                run_id=args.run_id,
                after_seq=args.after_seq,
                kinds=kinds,
                limit=args.limit,
            )
        except (LiveError, StorageError) as exc:
            print(f"live-tail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"events": events}, sort_keys=True))
        else:
            for event in events:
                preview = event.get("content_preview") or ""
                print(
                    f"[{event['seq']:>4}] {event['kind']:<11} "
                    f"{event.get('run_id') or '-'}  {preview}"
                )
            if not events:
                print("(no live events)")
        return 0

    if args.command == "mcp-log":
        try:
            events = list_mcp_log(
                db_path=args.db,
                session_id=args.session_id,
                tool_name=args.tool_name,
                after_seq=args.after_seq,
                limit=args.limit,
            )
        except StorageError as exc:
            print(f"mcp-log failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"events": events}, sort_keys=True))
        else:
            for event in events:
                preview = event.get("params_preview") or event.get("result_preview") or ""
                label = event.get("tool_name") or event.get("method") or "-"
                marker = "ERR" if event.get("is_error") else "   "
                print(
                    f"[{event['seq']:>4}] {marker} {event['direction']:<12} "
                    f"{label:<24} {preview}"
                )
            if not events:
                print("(no mcp log entries)")
        return 0

    if args.command == "current-run":
        run = get_current_run(db_path=args.db)
        if args.json:
            print(json.dumps({"run": run}, sort_keys=True))
        elif run is None:
            print("(no runs)")
        else:
            print(f"{run['id']}  status={run.get('status')}  spans={run.get('span_count')}")
        return 0

    if args.command == "run-outline":
        try:
            outline = get_run_outline(
                db_path=args.db, run_id=args.run_id, payload_preview_chars=args.preview_chars
            )
        except InspectionError as exc:
            print(f"run-outline failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(outline, sort_keys=True))
        else:
            summary = outline["summary"]
            print(
                f"run {outline['run']['id']}  spans={summary['spans']} "
                f"failed={summary['failed_spans']} handoffs={summary['handoffs']} "
                f"live_events={summary['live_events']} annotations={summary['annotations']}"
            )

            def _walk(nodes: list, depth: int = 0) -> None:
                for node in nodes:
                    print(
                        f"{'  ' * depth}- {node.get('kind')}/{node.get('name')} "
                        f"[{node.get('status')}]"
                    )
                    _walk(node.get("children", []), depth + 1)

            _walk(outline["span_tree"])
        return 0

    if args.command == "search-run":
        scope = [s.strip() for s in args.scope.split(",") if s.strip()] if args.scope else None
        try:
            result = search_run(
                db_path=args.db,
                run_id=args.run_id,
                pattern=args.pattern,
                regex=args.regex,
                case_sensitive=args.case_sensitive,
                scope=scope,
                max_matches=args.max_matches,
            )
        except InspectionError as exc:
            print(f"search-run failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            for match in result["matches"]:
                print(f"{match['kind']}: …{match['snippet']}…")
            print(f"({result['match_count']} match(es){', truncated' if result['truncated'] else ''})")
        return 0

    if args.command == "span-context":
        try:
            context = get_span_context(
                db_path=args.db, span_id=args.span_id, before=args.before, after=args.after
            )
        except InspectionError as exc:
            print(f"span-context failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(context, sort_keys=True))
        else:
            for span in context["context"]:
                marker = ">>" if span["id"] == args.span_id else "  "
                print(f"{marker} {span.get('kind')}/{span.get('name')} [{span.get('status')}]")
        return 0

    if args.command == "span-payload":
        try:
            payload = get_span_payload(
                db_path=args.db,
                span_id=args.span_id,
                target=args.target,
                path=args.path,
                max_chars=args.max_chars,
                offset=args.offset,
            )
        except InspectionError as exc:
            print(f"span-payload failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        elif not payload.get("available"):
            print(f"(no {args.target} payload for {args.span_id})")
        else:
            print(payload["content"])
        return 0

    if args.command == "annotate":
        try:
            annotation = create_annotation(
                db_path=args.db,
                kind=args.kind,
                run_id=args.run_id,
                span_id=args.span_id,
                note=args.note,
                source=args.source,
            )
        except (AnnotationError, StorageError) as exc:
            print(f"annotate failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"annotation": annotation}, sort_keys=True))
        else:
            print(f"{annotation['id']}  {annotation['kind']}  {annotation.get('note') or ''}")
        return 0

    if args.command == "annotations":
        try:
            entries = list_annotations(
                db_path=args.db, run_id=args.run_id, span_id=args.span_id, limit=args.limit
            )
        except (AnnotationError, StorageError) as exc:
            print(f"annotations failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"annotations": entries}, sort_keys=True))
        else:
            for entry in entries:
                target = entry.get("span_id") or entry.get("run_id") or "-"
                print(
                    f"[{entry['kind']:<5}] {target}  ({entry['source']})  "
                    f"{entry.get('note') or ''}"
                )
            if not entries:
                print("(no annotations)")
        return 0

    if args.command == "issues":
        try:
            entries = list_issues(
                db_path=args.db,
                status=args.status,
                section=args.section,
                limit=args.limit,
            )
        except (IssueError, StorageError) as exc:
            print(f"issues failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"issues": entries}, sort_keys=True))
        else:
            for entry in entries:
                badges = "/".join(
                    part
                    for part in (entry.get("status"), entry.get("severity"), entry.get("section"))
                    if part
                )
                print(f"{entry['id']}  [{badges}]  {entry['title']}")
            if not entries:
                print("(no issues)")
        return 0

    if args.command == "issue-detail":
        try:
            detail = get_issue_detail(db_path=args.db, issue_id=args.issue_id)
        except (IssueError, DetailError, StorageError) as exc:
            print(f"issue-detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(detail, sort_keys=True))
        else:
            issue = detail["issue"]
            print(f"{issue['id']}  {issue['title']}")
            print(f"status={issue['status']} severity={issue.get('severity') or '-'} "
                  f"section={issue.get('section') or '-'}")
            print(f"linked_proposals={detail['summary']['linked_proposals']} "
                  f"evidence_refs={detail['summary']['evidence_refs']}")
        return 0

    if args.command == "issue-create":
        try:
            issue = create_issue(
                db_path=args.db,
                title=args.title,
                body=args.body,
                section=args.section,
                category=args.category,
                severity=args.severity,
                proposal_ids=args.proposal_ids or None,
            )
        except (IssueError, StorageError) as exc:
            print(f"issue-create failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"issue": issue}, sort_keys=True))
        else:
            print(f"{issue['id']}  {issue['status']}  {issue['title']}")
        return 0

    if args.command == "issue-status":
        try:
            issue = update_issue_status(
                db_path=args.db,
                issue_id=args.issue_id,
                status=args.status,
            )
        except (IssueError, StorageError) as exc:
            print(f"issue-status failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"issue": issue}, sort_keys=True))
        else:
            print(f"{issue['id']}  {issue['status']}  {issue['title']}")
        return 0

    if args.command == "issue-comment":
        try:
            issue = set_issue_comment(
                db_path=args.db,
                issue_id=args.issue_id,
                comment=args.comment,
            )
        except (IssueError, StorageError) as exc:
            print(f"issue-comment failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"issue": issue}, sort_keys=True))
        else:
            print(f"{issue['id']}  comment set")
        return 0

    if args.command == "evals":
        try:
            detectors = list_detectors(db_path=args.db)
        except (DetectorError, EvalMeasureError, StorageError) as exc:
            print(f"evals failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"detectors": detectors}, sort_keys=True))
        else:
            for det in detectors:
                print(f"{det['id']}  [{det['source']}/{det['direction']}]  {det['name']}")
            if not detectors:
                print("(no detectors)")
        return 0

    if args.command == "eval-detail":
        try:
            detector = get_detector(db_path=args.db, detector_id=args.detector_id)
        except (DetectorError, EvalMeasureError, StorageError) as exc:
            print(f"eval-detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"detector": detector}, sort_keys=True))
        else:
            print(f"{detector['id']}  {detector['name']}")
            print(f"direction={detector['direction']} unit={detector['unit_type']} "
                  f"source={detector['source']}")
            if detector.get("problem_statement"):
                print(detector["problem_statement"])
        return 0

    if args.command == "eval-register":
        try:
            detector = register_detector(db_path=args.db, path=args.path, source="user")
        except (DetectorError, EvalMeasureError, StorageError) as exc:
            print(f"eval-register failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"detector": detector}, sort_keys=True))
        else:
            print(f"registered {detector['id']}  {detector['name']}")
        return 0

    if args.command == "run-eval":
        try:
            corpus = parse_corpus(args.corpus)
            report = run_detector(
                db_path=args.db,
                detector_id=args.detector_id,
                corpus=corpus,
                persist=args.persist,
                raise_issues=args.raise_issues,
                issue_threshold=args.threshold,
            )
        except (DetectorError, EvalMeasureError, StorageError) as exc:
            print(f"run-eval failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            agg = payload["aggregate"]
            print(f"{payload['detector_id']}: value={agg['value']:.3f} "
                  f"({agg.get('numerator')}/{agg.get('denominator')})  "
                  f"units={payload['corpus_resolution']['total_matched']} "
                  f"persisted={payload['persisted']}")
        return 0

    if args.command in ("eval-compare", "llm-eval-compare"):
        try:
            comparison = compare_eval_runs(
                db_path=args.db,
                baseline_run_id=args.baseline_run_id,
                compare_run_id=args.compare_run_id,
            )
        except (EvalMeasureError, StorageError) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(comparison, sort_keys=True))
        else:
            print(f"{comparison['eval_id']}: {comparison['baseline_value']:.3f} -> "
                  f"{comparison['compare_value']:.3f} (delta {comparison['delta']:+.3f}) "
                  f"= {comparison['direction']}")
        return 0

    if args.command == "eval-runs":
        try:
            runs = list_measure_runs(db_path=args.db, kind="python")
        except (EvalMeasureError, StorageError) as exc:
            print(f"eval-runs failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"eval_runs": runs}, sort_keys=True))
        else:
            for run in runs:
                agg = run.get("aggregate") or {}
                print(f"{run['id']}  {run['eval_definition_id']}  {run['status']}  "
                      f"value={agg.get('value')}")
            if not runs:
                print("(no eval runs)")
        return 0

    if args.command == "eval-run-detail":
        try:
            run = get_measure_run(db_path=args.db, eval_run_id=args.eval_run_id)
            results = get_measure_results(db_path=args.db, eval_run_id=args.eval_run_id)
        except (EvalMeasureError, StorageError) as exc:
            print(f"eval-run-detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"eval_run": run, "results": results}, sort_keys=True))
        else:
            agg = run.get("aggregate") or {}
            print(f"{run['id']}  {run['eval_definition_id']}  {run['status']}")
            print(f"value={agg.get('value')} scored={run['unit_scored']} "
                  f"skipped={run['unit_skipped']} total={run['unit_total']}")
        return 0

    if args.command == "llm-evals":
        try:
            templates = list_llm_evals(db_path=args.db)
        except (LlmEvalError, EvalMeasureError, StorageError) as exc:
            print(f"llm-evals failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"llm_evals": templates}, sort_keys=True))
        else:
            for t in templates:
                partner = f" partner={t['partner']}" if t.get("partner") else ""
                print(f"{t['id']}  [{t['unit_type']}/{t['output_type']}/{t['direction']}]{partner}  {t['name']}")
            if not templates:
                print("(no llm_evals)")
        return 0

    if args.command == "llm-eval-detail":
        try:
            template = get_llm_eval(db_path=args.db, llm_eval_id=args.llm_eval_id)
        except (LlmEvalError, EvalMeasureError, StorageError) as exc:
            print(f"llm-eval-detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"llm_eval": template}, sort_keys=True))
        else:
            print(f"{template['id']}  {template['name']}")
            print(f"unit={template['unit_type']} output={template['output_type']} "
                  f"direction={template['direction']} partner={template.get('partner') or '-'}")
            print(f"vars={template.get('vars')}")
        return 0

    if args.command == "run-llm-eval":
        try:
            corpus = parse_corpus(args.corpus)
            command = shlex.split(args.judge_command) if args.judge_command else None
            report = run_llm_eval(
                db_path=args.db,
                llm_eval_id=args.llm_eval_id,
                corpus=corpus,
                command=command,
                persist=args.persist,
                prepare_only=args.prepare_only,
                raise_issues=args.raise_issues,
                issue_threshold=args.threshold,
                output_dir=args.output_dir,
            )
        except (LlmEvalError, DetectorError, EvalMeasureError, StorageError) as exc:
            print(f"run-llm-eval failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            if payload["prepared_only"]:
                prepared = sum(1 for r in payload["results"] if r["status"] == "prepared")
                print(f"{payload['llm_eval_id']}: prepared {prepared} requests")
            else:
                agg = payload["aggregate"] or {}
                print(f"{payload['llm_eval_id']}: value={agg.get('value')} "
                      f"units={payload['corpus_resolution']['total_matched']} "
                      f"persisted={payload['persisted']}")
        return 0

    if args.command == "llm-eval-runs":
        try:
            runs = list_measure_runs(db_path=args.db, kind="llm")
        except (EvalMeasureError, StorageError) as exc:
            print(f"llm-eval-runs failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"eval_runs": runs}, sort_keys=True))
        else:
            for run in runs:
                agg = run.get("aggregate") or {}
                print(f"{run['id']}  {run['eval_definition_id']}  {run['status']}  value={agg.get('value')}")
            if not runs:
                print("(no llm_eval runs)")
        return 0

    if args.command == "llm-eval-run-detail":
        try:
            run = get_measure_run(db_path=args.db, eval_run_id=args.eval_run_id)
            results = get_measure_results(db_path=args.db, eval_run_id=args.eval_run_id)
        except (EvalMeasureError, StorageError) as exc:
            print(f"llm-eval-run-detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"eval_run": run, "results": results}, sort_keys=True))
        else:
            agg = run.get("aggregate") or {}
            print(f"{run['id']}  {run['eval_definition_id']}  {run['status']}")
            print(f"value={agg.get('value')} scored={run['unit_scored']} "
                  f"skipped={run['unit_skipped']} total={run['unit_total']}")
        return 0

    if args.command == "import-hermes-kanban":
        try:
            report = ingest_hermes_kanban_db(
                db_path=args.db,
                kanban_db_path=args.kanban_db,
                profile_id=args.profile_id,
                profile_name=args.profile_name,
                root_path=args.root_path,
                board=args.board,
                output_path=args.output,
            )
        except HermesImportError as exc:
            print(f"hermes kanban import failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"imported Hermes Kanban board for profile {report.profile_id}: {args.kanban_db}")
            for table, count in report.ingested_counts.items():
                print(f"{table}: {count}")
            if report.normalized_path:
                print(f"normalized: {report.normalized_path}")
        return 0

    if args.command == "import-openclaw-sessions":
        try:
            report = ingest_openclaw_sessions(
                db_path=args.db,
                source_path=args.session_path,
                profile_id=args.profile_id,
                profile_name=args.profile_name,
                root_path=args.root_path,
                agent_id=args.agent_id,
                session_key=args.session_key,
                output_path=args.output,
            )
        except OpenClawImportError as exc:
            print(f"openclaw sessions import failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"imported OpenClaw sessions for profile {report.profile_id}: {args.session_path}")
            for table, count in report.ingested_counts.items():
                print(f"{table}: {count}")
            if report.normalized_path:
                print(f"normalized: {report.normalized_path}")
        return 0

    if args.command == "status":
        status = get_database_status(args.db)
        if args.json:
            print(json.dumps(status_to_json(status), sort_keys=True))
        else:
            print(f"db: {status.db_path}")
            print(f"initialized: {status.initialized}")
            print(f"schema_version: {status.schema_version}")
            print(f"migration_versions: {','.join(str(version) for version in status.migration_versions)}")
            for table, count in status.counts.items():
                print(f"{table}: {count}")
        return 0

    if args.command == "dashboard-metrics":
        try:
            metrics = get_dashboard_metrics(db_path=args.db, profile_id=args.profile_id)
        except (DashboardMetricsError, StorageError) as exc:
            print(f"dashboard metrics failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(metrics, sort_keys=True))
        else:
            print(f"profile: {metrics.get('profile_id') or 'none'}")
            for card in metrics.get("cards", []):
                detail = f" ({card.get('detail')})" if card.get("detail") else ""
                print(f"{card.get('label')}: {card.get('value')}{detail}")
        return 0

    if args.command == "storage-report":
        try:
            report = storage_report(args.db)
        except StorageError as exc:
            print(f"storage report failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"db: {payload['db_path']}")
            print(f"blob_root: {payload['blob_root']}")
            print(f"db_size_bytes: {payload['db_size_bytes']}")
            print(f"wal_size_bytes: {payload['wal_size_bytes']}")
            print(f"registered_blobs: {payload['registered_blobs']}")
            print(f"registered_blob_bytes: {payload['registered_blob_bytes']}")
            print(f"missing_blobs: {len(payload['missing_blobs'])}")
            print(f"orphan_files: {len(payload['orphan_files'])}")
        return 0

    if args.command == "prune-retention":
        try:
            report = prune_retained_data(
                db_path=args.db,
                profile_id=args.profile_id,
                trace_older_than_days=args.trace_older_than_days,
                replay_older_than_days=args.replay_older_than_days,
                operator_older_than_days=args.operator_older_than_days,
                dry_run=not args.apply,
            )
        except RetentionError as exc:
            print(f"retention prune failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"profile_id: {payload['profile_id']}")
            print(f"dry_run: {payload['dry_run']}")
            for key, cutoff in payload["cutoffs"].items():
                print(f"{key}_cutoff: {cutoff}")
            for table, ids in payload["pruned_rows"].items():
                print(f"{table}: {len(ids)}")
            print(f"skipped_rows: {len(payload['skipped_rows'])}")
        return 0

    if args.command == "wal-checkpoint":
        try:
            report = checkpoint_database(args.db, mode=args.mode)
        except StorageError as exc:
            print(f"wal checkpoint failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"db: {payload['db_path']}")
            print(f"wal: {payload['wal_path']}")
            print(f"mode: {payload['mode']}")
            print(f"busy: {payload['busy']}")
            print(f"log_frames: {payload['log_frames']}")
            print(f"checkpointed_frames: {payload['checkpointed_frames']}")
            print(f"wal_size_before: {payload['wal_size_before']}")
            print(f"wal_size_after: {payload['wal_size_after']}")
        return 0

    if args.command == "load-smoke":
        try:
            if args.use_db:
                report = run_load_smoke(
                    db_path=args.db,
                    profile_id=args.profile_id,
                    run_count=args.runs,
                    spans_per_run=args.spans_per_run,
                    read_workers=args.read_workers,
                    read_iterations=args.read_iterations,
                    expired_blob_count=args.expired_blobs,
                    checkpoint_mode=args.checkpoint_mode,
                    max_p95_ms=args.max_p95_ms,
                )
                temporary = False
            else:
                with TemporaryDirectory() as tmpdir:
                    report = run_load_smoke(
                        db_path=Path(tmpdir) / "kyoko-load-smoke.db",
                        profile_id=args.profile_id,
                        run_count=args.runs,
                        spans_per_run=args.spans_per_run,
                        read_workers=args.read_workers,
                        read_iterations=args.read_iterations,
                        expired_blob_count=args.expired_blobs,
                        checkpoint_mode=args.checkpoint_mode,
                        max_p95_ms=args.max_p95_ms,
                    )
                temporary = True
        except (LoadSmokeError, StorageError) as exc:
            print(f"load smoke failed: {exc}", file=sys.stderr)
            return 1

        payload = report.to_json()
        payload["temporary"] = temporary
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"db: {payload['db_path']}")
            print(f"temporary: {temporary}")
            print(f"profile_id: {payload['profile_id']}")
            print(f"passed: {payload['passed']}")
            print(f"runs: {payload['status']['counts']['runs']}")
            print(f"spans: {payload['status']['counts']['spans']}")
            print(f"total_read_operations: {payload['total_read_operations']}")
            print(f"duration_ms: {payload['duration_ms']:.3f}")
            print(f"p50_ms: {payload['latency_ms']['p50']:.3f}")
            print(f"p95_ms: {payload['latency_ms']['p95']:.3f}")
            print(f"max_ms: {payload['latency_ms']['max']:.3f}")
            print(f"errors: {len(payload['errors'])}")
            print(f"retention_prunable_blobs: {len(payload['retention_dry_run']['pruned_blobs'])}")
            print(f"wal_size_after: {payload['wal_checkpoint']['wal_size_after']}")
        return 0 if report.passed else 1

    if args.command == "blobs":
        try:
            rows = list_payload_blobs(args.db, profile_id=args.profile_id)
        except StorageError as exc:
            print(f"blob list failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"payload_blobs": rows}, sort_keys=True))
        else:
            if not rows:
                print("no payload blobs")
            for row in rows:
                print(f"{row['id']} {row['size_bytes']} {row['path']}")
        return 0

    if args.command == "blob-put":
        try:
            report = put_blob(
                db_path=args.db,
                data=args.path.read_bytes(),
                kind=args.kind,
                media_type=args.media_type,
                profile_id=args.profile_id,
                retained_until=retained_until_for_days(args.retention_days),
                metadata={"source_path": str(args.path)},
            )
        except (OSError, StorageError) as exc:
            print(f"blob put failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"blob: {report.blob_id}")
            print(f"path: {report.path}")
            print(f"size_bytes: {report.size_bytes}")
        return 0

    if args.command == "prune":
        try:
            report = prune_payload_blobs(
                args.db,
                older_than_days=args.older_than_days,
                profile_id=args.profile_id,
                dry_run=not args.apply,
            )
        except StorageError as exc:
            print(f"prune failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"dry_run: {report.dry_run}")
            print(f"pruned_blobs: {len(report.pruned_blobs)}")
            print(f"pruned_bytes: {report.pruned_bytes}")
            for row in report.pruned_blobs:
                print(f"{row['blob_id']} {row['reason']} {row['path']}")
        return 0

    if args.command == "runs":
        try:
            runs = list_runs(db_path=args.db, profile_id=args.profile_id, limit=args.limit)
        except (DetailError, StorageError) as exc:
            print(f"runs failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"runs": runs}, sort_keys=True))
        else:
            if not runs:
                print("no runs")
            for run in runs:
                print(
                    f"{run['id']} "
                    f"[{run['status']}] "
                    f"spans={run['span_count']} "
                    f"failed={run['failed_span_count']} "
                    f"{run.get('summary') or ''}"
                )
        return 0

    if args.command == "run-detail":
        try:
            detail = get_run_detail(db_path=args.db, run_id=args.run_id)
        except (DetailError, StorageError) as exc:
            print(f"run detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(detail, sort_keys=True))
        else:
            run = detail["run"]
            summary = detail["summary"]
            task = detail.get("task") or {}
            agent = detail.get("agent_identity") or {}
            print(f"run: {run['id']}")
            print(f"status: {run['status']}")
            print(f"agent: {agent.get('name') or 'unknown'}")
            print(f"task: {task.get('id') or 'none'}")
            print(f"spans: {summary['spans']}")
            print(f"failed_spans: {summary['failed_spans']}")
            print(f"handoffs: {summary['handoffs']}")
            print(f"related_proposals: {summary['related_proposals']}")
        return 0

    if args.command == "policy":
        try:
            policy = get_autonomy_policy(db_path=args.db, profile_id=args.profile_id)
        except (AutonomyError, StorageError) as exc:
            print(f"policy failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"policy": policy}, sort_keys=True))
        else:
            print(f"profile: {policy['profile_id']}")
            print(f"context_mode: {policy['context_mode']}")
            print(f"harness_mode: {policy['harness_mode']}")
            print(f"allow_repo_patch: {policy['allow_repo_patch']}")
            print(f"dirty_worktree_policy: {policy['dirty_worktree_policy']}")
        return 0

    if args.command == "policy-set":
        try:
            policy = update_autonomy_policy(
                db_path=args.db,
                profile_id=args.profile_id,
                context_mode=args.context_mode,
                harness_mode=args.harness_mode,
                allow_repo_patch=_on_off(args.repo_patch),
                allow_check_write=_on_off(args.check_write),
                allow_skillbook_write=_on_off(args.skillbook_write),
                allow_profile_config_write=_on_off(args.profile_config_write),
                allow_replay_server_patch=_on_off(args.replay_server_patch),
                dirty_worktree_policy=args.dirty_worktree_policy,
                required_check_level_context=args.required_check_level_context,
                required_check_level_harness=args.required_check_level_harness,
                rollback_on_regression=_on_off(args.rollback_on_regression),
            )
        except (AutonomyError, StorageError) as exc:
            print(f"policy update failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"policy": policy}, sort_keys=True))
        else:
            print(f"policy updated: {policy['profile_id']}")
            print(f"context_mode: {policy['context_mode']}")
            print(f"harness_mode: {policy['harness_mode']}")
            print(f"allow_repo_patch: {policy['allow_repo_patch']}")
            print(f"dirty_worktree_policy: {policy['dirty_worktree_policy']}")
        return 0

    if args.command == "run-autonomy":
        try:
            report = run_autonomy(
                db_path=args.db,
                profile_id=args.profile_id,
                harness_workspace_root=args.harness_workspace_root,
            )
        except (AutonomyRunError, AutonomyError, StorageError) as exc:
            print(f"autonomy run failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"autonomy run complete: {report.profile_id}")
            if not report.decisions:
                print("no eligible proposals")
            for decision in report.decisions:
                print(
                    f"{decision.proposal_id} "
                    f"[{decision.section}/{decision.state_before}->{decision.state_after}] "
                    f"{decision.action}: {decision.reason}"
                )
                for skill_id in decision.applied_skill_ids:
                    print(f"skill: {skill_id}")
                for rule_id in decision.applied_context_rule_ids:
                    print(f"context_rule: {rule_id}")
                for patch_transaction_id in decision.patch_transaction_ids:
                    print(f"patch_transaction: {patch_transaction_id}")
        return 0

    if args.command == "autonomy-events":
        events = list_timeline_events(
            db_path=args.db,
            profile_id=args.profile_id,
            kinds=(args.kind,) if args.kind else AUTONOMY_EVENT_KINDS,
            entity_type=args.entity_type,
            entity_id=args.entity_id,
            limit=args.limit,
        )
        if args.json:
            print(json.dumps({"autonomy_events": events}, sort_keys=True))
        else:
            if not events:
                print("no autonomy events")
            for event in events:
                metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
                action = metadata.get("action") or _autonomy_event_action(str(event.get("kind") or ""))
                reason = metadata.get("reason") or "unknown"
                print(
                    f"{event.get('at') or 'unknown_time'} "
                    f"{event.get('kind') or 'autonomy_event'} "
                    f"{event.get('entity_type') or 'entity'}:{event.get('entity_id') or 'unknown'} "
                    f"{action} ({reason})"
                )
        return 0

    if args.command == "propose":
        try:
            report = submit_learning_proposal(
                db_path=args.db,
                proposal_path=args.proposal,
                schema_path=args.schema,
                require_jsonschema=args.strict_schema,
            )
        except (ProposalError, StorageError, ValidationError) as exc:
            print(f"proposal rejected: {exc}", file=sys.stderr)
            return 1
        print(f"proposal accepted: {report.proposal_id}")
        print(f"profile: {report.profile_id}")
        print(f"section: {report.section}")
        print(f"state: {report.state}")
        print(f"title: {report.title}")
        return 0

    if args.command == "proposals":
        proposals = list_learning_proposals(args.db, profile_id=args.profile_id)
        if args.json:
            print(json.dumps({"proposals": proposals}, sort_keys=True))
        else:
            if not proposals:
                print("no proposals")
            for proposal in proposals:
                print(
                    f"{proposal['id']} "
                    f"[{proposal['section']}/{proposal['state']}] "
                    f"{proposal['title']}"
                )
        return 0

    if args.command == "proposal-detail":
        try:
            detail = get_proposal_detail(db_path=args.db, proposal_id=args.proposal_id)
        except (DetailError, AutonomyRunError, StorageError) as exc:
            print(f"proposal detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(detail, sort_keys=True))
        else:
            proposal = detail["proposal"]
            confidence = detail.get("confidence_assessment", {})
            gate = detail["autonomy_gate"]
            target = detail["target"]
            target_ref = target.get("ref") or {}
            print(f"proposal: {proposal['id']}")
            print(f"title: {proposal['title']}")
            print(f"section: {proposal['section']}")
            print(f"state: {proposal['state']}")
            print(
                "confidence: "
                f"kyoko={confidence.get('kyoko_confidence', 'n/a')} "
                f"operator={confidence.get('operator_confidence', 'n/a')} "
                f"level={confidence.get('level', 'n/a')}"
            )
            print(f"target: {target_ref.get('entity_type', 'unknown')}:{target_ref.get('entity_id', 'unknown')}")
            print(f"autonomy: {gate['action']} ({gate['reason']})")
            print(f"evidence_refs: {len(detail['evidence'])}")
            print(f"check_specs: {len(detail['check_specs'])}")
            check_guidance = detail.get("check_guidance", {})
            assertion_preset_names = [
                preset.get("name")
                for preset in check_guidance.get("assertion_presets", [])
                if isinstance(preset, dict) and preset.get("name")
            ]
            print(
                "gateable_check_types: "
                f"{', '.join(check_guidance.get('gateable_check_types', [])) or 'none'}"
            )
            print(
                "assertion_presets: "
                f"{', '.join(assertion_preset_names) or 'none'}"
            )
            print(f"check_runs: {len(detail['check_runs'])}")
            print(f"replay_runs: {len(detail['replay_runs'])}")
            print(f"patch_transactions: {len(detail['patch_transactions'])}")
            evidence_chain = detail.get("evidence_chain", {})
            print(f"evidence_chain: {evidence_chain.get('summary', '')}")
            for step in evidence_chain.get("steps", []):
                print(
                    f"  {step.get('stage')}: "
                    f"{step.get('status') or 'unknown'} - "
                    f"{step.get('description') or ''}"
                )
            print(f"gate_history: {len(detail.get('gate_history', []))}")
            for gate_event in detail.get("gate_history", [])[-3:]:
                print(
                    f"  {gate_event.get('kind')}: "
                    f"{gate_event.get('action') or 'unknown'} "
                    f"({gate_event.get('reason') or 'unknown'})"
                )
            print(f"timeline_events: {len(detail['timeline_events'])}")
        return 0

    if args.command == "apply":
        try:
            report = apply_context_proposal(db_path=args.db, proposal_id=args.proposal_id)
        except (ApplyError, StorageError) as exc:
            print(f"apply failed: {exc}", file=sys.stderr)
            return 1
        print(f"proposal applied: {report.proposal_id}")
        print(f"profile: {report.profile_id}")
        print(f"state: {report.state}")
        for skill_id in report.applied_skill_ids:
            print(f"skill: {skill_id}")
        for rule_id in report.applied_context_rule_ids:
            print(f"context_rule: {rule_id}")
        return 0

    if args.command == "prepare-harness":
        try:
            report = prepare_harness_proposal(db_path=args.db, proposal_id=args.proposal_id)
        except (HarnessError, StorageError) as exc:
            print(f"harness prepare failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "proposal_id": report.proposal_id,
            "profile_id": report.profile_id,
            "patch_transaction_ids": list(report.patch_transaction_ids),
            "state": report.state,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"harness prepared: {report.proposal_id}")
            print(f"profile: {report.profile_id}")
            print(f"state: {report.state}")
            for patch_transaction_id in report.patch_transaction_ids:
                print(f"patch_transaction: {patch_transaction_id}")
        return 0

    if args.command == "harness-patches":
        patch_transactions = list_patch_transactions(args.db)
        if args.json:
            print(json.dumps({"patch_transactions": patch_transactions}, sort_keys=True))
        else:
            if not patch_transactions:
                print("no harness patches")
            for patch_transaction in patch_transactions:
                print(
                    f"{patch_transaction['id']} "
                    f"[{patch_transaction['status']}/{patch_transaction['patch_kind']}] "
                    f"{patch_transaction['proposal_id']}"
                )
        return 0

    if args.command == "harness-target-locks":
        try:
            locks = list_harness_target_locks(
                args.db,
                profile_id=args.profile_id,
                locked_only=not args.include_unlocked,
            )
        except (HarnessError, StorageError) as exc:
            print(f"harness target locks failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"harness_target_locks": locks}, sort_keys=True))
        else:
            if not locks:
                print("no harness target locks")
            for lock in locks:
                state = "locked" if lock.get("human_locked") else "unlocked"
                reason = f" reason={lock['reason']}" if lock.get("reason") else ""
                print(f"{lock['profile_id']} {lock['target_path']} [{state}]{reason}")
        return 0

    if args.command in {"harness-target-lock", "harness-target-unlock"}:
        try:
            report = set_harness_target_lock(
                db_path=args.db,
                profile_id=args.profile_id,
                target_path=args.target_path,
                locked=args.command == "harness-target-lock",
                reason=args.reason,
                actor_agent_identity_id=args.actor_agent_identity_id,
            )
        except (HarnessError, StorageError) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"profile: {report.profile_id}")
            print(f"target_path: {report.target_path}")
            print(f"human_locked: {report.human_locked}")
            if report.reason:
                print(f"reason: {report.reason}")
            if report.actor_agent_identity_id:
                print(f"actor_agent_identity_id: {report.actor_agent_identity_id}")
        return 0

    if args.command == "apply-harness":
        try:
            report = apply_patch_transaction(
                db_path=args.db,
                patch_transaction_id=args.patch_transaction_id,
                workspace_root=args.workspace_root,
            )
        except (HarnessError, StorageError) as exc:
            print(f"harness apply failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "patch_transaction_id": report.patch_transaction_id,
            "proposal_id": report.proposal_id,
            "profile_id": report.profile_id,
            "target_paths": list(report.target_paths),
            "status": report.status,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"harness patch applied: {report.patch_transaction_id}")
            print(f"profile: {report.profile_id}")
            print(f"proposal: {report.proposal_id}")
            for target_path in report.target_paths:
                print(f"target: {target_path}")
        return 0

    if args.command == "rollback-harness":
        try:
            report = rollback_patch_transaction(
                db_path=args.db,
                patch_transaction_id=args.patch_transaction_id,
                workspace_root=args.workspace_root,
            )
        except (HarnessError, StorageError) as exc:
            print(f"harness rollback failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "patch_transaction_id": report.patch_transaction_id,
            "proposal_id": report.proposal_id,
            "profile_id": report.profile_id,
            "target_paths": list(report.target_paths),
            "status": report.status,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"harness patch rolled back: {report.patch_transaction_id}")
            print(f"profile: {report.profile_id}")
            print(f"proposal: {report.proposal_id}")
            for target_path in report.target_paths:
                print(f"target: {target_path}")
        return 0

    if args.command == "skills":
        skills = list_skills(args.db)
        if args.json:
            print(json.dumps({"skills": skills}, sort_keys=True))
        else:
            if not skills:
                print("no skills")
            for skill in skills:
                locked = " locked" if skill.get("human_locked") else ""
                reason = f" reason={skill['human_lock_reason']}" if skill.get("human_lock_reason") else ""
                print(f"{skill['id']} [{skill['section']}{locked}] {skill['issue']}{reason}")
        return 0

    if args.command == "skill-revisions":
        revisions = list_skill_revisions(args.db, skill_id=args.skill_id)
        if args.json:
            print(json.dumps({"skill_revisions": revisions}, sort_keys=True))
        else:
            if not revisions:
                print("no skill revisions")
            for revision in revisions:
                print(
                    f"{revision['id']} [{revision['operation']}] "
                    f"{revision['skill_id']} proposal={revision.get('proposal_id')}"
                )
        return 0

    if args.command == "skill-rollback":
        try:
            report = rollback_skill_revision(db_path=args.db, revision_id=args.revision_id)
        except ApplyError as exc:
            print(f"skill rollback failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True))
        else:
            print(f"skill rollback: {report.revision_id}")
            print(f"rollback_revision: {report.rollback_revision_id}")
            print(f"skill: {report.skill_id}")
            print(f"status: {report.status}")
        return 0

    if args.command == "context-rules":
        rules = list_context_delivery_rules(args.db, active_only=not args.include_inactive)
        if args.json:
            print(json.dumps({"context_delivery_rules": rules}, sort_keys=True))
        else:
            if not rules:
                print("no context delivery rules")
            for rule in rules:
                target = rule.get("target", {})
                locked = " locked" if rule.get("human_locked") else ""
                active = "active" if rule.get("active") else "inactive"
                reason = f" reason={rule['human_lock_reason']}" if rule.get("human_lock_reason") else ""
                print(
                    f"{rule['id']} [{active}{locked}] "
                    f"{target.get('entity_type', 'unknown')}:{target.get('entity_id', 'unknown')}{reason}"
                )
        return 0

    if args.command == "context-rule-revisions":
        revisions = list_context_delivery_rule_revisions(args.db, rule_id=args.rule_id)
        if args.json:
            print(json.dumps({"context_delivery_rule_revisions": revisions}, sort_keys=True))
        else:
            if not revisions:
                print("no context delivery rule revisions")
            for revision in revisions:
                print(
                    f"{revision['id']} [{revision['operation']}] "
                    f"{revision['rule_id']} proposal={revision.get('proposal_id')}"
                )
        return 0

    if args.command == "context-rule-rollback":
        try:
            report = rollback_context_delivery_rule_revision(
                db_path=args.db,
                revision_id=args.revision_id,
            )
        except ApplyError as exc:
            print(f"context rule rollback failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True))
        else:
            print(f"context_rule_rollback: {report.revision_id}")
            print(f"rollback_revision: {report.rollback_revision_id}")
            print(f"context_rule: {report.rule_id}")
            print(f"status: {report.status}")
        return 0

    if args.command in {"skill-lock", "skill-unlock"}:
        try:
            report = set_skill_lock(
                db_path=args.db,
                skill_id=args.skill_id,
                locked=args.command == "skill-lock",
                reason=args.reason,
                actor_agent_identity_id=args.actor_agent_identity_id,
            )
        except ApplyError as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"skill: {report.skill_id}")
            print(f"human_locked: {report.human_locked}")
            if report.reason:
                print(f"reason: {report.reason}")
            if report.actor_agent_identity_id:
                print(f"actor_agent_identity_id: {report.actor_agent_identity_id}")
        return 0

    if args.command in {"context-rule-lock", "context-rule-unlock"}:
        try:
            report = set_context_delivery_rule_lock(
                db_path=args.db,
                rule_id=args.rule_id,
                locked=args.command == "context-rule-lock",
                reason=args.reason,
                actor_agent_identity_id=args.actor_agent_identity_id,
            )
        except ApplyError as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"context_rule: {report.rule_id}")
            print(f"human_locked: {report.human_locked}")
            if report.reason:
                print(f"reason: {report.reason}")
            if report.actor_agent_identity_id:
                print(f"actor_agent_identity_id: {report.actor_agent_identity_id}")
        return 0

    if args.command == "context":
        if bool(args.target_type) != bool(args.target_id):
            print("context failed: --target-type and --target-id must be provided together", file=sys.stderr)
            return 1
        try:
            prompt = render_skillbook_prompt(
                args.db,
                section=args.section,
                include_inactive=args.include_inactive,
                profile_id=args.profile_id,
                target_entity_type=args.target_type,
                target_entity_id=args.target_id,
            )
        except ValueError as exc:
            print(f"context failed: {exc}", file=sys.stderr)
            return 1
        print(prompt)
        return 0

    if args.command == "export-skillbook":
        try:
            if args.output:
                write_skillbook_export(
                    args.db,
                    output_path=args.output,
                    output_format=args.format,
                    section=args.section,
                    include_inactive=args.include_inactive,
                    profile_id=args.profile_id,
                )
                print(f"exported skillbook: {args.output}")
                return 0
            if args.format == "json":
                payload = export_skillbook(
                    args.db,
                    section=args.section,
                    include_inactive=args.include_inactive,
                    profile_id=args.profile_id,
                )
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(
                    render_skillbook_prompt(
                        args.db,
                        section=args.section,
                        include_inactive=args.include_inactive,
                        profile_id=args.profile_id,
                    )
                )
        except ValueError as exc:
            print(f"export failed: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "ace-compat":
        try:
            report = check_ace_compatibility(
                db_path=args.db,
                ace_path=args.ace_path,
                include_inactive=args.include_inactive,
            )
        except (AceBridgeError, StorageError) as exc:
            print(f"ace compatibility failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, sort_keys=True))
        else:
            print(f"ace_available: {report['available']}")
            print(f"schema_version: {report['schema_version']}")
            print(f"skills: {report['skill_count']}")
            print(f"python_version: {report['python_version']}")
            if report.get("import_path"):
                print(f"import_path: {report['import_path']}")
            if report.get("ace_package_version"):
                print(f"ace_package_version: {report['ace_package_version']}")
            if report.get("ace_source_version"):
                print(f"ace_source_version: {report['ace_source_version']}")
            if report.get("error"):
                print(f"error: {report['error']}")
        return 0 if report.get("available") else 1

    if args.command == "ace-diff-proposals":
        try:
            report = diff_ace_skillbook_files(
                db_path=args.db,
                before_path=args.before,
                after_path=args.after,
                profile_id=args.profile_id,
                output_dir=args.output_dir,
                persist=args.persist,
                schema_path=args.schema,
                producer_name=args.producer_name,
                evidence_refs=_fallback_evidence_refs_from_args(args),
            )
        except (AceBridgeError, StorageError, ProposalError) as exc:
            print(f"ace diff failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(include_proposals=True), sort_keys=True))
        else:
            print(f"ace diff proposals: {len(report.proposal_ids)}")
            print(f"profile: {report.profile_id}")
            print(f"persisted: {report.persisted}")
            for proposal_id in report.proposal_ids:
                print(f"proposal: {proposal_id}")
            for path in report.proposal_paths:
                print(f"proposal_path: {path}")
            for unsupported in report.unsupported_changes:
                print(f"unsupported: {unsupported}")
        return 0

    if args.command == "ace-native-run":
        try:
            if args.prepare_only:
                if args.persist:
                    raise AceBridgeError("ace_prepare_only_cannot_persist")
                report = prepare_native_ace_command(
                    args.db,
                    command=shlex.split(args.ace_command),
                    profile_id=args.profile_id,
                    output_dir=args.output_dir,
                    schema_path=args.schema,
                    include_inactive=args.include_inactive,
                    provider_backed=args.provider_backed,
                    timeout_seconds=args.timeout,
                )
            else:
                report = run_native_ace_command(
                    db_path=args.db,
                    command=shlex.split(args.ace_command),
                    profile_id=args.profile_id,
                    output_dir=args.output_dir,
                    persist=args.persist,
                    schema_path=args.schema,
                    producer_name=args.producer_name,
                    evidence_refs=_fallback_evidence_refs_from_args(args),
                    include_inactive=args.include_inactive,
                    provider_backed=args.provider_backed,
                    timeout_seconds=args.timeout,
                )
        except (AceBridgeError, StorageError, ProposalError) as exc:
            print(f"ace native run failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            payload = (
                report.to_json()
                if args.prepare_only
                else report.to_json(include_proposals=True)
            )
            print(json.dumps(payload, sort_keys=True))
        elif args.prepare_only:
            print("ace native run prepared")
            print(f"profile: {report.profile_id}")
            print(f"output_dir: {report.output_dir}")
            print(f"before_path: {report.before_path}")
            print(f"after_path: {report.after_path}")
            print(f"handoff_path: {report.handoff_path}")
            print(f"shell_command: {report.shell_command}")
            print(f"provider_backed: {report.provider_backed}")
        else:
            print(f"ace native run proposals: {len(report.diff.proposal_ids)}")
            print(f"profile: {report.profile_id}")
            print(f"output_dir: {report.output_dir}")
            print(f"provider_backed: {report.provider_backed}")
            print(f"before_path: {report.before_path}")
            print(f"after_path: {report.after_path}")
            print(f"report_path: {report.report_path}")
            print(f"persisted: {report.diff.persisted}")
            for proposal_id in report.diff.proposal_ids:
                print(f"proposal: {proposal_id}")
            for path in report.diff.proposal_paths:
                print(f"proposal_path: {path}")
            for unsupported in report.diff.unsupported_changes:
                print(f"unsupported: {unsupported}")
        return 0

    if args.command == "ace-native-smoke":
        try:
            report = run_legacy_ace_offline_adapter_smoke(
                db_path=args.db,
                output_dir=args.output_dir,
                persist=args.persist,
                schema_path=args.schema,
                timeout_seconds=args.timeout,
            )
        except (AceBridgeError, StorageError, ProposalError, AssetError, OSError) as exc:
            print(f"ace native smoke failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json(include_proposals=True)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            native = payload["native_run"]
            diff = native["diff"]
            print(f"ace native smoke passed: {payload['passed']}")
            print(f"profile: {payload['profile_id']}")
            print(f"output_dir: {payload['output_dir']}")
            print(f"persisted: {diff['persisted']}")
            for proposal_id in diff["proposal_ids"]:
                print(f"proposal: {proposal_id}")
            for unsupported in diff["unsupported_changes"]:
                print(f"unsupported: {unsupported}")
        return 0 if payload.get("passed") else 1

    if args.command == "evidence":
        try:
            bundle = write_evidence_bundle(
                db_path=args.db,
                output_path=args.output,
                profile_id=args.profile_id,
                run_id=args.run_id,
            )
        except StorageError as exc:
            print(f"evidence failed: {exc}", file=sys.stderr)
            return 1
        print(f"wrote evidence bundle: {args.output}")
        print(f"profile: {bundle['profile_id']}")
        print(f"failed_spans: {bundle['summary']['failed_spans']}")
        return 0

    if args.command == "operator-prompt":
        try:
            report = write_operator_prompt_artifacts(
                db_path=args.db,
                output_dir=args.output_dir,
                target=args.target,
                profile_id=args.profile_id,
                run_id=args.run_id,
                schema_path=args.schema,
            )
        except StorageError as exc:
            print(f"operator prompt failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "target": report.target,
            "profile_id": report.profile_id,
            "evidence_path": str(report.evidence_path),
            "prompt_path": str(report.prompt_path),
            "schema_path": str(report.schema_path) if report.schema_path else None,
            "proposal_block_begin": BEGIN_PROPOSAL_BLOCK,
            "proposal_block_end": END_PROPOSAL_BLOCK,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"operator prompt written: {report.prompt_path}")
            print(f"profile: {report.profile_id}")
            print(f"evidence: {report.evidence_path}")
            print(f"target: {report.target}")
        return 0

    if args.command == "analysis-run":
        ace_command = None
        operator_command = None
        if args.analyzer == "ace":
            if not args.ace_command:
                print("analysis failed: ace_command_required", file=sys.stderr)
                return 1
            ace_command = parse_operator_command(args.ace_command)
        if args.analyzer == "command":
            if not args.operator_command:
                print("analysis failed: operator_command_required", file=sys.stderr)
                return 1
            operator_command = parse_operator_command(args.operator_command)
        try:
            result = execute_analysis_job(
                args.db,
                AnalysisJob(
                    analyzer=args.analyzer,
                    adapter_id=args.adapter_id,
                    scope=args.scope,
                    run_id=args.run_id,
                    since=args.since,
                    refresh_import=bool(args.refresh_import),
                    source_kind=args.source_kind,
                    source_path=args.source_path,
                    run_autonomy=not args.no_autonomy,
                    ace_command=ace_command,
                    operator_command=operator_command,
                    timeout_seconds=args.timeout,
                    max_retries=args.max_retries,
                    profile_id=args.profile_id,
                    output_dir=args.output_dir,
                ),
            )
        except AnalysisRunError as exc:
            print(f"analysis failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"analysis {result['status']}: {result.get('job_id')}")
            if result.get("proposal_ids"):
                print(f"proposals: {', '.join(result['proposal_ids'])}")
            if result.get("reason"):
                print(f"reason: {result['reason']}")
            if result.get("error"):
                print(f"error: {result['error']}")
        return 0 if result.get("status") in {"succeeded", "skipped"} else 1

    if args.command == "analysis-schedule-add":
        try:
            schedule = create_analysis_schedule(
                db_path=args.db,
                analyzer_kind=args.analyzer,
                adapter_id=args.adapter_id,
                source_path=args.source_path,
                refresh_import=not args.no_refresh_import,
                interval_hours=args.interval_hours,
                at_time=args.at_time,
                run_autonomy=not args.no_autonomy,
                next_run_at=next_run_at_iso(args.interval_hours, args.at_time),
                profile_id=args.profile_id,
            )
        except (StorageError, AnalysisRunError) as exc:
            print(f"schedule add failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(schedule, sort_keys=True))
        else:
            print(f"schedule added: {schedule['id']}")
            print(f"analyzer: {schedule['analyzer_kind']}")
            print(f"every {schedule['interval_hours']}h" + (f" at {schedule['at_time']}" if schedule['at_time'] else ""))
            print(f"next_run_at: {schedule['next_run_at']}")
        return 0

    if args.command == "analysis-schedules":
        schedules = list_analysis_schedules(args.db)
        if args.json:
            print(json.dumps({"schedules": schedules}, sort_keys=True))
        else:
            if not schedules:
                print("no analysis schedules")
            for s in schedules:
                state = "enabled" if s["enabled"] else "disabled"
                print(
                    f"{s['id']} {s['analyzer_kind']} every {s['interval_hours']}h"
                    + (f" at {s['at_time']}" if s.get("at_time") else "")
                    + f" [{state}] next={s.get('next_run_at')} last={s.get('last_status')}"
                )
        return 0

    if args.command == "analysis-schedule-remove":
        deleted = delete_analysis_schedule(db_path=args.db, schedule_id=args.schedule_id)
        if args.json:
            print(json.dumps({"deleted": deleted, "id": args.schedule_id}, sort_keys=True))
        else:
            print("deleted" if deleted else "not found", args.schedule_id)
        return 0 if deleted else 1

    if args.command == "analysis-schedule-run":
        from .storage import get_analysis_schedule

        schedule = get_analysis_schedule(db_path=args.db, schedule_id=args.schedule_id)
        if schedule is None:
            print(f"analysis_schedule_not_found:{args.schedule_id}", file=sys.stderr)
            return 1
        result = execute_analysis_job(args.db, job_from_schedule(schedule))
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"schedule {args.schedule_id} {result['status']}")
            if result.get("proposal_ids"):
                print(f"proposals: {', '.join(result['proposal_ids'])}")
            if result.get("error"):
                print(f"error: {result['error']}")
        return 0 if result.get("status") in {"succeeded", "skipped"} else 1

    if args.command == "analyze":
        try:
            since = getattr(args, "since", None)
            if args.operator == "mock":
                report = analyze_with_mock_operator(
                    db_path=args.db,
                    output_dir=args.output_dir,
                    profile_id=args.profile_id,
                    run_id=args.run_id,
                    since=since,
                    schema_path=args.schema,
                )
            elif args.operator == "command":
                if not args.operator_command:
                    raise AnalyzeError("operator_command_required")
                report = analyze_with_command_operator(
                    db_path=args.db,
                    output_dir=args.output_dir,
                    command=parse_operator_command(args.operator_command),
                    operator_label="command",
                    profile_id=args.profile_id,
                    run_id=args.run_id,
                    since=since,
                    schema_path=args.schema,
                    timeout_seconds=args.timeout,
                    max_retries=args.max_retries,
                )
            else:
                adapter_id = args.operator_adapter if args.operator == "adapter" else args.operator
                if not adapter_id:
                    raise AnalyzeError("operator_adapter_required")
                report = run_registered_operator_adapter(
                    db_path=args.db,
                    adapter_id=adapter_id,
                    output_dir=args.output_dir,
                    profile_id=args.profile_id,
                    run_id=args.run_id,
                    since=since,
                    schema_path=args.schema,
                    timeout_seconds=args.timeout,
                    max_retries=args.max_retries,
                )
        except (AnalyzeError, OperatorAdapterError, StorageError) as exc:
            print(f"analysis failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    {
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
                        if report.raw_output_path
                        else None,
                    },
                    sort_keys=True,
                )
            )
        else:
            print(f"analysis complete: {report.proposal_id}")
            print(f"operator: {report.operator}")
            print(f"profile: {report.profile_id}")
            if report.operator_run_id:
                print(f"operator_run: {report.operator_run_id}")
            print(f"evidence: {report.evidence_path}")
            print(f"prompt: {report.prompt_path}")
            print(f"proposal: {report.proposal_path}")
            if report.raw_output_path:
                print(f"raw_output: {report.raw_output_path}")
            print(f"persisted: {report.persisted}")
        return 0

    if args.command == "improve":
        try:
            report = run_improvement_loop(
                db_path=args.db,
                output_dir=args.output_dir,
                proposal_id=args.proposal_id,
                operator=args.operator,
                operator_command=parse_operator_command(args.operator_command)
                if args.operator_command
                else None,
                operator_adapter=args.operator_adapter,
                operator_timeout_seconds=args.operator_timeout,
                operator_max_retries=args.operator_max_retries,
                profile_id=args.profile_id,
                run_id=args.run_id,
                schema_path=args.schema,
                replay_adapter_id=args.replay_adapter,
                replay_output_dir=args.replay_output_dir,
                replay_timeout_seconds=args.replay_timeout,
                run_autonomy_after=not args.no_autonomy,
                harness_workspace_root=args.harness_workspace_root,
                source_candidate_id=args.source_candidate_id,
                source_home=args.source_home,
                source_import_output_dir=args.source_import_output_dir,
            )
        except (ImproveError, AnalyzeError, StorageError) as exc:
            print(f"improve failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"improve complete: {report.proposal_id}")
            print(f"profile: {report.profile_id}")
            if report.source_import:
                print(f"source_import: {report.source_import.candidate['id']}")
            if report.operator:
                print(f"operator: {report.operator}")
            for check_spec_id in report.check_spec_ids:
                print(f"check_spec: {check_spec_id}")
            for replay in report.replay_runs:
                print(f"replay_run: {replay.get('replay_run_id')}")
                check_run = replay.get("check_run")
                if isinstance(check_run, dict):
                    print(f"check_status: {check_run.get('status')}")
            if report.autonomy is not None:
                for decision in report.autonomy.decisions:
                    print(
                        f"autonomy: {decision.proposal_id} "
                        f"{decision.action} ({decision.reason})"
                    )
                    for skill_id in decision.applied_skill_ids:
                        print(f"skill: {skill_id}")
                    for rule_id in decision.applied_context_rule_ids:
                        print(f"context_rule: {rule_id}")
                    for patch_transaction_id in decision.patch_transaction_ids:
                        print(f"patch_transaction: {patch_transaction_id}")
            for note in report.notes:
                print(f"note: {note}")
        return 0

    if args.command == "operator-adapter-register":
        try:
            report = register_operator_adapter(
                db_path=args.db,
                adapter_id=args.adapter_id,
                name=args.name,
                operator_kind=args.kind,
                command=parse_operator_adapter_command(args.adapter_command),
                profile_id=args.profile_id,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout,
                enabled=not args.disabled,
            )
        except (OperatorAdapterError, StorageError) as exc:
            print(f"operator adapter registration failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "adapter_id": report.adapter_id,
            "profile_id": report.profile_id,
            "name": report.name,
            "operator_kind": report.operator_kind,
            "command": list(report.command),
            "output_dir": report.output_dir,
            "timeout_seconds": report.timeout_seconds,
            "enabled": report.enabled,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"operator adapter registered: {report.adapter_id}")
            print(f"profile: {report.profile_id}")
            print(f"name: {report.name}")
            print(f"kind: {report.operator_kind}")
            print(f"enabled: {report.enabled}")
        return 0

    if args.command == "operator-adapter-bootstrap":
        if args.list_presets:
            presets = list_operator_presets()
            if args.json:
                print(json.dumps({"operator_presets": presets}, sort_keys=True))
            else:
                for preset in presets:
                    print(
                        f"{preset['adapter_id']} "
                        f"[{preset['operator_kind']}] "
                        f"{' '.join(preset['command'])}"
                    )
            return 0

        try:
            report = bootstrap_operator_adapters(
                db_path=args.db,
                target=args.target,
                profile_id=args.profile_id,
                output_dir=args.output_dir,
                timeout_seconds=args.timeout,
                enabled=not args.disabled,
            )
        except (OperatorAdapterError, StorageError) as exc:
            print(f"operator adapter bootstrap failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            if not report.registered:
                print("no operator adapters registered")
            for registered in report.registered:
                print(f"operator adapter registered: {registered.adapter_id}")
                print(f"profile: {registered.profile_id}")
                print(f"kind: {registered.operator_kind}")
            for skipped in report.skipped:
                print(
                    f"skipped: {skipped['adapter_id']} "
                    f"({skipped['reason']}:{skipped['command']})"
                )
        return 0

    if args.command == "operator-adapters":
        adapters = list_operator_adapters(args.db)
        if args.json:
            print(json.dumps({"operator_adapters": adapters}, sort_keys=True))
        else:
            if not adapters:
                print("no operator adapters")
            for adapter in adapters:
                print(
                    f"{adapter['id']} "
                    f"[{adapter['operator_kind']}] "
                    f"{adapter['name']}"
                )
        return 0

    if args.command == "operator-runs":
        runs = list_operator_runs(args.db)
        if args.json:
            print(json.dumps({"operator_runs": runs}, sort_keys=True))
        else:
            if not runs:
                print("no operator runs")
            for run in runs:
                print(
                    f"{run['id']} "
                    f"[{run['operator_label']}/{run['status']}] "
                    f"{run.get('proposal_id') or 'no proposal'}"
                )
        return 0

    if args.command == "operator-adapter-run":
        try:
            report = run_registered_operator_adapter(
                db_path=args.db,
                adapter_id=args.adapter_id,
                output_dir=args.output_dir,
                profile_id=args.profile_id,
                run_id=args.run_id,
                schema_path=args.schema,
                timeout_seconds=args.timeout,
                max_retries=args.max_retries,
            )
        except (OperatorAdapterError, StorageError) as exc:
            print(f"operator adapter run failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "adapter_id": args.adapter_id,
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
            if report.raw_output_path
            else None,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"operator adapter run complete: {args.adapter_id}")
            print(f"profile: {report.profile_id}")
            if report.operator_run_id:
                print(f"operator_run: {report.operator_run_id}")
            print(f"proposal: {report.proposal_id}")
            print(f"evidence: {report.evidence_path}")
            print(f"prompt: {report.prompt_path}")
            print(f"proposal_path: {report.proposal_path}")
            if report.raw_output_path:
                print(f"raw_output: {report.raw_output_path}")
        return 0

    if args.command == "operator-smoke":
        try:
            operator_command = (
                parse_operator_command(args.operator_command) if args.operator_command else None
            )
            if args.all_presets:
                if args.operator != "mock":
                    raise OperatorSmokeError("operator_not_allowed_with_all_presets")
                if operator_command is not None:
                    raise OperatorSmokeError("command_not_allowed_with_all_presets")
                if args.operator_adapter:
                    raise OperatorSmokeError("operator_adapter_not_allowed_with_all_presets")
                if args.expect_failure:
                    if args.prepare_only:
                        raise OperatorSmokeError("expect_failure_not_allowed_with_prepare_only")
                    expected_failure_kind = _expected_failure_kind_arg(args.expected_failure_kind)
                    report = run_operator_failure_smoke_matrix(
                        db_path=args.db,
                        output_dir=args.output_dir,
                        profile_id=args.profile_id,
                        run_id=args.run_id,
                        schema_path=args.schema,
                        timeout_seconds=args.timeout,
                        max_retries=args.max_retries,
                        skip_missing=not args.fail_on_missing,
                        expected_failure_kind=expected_failure_kind,
                        prompt_failure_mode=args.failure_mode,
                    )
                else:
                    report = run_operator_smoke_matrix(
                        prepare_only=args.prepare_only,
                        db_path=args.db,
                        output_dir=args.output_dir,
                        profile_id=args.profile_id,
                        run_id=args.run_id,
                        schema_path=args.schema,
                        timeout_seconds=args.timeout,
                        max_retries=args.max_retries,
                        skip_missing=not args.fail_on_missing,
                    )
                payload = report.to_json()
                if args.json:
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print(f"operator smoke matrix: {len(report.targets)} operators")
                    print(f"passed: {report.passed}")
                    print(f"summary: {payload['summary']}")
                    print(f"db: {report.db_path}")
                    print(f"output_dir: {report.output_dir}")
                    for target in payload["targets"]:
                        reason = f" reason={target['reason']}" if target["reason"] else ""
                        print(f"{target['operator']}: {target['status']}{reason}")
                return 0 if report.passed else 1
            if args.expect_failure and args.prepare_only:
                raise OperatorSmokeError("expect_failure_not_allowed_with_prepare_only")
            if args.prepare_only:
                plan = build_operator_smoke_plan(
                    operator=args.operator,
                    db_path=args.db,
                    output_dir=args.output_dir,
                    operator_command=operator_command,
                    operator_adapter=args.operator_adapter,
                    profile_id=args.profile_id,
                    run_id=args.run_id,
                    schema_path=args.schema,
                )
                payload = plan.to_json()
                if args.json:
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print(f"operator smoke prepared: {plan.operator}")
                    print(f"profile: {plan.profile_id}")
                    print(f"db: {plan.db_path}")
                    print(f"output_dir: {plan.output_dir}")
                    print(f"demo_database: {plan.used_demo_database}")
                    print(f"evidence: {plan.evidence_path}")
                    print(f"prompt: {plan.prompt_path}")
                    if plan.shell_command:
                        print(f"command: {plan.shell_command}")
                    else:
                        print("command: unavailable")
                return 0
            if args.expect_failure:
                expected_failure_kind = _expected_failure_kind_arg(args.expected_failure_kind)
                report = run_operator_failure_smoke(
                    operator=args.operator,
                    db_path=args.db,
                    output_dir=args.output_dir,
                    operator_command=operator_command,
                    operator_adapter=args.operator_adapter,
                    profile_id=args.profile_id,
                    run_id=args.run_id,
                    schema_path=args.schema,
                    timeout_seconds=args.timeout,
                    max_retries=args.max_retries,
                    expected_failure_kind=expected_failure_kind,
                    prompt_failure_mode=args.failure_mode,
                )
                payload = report.to_json()
                if args.json:
                    print(json.dumps(payload, sort_keys=True))
                else:
                    print(f"operator failure smoke: {report.operator}")
                    print(f"passed: {report.passed}")
                    print(f"status: {report.status}")
                    print(f"failure_kind: {report.failure_kind}")
                    print(f"error: {report.error}")
                    print(f"db: {report.db_path}")
                    print(f"output_dir: {report.output_dir}")
                    if report.raw_output_path:
                        print(f"raw_output: {report.raw_output_path}")
                return 0 if report.passed else 1
            report = run_operator_smoke(
                operator=args.operator,
                db_path=args.db,
                output_dir=args.output_dir,
                operator_command=operator_command,
                operator_adapter=args.operator_adapter,
                profile_id=args.profile_id,
                run_id=args.run_id,
                schema_path=args.schema,
                timeout_seconds=args.timeout,
                max_retries=args.max_retries,
            )
        except (OperatorSmokeError, AnalyzeError, OperatorAdapterError, StorageError) as exc:
            print(f"operator smoke failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"operator smoke complete: {report.operator}")
            print(f"profile: {report.profile_id}")
            print(f"proposal: {report.proposal_id}")
            if report.operator_run_id:
                print(f"operator_run: {report.operator_run_id}")
            print(f"db: {report.db_path}")
            print(f"output_dir: {report.output_dir}")
            print(f"demo_database: {report.used_demo_database}")
            print(f"evidence: {report.evidence_path}")
            print(f"prompt: {report.prompt_path}")
            print(f"proposal_path: {report.proposal_path}")
            if report.raw_output_path:
                print(f"raw_output: {report.raw_output_path}")
        return 0

    if args.command == "mcp":
        if args.mcp_command == "serve":
            try:
                serve_stdio(db_path=args.db, schema_path=args.schema)
            except (McpError, StorageError) as exc:
                print(f"mcp serve failed: {exc}", file=sys.stderr)
                return 1
            return 0
        if args.mcp_command == "config":
            payload = build_mcp_config(
                db_path=args.db,
                schema_path=args.schema,
                server_name=args.name,
                target=args.target,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.mcp_command == "install-plan":
            plan = build_mcp_install_plan(
                db_path=args.db,
                schema_path=args.schema,
                server_name=args.name,
                target=args.target,
                scope=args.scope,
            )
            payload = plan.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(f"target: {plan.target}")
                print(f"server: {plan.server}")
                if plan.shell_command:
                    print(f"command: {plan.shell_command}")
                else:
                    print("command: unavailable")
                if plan.config_path_hint:
                    print(f"config_path_hint: {plan.config_path_hint}")
                for note in plan.notes:
                    print(f"note: {note}")
            return 0
        if args.mcp_command == "install-smoke":
            try:
                if args.all_targets:
                    if args.target:
                        raise McpError("target_not_allowed_with_all_targets")
                    if args.client_command:
                        raise McpError("client_command_not_allowed_with_all_targets")
                    if args.output_dir:
                        report = run_mcp_install_smoke_matrix(
                            db_path=args.db,
                            schema_path=args.schema,
                            server_name=args.name,
                            scope=args.scope,
                            output_dir=args.output_dir,
                            timeout_seconds=args.timeout_seconds,
                            verify_list=not args.skip_list_verify,
                            skip_missing=not args.fail_on_missing,
                        )
                        temporary = False
                    else:
                        with TemporaryDirectory() as tmpdir:
                            report = run_mcp_install_smoke_matrix(
                                db_path=args.db,
                                schema_path=args.schema,
                                server_name=args.name,
                                scope=args.scope,
                                output_dir=Path(tmpdir) / "mcp-install-smoke",
                                timeout_seconds=args.timeout_seconds,
                                verify_list=not args.skip_list_verify,
                                skip_missing=not args.fail_on_missing,
                            )
                        temporary = True
                elif not args.target:
                    raise McpError("target_required")
                elif args.output_dir:
                    report = run_mcp_install_smoke(
                        db_path=args.db,
                        schema_path=args.schema,
                        server_name=args.name,
                        target=args.target,
                        scope=args.scope,
                        output_dir=args.output_dir,
                        client_command=args.client_command,
                        timeout_seconds=args.timeout_seconds,
                        verify_list=not args.skip_list_verify,
                    )
                    temporary = False
                else:
                    with TemporaryDirectory() as tmpdir:
                        report = run_mcp_install_smoke(
                            db_path=args.db,
                            schema_path=args.schema,
                            server_name=args.name,
                            target=args.target,
                            scope=args.scope,
                            output_dir=Path(tmpdir) / "mcp-install-smoke",
                            client_command=args.client_command,
                            timeout_seconds=args.timeout_seconds,
                            verify_list=not args.skip_list_verify,
                        )
                    temporary = True
            except (McpError, StorageError) as exc:
                print(f"mcp install smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            payload["temporary"] = temporary
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            elif args.all_targets:
                print(f"server: {report.server}")
                print(f"passed: {report.passed}")
                print(f"summary: {payload['summary']}")
                print(f"output_dir: {report.output_dir}")
                print(f"temporary: {temporary}")
                for result in payload["results"]:
                    reason = f" reason={result['reason']}" if result["reason"] else ""
                    print(f"{result['target']}: {result['status']}{reason}")
            else:
                print(f"target: {report.target}")
                print(f"server: {report.server}")
                print(f"passed: {report.passed}")
                print(f"returncode: {report.returncode}")
                print(f"command: {' '.join(report.command)}")
                if report.config_path_hint:
                    print(f"config_path_hint: {report.config_path_hint}")
                    print(f"config_exists: {report.config_exists}")
                if report.list_command:
                    print(f"list_command: {shlex.join(report.list_command)}")
                    print(f"list_returncode: {report.list_returncode}")
                    print(f"list_verified: {report.list_verified}")
                print(f"temporary: {temporary}")
                for note in report.notes:
                    print(f"note: {note}")
            return 0 if report.passed else 1
        if args.mcp_command == "install":
            payload = write_mcp_config(
                output_path=args.output,
                db_path=args.db,
                schema_path=args.schema,
                server_name=args.name,
                target=args.target,
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "target": args.target,
                            "output": str(args.output),
                            "server": args.name,
                            "config": payload,
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(f"wrote MCP config: {args.output}")
                print(f"target: {args.target}")
                print(f"server: {args.name}")
            return 0
        parser.error("mcp subcommand required")

    if args.command == "generate-checks":
        try:
            report = generate_checks_for_proposal(
                db_path=args.db,
                proposal_id=args.proposal_id,
            )
        except (CheckError, StorageError) as exc:
            print(f"check generation failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "proposal_id": report.proposal_id,
            "profile_id": report.profile_id,
            "check_spec_ids": list(report.check_spec_ids),
            "existing_check_spec_ids": list(report.existing_check_spec_ids),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"check generation complete: {report.proposal_id}")
            for check_spec_id in report.check_spec_ids:
                print(f"check_spec: {check_spec_id}")
            for check_spec_id in report.existing_check_spec_ids:
                print(f"existing_check_spec: {check_spec_id}")
        return 0

    if args.command == "checks":
        check_specs = list_check_specs(args.db)
        check_runs = list_check_runs(args.db)
        replay_runs = list_replay_runs(args.db)
        if args.json:
            print(
                json.dumps(
                    {
                        "check_specs": check_specs,
                        "check_runs": check_runs,
                        "replay_runs": replay_runs,
                    },
                    sort_keys=True,
                )
            )
        else:
            if not check_specs:
                print("no check specs")
            for check_spec in check_specs:
                print(
                    f"{check_spec['id']} "
                    f"[{check_spec['check_type']}/{check_spec['trust_level']}] "
                    f"{check_spec['name']}"
                )
            if replay_runs:
                print(f"replay_runs: {len(replay_runs)}")
            if check_runs:
                print(f"check_runs: {len(check_runs)}")
        return 0

    if args.command == "check-assertion-presets":
        presets = list_assertion_presets()
        if args.json:
            print(json.dumps({"assertion_presets": presets}, sort_keys=True))
        else:
            for preset in presets:
                assertion_names = ", ".join(preset.get("assertions", []))
                print(f"{preset['name']}: {assertion_names}")
        return 0

    if args.command == "check-capabilities":
        capabilities = list_check_capabilities()
        if args.json:
            print(json.dumps(capabilities, sort_keys=True))
        else:
            print("check_types:")
            for check_type in capabilities["check_types"]:
                gate = "gateable" if check_type["gateable"] else "informational"
                print(f"  {check_type['name']}: {gate}")
            print("assertion_presets:")
            for preset in capabilities["assertion_presets"]:
                print(f"  {preset['name']}")
        return 0

    if args.command == "check-locks":
        try:
            locks = list_check_locks(
                args.db,
                profile_id=args.profile_id,
                locked_only=not args.include_unlocked,
            )
        except StorageError as exc:
            print(f"check spec locks failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"check_locks": locks}, sort_keys=True))
        else:
            if not locks:
                print("no check spec locks")
            for lock in locks:
                state = "locked" if lock.get("human_locked") else "unlocked"
                reason = f" reason={lock['reason']}" if lock.get("reason") else ""
                print(f"{lock['profile_id']} {lock['check_spec_id']} [{state}]{reason}")
        return 0

    if args.command in {"check-lock", "check-unlock"}:
        try:
            report = set_check_lock(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                locked=args.command == "check-lock",
                reason=args.reason,
                actor_agent_identity_id=args.actor_agent_identity_id,
            )
        except (CheckError, StorageError) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True))
        else:
            print(f"check_spec: {report.check_spec_id}")
            print(f"human_locked: {report.human_locked}")
            if report.reason:
                print(f"reason: {report.reason}")
            if report.actor_agent_identity_id:
                print(f"actor_agent_identity_id: {report.actor_agent_identity_id}")
        return 0

    if args.command == "check-approve":
        try:
            report = approve_check_spec(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                reason=args.reason,
                actor_agent_identity_id=args.actor_agent_identity_id,
            )
        except (CheckError, StorageError) as exc:
            print(f"check-approve failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report.to_json(), sort_keys=True))
        else:
            print(f"check_spec: {report.check_spec_id}")
            print(f"previous_trust_level: {report.previous_trust_level}")
            print(f"trust_level: {report.trust_level}")
            if report.reason:
                print(f"reason: {report.reason}")
            if report.actor_agent_identity_id:
                print(f"actor_agent_identity_id: {report.actor_agent_identity_id}")
        return 0

    if args.command == "check-detail":
        try:
            detail = get_check_detail(db_path=args.db, check_spec_id=args.check_spec_id)
        except (DetailError, StorageError) as exc:
            print(f"check detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(detail, sort_keys=True))
        else:
            check_spec = detail["check_spec"]
            summary = detail["summary"]
            print(f"check_spec: {check_spec['id']}")
            print(f"name: {check_spec['name']}")
            print(f"trust_level: {summary['trust_level']}")
            print(f"latest_status: {summary['latest_status']}")
            print(f"latest_comparison: {summary['latest_comparison'] or 'n/a'}")
            assertions = summary.get("latest_assertion_counts", {})
            print(
                "assertions: "
                f"{assertions.get('passed', 0)}/{assertions.get('total', 0)} passed"
            )
            for assertion in summary.get("latest_assertions", []):
                status = "pass" if assertion.get("passed") else "fail"
                reason = assertion.get("reason") or "unknown"
                assertion_type = assertion.get("type") or "unknown"
                print(
                    f"  {assertion.get('index', '?')}. "
                    f"{status} {assertion_type}: {reason}"
                )
                if assertion.get("path") is not None:
                    print(
                        f"     {assertion.get('path')}: "
                        f"expected={assertion.get('expected')!r} "
                        f"actual={assertion.get('actual')!r}"
                    )
            print(f"replay_runs: {summary['replay_runs']}")
        return 0

    if args.command == "replay-detail":
        try:
            detail = get_replay_detail(db_path=args.db, replay_run_id=args.replay_run_id)
        except (DetailError, StorageError) as exc:
            print(f"replay detail failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(detail, sort_keys=True))
        else:
            replay_run = detail["replay_run"]
            summary = detail["summary"]
            print(f"replay_run: {replay_run['id']}")
            print(f"status: {summary['status']}")
            print(f"mode: {summary['mode']}")
            print(f"side_effect_mode: {summary['side_effect_mode']}")
            print(f"actual_side_effect_mode: {summary['actual_side_effect_mode'] or 'unknown'}")
            print(f"source_run: {summary['source_run_id'] or 'none'}")
            print(f"output_run: {summary['output_run_id'] or 'none'}")
            print(f"check_runs: {summary['check_runs']}")
            print(f"artifacts: {summary.get('artifacts', 0)}")
            for artifact in detail.get("artifacts", []):
                print(
                    f"  {artifact.get('kind', 'artifact')}: "
                    f"{artifact.get('path')} "
                    f"({artifact.get('size_bytes') if artifact.get('exists') else 'missing'} bytes)"
                )
                preview = str(artifact.get("preview") or "").strip()
                if preview:
                    print(f"     {preview[:200]}")
        return 0

    if args.command == "replay":
        try:
            report = create_replay_run(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                mode=args.mode,
                side_effect_mode=args.side_effect_mode,
                source_run_id=args.source_run_id,
            )
        except (CheckError, StorageError) as exc:
            print(f"replay failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "replay_run_id": report.replay_run_id,
            "profile_id": report.profile_id,
            "proposal_id": report.proposal_id,
            "check_spec_id": report.check_spec_id,
            "source_run_id": report.source_run_id,
            "mode": report.mode,
            "side_effect_mode": report.side_effect_mode,
            "status": report.status,
            "result": report.result,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay complete: {report.replay_run_id}")
            print(f"check_spec: {report.check_spec_id}")
            print(f"status: {report.status}")
            print(f"side_effect_mode: {report.side_effect_mode}")
        return 0

    if args.command == "complete-replay":
        try:
            report = complete_replay_from_fixture(
                db_path=args.db,
                replay_run_id=args.replay_run_id,
                fixture_path=args.fixture,
            )
        except (CheckError, StorageError) as exc:
            print(f"replay completion failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "replay_run_id": report.replay_run_id,
            "profile_id": report.profile_id,
            "check_spec_id": report.check_spec_id,
            "output_run_id": report.output_run_id,
            "status": report.status,
            "result": report.result,
            "ingested_counts": report.ingest_report.inserted_counts,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay completed: {report.replay_run_id}")
            print(f"check_spec: {report.check_spec_id}")
            print(f"output_run: {report.output_run_id}")
            print(f"status: {report.status}")
        return 0

    if args.command == "replay-command":
        try:
            report = run_replay_command(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                output_dir=args.output_dir,
                command=parse_replay_command(args.replay_command),
                mode=args.mode,
                side_effect_mode=args.side_effect_mode,
                source_run_id=args.source_run_id,
                timeout_seconds=args.timeout,
                run_check_after=args.run_check,
            )
        except (CheckError, StorageError) as exc:
            print(f"replay command failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "replay_run_id": report.replay_run_id,
            "profile_id": report.profile_id,
            "check_spec_id": report.check_spec_id,
            "request_path": str(report.request_path),
            "result_path": str(report.result_path),
            "raw_output_path": str(report.raw_output_path),
            "output_run_id": report.completion.output_run_id,
            "status": report.completion.status,
            "result": report.completion.result,
            "check_run": {
                "check_run_id": report.check_run.check_run_id,
                "status": report.check_run.status,
                "promoted_trust_level": report.check_run.promoted_trust_level,
                "result": report.check_run.result,
            }
            if report.check_run is not None
            else None,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay command complete: {report.replay_run_id}")
            print(f"request: {report.request_path}")
            print(f"result: {report.result_path}")
            print(f"raw_output: {report.raw_output_path}")
            print(f"output_run: {report.completion.output_run_id}")
            if report.check_run is not None:
                print(f"check_run: {report.check_run.check_run_id}")
                print(f"check_status: {report.check_run.status}")
        return 0

    if args.command == "replay-server-health":
        try:
            report = check_replay_server_health(
                server_url=args.server_url,
                health_path=args.health_path,
                timeout_seconds=args.timeout,
                allow_remote_server=args.allow_remote_server,
            )
        except ReplayServerError as exc:
            print(f"replay server health failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "server_url": report.server_url,
            "health_path": report.health_path,
            "ok": report.ok,
            "response": report.response,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server healthy: {report.server_url}")
        return 0

    if args.command == "replay-server-run":
        try:
            report = run_replay_server(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                server_url=args.server_url,
                health_path=args.health_path,
                replay_path=args.replay_path,
                mode=args.mode,
                side_effect_mode=args.side_effect_mode,
                source_run_id=args.source_run_id,
                timeout_seconds=args.timeout,
                trace_endpoint=args.trace_endpoint,
                check_health=not args.skip_health,
                run_check_after=args.run_check,
                allow_remote_server=args.allow_remote_server,
            )
        except (CheckError, ReplayServerError, StorageError) as exc:
            print(f"replay server run failed: {exc}", file=sys.stderr)
            return 1
        payload = _replay_run_report_payload(report, adapter_id=None)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server run complete: {report.replay_run_id}")
            print(f"server: {report.server_url}")
            print(f"output_run: {report.completion.output_run_id}")
            if report.check_run is not None:
                print(f"check_status: {report.check_run.status}")
        return 0

    if args.command == "replay-server-template":
        try:
            report = write_replay_server_template(
                output_path=args.output_path,
                framework=args.framework,
                profile_name=args.profile_name,
                force=args.force,
            )
        except ReplayTemplateError as exc:
            print(f"replay server template failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "output_path": str(report.output_path),
            "framework": report.framework,
            "profile_name": report.profile_name,
            "wrote": report.wrote,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server template written: {report.output_path}")
            print(f"framework: {report.framework}")
        return 0

    if args.command == "source-adapter-template":
        try:
            report = write_source_adapter_template(
                output_path=args.output,
                framework=args.framework,
                profile_name=args.profile_name,
                force=args.force,
            )
        except SourceTemplateError as exc:
            print(f"source adapter template failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "output_path": str(report.output_path),
            "framework": report.framework,
            "profile_name": report.profile_name,
            "wrote": report.wrote,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"source adapter template written: {report.output_path}")
            print(f"framework: {report.framework}")
        return 0

    if args.command == "integration-smoke":
        if args.integration_command == "source":
            try:
                report = run_source_adapter_smoke(
                    db_path=args.db,
                    adapter_path=args.adapter_path,
                    hook=args.hook,
                    output_dir=args.output_dir,
                    profile_id=args.profile_id,
                    profile_name=args.profile_name,
                    root_path=args.root_path,
                    source_id=args.source_id,
                    agent_id=args.agent_id,
                    agent_name=args.agent_name,
                    python_executable=args.python_executable,
                    cwd=args.cwd,
                    timeout_seconds=args.timeout,
                )
            except IntegrationSmokeError as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: source adapter")
                print(f"profile: {report.profile_id}")
                print(f"source_events: {report.source_events_path}")
                print(f"stdout: {report.stdout_path}")
                print(f"stderr: {report.stderr_path}")
            return 0

        if args.integration_command == "framework-source":
            try:
                report = run_installed_framework_source_smoke(
                    db_path=args.db,
                    framework=args.framework,
                    python_executable=args.python_executable,
                    output_dir=args.output_dir,
                    timeout_seconds=args.timeout,
                )
            except FrameworkSmokeError as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: installed framework source")
                print(f"framework: {report.framework}")
                print(f"package: {report.framework_package} {report.framework_version}")
                print(f"python: {report.python_executable}")
                print(f"profile: {report.source_smoke.profile_id}")
                print(f"output_dir: {report.output_dir}")
            return 0 if report.passed else 1

        if args.integration_command == "framework-replay":
            try:
                report = run_installed_framework_replay_smoke(
                    framework=args.framework,
                    python_executable=args.python_executable,
                    output_dir=args.output_dir,
                    timeout_seconds=args.timeout,
                )
            except FrameworkSmokeError as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: installed framework replay")
                print(f"framework: {report.framework}")
                print(f"package: {report.framework_package} {report.framework_version}")
                print(f"python: {report.python_executable}")
                print(f"server: {report.replay_server_url}")
                print(f"output_dir: {report.output_dir}")
            return 0 if report.passed else 1

        if args.integration_command == "framework-improve":
            try:
                report = run_installed_framework_improve_smoke(
                    db_path=args.db,
                    framework=args.framework,
                    python_executable=args.python_executable,
                    output_dir=args.output_dir,
                    schema_path=args.schema,
                    timeout_seconds=args.timeout,
                )
            except FrameworkSmokeError as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: installed framework improve")
                print(f"framework: {report.framework}")
                print(f"package: {report.framework_package} {report.framework_version}")
                print(f"python: {report.python_executable}")
                print(f"profile: {report.improve.profile_id}")
                print(f"proposal: {report.improve.proposal_id}")
                print(f"replay_adapter: {report.replay_adapter_id}")
                print(f"output_dir: {report.output_dir}")
            return 0 if report.passed else 1

        if args.integration_command == "opentelemetry-python":
            try:
                report = run_opentelemetry_sdk_smoke(
                    db_path=args.db,
                    python_executable=args.python_executable,
                    output_dir=args.output_dir,
                    timeout_seconds=args.timeout,
                )
            except OtlpSmokeError as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: OpenTelemetry Python SDK")
                print(f"package: opentelemetry-sdk {report.opentelemetry_sdk_version}")
                print(f"python: {report.python_executable}")
                print(f"profile: {report.ingest.profile_id}")
                print(f"output_dir: {report.output_dir}")
            return 0 if report.passed else 1

        if args.integration_command == "replay-server":
            replay_request = None
            if args.replay_request_json:
                try:
                    replay_request = json.loads(args.replay_request_json)
                except json.JSONDecodeError as exc:
                    print(f"integration smoke failed: invalid replay request JSON: {exc}", file=sys.stderr)
                    return 1
                if not isinstance(replay_request, dict):
                    print("integration smoke failed: replay request JSON must be an object", file=sys.stderr)
                    return 1
            try:
                report = run_replay_server_smoke(
                    command=parse_replay_command(args.integration_replay_command),
                    server_url=args.server_url,
                    output_dir=args.output_dir,
                    health_path=args.health_path,
                    run_replay=args.run_replay or replay_request is not None,
                    replay_path=args.replay_path,
                    replay_request=replay_request,
                    replay_hook=args.hook,
                    replay_timeout_seconds=args.replay_timeout,
                    startup_timeout_seconds=args.startup_timeout,
                    stop_timeout_seconds=args.stop_timeout,
                    cwd=args.cwd,
                    log_max_bytes=args.log_max_bytes,
                )
            except (CheckError, IntegrationSmokeError) as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: replay server")
                print(f"server: {report.server_url}")
                print(f"healthy: {report.healthy}")
                if report.replay_request is not None:
                    print(f"replay_ok: {report.replay_ok}")
                print(f"stopped: {report.stopped}")
                print(f"stdout: {report.stdout_path}")
                print(f"stderr: {report.stderr_path}")
            return 0

        if args.integration_command == "improve":
            try:
                report = run_generated_improve_smoke(
                    db_path=args.db,
                    output_dir=args.output_dir,
                    framework=args.framework,
                    schema_path=args.schema,
                    timeout_seconds=args.timeout,
                )
            except ImproveSmokeError as exc:
                print(f"integration smoke failed: {exc}", file=sys.stderr)
                return 1
            payload = report.to_json()
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print("integration smoke passed: improve")
                print(f"framework: {report.framework}")
                print(f"profile: {report.improve.profile_id}")
                print(f"proposal: {report.improve.proposal_id}")
                print(f"replay_adapter: {report.replay_adapter_id}")
                print(f"output_dir: {report.output_dir}")
            return 0 if report.passed else 1

        print("integration smoke failed: missing subcommand", file=sys.stderr)
        return 1

    if args.command == "replay-server-start":
        try:
            report = start_registered_replay_server_adapter(
                db_path=args.db,
                adapter_id=args.adapter_id,
                output_dir=args.output_dir,
            )
        except (ReplayAdapterError, ReplayServerError, StorageError) as exc:
            print(f"replay server start failed: {exc}", file=sys.stderr)
            return 1
        payload = _replay_server_process_payload(report, adapter_id=args.adapter_id)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server running: {args.adapter_id}")
            print(f"server: {report.server_url}")
            print(f"pid: {report.pid}")
        return 0

    if args.command == "replay-server-status":
        try:
            report = registered_replay_server_status(
                db_path=args.db,
                adapter_id=args.adapter_id,
                output_dir=args.output_dir,
            )
        except (ReplayAdapterError, ReplayServerError, StorageError) as exc:
            print(f"replay server status failed: {exc}", file=sys.stderr)
            return 1
        payload = _replay_server_process_payload(report, adapter_id=args.adapter_id)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server: {args.adapter_id}")
            print(f"running: {report.running}")
            print(f"healthy: {report.healthy}")
            if report.pid is not None:
                print(f"pid: {report.pid}")
        return 0

    if args.command == "replay-server-logs":
        try:
            report = registered_replay_server_logs(
                db_path=args.db,
                adapter_id=args.adapter_id,
                output_dir=args.output_dir,
                max_bytes=args.max_bytes,
            )
        except (ReplayAdapterError, ReplayServerError, StorageError) as exc:
            print(f"replay server logs failed: {exc}", file=sys.stderr)
            return 1
        payload = _replay_server_logs_payload(report, adapter_id=args.adapter_id)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server logs: {args.adapter_id}")
            print(f"stdout: {report.stdout_path}")
            print(report.stdout.rstrip())
            print(f"stderr: {report.stderr_path}")
            print(report.stderr.rstrip())
        return 0

    if args.command == "replay-server-stop":
        try:
            report = stop_registered_replay_server_adapter(
                db_path=args.db,
                adapter_id=args.adapter_id,
                output_dir=args.output_dir,
            )
        except (ReplayAdapterError, ReplayServerError, StorageError) as exc:
            print(f"replay server stop failed: {exc}", file=sys.stderr)
            return 1
        payload = _replay_server_process_payload(report, adapter_id=args.adapter_id)
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay server stopped: {args.adapter_id}")
            print(f"stopped: {report.stopped}")
        return 0

    if args.command == "replay-adapter-register":
        try:
            report = register_replay_adapter(
                db_path=args.db,
                adapter_id=args.adapter_id,
                name=args.name,
                command=parse_adapter_command(args.adapter_command) if args.adapter_command else None,
                server_url=args.server_url,
                health_path=args.health_path,
                replay_path=args.replay_path,
                startup_timeout_seconds=args.startup_timeout,
                cwd=args.cwd,
                profile_id=args.profile_id,
                output_dir=args.output_dir,
                default_mode=args.mode,
                default_side_effect_mode=args.side_effect_mode,
                timeout_seconds=args.timeout,
                enabled=not args.disabled,
                allow_remote_server=args.allow_remote_server,
            )
        except (ReplayAdapterError, StorageError) as exc:
            print(f"replay adapter registration failed: {exc}", file=sys.stderr)
            return 1
        payload = {
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
            "allow_remote_server": report.allow_remote_server,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay adapter registered: {report.adapter_id}")
            print(f"profile: {report.profile_id}")
            print(f"name: {report.name}")
            print(f"enabled: {report.enabled}")
        return 0

    if args.command == "replay-adapters":
        adapters = list_replay_adapters(args.db)
        if args.json:
            print(json.dumps({"replay_adapters": adapters}, sort_keys=True))
        else:
            if not adapters:
                print("no replay adapters")
            for adapter in adapters:
                print(
                    f"{adapter['id']} "
                    f"[{adapter['default_mode']}/{adapter['default_side_effect_mode']}] "
                    f"{adapter['name']}"
                )
        return 0

    if args.command == "replay-adapter-run":
        try:
            report = run_registered_replay_adapter(
                db_path=args.db,
                adapter_id=args.adapter_id,
                check_spec_id=args.check_spec_id,
                output_dir=args.output_dir,
                mode=args.mode,
                side_effect_mode=args.side_effect_mode,
                source_run_id=args.source_run_id,
                timeout_seconds=args.timeout,
                run_check_after=args.run_check,
            )
        except (CheckError, ReplayAdapterError, ReplayServerError, StorageError) as exc:
            print(f"replay adapter run failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            **_replay_run_report_payload(report, adapter_id=args.adapter_id),
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"replay adapter run complete: {args.adapter_id}")
            print(f"replay_run: {report.replay_run_id}")
            print(f"output_run: {report.completion.output_run_id}")
            if report.check_run is not None:
                print(f"check_status: {report.check_run.status}")
        return 0

    if args.command == "run-check":
        try:
            report = run_check(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                replay_run_id=args.replay_run_id,
            )
        except (CheckError, StorageError) as exc:
            print(f"check failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "check_run_id": report.check_run_id,
            "profile_id": report.profile_id,
            "proposal_id": report.proposal_id,
            "check_spec_id": report.check_spec_id,
            "replay_run_id": report.replay_run_id,
            "status": report.status,
            "result": report.result,
            "promoted_trust_level": report.promoted_trust_level,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"check complete: {report.check_run_id}")
            print(f"check_spec: {report.check_spec_id}")
            print(f"status: {report.status}")
            if report.promoted_trust_level:
                print(f"promoted_trust_level: {report.promoted_trust_level}")
        return 0

    if args.command == "judge-command":
        try:
            command = parse_judge_command(args.judge_command)
            report = run_judge_command(
                db_path=args.db,
                check_spec_id=args.check_spec_id,
                output_dir=args.output_dir,
                command=command,
                replay_run_id=args.replay_run_id,
                timeout_seconds=args.timeout,
            )
        except (CheckError, StorageError) as exc:
            print(f"judge command failed: {exc}", file=sys.stderr)
            return 1
        payload = {
            "profile_id": report.profile_id,
            "proposal_id": report.proposal_id,
            "check_spec_id": report.check_spec_id,
            "request_path": str(report.request_path),
            "result_path": str(report.result_path),
            "raw_output_path": str(report.raw_output_path),
            "judgment": report.judgment,
            "check_run": {
                "check_run_id": report.check_run.check_run_id,
                "profile_id": report.check_run.profile_id,
                "proposal_id": report.check_run.proposal_id,
                "check_spec_id": report.check_run.check_spec_id,
                "replay_run_id": report.check_run.replay_run_id,
                "status": report.check_run.status,
                "result": report.check_run.result,
                "promoted_trust_level": report.check_run.promoted_trust_level,
            },
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"judge check complete: {report.check_run.check_run_id}")
            print(f"check_spec: {report.check_spec_id}")
            print(f"status: {report.check_run.status}")
            print(f"request: {report.request_path}")
            print(f"result: {report.result_path}")
            print(f"raw_output: {report.raw_output_path}")
        return 0

    if args.command == "judge-smoke":
        try:
            command = parse_judge_command(args.judge_command) if args.judge_command else None
            report = run_judge_smoke(
                db_path=args.db,
                output_dir=args.output_dir,
                command=command,
                prepare_only=args.prepare_only,
                provider_backed=args.provider_backed,
                schema_path=args.schema,
                timeout_seconds=args.timeout,
            )
        except (JudgeSmokeError, CheckError, StorageError) as exc:
            print(f"judge smoke failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            action = "prepared" if report.prepare_only else "complete"
            print(f"judge smoke {action}: {report.check_spec_id}")
            print(f"passed: {report.passed}")
            print(f"db: {report.db_path}")
            print(f"output_dir: {report.output_dir}")
            print(f"demo_database: {report.used_demo_database}")
            print(f"external_command_invoked: {report.external_command_invoked}")
            print(f"provider_backed: {report.provider_backed}")
            print(f"request: {report.request_path}")
            print(f"handoff: {report.handoff_path}")
            if not report.prepare_only:
                print(f"status: {report.check_status}")
                print(f"result: {report.result_path}")
                print(f"raw_output: {report.raw_output_path}")
        return 0 if report.passed else 1

    if args.command == "dashboard-smoke":
        try:
            report = run_dashboard_browser_smoke(
                db_path=args.db,
                output_dir=args.output_dir,
                seed_demo=not args.no_seed_demo,
                screenshot=args.screenshot,
                install_browser_deps=args.install_browser_deps,
                timeout_seconds=args.timeout,
            )
        except DashboardSmokeError as exc:
            payload = {
                "kind": "dashboard_browser_smoke",
                "passed": False,
                "error": str(exc),
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(f"dashboard smoke failed: {exc}", file=sys.stderr)
            return 1
        payload = report.to_json()
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            action = "passed" if report.passed else "failed"
            print(f"dashboard smoke {action}")
            print(f"db: {report.db_path}")
            print(f"server_url: {report.server_url}")
            print(f"viewports: {', '.join(viewport.name for viewport in report.viewports)}")
            if report.console_errors:
                print(f"console_errors: {len(report.console_errors)}")
            if report.page_errors:
                print(f"page_errors: {len(report.page_errors)}")
            if report.request_failures:
                print(f"request_failures: {len(report.request_failures)}")
        return 0 if report.passed else 1

    if args.command == "serve":
        auth_token = args.auth_token or os.environ.get("KYOKO_AUTH_TOKEN")
        default_lock_actor_agent_identity_id = (
            args.default_lock_actor_agent_identity_id
            or os.environ.get("KYOKO_DEFAULT_LOCK_ACTOR_AGENT_IDENTITY_ID")
        )
        if auth_token is None and not _is_loopback_host(args.host):
            auth_token = secrets.token_urlsafe(24)
        dashboard_url = f"http://{args.host}:{args.port}"
        if auth_token is not None:
            dashboard_url = f"{dashboard_url}/?token={auth_token}"
        print(f"serving Kyoko dashboard: {dashboard_url}")
        print(f"db: {args.db}")
        if auth_token is not None:
            print("auth: enabled")
        if default_lock_actor_agent_identity_id is not None:
            print(
                f"default_lock_actor_agent_identity_id: {default_lock_actor_agent_identity_id}"
            )
        try:
            serve(
                db_path=args.db,
                host=args.host,
                port=args.port,
                auth_token=auth_token,
                default_lock_actor_agent_identity_id=default_lock_actor_agent_identity_id,
            )
        except (StorageError, WebError) as exc:
            print(f"serve failed: {exc}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("stopped Kyoko dashboard")
            return 0
        return 0

    parser.print_help()
    return 0


def _replay_run_report_payload(report: object, *, adapter_id: Optional[str]) -> dict[str, object]:
    check_run = getattr(report, "check_run", None)
    completion = getattr(report, "completion")
    payload: dict[str, object] = {
        "adapter_id": adapter_id,
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
            value = getattr(report, attr)
            payload[attr] = str(value) if isinstance(value, Path) else value
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
    return payload


def _replay_server_process_payload(report: object, *, adapter_id: str) -> dict[str, object]:
    health = getattr(report, "health", None)
    return {
        "adapter_id": adapter_id,
        "server_url": getattr(report, "server_url"),
        "health_path": getattr(report, "health_path"),
        "command": list(getattr(report, "command")),
        "output_dir": str(getattr(report, "output_dir")),
        "state_path": str(getattr(report, "state_path")),
        "stdout_path": str(getattr(report, "stdout_path")),
        "stderr_path": str(getattr(report, "stderr_path")),
        "pid": getattr(report, "pid"),
        "running": getattr(report, "running"),
        "healthy": getattr(report, "healthy"),
        "started": getattr(report, "started"),
        "stopped": getattr(report, "stopped"),
        "health": {
            "server_url": health.server_url,
            "health_path": health.health_path,
            "ok": health.ok,
            "response": health.response,
        }
        if health is not None
        else None,
        "error": getattr(report, "error"),
    }


def _replay_server_logs_payload(report: object, *, adapter_id: str) -> dict[str, object]:
    return {
        "adapter_id": adapter_id,
        "output_dir": str(getattr(report, "output_dir")),
        "stdout_path": str(getattr(report, "stdout_path")),
        "stderr_path": str(getattr(report, "stderr_path")),
        "stdout": getattr(report, "stdout"),
        "stderr": getattr(report, "stderr"),
        "stdout_truncated": getattr(report, "stdout_truncated"),
        "stderr_truncated": getattr(report, "stderr_truncated"),
        "max_bytes": getattr(report, "max_bytes"),
    }


def _autonomy_event_action(kind: str) -> str:
    if kind == "autonomy_gated":
        return "gated"
    if kind in {"autonomy_applied", "autonomy_harness_applied"}:
        return "applied"
    if kind == "autonomy_harness_prepared":
        return "prepared"
    if kind == "autonomy_regression_rolled_back":
        return "rolled_back"
    if kind in {"autonomy_regression_failed", "autonomy_regression_rollback_failed"}:
        return "failed"
    return kind.removeprefix("autonomy_") or "unknown"


def _expected_failure_kind_arg(value: str) -> Optional[str]:
    normalized = value.strip()
    if normalized == "any":
        return None
    if not normalized:
        raise OperatorSmokeError("expected_failure_kind_required")
    return normalized


def _format_cli_args(args: object) -> str:
    if not isinstance(args, list):
        return ""
    return " ".join(shlex.quote(str(arg)) for arg in args)


def _add_db_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        type=Path,
        default=default_db_path(),
        help="Path to the Kyoko SQLite database.",
    )


def _on_off(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value == "on"


def _bundled_asset_entries() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for path in list_bundled_assets():
        kind = path.split("/", 1)[0]
        entries.append({"path": path, "kind": kind})
    return entries


def _fallback_evidence_refs_from_args(args: argparse.Namespace) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    if getattr(args, "evidence_span_id", None):
        refs.append(
            {
                "entity_type": "span",
                "entity_id": args.evidence_span_id,
                "role": "failure",
            }
        )
    if getattr(args, "evidence_run_id", None):
        refs.append(
            {
                "entity_type": "run",
                "entity_id": args.evidence_run_id,
                "role": "source",
            }
        )
    return refs


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"} or normalized.startswith("127.")
