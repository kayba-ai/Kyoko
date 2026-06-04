from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from kyoko.project_bootstrap import bootstrap_project
from kyoko.storage import get_database_status


class ProjectBootstrapTests(unittest.TestCase):
    def test_bootstrap_project_writes_local_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "agent-project"

            with patch("kyoko.operator_presets.shutil.which", return_value="/usr/local/bin/codex"):
                report = bootstrap_project(
                    project_dir=project_dir,
                    profile_name="news-research",
                    source_framework="langgraph-python",
                    replay_framework="hermes-python",
                    mcp_target="codex",
                )

            status = get_database_status(report.db_path)

            self.assertEqual(report.project_dir, project_dir.resolve())
            self.assertTrue(status.initialized)
            self.assertTrue(report.source_adapter.output_path.exists())
            self.assertTrue(report.replay_server.output_path.exists())
            self.assertTrue(report.mcp_config_path.exists())
            self.assertTrue(report.next_steps_path.exists())
            self.assertEqual(report.source_adapter.framework, "langgraph-python")
            self.assertEqual(report.replay_server.framework, "hermes-python")
            self.assertEqual(report.mcp_config["target"], "codex")
            self.assertEqual(
                {registered.adapter_id for registered in report.operator_bootstrap.registered},
                {"codex", "claude", "hermes", "openclaw"},
            )
            next_steps = report.next_steps_path.read_text()
            self.assertIn("No live operator model", next_steps)
            self.assertIn("doctor --db", next_steps)
            self.assertIn("--safe-smokes", next_steps)
            self.assertIn("native ACE prepare", next_steps)
            self.assertIn("profile-next", next_steps)
            self.assertIn("discover-sources", next_steps)
            self.assertIn("integration-smoke replay-server", next_steps)
            self.assertIn("--run-replay", next_steps)
            self.assertIn("replay-adapter-register", next_steps)
            self.assertIn("import-hermes-kanban", next_steps)
            self.assertIn("import-openclaw-sessions", next_steps)
            self.assertIn("doctor_safe_smokes", report.commands)
            self.assertNotIn("profiles", report.commands)
            self.assertIn("profile_next", report.commands)
            self.assertIn("discover_sources", report.commands)
            self.assertIn("replay_smoke", report.commands)
            self.assertIn("replay_adapter_register", report.commands)
            self.assertIn("import_hermes_kanban", report.commands)
            self.assertIn("import_openclaw_sessions", report.commands)
            self.assertIn("--safe-smokes", report.commands["doctor_safe_smokes"])
            self.assertIn("--smoke-output-dir", report.commands["doctor_safe_smokes"])
            self.assertIn(".kyoko/smoke/doctor", report.commands["doctor_safe_smokes"])
            self.assertIn("--profile-id profile_news_research", report.commands["discover_sources"])
            self.assertIn("profile_news_research_replay", report.commands["replay_adapter_register"])
            self.assertIn("--server-url http://127.0.0.1:61200", report.commands["replay_adapter_register"])
            self.assertIn("KYOKO_REPLAY_HOOK=/absolute/path/to/replay_hook.py:replay", report.commands["replay_adapter_register"])
            self.assertIn("integration-smoke replay-server", report.commands["replay_smoke"])
            self.assertIn("--hook /absolute/path/to/replay_hook.py:replay", report.commands["replay_smoke"])
            self.assertIn("--run-replay", report.commands["replay_smoke"])
            self.assertIn(".kyoko/smoke/replay", report.commands["replay_smoke"])
            self.assertIn("--profile-id profile_news_research", report.commands["import_openclaw_sessions"])
            self.assertIn("--root-path", report.commands["import_hermes_kanban"])

    def test_bootstrap_project_can_skip_operator_registration(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report = bootstrap_project(
                project_dir=Path(tmpdir),
                bootstrap_operators=False,
            )

            self.assertEqual(report.operator_bootstrap.registered, ())
            self.assertEqual(report.operator_bootstrap.skipped, ())

    def test_bootstrap_project_uses_node_source_adapter_for_typescript_frameworks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report = bootstrap_project(
                project_dir=Path(tmpdir),
                source_framework="ai-sdk-typescript",
                bootstrap_operators=False,
            )

            self.assertEqual(report.source_adapter.framework, "ai-sdk-typescript")
            self.assertEqual(report.source_adapter.output_path.name, "kyoko_source_adapter.mjs")
            self.assertTrue(report.source_adapter.output_path.exists())
            next_steps = report.next_steps_path.read_text()
            self.assertIn("node", next_steps)
            self.assertIn("source_hook.mjs:collect", next_steps)

    def test_bootstrap_project_uses_node_replay_server_for_typescript_frameworks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            report = bootstrap_project(
                project_dir=Path(tmpdir),
                replay_framework="ai-sdk-typescript",
                bootstrap_operators=False,
            )

            self.assertEqual(report.replay_server.framework, "ai-sdk-typescript")
            self.assertEqual(report.replay_server.output_path.name, "kyoko_replay_server.mjs")
            self.assertTrue(report.replay_server.output_path.exists())
            self.assertIn("node", report.commands["replay"])
            self.assertIn("replay_hook.mjs:replay", report.commands["replay"])
            self.assertIn("node", report.commands["replay_adapter_register"])
            self.assertIn("node", report.commands["replay_smoke"])
            self.assertIn("replay_hook.mjs:replay", report.commands["replay_smoke"])
            self.assertIn("--run-replay", report.commands["replay_smoke"])

    def test_bootstrap_project_quotes_paths_in_commands(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "agent project with spaces"
            report = bootstrap_project(
                project_dir=project_dir,
                profile_name="news research",
                bootstrap_operators=False,
            )

            self.assertIn("'", report.commands["doctor"])
            self.assertIn("agent project with spaces", report.commands["doctor"])
            self.assertIn("'", report.commands["doctor_safe_smokes"])
            self.assertIn("agent project with spaces", report.commands["doctor_safe_smokes"])
            self.assertIn("--profile-name 'news research'", report.commands["discover_sources"])
            self.assertIn("--root-path", report.commands["discover_sources"])
            self.assertIn("agent project with spaces", report.commands["replay_adapter_register"])
            self.assertIn("'news research replay'", report.commands["replay_adapter_register"])
            self.assertIn("agent project with spaces", report.commands["replay_smoke"])
            self.assertIn("--output-dir", report.commands["replay_smoke"])
            self.assertIn("--hook /absolute/path/to/replay_hook.py:replay", report.commands["replay_smoke"])
            self.assertIn("--profile-name 'news research'", report.commands["import_hermes_kanban"])
            self.assertIn("--root-path", report.commands["import_openclaw_sessions"])


if __name__ == "__main__":
    unittest.main()
