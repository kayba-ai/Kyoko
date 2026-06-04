import io
import json
import os
import py_compile
import shutil
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.cli import main
from kyoko.framework_smoke import (
    run_installed_framework_improve_smoke,
    run_installed_framework_replay_smoke,
    run_installed_framework_source_smoke,
)
from kyoko.improve_smoke import run_generated_improve_smoke
from kyoko.integration_smoke import run_replay_server_smoke, run_source_adapter_smoke
from kyoko.replay_templates import write_replay_server_template
from kyoko.source_templates import write_source_adapter_template
from tests.test_replay_servers import _free_port
from tests.test_source_templates import _source_hook, _typescript_source_hook


class IntegrationSmokeTests(unittest.TestCase):
    def test_source_adapter_smoke_runs_adapter_and_ingests_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            adapter_path = tmp_path / "kyoko_source_adapter.py"
            hook_path = tmp_path / "source_hook.py"
            output_dir = tmp_path / "smoke"

            write_source_adapter_template(
                output_path=adapter_path,
                framework="langgraph-python",
                profile_name="news-research",
            )
            hook_path.write_text(_source_hook(), encoding="utf-8")

            report = run_source_adapter_smoke(
                db_path=db_path,
                adapter_path=adapter_path,
                hook=f"{hook_path}:collect",
                output_dir=output_dir,
                profile_id="profile_smoke_news",
                source_id="source_smoke_langgraph",
                agent_id="agent_smoke_researcher",
                python_executable=Path(sys.executable),
            )

            self.assertEqual(report.profile_id, "profile_smoke_news")
            self.assertEqual(report.ingested_counts["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 1)
            self.assertTrue(report.source_events_path.exists())
            self.assertTrue(report.stdout_path.exists())
            self.assertTrue(report.stderr_path.exists())

    def test_source_adapter_smoke_runs_node_adapter_and_ingests_output(self) -> None:
        if shutil.which("node") is None:
            self.skipTest("node is not installed")
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            adapter_path = tmp_path / "kyoko_source_adapter.mjs"
            hook_path = tmp_path / "source_hook.mjs"
            output_dir = tmp_path / "smoke"

            write_source_adapter_template(
                output_path=adapter_path,
                framework="ai-sdk-typescript",
                profile_name="ai-sdk-news",
            )
            hook_path.write_text(_typescript_source_hook(), encoding="utf-8")

            report = run_source_adapter_smoke(
                db_path=db_path,
                adapter_path=adapter_path,
                hook=f"{hook_path}:collect",
                output_dir=output_dir,
                profile_id="profile_smoke_ai_sdk",
                source_id="source_smoke_ai_sdk",
                agent_id="agent_smoke_planner",
            )

            self.assertEqual(report.profile_id, "profile_smoke_ai_sdk")
            self.assertEqual(report.ingested_counts["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 1)

    def test_replay_server_smoke_starts_health_checks_and_stops_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            server_path = tmp_path / "kyoko_replay_server.py"
            output_dir = tmp_path / "smoke"
            port = _free_port()

            write_replay_server_template(
                output_path=server_path,
                framework="generic-python",
                profile_name="news-research",
            )
            py_compile.compile(str(server_path), doraise=True)

            report = run_replay_server_smoke(
                command=[sys.executable, str(server_path), "--port", str(port)],
                server_url=f"http://127.0.0.1:{port}",
                output_dir=output_dir,
                startup_timeout_seconds=5,
            )

            self.assertTrue(report.started)
            self.assertTrue(report.healthy)
            self.assertTrue(report.stopped)
            self.assertEqual(report.health["response"]["profile"], "news-research")
            self.assertIsNone(report.replay_request)
            self.assertFalse(report.replay_ok)
            self.assertTrue(report.stdout_path.exists())
            self.assertTrue(report.stderr_path.exists())
            self.assertIn("stdout", report.logs)

    def test_replay_server_smoke_can_run_bounded_replay_request(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            server_path = tmp_path / "kyoko_replay_server.py"
            hook_path = tmp_path / "replay_hook.py"
            output_dir = tmp_path / "smoke"
            port = _free_port()

            write_replay_server_template(
                output_path=server_path,
                framework="generic-python",
                profile_name="news-research",
            )
            hook_path.write_text(
                """
import sys


def replay(request):
    if __name__ not in sys.modules:
        raise KeyError(__name__)
    return {
        "status": "passed",
        "output_run_id": "run_smoke_replay_001",
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {"span_source": "span_replay"},
        "executed_agent": False,
        "note": "bounded smoke replay",
    }
""",
                encoding="utf-8",
            )

            report = run_replay_server_smoke(
                command=[sys.executable, str(server_path), "--port", str(port)],
                server_url=f"http://127.0.0.1:{port}",
                output_dir=output_dir,
                replay_hook=f"{hook_path}:replay",
                run_replay=True,
                startup_timeout_seconds=5,
            )

            self.assertTrue(report.started)
            self.assertTrue(report.healthy)
            self.assertTrue(report.stopped)
            self.assertTrue(report.replay_ok)
            self.assertEqual(report.replay_request["side_effect_mode"], "network_mocked")
            self.assertEqual(report.replay_response["output_run_id"], "run_smoke_replay_001")
            self.assertEqual(
                report.replay_response["target_map"]["span_source"],
                "span_replay",
            )

    def test_cli_source_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            adapter_path = tmp_path / "kyoko_source_adapter.py"
            hook_path = tmp_path / "source_hook.py"

            write_source_adapter_template(output_path=adapter_path)
            hook_path.write_text(_source_hook(), encoding="utf-8")

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "source",
                        "--db",
                        str(db_path),
                        str(adapter_path),
                        "--hook",
                        f"{hook_path}:collect",
                        "--python-executable",
                        sys.executable,
                        "--profile-id",
                        "profile_cli_smoke",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["kind"], "source_adapter")
            self.assertEqual(payload["profile_id"], "profile_cli_smoke")
            self.assertEqual(payload["status"]["counts"]["runs"], 1)

    def test_installed_framework_source_smoke_runs_adapter_and_ingests_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-source"
            _write_fake_langgraph_package(output_dir)

            report = run_installed_framework_source_smoke(
                db_path=tmp_path / "kyoko.db",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            payload = json.loads(report.source_smoke.source_events_path.read_text(encoding="utf-8"))

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "langgraph-python")
            self.assertEqual(report.framework_package, "langgraph")
            self.assertEqual(report.framework_version, "9.9.0")
            self.assertEqual(report.source_smoke.profile_id, "profile_installed_langgraph_smoke")
            self.assertEqual(report.status["counts"]["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 2)
            self.assertTrue(payload["runs"][0]["metadata_json"]["installed_framework_invoked"])
            self.assertEqual(payload["runs"][0]["metadata_json"]["graph_result"]["result"], "timeout")

    def test_installed_framework_source_smoke_accepts_relative_output_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cwd = Path.cwd()
            try:
                os.chdir(tmp_path)
                output_dir = Path("framework-source")
                _write_fake_langgraph_package(output_dir)

                report = run_installed_framework_source_smoke(
                    db_path=Path("kyoko.db"),
                    output_dir=output_dir,
                    python_executable=Path(sys.executable),
                    timeout_seconds=10,
                )
            finally:
                os.chdir(cwd)

            self.assertTrue(report.passed)
            self.assertTrue(report.source_adapter_path.is_absolute())
            self.assertTrue(report.source_smoke.adapter_path.is_absolute())
            self.assertEqual(report.source_smoke.status["counts"]["spans"], 2)

    def test_installed_pydantic_ai_source_smoke_runs_adapter_and_ingests_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-source"
            _write_fake_pydantic_ai_package(output_dir)

            report = run_installed_framework_source_smoke(
                db_path=tmp_path / "kyoko.db",
                framework="pydantic-ai-python",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            payload = json.loads(report.source_smoke.source_events_path.read_text(encoding="utf-8"))

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "pydantic-ai-python")
            self.assertEqual(report.framework_package, "pydantic-ai")
            self.assertEqual(report.framework_version, "9.8.0")
            self.assertEqual(report.source_smoke.profile_id, "profile_installed_pydantic_ai_smoke")
            self.assertEqual(report.status["counts"]["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 2)
            self.assertTrue(payload["runs"][0]["metadata_json"]["installed_framework_invoked"])
            self.assertTrue(payload["runs"][0]["metadata_json"]["agent_result"]["tool_called"])

    def test_installed_openai_agents_source_smoke_runs_adapter_and_ingests_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-source"
            _write_fake_openai_agents_package(output_dir)

            report = run_installed_framework_source_smoke(
                db_path=tmp_path / "kyoko.db",
                framework="openai-agents-python",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            payload = json.loads(report.source_smoke.source_events_path.read_text(encoding="utf-8"))

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "openai-agents-python")
            self.assertEqual(report.framework_package, "openai-agents")
            self.assertEqual(report.framework_version, "9.7.0")
            self.assertEqual(report.source_smoke.profile_id, "profile_installed_openai_agents_smoke")
            self.assertEqual(report.status["counts"]["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 3)
            self.assertEqual(report.status["counts"]["handoffs"], 1)
            self.assertTrue(payload["runs"][0]["metadata_json"]["installed_framework_invoked"])
            self.assertTrue(payload["runs"][0]["metadata_json"]["agent_result"]["handoff_invoked"])
            self.assertTrue(payload["runs"][0]["metadata_json"]["agent_result"]["tool_called"])

    def test_installed_crewai_source_smoke_runs_adapter_and_ingests_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-source"
            _write_fake_crewai_package(output_dir)

            report = run_installed_framework_source_smoke(
                db_path=tmp_path / "kyoko.db",
                framework="crewai-python",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            payload = json.loads(report.source_smoke.source_events_path.read_text(encoding="utf-8"))

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "crewai-python")
            self.assertEqual(report.framework_package, "crewai")
            self.assertEqual(report.framework_version, "9.6.0")
            self.assertEqual(report.source_smoke.profile_id, "profile_installed_crewai_smoke")
            self.assertEqual(report.status["counts"]["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 3)
            self.assertEqual(report.status["counts"]["tasks"], 2)
            self.assertEqual(report.status["counts"]["handoffs"], 1)
            crew_result = payload["runs"][0]["metadata_json"]["crew_result"]
            self.assertTrue(payload["runs"][0]["metadata_json"]["installed_framework_invoked"])
            self.assertTrue(crew_result["crew_kickoff_invoked"])
            self.assertTrue(crew_result["local_llm_invoked"])
            self.assertTrue(crew_result["tool_run_invoked"])

    def test_cli_framework_source_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-source"
            _write_fake_langgraph_package(output_dir)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "framework-source",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--output-dir",
                        str(output_dir),
                        "--python-executable",
                        sys.executable,
                        "--timeout",
                        "10",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertTrue(payload["passed"])
            self.assertTrue(payload["installed_framework_invoked"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertEqual(payload["kind"], "installed_framework_source_smoke")
            self.assertEqual(payload["framework"], "langgraph-python")
            self.assertEqual(payload["framework_version"], "9.9.0")
            self.assertEqual(payload["source_smoke"]["status"]["counts"]["spans"], 2)

    def test_cli_pydantic_ai_framework_source_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-source"
            _write_fake_pydantic_ai_package(output_dir)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "framework-source",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--framework",
                        "pydantic-ai-python",
                        "--output-dir",
                        str(output_dir),
                        "--python-executable",
                        sys.executable,
                        "--timeout",
                        "10",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertTrue(payload["passed"])
            self.assertTrue(payload["installed_framework_invoked"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertEqual(payload["kind"], "installed_framework_source_smoke")
            self.assertEqual(payload["framework"], "pydantic-ai-python")
            self.assertEqual(payload["framework_version"], "9.8.0")
            self.assertEqual(payload["source_smoke"]["status"]["counts"]["spans"], 2)

    def test_installed_framework_replay_smoke_runs_server_and_hook(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-replay"
            _write_fake_langgraph_package(output_dir)

            report = run_installed_framework_replay_smoke(
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            replay = report.replay_smoke.replay_response["replay"]

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "langgraph-python")
            self.assertEqual(report.framework_version, "9.9.0")
            self.assertTrue(report.replay_smoke.healthy)
            self.assertTrue(report.replay_smoke.stopped)
            self.assertTrue(report.replay_smoke.replay_ok)
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["output_run_id"], "run_installed_langgraph_replay_001")

    def test_installed_framework_replay_smoke_accepts_relative_output_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            cwd = Path.cwd()
            try:
                os.chdir(tmp_path)
                output_dir = Path("framework-replay")
                _write_fake_langgraph_package(output_dir)

                report = run_installed_framework_replay_smoke(
                    output_dir=output_dir,
                    python_executable=Path(sys.executable),
                    timeout_seconds=10,
                )
            finally:
                os.chdir(cwd)

            self.assertTrue(report.passed)
            self.assertTrue(report.replay_server_path.is_absolute())
            self.assertTrue(report.replay_smoke.replay_ok)
            self.assertEqual(
                report.replay_smoke.replay_response["replay"]["output_run_id"],
                "run_installed_langgraph_replay_001",
            )

    def test_installed_pydantic_ai_replay_smoke_runs_server_and_hook(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-replay"
            _write_fake_pydantic_ai_package(output_dir)

            report = run_installed_framework_replay_smoke(
                framework="pydantic-ai-python",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            replay = report.replay_smoke.replay_response["replay"]

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "pydantic-ai-python")
            self.assertEqual(report.framework_version, "9.8.0")
            self.assertTrue(report.replay_smoke.healthy)
            self.assertTrue(report.replay_smoke.stopped)
            self.assertTrue(report.replay_smoke.replay_ok)
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["output_run_id"], "run_installed_pydantic_ai_replay_001")

    def test_installed_openai_agents_replay_smoke_runs_server_and_hook(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-replay"
            _write_fake_openai_agents_package(output_dir)

            report = run_installed_framework_replay_smoke(
                framework="openai-agents-python",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            replay = report.replay_smoke.replay_response["replay"]
            response = report.replay_smoke.replay_response

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "openai-agents-python")
            self.assertEqual(report.framework_version, "9.7.0")
            self.assertTrue(report.replay_smoke.healthy)
            self.assertTrue(report.replay_smoke.stopped)
            self.assertTrue(report.replay_smoke.replay_ok)
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["output_run_id"], "run_installed_openai_agents_replay_001")
            self.assertTrue(response["runs"][0]["metadata_json"]["agent_result"]["handoff_invoked"])
            self.assertTrue(response["runs"][0]["metadata_json"]["agent_result"]["tool_called"])

    def test_installed_crewai_replay_smoke_runs_server_and_hook(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-replay"
            _write_fake_crewai_package(output_dir)

            report = run_installed_framework_replay_smoke(
                framework="crewai-python",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            replay = report.replay_smoke.replay_response["replay"]
            response = report.replay_smoke.replay_response

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_invoked)
            self.assertEqual(report.framework, "crewai-python")
            self.assertEqual(report.framework_version, "9.6.0")
            self.assertTrue(report.replay_smoke.healthy)
            self.assertTrue(report.replay_smoke.stopped)
            self.assertTrue(report.replay_smoke.replay_ok)
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["output_run_id"], "run_installed_crewai_replay_001")
            crew_result = response["runs"][0]["metadata_json"]["crew_result"]
            self.assertTrue(crew_result["crew_kickoff_invoked"])
            self.assertTrue(crew_result["local_llm_invoked"])
            self.assertTrue(crew_result["tool_run_invoked"])

    def test_installed_framework_improve_smoke_runs_source_replay_and_autonomy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-improve"
            _write_fake_langgraph_package(output_dir)

            report = run_installed_framework_improve_smoke(
                db_path=tmp_path / "kyoko.db",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )

            self.assertTrue(report.passed)
            self.assertTrue(report.installed_framework_source_invoked)
            self.assertTrue(report.installed_framework_replay_invoked)
            self.assertEqual(report.framework, "langgraph-python")
            self.assertEqual(report.framework_version, "9.9.0")
            self.assertEqual(report.source_smoke.profile_id, "profile_installed_langgraph_smoke")
            self.assertEqual(
                report.improve.proposal_id,
                "proposal_mock_span_installed_langgraph_fetch_001",
            )
            self.assertEqual(
                report.improve.generated_eval_spec_ids,
                ("eval_proposal_mock_span_installed_langgraph_fetch_001_1",),
            )
            self.assertEqual(report.improve.replay_runs[0]["status"], "passed")
            self.assertEqual(report.improve.replay_runs[0]["output_run_id"], "run_installed_langgraph_replay_001")
            self.assertEqual(report.improve.replay_runs[0]["eval_run"]["status"], "passed")
            self.assertEqual(report.improve.autonomy.decisions[0].action, "applied")

    def test_cli_framework_replay_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-replay"
            _write_fake_langgraph_package(output_dir)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "framework-replay",
                        "--output-dir",
                        str(output_dir),
                        "--python-executable",
                        sys.executable,
                        "--timeout",
                        "10",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertTrue(payload["passed"])
            self.assertTrue(payload["installed_framework_invoked"])
            self.assertTrue(payload["replay_smoke"]["replay_ok"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertEqual(payload["kind"], "installed_framework_replay_smoke")
            self.assertEqual(payload["framework"], "langgraph-python")
            self.assertEqual(payload["framework_version"], "9.9.0")

    def test_cli_framework_improve_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            output_dir = tmp_path / "framework-improve"
            _write_fake_langgraph_package(output_dir)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "framework-improve",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--output-dir",
                        str(output_dir),
                        "--python-executable",
                        sys.executable,
                        "--timeout",
                        "10",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertTrue(payload["passed"])
            self.assertTrue(payload["installed_framework_invoked"])
            self.assertTrue(payload["installed_framework_source_invoked"])
            self.assertTrue(payload["installed_framework_replay_invoked"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertEqual(payload["kind"], "installed_framework_improve_smoke")
            self.assertEqual(payload["framework"], "langgraph-python")
            self.assertEqual(payload["framework_version"], "9.9.0")
            self.assertEqual(
                payload["improve"]["proposal_id"],
                "proposal_mock_span_installed_langgraph_fetch_001",
            )
            self.assertEqual(payload["improve"]["replay_runs"][0]["status"], "passed")

    def test_cli_replay_server_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            server_path = tmp_path / "kyoko_replay_server.py"
            hook_path = tmp_path / "replay_hook.py"
            output_dir = tmp_path / "smoke"
            port = _free_port()

            write_replay_server_template(output_path=server_path)
            hook_path.write_text(
                """
def replay(request):
    return {
        "status": "passed",
        "output_run_id": "run_cli_smoke_replay_001",
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {},
    }
""",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "replay-server",
                        "--command",
                        f"{sys.executable} {server_path} --port {port}",
                        "--server-url",
                        f"http://127.0.0.1:{port}",
                        "--output-dir",
                        str(output_dir),
                        "--startup-timeout",
                        "5",
                        "--hook",
                        f"{hook_path}:replay",
                        "--run-replay",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["kind"], "replay_server")
            self.assertTrue(payload["healthy"])
            self.assertTrue(payload["replay_ok"])
            self.assertEqual(payload["replay_response"]["output_run_id"], "run_cli_smoke_replay_001")
            self.assertTrue(payload["stopped"])
            self.assertEqual(payload["health"]["response"]["profile"], "kyoko-agent")

    def test_generated_improve_smoke_runs_source_replay_and_autonomy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            report = run_generated_improve_smoke(
                db_path=tmp_path / "kyoko.db",
                output_dir=tmp_path / "improve-smoke",
                timeout_seconds=10,
            )

            self.assertTrue(report.passed)
            self.assertEqual(report.framework, "generic-python")
            self.assertEqual(report.source_smoke.profile_id, "profile_framework_improve_smoke")
            self.assertEqual(report.improve.proposal_id, "proposal_mock_span_framework_fetch_timeout_001")
            self.assertEqual(
                report.improve.generated_eval_spec_ids,
                ("eval_proposal_mock_span_framework_fetch_timeout_001_1",),
            )
            self.assertEqual(report.improve.replay_runs[0]["status"], "passed")
            self.assertEqual(report.improve.replay_runs[0]["eval_run"]["status"], "passed")
            self.assertEqual(report.improve.autonomy.decisions[0].action, "applied")

    def test_cli_improve_integration_smoke_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "integration-smoke",
                        "improve",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--output-dir",
                        str(tmp_path / "improve-smoke"),
                        "--timeout",
                        "10",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["kind"], "improve_smoke")
            self.assertEqual(payload["improve"]["proposal_id"], "proposal_mock_span_framework_fetch_timeout_001")
            self.assertEqual(payload["improve"]["replay_runs"][0]["status"], "passed")


def _write_fake_langgraph_package(root: Path) -> None:
    _write_fake_langgraph_package_at(root)
    _write_fake_langgraph_package_at(root / "source")
    _write_fake_langgraph_package_at(root / "replay")


def _write_fake_langgraph_package_at(root: Path) -> None:
    package_dir = root / "langgraph"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text('__version__ = "9.9.0"\n', encoding="utf-8")
    (package_dir / "graph.py").write_text(
        """
START = "__start__"
END = "__end__"


class StateGraph:
    def __init__(self, state_type):
        self.nodes = {}
        self.edges = []

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_edge(self, source, target):
        self.edges.append((source, target))

    def compile(self):
        return CompiledGraph(self.nodes, self.edges)


class CompiledGraph:
    def __init__(self, nodes, edges):
        self.nodes = nodes
        self.edges = edges

    def invoke(self, state):
        current = dict(state)
        node = self._target_for(START)
        while node != END:
            result = self.nodes[node](current)
            if result:
                current.update(result)
            node = self._target_for(node)
        return current

    def _target_for(self, source):
        for edge_source, edge_target in self.edges:
            if edge_source == source:
                return edge_target
        raise RuntimeError("missing edge: " + source)
""".lstrip(),
        encoding="utf-8",
    )
    dist_info = root / "langgraph-9.9.0.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: langgraph\nVersion: 9.9.0\n",
        encoding="utf-8",
    )


def _write_fake_pydantic_ai_package(root: Path) -> None:
    _write_fake_pydantic_ai_package_at(root)
    _write_fake_pydantic_ai_package_at(root / "source")
    _write_fake_pydantic_ai_package_at(root / "replay")


def _write_fake_pydantic_ai_package_at(root: Path) -> None:
    package_dir = root / "pydantic_ai"
    models_dir = package_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text(
        """
__version__ = "9.8.0"


class Agent:
    def __init__(self, model, system_prompt=()):
        self.model = model
        self.system_prompt = system_prompt
        self.tools = {}

    def tool_plain(self, fn):
        self.tools[fn.__name__] = fn
        return fn

    def run_sync(self, prompt):
        tool = self.tools["fetch_source"]
        value = tool("framework-smoke")
        return AgentRunResult('{"fetch_source":"' + value + '"}')


class AgentRunResult:
    def __init__(self, output):
        self.output = output

    def all_messages(self):
        return ["ToolCallPart(tool_name='fetch_source')", "ToolReturnPart(content='timeout')"]

    def usage(self):
        return {"input_tokens": 1, "output_tokens": 1}
""".lstrip(),
        encoding="utf-8",
    )
    (models_dir / "__init__.py").write_text("", encoding="utf-8")
    (models_dir / "test.py").write_text(
        """
class TestModel:
    pass
""".lstrip(),
        encoding="utf-8",
    )
    dist_info = root / "pydantic_ai-9.8.0.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: pydantic-ai\nVersion: 9.8.0\n",
        encoding="utf-8",
    )


def _write_fake_openai_agents_package(root: Path) -> None:
    _write_fake_openai_agents_package_at(root)
    _write_fake_openai_agents_package_at(root / "source")
    _write_fake_openai_agents_package_at(root / "replay")


def _write_fake_openai_agents_package_at(root: Path) -> None:
    agents_dir = root / "agents"
    models_dir = agents_dir / "models"
    responses_dir = root / "openai" / "types" / "responses"
    models_dir.mkdir(parents=True, exist_ok=True)
    responses_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "__init__.py").write_text(
        """
from __future__ import annotations

import asyncio
from types import SimpleNamespace


__version__ = "9.7.0"


class Model:
    pass


class ModelProvider:
    def get_model(self, model_name):
        raise NotImplementedError


class RunConfig:
    def __init__(self, model_provider=None, tracing_disabled=False):
        self.model_provider = model_provider
        self.tracing_disabled = tracing_disabled


class Agent:
    def __init__(self, name, handoff_description=None, tools=None, instructions=None, handoffs=None, **kwargs):
        self.name = name
        self.handoff_description = handoff_description
        self.tools = list(tools or [])
        self.instructions = instructions
        self.handoffs = list(handoffs or [])


class FunctionTool:
    def __init__(self, fn):
        self.fn = fn
        self.name = fn.__name__


class Handoff:
    def __init__(self, agent):
        self.agent = agent
        self.agent_name = agent.name
        self.tool_name = "transfer_to_" + agent.name
        self.name = self.tool_name


class HandoffCallItem:
    def __init__(self, raw_item):
        self.raw_item = raw_item


class HandoffOutputItem:
    def __init__(self, raw_item):
        self.raw_item = raw_item


class ToolCallItem:
    def __init__(self, raw_item):
        self.raw_item = raw_item


class ToolCallOutputItem:
    def __init__(self, raw_item):
        self.raw_item = raw_item


class MessageOutputItem:
    def __init__(self, raw_item):
        self.raw_item = raw_item


class RunResult:
    def __init__(self, final_output, new_items, last_agent):
        self.final_output = final_output
        self.new_items = new_items
        self.last_agent = last_agent


class Runner:
    @staticmethod
    def run_sync(starting_agent, input, *, max_turns=10, run_config=None, **kwargs):
        model = run_config.model_provider.get_model(None)
        handoff_response = asyncio.run(
            model.get_response(
                starting_agent.instructions,
                input,
                None,
                [],
                None,
                starting_agent.handoffs,
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        )
        handoff_call = handoff_response.output[0]
        target_agent = starting_agent.handoffs[0].agent
        handoff_output = {
            "call_id": handoff_call.call_id,
            "output": '{"assistant": "researcher"}',
            "type": "function_call_output",
        }
        tool_response = asyncio.run(
            model.get_response(
                target_agent.instructions,
                input,
                None,
                target_agent.tools,
                None,
                [],
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        )
        tool_call = tool_response.output[0]
        tool = target_agent.tools[0]
        tool_output = {
            "call_id": tool_call.call_id,
            "output": tool.fn("framework-smoke"),
            "type": "function_call_output",
        }
        final_response = asyncio.run(
            model.get_response(
                target_agent.instructions,
                input,
                None,
                target_agent.tools,
                None,
                [],
                None,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            )
        )
        final_message = final_response.output[0]
        final_output = final_message.content[0].text
        return RunResult(
            final_output,
            [
                HandoffCallItem(handoff_call),
                HandoffOutputItem(handoff_output),
                ToolCallItem(tool_call),
                ToolCallOutputItem(tool_output),
                MessageOutputItem(final_message),
            ],
            target_agent,
        )


def function_tool(func=None, **kwargs):
    def decorate(fn):
        return FunctionTool(fn)

    if func is None:
        return decorate
    return decorate(func)


def handoff(agent, **kwargs):
    return Handoff(agent)


def set_tracing_disabled(value):
    return None
""".lstrip(),
        encoding="utf-8",
    )
    (agents_dir / "items.py").write_text(
        """
class ModelResponse:
    def __init__(self, output, usage, response_id, request_id=None):
        self.output = output
        self.usage = usage
        self.response_id = response_id
        self.request_id = request_id
""".lstrip(),
        encoding="utf-8",
    )
    (agents_dir / "usage.py").write_text(
        """
class Usage:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
""".lstrip(),
        encoding="utf-8",
    )
    (models_dir / "__init__.py").write_text("", encoding="utf-8")
    (models_dir / "interface.py").write_text(
        """
from agents import Model, ModelProvider
""".lstrip(),
        encoding="utf-8",
    )
    (root / "openai" / "__init__.py").write_text("", encoding="utf-8")
    (root / "openai" / "types" / "__init__.py").write_text("", encoding="utf-8")
    (responses_dir / "__init__.py").write_text(
        """
class ResponseFunctionToolCall:
    def __init__(self, arguments, call_id, name, type, **kwargs):
        self.arguments = arguments
        self.call_id = call_id
        self.name = name
        self.type = type

    def __repr__(self):
        return "ResponseFunctionToolCall(name=%r, arguments=%r)" % (self.name, self.arguments)


class ResponseOutputText:
    def __init__(self, annotations, text, type, **kwargs):
        self.annotations = annotations
        self.text = text
        self.type = type


class ResponseOutputMessage:
    def __init__(self, id, content, role, status, type, **kwargs):
        self.id = id
        self.content = content
        self.role = role
        self.status = status
        self.type = type
""".lstrip(),
        encoding="utf-8",
    )
    dist_info = root / "openai_agents-9.7.0.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: openai-agents\nVersion: 9.7.0\n",
        encoding="utf-8",
    )


def _write_fake_crewai_package(root: Path) -> None:
    _write_fake_crewai_package_at(root)
    _write_fake_crewai_package_at(root / "source")
    _write_fake_crewai_package_at(root / "replay")


def _write_fake_crewai_package_at(root: Path) -> None:
    package_dir = root / "crewai"
    llms_dir = package_dir / "llms"
    tools_dir = package_dir / "tools"
    tracing_dir = package_dir / "events" / "listeners" / "tracing"
    llms_dir.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)
    tracing_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text(
        """
__version__ = "9.6.0"


class Process:
    sequential = "sequential"


class Agent:
    def __init__(
        self,
        *,
        role,
        goal,
        backstory,
        llm=None,
        tools=None,
        verbose=False,
        max_iter=1,
        **kwargs,
    ):
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self.llm = llm
        self.tools = list(tools or [])
        self.verbose = verbose
        self.max_iter = max_iter


class Task:
    def __init__(self, *, description, expected_output, agent=None, tools=None, **kwargs):
        self.description = description
        self.expected_output = expected_output
        self.agent = agent
        self.tools = list(tools or [])


class TaskOutput:
    def __init__(self, description, raw, agent):
        self.description = description
        self.raw = raw
        self.agent = agent


class CrewOutput:
    def __init__(self, raw, tasks_output):
        self.raw = raw
        self.tasks_output = tasks_output

    def __str__(self):
        return self.raw


class Crew:
    def __init__(
        self,
        *,
        agents,
        tasks,
        process=None,
        verbose=False,
        memory=False,
        tracing=False,
        **kwargs,
    ):
        self.agents = list(agents)
        self.tasks = list(tasks)
        self.process = process
        self.verbose = verbose
        self.memory = memory
        self.tracing = tracing

    def kickoff(self, inputs=None):
        task = self.tasks[0]
        agent = task.agent or self.agents[0]
        raw = agent.llm.call(
            [{"role": "user", "content": task.description}],
            tools=task.tools,
            callbacks=None,
            available_functions={tool.name: tool.run for tool in task.tools},
            from_task=task,
            from_agent=agent,
            response_model=None,
        )
        return CrewOutput(str(raw), [TaskOutput(task.description, str(raw), agent.role)])
""".lstrip(),
        encoding="utf-8",
    )
    (llms_dir / "__init__.py").write_text("", encoding="utf-8")
    (llms_dir / "base_llm.py").write_text(
        """
class BaseLLM:
    def __init__(self, *, model, provider="openai", **kwargs):
        self.model = model
        self.provider = provider

    def call(self, *args, **kwargs):
        raise NotImplementedError
""".lstrip(),
        encoding="utf-8",
    )
    (tools_dir / "__init__.py").write_text(
        """
class Tool:
    def __init__(self, name, fn):
        self.name = name
        self.fn = fn

    def run(self, *args, **kwargs):
        return self.fn(*args, **kwargs)


def tool(*args, **kwargs):
    name = args[0] if args and isinstance(args[0], str) else None

    def decorate(fn):
        return Tool(name or fn.__name__, fn)

    if args and callable(args[0]):
        return decorate(args[0])
    return decorate
""".lstrip(),
        encoding="utf-8",
    )
    for init_dir in [
        package_dir / "events",
        package_dir / "events" / "listeners",
        tracing_dir,
    ]:
        (init_dir / "__init__.py").write_text("", encoding="utf-8")
    (tracing_dir / "utils.py").write_text(
        """
def set_suppress_tracing_messages(value):
    return None
""".lstrip(),
        encoding="utf-8",
    )
    dist_info = root / "crewai-9.6.0.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: crewai\nVersion: 9.6.0\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
