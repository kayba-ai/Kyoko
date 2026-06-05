"""Tests for dashboard-driven analysis: the runner, scheduler, /api/analysis/* and CLI."""

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kyoko.analysis_runner import (
    AnalysisJob,
    AnalysisRunError,
    Scheduler,
    compute_next_run_at,
    execute_analysis_job,
    next_run_at_iso,
)
from kyoko.cli import main
from kyoko.demo import run_demo_setup
from kyoko.evidence import build_evidence_bundle
from kyoko.storage import (
    connect,
    create_analysis_schedule,
    get_analysis_schedule,
    list_analysis_schedules,
    record_schedule_result,
    runs_newer_than,
    update_analysis_schedule,
)
from kyoko.web import make_handler
from tests.test_improve import _write_failed_openclaw_session


def _demo_db(tmpdir: str) -> Path:
    db_path = Path(tmpdir) / "demo.db"
    run_demo_setup(db_path=db_path, run_loop=False, apply_context=False)
    return db_path


class _RecordingRunner:
    """Stand-in AnalysisRunner that records submitted jobs instead of executing them."""

    def __init__(self) -> None:
        self.jobs: list[AnalysisJob] = []

    def submit(self, job: AnalysisJob) -> str:
        self.jobs.append(job)
        return job.job_id


class ComputeNextRunTests(unittest.TestCase):
    def test_daily_at_time_rolls_to_next_day_when_past(self) -> None:
        now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
        nxt = compute_next_run_at(now, 24, "03:30", tz=timezone.utc)
        self.assertEqual(nxt, datetime(2026, 6, 5, 3, 30, tzinfo=timezone.utc))

    def test_daily_at_time_same_day_when_future(self) -> None:
        now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
        nxt = compute_next_run_at(now, 24, "15:00", tz=timezone.utc)
        self.assertEqual(nxt, datetime(2026, 6, 4, 15, 0, tzinfo=timezone.utc))

    def test_interval_only(self) -> None:
        now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
        nxt = compute_next_run_at(now, 6, None, tz=timezone.utc)
        self.assertEqual(nxt, datetime(2026, 6, 4, 16, 0, tzinfo=timezone.utc))

    def test_invalid_interval_raises(self) -> None:
        with self.assertRaises(AnalysisRunError):
            compute_next_run_at(datetime.now(timezone.utc), 0, None)


