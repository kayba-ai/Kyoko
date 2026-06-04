import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from kyoko.analyze import (
    AnalyzeError,
    analyze_with_command_operator,
    analyze_with_mock_operator,
    extract_proposal_from_output,
    list_operator_runs,
)
from kyoko.autonomy import update_autonomy_policy
from kyoko.issues import get_issue, list_issues
from kyoko.proposals import list_learning_proposals
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
OPERATOR_ARG_COMMAND = ROOT / "tests/fixtures/operator_command_arg.py"
OPERATOR_RETRY_COMMAND = ROOT / "tests/fixtures/operator_command_retry.py"
OPERATOR_BAD_COMMAND = ROOT / "tests/fixtures/operator_command_bad_output.py"


class AnalyzeTests(unittest.TestCase):
    def test_mock_operator_writes_artifacts_and_persists_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)

            report = analyze_with_mock_operator(
                db_path=db_path,
                output_dir=output_dir,
                schema_path=SCHEMA,
            )
            status = get_database_status(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.operator, "mock")
            self.assertEqual(report.profile_id, "profile_news_research_001")
            self.assertEqual(report.proposal_id, "proposal_mock_span_fetch_timeout_001")
            self.assertTrue(report.evidence_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertTrue(report.proposal_path.exists())
            self.assertTrue(report.operator_run_id)
            self.assertEqual(status.counts["learning_proposals"], 1)
            self.assertEqual(status.counts["operator_runs"], 1)
            self.assertEqual(proposals[0]["id"], "proposal_mock_span_fetch_timeout_001")

            proposal_payload = json.loads(report.proposal_path.read_text())
            self.assertEqual(proposal_payload["producer"]["name"], "mock")
            self.assertEqual(
                proposal_payload["evidence_refs"][0]["entity_id"],
                "span_fetch_timeout_001",
            )

    def test_mock_operator_originates_issue_for_proposal(self) -> None:
        # Issue-centric spine: analysis surfaces+diagnoses an Issue, and the proposal is
        # born of it (carries issue_id; the issue backlinks the proposal and is proposed).
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)

            report = analyze_with_mock_operator(
                db_path=db_path, output_dir=output_dir, schema_path=SCHEMA
            )
            self.assertTrue(report.issue_id)

            issues = list_issues(db_path=db_path)
            self.assertEqual(len(issues), 1)
            issue = get_issue(db_path=db_path, issue_id=report.issue_id)
            self.assertEqual(issue["source"], "analysis")
            self.assertEqual(issue["status"], "proposed")
            self.assertIn(report.proposal_id, issue["proposal_ids"])
            self.assertTrue(issue["root_cause"])

            proposal_payload = json.loads(report.proposal_path.read_text())
            self.assertEqual(proposal_payload["issue_id"], report.issue_id)

    def test_gate1_off_surfaces_issue_without_generating_proposal(self) -> None:
        # Gate #1: when the fix section's autonomy mode is `off`, analysis still
        # surfaces+diagnoses the Issue but generates no proposal (stops at diagnosed).
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)
            # The mock proposal is a context-section fix.
            update_autonomy_policy(db_path=db_path, context_mode="off")

            report = analyze_with_mock_operator(
                db_path=db_path, output_dir=output_dir, schema_path=SCHEMA
            )
            self.assertIsNone(report.proposal_id)
            self.assertFalse(report.gate1_allow)
            self.assertEqual(report.gate1_mode, "off")
            self.assertFalse(report.persisted)
            self.assertTrue(report.issue_id)

            self.assertEqual(list_learning_proposals(db_path), [])
            issue = get_issue(db_path=db_path, issue_id=report.issue_id)
            self.assertEqual(issue["status"], "diagnosed")
            self.assertEqual(issue["proposal_ids"], [])

    def test_command_operator_extracts_and_persists_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)

            report = analyze_with_command_operator(
                db_path=db_path,
                output_dir=output_dir,
                command=[sys.executable, str(OPERATOR_COMMAND)],
                schema_path=SCHEMA,
            )
            status = get_database_status(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.operator, "command")
            self.assertEqual(report.proposal_id, "proposal_command_span_fetch_timeout_001")
            self.assertTrue(report.raw_output_path)
            self.assertTrue(report.raw_output_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertTrue(report.operator_run_id)
            self.assertEqual(status.counts["learning_proposals"], 1)
            self.assertEqual(status.counts["operator_runs"], 1)
            self.assertEqual(proposals[0]["id"], "proposal_command_span_fetch_timeout_001")
            prompt = report.prompt_path.read_text()
            self.assertIn("Kyoko Operator Task", prompt)
            self.assertIn("BEGIN_KYOKO_LEARNING_PROPOSAL_JSON", prompt)
            self.assertIn("## Check Capabilities", prompt)
            self.assertIn("Executable check types", prompt)
            self.assertIn("deterministic_assertion", prompt)
            self.assertIn("regression_replay", prompt)
            self.assertIn("Assertion presets", prompt)
            self.assertIn("replay_success_shape", prompt)
            self.assertIn("judge` and `smoke_run` are informational only", prompt)
            operator_runs = list_operator_runs(db_path)
            self.assertEqual(operator_runs[0]["id"], report.operator_run_id)
            self.assertEqual(operator_runs[0]["status"], "succeeded")
            self.assertEqual(operator_runs[0]["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertEqual(operator_runs[0]["prompt_ref"], str(report.prompt_path))
            self.assertEqual(operator_runs[0]["attempt_count"], 1)
            self.assertIsNone(operator_runs[0]["failure_kind"])

    def test_command_operator_expands_prompt_placeholders_for_argument_driven_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)

            report = analyze_with_command_operator(
                db_path=db_path,
                output_dir=output_dir,
                command=[
                    sys.executable,
                    str(OPERATOR_ARG_COMMAND),
                    "{prompt}",
                    "{profile_id}",
                    "{evidence_path}",
                    "{prompt_path}",
                    "{schema_path}",
                ],
                operator_label="fixture_arg",
                operator_kind="hermes",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.operator, "fixture_arg")
            self.assertEqual(report.proposal_id, "proposal_arg_span_fetch_timeout_001")
            self.assertTrue(report.raw_output_path)
            self.assertIn("ARG_PROFILE=profile_news_research_001", report.raw_output_path.read_text())
            prompt = report.prompt_path.read_text()
            self.assertIn("## Evidence Bundle JSON", prompt)
            self.assertIn("span_fetch_timeout_001", prompt)
            operator_runs = list_operator_runs(db_path)
            self.assertEqual(operator_runs[0]["metadata"]["command"][2], "{prompt}")

    def test_command_operator_retries_malformed_output_with_correction_prompt(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)

            report = analyze_with_command_operator(
                db_path=db_path,
                output_dir=output_dir,
                command=[sys.executable, str(OPERATOR_RETRY_COMMAND)],
                schema_path=SCHEMA,
                max_retries=1,
            )

            self.assertEqual(report.proposal_id, "proposal_retry_span_fetch_timeout_001")
            self.assertEqual(report.attempts, 2)
            self.assertTrue((output_dir / "operator-instructions-attempt-2.md").exists())
            self.assertTrue(report.raw_output_path)
            raw_output = report.raw_output_path.read_text()
            self.assertIn("attempt 1 status=invalid_output", raw_output)
            self.assertIn("attempt 2 status=succeeded", raw_output)
            operator_runs = list_operator_runs(db_path)
            self.assertEqual(operator_runs[0]["metadata"]["attempts"], 2)
            self.assertEqual(operator_runs[0]["metadata"]["max_retries"], 1)
            self.assertEqual(operator_runs[0]["metadata"]["attempt_results"][0]["status"], "invalid_output")
            self.assertEqual(operator_runs[0]["metadata"]["attempt_results"][1]["status"], "succeeded")

    def test_command_operator_records_representative_invalid_outputs(self) -> None:
        cases = [
            ("partial-json", "operator_proposal_json_invalid", "invalid_output", "invalid_output"),
            (
                "hallucinated-evidence",
                "evidence_ref_not_found:span:span_does_not_exist_001",
                "invalid_proposal",
                "invalid_proposal",
            ),
            ("unsupported-change", "schema_error", "invalid_proposal", "invalid_proposal"),
        ]
        for mode, expected_error, failure_kind, attempt_status in cases:
            with self.subTest(mode=mode), TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "kyoko.db"
                output_dir = Path(tmpdir) / "analysis"
                ingest_source_fixture(db_path, FIXTURE)

                with self.assertRaisesRegex(AnalyzeError, expected_error):
                    analyze_with_command_operator(
                        db_path=db_path,
                        output_dir=output_dir,
                        command=[sys.executable, str(OPERATOR_BAD_COMMAND), mode],
                        schema_path=SCHEMA,
                    )

                operator_runs = list_operator_runs(db_path)
                self.assertEqual(len(operator_runs), 1)
                self.assertEqual(operator_runs[0]["status"], "failed")
                self.assertEqual(operator_runs[0]["failure_kind"], failure_kind)
                self.assertEqual(operator_runs[0]["attempt_count"], 1)
                self.assertIn(expected_error, operator_runs[0]["error"])
                self.assertEqual(
                    operator_runs[0]["metadata"]["attempt_results"][0]["status"],
                    attempt_status,
                )
                raw_output = Path(operator_runs[0]["raw_output_ref"]).read_text()
                self.assertIn(f"attempt 1 status={attempt_status}", raw_output)

    def test_command_operator_records_failed_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)

            with self.assertRaisesRegex(AnalyzeError, "operator_failed:3"):
                analyze_with_command_operator(
                    db_path=db_path,
                    output_dir=output_dir,
                    command=[sys.executable, "-c", "import sys; print('bad output'); sys.exit(3)"],
                    schema_path=SCHEMA,
                )

            operator_runs = list_operator_runs(db_path)
            self.assertEqual(len(operator_runs), 1)
            self.assertEqual(operator_runs[0]["status"], "failed")
            self.assertEqual(operator_runs[0]["error"], "operator_failed:3")
            self.assertEqual(operator_runs[0]["failure_kind"], "nonzero_exit")
            self.assertEqual(operator_runs[0]["attempt_count"], 1)
            self.assertTrue(Path(operator_runs[0]["prompt_ref"]).exists())
            self.assertTrue(Path(operator_runs[0]["raw_output_ref"]).exists())

    def test_extract_proposal_rejects_missing_block(self) -> None:
        with self.assertRaisesRegex(AnalyzeError, "exactly_one_proposal_block"):
            extract_proposal_from_output("no json here")


if __name__ == "__main__":
    unittest.main()
