import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from kyoko.operator_adapters import register_operator_adapter
from kyoko.operator_smoke import (
    build_operator_smoke_plan,
    run_operator_failure_smoke,
    run_operator_smoke,
    run_operator_smoke_matrix,
)
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
OPERATOR_BAD_COMMAND = ROOT / "tests/fixtures/operator_command_bad_output.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class OperatorSmokeTests(unittest.TestCase):
    def test_mock_operator_smoke_uses_demo_database_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke"

            report = run_operator_smoke(
                operator="mock",
                output_dir=output_dir,
                schema_path=SCHEMA,
            )

            self.assertTrue(report.used_demo_database)
            self.assertEqual(report.db_path, output_dir / "smoke.db")
            self.assertEqual(report.operator, "mock")
            self.assertEqual(len(report.new_issue_ids), 1)
            self.assertTrue(report.persisted)
            self.assertTrue(report.evidence_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertFalse(report.live_operator_invoked)

    def test_mock_operator_smoke_reuses_output_dir_with_fresh_demo_database(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke"

            first = run_operator_smoke(
                operator="mock",
                output_dir=output_dir,
                schema_path=SCHEMA,
            )
            second = run_operator_smoke(
                operator="mock",
                output_dir=output_dir,
                schema_path=SCHEMA,
            )

            self.assertNotEqual(first.db_path, second.db_path)
            self.assertTrue(second.db_path.exists())
            self.assertEqual(len(second.new_issue_ids), 1)

    def test_command_operator_smoke_records_raw_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke"

            report = run_operator_smoke(
                operator="command",
                output_dir=output_dir,
                operator_command=[sys.executable, str(OPERATOR_COMMAND)],
                schema_path=SCHEMA,
            )

            self.assertEqual(report.operator, "command")
            self.assertEqual(len(report.new_issue_ids), 1)
            self.assertIsNotNone(report.raw_output_path)
            self.assertTrue(report.raw_output_path.exists())
            self.assertTrue(report.live_operator_invoked)

    def test_expected_failure_smoke_captures_invalid_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke"

            report = run_operator_failure_smoke(
                operator="command",
                output_dir=output_dir,
                operator_command=[sys.executable, str(OPERATOR_BAD_COMMAND), "partial-json"],
                schema_path=SCHEMA,
            )

            self.assertTrue(report.passed)
            self.assertEqual(report.status, "captured")
            self.assertEqual(report.failure_kind, "invalid_output")
            self.assertEqual(report.last_attempt_status, "invalid_output")
            self.assertFalse(report.persisted)
            self.assertTrue(report.prompt_path and report.prompt_path.exists())
            self.assertTrue(report.raw_output_path and report.raw_output_path.exists())
            self.assertIn("Expected Failure Capture", report.prompt_path.read_text())

    def test_prepare_only_command_smoke_writes_prompt_without_running_operator(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke"

            report = build_operator_smoke_plan(
                operator="command",
                output_dir=output_dir,
                operator_command=[
                    sys.executable,
                    "{prompt_path}",
                    "{evidence_path}",
                    "{profile_id}",
                ],
                schema_path=SCHEMA,
            )

            self.assertTrue(report.used_demo_database)
            self.assertFalse(report.live_operator_invoked)
            self.assertTrue(report.evidence_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertIsNotNone(report.raw_output_path)
            self.assertFalse(report.raw_output_path.exists())
            self.assertEqual(report.expanded_command[0], sys.executable)
            self.assertEqual(report.expanded_command[1], str(report.prompt_path))
            self.assertEqual(report.expanded_command[2], str(report.evidence_path))
            self.assertEqual(report.expanded_command[3], report.profile_id)
            self.assertIn("KYOKO_EVIDENCE_PATH", report.environment)
            self.assertIn("KYOKO_OPERATOR_PROMPT_PATH", report.environment)

    def test_prepare_only_smoke_resolves_default_schema_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke"

            report = build_operator_smoke_plan(
                operator="command",
                output_dir=output_dir,
                operator_command=[sys.executable, "{schema_path}"],
                schema_path=Path("docs/schemas/learning-proposal.schema.json"),
            )

            schema_path = Path(report.environment["KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH"])
            self.assertTrue(schema_path.is_absolute())
            self.assertTrue(schema_path.exists())
            self.assertEqual(report.expanded_command[1], str(schema_path))
            self.assertIn(f"LearningProposal schema: `{schema_path}`", report.prompt_path.read_text())

    def test_registered_adapter_smoke_uses_existing_database(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "smoke"
            ingest_source_fixture(db_path, FIXTURE)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                command=[sys.executable, str(OPERATOR_COMMAND)],
            )

            report = run_operator_smoke(
                operator="fixture_operator",
                db_path=db_path,
                output_dir=output_dir,
                schema_path=SCHEMA,
            )

            self.assertFalse(report.used_demo_database)
            self.assertEqual(report.db_path, db_path)
            self.assertEqual(report.operator, "fixture_operator")
            self.assertEqual(len(report.new_issue_ids), 1)

    def test_operator_smoke_matrix_skips_missing_presets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "matrix"

            with patch("kyoko.operator_smoke.shutil.which", return_value=None):
                report = run_operator_smoke_matrix(
                    operators=("codex",),
                    prepare_only=True,
                    output_dir=output_dir,
                    schema_path=SCHEMA,
                )
            payload = report.to_json()

            self.assertFalse(report.passed)
            self.assertEqual(payload["summary"]["skipped"], 1)
            self.assertEqual(payload["targets"][0]["status"], "skipped")
            self.assertIn("operator_preset_command_not_found", payload["targets"][0]["reason"])

    def test_operator_smoke_matrix_prepare_only_writes_per_operator_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "matrix"

            with patch("kyoko.operator_smoke.shutil.which", return_value="/usr/bin/codex"):
                report = run_operator_smoke_matrix(
                    operators=("codex",),
                    prepare_only=True,
                    output_dir=output_dir,
                    schema_path=SCHEMA,
                )
            payload = report.to_json()

            self.assertTrue(report.passed)
            self.assertEqual(payload["summary"]["prepared"], 1)
            target = payload["targets"][0]
            self.assertEqual(target["status"], "prepared")
            self.assertEqual(target["operator"], "codex")
            self.assertTrue(Path(target["plan"]["evidence_path"]).exists())
            self.assertTrue(Path(target["plan"]["prompt_path"]).exists())
            self.assertEqual(Path(target["plan"]["prompt_path"]).parent.name, "codex")


if __name__ == "__main__":
    unittest.main()
