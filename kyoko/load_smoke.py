from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .apply import list_context_delivery_rules, list_skills
from .autonomy import get_autonomy_policy
from .blobs import prune_payload_blobs, put_blob, storage_report
from .details import get_run_detail, list_runs
from .evidence import build_evidence_bundle
from .checks import list_check_runs, list_check_specs, list_replay_runs
from .harness import list_harness_target_locks
from .proposals import list_learning_proposals
from .redaction import get_redaction_policy
from .skillbook import render_skillbook_prompt
from .storage import (
    StorageError,
    checkpoint_database,
    connect,
    get_database_status,
    ingest_source_payload,
    status_to_json,
)


DEFAULT_PROFILE_ID = "profile_load_smoke"
DEFAULT_RUN_COUNT = 120
DEFAULT_SPANS_PER_RUN = 5
DEFAULT_READ_WORKERS = 4
DEFAULT_READ_ITERATIONS = 10
DEFAULT_EXPIRED_BLOB_COUNT = 8


class LoadSmokeError(Exception):
    """Raised when a load smoke run cannot be completed."""


@dataclass(frozen=True)
class LoadSmokeReport:
    db_path: Path
    profile_id: str
    seeded: bool
    parameters: dict[str, Any]
    status: dict[str, Any]
    storage: dict[str, Any]
    wal_checkpoint: dict[str, Any]
    retention_dry_run: dict[str, Any]
    latency_ms: dict[str, float]
    operation_latency_ms: dict[str, dict[str, float]]
    total_read_operations: int
    errors: tuple[dict[str, Any], ...]
    duration_ms: float
    passed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "profile_id": self.profile_id,
            "seeded": self.seeded,
            "parameters": self.parameters,
            "status": self.status,
            "storage": self.storage,
            "wal_checkpoint": self.wal_checkpoint,
            "retention_dry_run": self.retention_dry_run,
            "latency_ms": self.latency_ms,
            "operation_latency_ms": self.operation_latency_ms,
            "total_read_operations": self.total_read_operations,
            "errors": list(self.errors),
            "duration_ms": self.duration_ms,
            "passed": self.passed,
        }


