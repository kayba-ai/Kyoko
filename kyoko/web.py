from __future__ import annotations

import json
import queue as _queue
import secrets
import shutil
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Type
from urllib.parse import parse_qs, quote, urlparse

from .analyze import (
    AnalyzeError,
    list_operator_runs,
    parse_operator_command,
    propose_for_issue,
)
from .apply import (
    ApplyError,
    apply_context_proposal,
    apply_proposal,
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
from .guard_monitor import GuardMonitorError, monitor_guarded_issues
from .blobs import list_payload_blobs, prune_payload_blobs, storage_report
from .dashboard_metrics import DashboardMetricsError, get_dashboard_metrics
from .demo import DemoError, run_demo_setup
from .details import (
    DetailError,
    get_check_detail,
    get_issue_detail,
    get_proposal_detail,
    get_replay_detail,
    get_run_detail,
    list_runs,
)
from .eval_detectors import DetectorError, get_detector, list_detectors, run_detector
from .evals_measure import EvalMeasureError, compare_eval_runs, get_measure_results, get_measure_run, list_measure_runs
from .llm_evals import (
    LlmEvalError,
    get_llm_eval,
    list_llm_evals,
    run_llm_eval,
    set_llm_eval_status,
)
from .issues import (
    IssueError,
    accept_issue,
    create_issue,
    list_issues,
    set_issue_comment,
    update_issue_status,
)
from .issue_guard import GuardError, mint_guard_for_issue
from .doctor import DEFAULT_SMOKE_EVIDENCE_DIR, run_doctor
from .evidence import build_evidence_bundle
from .checks import (
    CheckError,
    approve_check_spec,
    complete_replay_from_fixture,
    create_replay_run,
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
    run_judge_command,
    set_check_lock,
)
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
from .integration_smoke import (
    IntegrationSmokeError,
    run_replay_server_smoke,
    run_source_adapter_smoke,
)
from .load_smoke import LoadSmokeError, run_load_smoke
from .mcp import McpError, run_mcp_install_smoke_matrix
from .proposals import list_learning_proposals
from .redaction import (
    RedactionError,
)
from .retention import (
    RetentionError,
    prune_retained_data,
)
from .operator_adapters import (
    OperatorAdapterError,
    list_operator_adapters,
    run_registered_operator_adapter,
)
from .operator_presets import (
    OPERATOR_PRESETS,
    bootstrap_operator_adapters,
    list_operator_presets,
)
from . import cancellation
from .analysis_runner import (
    DASHBOARD_ANALYZERS,
    DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
    SCHEDULABLE_ANALYZERS,
    AnalysisJob,
    AnalysisRunError,
    AnalysisRunner,
    InlineAnalysisRunner,
    Scheduler,
    job_from_schedule,
    next_run_at_iso,
)
from .operator_smoke import (
    OperatorSmokeError,
    build_operator_smoke_plan,
    run_operator_smoke,
    run_operator_smoke_matrix,
)
from .live import (
    EVENT_PING,
    EVENT_RUN_UPSERT,
    LiveError,
    global_bus,
    ingest_live_events,
    list_live_events,
)
from .annotations import AnnotationError, create_annotation, delete_annotation, list_annotations
from .inspection import (
    InspectionError,
    get_current_run,
    get_run_outline,
    get_run_payload,
    get_run_scores,
    get_span_context,
    get_span_payload,
    search_run,
)
from .mcp_log import list_mcp_log
from .openclaw_import import OpenClawImportError, ingest_openclaw_sessions
from .otlp import OtlpNormalizeError, ingest_otlp_payload
from .otlp_protobuf import (
    OtlpProtobufError,
    decode_export_trace_service_request,
    looks_like_protobuf,
)
from .profile_next import ProfileNextError, run_profile_next_step
from .replay_adapters import (
    ReplayAdapterError,
    list_replay_adapters,
    registered_replay_server_logs,
    registered_replay_server_status,
    run_registered_replay_adapter,
    start_registered_replay_server_adapter,
    stop_registered_replay_server_adapter,
)
from .replay_servers import ReplayServerError
from .replay_templates import (
    SUPPORTED_FRAMEWORKS,
    ReplayTemplateError,
    write_replay_server_template,
)
from .skillbook import render_skillbook_prompt
from .source_templates import (
    SUPPORTED_SOURCE_FRAMEWORKS,
    SourceTemplateError,
    write_source_adapter_template,
)
from .source_discovery import SourceDiscoveryError, discover_local_sources, import_discovered_source
from .storage import (
    ANALYSIS_SCHEDULE_ANALYZER_KINDS,
    StorageError,
    checkpoint_database,
    create_analysis_schedule,
    delete_analysis_schedule,
    get_analysis_schedule,
    get_database_status,
    ingest_source_payload,
    initialize_database,
    list_analysis_schedules,
    status_to_json,
    update_analysis_schedule,
)
from .timeline import AUTONOMY_EVENT_KINDS, list_timeline_events


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Built React/Vite dashboard bundle, emitted by `frontend/` into the package so
# `kyoko serve` can ship and serve it as static files. When the bundle is absent
# (e.g. a source checkout that hasn't run `npm run build`), the server falls back
# to the inline HTML dashboard in ``_dashboard_html()``.
SPA_BUNDLE_DIR = Path(__file__).resolve().parent / "assets" / "web"

# Minimal content-type table for the static assets a Vite build emits. Kept local
# rather than relying on the platform ``mimetypes`` registry so behaviour is stable.
_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
}


class WebError(Exception):
    """Raised when the local Kyoko server cannot start."""


def spa_bundle_available() -> bool:
    """True when a built dashboard bundle (index.html) is present on disk."""

    return (SPA_BUNDLE_DIR / "index.html").is_file()


def _resolve_static_asset(rel_path: str) -> Optional[Path]:
    """Resolve a request path to a file inside the bundle dir, or None.

    Defends against path traversal by requiring the resolved file to stay within
    :data:`SPA_BUNDLE_DIR`.
    """

    cleaned = rel_path.lstrip("/")
    if not cleaned:
        return None
    base = SPA_BUNDLE_DIR.resolve()
    candidate = (base / cleaned).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _optional_string(value: Any) -> Optional[str]:
    return value if isinstance(value, str) and value.strip() else None


def serve(
    *,
    db_path: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    auth_token: Optional[str] = None,
    default_lock_actor_agent_identity_id: Optional[str] = None,
) -> None:
    initialize_database(db_path)
    if not _is_loopback_host(host) and not auth_token:
        raise WebError("auth_token_required_for_remote_host")
    # Background analysis worker + recurring scheduler. The runner serializes manual
    # ("Run now") and scheduled analyses through one execution/gate path. Both are daemon
    # threads, so they never block server shutdown; schedules only fire while serve runs.
    analysis_runner = AnalysisRunner(db_path)
    analysis_runner.start()
    scheduler = Scheduler(db_path, analysis_runner)
    scheduler.start()
    handler = make_handler(
        db_path,
        auth_token=auth_token,
        default_lock_actor_agent_identity_id=default_lock_actor_agent_identity_id,
        analysis_runner=analysis_runner,
    )
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        scheduler.stop()
        analysis_runner.stop()
        raise WebError(f"server_bind_failed:{host}:{port}:{exc}") from exc

    try:
        server.serve_forever()
    finally:
        scheduler.stop()
        analysis_runner.stop()
        server.server_close()


