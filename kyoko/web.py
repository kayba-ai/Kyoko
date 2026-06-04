from __future__ import annotations

import json
import queue as _queue
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional, Type
from urllib.parse import parse_qs, quote, urlparse

from .analyze import AnalyzeError, list_operator_runs, parse_operator_command
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
from .blobs import list_payload_blobs, prune_payload_blobs, storage_report
from .dashboard_metrics import DashboardMetricsError, get_dashboard_metrics
from .demo import DemoError, run_demo_setup
from .details import (
    DetailError,
    get_eval_detail,
    get_issue_detail,
    get_proposal_detail,
    get_replay_detail,
    get_run_detail,
    list_runs,
)
from .issues import IssueError, create_issue, list_issues
from .doctor import DEFAULT_SMOKE_EVIDENCE_DIR, run_doctor
from .evidence import build_evidence_bundle
from .evals import (
    EvalError,
    approve_eval_spec,
    complete_replay_from_fixture,
    create_replay_run,
    generate_evals_for_proposal,
    list_assertion_presets,
    list_eval_capabilities,
    list_eval_runs,
    list_eval_spec_locks,
    list_eval_specs,
    list_replay_runs,
    parse_judge_command,
    parse_replay_command,
    run_eval,
    run_judge_command,
    set_eval_spec_lock,
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
from .operator_presets import bootstrap_operator_adapters, list_operator_presets
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
    StorageError,
    checkpoint_database,
    get_database_status,
    ingest_source_payload,
    initialize_database,
    status_to_json,
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
    handler = make_handler(
        db_path,
        auth_token=auth_token,
        default_lock_actor_agent_identity_id=default_lock_actor_agent_identity_id,
    )
    try:
        server = ThreadingHTTPServer((host, port), handler)
    except OSError as exc:
        raise WebError(f"server_bind_failed:{host}:{port}:{exc}") from exc

    try:
        server.serve_forever()
    finally:
        server.server_close()


def make_handler(
    db_path: Path,
    *,
    auth_token: Optional[str] = None,
    default_lock_actor_agent_identity_id: Optional[str] = None,
) -> Type[BaseHTTPRequestHandler]:
    resolved_db_path = db_path
    selected_auth_token = auth_token if auth_token else None
    selected_default_lock_actor_agent_identity_id = _optional_string(
        default_lock_actor_agent_identity_id
    )

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
                    self._send_json(
                        {
                            "proposals": list_learning_proposals(
                                resolved_db_path,
                                profile_id=profile_id if profile_id else None,
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
                if path == "/api/evals":
                    self._send_json(
                        {
                            "eval_specs": list_eval_specs(resolved_db_path),
                            "eval_runs": list_eval_runs(resolved_db_path),
                            "replay_runs": list_replay_runs(resolved_db_path),
                        }
                    )
                    return
                if path == "/api/eval-assertion-presets":
                    self._send_json({"assertion_presets": list_assertion_presets()})
                    return
                if path == "/api/eval-capabilities":
                    self._send_json(list_eval_capabilities())
                    return
                if path == "/api/eval-spec-locks":
                    query = parse_qs(urlparse(self.path).query)
                    profile_id = query.get("profile_id", [None])[0]
                    include_unlocked = query.get("include_unlocked", ["0"])[0] in {"1", "true", "yes"}
                    self._send_json(
                        {
                            "eval_spec_locks": list_eval_spec_locks(
                                resolved_db_path,
                                profile_id=profile_id if isinstance(profile_id, str) and profile_id else None,
                                locked_only=not include_unlocked,
                            )
                        }
                    )
                    return
                if path == "/api/eval-detail":
                    eval_spec_id = _query_param(self.path, "id")
                    if not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    self._send_json(get_eval_detail(db_path=resolved_db_path, eval_spec_id=eval_spec_id))
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
                if path == "/api/policy":
                    payload = self._read_json()
                    policy = update_autonomy_policy(
                        db_path=resolved_db_path,
                        profile_id=payload.get("profile_id")
                        if isinstance(payload.get("profile_id"), str)
                        else None,
                        context_mode=payload.get("context_mode")
                        if isinstance(payload.get("context_mode"), str)
                        else None,
                        harness_mode=payload.get("harness_mode")
                        if isinstance(payload.get("harness_mode"), str)
                        else None,
                        allow_repo_patch=payload.get("allow_repo_patch")
                        if isinstance(payload.get("allow_repo_patch"), bool)
                        else None,
                        allow_eval_write=payload.get("allow_eval_write")
                        if isinstance(payload.get("allow_eval_write"), bool)
                        else None,
                        allow_skillbook_write=payload.get("allow_skillbook_write")
                        if isinstance(payload.get("allow_skillbook_write"), bool)
                        else None,
                        dirty_worktree_policy=payload.get("dirty_worktree_policy")
                        if isinstance(payload.get("dirty_worktree_policy"), str)
                        else None,
                    )
                    self._send_json({"policy": policy})
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
                        replay_adapter_id=replay_adapter_id if isinstance(replay_adapter_id, str) and replay_adapter_id else None,
                        replay_output_dir=Path(replay_output_dir)
                        if isinstance(replay_output_dir, str) and replay_output_dir
                        else None,
                        replay_timeout_seconds=replay_timeout if isinstance(replay_timeout, int) else None,
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
                if path == "/api/eval-specs/lock":
                    payload = self._read_json()
                    eval_spec_id = payload.get("eval_spec_id")
                    if not isinstance(eval_spec_id, str) or not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    reason = payload.get("reason")
                    report = set_eval_spec_lock(
                        db_path=resolved_db_path,
                        eval_spec_id=eval_spec_id,
                        locked=bool(payload.get("locked")),
                        reason=reason if isinstance(reason, str) else None,
                        actor_agent_identity_id=_lock_actor_agent_identity_id(payload),
                    )
                    self._send_json(report.to_json())
                    return
                if path == "/api/eval-specs/approve":
                    payload = self._read_json()
                    eval_spec_id = payload.get("eval_spec_id")
                    if not isinstance(eval_spec_id, str) or not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    reason = payload.get("reason")
                    report = approve_eval_spec(
                        db_path=resolved_db_path,
                        eval_spec_id=eval_spec_id,
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
                if path == "/api/evals/generate":
                    payload = self._read_json()
                    proposal_id = payload.get("proposal_id")
                    if not isinstance(proposal_id, str) or not proposal_id:
                        self._send_json(
                            {"error": "proposal_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = generate_evals_for_proposal(
                        db_path=resolved_db_path,
                        proposal_id=proposal_id,
                    )
                    self._send_json(
                        {
                            "proposal_id": report.proposal_id,
                            "profile_id": report.profile_id,
                            "eval_spec_ids": list(report.eval_spec_ids),
                            "existing_eval_spec_ids": list(report.existing_eval_spec_ids),
                        }
                    )
                    return
                if path == "/api/replay":
                    payload = self._read_json()
                    eval_spec_id = payload.get("eval_spec_id")
                    if not isinstance(eval_spec_id, str) or not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = create_replay_run(
                        db_path=resolved_db_path,
                        eval_spec_id=eval_spec_id,
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
                            "eval_spec_id": report.eval_spec_id,
                            "source_run_id": report.source_run_id,
                            "mode": report.mode,
                            "side_effect_mode": report.side_effect_mode,
                            "status": report.status,
                            "result": report.result,
                        }
                    )
                    return
                if path == "/api/evals/run":
                    payload = self._read_json()
                    eval_spec_id = payload.get("eval_spec_id")
                    if not isinstance(eval_spec_id, str) or not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = run_eval(
                        db_path=resolved_db_path,
                        eval_spec_id=eval_spec_id,
                        replay_run_id=payload.get("replay_run_id")
                        if isinstance(payload.get("replay_run_id"), str)
                        else None,
                    )
                    self._send_json(
                        {
                            "eval_run_id": report.eval_run_id,
                            "profile_id": report.profile_id,
                            "proposal_id": report.proposal_id,
                            "eval_spec_id": report.eval_spec_id,
                            "replay_run_id": report.replay_run_id,
                            "status": report.status,
                            "result": report.result,
                            "promoted_trust_level": report.promoted_trust_level,
                        }
                    )
                    return
                if path == "/api/judge-command":
                    payload = self._read_json()
                    eval_spec_id = payload.get("eval_spec_id")
                    raw_command = payload.get("command")
                    output_dir = payload.get("output_dir")
                    if not isinstance(eval_spec_id, str) or not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
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
                        eval_spec_id=eval_spec_id,
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
                            "eval_spec_id": report.eval_spec_id,
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
                    eval_spec_id = payload.get("eval_spec_id")
                    if not isinstance(adapter_id, str) or not adapter_id:
                        self._send_json(
                            {"error": "adapter_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    if not isinstance(eval_spec_id, str) or not eval_spec_id:
                        self._send_json(
                            {"error": "eval_spec_id_required"},
                            status=HTTPStatus.BAD_REQUEST,
                        )
                        return
                    report = run_registered_replay_adapter(
                        db_path=resolved_db_path,
                        adapter_id=adapter_id,
                        eval_spec_id=eval_spec_id,
                        run_eval_after=bool(payload.get("run_eval", True)),
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
                            "proposal_id": report.proposal_id,
                            "operator_run_id": report.operator_run_id,
                            "evidence_path": str(report.evidence_path),
                            "prompt_path": str(report.prompt_path),
                            "proposal_path": str(report.proposal_path),
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
            except EvalError as exc:
                self._send_json(
                    {"error": "eval_failed", "detail": str(exc)},
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
    eval_run = getattr(report, "eval_run", None)
    payload: dict[str, Any] = {
        "replay_run_id": getattr(report, "replay_run_id"),
        "profile_id": getattr(report, "profile_id"),
        "eval_spec_id": getattr(report, "eval_spec_id"),
        "output_run_id": completion.output_run_id,
        "status": completion.status,
        "result": completion.result,
        "eval_run": {
            "eval_run_id": eval_run.eval_run_id,
            "status": eval_run.status,
            "promoted_trust_level": eval_run.promoted_trust_level,
            "result": eval_run.result,
        }
        if eval_run is not None
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
    eval_run = getattr(report, "eval_run")
    return {
        "profile_id": getattr(report, "profile_id"),
        "proposal_id": getattr(report, "proposal_id"),
        "eval_spec_id": getattr(report, "eval_spec_id"),
        "request_path": str(getattr(report, "request_path")),
        "result_path": str(getattr(report, "result_path")),
        "raw_output_path": str(getattr(report, "raw_output_path")),
        "judgment": getattr(report, "judgment"),
        "eval_run": {
            "eval_run_id": eval_run.eval_run_id,
            "profile_id": eval_run.profile_id,
            "proposal_id": eval_run.proposal_id,
            "eval_spec_id": eval_run.eval_spec_id,
            "replay_run_id": eval_run.replay_run_id,
            "status": eval_run.status,
            "result": eval_run.result,
            "promoted_trust_level": eval_run.promoted_trust_level,
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
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kyoko</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #000000;
      --surface: #0a0a0a;
      --elevated: #111213;
      --text: #c8d5dc;
      --muted: #7d8a90;
      --faint: #5a6a72;
      --strong: #f2f5f7;
      --border: rgba(255,255,255,0.07);
      --border-light: rgba(255,255,255,0.12);
      --accent: #5b8def;
      --accent-soft: rgba(91,141,239,0.12);
      --context: #4fcae3;
      --harness: #f0ad4e;
      --danger: #eb5757;
      --ok: #60e36d;
      --purple: #a57cf5;
      --selected: rgba(91,141,239,0.10);
      --selected-border: rgba(91,141,239,0.30);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    ::selection { background: var(--accent-soft); }

    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-thumb {
      background: rgba(255,255,255,0.10);
      border: 2px solid transparent;
      background-clip: padding-box;
      border-radius: 999px;
    }
    ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.18); background-clip: padding-box; }
    ::-webkit-scrollbar-track { background: transparent; }

    header {
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(10,10,10,0.82);
      backdrop-filter: saturate(140%) blur(10px);
      -webkit-backdrop-filter: saturate(140%) blur(10px);
      border-bottom: 1px solid var(--border);
      padding: 14px 24px;
    }

    .topbar {
      align-items: center;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin: 0 auto;
      max-width: 1180px;
    }

    h1, h2, p {
      margin: 0;
    }

    h1 {
      align-items: center;
      color: var(--strong);
      display: flex;
      font-size: 18px;
      font-weight: 600;
      gap: 9px;
      letter-spacing: 0.02em;
    }

    h1::before {
      content: "";
      width: 11px;
      height: 11px;
      border-radius: 50%;
      background: radial-gradient(circle at 32% 30%, #9bbcff 0%, var(--accent) 55%, #2f5fc0 100%);
      box-shadow: 0 0 10px rgba(91,141,239,0.6);
    }

    h2 {
      color: var(--strong);
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.10em;
      text-transform: uppercase;
    }

    .subtitle {
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
    }

    button {
      appearance: none;
      background: var(--accent);
      border: 1px solid transparent;
      border-radius: 7px;
      color: #06122b;
      cursor: pointer;
      font: inherit;
      font-size: 13px;
      font-weight: 600;
      min-height: 34px;
      padding: 6px 13px;
      transition: background 140ms ease, border-color 140ms ease, color 140ms ease, transform 80ms ease;
    }

    button:hover { background: #6e9bf2; }
    button:active { transform: translateY(1px); }

    button.secondary {
      background: rgba(255,255,255,0.04);
      border-color: var(--border-light);
      color: var(--text);
      font-weight: 500;
    }

    button.secondary:hover {
      background: rgba(255,255,255,0.08);
      border-color: rgba(255,255,255,0.18);
      color: var(--strong);
    }

    button:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
    button:disabled:hover { background: var(--accent); transform: none; }

    label {
      color: var(--muted);
      display: grid;
      font-size: 12px;
      gap: 4px;
    }

    input, select, textarea {
      appearance: none;
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--border);
      border-radius: 7px;
      color: var(--strong);
      font: inherit;
      min-height: 34px;
      padding: 6px 10px;
      width: 100%;
      transition: border-color 120ms ease, background 120ms ease, box-shadow 120ms ease;
    }

    input::placeholder, textarea::placeholder { color: var(--faint); }

    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--selected-border);
      background: rgba(255,255,255,0.05);
      box-shadow: 0 0 0 3px var(--accent-soft);
    }

    select option { background: var(--elevated); color: var(--strong); }

    textarea {
      min-height: 120px;
      resize: vertical;
    }

    .controls {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .checkbox-line {
      align-items: center;
      display: flex;
      gap: 8px;
      min-height: 34px;
    }

    .checkbox-line input[type="checkbox"] {
      appearance: auto;
      margin: 0;
      min-height: 16px;
      padding: 0;
      width: 16px;
    }

    .action-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 12px;
    }

    .top-actions {
      align-items: end;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
    }

    .actor-selector {
      min-width: 220px;
    }

    main {
      margin: 0 auto;
      max-width: 1180px;
      padding: 20px 24px 32px;
    }

    .status {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(110px, 1fr));
      margin-bottom: 20px;
    }

    .metric, .item {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
    }

    .metric {
      padding: 13px 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0.025), rgba(255,255,255,0));
    }

    .metric strong {
      color: var(--strong);
      display: block;
      font-size: 23px;
      font-variant-numeric: tabular-nums;
      letter-spacing: -0.01em;
      line-height: 1.1;
      max-width: 100%;
      overflow-wrap: anywhere;
    }

    .metric span {
      color: var(--muted);
      display: block;
      font-size: 11px;
      letter-spacing: 0.04em;
      margin-top: 4px;
      max-width: 100%;
      overflow-wrap: anywhere;
      text-transform: uppercase;
      word-break: break-word;
    }

    .layout {
      display: grid;
      gap: 20px;
      grid-template-columns: minmax(0, 1.1fr) minmax(300px, 0.9fr);
    }

    section {
      min-width: 0;
    }

    .section-head {
      align-items: center;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      margin-bottom: 12px;
      padding-bottom: 9px;
    }

    .list {
      display: grid;
      gap: 10px;
    }

    .item {
      padding: 13px 14px;
      transition: border-color 140ms ease, background 140ms ease;
    }

    .list > .item:hover {
      border-color: var(--border-light);
      background: rgba(255,255,255,0.018);
    }

    .item-head {
      align-items: flex-start;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }

    .item-title {
      color: var(--strong);
      font-size: 14px;
      font-weight: 600;
      margin-bottom: 4px;
    }

    .adapter-title {
      margin-top: 12px;
    }

    .item-summary {
      color: var(--muted);
      font-size: 13px;
    }

    .detail {
      border-top: 1px solid var(--border);
      display: grid;
      gap: 8px;
      margin-top: 12px;
      padding-top: 12px;
    }

    .detail-grid {
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .detail-cell {
      background: rgba(255,255,255,0.025);
      border: 1px solid var(--border);
      border-radius: 8px;
      min-width: 0;
      padding: 9px 10px;
    }

    .detail-cell strong {
      color: var(--strong);
      display: block;
      font-size: 13px;
    }

    .detail-cell span {
      color: var(--muted);
      display: block;
      font-size: 11px;
      overflow-wrap: anywhere;
    }

    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 10px;
    }

    .badge {
      background: rgba(255,255,255,0.03);
      border: 1px solid var(--border-light);
      border-radius: 999px;
      color: var(--muted);
      font-size: 11px;
      letter-spacing: 0.02em;
      padding: 2px 9px;
      white-space: nowrap;
    }

    .badge.context {
      background: rgba(79,202,227,0.10);
      border-color: rgba(79,202,227,0.35);
      color: var(--context);
    }

    .badge.harness {
      background: rgba(240,173,78,0.10);
      border-color: rgba(240,173,78,0.35);
      color: var(--harness);
    }

    .badge.applied {
      background: rgba(96,227,109,0.10);
      border-color: rgba(96,227,109,0.35);
      color: var(--ok);
    }

    .main-column, .side {
      display: grid;
      gap: 20px;
    }

    pre {
      background: #060606;
      border: 1px solid var(--border);
      border-radius: 8px;
      color: #d7e0e6;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      font-size: 12px;
      margin: 0;
      max-height: 360px;
      overflow: auto;
      padding: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .empty, .error {
      border: 1px dashed var(--border-light);
      border-radius: 8px;
      color: var(--muted);
      font-size: 13px;
      padding: 14px;
    }

    .error {
      background: rgba(235,87,87,0.06);
      border-color: rgba(235,87,87,0.35);
      border-style: solid;
      color: #f4a3a3;
    }

    .trace-panel {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      margin-top: 12px;
      overflow: hidden;
    }

    .trace-head {
      align-items: center;
      background: rgba(255,255,255,0.015);
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 12px;
      justify-content: space-between;
      padding: 9px 13px;
    }

    .trace-head h3 {
      color: var(--muted);
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.12em;
      margin: 0;
      text-transform: uppercase;
    }

    .trace-legend {
      color: var(--faint);
      display: flex;
      flex-wrap: wrap;
      font-size: 10px;
      gap: 11px;
    }

    .trace-legend i {
      border-radius: 2px;
      display: inline-block;
      height: 8px;
      margin-right: 4px;
      vertical-align: middle;
      width: 8px;
    }

    .trace-empty {
      color: var(--muted);
      font-size: 13px;
      padding: 16px 13px;
    }

    .span-tree {
      display: flex;
      flex-direction: column;
      font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
      max-height: 420px;
      overflow: auto;
    }

    .span-row {
      align-items: center;
      border-top: 1px solid rgba(255,255,255,0.035);
      display: flex;
      gap: 9px;
      padding: 4px 13px;
      transition: background 120ms ease;
    }

    .span-row:first-child { border-top: none; }
    .span-row:hover { background: rgba(255,255,255,0.03); }

    .span-pill {
      border-radius: 4px;
      flex-shrink: 0;
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.05em;
      min-width: 44px;
      padding: 2px 5px;
      text-align: center;
    }

    .span-name {
      color: var(--text);
      flex: 0 0 36%;
      font-size: 12px;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .span-row.err .span-name { color: #f4a3a3; }

    .span-track {
      background: rgba(255,255,255,0.035);
      border-radius: 3px;
      flex: 1;
      height: 14px;
      min-width: 40px;
      position: relative;
    }

    .span-bar {
      border-radius: 3px;
      height: 10px;
      min-width: 2px;
      position: absolute;
      top: 2px;
    }

    .span-dur {
      color: var(--faint);
      flex-shrink: 0;
      font-size: 10px;
      font-variant-numeric: tabular-nums;
      text-align: right;
      width: 56px;
    }

    @media (max-width: 900px) {
      .span-name { flex-basis: 44%; }
    }

    @media (max-width: 900px) {
      .status {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .layout {
        grid-template-columns: 1fr;
      }

      .detail-grid {
        grid-template-columns: 1fr;
      }

      .topbar {
        align-items: flex-start;
        flex-direction: column;
      }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>Kyoko</h1>
        <p class="subtitle">Local agent optimization loop</p>
      </div>
      <div class="top-actions">
        <label class="actor-selector">
          Lock Actor
          <input id="dashboard-actor-identity-id" list="dashboard-actor-identities" placeholder="optional agent_identity_id">
          <datalist id="dashboard-actor-identities"></datalist>
        </label>
        <label class="actor-selector">
          Lock Reason
          <input id="dashboard-lock-reason" placeholder="optional reason">
        </label>
        <button id="demo" type="button">Run demo</button>
        <button id="refresh" class="secondary" type="button">Refresh</button>
      </div>
    </div>
  </header>
  <main>
    <div id="error"></div>
    <div id="status" class="status"></div>
    <div class="layout">
      <div class="main-column">
        <section>
          <div class="section-head">
            <h2>Runs</h2>
            <span id="run-count" class="subtitle"></span>
          </div>
          <div id="runs" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Learning Proposals</h2>
            <span id="proposal-count" class="subtitle"></span>
          </div>
          <div id="proposals" class="list"></div>
        </section>
      </div>
      <div class="side">
        <section>
          <div class="section-head">
            <h2>Autonomy Policy</h2>
            <span id="policy-status" class="subtitle"></span>
          </div>
          <div class="item">
            <div class="controls">
              <label>
                Context
                <select id="policy-context-mode">
                  <option value="off">off</option>
                  <option value="propose">propose</option>
                  <option value="autonomous">autonomous</option>
                </select>
              </label>
              <label>
                Harness
                <select id="policy-harness-mode">
                  <option value="off">off</option>
                  <option value="propose">propose</option>
                  <option value="autonomous">autonomous</option>
                </select>
              </label>
              <label>
                Repo Patch
                <select id="policy-repo-patch">
                  <option value="false">off</option>
                  <option value="true">on</option>
                </select>
              </label>
              <label>
                Dirty Worktree
                <select id="policy-dirty-worktree">
                  <option value="block">block</option>
                  <option value="allow_touched_only">allow touched only</option>
                  <option value="allow">allow</option>
                </select>
              </label>
              <label>
                Harness Root
                <input id="harness-workspace-root" placeholder="optional path; profile root fallback">
              </label>
              <label>
                Replay Adapter
                <select id="replay-adapter-select">
                  <option value="">No enabled adapter</option>
                </select>
              </label>
              <label>
                Operator Adapter
                <select id="operator-adapter-select">
                  <option value="">Mock operator</option>
                </select>
              </label>
            </div>
            <div class="action-row">
              <button id="profile-next" type="button">Run next</button>
              <button id="run-autonomy" type="button">Run autonomy</button>
            </div>
            <div id="policy-action-detail" class="detail" hidden></div>
          </div>
        </section>
        <section>
          <div class="section-head">
            <h2>Autonomy History</h2>
            <span id="autonomy-event-count" class="subtitle"></span>
          </div>
          <div class="controls compact-controls">
            <label>
              Event
              <select id="autonomy-kind-filter">
                <option value="">all</option>
                <option value="autonomy_decision">decisions</option>
                <option value="autonomy_gated">gated</option>
                <option value="autonomy_applied">context applied</option>
                <option value="autonomy_harness_applied">harness applied</option>
                <option value="autonomy_harness_prepared">harness prepared</option>
                <option value="autonomy_blocked">blocked</option>
                <option value="autonomy_apply_failed">apply failed</option>
                <option value="autonomy_regression_failed">regression failed</option>
                <option value="autonomy_regression_rolled_back">rolled back</option>
                <option value="autonomy_regression_rollback_failed">rollback failed</option>
              </select>
            </label>
            <label>
              Entity Type
              <select id="autonomy-entity-type-filter">
                <option value="">all</option>
                <option value="learning_proposal">learning proposal</option>
              </select>
            </label>
            <label>
              Entity ID
              <input id="autonomy-entity-id-filter" placeholder="optional exact proposal id">
            </label>
          </div>
          <div id="autonomy-events" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Storage</h2>
            <span id="storage-count" class="subtitle"></span>
          </div>
          <div id="storage" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Skillbook Context</h2>
            <span id="skill-count" class="subtitle"></span>
          </div>
          <div id="skills" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Context Delivery Rules</h2>
            <span id="context-rule-count" class="subtitle"></span>
          </div>
          <div id="context-rules" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Operators</h2>
            <span id="operator-count" class="subtitle"></span>
          </div>
          <div id="operators" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Integrations</h2>
            <span id="integration-count" class="subtitle"></span>
          </div>
          <div id="integrations" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Evals And Replay</h2>
            <span id="eval-count" class="subtitle"></span>
          </div>
          <div class="control-grid">
            <label>
              Judge Command
              <input id="judge-command-input" placeholder="python /path/to/provider-judge.py">
            </label>
            <label>
              Judge Output Dir
              <input id="judge-output-dir" placeholder=".kyoko/judge-command">
            </label>
          </div>
          <div id="evals" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Harness Patches</h2>
            <span id="harness-count" class="subtitle"></span>
          </div>
          <div id="harness-patches" class="list"></div>
        </section>
        <section>
          <div class="section-head">
            <h2>Delivered Context</h2>
          </div>
          <pre id="context"></pre>
        </section>
      </div>
    </div>
  </main>
  <script>
    const state = {
      loading: false,
      replayAdapters: [],
      operatorAdapters: [],
      operatorRuns: [],
      integrationFrameworks: { source_frameworks: [], replay_frameworks: [] },
      harnessTargetLocks: [],
      profiles: [],
      latestProposalImproveReport: null,
      latestSourceDiscoveryReport: null,
      latestSourceImportReport: null,
      latestSourceImproveReport: null,
      selectedProfileId: "",
      selectedReplayAdapterId: window.localStorage.getItem("kyoko_replay_adapter_id") || "",
      selectedOperatorAdapterId: window.localStorage.getItem("kyoko_operator_adapter_id") || "",
      harnessWorkspaceRoot: window.localStorage.getItem("kyoko_harness_workspace_root") || "",
      dashboardActorIdentityId: window.localStorage.getItem("kyoko_actor_agent_identity_id") || "",
      dashboardLockReason: window.localStorage.getItem("kyoko_lock_reason") || "",
      autonomyKindFilter: "",
      autonomyEntityTypeFilter: "",
      autonomyEntityIdFilter: ""
    };

    const statusEl = document.querySelector("#status");
    const runsEl = document.querySelector("#runs");
    const proposalsEl = document.querySelector("#proposals");
    const skillsEl = document.querySelector("#skills");
    const contextRulesEl = document.querySelector("#context-rules");
    const storageEl = document.querySelector("#storage");
    const operatorsEl = document.querySelector("#operators");
    const integrationsEl = document.querySelector("#integrations");
    const evalsEl = document.querySelector("#evals");
    const harnessPatchesEl = document.querySelector("#harness-patches");
    const autonomyEventsEl = document.querySelector("#autonomy-events");
    const contextEl = document.querySelector("#context");
    const errorEl = document.querySelector("#error");
    const runCountEl = document.querySelector("#run-count");
    const proposalCountEl = document.querySelector("#proposal-count");
    const skillCountEl = document.querySelector("#skill-count");
    const contextRuleCountEl = document.querySelector("#context-rule-count");
    const storageCountEl = document.querySelector("#storage-count");
    const operatorCountEl = document.querySelector("#operator-count");
    const integrationCountEl = document.querySelector("#integration-count");
    const evalCountEl = document.querySelector("#eval-count");
    const harnessCountEl = document.querySelector("#harness-count");
    const autonomyEventCountEl = document.querySelector("#autonomy-event-count");
    const autonomyKindFilterEl = document.querySelector("#autonomy-kind-filter");
    const autonomyEntityTypeFilterEl = document.querySelector("#autonomy-entity-type-filter");
    const autonomyEntityIdFilterEl = document.querySelector("#autonomy-entity-id-filter");
    const policyStatusEl = document.querySelector("#policy-status");
    const policyContextModeEl = document.querySelector("#policy-context-mode");
    const policyHarnessModeEl = document.querySelector("#policy-harness-mode");
    const policyRepoPatchEl = document.querySelector("#policy-repo-patch");
    const policyDirtyWorktreeEl = document.querySelector("#policy-dirty-worktree");
    const policyActionDetailEl = document.querySelector("#policy-action-detail");
    const harnessWorkspaceRootEl = document.querySelector("#harness-workspace-root");
    const replayAdapterSelectEl = document.querySelector("#replay-adapter-select");
    const operatorAdapterSelectEl = document.querySelector("#operator-adapter-select");
    const judgeCommandInputEl = document.querySelector("#judge-command-input");
    const judgeOutputDirEl = document.querySelector("#judge-output-dir");
    const dashboardActorIdentityEl = document.querySelector("#dashboard-actor-identity-id");
    const dashboardActorIdentityOptionsEl = document.querySelector("#dashboard-actor-identities");
    const dashboardLockReasonEl = document.querySelector("#dashboard-lock-reason");
    const refreshButton = document.querySelector("#refresh");
    const demoButton = document.querySelector("#demo");
    const profileNextButton = document.querySelector("#profile-next");
    const runAutonomyButton = document.querySelector("#run-autonomy");
    const tokenFromUrl = new URLSearchParams(window.location.search).get("token");
    if (tokenFromUrl) {
      window.localStorage.setItem("kyoko_auth_token", tokenFromUrl);
      window.history.replaceState({}, document.title, window.location.pathname);
    }
    const authToken = window.localStorage.getItem("kyoko_auth_token") || "";

    dashboardActorIdentityEl.value = state.dashboardActorIdentityId;
    dashboardActorIdentityEl.addEventListener("change", syncDashboardActorIdentity);
    dashboardLockReasonEl.value = state.dashboardLockReason;
    dashboardLockReasonEl.addEventListener("change", syncDashboardLockReason);
    harnessWorkspaceRootEl.value = state.harnessWorkspaceRoot;
    harnessWorkspaceRootEl.addEventListener("change", syncHarnessWorkspaceRoot);
    replayAdapterSelectEl.addEventListener("change", syncSelectedReplayAdapter);
    operatorAdapterSelectEl.addEventListener("change", syncSelectedOperatorAdapter);
    refreshButton.addEventListener("click", loadDashboard);
    demoButton.addEventListener("click", () => runDemo(demoButton));
    profileNextButton.addEventListener("click", () => runProfileNext(profileNextButton));
    runAutonomyButton.addEventListener("click", () => runAutonomy(runAutonomyButton));
    for (const control of [policyContextModeEl, policyHarnessModeEl, policyRepoPatchEl, policyDirtyWorktreeEl]) {
      control.addEventListener("change", savePolicy);
    }
    for (const control of [autonomyKindFilterEl, autonomyEntityTypeFilterEl, autonomyEntityIdFilterEl]) {
      control.addEventListener("change", syncAutonomyFiltersAndReload);
    }
    loadDashboard();

    async function loadDashboard() {
      state.loading = true;
      refreshButton.disabled = true;
      profileNextButton.disabled = true;
      runAutonomyButton.disabled = true;
      errorEl.innerHTML = "";
      try {
        const status = await getJson("/api/status");
        renderDashboardActorIdentityOptions();
        const [
          policy,
          runs,
          proposals,
          dashboardMetrics,
          skills,
          contextRules,
          context,
          evals,
          evalCapabilities,
          replayAdapters,
          operatorAdapters,
          operatorRuns,
          storageReport,
          integrationFrameworks,
          harnessPatches,
          harnessTargetLocks,
          autonomyEvents,
          evidence
        ] = await Promise.all([
          getJson(withSelectedProfile("/api/policy")),
          getJson(withSelectedProfile("/api/runs")),
          getJson(withSelectedProfile("/api/proposals")),
          getJson(withSelectedProfile("/api/dashboard-metrics")),
          getJson(withSelectedProfile("/api/skills")),
          getJson(withSelectedProfile("/api/context-rules")),
          getJson(withSelectedProfile("/api/context")),
          getJson("/api/evals"),
          getJson("/api/eval-capabilities"),
          getJson("/api/replay-adapters"),
          getJson("/api/operator-adapters"),
          getJson("/api/operator-runs"),
          getJson("/api/storage-report"),
          getJson("/api/integration-frameworks"),
          getJson("/api/harness-patches"),
          getJson(withSelectedProfile("/api/harness-target-locks")),
          getJson(withSelectedProfile(autonomyEventsPath())),
          getJson(withSelectedProfile("/api/evidence-summary"))
        ]);
        state.replayAdapters = replayAdapters.replay_adapters || [];
        state.operatorAdapters = operatorAdapters.operator_adapters || [];
        state.operatorRuns = operatorRuns.operator_runs || [];
        state.integrationFrameworks = integrationFrameworks || { source_frameworks: [], replay_frameworks: [] };
        state.harnessTargetLocks = harnessTargetLocks.harness_target_locks || [];
        renderReplayAdapterSelector();
        renderOperatorAdapterSelector();
        renderStatus(status, evidence, dashboardMetrics);
        renderPolicy(policy.policy || null);
        renderRuns(runs.runs || []);
        renderProposals(proposals.proposals || []);
        renderSkills(skills.skills || []);
        renderContextRules(contextRules.context_delivery_rules || []);
        renderStorage(storageReport || null);
        renderOperators(state.operatorAdapters, state.operatorRuns);
        renderIntegrations(state.integrationFrameworks);
        renderEvals(
          evals.eval_specs || [],
          evals.eval_runs || [],
          evals.replay_runs || [],
          state.replayAdapters,
          evalCapabilities || null
        );
        renderHarnessPatches(harnessPatches.patch_transactions || [], state.harnessTargetLocks);
        renderAutonomyEvents(autonomyEvents.autonomy_events || []);
        contextEl.textContent = context.context || "No context has been applied yet.";
      } catch (error) {
        errorEl.innerHTML = "";
        const node = document.createElement("div");
        node.className = "error";
        node.textContent = error.message || String(error);
        errorEl.appendChild(node);
      } finally {
        state.loading = false;
        refreshButton.disabled = false;
        demoButton.disabled = false;
        profileNextButton.disabled = false;
        runAutonomyButton.disabled = false;
      }
    }

    function activeProfile() {
      return (state.profiles || []).find((profile) => profile.id === state.selectedProfileId) || null;
    }

    function activeProfileAgentIdentities() {
      const identities = activeProfile()?.agent_identities || [];
      return identities.filter((identity) => identity && identity.id);
    }

    function renderDashboardActorIdentityOptions() {
      dashboardActorIdentityOptionsEl.innerHTML = "";
      for (const identity of activeProfileAgentIdentities()) {
        const option = document.createElement("option");
        option.value = identity.id || "";
        const parts = [
          identity.name || identity.id,
          identity.kind || "",
          identity.role || ""
        ].filter(Boolean);
        option.label = parts.join(" · ");
        dashboardActorIdentityOptionsEl.appendChild(option);
      }
    }

    function withSelectedProfile(path) {
      // Kyoko runs a single implicit workflow profile; the dashboard never
      // selects between profiles, so requests carry no profile_id.
      return path;
    }

    function selectedProfilePayload(payload = {}) {
      // Single implicit profile: pass the payload through untouched.
      return payload;
    }

    function withHarnessWorkspaceRoot(payload = {}) {
      const workspaceRoot = (harnessWorkspaceRootEl.value || "").trim();
      if (!workspaceRoot) {
        return payload;
      }
      return { ...payload, harness_workspace_root: workspaceRoot };
    }

    function withSelectedReplayAdapter(payload = {}) {
      const adapterId = selectedReplayAdapterId();
      if (!adapterId) {
        return payload;
      }
      return { ...payload, replay_adapter_id: adapterId };
    }

    function withSelectedOperatorAdapter(payload = {}) {
      const adapterId = selectedOperatorAdapterId();
      if (!adapterId) {
        return payload;
      }
      return { ...payload, operator: "adapter", operator_adapter: adapterId };
    }


    function selectedOperatorAdapterId() {
      const adapterId = (operatorAdapterSelectEl.value || "").trim();
      if (adapterId) {
        return adapterId;
      }
      return state.selectedOperatorAdapterId || "";
    }

    function selectedReplayAdapterId() {
      const adapterId = (replayAdapterSelectEl.value || "").trim();
      if (adapterId) {
        return adapterId;
      }
      return state.selectedReplayAdapterId || "";
    }

    function renderReplayAdapterSelector() {
      const adapters = enabledReplayAdapters();
      replayAdapterSelectEl.innerHTML = "";
      if (!adapters.length) {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = "No enabled adapter";
        replayAdapterSelectEl.appendChild(option);
        replayAdapterSelectEl.disabled = true;
        state.selectedReplayAdapterId = "";
        window.localStorage.removeItem("kyoko_replay_adapter_id");
        return;
      }
      replayAdapterSelectEl.disabled = false;
      const adapterIds = new Set(adapters.map((adapter) => adapter.id).filter(Boolean));
      let selected = state.selectedReplayAdapterId;
      if (!selected || !adapterIds.has(selected)) {
        selected = adapters[0].id || "";
      }
      for (const adapter of adapters) {
        const option = document.createElement("option");
        option.value = adapter.id || "";
        option.textContent = `${adapter.name || adapter.id} (${adapter.kind || "adapter"})`;
        replayAdapterSelectEl.appendChild(option);
      }
      replayAdapterSelectEl.value = selected;
      state.selectedReplayAdapterId = selected;
      if (selected) {
        window.localStorage.setItem("kyoko_replay_adapter_id", selected);
      }
    }

    function renderOperatorAdapterSelector() {
      const adapters = enabledOperatorAdapters();
      operatorAdapterSelectEl.innerHTML = "";
      const mockOption = document.createElement("option");
      mockOption.value = "";
      mockOption.textContent = "Mock operator";
      operatorAdapterSelectEl.appendChild(mockOption);
      const adapterIds = new Set(adapters.map((adapter) => adapter.id).filter(Boolean));
      let selected = state.selectedOperatorAdapterId;
      if (!selected || !adapterIds.has(selected)) {
        selected = "";
      }
      for (const adapter of adapters) {
        const option = document.createElement("option");
        option.value = adapter.id || "";
        option.textContent = `${adapter.name || adapter.id} (${adapter.operator_kind || "generic"})`;
        operatorAdapterSelectEl.appendChild(option);
      }
      operatorAdapterSelectEl.disabled = false;
      operatorAdapterSelectEl.value = selected;
      state.selectedOperatorAdapterId = selected;
      if (selected) {
        window.localStorage.setItem("kyoko_operator_adapter_id", selected);
      } else {
        window.localStorage.removeItem("kyoko_operator_adapter_id");
      }
    }

    function syncSelectedOperatorAdapter() {
      state.selectedOperatorAdapterId = (operatorAdapterSelectEl.value || "").trim();
      if (state.selectedOperatorAdapterId) {
        window.localStorage.setItem("kyoko_operator_adapter_id", state.selectedOperatorAdapterId);
      } else {
        window.localStorage.removeItem("kyoko_operator_adapter_id");
      }
    }

    function syncSelectedReplayAdapter() {
      state.selectedReplayAdapterId = (replayAdapterSelectEl.value || "").trim();
      if (state.selectedReplayAdapterId) {
        window.localStorage.setItem("kyoko_replay_adapter_id", state.selectedReplayAdapterId);
      } else {
        window.localStorage.removeItem("kyoko_replay_adapter_id");
      }
    }

    function syncHarnessWorkspaceRoot() {
      state.harnessWorkspaceRoot = (harnessWorkspaceRootEl.value || "").trim();
      harnessWorkspaceRootEl.value = state.harnessWorkspaceRoot;
      if (state.harnessWorkspaceRoot) {
        window.localStorage.setItem("kyoko_harness_workspace_root", state.harnessWorkspaceRoot);
      } else {
        window.localStorage.removeItem("kyoko_harness_workspace_root");
      }
    }

    function syncDashboardActorIdentity() {
      state.dashboardActorIdentityId = (dashboardActorIdentityEl.value || "").trim();
      dashboardActorIdentityEl.value = state.dashboardActorIdentityId;
      if (state.dashboardActorIdentityId) {
        window.localStorage.setItem("kyoko_actor_agent_identity_id", state.dashboardActorIdentityId);
      } else {
        window.localStorage.removeItem("kyoko_actor_agent_identity_id");
      }
    }

    function syncDashboardLockReason() {
      state.dashboardLockReason = (dashboardLockReasonEl.value || "").trim();
      dashboardLockReasonEl.value = state.dashboardLockReason;
      if (state.dashboardLockReason) {
        window.localStorage.setItem("kyoko_lock_reason", state.dashboardLockReason);
      } else {
        window.localStorage.removeItem("kyoko_lock_reason");
      }
    }

    function syncAutonomyFiltersAndReload() {
      state.autonomyKindFilter = autonomyKindFilterEl.value || "";
      state.autonomyEntityTypeFilter = autonomyEntityTypeFilterEl.value || "";
      state.autonomyEntityIdFilter = (autonomyEntityIdFilterEl.value || "").trim();
      autonomyEntityIdFilterEl.value = state.autonomyEntityIdFilter;
      loadDashboard();
    }

    function autonomyEventsPath() {
      const params = new URLSearchParams({ limit: "8" });
      if (state.autonomyKindFilter) {
        params.set("kind", state.autonomyKindFilter);
      }
      if (state.autonomyEntityTypeFilter) {
        params.set("entity_type", state.autonomyEntityTypeFilter);
      }
      if (state.autonomyEntityIdFilter) {
        params.set("entity_id", state.autonomyEntityIdFilter);
      }
      return `/api/autonomy-events?${params.toString()}`;
    }

    function withDashboardLockMetadata(payload = {}) {
      syncDashboardActorIdentity();
      syncDashboardLockReason();
      const metadata = {};
      if (state.dashboardActorIdentityId) {
        metadata.actor_agent_identity_id = state.dashboardActorIdentityId;
      }
      if (state.dashboardLockReason) {
        metadata.reason = state.dashboardLockReason;
      }
      return { ...payload, ...metadata };
    }

    async function getJson(path) {
      const response = await fetch(path, { cache: "no-store", headers: authHeaders() });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || payload.error || response.statusText);
      }
      return payload;
    }

    function renderStatus(status, evidence, dashboardMetrics) {
      const counts = status.counts || {};
      const summary = evidence.summary || {};
      const redaction = evidence.redaction || {};
      const metricCards = dashboardMetrics?.cards || [];
      const metrics = [
        ["Runs", counts.runs || 0],
        ["Spans", counts.spans || 0],
        ["Failed spans", summary.failed_spans || 0],
        ["Redacted fields", redaction.redacted_count || 0],
        ["Proposals", counts.learning_proposals || 0],
        ["Skills", counts.skills || 0],
        ["Eval specs", counts.eval_specs || 0],
        ["Eval spec locks", counts.eval_spec_locks || 0],
        ["Replay runs", counts.replay_runs || 0],
        ["Replay adapters", counts.replay_adapters || 0],
        ["Operator adapters", counts.operator_adapters || 0],
        ["Operator runs", counts.operator_runs || 0],
        ["Harness patches", counts.patch_transactions || 0],
        ["Harness target locks", counts.harness_target_locks || 0]
      ];
      statusEl.innerHTML = "";
      for (const card of metricCards) {
        const node = document.createElement("div");
        node.className = "metric";
        const number = document.createElement("strong");
        number.textContent = card.value ?? "n/a";
        const caption = document.createElement("span");
        const detail = card.detail ? ` · ${card.detail}` : "";
        caption.textContent = `${card.label || card.id || "Metric"}${detail}`;
        node.append(number, caption);
        statusEl.appendChild(node);
      }
      for (const [label, value] of metrics) {
        const node = document.createElement("div");
        node.className = "metric";
        const number = document.createElement("strong");
        number.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        node.append(number, caption);
        statusEl.appendChild(node);
      }
    }

    function renderPolicy(policy) {
      if (!policy) {
        policyStatusEl.textContent = "unavailable";
        return;
      }
      policyStatusEl.textContent = policy.profile_id || "";
      policyContextModeEl.value = policy.context_mode || "propose";
      policyHarnessModeEl.value = policy.harness_mode || "propose";
      policyRepoPatchEl.value = policy.allow_repo_patch ? "true" : "false";
      policyDirtyWorktreeEl.value = policy.dirty_worktree_policy || "block";
    }

    function renderPolicyActionReport(detail, titleText, payload) {
      detail.innerHTML = "";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = `${titleText} result`;
      const cells = policyActionCells(payload);
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = policyActionSummary(payload);
      detail.append(title, grid, summary);
      const rows = policyActionRows(payload);
      if (rows.length) {
        const body = document.createElement("pre");
        body.textContent = rows.join("\\n");
        detail.appendChild(body);
      }
      detail.hidden = false;
    }

    function policyActionCells(payload) {
      if (Array.isArray(payload.decisions)) {
        return [
          ["Profile", payload.profile_id || "unknown"],
          ["Decisions", `${payload.decisions.length}`],
          ["Applied", `${payload.decisions.filter((decision) => decision.action === "applied").length}`],
          ["Gated", `${payload.decisions.filter((decision) => decision.action === "gated").length}`]
        ];
      }
      return [
        ["Profile", payload.profile_id || "unknown"],
        ["Action", payload.action || "unknown"],
        ["Status", payload.status || "unknown"],
        ["Reason", payload.reason || "none"]
      ];
    }

    function policyActionSummary(payload) {
      if (Array.isArray(payload.decisions)) {
        const latest = payload.decisions[payload.decisions.length - 1];
        if (!latest) {
          return "Autonomy ran with no candidate decisions.";
        }
        return `Latest decision: ${latest.proposal_id || "unknown"} ${latest.action || "unknown"} (${latest.reason || "no reason"}).`;
      }
      return `${payload.action || "Action"} ${payload.status || "completed"} for ${payload.profile_id || "profile"}: ${payload.reason || "no reason"}.`;
    }

    function policyActionRows(payload) {
      if (Array.isArray(payload.decisions)) {
        return payload.decisions.map((decision) => {
          const transition = `${decision.state_before || "unknown"} -> ${decision.state_after || "unknown"}`;
          const patches = (decision.patch_transaction_ids || []).length
            ? ` patches=${decision.patch_transaction_ids.join(",")}`
            : "";
          return `${decision.proposal_id || "unknown"}: ${decision.action || "unknown"} (${decision.reason || "no reason"}) ${transition}${patches}`;
        });
      }
      const rows = [];
      if (payload.result) {
        rows.push(JSON.stringify(payload.result, null, 2));
      }
      return rows;
    }

    function renderAutonomyEvents(events) {
      autonomyEventsEl.innerHTML = "";
      const filtered = Boolean(
        state.autonomyKindFilter ||
        state.autonomyEntityTypeFilter ||
        state.autonomyEntityIdFilter
      );
      autonomyEventCountEl.textContent = `${events.length} ${filtered ? "filtered" : "recent"}`;
      if (!events.length) {
        autonomyEventsEl.appendChild(emptyNode(filtered ? "No autonomy events match the filters." : "No autonomy events yet."));
        return;
      }
      for (const event of events) {
        const item = document.createElement("article");
        item.className = "item";
        const metadata = event.metadata || {};
        const action = autonomyEventAction(event);
        const reason = metadata.reason || "unknown";
        const proposalId = event.entity_id || metadata.proposal_id || "unknown";
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = `${autonomyEventLabel(event.kind)}: ${proposalId}`;
        const stateChange = metadata.state_before || metadata.state_after
          ? ` · ${metadata.state_before || "unknown"} -> ${metadata.state_after || "unknown"}`
          : "";
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = `${event.at || "unknown time"} · ${action} (${reason})${stateChange}`;
        const badges = document.createElement("div");
        badges.className = "badges";
        const evalCount = Array.isArray(metadata.eval_run_ids) ? metadata.eval_run_ids.length : 0;
        const patchCount = Array.isArray(metadata.patch_transaction_ids) ? metadata.patch_transaction_ids.length : 0;
        badges.append(
          badge(action, autonomyActionBadgeKind(action)),
          badge(metadata.section || "unknown section", metadata.section || ""),
          badge(event.kind || "unknown", "")
        );
        if (metadata.required_eval_level) {
          badges.appendChild(badge(metadata.required_eval_level, ""));
        }
        if (evalCount) {
          badges.appendChild(badge(`${evalCount} eval run${evalCount === 1 ? "" : "s"}`, ""));
        }
        if (patchCount) {
          badges.appendChild(badge(`${patchCount} patch${patchCount === 1 ? "" : "es"}`, ""));
        }
        item.append(title, summary, badges);
        autonomyEventsEl.appendChild(item);
      }
    }

    function autonomyEventAction(event) {
      const metadata = event.metadata || {};
      if (metadata.action) {
        return metadata.action;
      }
      const kind = event.kind || "";
      if (kind === "autonomy_gated") {
        return "gated";
      }
      if (kind === "autonomy_applied" || kind === "autonomy_harness_applied") {
        return "applied";
      }
      if (kind === "autonomy_harness_prepared") {
        return "prepared";
      }
      if (kind === "autonomy_regression_rolled_back") {
        return "rolled_back";
      }
      if (kind === "autonomy_regression_failed" || kind === "autonomy_regression_rollback_failed") {
        return "failed";
      }
      return kind.replace(/^autonomy_/, "") || "unknown";
    }

    function autonomyActionBadgeKind(action) {
      if (action === "applied" || action === "rolled_back" || action === "prepared") {
        return "applied";
      }
      return "";
    }

    function autonomyEventLabel(kind) {
      const labels = {
        autonomy_decision: "Decision",
        autonomy_gated: "Gate",
        autonomy_applied: "Context apply",
        autonomy_harness_applied: "Harness apply",
        autonomy_harness_prepared: "Harness prepare",
        autonomy_blocked: "Block",
        autonomy_apply_failed: "Apply failure",
        autonomy_regression_failed: "Regression failure",
        autonomy_regression_rolled_back: "Rollback",
        autonomy_regression_rollback_failed: "Rollback failure"
      };
      return labels[kind] || "Autonomy";
    }

    function renderStorage(report) {
      storageEl.innerHTML = "";
      if (!report) {
        storageCountEl.textContent = "unavailable";
        storageEl.appendChild(emptyNode("Storage report unavailable."));
        return;
      }
      storageCountEl.textContent = `${report.registered_blobs || 0} blobs`;
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Payload Blobs";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = `${formatBytes(report.registered_blob_bytes || 0)} registered · ${formatBytes(report.db_size_bytes || 0)} database · ${formatBytes(report.wal_size_bytes || 0)} WAL`;
      const badges = document.createElement("div");
      badges.className = "badges";
      badges.append(
        badge(`${report.missing_blobs?.length || 0} missing`, report.missing_blobs?.length ? "rejected" : ""),
        badge(`${report.orphan_files?.length || 0} orphans`, report.orphan_files?.length ? "gated" : ""),
        badge(`${formatBytes(report.wal_size_bytes || 0)} WAL`, report.wal_size_bytes ? "gated" : "")
      );
      const actions = document.createElement("div");
      actions.className = "action-row";
      const dryRun = document.createElement("button");
      dryRun.type = "button";
      dryRun.className = "secondary";
      dryRun.textContent = "Dry-run prune";
      const apply = document.createElement("button");
      apply.type = "button";
      apply.className = "secondary";
      apply.textContent = "Apply prune";
      const checkpoint = document.createElement("button");
      checkpoint.type = "button";
      checkpoint.className = "secondary";
      checkpoint.textContent = "Checkpoint WAL";
      const loadSmoke = document.createElement("button");
      loadSmoke.type = "button";
      loadSmoke.className = "secondary";
      loadSmoke.textContent = "Load smoke";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      dryRun.addEventListener("click", () => pruneStorage(false, detail, dryRun));
      apply.addEventListener("click", () => pruneStorage(true, detail, apply));
      checkpoint.addEventListener("click", () => checkpointWal(detail, checkpoint));
      loadSmoke.addEventListener("click", () => runLoadSmoke(detail, loadSmoke));
      actions.append(dryRun, apply, checkpoint, loadSmoke);
      item.append(title, summary, badges, actions, detail);
      storageEl.appendChild(item);

      const retentionItem = document.createElement("article");
      retentionItem.className = "item";
      const retentionTitle = document.createElement("div");
      retentionTitle.className = "item-title";
      retentionTitle.textContent = "Relational Retention";
      const retentionSummary = document.createElement("div");
      retentionSummary.className = "item-summary";
      retentionSummary.textContent = "Manually prune trace, replay/eval, and operator rows older than the given number of days. Leave a field blank to skip that surface. Defaults to dry-run.";
      const controls = document.createElement("div");
      controls.className = "controls";
      const traceInput = retentionInput("Trace older-than days");
      const replayInput = retentionInput("Replay/eval older-than days");
      const operatorInput = retentionInput("Operator older-than days");
      controls.append(traceInput.label, replayInput.label, operatorInput.label);
      const retentionActions = document.createElement("div");
      retentionActions.className = "action-row";
      const dataDryRun = document.createElement("button");
      dataDryRun.type = "button";
      dataDryRun.className = "secondary";
      dataDryRun.textContent = "Dry-run data prune";
      const dataApply = document.createElement("button");
      dataApply.type = "button";
      dataApply.className = "secondary";
      dataApply.textContent = "Apply data prune";
      const retentionDetail = document.createElement("div");
      retentionDetail.className = "detail";
      retentionDetail.hidden = true;
      const retentionInputs = {
        trace: traceInput.input,
        replay: replayInput.input,
        operator: operatorInput.input
      };
      dataDryRun.addEventListener(
        "click",
        () => pruneRelationalRetention(false, retentionInputs, retentionDetail, dataDryRun)
      );
      dataApply.addEventListener(
        "click",
        () => pruneRelationalRetention(true, retentionInputs, retentionDetail, dataApply)
      );
      retentionActions.append(dataDryRun, dataApply);
      retentionItem.append(retentionTitle, retentionSummary, controls, retentionActions, retentionDetail);
      storageEl.appendChild(retentionItem);
    }

    function retentionInput(labelText, value) {
      const label = document.createElement("label");
      label.textContent = labelText;
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.placeholder = "skip";
      input.value = value === null || value === undefined ? "" : String(value);
      label.appendChild(input);
      return { label, input };
    }

    function parseRetentionInput(input) {
      const raw = String(input.value || "").trim();
      if (!raw) {
        return null;
      }
      if (!/^\\d+$/.test(raw)) {
        throw new Error("Retention days must be a non-negative integer or blank.");
      }
      return Number.parseInt(raw, 10);
    }

    function formatBytes(value) {
      const bytes = Number(value || 0);
      if (bytes < 1024) {
        return `${bytes} B`;
      }
      if (bytes < 1024 * 1024) {
        return `${(bytes / 1024).toFixed(1)} KB`;
      }
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }

    function renderRuns(runs) {
      runCountEl.textContent = `${runs.length} recent`;
      runsEl.innerHTML = "";
      if (!runs.length) {
        runsEl.appendChild(emptyNode("No runs ingested yet."));
        return;
      }

      for (const run of runs) {
        const item = document.createElement("article");
        item.className = "item";
        const head = document.createElement("div");
        head.className = "item-head";
        const body = document.createElement("div");
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = run.summary || run.id;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = `${run.agent_name || "unknown agent"} · ${run.started_at || "unknown time"}`;
        body.append(title, summary);
        head.appendChild(body);

        const details = document.createElement("button");
        details.type = "button";
        details.className = "secondary";
        details.textContent = "Details";
        head.appendChild(details);

        const badges = document.createElement("div");
        badges.className = "badges";
        badges.append(
          badge(run.status || "unknown", run.status === "succeeded" ? "applied" : ""),
          badge(`${run.span_count || 0} spans`, ""),
          badge(`${run.failed_span_count || 0} failed`, run.failed_span_count ? "harness" : ""),
          badge(`${run.handoff_count || 0} handoffs`, "")
        );

        const detail = document.createElement("div");
        detail.className = "detail";
        detail.hidden = true;
        details.addEventListener("click", () => showRunDetail(run.id, detail, details));

        item.append(head, badges, detail);
        runsEl.appendChild(item);
      }
    }

    function renderProposals(proposals) {
      proposalCountEl.textContent = `${proposals.length} total`;
      proposalsEl.innerHTML = "";
      if (!proposals.length) {
        proposalsEl.appendChild(emptyNode("No learning proposals yet."));
        return;
      }

      for (const proposal of proposals) {
        const item = document.createElement("article");
        item.className = "item";
        const head = document.createElement("div");
        head.className = "item-head";
        const body = document.createElement("div");
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = proposal.title || proposal.id;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = proposal.summary || "";
        body.append(title, summary);
        head.appendChild(body);

        if (canApply(proposal)) {
          const apply = document.createElement("button");
          apply.type = "button";
          apply.textContent = "Apply";
          apply.addEventListener("click", () => applyProposal(proposal.id, apply));
          head.appendChild(apply);
        }

        if (canPrepareHarness(proposal)) {
          const prepare = document.createElement("button");
          prepare.type = "button";
          prepare.textContent = "Prepare harness";
          prepare.addEventListener("click", () => prepareHarness(proposal.id, prepare));
          head.appendChild(prepare);
        }

        if (["pending", "applied", "rolled_back"].includes(proposal.state)) {
          const generate = document.createElement("button");
          generate.type = "button";
          generate.className = "secondary";
          generate.textContent = "Generate evals";
          generate.addEventListener("click", () => generateEvals(proposal.id, generate));
          head.appendChild(generate);
        }

        if (canImprove(proposal)) {
          const improve = document.createElement("button");
          improve.type = "button";
          improve.textContent = "Improve";
          improve.addEventListener("click", () => improveProposal(proposal.id, improve));
          head.appendChild(improve);
        }

        const details = document.createElement("button");
        details.type = "button";
        details.className = "secondary";
        details.textContent = "Details";
        head.appendChild(details);

        const badges = document.createElement("div");
        badges.className = "badges";
        badges.append(
          badge(proposal.section_label || proposal.section || "unknown", proposal.section || "unknown"),
          badge(proposal.state || "unknown", proposal.state || "unknown"),
          badge(`kyoko ${proposal.kyoko_confidence ?? "n/a"}`, ""),
          badge(`operator ${proposal.operator_confidence ?? proposal.confidence ?? "n/a"}`, "")
        );

        const detail = document.createElement("div");
        detail.className = "detail";
        detail.hidden = true;
        details.addEventListener("click", () => showProposalDetail(proposal.id, detail, details));
        if (state.latestProposalImproveReport?.proposal_id === proposal.id) {
          renderImproveReport(detail, state.latestProposalImproveReport);
          detail.hidden = false;
          details.textContent = "Hide";
        }

        item.append(head, badges, detail);
        proposalsEl.appendChild(item);
      }
    }

    function renderEvals(evalSpecs, evalRuns, replayRuns, replayAdapters, evalCapabilities) {
      const enabledAdapters = replayAdapters.filter(adapter => adapter.enabled);
      const managedAdapters = enabledAdapters.filter(adapter => adapter.kind === "managed_http_server");
      evalCountEl.textContent = `${evalSpecs.length} specs, ${evalRuns.length} runs, ${enabledAdapters.length} adapters`;
      evalsEl.innerHTML = "";
      if (evalCapabilities) {
        appendEvalCapabilities(evalCapabilities);
      }
      if (managedAdapters.length) {
        appendReplayServerControls(managedAdapters);
      }
      if (!evalSpecs.length) {
        evalsEl.appendChild(emptyNode("No eval specs yet."));
        return;
      }

      const latestRunBySpec = latestBy(evalRuns, "eval_spec_id");
      const latestReplayBySpec = latestBy(replayRuns, "eval_spec_id");
      for (const evalSpec of evalSpecs) {
        const item = document.createElement("article");
        item.className = "item";
        const head = document.createElement("div");
        head.className = "item-head";
        const body = document.createElement("div");
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = evalSpec.name || evalSpec.id;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        const latestRun = latestRunBySpec[evalSpec.id];
        const latestReplay = latestReplayBySpec[evalSpec.id];
        summary.textContent = latestRun
          ? `latest eval ${latestRun.status}`
          : "not run yet";
        body.append(title, summary);
        head.appendChild(body);

        const replay = document.createElement("button");
        replay.type = "button";
        replay.className = "secondary";
        replay.textContent = "Replay";
        replay.addEventListener("click", () => createReplay(evalSpec.id, replay));
        head.appendChild(replay);

        if (enabledAdapters.length) {
          const adapter = document.createElement("button");
          adapter.type = "button";
          adapter.className = "secondary";
          adapter.textContent = "Run adapter";
          adapter.addEventListener(
            "click",
            () => runReplayAdapter(enabledAdapters[0].id, evalSpec.id, adapter)
          );
          head.appendChild(adapter);
        }

        const run = document.createElement("button");
        run.type = "button";
        run.textContent = "Run";
        run.addEventListener("click", () => runEval(evalSpec.id, latestReplay?.id || null, run));
        head.appendChild(run);

        if (evalSpec.eval_type === "judge") {
          const judge = document.createElement("button");
          judge.type = "button";
          judge.className = "secondary";
          judge.textContent = "Run judge";
          judge.addEventListener("click", () => runJudgeCommand(evalSpec.id, latestReplay?.id || null, judge));
          head.appendChild(judge);
        }

        const lockButton = document.createElement("button");
        lockButton.type = "button";
        lockButton.className = "secondary";
        lockButton.textContent = evalSpec.human_locked ? "Unlock" : "Lock";
        lockButton.addEventListener("click", () => setEvalSpecLock(evalSpec.id, !evalSpec.human_locked, lockButton));
        head.appendChild(lockButton);

        if (evalSpec.trust_level !== "L3_human_approved") {
          const approve = document.createElement("button");
          approve.type = "button";
          approve.className = "secondary";
          approve.textContent = "Approve L3";
          approve.addEventListener("click", () => approveEvalSpec(evalSpec.id, approve));
          head.appendChild(approve);
        }

        const details = document.createElement("button");
        details.type = "button";
        details.className = "secondary";
        details.textContent = "Details";
        head.appendChild(details);

        const badges = document.createElement("div");
        badges.className = "badges";
        badges.append(
          badge(evalSpec.eval_type || "unknown", ""),
          badge(evalSpec.trust_level || "unknown", ""),
          badge(evalSpec.side_effect_mode || "unknown", ""),
          badge(evalSpec.human_locked ? "human locked" : "unlocked", evalSpec.human_locked ? "gated" : ""),
          badge(latestRun ? latestRun.status : "not_run", latestRun?.status === "passed" ? "applied" : "")
        );

        const detail = document.createElement("div");
        detail.className = "detail";
        detail.hidden = true;
        details.addEventListener("click", () => showEvalDetail(evalSpec.id, detail, details));

        item.append(head, badges, detail);
        evalsEl.appendChild(item);
      }
    }

    function appendEvalCapabilities(capabilities) {
      const panel = document.createElement("article");
      panel.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Eval Capabilities";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      const gateable = capabilities.gateable_eval_types || [];
      const safeReplay = capabilities.replay?.safe_side_effect_modes || [];
      summary.textContent = `Gateable: ${gateable.join(", ") || "none"} · Safe replay: ${safeReplay.join(", ") || "none"}`;
      const badges = document.createElement("div");
      badges.className = "badges";
      for (const evalType of capabilities.eval_types || []) {
        badges.appendChild(badge(evalType.name || "unknown", evalType.gateable ? "applied" : ""));
      }
      const presets = document.createElement("div");
      presets.className = "item-summary";
      const presetNames = (capabilities.assertion_presets || []).map(preset => preset.name).filter(Boolean);
      presets.textContent = `Presets: ${presetNames.join(", ") || "none"}`;
      panel.append(title, summary, badges, presets);
      evalsEl.appendChild(panel);
    }

    function appendReplayServerControls(managedAdapters) {
      const panel = document.createElement("article");
      panel.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Managed Replay Servers";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Start long-running replay harnesses before running adapter replays.";
      panel.append(title, summary);

      for (const adapter of managedAdapters) {
        const adapterTitle = document.createElement("div");
        adapterTitle.className = "item-title adapter-title";
        adapterTitle.textContent = adapter.name || adapter.id;

        const adapterSummary = document.createElement("div");
        adapterSummary.className = "item-summary";
        adapterSummary.textContent = `${adapter.id} · ${adapter.server_url || "server URL missing"}`;

        const actions = document.createElement("div");
        actions.className = "action-row";
        const start = document.createElement("button");
        start.type = "button";
        start.textContent = "Start server";
        const status = document.createElement("button");
        status.type = "button";
        status.className = "secondary";
        status.textContent = "Status";
        const logs = document.createElement("button");
        logs.type = "button";
        logs.className = "secondary";
        logs.textContent = "Logs";
        const stop = document.createElement("button");
        stop.type = "button";
        stop.className = "secondary";
        stop.textContent = "Stop";

        const detail = document.createElement("div");
        detail.className = "detail";
        detail.hidden = true;

        start.addEventListener("click", () => startReplayServer(adapter.id, detail, start));
        status.addEventListener("click", () => showReplayServerStatus(adapter.id, detail, status));
        logs.addEventListener("click", () => showReplayServerLogs(adapter.id, detail, logs));
        stop.addEventListener("click", () => stopReplayServer(adapter.id, detail, stop));

        actions.append(start, status, logs, stop);
        panel.append(adapterTitle, adapterSummary, actions, detail);
      }

      evalsEl.appendChild(panel);
    }

    function renderSkills(skills) {
      skillCountEl.textContent = `${skills.length} active`;
      skillsEl.innerHTML = "";
      if (!skills.length) {
        skillsEl.appendChild(emptyNode("No skillbook entries yet."));
        return;
      }

      for (const skill of skills) {
        const item = document.createElement("article");
        item.className = "item";
        const head = document.createElement("div");
        head.className = "item-head";
        const body = document.createElement("div");
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = skill.issue || skill.id;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        const skillLockReason = skill.human_lock_reason ? ` · lock reason: ${skill.human_lock_reason}` : "";
        summary.textContent = `${skill.insight || ""}${skillLockReason}`;
        body.append(title, summary);
        head.appendChild(body);
        const lockButton = document.createElement("button");
        lockButton.type = "button";
        lockButton.className = "secondary";
        lockButton.textContent = skill.human_locked ? "Unlock" : "Lock";
        lockButton.addEventListener("click", () => setSkillLock(skill.id, !skill.human_locked, lockButton));
        head.appendChild(lockButton);
        const badges = document.createElement("div");
        badges.className = "badges";
        badges.append(
          badge(skill.section || "unknown", skill.section || "unknown"),
          badge(skill.active ? "active" : "inactive", skill.active ? "applied" : ""),
          badge(skill.human_locked ? "human locked" : "unlocked", skill.human_locked ? "gated" : "")
        );
        for (const keyword of skill.keywords || []) {
          badges.appendChild(badge(keyword, ""));
        }
        item.append(head, badges);
        skillsEl.appendChild(item);
      }
    }

    function renderContextRules(rules) {
      contextRuleCountEl.textContent = `${rules.length} active`;
      contextRulesEl.innerHTML = "";
      if (!rules.length) {
        contextRulesEl.appendChild(emptyNode("No context delivery rules yet."));
        return;
      }

      for (const rule of rules) {
        const item = document.createElement("article");
        item.className = "item";
        const head = document.createElement("div");
        head.className = "item-head";
        const body = document.createElement("div");
        const target = rule.target || {};
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = rule.id;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        const ruleLockReason = rule.human_lock_reason ? ` · lock reason: ${rule.human_lock_reason}` : "";
        summary.textContent = `${target.entity_type || "unknown"}:${target.entity_id || "unknown"}${ruleLockReason}`;
        body.append(title, summary);
        head.appendChild(body);
        const lockButton = document.createElement("button");
        lockButton.type = "button";
        lockButton.className = "secondary";
        lockButton.textContent = rule.human_locked ? "Unlock" : "Lock";
        lockButton.addEventListener("click", () => setContextRuleLock(rule.id, !rule.human_locked, lockButton));
        head.appendChild(lockButton);

        const badges = document.createElement("div");
        badges.className = "badges";
        const ruleBody = rule.rule || {};
        badges.append(
          badge(rule.active ? "active" : "inactive", rule.active ? "applied" : ""),
          badge(rule.human_locked ? "human locked" : "unlocked", rule.human_locked ? "gated" : "")
        );
        const mode = ruleBody.mode || ruleBody.delivery_mode;
        if (mode) {
          badges.appendChild(badge(String(mode), ""));
        }
        if (Array.isArray(ruleBody.include_keywords)) {
          for (const keyword of ruleBody.include_keywords) {
            badges.appendChild(badge(String(keyword), ""));
          }
        }
        item.append(head, badges);
        contextRulesEl.appendChild(item);
      }
    }

    function renderOperators(adapters, runs) {
      const presetOperatorIds = new Set(["codex", "claude", "hermes", "openclaw"]);
      operatorCountEl.textContent = `${adapters.length} registered, ${runs.length} runs`;
      operatorsEl.innerHTML = "";

      const controls = document.createElement("article");
      controls.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Operator Readiness";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Register local Codex, Claude, Hermes, or OpenClaw presets and run proposal-output smoke checks without applying changes.";
      const actions = document.createElement("div");
      actions.className = "action-row";
      const bootstrap = document.createElement("button");
      bootstrap.type = "button";
      bootstrap.textContent = "Bootstrap presets";
      const mockSmoke = document.createElement("button");
      mockSmoke.type = "button";
      mockSmoke.className = "secondary";
      mockSmoke.textContent = "Smoke mock";
      const mockPrepare = document.createElement("button");
      mockPrepare.type = "button";
      mockPrepare.className = "secondary";
      mockPrepare.textContent = "Prepare mock";
      const prepareAllPresets = document.createElement("button");
      prepareAllPresets.type = "button";
      prepareAllPresets.className = "secondary";
      prepareAllPresets.textContent = "Prepare all presets";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      bootstrap.addEventListener("click", () => bootstrapOperators(detail, bootstrap));
      mockSmoke.addEventListener("click", () => smokeOperator("mock", false, detail, mockSmoke));
      mockPrepare.addEventListener("click", () => smokeOperator("mock", false, detail, mockPrepare, true));
      prepareAllPresets.addEventListener("click", () => smokeAllPresetOperators(detail, prepareAllPresets));
      actions.append(bootstrap, prepareAllPresets, mockPrepare, mockSmoke);
      controls.append(title, summary, actions, detail);
      operatorsEl.appendChild(controls);

      operatorsEl.appendChild(operatorRunHistory(runs));

      if (!adapters.length) {
        operatorsEl.appendChild(emptyNode("No operator adapters registered yet."));
        return;
      }

      for (const adapter of adapters) {
        const item = document.createElement("article");
        item.className = "item";
        const head = document.createElement("div");
        head.className = "item-head";
        const body = document.createElement("div");
        const adapterTitle = document.createElement("div");
        adapterTitle.className = "item-title";
        adapterTitle.textContent = adapter.name || adapter.id;
        const adapterSummary = document.createElement("div");
        adapterSummary.className = "item-summary";
        adapterSummary.textContent = `${adapter.id} · ${adapter.operator_kind || "generic"} · ${adapter.enabled ? "enabled" : "disabled"}`;
        body.append(adapterTitle, adapterSummary);
        head.appendChild(body);

        const smoke = document.createElement("button");
        smoke.type = "button";
        smoke.className = "secondary";
        const prepare = document.createElement("button");
        prepare.type = "button";
        prepare.className = "secondary";
        const usesDemoSmoke = presetOperatorIds.has(adapter.id);
        prepare.textContent = "Prepare";
        smoke.textContent = usesDemoSmoke ? "Smoke demo" : "Run on profile";
        const adapterDetail = document.createElement("div");
        adapterDetail.className = "detail";
        adapterDetail.hidden = true;
        prepare.addEventListener(
          "click",
          () => smokeOperator(adapter.id, !usesDemoSmoke, adapterDetail, prepare, true)
        );
        smoke.addEventListener(
          "click",
          () => smokeOperator(adapter.id, !usesDemoSmoke, adapterDetail, smoke)
        );
        const adapterActions = document.createElement("div");
        adapterActions.className = "action-row";
        adapterActions.append(prepare, smoke);
        head.appendChild(adapterActions);

        const badges = document.createElement("div");
        badges.className = "badges";
        badges.append(
          badge(adapter.operator_kind || "generic", ""),
          badge(adapter.enabled ? "enabled" : "disabled", adapter.enabled ? "applied" : ""),
          badge(`${adapter.timeout_seconds || 120}s`, "")
        );
        item.append(head, badges, adapterDetail);
        operatorsEl.appendChild(item);
      }
    }

    function operatorRunHistory(runs) {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Operator Runs";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = runs.length
        ? "Recent operator attempts, including malformed output, retry, timeout, and failure states."
        : "No operator runs recorded yet.";
      item.append(title, summary);
      if (!runs.length) {
        return item;
      }
      for (const run of runs.slice(0, 5)) {
        const row = document.createElement("div");
        row.className = "detail";
        const runTitle = document.createElement("div");
        runTitle.className = "item-summary";
        runTitle.textContent = `${run.id} · ${run.operator_label || "operator"} · ${run.proposal_id || run.error || "no proposal"}`;
        const badges = document.createElement("div");
        badges.className = "badges";
        const attempts = run.attempt_count || run.metadata?.attempts || 0;
        const maxRetries = run.max_retries ?? run.metadata?.max_retries ?? 0;
        badges.append(
          badge(run.status || "unknown", run.status === "succeeded" ? "applied" : run.status === "failed" ? "rejected" : ""),
          badge(operatorRunFailureLabel(run), ""),
          badge(`${attempts} attempt${attempts === 1 ? "" : "s"}`, ""),
          badge(`${maxRetries} retries`, "")
        );
        row.append(runTitle, badges);
        item.appendChild(row);
      }
      return item;
    }

    function operatorRunFailureLabel(run) {
      if (run.status === "running") {
        return "running";
      }
      if (run.status === "succeeded") {
        return run.last_attempt_status || "succeeded";
      }
      if (run.failure_kind === "timeout") {
        return "timed out";
      }
      if (run.failure_kind === "command_not_found") {
        return "command missing";
      }
      if (run.failure_kind === "nonzero_exit") {
        return "nonzero exit";
      }
      if (run.failure_kind === "invalid_output") {
        return "invalid output";
      }
      if (run.failure_kind === "invalid_proposal") {
        return "invalid proposal";
      }
      return run.last_attempt_status || run.failure_kind || "operator error";
    }

    function renderIntegrations(frameworks) {
      const sourceFrameworks = frameworks.source_frameworks || [];
      const replayFrameworks = frameworks.replay_frameworks || [];
      integrationCountEl.textContent = `${sourceFrameworks.length} source, ${replayFrameworks.length} replay`;
      integrationsEl.innerHTML = "";
      integrationsEl.appendChild(doctorReadinessCard());
      integrationsEl.appendChild(
        integrationTemplateCard({
          title: "Source Adapter",
          summary: "Generate a hook-based telemetry adapter that emits Kyoko source events.",
          selectId: "source-framework",
          pathId: "source-output-path",
          defaultPath: "scripts/kyoko_source_adapter.py",
          frameworks: sourceFrameworks,
          buttonText: "Generate source",
          endpoint: "/api/source-adapter-template",
          smokeKind: "source",
          smokeEndpoint: "/api/integration-smoke/source",
          smokeOutputDir: ".kyoko/smoke/source-adapter"
        })
      );
      integrationsEl.appendChild(
        integrationTemplateCard({
          title: "Replay Server",
          summary: "Generate a hook-based HTTP replay server for eval replays.",
          selectId: "replay-framework",
          pathId: "replay-output-path",
          defaultPath: "scripts/kyoko_replay_server.py",
          frameworks: replayFrameworks,
          buttonText: "Generate replay",
          endpoint: "/api/replay-server-template",
          smokeKind: "replay-server",
          smokeEndpoint: "/api/integration-smoke/replay-server",
          smokeOutputDir: ".kyoko/smoke/replay-server"
        })
      );
      integrationsEl.appendChild(sourceDiscoveryCard());
      integrationsEl.appendChild(mcpInstallSmokeCard());
      integrationsEl.appendChild(otlpJsonIngestCard());
      integrationsEl.appendChild(hermesImportCard());
      integrationsEl.appendChild(openClawImportCard());
    }

    function doctorReadinessCard() {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "First-Run Doctor";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Run readiness checks and retain demo, operator, native ACE, integration, improve, MCP, and optional browser artifacts.";
      const controls = document.createElement("div");
      controls.className = "controls";
      const outputLabel = document.createElement("label");
      outputLabel.textContent = "Smoke Output Dir";
      const outputDir = document.createElement("input");
      outputDir.type = "text";
      outputDir.value = ".kyoko/smoke/doctor";
      outputLabel.appendChild(outputDir);
      controls.appendChild(outputLabel);
      const dashboardLabel = document.createElement("label");
      dashboardLabel.className = "checkbox-line";
      const dashboardSmoke = document.createElement("input");
      dashboardSmoke.type = "checkbox";
      dashboardLabel.append(dashboardSmoke, document.createTextNode("Dashboard browser smoke"));
      controls.appendChild(dashboardLabel);
      const screenshotLabel = document.createElement("label");
      screenshotLabel.className = "checkbox-line";
      const screenshot = document.createElement("input");
      screenshot.type = "checkbox";
      screenshot.checked = true;
      screenshotLabel.append(screenshot, document.createTextNode("Screenshots"));
      controls.appendChild(screenshotLabel);
      const installLabel = document.createElement("label");
      installLabel.className = "checkbox-line";
      const installDeps = document.createElement("input");
      installDeps.type = "checkbox";
      installLabel.append(installDeps, document.createTextNode("Install browser deps"));
      controls.appendChild(installLabel);
      const actions = document.createElement("div");
      actions.className = "action-row";
      const run = document.createElement("button");
      run.type = "button";
      run.className = "secondary";
      run.textContent = "Run safe doctor";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      run.addEventListener("click", () => runDoctorSafeSmokes({
        outputDir: outputDir.value,
        dashboardSmoke: dashboardSmoke.checked,
        screenshot: screenshot.checked,
        installDeps: installDeps.checked
      }, detail, run));
      actions.appendChild(run);
      item.append(title, summary, controls, actions, detail);
      return item;
    }

    function mcpInstallSmokeCard() {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "MCP Client Install Smoke";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Run isolated Codex and Claude MCP install smokes without touching your real client config.";
      const controls = document.createElement("div");
      controls.className = "controls";
      const outputLabel = document.createElement("label");
      outputLabel.textContent = "Output Dir";
      const outputDir = document.createElement("input");
      outputDir.type = "text";
      outputDir.value = ".kyoko/smoke/mcp-install";
      outputLabel.appendChild(outputDir);
      controls.appendChild(outputLabel);
      const actions = document.createElement("div");
      actions.className = "action-row";
      const smoke = document.createElement("button");
      smoke.type = "button";
      smoke.className = "secondary";
      smoke.textContent = "Smoke MCP clients";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      smoke.addEventListener("click", () => smokeMcpInstall(outputDir.value, detail, smoke));
      actions.appendChild(smoke);
      item.append(title, summary, controls, actions, detail);
      return item;
    }

    function sourceDiscoveryCard() {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Local Source Discovery";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Find local Hermes Kanban and OpenClaw session stores and generate import commands for the active profile.";
      const actions = document.createElement("div");
      actions.className = "action-row";
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.textContent = "Discover sources";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      refresh.addEventListener("click", () => discoverLocalSources(detail, refresh));
      if (state.latestSourceDiscoveryReport) {
        renderSourceDiscoveryReport(detail, state.latestSourceDiscoveryReport);
        detail.hidden = false;
      }
      actions.appendChild(refresh);
      item.append(title, summary, actions, detail);
      return item;
    }

    function otlpJsonIngestCard() {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "OTLP JSON Ingest";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Post OTLP/HTTP JSON to /v1/traces or paste a JSON export here for local trace ingest.";
      const controls = document.createElement("div");
      controls.className = "controls";

      const profileLabel = document.createElement("label");
      profileLabel.textContent = "Profile ID";
      const profileId = document.createElement("input");
      profileId.type = "text";
      profileId.placeholder = "profile_otlp_news";
      profileLabel.appendChild(profileId);

      const sourceKindLabel = document.createElement("label");
      sourceKindLabel.textContent = "Source kind";
      const sourceKind = document.createElement("input");
      sourceKind.type = "text";
      sourceKind.value = "otlp_http";
      sourceKindLabel.appendChild(sourceKind);

      const jsonLabel = document.createElement("label");
      jsonLabel.textContent = "OTLP JSON";
      jsonLabel.style.gridColumn = "1 / -1";
      const jsonInput = document.createElement("textarea");
      jsonInput.placeholder = '{"resourceSpans":[...]}';
      jsonLabel.appendChild(jsonInput);

      controls.append(profileLabel, sourceKindLabel, jsonLabel);

      const actions = document.createElement("div");
      actions.className = "action-row";
      const ingestButton = document.createElement("button");
      ingestButton.type = "button";
      ingestButton.textContent = "Ingest OTLP";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      ingestButton.addEventListener(
        "click",
        () => ingestOtlpJson(
          jsonInput.value,
          profileId.value,
          sourceKind.value,
          detail,
          ingestButton
        )
      );
      actions.appendChild(ingestButton);
      item.append(title, summary, controls, actions, detail);
      return item;
    }

    function hermesImportCard() {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "Hermes Kanban Import";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Import a Hermes kanban.db into Kyoko tasks, attempts, handoffs, and timeline events.";
      const controls = document.createElement("div");
      controls.className = "controls";

      const dbLabel = document.createElement("label");
      dbLabel.textContent = "Kanban DB";
      const kanbanDb = document.createElement("input");
      kanbanDb.type = "text";
      kanbanDb.value = "~/.hermes/kanban.db";
      dbLabel.appendChild(kanbanDb);

      const boardLabel = document.createElement("label");
      boardLabel.textContent = "Board";
      const board = document.createElement("input");
      board.type = "text";
      board.value = "default";
      boardLabel.appendChild(board);

      const profileLabel = document.createElement("label");
      profileLabel.textContent = "Profile ID";
      const profileId = document.createElement("input");
      profileId.type = "text";
      profileId.placeholder = "profile_hermes_default";
      profileLabel.appendChild(profileId);

      const outputLabel = document.createElement("label");
      outputLabel.textContent = "Normalized JSON";
      const outputPath = document.createElement("input");
      outputPath.type = "text";
      outputPath.placeholder = ".kyoko/imports/hermes-source-events.json";
      outputLabel.appendChild(outputPath);

      controls.append(dbLabel, boardLabel, profileLabel, outputLabel);

      const actions = document.createElement("div");
      actions.className = "action-row";
      const importButton = document.createElement("button");
      importButton.type = "button";
      importButton.textContent = "Import Hermes";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      importButton.addEventListener(
        "click",
        () => importHermesKanban(
          kanbanDb.value,
          board.value,
          profileId.value,
          outputPath.value,
          detail,
          importButton
        )
      );
      actions.appendChild(importButton);
      item.append(title, summary, controls, actions, detail);
      return item;
    }

    function openClawImportCard() {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = "OpenClaw Session Import";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Import OpenClaw sessions.json or JSONL transcripts into Kyoko runs, spans, handoffs, and timeline events.";
      const controls = document.createElement("div");
      controls.className = "controls";

      const pathLabel = document.createElement("label");
      pathLabel.textContent = "Session Path";
      const sessionPath = document.createElement("input");
      sessionPath.type = "text";
      sessionPath.value = "~/.openclaw/agents/main/sessions";
      pathLabel.appendChild(sessionPath);

      const agentLabel = document.createElement("label");
      agentLabel.textContent = "Agent ID";
      const agentId = document.createElement("input");
      agentId.type = "text";
      agentId.placeholder = "main";
      agentLabel.appendChild(agentId);

      const sessionLabel = document.createElement("label");
      sessionLabel.textContent = "Session Key";
      const sessionKey = document.createElement("input");
      sessionKey.type = "text";
      sessionKey.placeholder = "optional";
      sessionLabel.appendChild(sessionKey);

      const profileLabel = document.createElement("label");
      profileLabel.textContent = "Profile ID";
      const profileId = document.createElement("input");
      profileId.type = "text";
      profileId.placeholder = "profile_openclaw_main";
      profileLabel.appendChild(profileId);

      const outputLabel = document.createElement("label");
      outputLabel.textContent = "Normalized JSON";
      const outputPath = document.createElement("input");
      outputPath.type = "text";
      outputPath.placeholder = ".kyoko/imports/openclaw-source-events.json";
      outputLabel.appendChild(outputPath);

      controls.append(pathLabel, agentLabel, sessionLabel, profileLabel, outputLabel);

      const actions = document.createElement("div");
      actions.className = "action-row";
      const importButton = document.createElement("button");
      importButton.type = "button";
      importButton.textContent = "Import OpenClaw";
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      importButton.addEventListener(
        "click",
        () => importOpenClawSessions(
          sessionPath.value,
          agentId.value,
          sessionKey.value,
          profileId.value,
          outputPath.value,
          detail,
          importButton
        )
      );
      actions.appendChild(importButton);
      item.append(title, summary, controls, actions, detail);
      return item;
    }

    function integrationTemplateCard(options) {
      const item = document.createElement("article");
      item.className = "item";
      const title = document.createElement("div");
      title.className = "item-title";
      title.textContent = options.title;
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = options.summary;
      const controls = document.createElement("div");
      controls.className = "controls";

      const frameworkLabel = document.createElement("label");
      frameworkLabel.textContent = "Framework";
      const frameworkSelect = document.createElement("select");
      frameworkSelect.id = options.selectId;
      for (const framework of options.frameworks) {
        const option = document.createElement("option");
        option.value = framework.id;
        option.textContent = framework.name;
        frameworkSelect.appendChild(option);
      }
      frameworkLabel.appendChild(frameworkSelect);

      const pathLabel = document.createElement("label");
      pathLabel.textContent = "Output Path";
      const outputPath = document.createElement("input");
      outputPath.id = options.pathId;
      outputPath.type = "text";
      outputPath.value = suggestedTemplatePath(options.defaultPath, frameworkSelect.value, options.smokeKind);
      pathLabel.appendChild(outputPath);
      controls.append(frameworkLabel, pathLabel);

      const smokeOutputLabel = document.createElement("label");
      smokeOutputLabel.textContent = "Smoke Output";
      const smokeOutputDir = document.createElement("input");
      smokeOutputDir.type = "text";
      smokeOutputDir.value = options.smokeOutputDir || ".kyoko/smoke";
      smokeOutputLabel.appendChild(smokeOutputDir);
      controls.appendChild(smokeOutputLabel);

      let hookInput = null;
      let commandInput = null;
      let serverUrlInput = null;
      if (options.smokeKind === "source") {
        const hookLabel = document.createElement("label");
        hookLabel.textContent = "Hook";
        hookInput = document.createElement("input");
        hookInput.type = "text";
        hookInput.placeholder = suggestedHookPlaceholder(frameworkSelect.value);
        hookLabel.appendChild(hookInput);
        controls.appendChild(hookLabel);
      }
      if (options.smokeKind === "replay-server") {
        const commandLabel = document.createElement("label");
        commandLabel.textContent = "Command";
        commandInput = document.createElement("input");
        commandInput.type = "text";
        commandInput.value = suggestedReplayCommand(outputPath.value, frameworkSelect.value);
        commandLabel.appendChild(commandInput);
        const serverLabel = document.createElement("label");
        serverLabel.textContent = "Server URL";
        serverUrlInput = document.createElement("input");
        serverUrlInput.type = "text";
        serverUrlInput.value = "http://127.0.0.1:61200";
        serverLabel.appendChild(serverUrlInput);
        controls.append(commandLabel, serverLabel);
      }

      const actions = document.createElement("div");
      actions.className = "action-row";
      const generate = document.createElement("button");
      generate.type = "button";
      generate.textContent = options.buttonText;
      const detail = document.createElement("div");
      detail.className = "detail";
      detail.hidden = true;
      let outputPathTouched = false;
      let commandTouched = false;
      outputPath.addEventListener("input", () => {
        outputPathTouched = true;
        if (commandInput && !commandTouched) {
          commandInput.value = suggestedReplayCommand(outputPath.value, frameworkSelect.value);
        }
      });
      if (commandInput) {
        commandInput.addEventListener("input", () => {
          commandTouched = true;
        });
      }
      frameworkSelect.addEventListener("change", () => {
        if (!outputPathTouched) {
          outputPath.value = suggestedTemplatePath(options.defaultPath, frameworkSelect.value, options.smokeKind);
        }
        if (commandInput && !commandTouched) {
          commandInput.value = suggestedReplayCommand(outputPath.value, frameworkSelect.value);
        }
        if (hookInput) {
          hookInput.placeholder = suggestedHookPlaceholder(frameworkSelect.value);
        }
      });
      generate.addEventListener(
        "click",
        () => generateTemplate(options.endpoint, frameworkSelect.value, outputPath.value, detail, generate)
      );
      const smoke = document.createElement("button");
      smoke.type = "button";
      smoke.className = "secondary";
      smoke.textContent = "Smoke";
      if (options.smokeKind === "source") {
        smoke.addEventListener(
          "click",
          () => smokeSourceIntegration(
            outputPath.value,
            hookInput ? hookInput.value : "",
            smokeOutputDir.value,
            detail,
            smoke
          )
        );
      }
      if (options.smokeKind === "replay-server") {
        smoke.addEventListener(
          "click",
          () => smokeReplayIntegration(
            commandInput ? commandInput.value : "",
            serverUrlInput ? serverUrlInput.value : "",
            smokeOutputDir.value,
            detail,
            smoke
          )
        );
      }
      actions.append(generate, smoke);
      item.append(title, summary, controls, actions, detail);
      return item;
    }

    function suggestedTemplatePath(defaultPath, framework, smokeKind) {
      if ((smokeKind === "source" || smokeKind === "replay-server") && framework && framework.endsWith("-typescript")) {
        return defaultPath.replace(/\\.py$/, ".mjs");
      }
      return defaultPath;
    }

    function suggestedReplayCommand(outputPath, framework) {
      if (framework && framework.endsWith("-typescript")) {
        return `node ${outputPath} --port 61200`;
      }
      return `python3 ${outputPath} --port 61200`;
    }

    function suggestedHookPlaceholder(framework) {
      return framework && framework.endsWith("-typescript")
        ? "/absolute/path/to/source_hook.mjs:collect"
        : "/absolute/path/to/source_hook.py:collect";
    }

    function renderHarnessPatches(patchTransactions, targetLocks) {
      const locksByPath = Object.fromEntries(
        targetLocks.map(lock => [lock.target_path, lock])
      );
      harnessCountEl.textContent = `${patchTransactions.length} prepared, ${targetLocks.length} locked targets`;
      harnessPatchesEl.innerHTML = "";
      if (!patchTransactions.length && !targetLocks.length) {
        harnessPatchesEl.appendChild(emptyNode("No harness patches prepared yet."));
        return;
      }

      if (targetLocks.length) {
        const lockPanel = document.createElement("article");
        lockPanel.className = "item";
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = "Harness Target Locks";
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = targetLocks.map(lock => lock.target_path).join(", ");
        const actions = document.createElement("div");
        actions.className = "action-row";
        for (const lock of targetLocks) {
          const button = document.createElement("button");
          button.type = "button";
          button.className = "secondary";
          button.textContent = `Unlock ${lock.target_path}`;
          button.addEventListener(
            "click",
            () => setHarnessTargetLock(lock.target_path, false, button, lock.profile_id || null)
          );
          actions.appendChild(button);
        }
        lockPanel.append(title, summary, actions);
        harnessPatchesEl.appendChild(lockPanel);
      }

      for (const patchTransaction of patchTransactions) {
        const item = document.createElement("article");
        item.className = "item";
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = patchTransaction.id;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = (patchTransaction.target_paths || []).join(", ");
        const badges = document.createElement("div");
        badges.className = "badges";
        badges.append(
          badge(patchTransaction.status || "unknown", patchTransaction.status === "ready" ? "applied" : ""),
          badge(patchTransaction.patch_kind || "unknown", "harness"),
          badge(patchTransaction.side_effect_mode || "unknown", "")
        );
        const actions = document.createElement("div");
        actions.className = "action-row";
        for (const targetPath of patchTransaction.target_paths || []) {
          const lock = locksByPath[targetPath];
          const locked = Boolean(lock && lock.human_locked);
          const button = document.createElement("button");
          button.type = "button";
          button.className = locked ? "" : "secondary";
          button.textContent = `${locked ? "Unlock" : "Lock"} ${targetPath}`;
          button.addEventListener(
            "click",
            () => setHarnessTargetLock(targetPath, !locked, button, lock?.profile_id || patchTransaction.profile_id || null)
          );
          actions.appendChild(button);
        }
        item.append(title, summary, badges, actions);
        harnessPatchesEl.appendChild(item);
      }
    }

    function canApply(proposal) {
      return proposal.section === "context" && proposal.state === "pending";
    }

    function canPrepareHarness(proposal) {
      return proposal.section === "harness" && proposal.state === "pending";
    }

    function canImprove(proposal) {
      return proposal.state === "pending" && enabledReplayAdapters().length > 0;
    }

    function enabledReplayAdapters() {
      return (state.replayAdapters || []).filter(
        adapter => adapter.enabled && (!state.selectedProfileId || adapter.profile_id === state.selectedProfileId)
      );
    }

    function enabledOperatorAdapters() {
      return (state.operatorAdapters || []).filter(
        adapter => adapter.enabled && (!state.selectedProfileId || adapter.profile_id === state.selectedProfileId)
      );
    }

    async function applyProposal(proposalId, button) {
      button.disabled = true;
      try {
        const response = await fetch("/api/apply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ proposal_id: proposalId })
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || payload.error || response.statusText);
        }
        await loadDashboard();
      } catch (error) {
        button.disabled = false;
        errorEl.innerHTML = "";
        const node = document.createElement("div");
        node.className = "error";
        node.textContent = error.message || String(error);
        errorEl.appendChild(node);
      }
    }

    async function generateEvals(proposalId, button) {
      button.disabled = true;
      try {
        await postJson("/api/evals/generate", { proposal_id: proposalId });
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function improveProposal(proposalId, button) {
      button.disabled = true;
      try {
        const adapterId = selectedReplayAdapterId();
        if (!adapterId) {
          throw new Error("No enabled replay adapter is registered.");
        }
        const payload = await postJson("/api/improve", selectedProfilePayload(withHarnessWorkspaceRoot({
          proposal_id: proposalId,
          replay_adapter_id: adapterId,
          run_autonomy: true
        })));
        state.latestProposalImproveReport = payload;
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function prepareHarness(proposalId, button) {
      button.disabled = true;
      try {
        await postJson("/api/harness/prepare", { proposal_id: proposalId });
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function showRunDetail(runId, detail, button) {
      if (!detail.hidden) {
        detail.hidden = true;
        button.textContent = "Details";
        return;
      }
      button.disabled = true;
      try {
        const payload = await getJson(`/api/run-detail?id=${encodeURIComponent(runId)}`);
        renderRunDetail(detail, payload);
        detail.hidden = false;
        button.textContent = "Hide";
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderRunDetail(detail, payload) {
      detail.innerHTML = "";
      const run = payload.run || {};
      const summary = payload.summary || {};
      const agent = payload.agent_identity || {};
      const task = payload.task || {};
      const cells = [
        ["Run", run.id || "unknown"],
        ["Agent", agent.name || "unknown"],
        ["Task", task.id || "none"],
        ["Spans", `${summary.spans || 0}`],
        ["Failed spans", `${summary.failed_spans || 0}`],
        ["Handoffs", `${summary.handoffs || 0}`],
        ["Timeline", `${summary.timeline_events || 0} events`],
        ["Linked proposals", `${summary.related_proposals || 0}`],
        ["Replay runs", `${summary.replay_runs || 0}`]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      detail.append(grid, buildTracePanel(payload));
    }

    const SPAN_KINDS = {
      tool:      { label: "TOOL", color: "#f0ad4e" },
      llm:       { label: "LLM",  color: "#5b8def" },
      agent:     { label: "AGENT", color: "#a57cf5" },
      operator:  { label: "OP",   color: "#a57cf5" },
      retrieval: { label: "RETR", color: "#4fcae3" },
      workflow:  { label: "FLOW", color: "#60e36d" },
      system:    { label: "SPAN", color: "#7d8a90" }
    };

    function spanKindInfo(kind) {
      const key = String(kind || "").toLowerCase();
      if (SPAN_KINDS[key]) return SPAN_KINDS[key];
      if (key.includes("llm") || key.includes("generation")) return SPAN_KINDS.llm;
      if (key.includes("tool")) return SPAN_KINDS.tool;
      if (key.includes("agent")) return SPAN_KINDS.agent;
      return { label: (key ? key.slice(0, 4).toUpperCase() : "SPAN"), color: "#7d8a90" };
    }

    function spanFailed(status) {
      return ["failed", "timed_out", "errored", "error"].includes(String(status || "").toLowerCase());
    }

    function spanMs(value) {
      if (!value) return NaN;
      const t = Date.parse(value);
      return Number.isNaN(t) ? NaN : t;
    }

    function fmtDur(ms) {
      if (!Number.isFinite(ms) || ms < 0) return "–";
      if (ms < 1000) return `${Math.round(ms)}ms`;
      if (ms < 60000) return `${(ms / 1000).toFixed(2)}s`;
      return `${(ms / 60000).toFixed(1)}m`;
    }

    function buildTracePanel(payload) {
      const spans = payload.spans || [];
      const panel = document.createElement("div");
      panel.className = "trace-panel";

      const head = document.createElement("div");
      head.className = "trace-head";
      const title = document.createElement("h3");
      title.textContent = "Trace timeline";
      const legend = document.createElement("div");
      legend.className = "trace-legend";
      for (const key of ["agent", "llm", "tool", "retrieval"]) {
        const info = SPAN_KINDS[key];
        const item = document.createElement("span");
        const swatch = document.createElement("i");
        swatch.style.background = info.color;
        item.append(swatch, document.createTextNode(info.label.toLowerCase()));
        legend.appendChild(item);
      }
      head.append(title, legend);
      panel.appendChild(head);

      if (!spans.length) {
        const empty = document.createElement("div");
        empty.className = "trace-empty";
        empty.textContent = "No spans recorded for this run.";
        panel.appendChild(empty);
        return panel;
      }

      let minT = Infinity;
      let maxT = -Infinity;
      for (const span of spans) {
        const s = spanMs(span.started_at);
        const e = spanMs(span.ended_at);
        if (Number.isFinite(s)) { minT = Math.min(minT, s); maxT = Math.max(maxT, s); }
        if (Number.isFinite(e)) { maxT = Math.max(maxT, e); }
      }
      if (!Number.isFinite(minT)) minT = 0;
      if (!Number.isFinite(maxT)) maxT = minT;
      const totalT = Math.max(maxT - minT, 1);

      const tree = document.createElement("div");
      tree.className = "span-tree";
      const roots = (payload.span_tree && payload.span_tree.length)
        ? payload.span_tree
        : spans.map(s => ({ ...s, children: [] }));
      for (const node of roots) {
        appendSpanRows(tree, node, 0, minT, totalT);
      }
      panel.appendChild(tree);
      return panel;
    }

    function appendSpanRows(container, node, depth, minT, totalT) {
      const info = spanKindInfo(node.kind);
      const failed = spanFailed(node.status);
      const start = spanMs(node.started_at);
      const end = spanMs(node.ended_at);
      const dur = (Number.isFinite(start) && Number.isFinite(end)) ? end - start : NaN;
      const leftPct = Number.isFinite(start) ? ((start - minT) / totalT) * 100 : 0;
      const widthPct = Number.isFinite(dur) ? Math.max((dur / totalT) * 100, 1.2) : 1.2;

      const row = document.createElement("div");
      row.className = "span-row" + (failed ? " err" : "");

      const pill = document.createElement("span");
      pill.className = "span-pill";
      pill.textContent = info.label;
      pill.style.color = failed ? "#f4a3a3" : info.color;
      pill.style.background = (failed ? "rgba(235,87,87," : hexToRgbaPrefix(info.color)) + "0.14)";

      const name = document.createElement("span");
      name.className = "span-name";
      name.style.paddingLeft = `${depth * 15}px`;
      name.textContent = node.name || node.id || "span";
      name.title = `${node.name || node.id || "span"} · ${node.status || "unknown"}`;

      const track = document.createElement("span");
      track.className = "span-track";
      const bar = document.createElement("span");
      bar.className = "span-bar";
      bar.style.left = `${Math.min(Math.max(leftPct, 0), 99)}%`;
      bar.style.width = `${Math.min(widthPct, 100)}%`;
      bar.style.background = failed ? "#eb5757" : info.color;
      track.appendChild(bar);

      const durEl = document.createElement("span");
      durEl.className = "span-dur";
      durEl.textContent = fmtDur(dur);

      row.append(pill, name, track, durEl);
      container.appendChild(row);

      for (const child of (node.children || [])) {
        appendSpanRows(container, child, depth + 1, minT, totalT);
      }
    }

    function hexToRgbaPrefix(hex) {
      const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
      if (!m) return "rgba(125,138,144,";
      return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},`;
    }

    async function showEvalDetail(evalSpecId, detail, button) {
      if (!detail.hidden) {
        detail.hidden = true;
        button.textContent = "Details";
        return;
      }
      button.disabled = true;
      try {
        const payload = await getJson(`/api/eval-detail?id=${encodeURIComponent(evalSpecId)}`);
        renderEvalDetail(detail, payload);
        detail.hidden = false;
        button.textContent = "Hide";
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderEvalDetail(detail, payload) {
      detail.innerHTML = "";
      const evalSpec = payload.eval_spec || {};
      const summary = payload.summary || {};
      const target = payload.target || {};
      const targetRef = target.ref || {};
      const latestReplay = payload.latest_replay_run || {};
      const assertions = summary.latest_assertion_counts || {};
      const cells = [
        ["Eval", evalSpec.id || "unknown"],
        ["Target", `${targetRef.entity_type || "unknown"}:${targetRef.entity_id || "unknown"}`],
        ["Trust", summary.trust_level || "unknown"],
        ["Latest status", summary.latest_status || "not run"],
        ["Comparison", summary.latest_comparison || "n/a"],
        ["Assertions", `${assertions.passed || 0}/${assertions.total || 0} passed`],
        ["Replay runs", `${summary.replay_runs || 0}`],
        ["Latest replay", summary.latest_replay_status || "none"],
        ["Side effects", summary.side_effect_mode || "unknown"],
        ["Replay output", latestReplay.output_ref || "none"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const note = document.createElement("div");
      note.className = "item-summary";
      note.textContent = evalSpec.name || "";
      const assertionList = document.createElement("div");
      assertionList.className = "list";
      const latestAssertions = summary.latest_assertions || [];
      if (latestAssertions.length) {
        for (const assertion of latestAssertions) {
          const row = document.createElement("div");
          row.className = "detail-cell";
          const title = document.createElement("strong");
          title.textContent = `${assertion.index || "?"}. ${assertion.passed ? "pass" : "fail"} ${assertion.type || "assertion"}`;
          const body = document.createElement("span");
          const path = assertion.path
            ? ` · ${assertion.path}: ${formatValue(assertion.actual)} / ${formatValue(assertion.expected)}`
            : "";
          const status = assertion.replay_observed_status || assertion.observed_status || "";
          body.textContent = `${assertion.reason || "unknown"}${status ? ` · status ${status}` : ""}${path}`;
          row.append(title, body);
          assertionList.appendChild(row);
        }
      }
      detail.append(grid, note);
      if (latestAssertions.length) {
        detail.appendChild(assertionList);
      }
    }

    async function showProposalDetail(proposalId, detail, button) {
      if (!detail.hidden) {
        if (state.latestProposalImproveReport?.proposal_id === proposalId) {
          state.latestProposalImproveReport = null;
        }
        detail.hidden = true;
        button.textContent = "Details";
        return;
      }
      button.disabled = true;
      try {
        const payload = await getJson(`/api/proposal-detail?id=${encodeURIComponent(proposalId)}`);
        renderProposalDetail(detail, payload);
        detail.hidden = false;
        button.textContent = "Hide";
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderProposalDetail(detail, payload) {
      detail.innerHTML = "";
      const proposal = payload.proposal || {};
      const confidence = payload.confidence_assessment || {};
      const gate = payload.autonomy_gate || {};
      const target = payload.target || {};
      const targetRef = target.ref || {};
      const evidenceChain = payload.evidence_chain || {};
      const evalGuidance = payload.eval_guidance || {};
      const chainSteps = evidenceChain.steps || [];
      const latestEval = latestBy(payload.eval_runs || [], "proposal_id")[proposal.id] || null;
      const gateableEvalTypes = evalGuidance.gateable_eval_types || [];
      const assertionPresetNames = (evalGuidance.assertion_presets || [])
        .map((preset) => preset.name)
        .filter(Boolean);
      const cells = [
        ["Fix type", proposal.section_label || proposal.section || "unknown"],
        ["Target", `${targetRef.entity_type || "unknown"}:${targetRef.entity_id || "unknown"}`],
        ["Kyoko confidence", `${confidence.kyoko_confidence ?? "n/a"} (${confidence.level || "unknown"})`],
        ["Operator confidence", `${confidence.operator_confidence ?? proposal.confidence ?? "n/a"}`],
        ["Autonomy", `${gate.action || "unknown"} (${gate.reason || "unknown"})`],
        ["Required gate", gate.required_eval_level || "n/a"],
        ["Evidence", `${(payload.evidence || []).length} refs`],
        ["Eval specs", `${(payload.eval_specs || []).length}`],
        ["Gateable evals", gateableEvalTypes.join(", ") || "none"],
        ["Assertion presets", assertionPresetNames.join(", ") || "none"],
        ["Latest eval", latestEval ? latestEval.status : "not run"],
        ["Replay runs", `${(payload.replay_runs || []).length}`],
        ["Harness patches", `${(payload.patch_transactions || []).length}`],
        ["Evidence chain", `${chainSteps.length} steps`],
        ["Gate history", `${(payload.gate_history || []).length} events`],
        ["Timeline", `${(payload.timeline_events || []).length} events`]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const insight = document.createElement("div");
      insight.className = "item-summary";
      insight.textContent = proposal.insight || "";
      const chainSummary = document.createElement("div");
      chainSummary.className = "item-summary";
      chainSummary.textContent = evidenceChain.summary || "";
      const chainList = document.createElement("div");
      chainList.className = "list";
      for (const step of chainSteps) {
        const row = document.createElement("div");
        row.className = "detail-cell";
        const title = document.createElement("strong");
        title.textContent = `${step.title || step.stage || "Step"}: ${step.status || "unknown"}`;
        const body = document.createElement("span");
        body.textContent = step.description || "";
        row.append(title, body);
        chainList.appendChild(row);
      }
      const gateList = document.createElement("div");
      gateList.className = "list";
      const gateHistory = payload.gate_history || [];
      for (const gateEvent of gateHistory.slice(-3)) {
        const row = document.createElement("div");
        row.className = "detail-cell";
        const title = document.createElement("strong");
        title.textContent = `${gateEvent.kind || "autonomy"}: ${gateEvent.action || "unknown"}`;
        const body = document.createElement("span");
        body.textContent = `${gateEvent.reason || "unknown"} · ${gateEvent.at || "unknown time"}`;
        row.append(title, body);
        gateList.appendChild(row);
      }
      detail.append(grid, insight);
      if (evidenceChain.summary) {
        detail.appendChild(chainSummary);
      }
      if (chainSteps.length) {
        detail.appendChild(chainList);
      }
      if (gateHistory.length) {
        detail.appendChild(gateList);
      }
    }

    async function savePolicy() {
      try {
        await postJson("/api/policy", selectedProfilePayload({
          context_mode: policyContextModeEl.value,
          harness_mode: policyHarnessModeEl.value,
          allow_repo_patch: policyRepoPatchEl.value === "true",
          dirty_worktree_policy: policyDirtyWorktreeEl.value
        }));
        await loadDashboard();
      } catch (error) {
        showError(error);
      }
    }

    async function pruneStorage(apply, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/prune", selectedProfilePayload({ apply }));
        detail.innerHTML = "";
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = `${payload.dry_run ? "Dry run" : "Applied"}: ${payload.pruned_blobs?.length || 0} blobs, ${formatBytes(payload.pruned_bytes || 0)}.`;
        const body = document.createElement("pre");
        body.textContent = JSON.stringify(payload, null, 2);
        detail.append(summary, body);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function pruneRelationalRetention(apply, inputs, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/prune-retention", selectedProfilePayload({
          trace_older_than_days: parseRetentionInput(inputs.trace),
          replay_older_than_days: parseRetentionInput(inputs.replay),
          operator_older_than_days: parseRetentionInput(inputs.operator),
          apply
        }));
        detail.innerHTML = "";
        const summary = document.createElement("div");
        summary.className = "item-summary";
        const rows = payload.summary?.pruned_rows || 0;
        const skipped = payload.summary?.skipped_rows || 0;
        summary.textContent = `${payload.dry_run ? "Dry run" : "Applied"}: ${rows} relational rows, ${skipped} skipped.`;
        const body = document.createElement("pre");
        body.textContent = JSON.stringify(payload, null, 2);
        detail.append(summary, body);
        detail.hidden = false;
        if (apply) {
          await loadDashboard();
        }
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function checkpointWal(detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/wal-checkpoint", { mode: "TRUNCATE" });
        detail.innerHTML = "";
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = `Checkpoint ${payload.mode}: WAL ${formatBytes(payload.wal_size_before || 0)} -> ${formatBytes(payload.wal_size_after || 0)}.`;
        const body = document.createElement("pre");
        body.textContent = JSON.stringify(payload, null, 2);
        detail.append(summary, body);
        detail.hidden = false;
        await loadDashboard();
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function runLoadSmoke(detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/load-smoke", {
          runs: 30,
          spans_per_run: 3,
          read_workers: 2,
          read_iterations: 2,
          expired_blobs: 2,
          checkpoint_mode: "PASSIVE"
        });
        detail.innerHTML = "";
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = `Load smoke ${payload.passed ? "passed" : "failed"}: ${payload.total_read_operations || 0} reads, p95 ${Number(payload.latency_ms?.p95 || 0).toFixed(3)} ms, ${payload.errors?.length || 0} errors.`;
        const body = document.createElement("pre");
        body.textContent = JSON.stringify(payload, null, 2);
        detail.append(summary, body);
        detail.hidden = false;
        await loadDashboard();
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function setSkillLock(skillId, locked, button) {
      button.disabled = true;
      try {
        await postJson("/api/skills/lock", withDashboardLockMetadata({ skill_id: skillId, locked }));
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function setContextRuleLock(ruleId, locked, button) {
      button.disabled = true;
      try {
        await postJson("/api/context-rules/lock", withDashboardLockMetadata({ rule_id: ruleId, locked }));
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function setEvalSpecLock(evalSpecId, locked, button) {
      button.disabled = true;
      try {
        await postJson("/api/eval-specs/lock", withDashboardLockMetadata({ eval_spec_id: evalSpecId, locked }));
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function approveEvalSpec(evalSpecId, button) {
      button.disabled = true;
      try {
        await postJson("/api/eval-specs/approve", withDashboardLockMetadata({ eval_spec_id: evalSpecId }));
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function setHarnessTargetLock(targetPath, locked, button, profileId) {
      button.disabled = true;
      try {
        const payload = { target_path: targetPath, locked };
        if (profileId) {
          payload.profile_id = profileId;
        }
        await postJson("/api/harness-targets/lock", withDashboardLockMetadata(payload));
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function createReplay(evalSpecId, button) {
      button.disabled = true;
      try {
        await postJson("/api/replay", { eval_spec_id: evalSpecId, mode: "dry_run" });
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function runEval(evalSpecId, replayRunId, button) {
      button.disabled = true;
      try {
        await postJson("/api/evals/run", {
          eval_spec_id: evalSpecId,
          replay_run_id: replayRunId
        });
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function runJudgeCommand(evalSpecId, replayRunId, button) {
      button.disabled = true;
      try {
        const command = (judgeCommandInputEl.value || "").trim();
        if (!command) {
          throw new Error("Judge command is required.");
        }
        const outputDir = (judgeOutputDirEl.value || "").trim() || ".kyoko/judge-command";
        const payload = {
          eval_spec_id: evalSpecId,
          command,
          output_dir: outputDir
        };
        if (replayRunId) {
          payload.replay_run_id = replayRunId;
        }
        await postJson("/api/judge-command", payload);
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function runReplayAdapter(adapterId, evalSpecId, button) {
      button.disabled = true;
      try {
        await postJson("/api/replay-adapters/run", {
          adapter_id: adapterId,
          eval_spec_id: evalSpecId,
          run_eval: true
        });
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function startReplayServer(adapterId, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/replay-servers/start", { adapter_id: adapterId });
        renderReplayServerProcessReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function showReplayServerStatus(adapterId, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/replay-servers/status", { adapter_id: adapterId });
        renderReplayServerProcessReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function stopReplayServer(adapterId, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/replay-servers/stop", { adapter_id: adapterId });
        renderReplayServerProcessReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function showReplayServerLogs(adapterId, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/replay-servers/logs", {
          adapter_id: adapterId,
          max_bytes: 40000
        });
        renderReplayServerLogs(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderReplayServerProcessReport(detail, payload) {
      detail.innerHTML = "";
      const health = payload.health || {};
      const cells = [
        ["Adapter", payload.adapter_id || "unknown"],
        ["Running", payload.running ? "yes" : "no"],
        ["Healthy", payload.healthy ? "yes" : "no"],
        ["PID", payload.pid == null ? "none" : `${payload.pid}`],
        ["Server", payload.server_url || "unknown"],
        ["Logs", payload.stdout_path || "unknown"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const note = document.createElement("div");
      note.className = "item-summary";
      note.textContent = payload.error
        ? `Error: ${payload.error}`
        : `Health: ${health.ok ? "ok" : "not confirmed"} · state ${payload.state_path || "not written"}`;
      detail.append(grid, note);
    }

    function renderReplayServerLogs(detail, payload) {
      detail.innerHTML = "";
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = `Showing up to ${payload.max_bytes || 0} bytes per stream.`;
      const stdoutLabel = document.createElement("div");
      stdoutLabel.className = "item-title";
      stdoutLabel.textContent = payload.stdout_truncated ? "stdout (tail)" : "stdout";
      const stdout = document.createElement("pre");
      stdout.textContent = payload.stdout || "No stdout captured.";
      const stderrLabel = document.createElement("div");
      stderrLabel.className = "item-title adapter-title";
      stderrLabel.textContent = payload.stderr_truncated ? "stderr (tail)" : "stderr";
      const stderr = document.createElement("pre");
      stderr.textContent = payload.stderr || "No stderr captured.";
      detail.append(summary, stdoutLabel, stdout, stderrLabel, stderr);
    }

    async function bootstrapOperators(detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/operator-adapters/bootstrap", selectedProfilePayload({ target: "all" }));
        renderOperatorBootstrapReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function smokeOperator(operator, useCurrentDb, detail, button, prepareOnly = false) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/operator-smoke", selectedProfilePayload({
          operator,
          use_current_db: useCurrentDb,
          prepare_only: prepareOnly
        }));
        renderOperatorSmokeReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function smokeAllPresetOperators(detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/operator-smoke", selectedProfilePayload({
          all_presets: true,
          prepare_only: true,
          output_dir: ".kyoko/operator-smoke"
        }));
        renderOperatorSmokeReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderOperatorBootstrapReport(detail, payload) {
      detail.innerHTML = "";
      const registered = payload.registered || [];
      const skipped = payload.skipped || [];
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = `${registered.length} registered, ${skipped.length} skipped.`;
      const list = document.createElement("pre");
      list.textContent = JSON.stringify(payload, null, 2);
      detail.append(summary, list);
    }

    function renderOperatorSmokeReport(detail, payload) {
      detail.innerHTML = "";
      if (Array.isArray(payload.targets)) {
        const summaryPayload = payload.summary || {};
        const cells = [
          ["Operators", String(summaryPayload.total || payload.targets.length || 0)],
          ["Prepared", String(summaryPayload.prepared || 0)],
          ["Passed", String(summaryPayload.passed || 0)],
          ["Skipped", String(summaryPayload.skipped || 0)],
          ["Failed", String(summaryPayload.failed || 0)],
          ["Output", payload.output_dir || "unknown"]
        ];
        const grid = document.createElement("div");
        grid.className = "detail-grid";
        for (const [label, value] of cells) {
          const cell = document.createElement("div");
          cell.className = "detail-cell";
          const strong = document.createElement("strong");
          strong.textContent = value;
          const caption = document.createElement("span");
          caption.textContent = label;
          cell.append(strong, caption);
          grid.appendChild(cell);
        }
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = payload.prepare_only
          ? "Prepared operator evidence and prompts for all built-in presets without invoking live operator CLIs."
          : "Ran proposal-output smoke checks across built-in presets; no replay, autonomy, or apply path ran.";
        const list = document.createElement("pre");
        list.textContent = JSON.stringify(payload.targets, null, 2);
        detail.append(grid, summary, list);
        return;
      }
      const cells = [
        ["Operator", payload.operator || "unknown"],
        ["Proposal", payload.proposal_id || "none"],
        ["Live operator", payload.live_operator_invoked === false ? "no" : "yes"],
        ["Profile", payload.profile_id || "unknown"],
        ["Smoke DB", payload.db_path || "unknown"],
        ["Prompt", payload.prompt_path || "unknown"],
        ["Raw output", payload.raw_output_path || "none"],
        ["Command", payload.shell_command || "none"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      if (payload.live_operator_invoked === false) {
        summary.textContent = payload.used_demo_database
          ? "Prepared evidence and prompt against a generated demo database; no live operator ran."
          : "Prepared evidence and prompt against the current database; no live operator ran.";
      } else {
        summary.textContent = payload.used_demo_database
          ? "Validated against a generated demo database; no apply path ran."
          : "Validated against the current database; no apply path ran.";
      }
      detail.append(grid, summary);
    }

    async function generateTemplate(endpoint, framework, outputPath, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson(endpoint, {
          framework,
          output_path: outputPath,
          profile_name: "kyoko-agent",
          force: false
        });
        renderTemplateReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderTemplateReport(detail, payload) {
      detail.innerHTML = "";
      const cells = [
        ["Framework", payload.framework || "unknown"],
        ["Output", payload.output_path || "unknown"],
        ["Profile", payload.profile_name || "unknown"],
        ["Wrote", payload.wrote ? "yes" : "no"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      detail.appendChild(grid);
    }

    async function smokeSourceIntegration(adapterPath, hook, outputDir, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/integration-smoke/source", {
          adapter_path: adapterPath,
          hook,
          output_dir: outputDir,
          profile_name: "kyoko-agent"
        });
        renderIntegrationSmokeReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function smokeReplayIntegration(command, serverUrl, outputDir, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/integration-smoke/replay-server", {
          command,
          server_url: serverUrl,
          output_dir: outputDir,
          startup_timeout_seconds: 10,
          stop_timeout_seconds: 5
        });
        renderIntegrationSmokeReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function smokeMcpInstall(outputDir, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/mcp-install-smoke", {
          output_dir: outputDir,
          scope: "user"
        });
        renderMcpInstallSmokeReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function runDoctorSafeSmokes(options, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/doctor", {
          safe_smokes: true,
          smoke_output_dir: options.outputDir,
          dashboard_smoke: Boolean(options.dashboardSmoke),
          dashboard_smoke_screenshot: Boolean(options.screenshot),
          dashboard_smoke_install_browser_deps: Boolean(options.installDeps)
        });
        renderDoctorReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderDoctorReport(detail, payload) {
      detail.innerHTML = "";
      const summaryPayload = payload.summary || {};
      const readiness = payload.readiness || {};
      const checks = payload.checks || [];
      const cells = [
        ["Overall", payload.ok ? "ok" : "failed"],
        ["Runtime", readinessLabel(readiness.local_runtime_ready)],
        ["Local v0", readinessLabel(readiness.local_v0_ready)],
        ["Safe smokes", readinessLabel(readiness.safe_smokes_complete)],
        ["Passed", String(summaryPayload.passed || 0)],
        ["Warnings", String(summaryPayload.warnings || 0)],
        ["Failed", String(summaryPayload.failed || 0)]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const retained = checks
        .map((check) => check.detail || {})
        .filter((detailPayload) => detailPayload.artifacts_retained && detailPayload.output_dir)
        .map((detailPayload) => detailPayload.output_dir);
      const note = document.createElement("div");
      note.className = "item-summary";
      note.textContent = retained.length
        ? `Artifacts retained: ${retained.join(", ")}`
        : "No retained artifact directories reported.";
      const readinessNote = document.createElement("div");
      readinessNote.className = "item-summary";
      readinessNote.textContent = doctorReadinessSummary(readiness);
      const body = document.createElement("pre");
      body.textContent = JSON.stringify({
        readiness,
        checks: checks.map((check) => ({
          id: check.id,
          status: check.status,
          message: check.message
        })),
        retained_external_evidence: payload.retained_external_evidence || [],
        suggested_commands: payload.suggested_commands || []
      }, null, 2);
      detail.append(grid, readinessNote, note, body);
    }

    function readinessLabel(value) {
      if (value === true) return "ready";
      if (value === false) return "pending";
      return "unknown";
    }

    function doctorReadinessSummary(readiness) {
      const blocking = Array.isArray(readiness.blocking_checks) ? readiness.blocking_checks : [];
      const pendingSafe = Array.isArray(readiness.pending_safe_smoke_checks)
        ? readiness.pending_safe_smoke_checks
        : [];
      const external = Array.isArray(readiness.pending_external_evidence_commands)
        ? readiness.pending_external_evidence_commands
        : [];
      const satisfiedExternal = Array.isArray(readiness.satisfied_external_evidence_commands)
        ? readiness.satisfied_external_evidence_commands
        : [];
      if (blocking.length) {
        return `Blocking checks: ${blocking.join(", ")}`;
      }
      if (pendingSafe.length) {
        return `Pending safe smokes: ${pendingSafe.join(", ")}`;
      }
      if (external.length) {
        return `External evidence follow-ups: ${external.join(", ")}`;
      }
      if (satisfiedExternal.length) {
        return `Retained external evidence: ${satisfiedExternal.join(", ")}`;
      }
      if (readiness.local_v0_ready === true) {
        return "Local v0 readiness is complete.";
      }
      return "Readiness details unavailable.";
    }

    function renderMcpInstallSmokeReport(detail, payload) {
      detail.innerHTML = "";
      const summaryPayload = payload.summary || {};
      const cells = [
        ["Targets", String(summaryPayload.total || 0)],
        ["Passed", String(summaryPayload.passed || 0)],
        ["Skipped", String(summaryPayload.skipped || 0)],
        ["Failed", String(summaryPayload.failed || 0)],
        ["Output", payload.output_dir || "unknown"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "Install smokes run with isolated HOME, CODEX_HOME, and XDG_CONFIG_HOME values.";
      const list = document.createElement("pre");
      list.textContent = JSON.stringify(payload.results || [], null, 2);
      detail.append(grid, summary, list);
    }

    function renderIntegrationSmokeReport(detail, payload) {
      detail.innerHTML = "";
      const status = payload.status || {};
      const counts = status.counts || {};
      const health = payload.health || {};
      const healthResponse = health.response || {};
      const cells = payload.kind === "source_adapter"
        ? [
            ["Smoke", "source adapter"],
            ["Profile", payload.profile_id || "unknown"],
            ["Runs", `${counts.runs || 0}`],
            ["Spans", `${counts.spans || 0}`],
            ["Source events", payload.source_events_path || "unknown"],
            ["stdout", payload.stdout_path || "unknown"],
            ["stderr", payload.stderr_path || "unknown"]
          ]
        : [
            ["Smoke", "replay server"],
            ["Server", payload.server_url || "unknown"],
            ["Healthy", payload.healthy ? "yes" : "no"],
            ["Replay", payload.replay_request ? (payload.replay_ok ? "passed" : "failed") : "not run"],
            ["Stopped", payload.stopped ? "yes" : "no"],
            ["Profile", healthResponse.profile || "unknown"],
            ["stdout", payload.stdout_path || "unknown"],
            ["stderr", payload.stderr_path || "unknown"]
          ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = payload.kind === "source_adapter"
        ? `Ingested ${JSON.stringify(payload.ingested_counts || {})}.`
        : `Health ${health.ok ? "ok" : "not confirmed"}; replay ${payload.replay_request ? (payload.replay_ok ? "passed" : "failed") : "not run"}; logs saved in ${payload.output_dir || "unknown"}.`;
      detail.append(grid, summary);
    }

    async function importHermesKanban(kanbanDbPath, board, profileId, outputPath, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/import-hermes-kanban", {
          kanban_db_path: kanbanDbPath,
          board,
          profile_id: profileId || undefined,
          output_path: outputPath || undefined
        });
        renderHermesImportReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function discoverLocalSources(detail, button) {
      button.disabled = true;
      try {
        const payload = await getJson(withSelectedProfile("/api/source-discovery"));
        state.latestSourceDiscoveryReport = payload;
        renderSourceDiscoveryReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderSourceDiscoveryReport(detail, payload) {
      detail.innerHTML = "";
      const candidates = payload.candidates || [];
      if (!candidates.length) {
        const empty = document.createElement("div");
        empty.className = "item-summary";
        empty.textContent = "No local Hermes or OpenClaw source stores found.";
        detail.appendChild(empty);
        return;
      }
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      const cells = [
        ["Candidates", `${candidates.length}`],
        ["Home", payload.home || "unknown"],
        ["DB", payload.db_path || "unknown"]
      ];
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      detail.appendChild(grid);
      for (const candidate of candidates) {
        const title = document.createElement("div");
        title.className = "item-title";
        title.textContent = `${candidate.label || candidate.id} (${candidate.status || "unknown"})`;
        const summary = document.createElement("div");
        summary.className = "item-summary";
        summary.textContent = candidate.path || "";
        const command = document.createElement("pre");
        command.textContent = candidate.import_command || "";
        const actions = document.createElement("div");
        actions.className = "action-row";
        const importButton = document.createElement("button");
        importButton.type = "button";
        importButton.textContent = "Import";
        importButton.disabled = candidate.status !== "ready";
        importButton.addEventListener(
          "click",
          () => importDiscoveredSource(candidate.id, detail, importButton)
        );
        const improveButton = document.createElement("button");
        improveButton.type = "button";
        improveButton.textContent = "Improve";
        improveButton.disabled = candidate.status !== "ready";
        improveButton.addEventListener(
          "click",
          () => improveDiscoveredSource(candidate.id, payload.home || "", detail, improveButton)
        );
        actions.append(importButton, improveButton);
        detail.append(title, summary, command, actions);
        if (state.latestSourceImportReport?.candidateId === candidate.id) {
          const importDetail = document.createElement("div");
          importDetail.className = "detail";
          renderDiscoveredImportReport(importDetail, state.latestSourceImportReport.payload || {});
          detail.appendChild(importDetail);
        }
        if (state.latestSourceImproveReport?.candidateId === candidate.id) {
          const improveDetail = document.createElement("div");
          improveDetail.className = "detail";
          renderImproveReport(improveDetail, state.latestSourceImproveReport.payload || {});
          detail.appendChild(improveDetail);
        }
      }
    }

    async function importDiscoveredSource(candidateId, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson(
          "/api/import-discovered-source",
          selectedProfilePayload({ candidate_id: candidateId })
        );
        state.latestSourceImportReport = { candidateId, payload };
        await loadDashboard();
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    async function improveDiscoveredSource(candidateId, sourceHome, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson(
          "/api/improve",
          selectedProfilePayload(withSelectedReplayAdapter(withSelectedOperatorAdapter({
            source_candidate_id: candidateId,
            source_home: sourceHome || undefined,
            run_autonomy: false
          })))
        );
        state.latestSourceImproveReport = { candidateId, payload };
        await loadDashboard();
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderImproveReport(detail, payload) {
      detail.innerHTML = "";
      const sourceImport = payload.source_import || {};
      const candidate = sourceImport.candidate || {};
      const decisions = payload.autonomy?.decisions || [];
      const latestDecision = decisions.length ? decisions[decisions.length - 1] : null;
      const patchTransactionIds = (decisions || []).flatMap(
        (decision) => decision.patch_transaction_ids || []
      );
      const autonomyLabel = latestDecision
        ? `${latestDecision.action || "unknown"}${latestDecision.reason ? `: ${latestDecision.reason}` : ""}`
        : payload.autonomy ? "ran" : "disabled";
      const cells = [
        ["Profile", payload.profile_id || "unknown"],
        ["Proposal", payload.proposal_id || "none"],
        ["Operator", improveOperatorLabel(payload)],
        ["Source", candidate.id || "none"],
        ["Generated evals", `${(payload.generated_eval_spec_ids || []).length}`],
        ["Replay runs", `${(payload.replay_runs || []).length}`],
        ["Replay adapters", improveReplayAdapterLabel(payload)],
        ["Autonomy", autonomyLabel],
        ["Patch tx", `${patchTransactionIds.length}`]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      if (latestDecision) {
        summary.textContent = `Improve ${latestDecision.action || "completed"} for ${payload.proposal_id || "proposal"}${latestDecision.reason ? `: ${latestDecision.reason}` : ""}.`;
      } else {
        summary.textContent = payload.proposal_id
          ? `Improvement proposal ${payload.proposal_id} is ready for review.`
          : "Improve completed without creating a proposal.";
      }
      detail.append(grid, summary);
      if (patchTransactionIds.length) {
        const patchSummary = document.createElement("pre");
        patchSummary.textContent = patchTransactionIds.join("\\n");
        detail.appendChild(patchSummary);
      }
    }

    function improveOperatorLabel(payload) {
      const analyzeOperator = payload.analyze?.operator;
      if (analyzeOperator) {
        return analyzeOperator;
      }
      return payload.operator || "none";
    }

    function improveReplayAdapterLabel(payload) {
      const adapterIds = (payload.replay_runs || [])
        .map((run) => run.adapter_id)
        .filter(Boolean);
      const uniqueAdapterIds = Array.from(new Set(adapterIds));
      return uniqueAdapterIds.length ? uniqueAdapterIds.join(", ") : "none";
    }

    function renderDiscoveredImportReport(detail, payload) {
      const report = payload.import || {};
      const candidate = payload.candidate || {};
      const counts = report.counts || {};
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = `Imported ${candidate.label || candidate.id || "source"} into ${report.profile_id || "Kyoko"}.`;
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      const cells = [
        ["Tasks", `${counts.tasks || 0}`],
        ["Runs", `${counts.runs || 0}`],
        ["Spans", `${counts.spans || 0}`],
        ["Handoffs", `${counts.handoffs || 0}`],
        ["Timeline", `${counts.timeline_events || 0}`],
        ["Normalized", report.normalized_path || "not written"]
      ];
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      detail.append(summary, grid);
    }

    async function importOpenClawSessions(sessionPath, agentId, sessionKey, profileId, outputPath, detail, button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/import-openclaw-sessions", {
          session_path: sessionPath,
          agent_id: agentId || undefined,
          session_key: sessionKey || undefined,
          profile_id: profileId || undefined,
          output_path: outputPath || undefined
        });
        renderOpenClawImportReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderHermesImportReport(detail, payload) {
      detail.innerHTML = "";
      const counts = payload.counts || {};
      const cells = [
        ["Profile", payload.profile_id || "unknown"],
        ["Tasks", `${counts.tasks || 0}`],
        ["Attempts", `${counts.task_attempts || 0}`],
        ["Runs", `${counts.runs || 0}`],
        ["Handoffs", `${counts.handoffs || 0}`],
        ["Timeline", `${counts.timeline_events || 0}`],
        ["Normalized", payload.normalized_path || "not written"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = `Imported ${payload.kanban_db_path || "Hermes kanban.db"} into Kyoko.`;
      detail.append(grid, summary);
    }

    function renderOpenClawImportReport(detail, payload) {
      detail.innerHTML = "";
      const counts = payload.counts || {};
      const cells = [
        ["Profile", payload.profile_id || "unknown"],
        ["Tasks", `${counts.tasks || 0}`],
        ["Runs", `${counts.runs || 0}`],
        ["Spans", `${counts.spans || 0}`],
        ["Handoffs", `${counts.handoffs || 0}`],
        ["Timeline", `${counts.timeline_events || 0}`],
        ["Normalized", payload.normalized_path || "not written"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = `Imported ${payload.source_path || "OpenClaw sessions"} into Kyoko.`;
      detail.append(grid, summary);
    }

    async function ingestOtlpJson(rawJson, profileId, sourceKind, detail, button) {
      button.disabled = true;
      try {
        const parsed = JSON.parse(rawJson || "{}");
        const payload = await postJson("/api/ingest-otlp", {
          otlp: parsed,
          profile_id: profileId || undefined,
          source_kind: sourceKind || "otlp_http"
        });
        renderOtlpIngestReport(detail, payload);
        detail.hidden = false;
      } catch (error) {
        showError(error);
      } finally {
        button.disabled = false;
      }
    }

    function renderOtlpIngestReport(detail, payload) {
      detail.innerHTML = "";
      const counts = payload.ingested_counts || {};
      const cells = [
        ["Profile", payload.profile_id || "unknown"],
        ["Runs", `${(payload.run_ids || []).length}`],
        ["Spans", `${(payload.span_ids || []).length}`],
        ["Inserted runs", `${counts.runs || 0}`],
        ["Inserted spans", `${counts.spans || 0}`],
        ["Normalized", payload.normalized_path || "not written"]
      ];
      const grid = document.createElement("div");
      grid.className = "detail-grid";
      for (const [label, value] of cells) {
        const cell = document.createElement("div");
        cell.className = "detail-cell";
        const strong = document.createElement("strong");
        strong.textContent = value;
        const caption = document.createElement("span");
        caption.textContent = label;
        cell.append(strong, caption);
        grid.appendChild(cell);
      }
      const summary = document.createElement("div");
      summary.className = "item-summary";
      summary.textContent = "OTLP JSON normalized into Kyoko source events.";
      detail.append(grid, summary);
    }

    async function runDemo(button) {
      button.disabled = true;
      try {
        await postJson("/api/demo", { run_loop: true, apply_context: true });
        await loadDashboard();
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function runAutonomy(button) {
      button.disabled = true;
      try {
        const payload = await postJson("/api/autonomy/run", selectedProfilePayload(withHarnessWorkspaceRoot({})));
        await loadDashboard();
        renderPolicyActionReport(policyActionDetailEl, "Run autonomy", payload);
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function runProfileNext(button) {
      button.disabled = true;
      try {
        const request = withSelectedReplayAdapter(withHarnessWorkspaceRoot({ run: true }));
        const operatorAdapterId = selectedOperatorAdapterId();
        if (operatorAdapterId) {
          request.operator_adapter_id = operatorAdapterId;
        }
        const payload = await postJson("/api/profile-next", request);
        await loadDashboard();
        renderPolicyActionReport(policyActionDetailEl, "Run next", payload);
      } catch (error) {
        showError(error);
        button.disabled = false;
      }
    }

    async function postJson(path, payload) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(payload)
      });
      const body = await response.json();
      if (!response.ok) {
        throw new Error(body.detail || body.error || response.statusText);
      }
      return body;
    }

    function authHeaders() {
      return authToken ? { "Authorization": `Bearer ${authToken}` } : {};
    }

    function showError(error) {
      errorEl.innerHTML = "";
      const node = document.createElement("div");
      node.className = "error";
      node.textContent = error.message || String(error);
      errorEl.appendChild(node);
    }

    function latestBy(rows, key) {
      const byId = {};
      for (const row of rows) {
        const value = row[key];
        if (!value) {
          continue;
        }
        if (!byId[value] || String(row.created_at || "") > String(byId[value].created_at || "")) {
          byId[value] = row;
        }
      }
      return byId;
    }

    function formatValue(value) {
      if (value === null || value === undefined) {
        return "null";
      }
      if (typeof value === "object") {
        return JSON.stringify(value);
      }
      return String(value);
    }

    function badge(label, kind) {
      const node = document.createElement("span");
      node.className = `badge ${kind || ""}`.trim();
      node.textContent = label;
      return node;
    }

    function emptyNode(text) {
      const node = document.createElement("div");
      node.className = "empty";
      node.textContent = text;
      return node;
    }
  </script>
</body>
</html>
"""
