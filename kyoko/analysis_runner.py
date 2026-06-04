"""Dashboard-driven analysis orchestration.

A single entry point — :func:`execute_analysis_job` — runs one analysis end to end:

  (optional) refresh-import new traces  →  scope to new/all/one run
  →  dispatch to the chosen analyzer (ace | codex | claude | openclaw | hermes
     | generic | command | mock)  →  the normal gate (checks → replay → autonomy).

Both the dashboard ("Run now") and the recurring :class:`Scheduler` submit jobs to a
single-worker :class:`AnalysisRunner`, so runs never overlap and there is exactly one
execution/redaction/gate path. Nothing here bypasses the autonomy gate — a fired
schedule runs the same :func:`kyoko.improve.run_improvement_loop` as everything else,
and the profile's autonomy policy stays the sole decider of whether anything is applied.

The scheduler is a daemon thread inside ``kyoko serve``; schedules persist in SQLite but
only fire while the server is running (a documented single-machine limitation).
"""

from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from .live import EVENT_ANALYSIS, LiveBus, global_bus
from .storage import (
    StorageError,
    list_analysis_schedules,
    record_schedule_result,
    runs_newer_than,
    update_analysis_schedule,
    utc_now,
)

# Analyzers the dashboard offers. ace/codex/claude are manual-only; openclaw/hermes can
# additionally be scheduled (they are connected trace sources). "mock"/"command" exist
# for tests and ad-hoc CLI use.
DASHBOARD_ANALYZERS = ("ace", "codex", "claude", "openclaw", "hermes")
SCHEDULABLE_ANALYZERS = ("openclaw", "hermes")
_OPERATOR_ADAPTER_ANALYZERS = {"codex", "claude", "openclaw", "hermes", "generic", "adapter"}


class AnalysisRunError(Exception):
    """Raised for invalid analysis-job configuration."""


@dataclass
class AnalysisJob:
    analyzer: str
    adapter_id: Optional[str] = None
    scope: str = "all"  # all | new | run
    run_id: Optional[str] = None
    since: Optional[str] = None
    refresh_import: bool = False
    source_kind: Optional[str] = None
    source_path: Optional[str] = None
    run_autonomy: bool = True
    ace_command: Optional[Sequence[str]] = None
    operator_command: Optional[Sequence[str]] = None
    timeout_seconds: int = 120
    max_retries: int = 0
    schedule_id: Optional[str] = None
    profile_id: Optional[str] = None
    output_dir: Optional[Path] = None
    job_id: str = field(default_factory=lambda: f"analysis_{uuid.uuid4().hex[:12]}")


def execute_analysis_job(
    db_path: Path,
    job: AnalysisJob,
    *,
    bus: Optional[LiveBus] = None,
) -> dict[str, Any]:
    """Run one analysis job synchronously and return a result record.

    Never raises for an analysis failure — failures are reported in the returned
    ``status``/``error`` so the worker thread and schedulers stay alive. Programming
    misuse (bad ``analyzer``) raises :class:`AnalysisRunError` before any work starts.
    """

    if job.analyzer not in DASHBOARD_ANALYZERS and job.analyzer not in {"mock", "command", "generic", "adapter"}:
        raise AnalysisRunError(f"unsupported_analyzer:{job.analyzer}")
    if job.scope not in {"all", "new", "run"}:
        raise AnalysisRunError(f"unsupported_scope:{job.scope}")
    if job.scope == "run" and not job.run_id:
        raise AnalysisRunError("run_id_required_for_scope_run")

    publish = _publisher(bus)
    started_at = utc_now()
    base = {
        "job_id": job.job_id,
        "schedule_id": job.schedule_id,
        "analyzer": job.analyzer,
        "scope": job.scope,
        "started_at": started_at,
    }
    publish("running", base)

    try:
        profile_id = _refresh_and_resolve_profile(db_path, job, publish, base)
        since, watermark_after, new_run_count = _resolve_scope(db_path, job, profile_id)

        if job.scope == "new" and new_run_count == 0:
            result = {**base, "status": "skipped", "reason": "no_new_traces", "ended_at": utc_now()}
            _record_schedule(db_path, job, result, watermark_after)
            publish("skipped", result)
            return result

        publish("analyzing", {**base, "since": since, "new_run_count": new_run_count})
        proposal_ids, operator_run_id, autonomy = _dispatch(db_path, job, profile_id, since)

        result = {
            **base,
            "status": "succeeded",
            "profile_id": profile_id,
            "proposal_ids": proposal_ids,
            "operator_run_id": operator_run_id,
            "autonomy": autonomy,
            "since": since,
            "new_run_count": new_run_count,
            "ended_at": utc_now(),
        }
        _record_schedule(db_path, job, result, watermark_after)
        publish("succeeded", result)
        return result
    except Exception as exc:  # noqa: BLE001 — surface as a result, never crash the worker
        result = {**base, "status": "failed", "error": str(exc), "ended_at": utc_now()}
        _record_schedule(db_path, job, result, None)
        publish("failed", result)
        return result


