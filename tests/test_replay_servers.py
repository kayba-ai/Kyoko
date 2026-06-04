import json
import socket
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest

from kyoko.details import get_replay_detail
from kyoko.evals import generate_evals_for_proposal
from kyoko.proposals import submit_learning_proposal
from kyoko.replay_adapters import (
    register_replay_adapter,
    registered_replay_server_logs,
    registered_replay_server_status,
    run_registered_replay_adapter,
    start_registered_replay_server_adapter,
    stop_registered_replay_server_adapter,
)
from kyoko.replay_servers import (
    ReplayServerError,
    check_replay_server_health,
    normalize_replay_server_url,
    run_managed_replay_server,
    run_replay_server,
)
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ReplayServerTests(unittest.TestCase):
    def test_replay_server_health_and_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            with RunningReplayServer() as server:
                health = check_replay_server_health(server_url=server.base_url)
                report = run_replay_server(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    server_url=server.base_url,
                    run_eval_after=True,
                )
            status = get_database_status(db_path)

            self.assertTrue(health.ok)
            self.assertEqual(report.replay_run_id, "replay_eval_proposal_context_timeout_001_1_001")
            self.assertEqual(report.completion.output_run_id, "run_research_topic_replay_001")
            self.assertEqual(report.eval_run.status, "passed")
            self.assertEqual(report.request["schema_version"], "kyoko.replay_server_request.v1")
            self.assertEqual(report.request["side_effect_mode"], "network_mocked")
            self.assertEqual(report.request["idempotency_key"], report.replay_run_id)
            self.assertEqual(report.response["replay"]["idempotency_key"], report.replay_run_id)
            self.assertEqual(status.counts["runs"], 2)
            self.assertEqual(status.counts["eval_runs"], 1)

    def test_remote_replay_server_url_requires_explicit_opt_in(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            with self.assertRaisesRegex(ReplayServerError, "remote_replay_server_requires_opt_in"):
                check_replay_server_health(server_url="http://example.com:61200")
            with self.assertRaisesRegex(ReplayServerError, "remote_replay_server_requires_opt_in"):
                run_replay_server(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    server_url="http://example.com:61200",
                    check_health=False,
                )

            self.assertEqual(
                normalize_replay_server_url(
                    "http://example.com:61200",
                    allow_remote_server=True,
                ),
                "http://example.com:61200",
            )
            status = get_database_status(db_path)
            self.assertEqual(status.counts["replay_runs"], 0)

    def test_replay_server_health_side_effect_modes_must_support_request(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            with RunningReplayServer(side_effect_modes=["none"]) as server:
                with self.assertRaisesRegex(
                    ReplayServerError,
                    "replay_server_side_effect_mode_unsupported:network_mocked:none",
                ):
                    run_replay_server(
                        db_path=db_path,
                        eval_spec_id=eval_spec_id,
                        server_url=server.base_url,
                    )
                self.assertEqual(server.replay_requests, [])

            detail = get_replay_detail(
                db_path=db_path,
                replay_run_id="replay_eval_proposal_context_timeout_001_1_001",
            )
            self.assertEqual(detail["summary"]["status"], "errored")
            self.assertEqual(
                detail["replay_run"]["result"]["error"],
                "replay_server_side_effect_mode_unsupported:network_mocked:none",
            )

    def test_replay_server_health_capabilities_must_include_replay_when_advertised(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            with RunningReplayServer(capabilities=["trace"]) as server:
                with self.assertRaisesRegex(
                    ReplayServerError,
                    "replay_server_capability_unsupported:replay:trace",
                ):
                    run_replay_server(
                        db_path=db_path,
                        eval_spec_id=eval_spec_id,
                        server_url=server.base_url,
                    )
                self.assertEqual(server.replay_requests, [])

            detail = get_replay_detail(
                db_path=db_path,
                replay_run_id="replay_eval_proposal_context_timeout_001_1_001",
            )
            self.assertEqual(detail["summary"]["status"], "errored")
            self.assertEqual(
                detail["replay_run"]["result"]["error"],
                "replay_server_capability_unsupported:replay:trace",
            )

    def test_http_replay_request_respects_profile_redaction_policy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _add_sensitive_span_attribute(db_path)

            with RunningReplayServer() as server:
                report = run_replay_server(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    server_url=server.base_url,
                )

            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(len(server.replay_requests), 1)
            payload = server.replay_requests[0]
            source_spans = {
                span["id"]: span for span in payload["input"]["source_spans"]
            }
            handoff = payload["input"]["handoffs"][0]
            redaction = payload["kyoko_request"]["redaction"]

            self.assertEqual(
                source_spans["span_fetch_timeout_001"]["input_ref"],
                "[REDACTED:payload_ref]",
            )
            self.assertEqual(
                source_spans["span_fetch_timeout_001"]["attributes"]["authorization"],
                "[REDACTED:secret]",
            )
            self.assertEqual(handoff["payload_ref"], "[REDACTED:payload_ref]")
            self.assertEqual(redaction["consumer"], "replay:http_server")
            self.assertGreater(redaction["redacted_count"], 0)

    def test_http_replay_server_can_be_registered_as_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            with RunningReplayServer() as server:
                register = register_replay_adapter(
                    db_path=db_path,
                    adapter_id="http_replay",
                    name="HTTP replay",
                    server_url=server.base_url,
                )
                report = run_registered_replay_adapter(
                    db_path=db_path,
                    adapter_id="http_replay",
                    eval_spec_id=eval_spec_id,
                    run_eval_after=True,
                )

            self.assertEqual(register.adapter_kind, "http_server")
            self.assertEqual(register.server_url, server.base_url)
            self.assertEqual(report.server_url, server.base_url)
            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")

    def test_managed_replay_server_command_runs_and_captures_logs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "managed-server"
            eval_spec_id = _create_eval_spec(db_path)
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"

            report = run_managed_replay_server(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                command=_fixture_replay_server_command(port),
                server_url=server_url,
                output_dir=output_dir,
                startup_timeout_seconds=5,
                run_eval_after=True,
            )

            self.assertEqual(report.server_url, server_url)
            self.assertEqual(report.completion.output_run_id, "run_research_topic_replay_001")
            self.assertEqual(report.eval_run.status, "passed")
            self.assertEqual(report.command, tuple(_fixture_replay_server_command(port)))
            self.assertTrue(report.stdout_path.exists())
            self.assertTrue(report.stderr_path.exists())
            self.assertIsNotNone(report.exit_code)
            detail = get_replay_detail(db_path=db_path, replay_run_id=report.replay_run_id)
            artifacts = {artifact["kind"]: artifact for artifact in detail["artifacts"]}
            self.assertIn("replay_server_stdout", artifacts)
            self.assertIn("kyoko fixture replay server listening", artifacts["replay_server_stdout"]["preview"])

    def test_managed_replay_server_can_be_registered_as_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "managed-adapter"
            eval_spec_id = _create_eval_spec(db_path)
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            command = _fixture_replay_server_command(port)

            register = register_replay_adapter(
                db_path=db_path,
                adapter_id="managed_http_replay",
                name="Managed HTTP replay",
                command=command,
                server_url=server_url,
                output_dir=output_dir,
                startup_timeout_seconds=5,
            )
            report = run_registered_replay_adapter(
                db_path=db_path,
                adapter_id="managed_http_replay",
                eval_spec_id=eval_spec_id,
                run_eval_after=True,
            )

            self.assertEqual(register.adapter_kind, "managed_http_server")
            self.assertEqual(register.command, tuple(command))
            self.assertEqual(register.server_url, server_url)
            self.assertEqual(report.server_url, server_url)
            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")
            self.assertTrue(report.stdout_path.exists())

    def test_registered_replay_server_can_start_status_and_stop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "server-process"
            _create_eval_spec(db_path)
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            register_replay_adapter(
                db_path=db_path,
                adapter_id="persistent_http_replay",
                name="Persistent HTTP replay",
                command=_fixture_replay_server_command(port),
                server_url=server_url,
                output_dir=output_dir,
                startup_timeout_seconds=5,
            )

            start = start_registered_replay_server_adapter(
                db_path=db_path,
                adapter_id="persistent_http_replay",
            )
            try:
                status = registered_replay_server_status(
                    db_path=db_path,
                    adapter_id="persistent_http_replay",
                )
                logs = registered_replay_server_logs(
                    db_path=db_path,
                    adapter_id="persistent_http_replay",
                    max_bytes=2000,
                )
            finally:
                stop = stop_registered_replay_server_adapter(
                    db_path=db_path,
                    adapter_id="persistent_http_replay",
                )

            self.assertTrue(start.started)
            self.assertTrue(start.running)
            self.assertTrue(start.healthy)
            self.assertTrue(status.running)
            self.assertTrue(status.healthy)
            self.assertEqual(status.pid, start.pid)
            self.assertIn("kyoko fixture replay server listening", logs.stdout)
            self.assertEqual(logs.max_bytes, 2000)
            self.assertTrue(stop.stopped)
            self.assertFalse(stop.running)
            self.assertTrue(start.state_path.exists())

    def test_running_managed_adapter_reuses_persistent_server_for_replay(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "server-process"
            eval_spec_id = _create_eval_spec(db_path)
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            register_replay_adapter(
                db_path=db_path,
                adapter_id="persistent_http_replay",
                name="Persistent HTTP replay",
                command=_fixture_replay_server_command(port),
                server_url=server_url,
                output_dir=output_dir,
                startup_timeout_seconds=5,
            )
            start = start_registered_replay_server_adapter(
                db_path=db_path,
                adapter_id="persistent_http_replay",
            )
            try:
                report = run_registered_replay_adapter(
                    db_path=db_path,
                    adapter_id="persistent_http_replay",
                    eval_spec_id=eval_spec_id,
                    run_eval_after=True,
                )
                status = registered_replay_server_status(
                    db_path=db_path,
                    adapter_id="persistent_http_replay",
                )
            finally:
                stop_registered_replay_server_adapter(
                    db_path=db_path,
                    adapter_id="persistent_http_replay",
                )

            self.assertEqual(report.server_url, server_url)
            self.assertFalse(hasattr(report, "stdout_path"))
            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")
            self.assertEqual(status.pid, start.pid)
            self.assertTrue(status.running)


class RunningReplayServer:
    def __init__(self, *, side_effect_modes=None, capabilities=None) -> None:
        self.side_effect_modes = side_effect_modes or ["network_mocked", "none"]
        self.capabilities = capabilities or ["trace", "replay"]
        self.replay_requests: list[dict] = []

    def __enter__(self) -> "RunningReplayServer":
        handler = make_handler(
            side_effect_modes=self.side_effect_modes,
            capabilities=self.capabilities,
            replay_requests=self.replay_requests,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def make_handler(
    *,
    side_effect_modes=None,
    capabilities=None,
    replay_requests=None,
) -> type[BaseHTTPRequestHandler]:
    selected_side_effect_modes = side_effect_modes or ["network_mocked", "none"]
    selected_capabilities = capabilities or ["trace", "replay"]
    received_replay_requests = replay_requests if replay_requests is not None else []

    class ReplayHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self.send_error(404)
                return
            self._send_json(
                {
                    "ok": True,
                    "profile": "news-research-agent",
                    "framework": "fixture",
                    "side_effect_modes": selected_side_effect_modes,
                    "capabilities": selected_capabilities,
                }
            )

        def do_POST(self) -> None:
            if self.path != "/replay":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            received_replay_requests.append(payload)
            fixture = json.loads(REPLAY_SUCCESS.read_text())
            fixture["replay"]["replay_run_id"] = payload["replay_run_id"]
            fixture["replay"]["idempotency_key"] = payload["idempotency_key"]
            self._send_json(fixture)

        def log_message(self, format: str, *args) -> None:
            return

        def _send_json(self, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ReplayHandler


def _create_eval_spec(db_path: Path) -> str:
    ingest_source_fixture(db_path, FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    report = generate_evals_for_proposal(
        db_path=db_path,
        proposal_id="proposal_context_timeout_001",
    )
    return report.eval_spec_ids[0]


def _add_sensitive_span_attribute(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            UPDATE spans
            SET attributes_json = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    {
                        "authorization": "Bearer replay-server-secret-token",
                        "safe_attribute": "kept",
                    },
                    sort_keys=True,
                ),
                "span_fetch_timeout_001",
            ),
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _fixture_replay_server_command(port: int) -> list[str]:
    return [sys.executable, "-m", "kyoko.fixture_replay_server", "--port", str(port)]


if __name__ == "__main__":
    unittest.main()