def run_load_smoke(
    *,
    db_path: Path,
    profile_id: Optional[str] = DEFAULT_PROFILE_ID,
    seed: bool = True,
    run_count: int = DEFAULT_RUN_COUNT,
    spans_per_run: int = DEFAULT_SPANS_PER_RUN,
    read_workers: int = DEFAULT_READ_WORKERS,
    read_iterations: int = DEFAULT_READ_ITERATIONS,
    expired_blob_count: int = DEFAULT_EXPIRED_BLOB_COUNT,
    checkpoint_mode: str = "PASSIVE",
    max_p95_ms: Optional[float] = None,
) -> LoadSmokeReport:
    _validate_positive("run_count", run_count)
    _validate_positive("spans_per_run", spans_per_run)
    _validate_positive("read_workers", read_workers)
    _validate_positive("read_iterations", read_iterations)
    if expired_blob_count < 0:
        raise LoadSmokeError("expired_blob_count_must_be_non_negative")

    start = time.perf_counter()
    selected_profile_id = profile_id or DEFAULT_PROFILE_ID
    seeded_counts: dict[str, int] = {}
    if seed:
        source_payload = build_load_smoke_source_payload(
            profile_id=selected_profile_id,
            run_count=run_count,
            spans_per_run=spans_per_run,
        )
        ingest_report = ingest_source_payload(
            db_path=db_path,
            fixture=source_payload,
            source_label="load-smoke",
        )
        selected_profile_id = ingest_report.profile_id
        seeded_counts = dict(ingest_report.inserted_counts)
        _seed_expired_blobs(
            db_path=db_path,
            profile_id=selected_profile_id,
            expired_blob_count=expired_blob_count,
        )
    else:
        selected_profile_id = _resolve_profile_id(db_path, selected_profile_id)

    sample_run_id = _sample_run_id(db_path=db_path, profile_id=selected_profile_id)
    operations = _dashboard_read_operations(
        db_path=db_path,
        profile_id=selected_profile_id,
        sample_run_id=sample_run_id,
    )
    if not operations:
        raise LoadSmokeError("no_read_operations_available")

    samples: list[tuple[str, float]] = []
    errors: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=read_workers) as executor:
        futures = [
            executor.submit(
                _run_read_worker,
                worker_index=worker_index,
                iterations=read_iterations,
                operations=operations,
            )
            for worker_index in range(read_workers)
        ]
        for future in as_completed(futures):
            worker_samples, worker_errors = future.result()
            samples.extend(worker_samples)
            errors.extend(worker_errors)

    checkpoint = checkpoint_database(db_path, mode=checkpoint_mode).to_json()
    retention = prune_payload_blobs(
        db_path,
        profile_id=selected_profile_id,
        dry_run=True,
    ).to_json()
    status = status_to_json(get_database_status(db_path))
    storage = storage_report(db_path).to_json()
    latency = _latency_summary([elapsed for _name, elapsed in samples])
    operation_latency = {
        name: _latency_summary([elapsed for sample_name, elapsed in samples if sample_name == name])
        for name, _operation in operations
    }
    duration_ms = _elapsed_ms(start)
    passed = not errors and (
        max_p95_ms is None
        or latency.get("p95", 0.0) <= max_p95_ms
    )

    return LoadSmokeReport(
        db_path=db_path,
        profile_id=selected_profile_id,
        seeded=seed,
        parameters={
            "run_count": run_count,
            "spans_per_run": spans_per_run,
            "read_workers": read_workers,
            "read_iterations": read_iterations,
            "expired_blob_count": expired_blob_count,
            "checkpoint_mode": checkpoint_mode.upper(),
            "max_p95_ms": max_p95_ms,
            "seeded_counts": seeded_counts,
            "sample_run_id": sample_run_id,
        },
        status=status,
        storage=storage,
        wal_checkpoint=checkpoint,
        retention_dry_run=retention,
        latency_ms=latency,
        operation_latency_ms=operation_latency,
        total_read_operations=len(samples),
        errors=tuple(errors[:25]),
        duration_ms=duration_ms,
        passed=passed,
    )