def _refresh_and_resolve_profile(
    db_path: Path,
    job: AnalysisJob,
    publish: Callable[[str, dict[str, Any]], None],
    base: dict[str, Any],
) -> str:
    profile_id = job.profile_id
    if job.refresh_import and job.source_path and job.source_kind:
        publish("importing", {**base, "source_kind": job.source_kind})
        profile_id = _refresh_import(db_path, job) or profile_id
    if profile_id:
        return profile_id
    return _first_profile_id(db_path)


def _refresh_import(db_path: Path, job: AnalysisJob) -> Optional[str]:
    source_path = Path(str(job.source_path)).expanduser()
    if job.source_kind == "openclaw_sessions":
        from .openclaw_import import ingest_openclaw_sessions

        report = ingest_openclaw_sessions(
            db_path=db_path, source_path=source_path, profile_id=job.profile_id
        )
        return report.profile_id
    if job.source_kind == "hermes_kanban":
        from .hermes_import import ingest_hermes_kanban_db

        report = ingest_hermes_kanban_db(
            db_path=db_path, kanban_db_path=source_path, profile_id=job.profile_id
        )
        return report.profile_id
    raise AnalysisRunError(f"unsupported_source_kind:{job.source_kind}")


def _resolve_scope(
    db_path: Path,
    job: AnalysisJob,
    profile_id: str,
) -> tuple[Optional[str], Optional[str], int]:
    """Return ``(since, watermark_after, new_run_count)``.

    ``since`` is the cutoff passed to the evidence bundle (None = all runs / single run).
    ``watermark_after`` is the max run timestamp seen, used to advance a schedule cursor.
    """

    if job.scope == "run":
        return None, None, 1
    if job.scope == "all":
        _, max_started = runs_newer_than(db_path, profile_id=profile_id, since=None)
        return None, max_started, 0
    # scope == "new"
    since = job.since
    count, max_started = runs_newer_than(db_path, profile_id=profile_id, since=since)
    # Advance to the newest run seen (or keep the prior cutoff if nothing newer).
    watermark_after = max_started or since
    return since, watermark_after, count


def _dispatch(
    db_path: Path,
    job: AnalysisJob,
    profile_id: str,
    since: Optional[str],
) -> tuple[list[str], Optional[str], Optional[dict[str, Any]]]:
    if job.analyzer == "ace":
        return _dispatch_ace(db_path, job, profile_id)

    from .improve import run_improvement_loop

    if job.analyzer == "mock":
        operator, operator_adapter, operator_command = "mock", None, None
    elif job.analyzer == "command":
        operator, operator_adapter, operator_command = "command", None, job.operator_command
    else:  # codex | claude | openclaw | hermes | generic | adapter
        operator = "adapter"
        operator_adapter = job.adapter_id or job.analyzer
        operator_command = None

    report = run_improvement_loop(
        db_path=db_path,
        proposal_id=None,
        operator=operator,
        operator_adapter=operator_adapter,
        operator_command=operator_command,
        operator_timeout_seconds=job.timeout_seconds,
        operator_max_retries=job.max_retries,
        profile_id=profile_id,
        run_id=job.run_id if job.scope == "run" else None,
        since=since,
        output_dir=job.output_dir,
        run_autonomy_after=job.run_autonomy,
        schedule_id=job.schedule_id,
    )
    operator_run_id = report.analyze.operator_run_id if report.analyze is not None else None
    autonomy = report.autonomy.to_json() if report.autonomy is not None else None
    return [report.proposal_id], operator_run_id, autonomy


