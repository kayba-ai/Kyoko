import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from kyoko.analyze import (
    AnalyzeError,
    _surface_issues,
    analyze_with_command_operator,
    analyze_with_mock_operator,
    extract_issues_from_output,
    extract_proposal_from_output,
    list_operator_runs,
)
from kyoko.issues import create_issue, get_issue, list_issues
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
    def test_mock_operator_surfaces_issue_without_proposal(self) -> None:
        # ST2 decoupling: analysis is diagnosis-only. It surfaces an Issue and authors no
        # proposal (a proposal is authored later in a separate, gate-#1-guarded step).
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

            self.assertEqual(report.operator, "mock")
            self.assertEqual(report.profile_id, "profile_news_research_001")
            self.assertEqual(len(report.issue_ids), 1)
            self.assertEqual(report.new_issue_ids, report.issue_ids)
            self.assertEqual(report.bundled_issue_ids, ())
            self.assertTrue(report.persisted)
            self.assertTrue(report.evidence_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertTrue(report.operator_run_id)
            # No proposal is authored by analysis.
            self.assertEqual(status.counts["learning_proposals"], 0)
            self.assertEqual(list_learning_proposals(db_path), [])
            self.assertEqual(status.counts["operator_runs"], 1)

            issues = list_issues(db_path=db_path)
            self.assertEqual(len(issues), 1)
            issue = get_issue(db_path=db_path, issue_id=report.issue_ids[0])
            self.assertEqual(issue["source"], "analysis")
            self.assertEqual(issue["status"], "diagnosed")
            self.assertEqual(issue["proposal_ids"], [])
            self.assertTrue(issue["root_cause"])

    def test_mock_operator_dedups_recurring_issue(self) -> None:
        # A second analysis of the same evidence folds into the existing issue (dedup net).
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            first = analyze_with_mock_operator(
                db_path=db_path, output_dir=Path(tmpdir) / "a1", schema_path=SCHEMA
            )
            second = analyze_with_mock_operator(
                db_path=db_path, output_dir=Path(tmpdir) / "a2", schema_path=SCHEMA
            )

            self.assertEqual(first.new_issue_ids, first.issue_ids)
            self.assertEqual(second.bundled_issue_ids, second.issue_ids)
            self.assertEqual(second.new_issue_ids, ())
            self.assertEqual(len(list_issues(db_path=db_path)), 1)

    def test_command_operator_surfaces_issue(self) -> None:
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

            self.assertEqual(report.operator, "command")
            self.assertEqual(len(report.issue_ids), 1)
            self.assertTrue(report.persisted)
            self.assertTrue(report.raw_output_path)
            self.assertTrue(report.raw_output_path.exists())
            self.assertTrue(report.prompt_path.exists())
            self.assertTrue(report.operator_run_id)
            self.assertEqual(status.counts["learning_proposals"], 0)
            self.assertEqual(status.counts["operator_runs"], 1)
            prompt = report.prompt_path.read_text()
            self.assertIn("Kyoko Diagnosis Task", prompt)
            self.assertIn("BEGIN_KYOKO_ISSUES_JSON", prompt)
            # The diagnosis turn now shows the living skillbook and asks the agent to
            # integrate its findings via add/update/merge ops.
            self.assertIn("Current Skillbook (the living state)", prompt)
            self.assertIn('op: "update"', prompt)
            self.assertIn('op: "merge"', prompt)
            operator_runs = list_operator_runs(db_path)
            self.assertEqual(operator_runs[0]["id"], report.operator_run_id)
            self.assertEqual(operator_runs[0]["status"], "succeeded")
            self.assertEqual(operator_runs[0]["prompt_ref"], str(report.prompt_path))
            self.assertEqual(operator_runs[0]["attempt_count"], 1)
            self.assertIsNone(operator_runs[0]["failure_kind"])
            self.assertEqual(
                operator_runs[0]["metadata"]["issue_ids"], list(report.issue_ids)
            )

    def test_diagnosis_prompt_lists_existing_open_issues(self) -> None:
        # An open problem-phase entry is rendered (with its id) so the agent can target it.
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "analysis"
            ingest_source_fixture(db_path, FIXTURE)
            existing = create_issue(
                db_path=db_path, title="Existing open failure", section="context",
                root_cause="prior diagnosis",
            )
            report = analyze_with_command_operator(
                db_path=db_path,
                output_dir=output_dir,
                command=[sys.executable, str(OPERATOR_COMMAND)],
                schema_path=SCHEMA,
            )
            prompt = report.prompt_path.read_text()
            self.assertIn(existing["id"], prompt)
            self.assertIn("Existing open failure", prompt)

    def test_surface_issues_dispatches_update_and_merge_ops(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            seed = create_issue(
                db_path=db_path, title="Fetch times out", section="harness",
                root_cause="initial", source="analysis",
                evidence_refs=[{"entity_type": "span", "entity_id": "span_fetch_timeout_001"}],
                profile_id="profile_news_research_001",
            )
            new_ids, bundled_ids, all_ids = _surface_issues(
                db_path=db_path,
                profile_id="profile_news_research_001",
                issues=[
                    {
                        "schema_version": "kyoko.issue.v1", "op": "update",
                        "target_id": seed["id"], "title": "Fetch times out",
                        "section": "harness", "root_cause": "No backoff on the fetch tool",
                        "evidence_refs": [{"entity_type": "run", "entity_id": "run_research_topic_001"}],
                    },
                    {
                        "schema_version": "kyoko.issue.v1", "op": "merge",
                        "target_id": seed["id"], "title": "again", "section": "harness",
                        "root_cause": "again",
                        "evidence_refs": [{"entity_type": "span", "entity_id": "span_fetch_timeout_001"}],
                    },
                ],
            )
            # Both ops folded into the existing entry — none created a new row.
            self.assertEqual(new_ids, [])
            self.assertEqual(bundled_ids, [seed["id"], seed["id"]])
            self.assertEqual(all_ids, [seed["id"], seed["id"]])
            self.assertEqual(len(list_issues(db_path=db_path)), 1)
            refreshed = get_issue(db_path=db_path, issue_id=seed["id"])
            self.assertEqual(refreshed["root_cause"], "No backoff on the fetch tool")
            self.assertEqual(refreshed["recurrence_count"], 2)  # the merge bumped it once

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
            self.assertEqual(len(report.issue_ids), 1)
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

            self.assertEqual(len(report.issue_ids), 1)
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
            ("partial-json", "operator_issues_json_invalid", "invalid_output", "invalid_output"),
            (
                "hallucinated-evidence",
                "evidence_ref_not_found:span:span_does_not_exist_001",
                "invalid_output",
                "invalid_output",
            ),
            ("missing-root-cause", "'root_cause' is a required property", "invalid_output", "invalid_output"),
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
                # No proposal is ever authored from analysis.
                self.assertEqual(list_learning_proposals(db_path), [])

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

    def test_extract_issues_rejects_missing_block(self) -> None:
        with self.assertRaisesRegex(AnalyzeError, "exactly_one_issues_block"):
            extract_issues_from_output("no json here")

    def test_extract_proposal_rejects_missing_block(self) -> None:
        with self.assertRaisesRegex(AnalyzeError, "exactly_one_proposal_block"):
            extract_proposal_from_output("no json here")


if __name__ == "__main__":
    unittest.main()
