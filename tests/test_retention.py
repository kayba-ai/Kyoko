from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

from kyoko.apply import apply_context_proposal
from kyoko.demo import run_demo_setup
from kyoko.operator_adapters import register_operator_adapter, run_registered_operator_adapter
from kyoko.proposals import submit_learning_proposal
from kyoko.retention import prune_retained_data
from kyoko.storage import connect, get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
FUTURE_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class RetentionTests(unittest.TestCase):
    def test_trace_prune_dry_run_and_apply_remove_unprotected_trace_rows(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            before = get_database_status(db_path)

            dry_run = prune_retained_data(
                db_path=db_path,
                trace_older_than_days=0,
                dry_run=True,
                now=FUTURE_NOW,
            )
            after_dry_run = get_database_status(db_path)
            applied = prune_retained_data(
                db_path=db_path,
                trace_older_than_days=0,
                dry_run=False,
                now=FUTURE_NOW,
            )
            after_apply = get_database_status(db_path)

            self.assertTrue(dry_run.dry_run)
            self.assertEqual(dry_run.pruned_rows["runs"], ["run_research_topic_001"])
            self.assertEqual(dry_run.pruned_rows["task_attempts"], ["attempt_research_topic_001"])
            self.assertEqual(dry_run.pruned_rows["tasks"], ["task_research_topic_001"])
            self.assertEqual(before.counts["runs"], after_dry_run.counts["runs"])
            self.assertFalse(applied.dry_run)
            self.assertEqual(after_apply.counts["runs"], 0)
            self.assertEqual(after_apply.counts["spans"], 0)
            self.assertEqual(after_apply.counts["handoffs"], 0)
            self.assertEqual(after_apply.counts["task_attempts"], 0)
            self.assertEqual(after_apply.counts["tasks"], 0)
            self.assertEqual(after_apply.counts["timeline_events"], 0)
            self.assertEqual(after_apply.counts["sources"], 2)

    def test_trace_prune_skips_runs_used_by_applied_skills(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")

            report = prune_retained_data(
                db_path=db_path,
                trace_older_than_days=0,
                dry_run=True,
                now=FUTURE_NOW,
            )
            status = get_database_status(db_path)

            self.assertEqual(report.pruned_rows["runs"], [])
            self.assertIn(
                {"entity_type": "run", "entity_id": "run_research_topic_001", "reason": "skill_source_run"},
                report.skipped_rows,
            )
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 2)

    def test_active_replay_task_attempt_reference_protects_trace_apply(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            _insert_replay_task_attempt_reference(db_path)

            report = prune_retained_data(
                db_path=db_path,
                trace_older_than_days=0,
                dry_run=False,
                now=FUTURE_NOW,
            )
            status = get_database_status(db_path)

            self.assertEqual(report.pruned_rows["runs"], [])
            self.assertIn(
                {
                    "entity_type": "run",
                    "entity_id": "run_research_topic_001",
                    "reason": "active_replay_task_attempt",
                },
                report.skipped_rows,
            )
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["task_attempts"], 1)
            self.assertEqual(status.counts["replay_runs"], 1)

    def test_replay_check_and_operator_retention_apply_prunes_only_runtime_rows(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "output"
            run_demo_setup(db_path=db_path, output_dir=output_dir)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                operator_kind="generic",
                command=[sys.executable, str(OPERATOR_COMMAND)],
                output_dir=output_dir / "operator",
            )
            run_registered_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                schema_path=SCHEMA,
            )
            before = get_database_status(db_path)

            report = prune_retained_data(
                db_path=db_path,
                replay_older_than_days=0,
                operator_older_than_days=0,
                dry_run=False,
                now=FUTURE_NOW,
            )
            after = get_database_status(db_path)

            self.assertEqual(before.counts["replay_runs"], 1)
            self.assertEqual(before.counts["check_runs"], 1)
            self.assertEqual(before.counts["operator_runs"], 1)
            self.assertEqual(report.pruned_rows["replay_runs"], ["replay_check_proposal_context_timeout_001_1_001"])
            self.assertEqual(len(report.pruned_rows["check_runs"]), 1)
            self.assertEqual(len(report.pruned_rows["operator_runs"]), 1)
            self.assertEqual(after.counts["replay_runs"], 0)
            self.assertEqual(after.counts["check_runs"], 0)
            self.assertEqual(after.counts["operator_runs"], 0)
            self.assertEqual(after.counts["check_specs"], 1)
            self.assertGreaterEqual(after.counts["learning_proposals"], 1)

def _insert_replay_task_attempt_reference(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO replay_runs (
              id,
              profile_id,
              proposal_id,
              check_spec_id,
              source_run_id,
              task_attempt_id,
              mode,
              side_effect_mode,
              status,
              started_at,
              ended_at,
              input_ref,
              output_ref,
              result_json,
              artifact_refs_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "replay_task_attempt_only_001",
                "profile_news_research_001",
                None,
                None,
                None,
                "attempt_research_topic_001",
                "dry_run",
                "network_mocked",
                "passed",
                "2026-05-31T11:51:00Z",
                "2026-05-31T11:52:00Z",
                None,
                None,
                "{}",
                "{}",
                "2026-05-31T11:52:00Z",
                "2026-05-31T11:52:00Z",
            ),
        )


if __name__ == "__main__":
    unittest.main()
