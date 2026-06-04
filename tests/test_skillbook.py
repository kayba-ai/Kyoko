import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import apply_context_proposal
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.skillbook import export_skillbook, render_skillbook_prompt, write_skillbook_export
from kyoko.storage import ingest_source_fixture, ingest_source_payload
from tests.profile_fixtures import second_profile_payload, second_profile_proposal


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _prepared_db(tmpdir: str) -> Path:
    db_path = Path(tmpdir) / "kyoko.db"
    ingest_source_fixture(db_path, SOURCE_FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
    return db_path


def _context_rule_proposal() -> dict:
    proposal = json.loads(VALID_PROPOSAL.read_text())
    proposal["id"] = "proposal_context_rule_001"
    proposal["producer"]["session_id"] = "proposal_context_rule_001"
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


class SkillbookExportTests(unittest.TestCase):
    def test_export_skillbook_matches_ace_v2_shape(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _prepared_db(tmpdir)

            skillbook = export_skillbook(db_path)

            self.assertEqual(skillbook["schema_version"], "2")
            self.assertEqual(skillbook["sections"]["context"], ["skill_proposal_context_timeout_001_1"])
            self.assertEqual(skillbook["next_id"], 0)
            self.assertEqual(skillbook["similarity_decisions"], {})

            skill = skillbook["skills"]["skill_proposal_context_timeout_001_1"]
            self.assertEqual(skill["section"], "context")
            self.assertEqual(skill["keywords"], ["fetch", "timeout", "retry", "handoff", "evidence"])
            self.assertEqual(skill["helpful_count"], 0)
            self.assertTrue(skill["active"])
            self.assertEqual(skill["occurrences"][0]["trace_uid"], "kyoko:run_research_topic_001")
            self.assertEqual(skill["occurrences"][0]["source_system"], "kyoko")
            self.assertEqual(skill["occurrences"][0]["relation"], "failure")

    def test_render_skillbook_prompt_matches_agent_context_format(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _prepared_db(tmpdir)

            prompt = render_skillbook_prompt(db_path)

            self.assertIn("## context", prompt)
            self.assertIn("- [skill_proposal_context_timeout_001_1]", prompt)
            self.assertIn("Keywords: fetch, timeout, retry, handoff, evidence", prompt)
            self.assertIn("Issue: Source fetch timeouts are treated as final failures.", prompt)
            self.assertIn("Insight: Retry transient fetch failures once before handoff", prompt)
            self.assertNotIn("## harness", prompt)

    def test_render_skillbook_prompt_includes_target_delivery_rules(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _prepared_db(tmpdir)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal(),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_rule_001")

            prompt = render_skillbook_prompt(
                db_path,
                target_entity_type="agent_identity",
                target_entity_id="agent_researcher_001",
            )
            unrelated_prompt = render_skillbook_prompt(
                db_path,
                target_entity_type="agent_identity",
                target_entity_id="agent_writer_001",
            )

            self.assertIn("## context_delivery_rules", prompt)
            self.assertIn("context_rule_researcher_timeout", prompt)
            self.assertIn("include_keywords", prompt)
            self.assertNotIn("context_rule_researcher_timeout", unrelated_prompt)

    def test_target_context_is_scoped_to_inferred_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _prepared_db(tmpdir)
            ingest_source_payload(
                db_path=db_path,
                fixture=second_profile_payload(),
                source_label="second-profile",
            )
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=second_profile_proposal(),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_second_context")

            first_prompt = render_skillbook_prompt(
                db_path,
                target_entity_type="agent_identity",
                target_entity_id="agent_researcher_001",
            )
            second_prompt = render_skillbook_prompt(
                db_path,
                target_entity_type="agent_identity",
                target_entity_id="agent_second",
            )
            second_profile_prompt = render_skillbook_prompt(db_path, profile_id="profile_second")
            unknown_target_prompt = render_skillbook_prompt(
                db_path,
                target_entity_type="agent_identity",
                target_entity_id="agent_missing",
            )
            all_skillbook = export_skillbook(db_path)
            second_skillbook = export_skillbook(db_path, profile_id="profile_second")

            self.assertIn("Retry transient fetch failures once before handoff", first_prompt)
            self.assertNotIn("billing-specific", first_prompt)
            self.assertIn("billing-specific", second_prompt)
            self.assertIn("billing-specific", second_profile_prompt)
            self.assertNotIn("Retry transient fetch failures once before handoff", second_prompt)
            self.assertEqual(unknown_target_prompt, "")
            self.assertIn("skill_proposal_context_timeout_001_1", all_skillbook["skills"])
            self.assertIn("skill_proposal_second_context_1", all_skillbook["skills"])
            self.assertEqual(
                list(second_skillbook["skills"]),
                ["skill_proposal_second_context_1"],
            )

    def test_write_skillbook_export_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _prepared_db(tmpdir)
            output_path = Path(tmpdir) / "skillbook.json"

            write_skillbook_export(
                db_path,
                output_path=output_path,
                output_format="json",
            )

            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["schema_version"], "2")
            self.assertIn("skill_proposal_context_timeout_001_1", payload["skills"])


if __name__ == "__main__":
    unittest.main()
