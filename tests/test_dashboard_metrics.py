from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.autonomy import update_autonomy_policy
from kyoko.autonomy_runner import run_autonomy
from kyoko.dashboard_metrics import DashboardMetricsError, get_dashboard_metrics
from kyoko.checks import complete_replay_from_fixture, create_replay_run, generate_checks_for_proposal, run_check
from kyoko.proposals import submit_learning_proposal
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class DashboardMetricsTests(unittest.TestCase):
    def test_dashboard_metrics_describe_local_improvement_loop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            metrics = get_dashboard_metrics(db_path=db_path)

            self.assertEqual(metrics["profile_id"], "profile_news_research_001")
            self.assertEqual(metrics["runs"]["failed_spans"], 1)
            self.assertEqual(metrics["issues"]["total"], 1)
            self.assertEqual(metrics["issues"]["active"], 1)
            self.assertEqual(metrics["issues"]["by_section"]["context"], 1)
            self.assertEqual(metrics["checks"]["latest_status"], "none")
            self.assertEqual(metrics["replay"]["latest_status"], "none")
            self.assertFalse(metrics["before_after"]["verified_replay_improvement"])
            self.assertEqual(
                [card["id"] for card in metrics["cards"]],
                ["issues", "proposal_status", "checks", "replay", "autonomy", "before_after"],
            )

    def test_dashboard_metrics_show_verified_before_after_after_check_replay(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, mode="autonomous")
            generate_checks_for_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
            )
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )
            run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
                replay_run_id=replay.replay_run_id,
            )
            run_autonomy(db_path=db_path)

            metrics = get_dashboard_metrics(db_path=db_path, profile_id="profile_news_research_001")

            self.assertEqual(metrics["issues"]["by_state"]["applied"], 1)
            self.assertEqual(metrics["issues"]["active"], 0)
            self.assertEqual(metrics["checks"]["passed"], 1)
            self.assertEqual(metrics["checks"]["latest_status"], "passed")
            self.assertEqual(metrics["replay"]["passed"], 1)
            self.assertEqual(metrics["replay"]["latest_status"], "passed")
            self.assertEqual(metrics["autonomy"]["by_action"]["applied"], 1)
            self.assertTrue(metrics["before_after"]["verified_replay_improvement"])
            self.assertEqual(
                metrics["before_after"]["latest_passed_replay_run_id"],
                replay.replay_run_id,
            )

    def test_dashboard_metrics_reject_missing_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(DashboardMetricsError, "profile_not_found"):
                get_dashboard_metrics(db_path=db_path, profile_id="missing")


if __name__ == "__main__":
    unittest.main()