def build_load_smoke_source_payload(
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    run_count: int = DEFAULT_RUN_COUNT,
    spans_per_run: int = DEFAULT_SPANS_PER_RUN,
) -> dict[str, Any]:
    _validate_positive("run_count", run_count)
    _validate_positive("spans_per_run", spans_per_run)
    source_id = f"source_{profile_id}"
    researcher_id = f"agent_{profile_id}_researcher"
    reviewer_id = f"agent_{profile_id}_reviewer"
    root_node_id = f"node_{profile_id}_researcher"
    tool_node_id = f"node_{profile_id}_tool"
    queue_id = f"queue_{profile_id}"
    runs = []
    spans = []
    tasks = []
    task_attempts = []
    handoffs = []
    timeline_events = []

    for run_index in range(run_count):
        run_id = f"run_load_{run_index:04d}"
        task_id = f"task_load_{run_index:04d}"
        attempt_id = f"attempt_load_{run_index:04d}"
        root_span_id = f"span_load_{run_index:04d}_0000"
        failed = run_index % 10 == 0
        tasks.append(
            {
                "id": task_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "queue_id": queue_id,
                "external_id": f"external-task-{run_index}",
                "title": f"Load smoke task {run_index}",
                "body_ref": f"blob_task_body_{run_index:04d}",
                "status": "failed" if failed else "completed",
                "assignee_agent_identity_id": researcher_id,
                "created_by_agent_identity_id": reviewer_id,
                "priority": "normal",
                "workspace_kind": "local",
                "workspace_path": ".",
                "created_at": "2026-05-31T12:00:00Z",
                "started_at": "2026-05-31T12:00:05Z",
                "completed_at": "2026-05-31T12:01:00Z",
                "metadata_json": {"load_smoke": True, "run_index": run_index},
            }
        )
        task_attempts.append(
            {
                "id": attempt_id,
                "task_id": task_id,
                "run_id": run_id,
                "agent_identity_id": researcher_id,
                "status": "failed" if failed else "completed",
                "outcome": "timeout" if failed else "success",
                "claim_token_hash": None,
                "worker_pid": None,
                "started_at": "2026-05-31T12:00:05Z",
                "ended_at": "2026-05-31T12:01:00Z",
                "last_heartbeat_at": "2026-05-31T12:00:50Z",
                "summary_ref": f"blob_attempt_summary_{run_index:04d}",
                "metadata_json": {"load_smoke": True},
                "error_ref": f"blob_attempt_error_{run_index:04d}" if failed else None,
            }
        )
        runs.append(
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": f"external-run-{run_index}",
                "root_span_id": root_span_id,
                "agent_identity_id": researcher_id,
                "task_attempt_id": attempt_id,
                "status": "failed" if failed else "succeeded",
                "started_at": "2026-05-31T12:00:05Z",
                "ended_at": "2026-05-31T12:01:00Z",
                "input_ref": f"blob_run_input_{run_index:04d}",
                "output_ref": f"blob_run_output_{run_index:04d}",
                "summary": f"Generated load smoke run {run_index}",
                "metadata_json": {"load_smoke": True, "run_index": run_index},
            }
        )
        for span_index in range(spans_per_run):
            span_id = f"span_load_{run_index:04d}_{span_index:04d}"
            span_failed = failed and span_index == spans_per_run - 1
            spans.append(
                {
                    "id": span_id,
                    "run_id": run_id,
                    "source_id": source_id,
                    "external_id": f"external-span-{run_index}-{span_index}",
                    "parent_span_id": None if span_index == 0 else root_span_id,
                    "workflow_node_id": root_node_id if span_index == 0 else tool_node_id,
                    "agent_identity_id": researcher_id,
                    "kind": "agent" if span_index == 0 else "tool",
                    "name": "root" if span_index == 0 else f"tool_{span_index}",
                    "status": "failed" if span_failed else "succeeded",
                    "started_at": "2026-05-31T12:00:05Z",
                    "ended_at": "2026-05-31T12:00:45Z",
                    "input_ref": f"blob_span_input_{run_index:04d}_{span_index:04d}",
                    "output_ref": f"blob_span_output_{run_index:04d}_{span_index:04d}",
                    "usage_json": {
                        "input_tokens": span_index + 1,
                        "output_tokens": span_index + 2,
                    },
                    "attributes_json": {
                        "load_smoke": True,
                        "run_index": run_index,
                        "span_index": span_index,
                    },
                    "raw_ref": f"blob_raw_span_{run_index:04d}_{span_index:04d}",
                }
            )
            if span_failed:
                timeline_events.append(
                    {
                        "id": f"event_load_span_failed_{run_index:04d}",
                        "profile_id": profile_id,
                        "source_id": source_id,
                        "entity_type": "span",
                        "entity_id": span_id,
                        "kind": "span_failed",
                        "at": "2026-05-31T12:00:45Z",
                        "agent_identity_id": researcher_id,
                        "payload_ref": f"blob_span_failed_{run_index:04d}",
                        "metadata_json": {"load_smoke": True},
                    }
                )
        if failed:
            handoffs.append(
                {
                    "id": f"handoff_load_{run_index:04d}",
                    "profile_id": profile_id,
                    "source_id": source_id,
                    "from_agent_identity_id": researcher_id,
                    "to_agent_identity_id": reviewer_id,
                    "from_workflow_node_id": root_node_id,
                    "to_workflow_node_id": tool_node_id,
                    "from_task_id": task_id,
                    "to_task_id": None,
                    "run_id": run_id,
                    "span_id": f"span_load_{run_index:04d}_{spans_per_run - 1:04d}",
                    "kind": "failure_escalation",
                    "reason_ref": f"blob_handoff_reason_{run_index:04d}",
                    "payload_ref": f"blob_handoff_payload_{run_index:04d}",
                    "created_at": "2026-05-31T12:00:50Z",
                    "metadata_json": {"load_smoke": True},
                }
            )
        timeline_events.append(
            {
                "id": f"event_load_run_completed_{run_index:04d}",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "run",
                "entity_id": run_id,
                "kind": "run_failed" if failed else "run_completed",
                "at": "2026-05-31T12:01:00Z",
                "agent_identity_id": researcher_id,
                "payload_ref": f"blob_run_event_{run_index:04d}",
                "metadata_json": {"load_smoke": True},
            }
        )

    return {
        "profile": {
            "id": profile_id,
            "name": "Load Smoke",
            "root_path": ".",
            "status": "active",
            "created_at": "2026-05-31T12:00:00Z",
            "updated_at": "2026-05-31T12:00:00Z",
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "generated",
                "display_name": "Generated load smoke source",
                "status": "active",
                "adapter_version": "load-smoke",
                "config_json": {"load_smoke": True},
                "capabilities_json": {"load_smoke": True},
                "last_seen_at": "2026-05-31T12:01:00Z",
            }
        ],
        "agent_identities": [
            {
                "id": researcher_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "load-researcher",
                "name": "load-researcher",
                "kind": "agent",
                "role": "researcher",
                "model": "test-model",
                "workspace_path": ".",
                "metadata_json": {"load_smoke": True},
            },
            {
                "id": reviewer_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "load-reviewer",
                "name": "load-reviewer",
                "kind": "agent",
                "role": "reviewer",
                "model": "test-model",
                "workspace_path": ".",
                "metadata_json": {"load_smoke": True},
            },
        ],
        "workflow_nodes": [
            {
                "id": root_node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "load-root-node",
                "agent_identity_id": researcher_id,
                "kind": "agent",
                "name": "load-root",
                "metadata_json": {"load_smoke": True},
            },
            {
                "id": tool_node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "load-tool-node",
                "agent_identity_id": researcher_id,
                "kind": "tool",
                "name": "load-tool",
                "metadata_json": {"load_smoke": True},
            },
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "load-queue",
                "name": "load-queue",
                "kind": "local",
                "metadata_json": {"load_smoke": True},
            }
        ],
        "tasks": tasks,
        "task_attempts": task_attempts,
        "runs": runs,
        "spans": spans,
        "handoffs": handoffs,
        "timeline_events": timeline_events,
    }


