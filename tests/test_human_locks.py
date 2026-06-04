import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import (
    ApplyError,
    apply_context_proposal,
    list_context_delivery_rules,
    list_skills,
    set_context_delivery_rule_lock,
    set_skill_lock,
)
from kyoko.harness import (
    HarnessError,
    list_harness_target_locks,
    prepare_harness_proposal,
    set_harness_target_lock,
)
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _conflicting_skill_proposal() -> dict:
    proposal = json.loads(VALID_PROPOSAL.read_text())
    proposal["id"] = "proposal_context_timeout_002"
    proposal["producer"]["session_id"] = "proposal_context_timeout_002"
    proposal["proposed_changes"][0]["skill_id"] = "skill_proposal_context_timeout_001_1"
    return proposal


def _context_rule_proposal() -> dict:
    proposal = json.loads(VALID_PROPOSAL.read_text())
    proposal["id"] = "proposal_context_rule_001"
    proposal["producer"]["session_id"] = "proposal_context_rule_001"
    proposal["title"] = "Context delivery rule"
    proposal["proposed_changes"] = [
        {
            "type": "context_delivery_rule",
            "operation": "create",
            "target": {
                "entity_type": "agent_identity",
                "entity_id": "agent_researcher_001",
            },
            "rule": {
                "id": "context_rule_researcher_timeout",
                "mode": "prompt",
                "include_keywords": ["timeout"],
                "max_skills": 1,
            },
        }
    ]
    return proposal


class HumanLockStateTests(unittest.TestCase):
    """A human lock is boolean state + reason (no event ledger), with enforcement."""

    def test_skill_lock_is_boolean_state_and_blocks_apply(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")

            lock = set_skill_lock(
                db_path=db_path,
                skill_id="skill_proposal_context_timeout_001_1",
                locked=True,
                reason="manual owner review",
                actor_agent_identity_id="agent_researcher_001",
            )
            self.assertTrue(lock.human_locked)
            self.assertTrue(list_skills(db_path)[0]["human_locked"])
            self.assertEqual(list_skills(db_path)[0]["human_lock_reason"], "manual owner review")

            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_conflicting_skill_proposal(),
                schema_path=SCHEMA,
            )
            with self.assertRaisesRegex(ApplyError, "human_locked_skill"):
                apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_002")

            # Unlock flips the boolean back; enforcement no longer trips on the lock.
            unlock = set_skill_lock(
                db_path=db_path,
                skill_id="skill_proposal_context_timeout_001_1",
                locked=False,
            )
            self.assertFalse(unlock.human_locked)
            self.assertFalse(list_skills(db_path)[0]["human_locked"])
            with self.assertRaisesRegex(ApplyError, "skill_already_exists"):
                apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_002")

    def test_context_rule_lock_is_boolean_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal(),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_001")
            rule_id = list_context_delivery_rules(db_path)[0]["id"]

            lock = set_context_delivery_rule_lock(
                db_path=db_path,
                rule_id=rule_id,
                locked=True,
                reason="preserve handoff policy",
            )
            self.assertTrue(lock.human_locked)
            self.assertTrue(list_context_delivery_rules(db_path)[0]["human_locked"])

            unlock = set_context_delivery_rule_lock(db_path=db_path, rule_id=rule_id, locked=False)
            self.assertFalse(unlock.human_locked)
            self.assertFalse(list_context_delivery_rules(db_path)[0]["human_locked"])

    def test_harness_target_lock_row_blocks_prepare(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )

            set_harness_target_lock(
                db_path=db_path,
                target_path="evals/generated_timeout_eval.py",
                locked=True,
                reason="manual owner review",
            )
            locks = list_harness_target_locks(db_path)
            self.assertTrue(locks[0]["human_locked"])
            self.assertEqual(locks[0]["target_path"], "evals/generated_timeout_eval.py")

            with self.assertRaisesRegex(HarnessError, "human_locked_harness_target"):
                prepare_harness_proposal(
                    db_path=db_path,
                    proposal_id="proposal_harness_generated_eval_001",
                )

            set_harness_target_lock(
                db_path=db_path,
                target_path="evals/generated_timeout_eval.py",
                locked=False,
            )
            self.assertEqual(list_harness_target_locks(db_path), [])
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )


if __name__ == "__main__":
    unittest.main()
