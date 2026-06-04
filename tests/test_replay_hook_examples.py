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
from urllib.error import URLError
from urllib.request import urlopen

from kyoko.checks import generate_checks_for_proposal
from kyoko.proposals import submit_learning_proposal
from kyoko.replay_servers import run_replay_server
from kyoko.replay_templates import write_replay_server_template
from kyoko.storage import ingest_source_fixture
from tests.test_replay_servers import _free_port


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "replay-hooks"
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ReplayHookExampleTests(unittest.TestCase):
    def test_python_replay_hook_examples_run_through_generated_servers(self) -> None:
        cases = (
            ("langgraph-python", "langgraph_replay_hook.py"),
            ("pydantic-ai-python", "pydantic_ai_replay_hook.py"),
            ("openai-agents-python", "openai_agents_replay_hook.py"),
            ("crewai-python", "crewai_replay_hook.py"),
            ("hermes-python", "hermes_replay_hook.py"),
            ("openclaw-python", "openclaw_replay_hook.py"),
        )
        for framework, hook_name in cases:
            with self.subTest(framework=framework), TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                db_path = tmp_path / "kyoko.db"
                server_path = tmp_path / "kyoko_replay_server.py"
                hook_path = EXAMPLES / hook_name

                py_compile.compile(str(hook_path), doraise=True)
                check_spec_id = _prepare_check(db_path)
                write_replay_server_template(
                    output_path=server_path,
                    framework=framework,
                    profile_name="news-research",
                )
                port = _free_port()
                process = subprocess.Popen(
                    [sys.executable, str(server_path), "--port", str(port)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**_clean_env(), "KYOKO_REPLAY_HOOK": f"{hook_path}:replay"},
                )
                try:
                    _wait_for_health(port)
                    report = run_replay_server(
                        db_path=db_path,
                        check_spec_id=check_spec_id,
                        server_url=f"http://127.0.0.1:{port}",
                        run_check_after=True,
                    )
                finally:
                    _stop_process(process)

                self.assertEqual(report.completion.status, "passed")
                self.assertEqual(
                    report.completion.result["target_map"]["span_fetch_timeout_001"],
                    "span_fetch_retry_success_001",
                )
                self.assertEqual(report.check_run.status, "passed")
                self.assertEqual(report.check_run.promoted_trust_level, "L2_regression")

    def test_ai_sdk_replay_hook_example_runs_through_generated_node_server(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            server_path = tmp_path / "kyoko_replay_server.mjs"
            hook_path = EXAMPLES / "ai_sdk_replay_hook.mjs"

            check = subprocess.run(
                [node, "--check", str(hook_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            check_spec_id = _prepare_check(db_path)
            write_replay_server_template(
                output_path=server_path,
                framework="ai-sdk-typescript",
                profile_name="ai-sdk-news",
            )
            port = _free_port()
            process = subprocess.Popen(
                [node, str(server_path), "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={**_clean_env(), "KYOKO_REPLAY_HOOK": f"{hook_path}:replay"},
            )
            try:
                _wait_for_health(port)
                report = run_replay_server(
                    db_path=db_path,
                    check_spec_id=check_spec_id,
                    server_url=f"http://127.0.0.1:{port}",
                    run_check_after=True,
                )
            finally:
                _stop_process(process)

            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(report.check_run.status, "passed")
            self.assertEqual(report.check_run.promoted_trust_level, "L2_regression")


def _prepare_check(db_path: Path) -> str:
    ingest_source_fixture(db_path, FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    check_report = generate_checks_for_proposal(
        db_path=db_path,
        proposal_id="proposal_context_timeout_001",
    )
    return check_report.check_spec_ids[0]


def _clean_env() -> dict[str, str]:
    return os.environ.copy()


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