def _dashboard_read_operations(
    *,
    db_path: Path,
    profile_id: str,
    sample_run_id: Optional[str],
) -> tuple[tuple[str, Callable[[], Any]], ...]:
    operations: list[tuple[str, Callable[[], Any]]] = [
        ("status", lambda: status_to_json(get_database_status(db_path))),
        ("storage_report", lambda: storage_report(db_path).to_json()),
        ("proposals", lambda: {"count": len(list_learning_proposals(db_path))}),
        ("runs", lambda: {"count": len(list_runs(db_path=db_path, profile_id=profile_id))}),
        ("skills", lambda: {"count": len(list_skills(db_path, profile_id=profile_id))}),
        (
            "context_rules",
            lambda: {"count": len(list_context_delivery_rules(db_path, profile_id=profile_id))},
        ),
        (
            "context",
            lambda: {"chars": len(render_skillbook_prompt(db_path, profile_id=profile_id))},
        ),
        (
            "checks",
            lambda: {
                "check_specs": len(list_check_specs(db_path)),
                "check_runs": len(list_check_runs(db_path)),
                "replay_runs": len(list_replay_runs(db_path)),
            },
        ),
        ("policy", lambda: get_autonomy_policy(db_path=db_path, profile_id=profile_id)),
        ("redaction_policy", lambda: get_redaction_policy(db_path=db_path, profile_id=profile_id)),
        (
            "harness_locks",
            lambda: {"count": len(list_harness_target_locks(db_path, profile_id=profile_id))},
        ),
        (
            "evidence_summary",
            lambda: build_evidence_bundle(db_path=db_path, profile_id=profile_id)["summary"],
        ),
        (
            "retention_dry_run",
            lambda: prune_payload_blobs(db_path, profile_id=profile_id, dry_run=True).to_json(),
        ),
    ]
    if sample_run_id:
        operations.append(("run_detail", lambda: get_run_detail(db_path=db_path, run_id=sample_run_id)))
    return tuple(operations)


