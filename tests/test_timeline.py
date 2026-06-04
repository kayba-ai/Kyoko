from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.autonomy import update_autonomy_policy
from kyoko.autonomy_runner import run_autonomy
from kyoko.proposals import submit_learning_proposal
from kyoko.storage import ingest_source_fixture
from kyoko.timeline import AUTONOMY_EVENT_KINDS, list_timeline_events


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class TimelineTests(unittest.TestCase):
    def test_list_timeline_events_filters_autonomy_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            run_autonomy(db_path=db_path)

            events = list_timeline_events(
                db_path=db_path,
                profile_id="profile_news_research_001",
                kinds=AUTONOMY_EVENT_KINDS,
                limit=10,
            )
            decision_events = list_timeline_events(
                db_path=db_path,
                profile_id="profile_news_research_001",
                kinds=("autonomy_decision",),
                entity_type="learning_proposal",
                entity_id="proposal_context_timeout_001",
                limit=10,
            )

            self.assertEqual(
                {event["kind"] for event in events},
                {"autonomy_gated", "autonomy_decision"},
            )
            self.assertEqual(len(decision_events), 1)
            self.assertEqual(decision_events[0]["kind"], "autonomy_decision")
            self.assertEqual(decision_events[0]["metadata"]["action"], "gated")
            self.assertEqual(decision_events[0]["metadata"]["reason"], "missing_check_run")


if __name__ == "__main__":
    unittest.main()
