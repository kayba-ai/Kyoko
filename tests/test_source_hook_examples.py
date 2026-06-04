import py_compile
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.integration_smoke import run_source_adapter_smoke
from kyoko.source_templates import write_source_adapter_template


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "source-hooks"


class SourceHookExampleTests(unittest.TestCase):
    def test_python_source_hook_examples_run_through_generated_adapters(self) -> None:
        cases = (
            (
                "langgraph-python",
                "langgraph_source_hook.py",
                {
                    "runs": 1,
                    "spans": 2,
                    "agent_identities": 2,
                    "workflow_nodes": 2,
                    "handoffs": 1,
                    "timeline_events": 1,
                },
            ),
            (
                "pydantic-ai-python",
                "pydantic_ai_source_hook.py",
                {
                    "runs": 1,
                    "spans": 2,
                    "agent_identities": 1,
                    "workflow_nodes": 1,
                    "handoffs": 0,
                    "timeline_events": 1,
                },
            ),
            (
                "openai-agents-python",
                "openai_agents_source_hook.py",
                {
                    "runs": 1,
                    "spans": 3,
                    "agent_identities": 2,
                    "workflow_nodes": 2,
                    "handoffs": 1,
                    "timeline_events": 1,
                },
            ),
            (
                "crewai-python",
                "crewai_source_hook.py",
                {
                    "runs": 1,
                    "spans": 3,
                    "agent_identities": 2,
                    "workflow_nodes": 2,
                    "queues": 1,
                    "tasks": 2,
                    "task_attempts": 1,
                    "handoffs": 1,
                    "timeline_events": 2,
                },
            ),
            (
                "hermes-python",
                "hermes_source_hook.py",
                {
                    "runs": 1,
                    "spans": 2,
                    "agent_identities": 2,
                    "workflow_nodes": 2,
                    "queues": 1,
                    "tasks": 1,
                    "task_attempts": 1,
                    "handoffs": 1,
                    "timeline_events": 2,
                },
            ),
            (
                "openclaw-python",
                "openclaw_source_hook.py",
                {
                    "runs": 1,
                    "spans": 4,
                    "agent_identities": 2,
                    "workflow_nodes": 2,
                    "tasks": 1,
                    "handoffs": 1,
                    "timeline_events": 2,
                },
            )
        )
        for framework, hook_name, expected_counts in cases:
            with self.subTest(framework=framework), TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                db_path = tmp_path / "kyoko.db"
                adapter_path = tmp_path / "kyoko_source_adapter.py"
                output_dir = tmp_path / "smoke"
                hook_path = EXAMPLES / hook_name
                suffix = framework.replace("-", "_")

                py_compile.compile(str(hook_path), doraise=True)
                write_source_adapter_template(
                    output_path=adapter_path,
                    framework=framework,
                    profile_name=f"{framework}-example",
                )

                report = run_source_adapter_smoke(
                    db_path=db_path,
                    adapter_path=adapter_path,
                    hook=f"{hook_path}:collect",
                    output_dir=output_dir,
                    profile_id=f"profile_example_{suffix}",
                    profile_name=f"{framework} Example",
                    source_id=f"source_example_{suffix}",
                    agent_id=f"agent_example_{suffix}",
                    agent_name=f"{framework}-agent",
                )

                self.assertEqual(report.profile_id, f"profile_example_{suffix}")
                for key, value in expected_counts.items():
                    self.assertEqual(report.status["counts"][key], value, key)
                self.assertGreater(report.status["counts"]["payload_blobs"], 0)

    def test_ai_sdk_source_hook_example_runs_through_generated_node_adapter(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            adapter_path = tmp_path / "kyoko_source_adapter.mjs"
            output_dir = tmp_path / "smoke"
            hook_path = EXAMPLES / "ai_sdk_source_hook.mjs"

            check = subprocess.run(
                [node, "--check", str(hook_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            write_source_adapter_template(
                output_path=adapter_path,
                framework="ai-sdk-typescript",
                profile_name="ai-sdk-news",
            )

            report = run_source_adapter_smoke(
                db_path=db_path,
                adapter_path=adapter_path,
                hook=f"{hook_path}:collect",
                output_dir=output_dir,
                profile_id="profile_example_ai_sdk",
                profile_name="AI SDK Example",
                source_id="source_example_ai_sdk",
                agent_id="agent_example_ai_sdk",
                agent_name="ai-sdk-news",
            )

            self.assertEqual(report.profile_id, "profile_example_ai_sdk")
            self.assertEqual(report.status["counts"]["runs"], 1)
            self.assertEqual(report.status["counts"]["spans"], 2)
            self.assertEqual(report.status["counts"]["timeline_events"], 1)


if __name__ == "__main__":
    unittest.main()
