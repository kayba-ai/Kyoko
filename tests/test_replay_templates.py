import json
import os
import py_compile
import shutil
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kyoko.cli import main
from kyoko.evals import generate_evals_for_proposal
from kyoko.proposals import submit_learning_proposal
from kyoko.replay_servers import run_replay_server
from kyoko.replay_templates import (
    SUPPORTED_FRAMEWORKS,
    ReplayTemplateError,
    write_replay_server_template,
)
from kyoko.source_templates import SUPPORTED_SOURCE_FRAMEWORKS
from kyoko.storage import ingest_source_fixture
from tests.test_replay_servers import _free_port


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ReplayTemplateTests(unittest.TestCase):
    def test_write_template_generates_runnable_health_endpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "kyoko_replay_server.py"
            report = write_replay_server_template(
                output_path=output_path,
                framework="langgraph-python",
                profile_name="news-research",
            )
            py_compile.compile(str(output_path), doraise=True)
            port = _free_port()
            process = subprocess.Popen(
                [sys.executable, str(output_path), "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                health = _wait_for_health(port)
                replay_request = Request(
                    f"http://127.0.0.1:{port}/replay",
                    data=json.dumps(
                        {
                            "replay_run_id": "replay_001",
                            "side_effect_mode": "network_mocked",
                        }
                    ).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as replay_error:
                    urlopen(replay_request, timeout=5)
                replay_error.exception.close()
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

            self.assertEqual(report.output_path, output_path)
            self.assertEqual(health["profile"], "news-research")
            self.assertEqual(health["framework"], "langgraph-python")
            self.assertEqual(replay_error.exception.code, 501)

    def test_generated_template_completes_kyoko_replay_with_hook(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            output_path = tmp_path / "kyoko_replay_server.py"
            hook_path = tmp_path / "replay_hook.py"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            eval_report = generate_evals_for_proposal(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )
            write_replay_server_template(
                output_path=output_path,
                framework="generic-python",
                profile_name="news-research",
            )
            hook_path.write_text(
                f"""
import json
from pathlib import Path

REPLAY_SUCCESS = Path({str(REPLAY_SUCCESS)!r})


def replay(request):
    fixture = json.loads(REPLAY_SUCCESS.read_text())
    source_events = dict(fixture)
    source_events.pop("replay", None)
    return {{
        "status": "passed",
        "output_run_id": "run_research_topic_replay_001",
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {{
            "span_fetch_timeout_001": "span_fetch_retry_success_001",
        }},
        "source_events": source_events,
        "note": "generated template hook completed",
    }}
""",
                encoding="utf-8",
            )
            port = _free_port()
            env = os.environ.copy()
            env["KYOKO_REPLAY_HOOK"] = f"{hook_path}:replay"
            process = subprocess.Popen(
                [sys.executable, str(output_path), "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                _wait_for_health(port)
                report = run_replay_server(
                    db_path=db_path,
                    eval_spec_id=eval_report.eval_spec_ids[0],
                    server_url=f"http://127.0.0.1:{port}",
                    run_eval_after=True,
                )
            finally:
                _stop_process(process)

            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(report.completion.output_run_id, "run_research_topic_replay_001")
            self.assertEqual(report.eval_run.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")
            self.assertEqual(
                report.response["replay"]["target_map"]["span_fetch_timeout_001"],
                "span_fetch_retry_success_001",
            )

    def test_template_refuses_overwrite_without_force(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "kyoko_replay_server.py"
            write_replay_server_template(output_path=output_path)

            with self.assertRaisesRegex(ReplayTemplateError, "exists"):
                write_replay_server_template(output_path=output_path)

            report = write_replay_server_template(output_path=output_path, force=True)
            self.assertTrue(report.wrote)

    def test_replay_templates_cover_source_frameworks(self) -> None:
        self.assertEqual(set(SUPPORTED_FRAMEWORKS), set(SUPPORTED_SOURCE_FRAMEWORKS))

    def test_openai_agents_and_crewai_replay_templates_compile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            for framework in ("openai-agents-python", "crewai-python"):
                output_path = Path(tmpdir) / f"{framework}.py"
                report = write_replay_server_template(
                    output_path=output_path,
                    framework=framework,
                    profile_name="agent-team",
                )
                py_compile.compile(str(output_path), doraise=True)
                template = output_path.read_text(encoding="utf-8")

                self.assertEqual(report.framework, framework)
                self.assertIn(f'FRAMEWORK = "{framework}"', template)
                self.assertIn("KYOKO_REPLAY_HOOK", template)

    def test_generated_typescript_template_completes_kyoko_replay_with_hook(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            output_path = tmp_path / "kyoko_replay_server.mjs"
            hook_path = tmp_path / "replay_hook.mjs"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            eval_report = generate_evals_for_proposal(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )
            report = write_replay_server_template(
                output_path=output_path,
                framework="ai-sdk-typescript",
                profile_name="ai-sdk-news",
            )
            check = subprocess.run(
                [node, "--check", str(output_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            hook_path.write_text(
                f"""
import fs from "node:fs";

const REPLAY_SUCCESS = {json.dumps(str(REPLAY_SUCCESS))};

export async function replay(request) {{
  const fixture = JSON.parse(fs.readFileSync(REPLAY_SUCCESS, "utf8"));
  delete fixture.replay;
  return {{
    status: "passed",
    output_run_id: "run_research_topic_replay_001",
    actual_side_effect_mode: request.side_effect_mode,
    target_map: {{
      span_fetch_timeout_001: "span_fetch_retry_success_001"
    }},
    source_events: fixture,
    note: "generated Node template hook completed"
  }};
}}
""",
                encoding="utf-8",
            )
            port = _free_port()
            env = os.environ.copy()
            env["KYOKO_REPLAY_HOOK"] = f"{hook_path}:replay"
            process = subprocess.Popen(
                [node, str(output_path), "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            try:
                health = _wait_for_health(port)
                replay_report = run_replay_server(
                    db_path=db_path,
                    eval_spec_id=eval_report.eval_spec_ids[0],
                    server_url=f"http://127.0.0.1:{port}",
                    run_eval_after=True,
                )
            finally:
                _stop_process(process)

            self.assertEqual(report.framework, "ai-sdk-typescript")
            self.assertEqual(health["framework"], "ai-sdk-typescript")
            self.assertEqual(replay_report.completion.status, "passed")
            self.assertEqual(replay_report.eval_run.status, "passed")
            self.assertEqual(replay_report.eval_run.promoted_trust_level, "L2_regression")

    def test_cli_writes_template_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "kyoko_replay_server.py"

            from io import StringIO
            from contextlib import redirect_stdout

            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "replay-server-template",
                        str(output_path),
                        "--framework",
                        "hermes-python",
                        "--profile-name",
                        "hermes-news",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["framework"], "hermes-python")
            self.assertEqual(payload["profile_name"], "hermes-news")
            self.assertTrue(output_path.exists())


def _wait_for_health(port: int) -> dict:
    deadline = time.time() + 5
    last_error = None
    while time.time() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                return json.loads(response.read().decode("utf-8"))
        except URLError as exc:
            last_error = exc
            time.sleep(0.1)
    raise AssertionError(f"health endpoint did not start: {last_error}")


def _stop_process(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
