from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.autonomy import AutonomyError, get_autonomy_policy, update_autonomy_policy
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


class AutonomyTests(unittest.TestCase):
    def test_get_and_update_policy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            default_policy = get_autonomy_policy(db_path=db_path)
            updated_policy = update_autonomy_policy(
                db_path=db_path,
                context_mode="autonomous",
                harness_mode="propose",
                allow_repo_patch=True,
                dirty_worktree_policy="block",
            )

            # Single implicit profile (SCOPE Decision 1): policy resolves without
            # being told which profile to target.
            self.assertEqual(default_policy["profile_id"], "profile_news_research_001")
            self.assertEqual(updated_policy["profile_id"], "profile_news_research_001")
            self.assertEqual(default_policy["context_mode"], "propose")
            self.assertEqual(default_policy["harness_mode"], "propose")
            self.assertFalse(default_policy["allow_repo_patch"])
            self.assertIn("evals/**", default_policy["allowed_paths"])
            self.assertEqual(updated_policy["context_mode"], "autonomous")
            self.assertEqual(updated_policy["harness_mode"], "propose")
            self.assertTrue(updated_policy["allow_repo_patch"])
            self.assertEqual(updated_policy["dirty_worktree_policy"], "block")

    def test_update_rejects_invalid_mode(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with self.assertRaisesRegex(AutonomyError, "invalid_context_mode"):
                update_autonomy_policy(db_path=db_path, context_mode="always")


if __name__ == "__main__":
    unittest.main()
