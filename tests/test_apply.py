import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import (
    ApplyError,
    apply_context_proposal,
    list_context_delivery_rules,
    list_context_delivery_rule_revisions,
    list_skill_revisions,
    list_skills,
    rollback_context_delivery_rule_revision,
    rollback_skill_revision,
    set_context_delivery_rule_lock,
    set_skill_lock,
)
from kyoko.proposals import (
    list_learning_proposals,
    submit_learning_proposal,
    submit_learning_proposal_payload,
)
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _context_rule_proposal(proposal_id: str, *, operation: str = "create") -> dict:
    proposal = json.loads(VALID_PROPOSAL.read_text())
    proposal["id"] = proposal_id
    proposal["producer"]["session_id"] = proposal_id
    proposal["title"] = f"Context delivery rule {operation}"
    proposal["proposed_changes"] = [
        {
            "type": "context_delivery_rule",
            "operation": operation,
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


class ApplyTests(unittest.TestCase):
    def test_apply_context_proposal_creates_skill_and_updates_state(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            report = apply_context_proposal(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )
            status = get_database_status(db_path)
            proposals = list_learning_proposals(db_path)
            skills = list_skills(db_path)

            self.assertEqual(report.state, "applied")
            self.assertEqual(report.applied_skill_ids, ("skill_proposal_context_timeout_001_1",))
            self.assertEqual(report.applied_context_rule_ids, ())
            self.assertEqual(status.counts["skills"], 1)
            self.assertEqual(status.counts["context_delivery_rules"], 0)
            self.assertEqual(status.counts["skill_revisions"], 1)
            self.assertEqual(status.counts["timeline_events"], 4)
            self.assertEqual(status.counts["sources"], 3)
            self.assertEqual(proposals[0]["state"], "applied")
            self.assertEqual(skills[0]["section"], "context")
            self.assertEqual(skills[0]["source_run_id"], "run_research_topic_001")
            self.assertFalse(skills[0]["human_locked"])
            self.assertIn("timeout", skills[0]["keywords"])

    def test_apply_rejects_repeat_application(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")

            with self.assertRaisesRegex(ApplyError, "proposal_state_not_applyable"):
                apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")

            self.assertEqual(get_database_status(db_path).counts["skills"], 1)

    def test_human_locked_skill_blocks_conflicting_apply(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")

            lock_report = set_skill_lock(
                db_path=db_path,
                skill_id="skill_proposal_context_timeout_001_1",
                locked=True,
                reason="manual owner review",
                actor_agent_identity_id="agent_researcher_001",
            )
            self.assertTrue(lock_report.human_locked)
            self.assertTrue(list_skills(db_path)[0]["human_locked"])
            self.assertEqual(lock_report.reason, "manual owner review")
            self.assertEqual(list_skills(db_path)[0]["human_lock_reason"], "manual owner review")

            proposal = json.loads(VALID_PROPOSAL.read_text())
            proposal["id"] = "proposal_context_timeout_002"
            proposal["producer"]["session_id"] = "test_conflict"
            proposal["proposed_changes"][0]["skill_id"] = "skill_proposal_context_timeout_001_1"
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )

            with self.assertRaisesRegex(ApplyError, "human_locked_skill"):
                apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_002")

            unlock_report = set_skill_lock(
                db_path=db_path,
                skill_id="skill_proposal_context_timeout_001_1",
                locked=False,
                reason="review complete",
                actor_agent_identity_id="agent_researcher_001",
            )

            self.assertFalse(unlock_report.human_locked)
            self.assertFalse(list_skills(db_path)[0]["human_locked"])
            self.assertEqual(unlock_report.reason, "review complete")
            self.assertEqual(lock_report.actor_agent_identity_id, "agent_researcher_001")
            self.assertEqual(unlock_report.actor_agent_identity_id, "agent_researcher_001")

            with self.assertRaisesRegex(ApplyError, "actor_agent_identity_not_found"):
                set_skill_lock(
                    db_path=db_path,
                    skill_id="skill_proposal_context_timeout_001_1",
                    locked=True,
                    actor_agent_identity_id="agent_missing",
                )

    def test_apply_skill_update_link_occurrence_and_deactivate_records_revisions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")

            update_proposal = json.loads(VALID_PROPOSAL.read_text())
            update_proposal["id"] = "proposal_context_timeout_update_001"
            update_proposal["producer"]["session_id"] = "proposal_context_timeout_update_001"
            update_proposal["proposed_changes"][0]["operation"] = "update"
            update_proposal["proposed_changes"][0]["skill_id"] = "skill_proposal_context_timeout_001_1"
            update_proposal["proposed_changes"][0]["issue"] = "Fetch timeout retries need clearer guidance."
            update_proposal["proposed_changes"][0]["keywords"] = ["fetch", "timeout", "retry"]
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=update_proposal,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_update_001")

            link_proposal = json.loads(VALID_PROPOSAL.read_text())
            link_proposal["id"] = "proposal_context_timeout_link_001"
            link_proposal["producer"]["session_id"] = "proposal_context_timeout_link_001"
            link_proposal["proposed_changes"][0]["operation"] = "link_occurrence"
            link_proposal["proposed_changes"][0]["skill_id"] = "skill_proposal_context_timeout_001_1"
            link_proposal["proposed_changes"][0]["occurrence_refs"] = [
                {
                    "entity_type": "run",
                    "entity_id": "run_research_topic_001",
                    "role": "source",
                }
            ]
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=link_proposal,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_link_001")

            deactivate_proposal = json.loads(VALID_PROPOSAL.read_text())
            deactivate_proposal["id"] = "proposal_context_timeout_deactivate_001"
            deactivate_proposal["producer"]["session_id"] = "proposal_context_timeout_deactivate_001"
            deactivate_proposal["proposed_changes"][0]["operation"] = "deactivate"
            deactivate_proposal["proposed_changes"][0]["skill_id"] = "skill_proposal_context_timeout_001_1"
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=deactivate_proposal,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_deactivate_001")

            skills = list_skills(db_path)
            revisions = list_skill_revisions(db_path, skill_id="skill_proposal_context_timeout_001_1")
            status = get_database_status(db_path)

            self.assertFalse(skills[0]["active"])
            self.assertEqual(skills[0]["issue"], "Fetch timeout retries need clearer guidance.")
            self.assertEqual(len(skills[0]["occurrences"]), 2)
            self.assertEqual(status.counts["skill_revisions"], 4)
            self.assertEqual([revision["operation"] for revision in revisions], ["deactivate", "link_occurrence", "update", "create"])
            self.assertEqual(revisions[0]["before"]["active"], True)
            self.assertEqual(revisions[0]["after"]["active"], False)

            rollback = rollback_skill_revision(db_path=db_path, revision_id=revisions[0]["id"])
            rolled_back_skill = list_skills(db_path)[0]
            rolled_back_revisions = list_skill_revisions(db_path, skill_id="skill_proposal_context_timeout_001_1")

            self.assertEqual(rollback.status, "rolled_back")
            self.assertTrue(rolled_back_skill["active"])
            self.assertEqual(rolled_back_revisions[0]["operation"], "rollback")
            self.assertEqual(rolled_back_revisions[0]["before"]["active"], False)
            self.assertEqual(rolled_back_revisions[0]["after"]["active"], True)

            with self.assertRaisesRegex(ApplyError, "skill_revision_not_latest"):
                rollback_skill_revision(db_path=db_path, revision_id=revisions[1]["id"])

    def test_rollback_create_skill_revision_deactivates_created_skill(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
            revisions = list_skill_revisions(db_path, skill_id="skill_proposal_context_timeout_001_1")

            rollback = rollback_skill_revision(db_path=db_path, revision_id=revisions[0]["id"])
            skills = list_skills(db_path)
            rolled_back_revisions = list_skill_revisions(db_path, skill_id="skill_proposal_context_timeout_001_1")

            self.assertEqual(rollback.status, "rolled_back")
            self.assertFalse(skills[0]["active"])
            self.assertEqual(rolled_back_revisions[0]["operation"], "rollback")
            self.assertTrue(rolled_back_revisions[0]["before"]["active"])
            self.assertFalse(rolled_back_revisions[0]["after"]["active"])

    def test_apply_context_delivery_rule_without_skill_update(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal("proposal_context_rule_001"),
                schema_path=SCHEMA,
            )

            report = apply_context_proposal(
                db_path=db_path,
                proposal_id="proposal_context_rule_001",
            )
            rules = list_context_delivery_rules(db_path)
            revisions = list_context_delivery_rule_revisions(db_path, rule_id="context_rule_researcher_timeout")
            status = get_database_status(db_path)

            self.assertEqual(report.applied_skill_ids, ())
            self.assertEqual(report.applied_context_rule_ids, ("context_rule_researcher_timeout",))
            self.assertEqual(status.counts["context_delivery_rules"], 1)
            self.assertEqual(status.counts["context_delivery_rule_revisions"], 1)
            self.assertEqual(status.counts["timeline_events"], 5)
            self.assertEqual(rules[0]["id"], "context_rule_researcher_timeout")
            self.assertEqual(rules[0]["target"]["entity_id"], "agent_researcher_001")
            self.assertEqual(rules[0]["rule"]["include_keywords"], ["timeout"])
            self.assertTrue(rules[0]["active"])
            self.assertFalse(rules[0]["human_locked"])
            self.assertEqual(revisions[0]["operation"], "create")
            self.assertIsNone(revisions[0]["before"])
            self.assertEqual(revisions[0]["after"]["rule"]["include_keywords"], ["timeout"])

    def test_context_delivery_rule_update_and_create_rollbacks_use_revisions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal("proposal_context_rule_001"),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_001")

            update_proposal = _context_rule_proposal("proposal_context_rule_002", operation="update")
            update_proposal["proposed_changes"][0]["rule"]["include_keywords"] = ["handoff"]
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=update_proposal,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_002")

            revisions = list_context_delivery_rule_revisions(db_path, rule_id="context_rule_researcher_timeout")
            self.assertEqual([revision["operation"] for revision in revisions], ["update", "create"])
            self.assertEqual(revisions[0]["before"]["rule"]["include_keywords"], ["timeout"])
            self.assertEqual(revisions[0]["after"]["rule"]["include_keywords"], ["handoff"])

            rollback_update = rollback_context_delivery_rule_revision(
                db_path=db_path,
                revision_id=revisions[0]["id"],
            )
            rules_after_update_rollback = list_context_delivery_rules(db_path)
            revisions_after_update_rollback = list_context_delivery_rule_revisions(
                db_path,
                rule_id="context_rule_researcher_timeout",
            )

            self.assertEqual(rollback_update.status, "rolled_back")
            self.assertEqual(rules_after_update_rollback[0]["rule"]["include_keywords"], ["timeout"])
            self.assertTrue(rules_after_update_rollback[0]["active"])
            self.assertEqual(revisions_after_update_rollback[0]["operation"], "rollback")
            self.assertEqual(revisions_after_update_rollback[0]["before"]["rule"]["include_keywords"], ["handoff"])
            self.assertEqual(revisions_after_update_rollback[0]["after"]["rule"]["include_keywords"], ["timeout"])

            with self.assertRaisesRegex(ApplyError, "context_delivery_rule_revision_not_latest"):
                rollback_context_delivery_rule_revision(db_path=db_path, revision_id=revisions[1]["id"])

    def test_rollback_create_context_delivery_rule_revision_deactivates_rule(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal("proposal_context_rule_001"),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_001")
            revisions = list_context_delivery_rule_revisions(db_path, rule_id="context_rule_researcher_timeout")

            rollback = rollback_context_delivery_rule_revision(db_path=db_path, revision_id=revisions[0]["id"])
            rules = list_context_delivery_rules(db_path, active_only=False)
            rolled_back_revisions = list_context_delivery_rule_revisions(
                db_path,
                rule_id="context_rule_researcher_timeout",
            )

            self.assertEqual(rollback.status, "rolled_back")
            self.assertFalse(rules[0]["active"])
            self.assertEqual(rolled_back_revisions[0]["operation"], "rollback")
            self.assertTrue(rolled_back_revisions[0]["before"]["active"])
            self.assertFalse(rolled_back_revisions[0]["after"]["active"])

    def test_human_locked_context_delivery_rule_blocks_update(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal("proposal_context_rule_001"),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_001")

            lock_report = set_context_delivery_rule_lock(
                db_path=db_path,
                rule_id="context_rule_researcher_timeout",
                locked=True,
                reason="preserve handoff policy",
                actor_agent_identity_id="agent_researcher_001",
            )
            self.assertTrue(lock_report.human_locked)
            self.assertTrue(list_context_delivery_rules(db_path)[0]["human_locked"])
            self.assertEqual(lock_report.reason, "preserve handoff policy")
            self.assertEqual(
                list_context_delivery_rules(db_path)[0]["human_lock_reason"],
                "preserve handoff policy",
            )

            update_proposal = _context_rule_proposal("proposal_context_rule_002", operation="update")
            update_proposal["proposed_changes"][0]["rule"]["include_keywords"] = ["handoff"]
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=update_proposal,
                schema_path=SCHEMA,
            )

            with self.assertRaisesRegex(ApplyError, "human_locked_context_delivery_rule"):
                apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_002")

            unlock_report = set_context_delivery_rule_lock(
                db_path=db_path,
                rule_id="context_rule_researcher_timeout",
                locked=False,
                reason="policy update approved",
                actor_agent_identity_id="agent_researcher_001",
            )

            self.assertFalse(unlock_report.human_locked)
            self.assertFalse(list_context_delivery_rules(db_path)[0]["human_locked"])
            self.assertEqual(unlock_report.reason, "policy update approved")
            self.assertEqual(lock_report.actor_agent_identity_id, "agent_researcher_001")
            self.assertEqual(unlock_report.actor_agent_identity_id, "agent_researcher_001")

            with self.assertRaisesRegex(ApplyError, "actor_agent_identity_not_found"):
                set_context_delivery_rule_lock(
                    db_path=db_path,
                    rule_id="context_rule_researcher_timeout",
                    locked=True,
                    actor_agent_identity_id="agent_missing",
                )

    def test_apply_rejects_missing_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(ApplyError, "proposal_not_found"):
                apply_context_proposal(db_path=db_path, proposal_id="proposal_missing_001")


if __name__ == "__main__":
    unittest.main()