class ExecuteAnalysisJobTests(unittest.TestCase):
    def test_mock_all_scope_produces_proposal_and_operator_run(self) -> None:
        from kyoko.autonomy import update_autonomy_policy

        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            # ST2 decoupling: analysis surfaces issues; a proposal is authored only when the
            # section's autonomy mode is `autonomous`.
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            result = execute_analysis_job(
                db_path, AnalysisJob(analyzer="mock", scope="all", run_autonomy=False)
            )
            self.assertEqual(result["status"], "succeeded")
            self.assertTrue(result["proposal_ids"][0].startswith("proposal_mock_"))
            with connect(db_path) as connection:
                row = connection.execute(
                    "SELECT status, analyzed_since FROM operator_runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(row["status"], "succeeded")
            self.assertIsNone(row["analyzed_since"])

    def test_new_scope_skips_when_no_new_traces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            result = execute_analysis_job(
                db_path,
                AnalysisJob(
                    analyzer="mock", scope="new", since="2099-01-01T00:00:00Z", run_autonomy=False
                ),
            )
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["reason"], "no_new_traces")

    def test_new_scope_records_analyzed_since(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            result = execute_analysis_job(
                db_path,
                AnalysisJob(
                    analyzer="mock", scope="new", since="2000-01-01T00:00:00Z", run_autonomy=False
                ),
            )
            self.assertEqual(result["status"], "succeeded")
            with connect(db_path) as connection:
                row = connection.execute(
                    "SELECT analyzed_since FROM operator_runs ORDER BY started_at DESC LIMIT 1"
                ).fetchone()
            self.assertEqual(row["analyzed_since"], "2000-01-01T00:00:00Z")

    def test_unsupported_analyzer_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            with self.assertRaises(AnalysisRunError):
                execute_analysis_job(db_path, AnalysisJob(analyzer="not-a-real-analyzer"))

    def test_refresh_import_then_analyze(self) -> None:
        with TemporaryDirectory() as tmpdir:
            home = Path(tmpdir) / "home"
            home.mkdir()
            sessions_dir = _write_failed_openclaw_session(home)
            db_path = Path(tmpdir) / "imported.db"
            # mock analyzer over the freshly-imported openclaw traces (no live CLI needed).
            result = execute_analysis_job(
                db_path,
                AnalysisJob(
                    analyzer="mock",
                    scope="all",
                    refresh_import=True,
                    source_kind="openclaw_sessions",
                    source_path=str(sessions_dir),
                    run_autonomy=False,
                ),
            )
            self.assertEqual(result["status"], "succeeded", result.get("error"))
            count, _ = runs_newer_than(db_path, profile_id=result["profile_id"], since=None)
            self.assertGreaterEqual(count, 1)

    def test_since_scopes_evidence_bundle(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            full = build_evidence_bundle(db_path=db_path, consumer="t")
            scoped = build_evidence_bundle(
                db_path=db_path, since="2099-01-01T00:00:00Z", consumer="t"
            )
            self.assertGreaterEqual(full["summary"]["runs"], 1)
            self.assertEqual(scoped["summary"]["runs"], 0)


class SchedulerTickTests(unittest.TestCase):
    def _profile(self, db_path: Path) -> None:
        from kyoko.storage import initialize_database

        initialize_database(db_path)
        with connect(db_path) as connection:
            connection.execute(
                "INSERT INTO profiles VALUES ('p1','p1','/tmp','active',"
                "'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
            )

    def test_first_tick_arms_without_firing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "k.db"
            self._profile(db_path)
            schedule = create_analysis_schedule(
                db_path=db_path, analyzer_kind="openclaw", interval_hours=24, profile_id="p1"
            )
            self.assertIsNone(schedule["next_run_at"])
            runner = _RecordingRunner()
            scheduler = Scheduler(db_path, runner)
            fired = scheduler.tick(datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc))
            self.assertEqual(fired, [])
            self.assertEqual(runner.jobs, [])
            self.assertIsNotNone(get_analysis_schedule(db_path=db_path, schedule_id=schedule["id"])["next_run_at"])

    def test_due_schedule_fires_and_rearms(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "k.db"
            self._profile(db_path)
            schedule = create_analysis_schedule(
                db_path=db_path,
                analyzer_kind="openclaw",
                interval_hours=24,
                at_time="03:30",
                next_run_at="2026-06-04T03:30:00Z",
                profile_id="p1",
            )
            runner = _RecordingRunner()
            scheduler = Scheduler(db_path, runner)
            fired = scheduler.tick(datetime(2026, 6, 4, 4, 0, tzinfo=timezone.utc))
            self.assertEqual(len(fired), 1)
            self.assertEqual(len(runner.jobs), 1)
            job = runner.jobs[0]
            self.assertEqual(job.analyzer, "openclaw")
            self.assertEqual(job.scope, "new")
            self.assertEqual(job.schedule_id, schedule["id"])
            # Re-armed strictly after the fire instant (at_time is local, so the exact
            # UTC value depends on the host timezone — assert it advanced, not a constant).
            updated = get_analysis_schedule(db_path=db_path, schedule_id=schedule["id"])
            self.assertNotEqual(updated["next_run_at"], "2026-06-04T03:30:00Z")
            self.assertGreater(updated["next_run_at"], "2026-06-04T04:00:00Z")

    def test_disabled_schedule_does_not_fire(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "k.db"
            self._profile(db_path)
            schedule = create_analysis_schedule(
                db_path=db_path,
                analyzer_kind="hermes",
                interval_hours=24,
                next_run_at="2026-06-04T03:30:00Z",
                enabled=False,
                profile_id="p1",
            )
            runner = _RecordingRunner()
            fired = Scheduler(db_path, runner).tick(datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc))
            self.assertEqual(fired, [])

    def test_record_result_preserves_next_run_at(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "k.db"
            self._profile(db_path)
            schedule = create_analysis_schedule(
                db_path=db_path,
                analyzer_kind="openclaw",
                interval_hours=24,
                next_run_at="2026-06-05T03:30:00Z",
                profile_id="p1",
            )
            record_schedule_result(
                db_path=db_path,
                schedule_id=schedule["id"],
                last_run_at="2026-06-04T03:30:00Z",
                last_status="succeeded",
                watermark="2026-06-04T00:00:00Z",
            )
            updated = get_analysis_schedule(db_path=db_path, schedule_id=schedule["id"])
            self.assertEqual(updated["next_run_at"], "2026-06-05T03:30:00Z")
            self.assertEqual(updated["last_status"], "succeeded")
            self.assertEqual(updated["watermark"], "2026-06-04T00:00:00Z")


class _Server:
    def __init__(self, db_path: Path) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "_Server":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path: str) -> dict:
        with urlopen(Request(f"{self.base}{path}"), timeout=5) as response:
            return json.loads(response.read().decode())

    def post(self, path: str, payload: dict) -> tuple[int, dict]:
        request = Request(
            f"{self.base}{path}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())


class AnalysisApiTests(unittest.TestCase):
    def test_analyzers_availability(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            with _Server(db_path) as server:
                payload = server.get("/api/analysis/analyzers")
            kinds = {a["analyzer"] for a in payload["analyzers"]}
            self.assertEqual(kinds, {"ace", "codex", "claude", "openclaw", "hermes"})
            self.assertEqual(payload["schedulable"], ["openclaw", "hermes"])

    def test_run_then_list_runs(self) -> None:
        from kyoko.autonomy import update_autonomy_policy

        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            # Author a proposal so the run records a proposal id (gate #1 autonomous).
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            with _Server(db_path) as server:
                status, body = server.post(
                    "/api/analysis/run", {"analyzer": "mock", "scope": "all", "run_autonomy": False}
                )
                self.assertEqual(status, 202)
                self.assertEqual(body["status"], "queued")
                runs = server.get("/api/analysis/runs")["runs"]
            self.assertTrue(runs)
            self.assertTrue(all(r["status"] == "succeeded" for r in runs))
            # Decoupled flow records two operator runs (diagnosis + propose); only the
            # propose run carries a proposal id, and their started_at can tie — assert on
            # the proposal-bearing run rather than ordering.
            proposal_runs = [r for r in runs if r.get("proposal_id")]
            self.assertTrue(proposal_runs, "expected a propose run with a proposal id")
            self.assertTrue(proposal_runs[0]["proposal_id"].startswith("proposal_mock_"))

    def test_schedule_crud(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            with _Server(db_path) as server:
                status, created = server.post(
                    "/api/analysis/schedules/create",
                    {"analyzer": "openclaw", "source_path": "/tmp/x", "interval_hours": 24, "at_time": "03:30"},
                )
                self.assertEqual(status, 200)
                sid = created["schedule"]["id"]
                self.assertIsNotNone(created["schedule"]["next_run_at"])

                status, updated = server.post(
                    "/api/analysis/schedules/update", {"id": sid, "enabled": False, "interval_hours": 12}
                )
                self.assertEqual(status, 200)
                self.assertFalse(updated["schedule"]["enabled"])
                self.assertEqual(updated["schedule"]["interval_hours"], 12)

                listed = server.get("/api/analysis/schedules")["schedules"]
                self.assertEqual(len(listed), 1)

                status, deleted = server.post("/api/analysis/schedules/delete", {"id": sid})
                self.assertTrue(deleted["deleted"])

    def test_schedule_rejects_non_schedulable_analyzer(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            with _Server(db_path) as server:
                status, body = server.post("/api/analysis/schedules/create", {"analyzer": "codex"})
            self.assertEqual(status, 400)
            self.assertEqual(body["error"], "unschedulable_analyzer")


class AnalysisCliTests(unittest.TestCase):
    def _json_stdout(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, json.loads(buffer.getvalue())

    def test_analysis_run_mock(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            code, payload = self._json_stdout(
                ["analysis-run", "--db", str(db_path), "--analyzer", "mock", "--no-autonomy", "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "succeeded")

    def test_analysis_run_ace_requires_command(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["analysis-run", "--db", str(db_path), "--analyzer", "ace", "--json"])
            self.assertEqual(code, 1)

    def test_schedule_add_list_remove(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _demo_db(tmpdir)
            code, added = self._json_stdout(
                [
                    "analysis-schedule-add",
                    "--db", str(db_path),
                    "--analyzer", "openclaw",
                    "--source-path", "/tmp/x",
                    "--interval-hours", "24",
                    "--at-time", "03:30",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            sid = added["id"]
            self.assertEqual(added["analyzer_kind"], "openclaw")

            code, listed = self._json_stdout(["analysis-schedules", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(len(listed["schedules"]), 1)

            code, removed = self._json_stdout(
                ["analysis-schedule-remove", "--db", str(db_path), sid, "--json"]
            )
            self.assertEqual(code, 0)
            self.assertTrue(removed["deleted"])
            self.assertEqual(list_analysis_schedules(db_path), [])


if __name__ == "__main__":
    unittest.main()