def _dispatch_ace(
    db_path: Path,
    job: AnalysisJob,
    profile_id: str,
) -> tuple[list[str], Optional[str], Optional[dict[str, Any]]]:
    if not job.ace_command:
        raise AnalysisRunError("ace_command_required")
    from .ace_bridge import run_native_ace_command
    from .improve import run_improvement_loop

    report = run_native_ace_command(
        db_path=db_path,
        command=list(job.ace_command),
        profile_id=profile_id,
        output_dir=job.output_dir,
        persist=True,
        producer_name="native_ace",
        timeout_seconds=job.timeout_seconds,
    )
    proposal_ids = list(report.diff.proposal_ids)
    last_autonomy: Optional[dict[str, Any]] = None
    # ACE proposals go through the same gate as everything else, one per proposal.
    for proposal_id in proposal_ids:
        loop = run_improvement_loop(
            db_path=db_path,
            proposal_id=proposal_id,
            profile_id=report.diff.profile_id,
            run_autonomy_after=job.run_autonomy,
            schedule_id=job.schedule_id,
        )
        if loop.autonomy is not None:
            last_autonomy = loop.autonomy.to_json()
    return proposal_ids, None, last_autonomy


def _record_schedule(
    db_path: Path,
    job: AnalysisJob,
    result: dict[str, Any],
    watermark_after: Optional[str],
) -> None:
    if not job.schedule_id:
        return
    try:
        record_schedule_result(
            db_path=db_path,
            schedule_id=job.schedule_id,
            last_run_at=result.get("started_at", utc_now()),
            last_status=str(result.get("status")),
            last_operator_run_id=result.get("operator_run_id"),
            last_error=result.get("error"),
            watermark=watermark_after if result.get("status") in {"succeeded", "skipped"} else None,
        )
    except StorageError:
        # A deleted schedule should not turn a successful analysis into a failure.
        pass


def _publisher(bus: Optional[LiveBus]) -> Callable[[str, dict[str, Any]], None]:
    target = bus or global_bus()

    def publish(status: str, data: dict[str, Any]) -> None:
        target.publish(EVENT_ANALYSIS, {**data, "status": status, "at": utc_now()})

    return publish


def _first_profile_id(db_path: Path) -> str:
    from .storage import connect

    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM profiles ORDER BY created_at, id LIMIT 1"
        ).fetchone()
    if row is None:
        raise AnalysisRunError("no_profiles_found")
    return str(row["id"])


# ---------------------------------------------------------------------------
# Schedule timing
# ---------------------------------------------------------------------------

def compute_next_run_at(
    now: datetime,
    interval_hours: int,
    at_time: Optional[str] = None,
    *,
    tz: Optional[Any] = None,
) -> datetime:
    """Return the next fire time (aware, UTC) strictly after ``now``.

    With ``at_time`` (``'HH:MM'``, local) the anchor is that local wall-clock time and
    the cadence steps by ``interval_hours`` (so ``at_time`` + 24h == "daily at HH:MM").
    Without ``at_time`` it is simply ``now + interval_hours``.
    """

    if interval_hours <= 0:
        raise AnalysisRunError("interval_hours_must_be_positive")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    interval = timedelta(hours=interval_hours)
    if at_time:
        local_tz = tz or now.astimezone().tzinfo
        hh, mm = (int(part) for part in at_time.split(":"))
        now_local = now.astimezone(local_tz)
        candidate = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
        while candidate <= now_local:
            candidate += interval
        return candidate.astimezone(timezone.utc)
    return (now + interval).astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def next_run_at_iso(interval_hours: int, at_time: Optional[str], *, now: Optional[datetime] = None) -> str:
    return _iso_utc(compute_next_run_at(now or datetime.now(timezone.utc), interval_hours, at_time))


