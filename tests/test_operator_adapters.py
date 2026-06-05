import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from kyoko.operator_adapters import (
    OperatorAdapterError,
    list_operator_adapters,
    register_operator_adapter,
    run_registered_operator_adapter,
)
from kyoko.operator_presets import bootstrap_operator_adapters, list_operator_presets
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
HERMES_OPERATOR_COMMAND = ROOT / "tests/fixtures/hermes_operator_command.py"
OPENCLAW_OPERATOR_COMMAND = ROOT / "tests/fixtures/openclaw_operator_command.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class OperatorAdapterTests(unittest.TestCase):
    def test_register_and_run_operator_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"
            ingest_source_fixture(db_path, FIXTURE)

            register = register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                operator_kind="generic",
                command=[sys.executable, str(OPERATOR_COMMAND)],
                output_dir=output_dir,
            )
            adapters = list_operator_adapters(db_path)
            report = run_registered_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                schema_path=SCHEMA,
            )
            status = get_database_status(db_path)

            self.assertEqual(register.adapter_id, "fixture_operator")
            self.assertEqual(register.profile_id, "profile_news_research_001")
            self.assertEqual(adapters[0]["command"], [sys.executable, str(OPERATOR_COMMAND)])
            self.assertTrue(adapters[0]["enabled"])
            self.assertEqual(report.operator, "fixture_operator")
            self.assertEqual(len(report.new_issue_ids), 1)
            self.assertTrue(report.persisted)
            self.assertTrue(report.evidence_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertEqual(status.counts["operator_adapters"], 1)
            self.assertEqual(status.counts["operator_runs"], 1)
            # Analysis is diagnosis-only — it authors no proposal.
            self.assertEqual(status.counts["learning_proposals"], 0)
            self.assertEqual(status.counts["skills"], 1)

    def test_disabled_operator_adapter_is_not_runnable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                command=[sys.executable, str(OPERATOR_COMMAND)],
                enabled=False,
            )

            with self.assertRaisesRegex(OperatorAdapterError, "disabled"):
                run_registered_operator_adapter(
                    db_path=db_path,
                    adapter_id="fixture_operator",
                    schema_path=SCHEMA,
                )

    def test_bootstrap_operator_presets_registers_available_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"
            ingest_source_fixture(db_path, FIXTURE)

            with patch("kyoko.operator_presets.shutil.which", return_value="/usr/local/bin/codex"):
                report = bootstrap_operator_adapters(
                    db_path=db_path,
                    target="codex",
                    output_dir=output_dir,
                    timeout_seconds=300,
                )

            adapters = list_operator_adapters(db_path)
            self.assertEqual(len(report.registered), 1)
            self.assertEqual(report.registered[0].adapter_id, "codex")
            self.assertEqual(report.registered[0].operator_kind, "codex")
            self.assertEqual(report.registered[0].timeout_seconds, 300)
            self.assertEqual(adapters[0]["id"], "codex")
            self.assertEqual(adapters[0]["command"][0:2], ["codex", "exec"])
            self.assertIn("--sandbox", adapters[0]["command"])
            self.assertEqual(adapters[0]["metadata"]["executable"], "/usr/local/bin/codex")

    def test_bootstrap_all_skips_missing_presets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with patch("kyoko.operator_presets.shutil.which", return_value=None):
                report = bootstrap_operator_adapters(db_path=db_path)

            self.assertEqual(report.registered, ())
            self.assertEqual(
                {item["adapter_id"] for item in report.skipped},
                {"codex", "claude", "hermes", "openclaw"},
            )
            self.assertEqual(list_operator_adapters(db_path), [])

    def test_bootstrap_openclaw_preset_uses_prompt_argument_command(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            def fake_which(command: str):
                return "/usr/local/bin/openclaw" if command == "openclaw" else None

            with patch("kyoko.operator_presets.shutil.which", side_effect=fake_which):
                report = bootstrap_operator_adapters(db_path=db_path, target="openclaw")

            adapters = list_operator_adapters(db_path)
            self.assertEqual(len(report.registered), 1)
            self.assertEqual(report.registered[0].adapter_id, "openclaw")
            self.assertEqual(report.registered[0].operator_kind, "openclaw")
            self.assertEqual(
                adapters[0]["command"][0:7],
                ["openclaw", "agent", "--agent", "main", "--local", "--message", "{prompt}"],
            )
            self.assertEqual(adapters[0]["metadata"]["executable"], "/usr/local/bin/openclaw")

    def test_bootstrap_openclaw_preset_runs_local_message_operator(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            fake_openclaw = root / "openclaw"
            fake_openclaw.write_text(
                f"#!{sys.executable}\n"
                "import runpy\n"
                f"runpy.run_path({str(OPENCLAW_OPERATOR_COMMAND)!r}, run_name='__main__')\n",
                encoding="utf-8",
            )
            fake_openclaw.chmod(fake_openclaw.stat().st_mode | 0o111)
            ingest_source_fixture(db_path, FIXTURE)

            with patch.dict(os.environ, {"PATH": f"{root}{os.pathsep}{os.environ.get('PATH', '')}"}):
                bootstrap = bootstrap_operator_adapters(
                    db_path=db_path,
                    target="openclaw",
                    output_dir=output_dir,
                )
                report = run_registered_operator_adapter(
                    db_path=db_path,
                    adapter_id="openclaw",
                    schema_path=SCHEMA,
                )

            adapters = list_operator_adapters(db_path)
            status = get_database_status(db_path)
            self.assertEqual(len(bootstrap.registered), 1)
            self.assertEqual(bootstrap.registered[0].adapter_id, "openclaw")
            self.assertEqual(
                adapters[0]["command"],
                [
                    "openclaw",
                    "agent",
                    "--agent",
                    "main",
                    "--local",
                    "--message",
                    "{prompt}",
                    "--timeout",
                    "120",
                ],
            )
            self.assertEqual(adapters[0]["metadata"]["executable"], str(fake_openclaw))
            self.assertEqual(report.operator, "openclaw")
            self.assertEqual(len(report.new_issue_ids), 1)
            self.assertEqual(status.counts["operator_runs"], 1)
            self.assertEqual(status.counts["learning_proposals"], 0)
            self.assertEqual(status.counts["skills"], 1)
            self.assertIn("OpenClaw local", report.raw_output_path.read_text(encoding="utf-8"))

    def test_bootstrap_hermes_preset_runs_one_shot_prompt_argument_operator(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            fake_hermes = root / "hermes"
            fake_hermes.write_text(
                f"#!{sys.executable}\n"
                "import runpy\n"
                f"runpy.run_path({str(HERMES_OPERATOR_COMMAND)!r}, run_name='__main__')\n",
                encoding="utf-8",
            )
            fake_hermes.chmod(fake_hermes.stat().st_mode | 0o111)
            ingest_source_fixture(db_path, FIXTURE)

            with patch.dict(os.environ, {"PATH": f"{root}{os.pathsep}{os.environ.get('PATH', '')}"}):
                bootstrap = bootstrap_operator_adapters(
                    db_path=db_path,
                    target="hermes",
                    output_dir=output_dir,
                )
                report = run_registered_operator_adapter(
                    db_path=db_path,
                    adapter_id="hermes",
                    schema_path=SCHEMA,
                )

            adapters = list_operator_adapters(db_path)
            status = get_database_status(db_path)
            self.assertEqual(len(bootstrap.registered), 1)
            self.assertEqual(bootstrap.registered[0].adapter_id, "hermes")
            self.assertEqual(adapters[0]["command"], ["hermes", "-z", "{prompt}"])
            self.assertEqual(adapters[0]["metadata"]["executable"], str(fake_hermes))
            self.assertEqual(report.operator, "hermes")
            self.assertEqual(len(report.new_issue_ids), 1)
            self.assertEqual(status.counts["operator_runs"], 1)
            self.assertEqual(status.counts["learning_proposals"], 0)
            self.assertEqual(status.counts["skills"], 1)
            self.assertIn("Hermes one-shot", report.raw_output_path.read_text(encoding="utf-8"))

    def test_operator_presets_are_listable(self) -> None:
        presets = {preset["adapter_id"]: preset for preset in list_operator_presets()}

        self.assertIn("codex", presets)
        self.assertIn("claude", presets)
        self.assertIn("hermes", presets)
        self.assertIn("openclaw", presets)
        self.assertEqual(presets["claude"]["operator_kind"], "claude")
        self.assertIn("--allowedTools", presets["claude"]["command"])
        self.assertEqual(presets["hermes"]["command"], ["hermes", "-z", "{prompt}"])
        self.assertIn("{prompt}", presets["openclaw"]["command"])


if __name__ == "__main__":
    unittest.main()
