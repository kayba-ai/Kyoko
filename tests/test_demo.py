from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.demo import run_demo_setup
from kyoko.storage import get_database_status


class DemoTests(unittest.TestCase):
    def test_demo_runs_full_local_loop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "demo-output"

            report = run_demo_setup(db_path=db_path, output_dir=output_dir)
            status = get_database_status(db_path)

            self.assertEqual(report.profile_id, "profile_news_research_001")
            self.assertEqual(report.proposal_id, "proposal_context_timeout_001")
            self.assertEqual(report.check_spec_ids, ("check_proposal_context_timeout_001_1",))
            self.assertEqual(report.adapter_id, "fixture_replay")
            self.assertEqual(report.check_status, "passed")
            self.assertEqual(report.promoted_trust_level, "L2_regression")
            self.assertEqual(report.applied_skill_ids, ("skill_proposal_context_timeout_001_1",))
            self.assertEqual(status.counts["learning_proposals"], 4)
            self.assertEqual(status.counts["check_specs"], 3)
            self.assertEqual(status.counts["replay_adapters"], 1)
            self.assertEqual(status.counts["replay_runs"], 3)
            self.assertEqual(status.counts["check_runs"], 3)
            self.assertEqual(status.counts["skills"], 5)
            self.assertEqual(status.counts["runs"], 14)
            self.assertEqual(status.counts["spans"], 40)

    def test_demo_setup_is_idempotent_for_seed_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "demo-output"

            first = run_demo_setup(db_path=db_path, output_dir=output_dir)
            second = run_demo_setup(
                db_path=db_path,
                output_dir=output_dir,
                run_loop=False,
                apply_context=False,
            )
            status = get_database_status(db_path)

            self.assertTrue(first.proposal_created)
            self.assertFalse(second.proposal_created)
            self.assertEqual(second.check_spec_existing_ids, ("check_proposal_context_timeout_001_1",))
            self.assertEqual(status.counts["learning_proposals"], 4)
            self.assertEqual(status.counts["check_specs"], 3)
            self.assertEqual(status.counts["replay_adapters"], 1)
            self.assertEqual(status.counts["skills"], 5)
            self.assertEqual(status.counts["runs"], 14)
            self.assertEqual(status.counts["spans"], 40)


if __name__ == "__main__":
    unittest.main()