def _run_read_worker(
    *,
    worker_index: int,
    iterations: int,
    operations: tuple[tuple[str, Callable[[], Any]], ...],
) -> tuple[list[tuple[str, float]], list[dict[str, Any]]]:
    samples: list[tuple[str, float]] = []
    errors: list[dict[str, Any]] = []
    for iteration in range(iterations):
        for name, operation in operations:
            start = time.perf_counter()
            try:
                operation()
            except Exception as exc:  # pragma: no cover - exercised by report assertions.
                errors.append(
                    {
                        "worker": worker_index,
                        "iteration": iteration,
                        "operation": name,
                        "error": f"{type(exc).__name__}:{exc}",
                    }
                )
            samples.append((name, _elapsed_ms(start)))
    return samples, errors


def _seed_expired_blobs(
    *,
    db_path: Path,
    profile_id: str,
    expired_blob_count: int,
) -> None:
    for index in range(expired_blob_count):
        put_blob(
            db_path=db_path,
            profile_id=profile_id,
            kind="load_smoke",
            media_type="text/plain",
            data=f"load-smoke-expired-{index}".encode("utf-8"),
            retained_until="2000-01-01T00:00:00Z",
            metadata={"load_smoke": True, "index": index},
        )


def _resolve_profile_id(db_path: Path, requested_profile_id: str) -> str:
    if not db_path.exists():
        raise LoadSmokeError(f"database_not_found:{db_path}")
    with connect(db_path) as connection:
        if requested_profile_id:
            row = connection.execute(
                "SELECT id FROM profiles WHERE id = ?",
                (requested_profile_id,),
            ).fetchone()
            if row is not None:
                return str(row["id"])
        row = connection.execute(
            "SELECT id FROM profiles ORDER BY created_at, id LIMIT 1"
        ).fetchone()
    if row is None:
        raise LoadSmokeError("no_profiles_found")
    return str(row["id"])


def _sample_run_id(*, db_path: Path, profile_id: str) -> Optional[str]:
    try:
        with connect(db_path) as connection:
            row = connection.execute(
                """
                SELECT id
                FROM runs
                WHERE profile_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (profile_id,),
            ).fetchone()
    except StorageError as exc:
        raise LoadSmokeError(str(exc)) from exc
    return str(row["id"]) if row is not None else None


def _latency_summary(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0.0, "min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    return {
        "count": float(len(ordered)),
        "min": round(ordered[0], 3),
        "p50": round(_percentile(ordered, 0.50), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "max": round(ordered[-1], 3),
    }


def _percentile(ordered_values: list[float], fraction: float) -> float:
    if len(ordered_values) == 1:
        return ordered_values[0]
    index = max(0, min(len(ordered_values) - 1, math.ceil(fraction * len(ordered_values)) - 1))
    return ordered_values[index]


def _validate_positive(name: str, value: int) -> None:
    if value < 1:
        raise LoadSmokeError(f"{name}_must_be_positive")


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
