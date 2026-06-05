import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import apply_context_proposal, list_skills
from kyoko.autonomy import update_autonomy_policy
from kyoko.checks import generate_checks_for_proposal, run_check
from kyoko.autonomy_runner import run_autonomy
from kyoko.proposals import (
    list_learning_proposals,
    submit_learning_proposal_payload,
    validate_learning_proposal,
)
from kyoko.skillbook_manager import (
    ConsolidationReport,
    SkillbookManagerError,
    build_consolidation_proposal,
    detect_duplicate_skill_groups,
    run_skillbook_consolidation,
)
from kyoko.storage import connect, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
PROFILE_ID = "profile_news_research_001"


def _skill_proposal(proposal_id: str, *, span_id: str, keywords, issue=None) -> dict:
    """A context proposal that CREATEs one skill (so applying it seeds the skillbook)."""
    base = json.loads(VALID_PROPOSAL.read_text())
    base["id"] = proposal_id
    base["producer"]["session_id"] = proposal_id
    base["title"] = f"Seed skill {proposal_id}"
    issue_text = issue or "Source fetch timeouts are treated as final failures."
    base["proposed_changes"] = [
        {
            "type": "skillbook_update",
            "operation": "create",
            "section": "context",
            "issue": issue_text,
            "insight": "Retry transient fetch failures once before handoff.",
            "keywords": keywords,
            "occurrence_refs": [
                {"entity_type": "span", "entity_id": span_id, "role": "failure"}
            ],
        }
    ]
    base["evidence_refs"] = [
        {"entity_type": "span", "entity_id": span_id, "role": "failure"}
    ]
    return base


def _seed_two_duplicate_skills(db_path: Path) -> None:
    ingest_source_fixture(db_path, SOURCE_FIXTURE)
    # Two near-duplicate skills: same section + same normalized keyword set ("Fetch"/"fetch").
    for proposal_id in ("proposal_dup_a_001", "proposal_dup_b_001"):
        proposal = _skill_proposal(
            proposal_id,
            span_id="span_fetch_timeout_001",
            keywords=["Fetch", "timeout", "retry"],
        )
        submit_learning_proposal_payload(db_path=db_path, proposal=proposal, schema_path=SCHEMA)
        apply_context_proposal(db_path=db_path, proposal_id=proposal_id)