def _parse_iso(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---------------------------------------------------------------------------
# Single-worker runner + scheduler (used by `kyoko serve`)
# ---------------------------------------------------------------------------

class AnalysisRunner:
    """Single background worker that drains a queue of analysis jobs serially."""

    def __init__(self, db_path: Path, *, bus: Optional[LiveBus] = None) -> None:
        self._db_path = db_path
        self._bus = bus or global_bus()
        self._queue: "queue.Queue[Optional[AnalysisJob]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="kyoko-analysis-runner", daemon=True)
        self._thread.start()

    def submit(self, job: AnalysisJob) -> str:
        self._queue.put(job)
        return job.job_id

    def stop(self) -> None:
        self._stop.set()
        self._queue.put(None)

    def _run(self) -> None:
        while not self._stop.is_set():
            job = self._queue.get()
            if job is None:
                break
            try:
                execute_analysis_job(self._db_path, job, bus=self._bus)
            except Exception:  # noqa: BLE001 — a bad job must not kill the worker
                continue


class InlineAnalysisRunner:
    """Executes jobs synchronously on ``submit`` — used on the request path and in tests
    where a background worker would make behavior non-deterministic."""

    def __init__(self, db_path: Path, *, bus: Optional[LiveBus] = None) -> None:
        self._db_path = db_path
        self._bus = bus

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def submit(self, job: AnalysisJob) -> str:
        execute_analysis_job(self._db_path, job, bus=self._bus)
        return job.job_id


class Scheduler:
    """Daemon thread that fires due analysis schedules into an :class:`AnalysisRunner`."""

    def __init__(
        self,
        db_path: Path,
        runner: AnalysisRunner,
        *,
        poll_seconds: float = 60.0,
    ) -> None:
        self._db_path = db_path
        self._runner = runner
        self._poll_seconds = poll_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="kyoko-analysis-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        # Backfill next_run_at for any schedule missing one, then poll.
        while not self._stop.is_set():
            try:
                self.tick(datetime.now(timezone.utc))
            except Exception:  # noqa: BLE001 — never let the scheduler thread die
                pass
            self._stop.wait(self._poll_seconds)

    def tick(self, now: datetime) -> list[str]:
        """Fire all due schedules. Returns the job ids submitted. Pure-ish: ``now`` is
        injected so this is unit-testable without real time."""

        submitted: list[str] = []
        for schedule in list_analysis_schedules(self._db_path, enabled_only=True):
            next_at = schedule.get("next_run_at")
            if not next_at:
                # First sight of this schedule — arm it without firing immediately.
                update_analysis_schedule(
                    db_path=self._db_path,
                    schedule_id=schedule["id"],
                    next_run_at=next_run_at_iso(
                        int(schedule["interval_hours"]), schedule.get("at_time"), now=now
                    ),
                )
                continue
            if _parse_iso(str(next_at)) > now:
                continue
            # Due: re-arm next_run_at first (so a long job can't double-fire), then submit.
            update_analysis_schedule(
                db_path=self._db_path,
                schedule_id=schedule["id"],
                next_run_at=next_run_at_iso(
                    int(schedule["interval_hours"]), schedule.get("at_time"), now=now
                ),
            )
            submitted.append(self._runner.submit(job_from_schedule(schedule)))
        return submitted


def job_from_schedule(schedule: dict[str, Any]) -> AnalysisJob:
    return AnalysisJob(
        analyzer=str(schedule["analyzer_kind"]),
        adapter_id=schedule.get("adapter_id") or str(schedule["analyzer_kind"]),
        scope="new",
        since=schedule.get("watermark"),
        refresh_import=bool(schedule.get("refresh_import")),
        source_kind=schedule.get("source_kind"),
        source_path=schedule.get("source_path"),
        run_autonomy=bool(schedule.get("run_autonomy", True)),
        profile_id=schedule.get("profile_id"),
        schedule_id=schedule.get("id"),
    )