def make_handler(
    db_path: Path,
    *,
    auth_token: Optional[str] = None,
    default_lock_actor_agent_identity_id: Optional[str] = None,
    analysis_runner: Optional[Any] = None,
) -> Type[BaseHTTPRequestHandler]:
    resolved_db_path = db_path
    selected_auth_token = auth_token if auth_token else None
    selected_default_lock_actor_agent_identity_id = _optional_string(
        default_lock_actor_agent_identity_id
    )
    # Without a background runner (tests, or a handler built outside `serve`), execute
    # analysis jobs synchronously on the request thread so behavior stays deterministic.
    selected_analysis_runner = analysis_runner or InlineAnalysisRunner(resolved_db_path)

    def _lock_actor_agent_identity_id(payload: dict[str, Any]) -> Optional[str]:
        return (
            _optional_string(payload.get("actor_agent_identity_id"))
            or selected_default_lock_actor_agent_identity_id
        )

    class KyokoRequestHandler(BaseHTTPRequestHandler):
        server_version = "KyokoHTTP/0.1"

        def do_GET(self) -> None:
            path = _request_path(self.path)
            if not self._is_authorized():
                self._send_auth_required()
                return
            try:
                if path == "/":
                    if spa_bundle_available():
                        self._serve_spa_index()
                    else:
                        self._send_html(_dashboard_html())
                    return
                # Static assets from the built dashboard bundle (e.g. /assets/*.js).
                if not path.startswith("/api/") and not path.startswith("/v1/"):
                    asset = _resolve_static_asset(path)
                    if asset is not None:
                        self._serve_static_file(asset)
                        return
                if path == "/api/status":
                    self._send_json(status_to_json(get_database_status(resolved_db_path)))
                    return
                if path == "/api/events/stream":
                    self._send_sse_stream()
                    return
                if path == "/api/live-events":
                    after_seq_raw = _query_param(self.path, "after_seq")
                    kinds_raw = _query_param(self.path, "kinds")
                    self._send_json(
                        {
                            "events": list_live_events(
                                db_path=resolved_db_path,
                                profile_id=_query_param(self.path, "profile_id"),
                                run_id=_query_param(self.path, "run_id"),
                                after_seq=int(after_seq_raw)
                                if after_seq_raw and after_seq_raw.isdigit()
                                else None,
                                kinds=[k.strip() for k in kinds_raw.split(",") if k.strip()]
                                if kinds_raw
                                else None,
                                limit=_optional_int(_query_param(self.path, "limit"), 200),
                            )
                        }
                    )
                    return
                if path == "/api/current-run":
                    self._send_json({"run": get_current_run(db_path=resolved_db_path)})
                    return
                if path == "/api/run-outline":
                    try:
                        self._send_json(
                            get_run_outline(
                                db_path=resolved_db_path,
                                run_id=_query_param(self.path, "run_id") or "",
                                payload_preview_chars=_optional_int(
                                    _query_param(self.path, "payload_preview_chars"), 200
                                ),
                            )
                        )
                    except InspectionError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/run-search":
                    scope_raw = _query_param(self.path, "scope")
                    try:
                        self._send_json(
                            search_run(
                                db_path=resolved_db_path,
                                run_id=_query_param(self.path, "run_id") or "",
                                pattern=_query_param(self.path, "pattern") or "",
                                regex=_query_param(self.path, "regex") in {"1", "true", "yes"},
                                case_sensitive=_query_param(self.path, "case_sensitive")
                                in {"1", "true", "yes"},
                                scope=[s.strip() for s in scope_raw.split(",") if s.strip()]
                                if scope_raw
                                else None,
                                context_chars=_optional_int(
                                    _query_param(self.path, "context_chars"), 80
                                ),
                                max_matches=_optional_int(_query_param(self.path, "max_matches"), 50),
                            )
                        )
                    except InspectionError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/span-context":
                    try:
                        self._send_json(
                            get_span_context(
                                db_path=resolved_db_path,
                                span_id=_query_param(self.path, "span_id") or "",
                                before=_optional_int(_query_param(self.path, "before"), 2),
                                after=_optional_int(_query_param(self.path, "after"), 2),
                                include_parent=_query_param(self.path, "include_parent")
                                not in {"0", "false", "no"},
                            )
                        )
                    except InspectionError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/span-payload":
                    try:
                        self._send_json(
                            get_span_payload(
                                db_path=resolved_db_path,
                                span_id=_query_param(self.path, "span_id") or "",
                                target=_query_param(self.path, "target") or "input",
                                path=_query_param(self.path, "path"),
                                max_chars=_optional_int(_query_param(self.path, "max_chars"), 4000),
                                offset=_optional_int(_query_param(self.path, "offset"), 0),
                            )
                        )
                    except InspectionError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/run-payload":
                    try:
                        self._send_json(
                            get_run_payload(
                                db_path=resolved_db_path,
                                run_id=_query_param(self.path, "run_id") or "",
                                target=_query_param(self.path, "target") or "input",
                                path=_query_param(self.path, "path"),
                                max_chars=_optional_int(_query_param(self.path, "max_chars"), 4000),
                                offset=_optional_int(_query_param(self.path, "offset"), 0),
                            )
                        )
                    except InspectionError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/run-scores":
                    try:
                        self._send_json(
                            get_run_scores(
                                db_path=resolved_db_path,
                                run_id=_query_param(self.path, "run_id") or "",
                            )
                        )
                    except InspectionError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/annotations":
                    self._send_json(
                        {
                            "annotations": list_annotations(
                                db_path=resolved_db_path,
                                run_id=_query_param(self.path, "run_id"),
                                span_id=_query_param(self.path, "span_id"),
                                limit=_optional_int(_query_param(self.path, "limit"), 200),
                            )
                        }
                    )
                    return
                if path == "/api/mcp-log":
                    after_seq_raw = _query_param(self.path, "after_seq")
                    self._send_json(
                        {
                            "events": list_mcp_log(
                                db_path=resolved_db_path,
                                session_id=_query_param(self.path, "session_id"),
                                tool_name=_query_param(self.path, "tool_name"),
                                after_seq=int(after_seq_raw)
                                if after_seq_raw and after_seq_raw.isdigit()
                                else None,
                                limit=_optional_int(_query_param(self.path, "limit"), 200),
                            )
                        }
                    )
                    return
                if path == "/api/source-discovery":
                    self._send_json(
                        discover_local_sources(
                            db_path=resolved_db_path,
                            home=_query_path(self.path, "home"),
                            profile_id=_query_param(self.path, "profile_id"),
                            profile_name=_query_param(self.path, "profile_name"),
                            root_path=_query_path(self.path, "root_path"),
                            include_missing=_query_param(self.path, "include_missing") in {"1", "true", "yes"},
                        ).to_json()
                    )
                    return
                if path == "/api/storage-report":
                    self._send_json(storage_report(resolved_db_path).to_json())
                    return
                if path == "/api/dashboard-metrics":
                    profile_id = _query_param(self.path, "profile_id")
                    self._send_json(
                        get_dashboard_metrics(
                            db_path=resolved_db_path,
                            profile_id=profile_id if profile_id else None,
                        )
                    )
                    return
                if path == "/api/blobs":
                    self._send_json({"payload_blobs": list_payload_blobs(resolved_db_path)})
                    return
                if path == "/api/policy":
                    profile_id = _query_param(self.path, "profile_id")
                    self._send_json(
                        {
                            "policy": get_autonomy_policy(
                                db_path=resolved_db_path,
                                profile_id=profile_id if profile_id else None,
                            )
                        }
                    )
                    return
                if path == "/api/autonomy-events":
                    profile_id = _query_param(self.path, "profile_id")
                    kind = _query_param(self.path, "kind")
                    selected_kinds = (
                        (kind,)
                        if kind in AUTONOMY_EVENT_KINDS
                        else AUTONOMY_EVENT_KINDS
                    )
                    self._send_json(
                        {
                            "autonomy_events": list_timeline_events(
                                db_path=resolved_db_path,
                                profile_id=profile_id if profile_id else None,
                                kinds=selected_kinds,
                                entity_type=_query_param(self.path, "entity_type") or None,
                                entity_id=_query_param(self.path, "entity_id") or None,
                                limit=_query_int(self.path, "limit", default=20),
                            )
                        }
                    )
                    return
                if path == "/api/proposals":
                    profile_id = _query_param(self.path, "profile_id")
                    state = _query_param(self.path, "state")
                    self._send_json(
                        {
                            "proposals": list_learning_proposals(
                                resolved_db_path,
                                profile_id=profile_id if profile_id else None,
                                state=state if state else None,
                            )
                        }
                    )
                    return
                if path == "/api/runs":
                    profile_id = _query_param(self.path, "profile_id")
                    self._send_json(
                        {
                            "runs": list_runs(
                                db_path=resolved_db_path,
                                profile_id=profile_id if profile_id else None,
                            )
                        }
                    )
                    return
                if path == "/api/run-detail":
                    run_id = _query_param(self.path, "id")
                    if not run_id:
                        self._send_json(
                            {"error": "run_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(get_run_detail(db_path=resolved_db_path, run_id=run_id))
                    return
                if path == "/api/proposal-detail":
                    proposal_id = _query_param(self.path, "id")
                    if not proposal_id:
                        self._send_json(
                            {"error": "proposal_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(get_proposal_detail(db_path=resolved_db_path, proposal_id=proposal_id))
                    return
                if path == "/api/issues":
                    try:
                        self._send_json(
                            {
                                "issues": list_issues(
                                    db_path=resolved_db_path,
                                    status=_query_param(self.path, "status") or None,
                                    section=_query_param(self.path, "section") or None,
                                    profile_id=_query_param(self.path, "profile_id") or None,
                                    limit=_optional_int(_query_param(self.path, "limit"), 200),
                                )
                            }
                        )
                    except IssueError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/issue-detail":
                    issue_id = _query_param(self.path, "id")
                    if not issue_id:
                        self._send_json(
                            {"error": "issue_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(get_issue_detail(db_path=resolved_db_path, issue_id=issue_id))
                    except IssueError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                # ---- eval (Python detector) measurement plane ----
                if path == "/api/evals":
                    try:
                        self._send_json(
                            {
                                "detectors": list_detectors(
                                    db_path=resolved_db_path,
                                    profile_id=_query_param(self.path, "profile_id") or None,
                                )
                            }
                        )
                    except DetectorError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/evals/detail":
                    detector_id = _query_param(self.path, "id")
                    if not detector_id:
                        self._send_json(
                            {"error": "detector_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(
                            {"detector": get_detector(db_path=resolved_db_path, detector_id=detector_id)}
                        )
                    except DetectorError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/eval-runs":
                    try:
                        self._send_json(
                            {
                                "eval_runs": list_measure_runs(
                                    db_path=resolved_db_path,
                                    kind="python",
                                    eval_definition_id=_query_param(self.path, "eval_definition_id") or None,
                                    profile_id=_query_param(self.path, "profile_id") or None,
                                )
                            }
                        )
                    except EvalMeasureError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/eval-runs/detail":
                    eval_run_id = _query_param(self.path, "id")
                    if not eval_run_id:
                        self._send_json(
                            {"error": "eval_run_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(
                            {
                                "eval_run": get_measure_run(
                                    db_path=resolved_db_path,
                                    eval_run_id=eval_run_id,
                                ),
                                "results": get_measure_results(
                                    db_path=resolved_db_path,
                                    eval_run_id=eval_run_id,
                                ),
                            }
                        )
                    except EvalMeasureError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                # ---- llm_eval (LLM-as-judge) measurement plane ----
                if path == "/api/llm-evals":
                    try:
                        self._send_json(
                            {
                                "llm_evals": list_llm_evals(
                                    db_path=resolved_db_path,
                                    profile_id=_query_param(self.path, "profile_id") or None,
                                )
                            }
                        )
                    except LlmEvalError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/llm-evals/detail":
                    llm_eval_id = _query_param(self.path, "id")
                    if not llm_eval_id:
                        self._send_json(
                            {"error": "llm_eval_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(
                            {"llm_eval": get_llm_eval(db_path=resolved_db_path, llm_eval_id=llm_eval_id)}
                        )
                    except LlmEvalError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/llm-eval-runs":
                    try:
                        self._send_json(
                            {
                                "eval_runs": list_measure_runs(
                                    db_path=resolved_db_path,
                                    kind="llm",
                                    eval_definition_id=_query_param(self.path, "eval_definition_id") or None,
                                    profile_id=_query_param(self.path, "profile_id") or None,
                                )
                            }
                        )
                    except EvalMeasureError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/llm-eval-runs/detail":
                    eval_run_id = _query_param(self.path, "id")
                    if not eval_run_id:
                        self._send_json(
                            {"error": "eval_run_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(
                            {
                                "eval_run": get_measure_run(
                                    db_path=resolved_db_path,
                                    eval_run_id=eval_run_id,
                                ),
                                "results": get_measure_results(
                                    db_path=resolved_db_path,
                                    eval_run_id=eval_run_id,
                                ),
                            }
                        )
                    except EvalMeasureError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                    return
                if path == "/api/eval-compare":
                    baseline = _query_param(self.path, "baseline")
                    compare = _query_param(self.path, "compare")
                    if not baseline or not compare:
                        self._send_json(
                            {"error": "baseline_and_compare_run_ids_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(
                            compare_eval_runs(
                                db_path=resolved_db_path,
                                baseline_run_id=baseline,
                                compare_run_id=compare,
                            )
                        )
                    except EvalMeasureError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/llm-eval-compare":
                    baseline = _query_param(self.path, "baseline")
                    compare = _query_param(self.path, "compare")
                    if not baseline or not compare:
                        self._send_json(
                            {"error": "baseline_and_compare_run_ids_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        self._send_json(
                            compare_eval_runs(
                                db_path=resolved_db_path,
                                baseline_run_id=baseline,
                                compare_run_id=compare,
                            )
                        )
                    except EvalMeasureError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                    return
                if path == "/api/skills":
                    profile_id = _query_param(self.path, "profile_id")
                    self._send_json(
                        {
                            "skills": list_skills(
                                resolved_db_path,
                                profile_id=profile_id if profile_id else None,
                            )
                        }
                    )
                    return
                if path == "/api/skill-revisions":
                    skill_id = _query_param(self.path, "skill_id")
                    self._send_json(
                        {
                            "skill_revisions": list_skill_revisions(
                                resolved_db_path,
                                skill_id=skill_id if skill_id else None,
                            )
                        }
                    )
                    return
                if path == "/api/context-rules":
                    include_inactive = _query_param(self.path, "include_inactive") == "true"
                    profile_id = _query_param(self.path, "profile_id")
                    self._send_json(
                        {
                            "context_delivery_rules": list_context_delivery_rules(
                                resolved_db_path,
                                profile_id=profile_id if profile_id else None,
                                active_only=not include_inactive,
                            )
                        }
                    )
                    return
                if path == "/api/context-rule-revisions":
                    rule_id = _query_param(self.path, "rule_id")
                    self._send_json(
                        {
                            "context_delivery_rule_revisions": list_context_delivery_rule_revisions(
                                resolved_db_path,
                                rule_id=rule_id if rule_id else None,
                            )
                        }
                    )
                    return
                if path == "/api/context":
                    target_type = _query_param(self.path, "target_type")
                    target_id = _query_param(self.path, "target_id")
                    profile_id = _query_param(self.path, "profile_id")
                    if bool(target_type) != bool(target_id):
                        self._send_json(
                            {"error": "context_target_requires_type_and_id"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(
                        {
                            "section": "context",
                            "target": {
                                "entity_type": target_type,
                                "entity_id": target_id,
                            }
                            if target_type and target_id
                            else None,
                            "profile_id": profile_id,
                            "context": render_skillbook_prompt(
                                resolved_db_path,
                                profile_id=profile_id,
                                target_entity_type=target_type,
                                target_entity_id=target_id,
                            ),
                        }
                    )
                    return
                if path == "/api/checks":
                    self._send_json(
                        {
                            "check_specs": list_check_specs(resolved_db_path),
                            "check_runs": list_check_runs(resolved_db_path),
                            "replay_runs": list_replay_runs(resolved_db_path),
                        }
                    )
                    return
                if path == "/api/check-assertion-presets":
                    self._send_json({"assertion_presets": list_assertion_presets()})
                    return
                if path == "/api/check-capabilities":
                    self._send_json(list_check_capabilities())
                    return
                if path == "/api/check-locks":
                    query = parse_qs(urlparse(self.path).query)
                    profile_id = query.get("profile_id", [None])[0]
                    include_unlocked = query.get("include_unlocked", ["0"])[0] in {"1", "true", "yes"}
                    self._send_json(
                        {
                            "check_locks": list_check_locks(
                                resolved_db_path,
                                profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                                locked_only=not include_unlocked,
                            )
                        }
                    )
                    return
                if path == "/api/check-detail":
                    check_spec_id = _query_param(self.path, "id")
                    if not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(get_check_detail(db_path=resolved_db_path, check_spec_id=check_spec_id))
                    return
                if path == "/api/replay-detail":
                    replay_run_id = _query_param(self.path, "id")
                    if not replay_run_id:
                        self._send_json(
                            {"error": "replay_run_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(get_replay_detail(db_path=resolved_db_path, replay_run_id=replay_run_id))
                    return
                if path == "/api/replay-adapters":
                    self._send_json({"replay_adapters": list_replay_adapters(resolved_db_path)})
                    return
                if path == "/api/integration-frameworks":
                    self._send_json(
                        {
                            "source_frameworks": _frameworks_payload(SUPPORTED_SOURCE_FRAMEWORKS),
                            "replay_frameworks": _frameworks_payload(SUPPORTED_FRAMEWORKS),
                        }
                    )
                    return
                if path == "/api/replay-servers/status":
                    adapter_id = _query_param(self.path, "id")
                    if not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = registered_replay_server_status(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                    )
                    self._send_json(_replay_server_process_payload(report, adapter_id=adapter_id))
                    return
                if path == "/api/replay-servers/logs":
                    adapter_id = _query_param(self.path, "id")
                    if not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = registered_replay_server_logs(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                        max_bytes=_query_int(self.path, "max_bytes", 40000),
                    )
                    self._send_json(_replay_server_logs_payload(report, adapter_id=adapter_id))
                    return
                if path == "/api/operator-adapters":
                    self._send_json({"operator_adapters": list_operator_adapters(resolved_db_path)})
                    return
                if path == "/api/operator-presets":
                    self._send_json({"operator_presets": list_operator_presets()})
                    return
                if path == "/api/operator-runs":
                    self._send_json({"operator_runs": list_operator_runs(resolved_db_path)})
                    return
                if path == "/api/analysis/analyzers":
                    self._send_json(_analyzer_availability(resolved_db_path))
                    return
                if path == "/api/analysis/runs":
                    self._send_json({"runs": list_operator_runs(resolved_db_path)})
                    return
                if path == "/api/analysis/schedules":
                    self._send_json(
                        {"schedules": list_analysis_schedules(resolved_db_path)}
                    )
                    return
                if path == "/api/harness-patches":
                    self._send_json({"patch_transactions": list_patch_transactions(resolved_db_path)})
                    return
                if path == "/api/harness-target-locks":
                    query = parse_qs(urlparse(self.path).query)
                    profile_id = query.get("profile_id", [None])[0]
                    include_unlocked = query.get("include_unlocked", ["0"])[0] in {"1", "true", "yes"}
                    self._send_json(
                        {
                            "harness_target_locks": list_harness_target_locks(
                                resolved_db_path,
                                profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                                locked_only=not include_unlocked,
                            )
                        }
                    )
                    return
                if path == "/api/evidence-summary":
                    profile_id = _query_param(self.path, "profile_id")
                    self._send_json(_evidence_summary(resolved_db_path, profile_id=profile_id if profile_id else None))
                    return
                # SPA client-side routes (e.g. /runs, /mcp-log): serve index.html so a
                # browser refresh or deep link resolves to the React app, not a 404.
                if (
                    spa_bundle_available()
                    and not path.startswith("/api/")
                    and not path.startswith("/v1/")
                ):
                    self._serve_spa_index()
                    return
                self._send_json({"error": "not_found", "path": path}, status=HTTPStatus.NOT_FOUND)
            except (StorageError, RedactionError, RetentionError, DashboardMetricsError) as exc:
                self._send_json(
                    {"error": "storage_error", "detail": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except (DetailError, AutonomyRunError) as exc:
                self._send_json(
                    {"error": "detail_failed", "detail": str(exc)},
                    status=HTTPStatus.NOT_FOUND,
                )
            except (ReplayAdapterError, ReplayServerError) as exc:
                self._send_json(
                    {"error": "replay_adapter_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )

        def do_POST(self) -> None:
            path = _request_path(self.path)
            if not self._is_authorized():
                self._send_auth_required()
                return
            # OTLP trace ingest also accepts protobuf. application/x-protobuf is not a
            # browser "simple request" content type, so it does not weaken the loopback
            # CSRF content-type guard (SCOPE Decision 2).
            protobuf_traces = path in {"/api/ingest-otlp", "/v1/traces"} and looks_like_protobuf(
                self.headers.get("Content-Type")
            )
            if not self._has_json_content_type() and not protobuf_traces:
                self._send_unsupported_media_type()
                return
            try:
                if path == "/api/doctor":
                    payload = self._read_json()
                    report = run_doctor(
                        db_path=resolved_db_path,
                        smoke_demo=bool(payload.get("smoke_demo", False)),
                        operator_smoke_prepare=bool(payload.get("operator_smoke_prepare", False)),
                        judge_smoke_prepare=bool(payload.get("judge_smoke_prepare", False)),
                        ace_native_prepare=bool(payload.get("ace_native_prepare", False)),
                        integration_smoke=bool(payload.get("integration_smoke", False)),
                        improve_smoke=bool(payload.get("improve_smoke", False)),
                        opentelemetry_smoke=bool(payload.get("opentelemetry_smoke", False)),
                        opentelemetry_python_executable=_optional_path(
                            payload.get("opentelemetry_python_executable")
                        ),
                        ace_native_smoke=bool(payload.get("ace_native_smoke", False)),
                        dashboard_smoke=bool(payload.get("dashboard_smoke", False)),
                        dashboard_smoke_screenshot=bool(
                            payload.get("dashboard_smoke_screenshot", False)
                        ),
                        dashboard_smoke_install_browser_deps=bool(
                            payload.get("dashboard_smoke_install_browser_deps", False)
                        ),
                        dashboard_smoke_timeout_seconds=_optional_int(
                            payload.get("dashboard_smoke_timeout_seconds"), 30
                        ),
                        safe_smokes=bool(payload.get("safe_smokes", False)),
                        smoke_output_dir=_optional_path(payload.get("smoke_output_dir")),
                        smoke_evidence_dir=(
                            _optional_path(payload.get("smoke_evidence_dir"))
                            or DEFAULT_SMOKE_EVIDENCE_DIR
                        ),
                        ace_path=_optional_path(payload.get("ace_path")),
                        host=_optional_str(payload.get("host")) or DEFAULT_HOST,
                        port=_optional_int(payload.get("port"), DEFAULT_PORT),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/demo":
                    payload = self._read_json()
                    output_dir = payload.get("output_dir")
                    report = run_demo_setup(
                        db_path=resolved_db_path,
                        output_dir=Path(output_dir) if isinstance(output_dir, str) and output_dir else None,
                        run_loop=bool(payload.get("run_loop", True)),
                        apply_context=bool(payload.get("apply_context", True)),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/ingest":
                    payload = self._read_json()
                    source_events = payload.get("source_events")
                    fixture = source_events if isinstance(source_events, dict) else payload
                    if not isinstance(fixture, dict):
                        self._send_json(
                            {"error": "source_events_object_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = ingest_source_payload(
                        db_path=resolved_db_path,
                        fixture=fixture,
                        source_label="POST /api/ingest",
                    )
                    self._send_json(
                        {
                            "profile_id": report.profile_id,
                            "ingested_counts": report.inserted_counts,
                        }
                    )
                    return
                if path in {"/api/ingest-otlp", "/v1/traces"}:
                    if looks_like_protobuf(self.headers.get("Content-Type")):
                        length = int(self.headers.get("Content-Length", "0"))
                        raw = self.rfile.read(length) if length else b""
                        try:
                            fixture = decode_export_trace_service_request(raw)
                        except OtlpProtobufError as exc:
                            self._send_json(
                                {"error": f"otlp_protobuf_decode_failed:{exc}"},
                                status=HTTPStatus.BAD_REQUEST,
                            )
                            return
                        payload = {}
                    else:
                        payload = self._read_json()
                        otlp_payload = payload.get("otlp")
                        fixture = otlp_payload if isinstance(otlp_payload, dict) else payload
                    profile_id = _optional_str(payload.get("profile_id"))
                    profile_name = _optional_str(payload.get("profile_name"))
                    root_path = _optional_str(payload.get("root_path"))
                    output_path = _optional_path(payload.get("output_path"))
                    report = ingest_otlp_payload(
                        db_path=resolved_db_path,
                        payload=fixture,
                        profile_id=profile_id
                        or _query_param(self.path, "profile_id")
                        or _header_str(self.headers.get("X-Kyoko-Profile-Id")),
                        profile_name=profile_name
                        or _query_param(self.path, "profile_name")
                        or _header_str(self.headers.get("X-Kyoko-Profile-Name")),
                        root_path=root_path
                        or _query_param(self.path, "root_path")
                        or _header_str(self.headers.get("X-Kyoko-Root-Path")),
                        source_kind=_optional_str(payload.get("source_kind"))
                        or _query_param(self.path, "source_kind")
                        or "otlp_http",
                        source_name=_optional_str(payload.get("source_name"))
                        or _query_param(self.path, "source_name")
                        or "OpenTelemetry",
                        output_path=output_path.expanduser() if output_path else None,
                        source_label=f"POST {path}",
                    )
                    global_bus().publish(
                        EVENT_RUN_UPSERT,
                        {"profile_id": report.profile_id, "run_ids": list(report.run_ids)},
                    )
                    self._send_json(report.to_json())
                    return
                if path in {"/api/ingest-live", "/v1/live"}:
                    payload = self._read_json()
                    events = payload.get("events")
                    if events is None:
                        # Single-event convenience form: the body itself is the event.
                        events = [payload]
                    if not isinstance(events, list):
                        self._send_json(
                            {"error": "events_must_be_a_list"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        records = ingest_live_events(
                            db_path=resolved_db_path,
                            events=events,
                            profile_id=_optional_str(payload.get("profile_id"))
                            or _query_param(self.path, "profile_id")
                            or _header_str(self.headers.get("X-Kyoko-Profile-Id")),
                        )
                    except LiveError as exc:
                        self._send_json(
                            {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST
                        )
                        return
                    self._send_json({"ingested_count": len(records), "events": records})
                    return
                if path == "/api/annotations":
                    payload = self._read_json()
                    try:
                        annotation = create_annotation(
                            db_path=resolved_db_path,
                            kind=_optional_str(payload.get("kind")) or "",
                            run_id=_optional_str(payload.get("run_id")),
                            span_id=_optional_str(payload.get("span_id")),
                            note=_optional_str(payload.get("note")),
                            source=_optional_str(payload.get("source")) or "user",
                        )
                    except AnnotationError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json({"annotation": annotation})
                    return
                if path == "/api/annotations/delete":
                    payload = self._read_json()
                    annotation_id = _optional_str(payload.get("id"))
                    if not annotation_id:
                        self._send_json({"error": "id_required"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    try:
                        deleted = delete_annotation(
                            db_path=resolved_db_path, annotation_id=annotation_id
                        )
                    except AnnotationError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.NOT_FOUND)
                        return
                    self._send_json({"annotation": deleted})
                    return
                if path == "/api/issues":
                    payload = self._read_json()
                    try:
                        issue = create_issue(
                            db_path=resolved_db_path,
                            title=_optional_str(payload.get("title")) or "",
                            body=_optional_str(payload.get("body")),
                            section=_optional_str(payload.get("section")),
                            category=_optional_str(payload.get("category")),
                            severity=_optional_str(payload.get("severity")),
                            status=_optional_str(payload.get("status")) or "open",
                            evidence_refs=payload.get("evidence_refs")
                            if isinstance(payload.get("evidence_refs"), list)
                            else None,
                            affected_agent_identity_ids=payload.get("affected_agent_identity_ids")
                            if isinstance(payload.get("affected_agent_identity_ids"), list)
                            else None,
                            affected_workflow_node_ids=payload.get("affected_workflow_node_ids")
                            if isinstance(payload.get("affected_workflow_node_ids"), list)
                            else None,
                            affected_task_ids=payload.get("affected_task_ids")
                            if isinstance(payload.get("affected_task_ids"), list)
                            else None,
                            affected_span_ids=payload.get("affected_span_ids")
                            if isinstance(payload.get("affected_span_ids"), list)
                            else None,
                            proposal_ids=payload.get("proposal_ids")
                            if isinstance(payload.get("proposal_ids"), list)
                            else None,
                            profile_id=_optional_str(payload.get("profile_id")),
                        )
                    except IssueError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json({"issue": issue})
                    return
                if path == "/api/issue-status":
                    payload = self._read_json()
                    issue_id = _optional_str(payload.get("id"))
                    status = _optional_str(payload.get("status"))
                    if not issue_id or not status:
                        self._send_json(
                            {"error": "id_and_status_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        issue = update_issue_status(
                            db_path=resolved_db_path,
                            issue_id=issue_id,
                            status=status,
                        )
                    except IssueError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json({"issue": issue})
                    return
                if path == "/api/issue-comment":
                    payload = self._read_json()
                    issue_id = _optional_str(payload.get("id"))
                    if not issue_id:
                        self._send_json(
                            {"error": "id_required"}, status=HTTPStatus.BAD_REQUEST
                        )
                        return
                    try:
                        issue = set_issue_comment(
                            db_path=resolved_db_path,
                            issue_id=issue_id,
                            comment=_optional_str(payload.get("comment")),
                        )
                    except IssueError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json({"issue": issue})
                    return
                if path == "/api/issues/mint-guard":
                    payload = self._read_json()
                    issue_id = _optional_str(payload.get("id")) or _optional_str(
                        payload.get("issue_id")
                    )
                    if not issue_id:
                        self._send_json(
                            {"error": "id_required"}, status=HTTPStatus.BAD_REQUEST
                        )
                        return
                    try:
                        report = mint_guard_for_issue(
                            db_path=resolved_db_path, issue_id=issue_id
                        )
                    except (GuardError, IssueError) as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json({"guard": report.to_json()})
                    return
                if path == "/api/issues/accept":
                    payload = self._read_json()
                    issue_id = _optional_str(payload.get("id")) or _optional_str(
                        payload.get("issue_id")
                    )
                    if not issue_id:
                        self._send_json(
                            {"error": "id_required"}, status=HTTPStatus.BAD_REQUEST
                        )
                        return
                    operator = _optional_str(payload.get("operator")) or "mock"
                    if operator != "mock":
                        # Loopback-only synchronous handler: only the deterministic mock
                        # author is supported in-process (command operators shell out).
                        self._send_json(
                            {"error": f"unsupported_operator:{operator}"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        issue = accept_issue(db_path=resolved_db_path, issue_id=issue_id)
                        output_dir = (
                            resolved_db_path.parent
                            / ".kyoko"
                            / "propose-runs"
                            / issue_id
                        )
                        propose_report = propose_for_issue(
                            db_path=resolved_db_path,
                            output_dir=output_dir,
                            issue_id=issue_id,
                            operator="mock",
                        )
                    except (IssueError, AnalyzeError) as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json(
                        {"issue": issue, "propose": propose_report.to_json()}
                    )
                    return
                # ---- eval (Python detector) measurement plane ----
                if path == "/api/run-eval":
                    payload = self._read_json()
                    detector_id = payload.get("detector_id")
                    if not isinstance(detector_id, str) or not detector_id:
                        self._send_json(
                            {"error": "detector_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    corpus = payload.get("corpus")
                    if not isinstance(corpus, dict):
                        self._send_json(
                            {"error": "corpus_object_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    persist = bool(payload.get("persist", False))
                    timeout_seconds = payload.get("timeout_seconds", 120)
                    raise_issues_raw = payload.get("raise_issues")
                    raise_issues = bool(raise_issues_raw) if raise_issues_raw is not None else False
                    threshold_raw = payload.get("threshold")
                    issue_threshold = float(threshold_raw) if threshold_raw is not None else None
                    try:
                        report = run_detector(
                            db_path=resolved_db_path,
                            detector_id=detector_id,
                            corpus=corpus,
                            persist=persist,
                            profile_id=_optional_str(payload.get("profile_id")),
                            timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 120,
                            raise_issues=raise_issues,
                            issue_threshold=issue_threshold,
                        )
                    except DetectorError as exc:
                        self._send_json(
                            {"error": "eval_failed", "detail": str(exc)},
                            status=HTTPStatus.CONFLICT,
                        )
                        return
                    except EvalMeasureError as exc:
                        self._send_json(
                            {"error": "eval_failed", "detail": str(exc)},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(report.to_json())
                    return
                # ---- llm_eval (LLM-as-judge) measurement plane ----
                if path == "/api/run-llm-eval":
                    payload = self._read_json()
                    llm_eval_id = payload.get("llm_eval_id")
                    if not isinstance(llm_eval_id, str) or not llm_eval_id:
                        self._send_json(
                            {"error": "llm_eval_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    corpus = payload.get("corpus")
                    if not isinstance(corpus, dict):
                        self._send_json(
                            {"error": "corpus_object_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    command = payload.get("command")
                    persist = bool(payload.get("persist", False))
                    prepare_only = bool(payload.get("prepare_only", False))
                    timeout_seconds = payload.get("timeout_seconds", 120)
                    raise_issues_raw = payload.get("raise_issues")
                    raise_issues = bool(raise_issues_raw) if raise_issues_raw is not None else False
                    threshold_raw = payload.get("threshold")
                    issue_threshold = float(threshold_raw) if threshold_raw is not None else None
                    try:
                        report = run_llm_eval(
                            db_path=resolved_db_path,
                            llm_eval_id=llm_eval_id,
                            corpus=corpus,
                            command=list(command) if isinstance(command, list) else None,
                            operator_adapter_id=_optional_str(payload.get("operator_adapter_id"))
                            or _optional_str(payload.get("operator")),
                            persist=persist,
                            prepare_only=prepare_only,
                            output_dir=None,
                            profile_id=_optional_str(payload.get("profile_id")),
                            timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 120,
                            raise_issues=raise_issues,
                            issue_threshold=issue_threshold,
                            bus=global_bus(),
                        )
                    except LlmEvalError as exc:
                        self._send_json(
                            {"error": "eval_failed", "detail": str(exc)},
                            status=HTTPStatus.CONFLICT,
                        )
                        return
                    except EvalMeasureError as exc:
                        self._send_json(
                            {"error": "eval_failed", "detail": str(exc)},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(report.to_json())
                    return
                if path == "/api/llm-evals/status":
                    payload = self._read_json()
                    llm_eval_id = payload.get("id")
                    if not isinstance(llm_eval_id, str) or not llm_eval_id:
                        self._send_json({"error": "id_required"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    # Accept either an explicit status string or a boolean `active`.
                    status_raw = payload.get("status")
                    if isinstance(status_raw, str):
                        new_status = status_raw
                    elif isinstance(payload.get("active"), bool):
                        new_status = "active" if payload["active"] else "archived"
                    else:
                        self._send_json(
                            {"error": "status_or_active_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    try:
                        llm_eval = set_llm_eval_status(
                            db_path=resolved_db_path,
                            llm_eval_id=llm_eval_id,
                            status=new_status,
                            profile_id=_optional_str(payload.get("profile_id")),
                        )
                    except (LlmEvalError, EvalMeasureError) as exc:
                        self._send_json(
                            {"error": "status_update_failed", "detail": str(exc)},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json({"llm_eval": llm_eval})
                    return
                if path == "/api/policy":
                    payload = self._read_json()
                    policy = update_autonomy_policy(
                        db_path=resolved_db_path,
                        profile_id=payload.get("profile_id")
                        if isinstance(payload.get("profile_id"), str)
                        else None,
                        mode=payload.get("mode")
                        if isinstance(payload.get("mode"), str)
                        else None,
                        recurrence_threshold=payload.get("recurrence_threshold")
                        if isinstance(payload.get("recurrence_threshold"), int)
                        and not isinstance(payload.get("recurrence_threshold"), bool)
                        else None,
                        regression_threshold=payload.get("regression_threshold")
                        if isinstance(payload.get("regression_threshold"), int)
                        and not isinstance(payload.get("regression_threshold"), bool)
                        else None,
                        auto_rollback_on_regression=payload.get("auto_rollback_on_regression")
                        if isinstance(payload.get("auto_rollback_on_regression"), bool)
                        else None,
                        max_auto_fix_attempts=payload.get("max_auto_fix_attempts")
                        if isinstance(payload.get("max_auto_fix_attempts"), int)
                        and not isinstance(payload.get("max_auto_fix_attempts"), bool)
                        else None,
                        allow_repo_patch=payload.get("allow_repo_patch")
                        if isinstance(payload.get("allow_repo_patch"), bool)
                        else None,
                        dirty_worktree_policy=payload.get("dirty_worktree_policy")
                        if isinstance(payload.get("dirty_worktree_policy"), str)
                        else None,
                    )
                    self._send_json({"policy": policy})
                    return
                if path == "/api/proposals/apply":
                    payload = self._read_json()
                    proposal_id = payload.get("proposal_id")
                    if not isinstance(proposal_id, str) or not proposal_id:
                        self._send_json({"error": "proposal_id_required"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    harness_workspace_root = payload.get("harness_workspace_root")
                    try:
                        result = apply_proposal(
                            db_path=resolved_db_path,
                            proposal_id=proposal_id,
                            harness_workspace_root=Path(harness_workspace_root).expanduser()
                            if isinstance(harness_workspace_root, str) and harness_workspace_root
                            else None,
                        )
                    except ApplyError as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json(result)
                    return
                if path == "/api/guard-monitor":
                    payload = self._read_json()
                    profile_id = payload.get("profile_id")
                    try:
                        report = monitor_guarded_issues(
                            db_path=resolved_db_path,
                            profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        )
                    except (GuardMonitorError, AutonomyError) as exc:
                        self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json(report.to_json())
                    return
                if path == "/api/prune":
                    payload = self._read_json()
                    older_than_days = payload.get("older_than_days")
                    profile_id = payload.get("profile_id")
                    report = prune_payload_blobs(
                        resolved_db_path,
                        older_than_days=older_than_days if isinstance(older_than_days, int) else None,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        dry_run=not bool(payload.get("apply")),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/prune-retention":
                    payload = self._read_json()
                    profile_id = payload.get("profile_id")
                    report = prune_retained_data(
                        db_path=resolved_db_path,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        trace_older_than_days=_optional_int_or_none(payload.get("trace_older_than_days")),
                        replay_older_than_days=_optional_int_or_none(payload.get("replay_older_than_days")),
                        operator_older_than_days=_optional_int_or_none(payload.get("operator_older_than_days")),
                        dry_run=not bool(payload.get("apply")),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/wal-checkpoint":
                    payload = self._read_json()
                    mode = payload.get("mode", "PASSIVE")
                    report = checkpoint_database(
                        resolved_db_path,
                        mode=mode if isinstance(mode, str) and mode else "PASSIVE",
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/load-smoke":
                    payload = self._read_json()
                    mode = payload.get("checkpoint_mode", "PASSIVE")
                    report = run_load_smoke(
                        db_path=resolved_db_path,
                        profile_id=_optional_str(payload.get("profile_id")) or "profile_load_smoke",
                        seed=bool(payload.get("seed", True)),
                        run_count=_optional_int(payload.get("runs"), 30),
                        spans_per_run=_optional_int(payload.get("spans_per_run"), 3),
                        read_workers=_optional_int(payload.get("read_workers"), 2),
                        read_iterations=_optional_int(payload.get("read_iterations"), 2),
                        expired_blob_count=_optional_int(payload.get("expired_blobs"), 2),
                        checkpoint_mode=mode if isinstance(mode, str) and mode else "PASSIVE",
                        max_p95_ms=_optional_float(payload.get("max_p95_ms")),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/autonomy/run":
                    payload = self._read_json()
                    profile_id = payload.get("profile_id")
                    harness_workspace_root = payload.get("harness_workspace_root")
                    report = run_autonomy(
                        db_path=resolved_db_path,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        harness_workspace_root=Path(harness_workspace_root)
                        if isinstance(harness_workspace_root, str) and harness_workspace_root
                        else None,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/improve":
                    payload = self._read_json()
                    proposal_id = payload.get("proposal_id")
                    replay_adapter_id = payload.get("replay_adapter_id") or payload.get("replay_adapter")
                    operator = payload.get("operator")
                    operator_adapter = payload.get("operator_adapter")
                    output_dir = payload.get("output_dir")
                    replay_output_dir = payload.get("replay_output_dir")
                    profile_id = payload.get("profile_id")
                    run_id = payload.get("run_id")
                    source_candidate_id = payload.get("source_candidate_id")
                    source_home = payload.get("source_home")
                    source_import_output_dir = payload.get("source_import_output_dir")
                    harness_workspace_root = payload.get("harness_workspace_root")
                    replay_timeout = payload.get("replay_timeout_seconds")
                    operator_timeout = payload.get("operator_timeout_seconds", 120)
                    operator_max_retries = payload.get("operator_max_retries", 0)
                    report = run_improvement_loop(
                        db_path=resolved_db_path,
                        output_dir=Path(output_dir) if isinstance(output_dir, str) and output_dir else None,
                        proposal_id=proposal_id if isinstance(proposal_id, str) and proposal_id else None,
                        operator=operator if isinstance(operator, str) and operator else "mock",
                        operator_adapter=operator_adapter if isinstance(operator_adapter, str) and operator_adapter else None,
                        operator_timeout_seconds=operator_timeout if isinstance(operator_timeout, int) else 120,
                        operator_max_retries=operator_max_retries if isinstance(operator_max_retries, int) else 0,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        run_id=run_id if isinstance(run_id, str) and run_id else None,
                        run_autonomy_after=bool(payload.get("run_autonomy", True)),
                        harness_workspace_root=Path(harness_workspace_root).expanduser()
                        if isinstance(harness_workspace_root, str) and harness_workspace_root
                        else None,
                        source_candidate_id=source_candidate_id
                        if isinstance(source_candidate_id, str) and source_candidate_id
                        else None,
                        source_home=Path(source_home).expanduser()
                        if isinstance(source_home, str) and source_home
                        else None,
                        source_import_output_dir=Path(source_import_output_dir).expanduser()
                        if isinstance(source_import_output_dir, str) and source_import_output_dir
                        else None,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/profile-next":
                    payload = self._read_json()
                    profile_id = payload.get("profile_id")
                    replay_adapter_id = payload.get("replay_adapter_id") or payload.get("replay_adapter")
                    replay_output_dir = payload.get("replay_output_dir")
                    replay_timeout = payload.get("replay_timeout_seconds")
                    harness_workspace_root = payload.get("harness_workspace_root")
                    operator_adapter_id = payload.get("operator_adapter_id") or payload.get("operator_adapter")
                    operator_target = payload.get("operator_target")
                    operator_output_dir = payload.get("operator_output_dir")
                    operator_timeout = payload.get("operator_timeout_seconds")
                    operator_max_retries = payload.get("operator_max_retries", 0)
                    schema_path = payload.get("schema_path")
                    report = run_profile_next_step(
                        db_path=resolved_db_path,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        run=bool(payload.get("run", False)),
                        replay_adapter_id=replay_adapter_id
                        if isinstance(replay_adapter_id, str) and replay_adapter_id
                        else None,
                        replay_output_dir=Path(replay_output_dir)
                        if isinstance(replay_output_dir, str) and replay_output_dir
                        else None,
                        replay_timeout_seconds=replay_timeout if isinstance(replay_timeout, int) else None,
                        harness_workspace_root=Path(harness_workspace_root)
                        if isinstance(harness_workspace_root, str) and harness_workspace_root
                        else None,
                        operator_adapter_id=operator_adapter_id
                        if isinstance(operator_adapter_id, str) and operator_adapter_id
                        else None,
                        operator_target=operator_target
                        if isinstance(operator_target, str) and operator_target
                        else None,
                        operator_output_dir=Path(operator_output_dir)
                        if isinstance(operator_output_dir, str) and operator_output_dir
                        else None,
                        operator_timeout_seconds=operator_timeout
                        if isinstance(operator_timeout, int)
                        else None,
                        operator_max_retries=operator_max_retries
                        if isinstance(operator_max_retries, int)
                        else 0,
                        schema_path=Path(schema_path) if isinstance(schema_path, str) and schema_path else None,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/apply":
                    payload = self._read_json()
                    proposal_id = payload.get("proposal_id")
                    if not isinstance(proposal_id, str) or not proposal_id:
                        self._send_json(
                            {"error": "proposal_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = apply_context_proposal(
                        db_path=resolved_db_path,
                        proposal_id=proposal_id,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/skills/lock":
                    payload = self._read_json()
                    skill_id = payload.get("skill_id")
                    if not isinstance(skill_id, str) or not skill_id:
                        self._send_json(
                            {"error": "skill_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = set_skill_lock(
                        db_path=resolved_db_path,
                        skill_id=skill_id,
                        locked=bool(payload.get("locked")),
                        reason=_optional_string(payload.get("reason")),
                        actor_agent_identity_id=_lock_actor_agent_identity_id(payload),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/context-rules/lock":
                    payload = self._read_json()
                    rule_id = payload.get("rule_id")
                    if not isinstance(rule_id, str) or not rule_id:
                        self._send_json(
                            {"error": "context_rule_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = set_context_delivery_rule_lock(
                        db_path=resolved_db_path,
                        rule_id=rule_id,
                        locked=bool(payload.get("locked")),
                        reason=_optional_string(payload.get("reason")),
                        actor_agent_identity_id=_lock_actor_agent_identity_id(payload),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/harness-targets/lock":
                    payload = self._read_json()
                    target_path = payload.get("target_path")
                    if not isinstance(target_path, str) or not target_path:
                        self._send_json(
                            {"error": "target_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    profile_id = payload.get("profile_id")
                    reason = payload.get("reason")
                    report = set_harness_target_lock(
                        db_path=resolved_db_path,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        target_path=target_path,
                        locked=bool(payload.get("locked")),
                        reason=reason if isinstance(reason, str) else None,
                        actor_agent_identity_id=_lock_actor_agent_identity_id(payload),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/check-specs/lock":
                    payload = self._read_json()
                    check_spec_id = payload.get("check_spec_id")
                    if not isinstance(check_spec_id, str) or not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    reason = payload.get("reason")
                    report = set_check_lock(
                        db_path=resolved_db_path,
                        check_spec_id=check_spec_id,
                        locked=bool(payload.get("locked")),
                        reason=reason if isinstance(reason, str) else None,
                        actor_agent_identity_id=_lock_actor_agent_identity_id(payload),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/check-specs/approve":
                    payload = self._read_json()
                    check_spec_id = payload.get("check_spec_id")
                    if not isinstance(check_spec_id, str) or not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    reason = payload.get("reason")
                    report = approve_check_spec(
                        db_path=resolved_db_path,
                        check_spec_id=check_spec_id,
                        reason=reason if isinstance(reason, str) else None,
                        actor_agent_identity_id=_lock_actor_agent_identity_id(payload),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/skill-revisions/rollback":
                    payload = self._read_json()
                    revision_id = payload.get("revision_id")
                    if not isinstance(revision_id, str) or not revision_id:
                        self._send_json(
                            {"error": "revision_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = rollback_skill_revision(
                        db_path=resolved_db_path,
                        revision_id=revision_id,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/context-rule-revisions/rollback":
                    payload = self._read_json()
                    revision_id = payload.get("revision_id")
                    if not isinstance(revision_id, str) or not revision_id:
                        self._send_json(
                            {"error": "revision_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = rollback_context_delivery_rule_revision(
                        db_path=resolved_db_path,
                        revision_id=revision_id,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/harness/prepare":
                    payload = self._read_json()
                    proposal_id = payload.get("proposal_id")
                    if not isinstance(proposal_id, str) or not proposal_id:
                        self._send_json(
                            {"error": "proposal_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = prepare_harness_proposal(
                        db_path=resolved_db_path,
                        proposal_id=proposal_id,
                    )
                    self._send_json(
                        {
                            "proposal_id": report.proposal_id,
                            "profile_id": report.profile_id,
                            "patch_transaction_ids": list(report.patch_transaction_ids),
                            "state": report.state,
                        }
                    )
                    return
                if path == "/api/harness/apply":
                    payload = self._read_json()
                    patch_transaction_id = payload.get("patch_transaction_id")
                    workspace_root = payload.get("workspace_root")
                    if not isinstance(patch_transaction_id, str) or not patch_transaction_id:
                        self._send_json(
                            {"error": "patch_transaction_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(workspace_root, str) or not workspace_root:
                        self._send_json(
                            {"error": "workspace_root_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = apply_patch_transaction(
                        db_path=resolved_db_path,
                        patch_transaction_id=patch_transaction_id,
                        workspace_root=Path(workspace_root),
                    )
                    self._send_json(
                        {
                            "patch_transaction_id": report.patch_transaction_id,
                            "proposal_id": report.proposal_id,
                            "profile_id": report.profile_id,
                            "target_paths": list(report.target_paths),
                            "status": report.status,
                        }
                    )
                    return
                if path == "/api/harness/rollback":
                    payload = self._read_json()
                    patch_transaction_id = payload.get("patch_transaction_id")
                    workspace_root = payload.get("workspace_root")
                    if not isinstance(patch_transaction_id, str) or not patch_transaction_id:
                        self._send_json(
                            {"error": "patch_transaction_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(workspace_root, str) or not workspace_root:
                        self._send_json(
                            {"error": "workspace_root_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = rollback_patch_transaction(
                        db_path=resolved_db_path,
                        patch_transaction_id=patch_transaction_id,
                        workspace_root=Path(workspace_root),
                    )
                    self._send_json(
                        {
                            "patch_transaction_id": report.patch_transaction_id,
                            "proposal_id": report.proposal_id,
                            "profile_id": report.profile_id,
                            "target_paths": list(report.target_paths),
                            "status": report.status,
                        }
                    )
                    return
                if path == "/api/checks/generate":
                    payload = self._read_json()
                    proposal_id = payload.get("proposal_id")
                    if not isinstance(proposal_id, str) or not proposal_id:
                        self._send_json(
                            {"error": "proposal_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = generate_checks_for_proposal(
                        db_path=resolved_db_path,
                        proposal_id=proposal_id,
                    )
                    self._send_json(
                        {
                            "proposal_id": report.proposal_id,
                            "profile_id": report.profile_id,
                            "check_spec_ids": list(report.check_spec_ids),
                            "existing_check_spec_ids": list(report.existing_check_spec_ids),
                        }
                    )
                    return
                if path == "/api/replay":
                    payload = self._read_json()
                    check_spec_id = payload.get("check_spec_id")
                    if not isinstance(check_spec_id, str) or not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = create_replay_run(
                        db_path=resolved_db_path,
                        check_spec_id=check_spec_id,
                        mode=str(payload.get("mode") or "dry_run"),
                        side_effect_mode=payload.get("side_effect_mode")
                        if isinstance(payload.get("side_effect_mode"), str)
                        else None,
                        source_run_id=payload.get("source_run_id")
                        if isinstance(payload.get("source_run_id"), str)
                        else None,
                    )
                    self._send_json(
                        {
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
                    )
                    return
                if path == "/api/checks/run":
                    payload = self._read_json()
                    check_spec_id = payload.get("check_spec_id")
                    if not isinstance(check_spec_id, str) or not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = run_check(
                        db_path=resolved_db_path,
                        check_spec_id=check_spec_id,
                        replay_run_id=payload.get("replay_run_id")
                        if isinstance(payload.get("replay_run_id"), str)
                        else None,
                    )
                    self._send_json(
                        {
                            "check_run_id": report.check_run_id,
                            "profile_id": report.profile_id,
                            "proposal_id": report.proposal_id,
                            "check_spec_id": report.check_spec_id,
                            "replay_run_id": report.replay_run_id,
                            "status": report.status,
                            "result": report.result,
                            "promoted_trust_level": report.promoted_trust_level,
                        }
                    )
                    return
                if path == "/api/judge-command":
                    payload = self._read_json()
                    check_spec_id = payload.get("check_spec_id")
                    raw_command = payload.get("command")
                    output_dir = payload.get("output_dir")
                    if not isinstance(check_spec_id, str) or not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(output_dir, str) or not output_dir:
                        self._send_json(
                            {"error": "output_dir_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if isinstance(raw_command, list) and all(isinstance(part, str) for part in raw_command):
                        command = list(raw_command)
                    elif isinstance(raw_command, str) and raw_command:
                        command = parse_judge_command(raw_command)
                    else:
                        self._send_json(
                            {"error": "command_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    timeout_seconds = payload.get("timeout_seconds", 120)
                    report = run_judge_command(
                        db_path=resolved_db_path,
                        check_spec_id=check_spec_id,
                        output_dir=Path(output_dir),
                        command=command,
                        replay_run_id=payload.get("replay_run_id")
                        if isinstance(payload.get("replay_run_id"), str)
                        else None,
                        timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 120,
                    )
                    self._send_json(_judge_command_payload(report))
                    return
                if path == "/api/replay/complete":
                    payload = self._read_json()
                    replay_run_id = payload.get("replay_run_id")
                    fixture_path = payload.get("fixture_path")
                    if not isinstance(replay_run_id, str) or not replay_run_id:
                        self._send_json(
                            {"error": "replay_run_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(fixture_path, str) or not fixture_path:
                        self._send_json(
                            {"error": "fixture_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = complete_replay_from_fixture(
                        db_path=resolved_db_path,
                        replay_run_id=replay_run_id,
                        fixture_path=Path(fixture_path),
                    )
                    self._send_json(
                        {
                            "replay_run_id": report.replay_run_id,
                            "profile_id": report.profile_id,
                            "check_spec_id": report.check_spec_id,
                            "output_run_id": report.output_run_id,
                            "status": report.status,
                            "result": report.result,
                            "ingested_counts": report.ingest_report.inserted_counts,
                        }
                    )
                    return
                if path == "/api/replay-adapters/run":
                    payload = self._read_json()
                    adapter_id = payload.get("adapter_id")
                    check_spec_id = payload.get("check_spec_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(check_spec_id, str) or not check_spec_id:
                        self._send_json(
                            {"error": "check_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = run_registered_replay_adapter(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                        check_spec_id=check_spec_id,
                        run_check_after=bool(payload.get("run_check", True)),
                    )
                    self._send_json(
                        {
                            "adapter_id": adapter_id,
                            **_replay_run_report_payload(report),
                        }
                    )
                    return
                if path == "/api/source-adapter-template":
                    payload = self._read_json()
                    output_path = payload.get("output_path")
                    if not isinstance(output_path, str) or not output_path:
                        self._send_json(
                            {"error": "output_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    framework = payload.get("framework")
                    profile_name = payload.get("profile_name")
                    report = write_source_adapter_template(
                        output_path=Path(output_path),
                        framework=framework if isinstance(framework, str) and framework else "generic-python",
                        profile_name=profile_name if isinstance(profile_name, str) and profile_name else "kyoko-agent",
                        force=bool(payload.get("force", False)),
                    )
                    self._send_json(_template_report_payload(report))
                    return
                if path == "/api/replay-server-template":
                    payload = self._read_json()
                    output_path = payload.get("output_path")
                    if not isinstance(output_path, str) or not output_path:
                        self._send_json(
                            {"error": "output_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    framework = payload.get("framework")
                    profile_name = payload.get("profile_name")
                    report = write_replay_server_template(
                        output_path=Path(output_path),
                        framework=framework if isinstance(framework, str) and framework else "generic-python",
                        profile_name=profile_name if isinstance(profile_name, str) and profile_name else "kyoko-agent",
                        force=bool(payload.get("force", False)),
                    )
                    self._send_json(_template_report_payload(report))
                    return
                if path == "/api/integration-smoke/source":
                    payload = self._read_json()
                    adapter_path = payload.get("adapter_path")
                    hook = payload.get("hook")
                    if not isinstance(adapter_path, str) or not adapter_path:
                        self._send_json(
                            {"error": "adapter_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(hook, str) or not hook:
                        self._send_json(
                            {"error": "hook_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = run_source_adapter_smoke(
                        db_path=resolved_db_path,
                        adapter_path=Path(adapter_path),
                        hook=hook,
                        output_dir=_optional_path(payload.get("output_dir")),
                        profile_id=_optional_str(payload.get("profile_id")),
                        profile_name=_optional_str(payload.get("profile_name")),
                        root_path=_optional_path(payload.get("root_path")),
                        source_id=_optional_str(payload.get("source_id")),
                        agent_id=_optional_str(payload.get("agent_id")),
                        agent_name=_optional_str(payload.get("agent_name")),
                        cwd=_optional_path(payload.get("cwd")),
                        timeout_seconds=_optional_int(payload.get("timeout_seconds"), 30),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/integration-smoke/replay-server":
                    payload = self._read_json()
                    command = payload.get("command")
                    server_url = payload.get("server_url")
                    if not isinstance(command, str) or not command:
                        self._send_json(
                            {"error": "command_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(server_url, str) or not server_url:
                        self._send_json(
                            {"error": "server_url_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = run_replay_server_smoke(
                        command=parse_replay_command(command),
                        server_url=server_url,
                        output_dir=_optional_path(payload.get("output_dir")),
                        health_path=_optional_str(payload.get("health_path")) or "/health",
                        run_replay=bool(payload.get("run_replay", False)),
                        replay_path=_optional_str(payload.get("replay_path")) or "/replay",
                        replay_request=payload.get("replay_request")
                        if isinstance(payload.get("replay_request"), dict)
                        else None,
                        replay_hook=_optional_str(payload.get("hook")),
                        replay_timeout_seconds=_optional_int(payload.get("replay_timeout_seconds"), 10),
                        startup_timeout_seconds=_optional_int(payload.get("startup_timeout_seconds"), 10),
                        stop_timeout_seconds=_optional_int(payload.get("stop_timeout_seconds"), 5),
                        cwd=_optional_path(payload.get("cwd")),
                        log_max_bytes=_optional_int(payload.get("log_max_bytes"), 40000),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/mcp-install-smoke":
                    payload = self._read_json()
                    scope = payload.get("scope", "user")
                    output_dir = payload.get("output_dir")
                    timeout_seconds = payload.get("timeout_seconds", 30)
                    report = run_mcp_install_smoke_matrix(
                        db_path=resolved_db_path,
                        schema_path=None,
                        server_name="kyoko",
                        scope=scope if isinstance(scope, str) and scope else "user",
                        output_dir=Path(output_dir)
                        if isinstance(output_dir, str) and output_dir
                        else resolved_db_path.parent / "mcp-install-smoke",
                        timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 30,
                        verify_list=not bool(payload.get("skip_list_verify", False)),
                        skip_missing=not bool(payload.get("fail_on_missing", False)),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/import-hermes-kanban":
                    payload = self._read_json()
                    kanban_db_path = payload.get("kanban_db_path")
                    if not isinstance(kanban_db_path, str) or not kanban_db_path:
                        self._send_json(
                            {"error": "kanban_db_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    output_path = _optional_path(payload.get("output_path"))
                    report = ingest_hermes_kanban_db(
                        db_path=resolved_db_path,
                        kanban_db_path=Path(kanban_db_path).expanduser(),
                        profile_id=_optional_str(payload.get("profile_id")),
                        profile_name=_optional_str(payload.get("profile_name")),
                        root_path=_expanded_path(payload.get("root_path")),
                        board=_optional_str(payload.get("board")) or "default",
                        output_path=output_path.expanduser() if output_path else None,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/import-openclaw-sessions":
                    payload = self._read_json()
                    session_path = payload.get("session_path")
                    if not isinstance(session_path, str) or not session_path:
                        self._send_json(
                            {"error": "session_path_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    output_path = _optional_path(payload.get("output_path"))
                    report = ingest_openclaw_sessions(
                        db_path=resolved_db_path,
                        source_path=Path(session_path).expanduser(),
                        profile_id=_optional_str(payload.get("profile_id")),
                        profile_name=_optional_str(payload.get("profile_name")),
                        root_path=_expanded_path(payload.get("root_path")),
                        agent_id=_optional_str(payload.get("agent_id")),
                        session_key=_optional_str(payload.get("session_key")),
                        output_path=output_path.expanduser() if output_path else None,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/import-discovered-source":
                    payload = self._read_json()
                    candidate_id = payload.get("candidate_id")
                    if not isinstance(candidate_id, str) or not candidate_id:
                        self._send_json(
                            {"error": "candidate_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    output_dir = _optional_path(payload.get("output_dir"))
                    report = import_discovered_source(
                        db_path=resolved_db_path,
                        candidate_id=candidate_id,
                        home=_expanded_path(payload.get("home")),
                        profile_id=_optional_str(payload.get("profile_id")),
                        profile_name=_optional_str(payload.get("profile_name")),
                        root_path=_expanded_path(payload.get("root_path")),
                        output_dir=output_dir.expanduser() if output_dir else None,
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/replay-servers/start":
                    payload = self._read_json()
                    adapter_id = payload.get("adapter_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = start_registered_replay_server_adapter(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                    )
                    self._send_json(_replay_server_process_payload(report, adapter_id=adapter_id))
                    return
                if path == "/api/replay-servers/status":
                    payload = self._read_json()
                    adapter_id = payload.get("adapter_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = registered_replay_server_status(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                    )
                    self._send_json(_replay_server_process_payload(report, adapter_id=adapter_id))
                    return
                if path == "/api/replay-servers/logs":
                    payload = self._read_json()
                    adapter_id = payload.get("adapter_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    max_bytes = payload.get("max_bytes", 40000)
                    report = registered_replay_server_logs(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                        max_bytes=max_bytes if isinstance(max_bytes, int) else 40000,
                    )
                    self._send_json(_replay_server_logs_payload(report, adapter_id=adapter_id))
                    return
                if path == "/api/replay-servers/stop":
                    payload = self._read_json()
                    adapter_id = payload.get("adapter_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = stop_registered_replay_server_adapter(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                    )
                    self._send_json(_replay_server_process_payload(report, adapter_id=adapter_id))
                    return
                if path == "/api/operator-adapters/run":
                    payload = self._read_json()
                    adapter_id = payload.get("adapter_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    output_dir = payload.get("output_dir")
                    profile_id = payload.get("profile_id")
                    run_id = payload.get("run_id")
                    report = run_registered_operator_adapter(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                        output_dir=Path(output_dir) if isinstance(output_dir, str) and output_dir else None,
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        run_id=run_id if isinstance(run_id, str) and run_id else None,
                    )
                    self._send_json(
                        {
                            "adapter_id": adapter_id,
                            "operator": report.operator,
                            "profile_id": report.profile_id,
                            "issue_ids": list(report.issue_ids),
                            "new_issue_ids": list(report.new_issue_ids),
                            "bundled_issue_ids": list(report.bundled_issue_ids),
                            "operator_run_id": report.operator_run_id,
                            "evidence_path": str(report.evidence_path),
                            "prompt_path": str(report.prompt_path),
                            "persisted": report.persisted,
                            "raw_output_path": str(report.raw_output_path)
                            if report.raw_output_path
                            else None,
                        }
                    )
                    return
                if path == "/api/operator-adapters/bootstrap":
                    payload = self._read_json()
                    target = payload.get("target", "all")
                    output_dir = payload.get("output_dir")
                    profile_id = payload.get("profile_id")
                    timeout_seconds = payload.get("timeout_seconds", 120)
                    report = bootstrap_operator_adapters(
                        db_path=resolved_db_path,
                        target=target if isinstance(target, str) and target else "all",
                        profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                        output_dir=Path(output_dir) if isinstance(output_dir, str) and output_dir else None,
                        timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 120,
                        enabled=bool(payload.get("enabled", True)),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/analysis/run":
                    payload = self._read_json()
                    try:
                        job = _analysis_job_from_payload(payload)
                    except AnalysisRunError as exc:
                        self._send_json(
                            {"error": "invalid_analysis_job", "detail": str(exc)},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    job_id = selected_analysis_runner.submit(job)
                    self._send_json(
                        {"job_id": job_id, "analyzer": job.analyzer, "status": "queued"},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if path == "/api/analysis/cancel":
                    payload = self._read_json()
                    job_id = payload.get("job_id")
                    if not isinstance(job_id, str) or not job_id:
                        self._send_json({"error": "job_id_required"}, status=HTTPStatus.BAD_REQUEST)
                        return
                    # In-process only: a cancel reaches the job iff it's running in
                    # this serve process. Unknown id (already done / queued elsewhere)
                    # is reported as cancelled=False, not an error.
                    cancelled = cancellation.request_cancel(job_id)
                    self._send_json({"job_id": job_id, "cancelled": cancelled})
                    return
                if path == "/api/analysis/schedules/create":
                    payload = self._read_json()
                    analyzer = payload.get("analyzer") or payload.get("analyzer_kind")
                    if not isinstance(analyzer, str) or analyzer not in ANALYSIS_SCHEDULE_ANALYZER_KINDS:
                        self._send_json(
                            {
                                "error": "unschedulable_analyzer",
                                "detail": f"schedulable analyzers: {list(ANALYSIS_SCHEDULE_ANALYZER_KINDS)}",
                            },
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    interval_hours = payload.get("interval_hours", 24)
                    at_time = payload.get("at_time")
                    metadata = None
                    templates = payload.get("templates") or payload.get("llm_eval_ids")
                    if isinstance(templates, list) and templates:
                        metadata = {"llm_eval_ids": [str(t) for t in templates]}
                    try:
                        schedule = create_analysis_schedule(
                            db_path=resolved_db_path,
                            analyzer_kind=analyzer,
                            adapter_id=_optional_str(payload.get("adapter_id")),
                            source_path=_optional_str(payload.get("source_path")),
                            refresh_import=bool(payload.get("refresh_import", True)),
                            interval_hours=interval_hours if isinstance(interval_hours, int) else 24,
                            at_time=_optional_str(at_time),
                            enabled=bool(payload.get("enabled", True)),
                            run_autonomy=bool(payload.get("run_autonomy", True)),
                            next_run_at=next_run_at_iso(
                                interval_hours if isinstance(interval_hours, int) else 24,
                                _optional_str(at_time),
                            ),
                            profile_id=_optional_str(payload.get("profile_id")),
                            metadata=metadata,
                        )
                    except StorageError as exc:
                        self._send_json(
                            {"error": "invalid_schedule", "detail": str(exc)},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json({"schedule": schedule})
                    return
                if path == "/api/analysis/schedules/update":
                    payload = self._read_json()
                    schedule_id = payload.get("id") or payload.get("schedule_id")
                    if not isinstance(schedule_id, str) or not schedule_id:
                        self._send_json(
                            {"error": "schedule_id_required"}, status=HTTPStatus.BAD_REQUEST
                        )
                        return
                    fields = _schedule_update_fields(payload)
                    schedule = update_analysis_schedule(
                        db_path=resolved_db_path, schedule_id=schedule_id, **fields
                    )
                    self._send_json({"schedule": schedule})
                    return
                if path == "/api/analysis/schedules/delete":
                    payload = self._read_json()
                    schedule_id = payload.get("id") or payload.get("schedule_id")
                    if not isinstance(schedule_id, str) or not schedule_id:
                        self._send_json(
                            {"error": "schedule_id_required"}, status=HTTPStatus.BAD_REQUEST
                        )
                        return
                    deleted = delete_analysis_schedule(
                        db_path=resolved_db_path, schedule_id=schedule_id
                    )
                    self._send_json({"deleted": deleted, "id": schedule_id})
                    return
                if path == "/api/analysis/schedules/run":
                    payload = self._read_json()
                    schedule_id = payload.get("id") or payload.get("schedule_id")
                    schedule = (
                        get_analysis_schedule(db_path=resolved_db_path, schedule_id=schedule_id)
                        if isinstance(schedule_id, str) and schedule_id
                        else None
                    )
                    if schedule is None:
                        self._send_json(
                            {"error": "analysis_schedule_not_found", "id": schedule_id},
                            status=HTTPStatus.NOT_FOUND,
                        )
                        return
                    job = job_from_schedule(schedule)
                    job_id = selected_analysis_runner.submit(job)
                    self._send_json(
                        {"job_id": job_id, "schedule_id": schedule_id, "status": "queued"},
                        status=HTTPStatus.ACCEPTED,
                    )
                    return
                if path == "/api/operator-smoke":
                    payload = self._read_json()
                    operator = payload.get("operator", "mock")
                    operator_adapter = payload.get("operator_adapter") or payload.get("adapter_id")
                    output_dir = payload.get("output_dir")
                    profile_id = payload.get("profile_id")
                    run_id = payload.get("run_id")
                    timeout_seconds = payload.get("timeout_seconds", 120)
                    max_retries = payload.get("max_retries", 0)
                    use_current_db = bool(payload.get("use_current_db", False))
                    prepare_only = bool(payload.get("prepare_only", False))
                    all_presets = bool(payload.get("all_presets", False))
                    fail_on_missing = bool(payload.get("fail_on_missing", False))
                    raw_command = payload.get("command") or payload.get("operator_command")
                    operator_command = (
                        parse_operator_command(raw_command) if isinstance(raw_command, str) and raw_command else None
                    )
                    if all_presets:
                        report = run_operator_smoke_matrix(
                            prepare_only=prepare_only,
                            db_path=resolved_db_path if use_current_db else None,
                            output_dir=Path(output_dir) if isinstance(output_dir, str) and output_dir else None,
                            profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                            run_id=run_id if isinstance(run_id, str) and run_id else None,
                            timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 120,
                            max_retries=max_retries if isinstance(max_retries, int) else 0,
                            skip_missing=not fail_on_missing,
                        )
                        self._send_json(report.to_json())
                        return
                    common_kwargs = {
                        "operator": operator if isinstance(operator, str) and operator else "mock",
                        "db_path": resolved_db_path if use_current_db else None,
                        "output_dir": Path(output_dir) if isinstance(output_dir, str) and output_dir else None,
                        "operator_command": operator_command,
                        "operator_adapter": operator_adapter
                        if isinstance(operator_adapter, str) and operator_adapter
                        else None,
                        "profile_id": profile_id if isinstance(profile_id, str) and profile_id else None,
                        "run_id": run_id if isinstance(run_id, str) and run_id else None,
                    }
                    if prepare_only:
                        report = build_operator_smoke_plan(**common_kwargs)
                        self._send_json(report.to_json())
                        return
                    report = run_operator_smoke(
                        **common_kwargs,
                        timeout_seconds=timeout_seconds if isinstance(timeout_seconds, int) else 120,
                        max_retries=max_retries if isinstance(max_retries, int) else 0,
                    )
                    self._send_json(report.to_json())
                    return
                self._send_json({"error": "not_found", "path": path}, status=HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json(
                    {"error": "invalid_json", "detail": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except ApplyError as exc:
                self._send_json(
                    {"error": "apply_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except (AutonomyError, AutonomyRunError, RedactionError, RetentionError) as exc:
                self._send_json(
                    {"error": "policy_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except HarnessError as exc:
                self._send_json(
                    {"error": "harness_prepare_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except CheckError as exc:
                self._send_json(
                    {"error": "check_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except (ReplayAdapterError, ReplayServerError) as exc:
                self._send_json(
                    {"error": "replay_adapter_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except (ReplayTemplateError, SourceTemplateError) as exc:
                self._send_json(
                    {"error": "template_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except IntegrationSmokeError as exc:
                self._send_json(
                    {"error": "integration_smoke_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except LoadSmokeError as exc:
                self._send_json(
                    {"error": "load_smoke_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except McpError as exc:
                self._send_json(
                    {"error": "mcp_install_smoke_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except HermesImportError as exc:
                self._send_json(
                    {"error": "hermes_import_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except OpenClawImportError as exc:
                self._send_json(
                    {"error": "openclaw_import_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except SourceDiscoveryError as exc:
                self._send_json(
                    {"error": "source_discovery_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except (AnalyzeError, OperatorAdapterError) as exc:
                self._send_json(
                    {"error": "operator_adapter_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except AnalysisRunError as exc:
                self._send_json(
                    {"error": "invalid_analysis_job", "detail": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except OperatorSmokeError as exc:
                self._send_json(
                    {"error": "operator_smoke_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except ImproveError as exc:
                self._send_json(
                    {"error": "improve_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except ProfileNextError as exc:
                self._send_json(
                    {"error": "profile_next_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except DemoError as exc:
                self._send_json(
                    {"error": "demo_failed", "detail": str(exc)},
                    status=HTTPStatus.CONFLICT,
                )
            except (StorageError, RedactionError) as exc:
                self._send_json(
                    {"error": "storage_error", "detail": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )
            except OtlpNormalizeError as exc:
                self._send_json(
                    {"error": "otlp_ingest_failed", "detail": str(exc)},
                    status=HTTPStatus.BAD_REQUEST,
                )

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(str(exc)) from exc
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_auth_cookie_if_needed()
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_sse_stream(self) -> None:
            """Stream live-bus events to the client as Server-Sent Events.

            Loopback-only (the server refuses remote hosts without auth, and the
            dashboard is local). Each handler runs on its own daemon thread, so a
            long-lived stream never blocks other requests or shutdown.
            """

            bus = global_bus()
            subscriber = bus.subscribe()
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self._send_auth_cookie_if_needed()
            try:
                self.end_headers()
                # Prelude comment so the client opens the stream immediately.
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        message = subscriber.get(timeout=15.0)
                    except _queue.Empty:
                        # Keepalive ping so proxies/clients don't time the stream out.
                        self.wfile.write(f": {EVENT_PING}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        continue
                    frame = (
                        f"event: {message['event']}\n"
                        f"data: {json.dumps(message['data'], sort_keys=True)}\n\n"
                    )
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                return
            finally:
                bus.unsubscribe(subscriber)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_auth_cookie_if_needed()
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _serve_spa_index(self) -> None:
            index = SPA_BUNDLE_DIR / "index.html"
            try:
                body = index.read_bytes()
            except OSError:
                self._send_html(_dashboard_html())
                return
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # The HTML shell must not be cached (it references hashed asset names);
            # the hashed /assets/* files below are immutable and cached aggressively.
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_auth_cookie_if_needed()
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _serve_static_file(self, file_path: Path) -> None:
            try:
                body = file_path.read_bytes()
            except OSError:
                self._send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            content_type = _STATIC_CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # Vite emits content-hashed filenames under /assets, so they are safe to
            # cache immutably; everything else stays uncached.
            if "/assets/" in file_path.as_posix():
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            else:
                self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _send_auth_required(self) -> None:
            self._send_json(
                {"error": "auth_required", "detail": "Valid Kyoko auth token required."},
                status=HTTPStatus.UNAUTHORIZED,
            )

        def _send_unsupported_media_type(self) -> None:
            self._send_json(
                {
                    "error": "unsupported_media_type",
                    "detail": "POST requests must use application/json.",
                },
                status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
            )

        def _has_json_content_type(self) -> bool:
            content_type = self.headers.get("Content-Type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            return media_type == "application/json"

        def _is_authorized(self) -> bool:
            if selected_auth_token is None:
                return True
            provided = self._auth_token_from_request()
            return provided is not None and secrets.compare_digest(provided, selected_auth_token)

        def _auth_token_from_request(self) -> Optional[str]:
            authorization = self.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                return authorization[len("Bearer ") :].strip()
            header_token = self.headers.get("X-Kyoko-Token")
            if header_token:
                return header_token.strip()
            query_token = _query_param(self.path, "token")
            if query_token:
                return query_token
            cookie = self.headers.get("Cookie", "")
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == "kyoko_token" and value:
                    return value
            return None

        def _send_auth_cookie_if_needed(self) -> None:
            if selected_auth_token is None:
                return
            query_token = _query_param(self.path, "token")
            if query_token is not None and secrets.compare_digest(query_token, selected_auth_token):
                cookie_value = quote(query_token, safe="")
                self.send_header(
                    "Set-Cookie",
                    f"kyoko_token={cookie_value}; Path=/; HttpOnly; SameSite=Strict",
                )

    return KyokoRequestHandler


def _request_path(raw_path: str) -> str:
    parsed = urlparse(raw_path)
    return parsed.path or "/"


def _query_param(raw_path: str, key: str) -> Optional[str]:
    values = parse_qs(urlparse(raw_path).query).get(key)
    if not values:
        return None
    value = values[0]
    return value if value else None


def _query_path(raw_path: str, key: str) -> Optional[Path]:
    value = _query_param(raw_path, key)
    return Path(value).expanduser() if value else None


def _query_int(raw_path: str, key: str, default: int) -> int:
    value = _query_param(raw_path, key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _optional_str(value: object) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _analyzer_availability(db_path: Path) -> dict[str, Any]:
    """Report which dashboard analyzers are usable: which CLIs are on PATH and which
    operator adapters are registered. Drives the picker's enabled/disabled state."""

    adapters = {a["id"]: a for a in list_operator_adapters(db_path)}
    analyzers: list[dict[str, Any]] = []
    for kind in DASHBOARD_ANALYZERS:
        # ACE is a skillbook-diff path (its own command), not an operator preset.
        preset = OPERATOR_PRESETS.get(kind)
        command = preset.command[0] if preset is not None else ("ace" if kind == "ace" else kind)
        analyzers.append(
            {
                "analyzer": kind,
                "installed": shutil.which(command) is not None,
                "command": command,
                "adapter_registered": kind in adapters,
                "schedulable": kind in SCHEDULABLE_ANALYZERS,
            }
        )
    return {"analyzers": analyzers, "schedulable": list(SCHEDULABLE_ANALYZERS)}


def _analysis_job_from_payload(payload: dict[str, Any]) -> AnalysisJob:
    analyzer = payload.get("analyzer")
    if not isinstance(analyzer, str) or not analyzer:
        raise AnalysisRunError("analyzer_required")
    ace_command = payload.get("ace_command")
    operator_command = payload.get("operator_command")
    timeout = payload.get("timeout_seconds", DEFAULT_ANALYSIS_TIMEOUT_SECONDS)
    max_retries = payload.get("max_retries", 0)
    return AnalysisJob(
        analyzer=analyzer,
        adapter_id=_optional_str(payload.get("adapter_id")),
        scope=str(payload.get("scope") or "all"),
        run_id=_optional_str(payload.get("run_id")),
        since=_optional_str(payload.get("since")),
        refresh_import=bool(payload.get("refresh_import", False)),
        source_kind=_optional_str(payload.get("source_kind")),
        source_path=_optional_str(payload.get("source_path")),
        run_autonomy=bool(payload.get("run_autonomy", True)),
        ace_command=ace_command if isinstance(ace_command, list) and ace_command else None,
        operator_command=(
            operator_command if isinstance(operator_command, list) and operator_command else None
        ),
        timeout_seconds=timeout if isinstance(timeout, int) else DEFAULT_ANALYSIS_TIMEOUT_SECONDS,
        max_retries=max_retries if isinstance(max_retries, int) else 0,
        profile_id=_optional_str(payload.get("profile_id")),
    )


def _schedule_update_fields(payload: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if "adapter_id" in payload:
        fields["adapter_id"] = _optional_str(payload.get("adapter_id"))
    if "source_path" in payload:
        fields["source_path"] = _optional_str(payload.get("source_path"))
    if "at_time" in payload:
        fields["at_time"] = _optional_str(payload.get("at_time"))
    if "refresh_import" in payload:
        fields["refresh_import"] = bool(payload.get("refresh_import"))
    if "enabled" in payload:
        fields["enabled"] = bool(payload.get("enabled"))
    if "run_autonomy" in payload:
        fields["run_autonomy"] = bool(payload.get("run_autonomy"))
    if isinstance(payload.get("interval_hours"), int):
        fields["interval_hours"] = payload["interval_hours"]
    # Recompute next_run_at when cadence changes so the new timing takes effect.
    if "interval_hours" in fields or "at_time" in fields:
        interval = fields.get("interval_hours", payload.get("interval_hours", 24))
        fields["next_run_at"] = next_run_at_iso(
            interval if isinstance(interval, int) else 24,
            fields.get("at_time", _optional_str(payload.get("at_time"))),
        )
    return fields


def _header_str(value: object) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_path(value: object) -> Optional[Path]:
    text = _optional_str(value)
    return Path(text) if text is not None else None


def _expanded_path(value: object) -> Optional[Path]:
    path = _optional_path(value)
    return path.expanduser() if path else None


def _optional_int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _optional_int_or_none(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _optional_float(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    return normalized in {"127.0.0.1", "localhost", "::1"} or normalized.startswith("127.")


def _evidence_summary(db_path: Path, *, profile_id: Optional[str] = None) -> dict[str, Any]:
    try:
        bundle = build_evidence_bundle(
            db_path=db_path,
            profile_id=profile_id,
            consumer="api:evidence-summary",
        )
    except StorageError as exc:
        if str(exc) == "no profiles found" or "database does not exist" in str(exc):
            return {"profile_id": None, "run_id": None, "summary": None}
        raise
    return {
        "profile_id": bundle["profile_id"],
        "run_id": bundle.get("run_id"),
        "summary": bundle["summary"],
        "redaction": bundle.get("redaction"),
    }


def _replay_run_report_payload(report: object) -> dict[str, Any]:
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
    return payload


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


def _replay_server_process_payload(report: object, *, adapter_id: str) -> dict[str, Any]:
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


def _replay_server_logs_payload(report: object, *, adapter_id: str) -> dict[str, Any]:
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


def _frameworks_payload(frameworks: dict[str, str]) -> list[dict[str, str]]:
    return [
        {"id": framework_id, "name": name}
        for framework_id, name in sorted(frameworks.items())
    ]


def _template_report_payload(report: object) -> dict[str, Any]:
    return {
        "output_path": str(getattr(report, "output_path")),
        "framework": getattr(report, "framework"),
        "profile_name": getattr(report, "profile_name"),
        "wrote": getattr(report, "wrote"),
    }



def _dashboard_html() -> str:
    """Minimal fallback page served only when the built SPA bundle is absent.

    The shipping dashboard is the React/Vite SPA built into ``assets/web``. When
    that bundle is missing (``spa_bundle_available()`` is false), this stub
    explains how to build it. Serving is loopback-only.
    """
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        '<head>\n'
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Kyoko</title>\n"
        "</head>\n"
        "<body>\n"
        "  <h1>Kyoko</h1>\n"
        "  <p>The dashboard bundle isn't built yet. Build it with:</p>\n"
        "  <pre>cd frontend &amp;&amp; npm run build</pre>\n"
        "  <p>Run <code>cd frontend && npm run build</code>, then reload.</p>\n"
        "  <p>Then reload. The dashboard is served loopback-only.</p>\n"
        "</body>\n"
        "</html>\n"
    )