class DetectDuplicateGroupTests(unittest.TestCase):
    def test_detects_keyword_duplicate_group(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_two_duplicate_skills(db_path)

            groups = detect_duplicate_skill_groups(db_path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(
                [skill["id"] for skill in groups[0]],
                ["skill_proposal_dup_a_001_1", "skill_proposal_dup_b_001_1"],
            )

    def test_detects_issue_text_duplicate_group(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            # Same issue text but DIFFERENT keyword sets — grouped on identical issue text.
            for proposal_id, keywords in (
                ("proposal_iss_a_001", ["alpha"]),
                ("proposal_iss_b_001", ["beta"]),
            ):
                proposal = _skill_proposal(
                    proposal_id,
                    span_id="span_fetch_timeout_001",
                    keywords=keywords,
                    issue="The agent gave up after one fetch timeout.",
                )
                submit_learning_proposal_payload(
                    db_path=db_path, proposal=proposal, schema_path=SCHEMA
                )
                apply_context_proposal(db_path=db_path, proposal_id=proposal_id)

            groups = detect_duplicate_skill_groups(db_path)
            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0]), 2)

    def test_distinct_skills_produce_no_groups(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            proposal = _skill_proposal(
                "proposal_solo_001",
                span_id="span_fetch_timeout_001",
                keywords=["only", "one"],
                issue="A unique single issue.",
            )
            submit_learning_proposal_payload(
                db_path=db_path, proposal=proposal, schema_path=SCHEMA
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_solo_001")

            self.assertEqual(detect_duplicate_skill_groups(db_path), [])


class BuildConsolidationProposalTests(unittest.TestCase):
    def test_builds_valid_merge_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_two_duplicate_skills(db_path)
            groups = detect_duplicate_skill_groups(db_path)

            proposal = build_consolidation_proposal(groups[0], profile_id=PROFILE_ID)

            self.assertEqual(
                proposal["id"], "proposal_consolidate_skill_proposal_dup_a_001_1"
            )
            self.assertEqual(proposal["section"], "context")
            # Decomposes to update(winner) + deactivate(loser) + link_occurrence(winner).
            ops = [
                (change["operation"], change.get("skill_id"))
                for change in proposal["proposed_changes"]
            ]
            self.assertEqual(
                ops,
                [
                    ("update", "skill_proposal_dup_a_001_1"),
                    ("deactivate", "skill_proposal_dup_b_001_1"),
                    ("link_occurrence", "skill_proposal_dup_a_001_1"),
                ],
            )
            self.assertEqual(
                proposal["gate_expectations"]["requires_check_level"], "L1_repeated"
            )
            self.assertFalse(proposal["gate_expectations"]["requires_replay"])

            with connect(db_path) as connection:
                result = validate_learning_proposal(
                    connection=connection, proposal=proposal, schema_path=SCHEMA
                )
            self.assertTrue(result.ok, result.errors)

    def test_single_skill_group_raises(self) -> None:
        with self.assertRaises(SkillbookManagerError):
            build_consolidation_proposal(
                [{"id": "skill_only", "section": "context"}], profile_id=PROFILE_ID
            )


class RunConsolidationTests(unittest.TestCase):
    def test_mock_submits_pending_consolidation_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_two_duplicate_skills(db_path)

            report = run_skillbook_consolidation(
                db_path=db_path,
                output_dir=Path(tmpdir) / "out",
                profile_id=PROFILE_ID,
            )

            self.assertIsInstance(report, ConsolidationReport)
            self.assertEqual(report.duplicate_group_count, 1)
            self.assertEqual(
                report.proposal_ids,
                ("proposal_consolidate_skill_proposal_dup_a_001_1",),
            )
            self.assertEqual(report.applied_proposal_ids, ())

            proposals = list_learning_proposals(db_path)
            consolidation = next(
                p for p in proposals if p["id"].startswith("proposal_consolidate_")
            )
            self.assertEqual(consolidation["state"], "pending")
            # Skillbook untouched: nothing applied without the gate.
            self.assertTrue(all(skill["active"] for skill in list_skills(db_path)))

    def test_no_duplicates_returns_empty_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            proposal = _skill_proposal(
                "proposal_solo_001",
                span_id="span_fetch_timeout_001",
                keywords=["unique"],
                issue="A unique single issue.",
            )
            submit_learning_proposal_payload(
                db_path=db_path, proposal=proposal, schema_path=SCHEMA
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_solo_001")

            report = run_skillbook_consolidation(db_path=db_path, profile_id=PROFILE_ID)

            self.assertEqual(report.duplicate_group_count, 0)
            self.assertEqual(report.proposal_ids, ())
            self.assertEqual(report.applied_proposal_ids, ())
            self.assertIn("no_duplicate_skill_groups", report.notes)

    def test_autonomous_gate_applies_merge_after_check_passes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_two_duplicate_skills(db_path)
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            # First pass: submit pending + generate the gate check (still L0 -> blocked).
            first = run_skillbook_consolidation(
                db_path=db_path,
                output_dir=Path(tmpdir) / "o1",
                profile_id=PROFILE_ID,
                run_autonomy_after=True,
            )
            self.assertEqual(first.applied_proposal_ids, ())
            consolidation_id = first.proposal_ids[0]

            # Promote the deterministic check to L1 by running it twice (same passing status).
            check_spec_id = f"check_{consolidation_id}_1"
            self.assertEqual(
                run_check(db_path=db_path, check_spec_id=check_spec_id).status, "passed"
            )
            promoted = run_check(db_path=db_path, check_spec_id=check_spec_id)
            self.assertEqual(promoted.status, "passed")
            self.assertEqual(promoted.promoted_trust_level, "L1_repeated")

            # Second pass: the gate now applies the merge.
            applied = run_autonomy(db_path=db_path, profile_id=PROFILE_ID)
            decision = next(
                d for d in applied.decisions if d.proposal_id == consolidation_id
            )
            self.assertEqual(decision.action, "applied")

            skills = {skill["id"]: skill for skill in list_skills(db_path)}
            winner = skills["skill_proposal_dup_a_001_1"]
            loser = skills["skill_proposal_dup_b_001_1"]
            self.assertTrue(winner["active"])
            self.assertFalse(loser["active"])
            # Winner carries the unioned (normalized) keywords.
            self.assertEqual(set(winner["keywords"]), {"fetch", "timeout", "retry"})

    def test_run_autonomy_after_reports_applied_when_check_ready(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_two_duplicate_skills(db_path)
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            first = run_skillbook_consolidation(
                db_path=db_path,
                output_dir=Path(tmpdir) / "o1",
                profile_id=PROFILE_ID,
                run_autonomy_after=True,
            )
            consolidation_id = first.proposal_ids[0]
            check_spec_id = f"check_{consolidation_id}_1"
            run_check(db_path=db_path, check_spec_id=check_spec_id)
            run_check(db_path=db_path, check_spec_id=check_spec_id)

            # Re-run consolidation: idempotent submit, gate now applies, report reflects it.
            second = run_skillbook_consolidation(
                db_path=db_path,
                output_dir=Path(tmpdir) / "o2",
                profile_id=PROFILE_ID,
                run_autonomy_after=True,
            )
            self.assertEqual(second.applied_proposal_ids, (consolidation_id,))


if __name__ == "__main__":
    unittest.main()
