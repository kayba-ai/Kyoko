import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.proposals import (
    ProposalError,
    list_learning_proposals,
    submit_learning_proposal,
    submit_learning_proposal_payload,
)
from kyoko.storage import get_database_status, ingest_source_fixture, ingest_source_payload
from tests.profile_fixtures import second_profile_payload, second_profile_proposal


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
HERMES_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/hermes-one-shot-proposal.json"
OPENCLAW_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/openclaw-local-operator-proposal.json"
VALID_HARNESS_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-harness-proposal.json"
INVALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/invalid-hallucinated-span.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ProposalTests(unittest.TestCase):
    def test_submit_valid_proposal_persists_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            report = submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            status = get_database_status(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.proposal_id, "proposal_context_timeout_001")
            self.assertEqual(report.section, "context")
            self.assertEqual(status.counts["learning_proposals"], 1)
            self.assertEqual(len(proposals), 1)
            self.assertEqual(proposals[0]["id"], "proposal_context_timeout_001")
            self.assertEqual(proposals[0]["section_label"], "Context fix")
            self.assertIn("agent-facing", proposals[0]["section_description"])
            self.assertEqual(proposals[0]["operator_confidence"], 0.82)
            self.assertEqual(proposals[0]["kyoko_confidence"], 0.66)
            self.assertEqual(proposals[0]["confidence_level"], "medium")

    def test_submit_normalizes_legacy_states_to_collapsed_model(self) -> None:
        legacy_to_canonical = {
            "draft": "pending",
            "proposed": "pending",
            "gated": "pending",
            "approved": "pending",
            "applying": "pending",
            "applied": "applied",
            "superseded": "rolled_back",
            "failed": "failed",
            "invalid": "failed",
            "rejected": "failed",
        }
        base = json.loads(VALID_PROPOSAL.read_text())
        for index, (legacy, canonical) in enumerate(legacy_to_canonical.items()):
            with TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "kyoko.db"
                ingest_source_fixture(db_path, SOURCE_FIXTURE)
                proposal = json.loads(json.dumps(base))
                proposal["id"] = f"proposal_state_norm_{index}"
                proposal["state"] = legacy
                report = submit_learning_proposal_payload(
                    db_path=db_path,
                    proposal=proposal,
                    schema_path=SCHEMA,
                )
                self.assertEqual(report.state, canonical)
                stored = list_learning_proposals(db_path)[0]
                self.assertEqual(stored["state"], canonical)

    def test_submit_valid_harness_proposal_persists_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            report = submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_HARNESS_PROPOSAL,
                schema_path=SCHEMA,
            )
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.proposal_id, "proposal_harness_timeout_check_001")
            self.assertEqual(report.section, "harness")
            self.assertEqual(proposals[0]["section"], "harness")
            self.assertEqual(proposals[0]["section_label"], "Harness fix")
            self.assertIn("check", proposals[0]["section_description"])

    def test_submit_hermes_operator_proposal_fixture_persists_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            report = submit_learning_proposal(
                db_path=db_path,
                proposal_path=HERMES_PROPOSAL,
                schema_path=SCHEMA,
            )
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.proposal_id, "proposal_hermes_span_fetch_timeout_001")
            self.assertEqual(report.section, "context")
            self.assertEqual(proposals[0]["id"], "proposal_hermes_span_fetch_timeout_001")
            self.assertEqual(proposals[0]["section_label"], "Context fix")

    def test_submit_openclaw_operator_proposal_fixture_persists_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            report = submit_learning_proposal(
                db_path=db_path,
                proposal_path=OPENCLAW_PROPOSAL,
                schema_path=SCHEMA,
            )
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.proposal_id, "proposal_openclaw_span_fetch_timeout_001")
            self.assertEqual(report.section, "context")
            self.assertEqual(proposals[0]["id"], "proposal_openclaw_span_fetch_timeout_001")
            self.assertEqual(proposals[0]["section_label"], "Context fix")

    def test_list_learning_proposals_can_filter_by_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            ingest_source_payload(
                db_path=db_path,
                fixture=second_profile_payload(),
                source_label="second-profile",
            )
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=second_profile_proposal(),
                schema_path=SCHEMA,
            )

            all_proposals = list_learning_proposals(db_path)
            second = list_learning_proposals(db_path, profile_id="profile_second")

            self.assertEqual({proposal["id"] for proposal in all_proposals}, {
                "proposal_context_timeout_001",
                "proposal_second_context",
            })
            self.assertEqual([proposal["id"] for proposal in second], ["proposal_second_context"])

    def test_default_schema_path_falls_back_to_bundled_schema_outside_repo(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            previous_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                report = submit_learning_proposal(
                    db_path=db_path,
                    proposal_path=VALID_PROPOSAL,
                    schema_path=Path("docs/schemas/learning-proposal.schema.json"),
                )
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(report.proposal_id, "proposal_context_timeout_001")

    def test_missing_custom_schema_path_is_rejected(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(ProposalError, "schema not found"):
                submit_learning_proposal(
                    db_path=db_path,
                    proposal_path=VALID_PROPOSAL,
                    schema_path=Path(tmpdir) / "missing-schema.json",
                )

    def test_submit_rejects_hallucinated_evidence(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(ProposalError, "evidence_ref_not_found"):
                submit_learning_proposal(
                    db_path=db_path,
                    proposal_path=INVALID_PROPOSAL,
                    schema_path=SCHEMA,
                )

            status = get_database_status(db_path)
            self.assertEqual(status.counts["learning_proposals"], 0)

    def test_submit_rejects_hallucinated_context_delivery_target(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            proposal = json.loads(VALID_PROPOSAL.read_text())
            proposal["id"] = "proposal_context_rule_bad_target"
            proposal["proposed_changes"] = [
                {
                    "type": "context_delivery_rule",
                    "operation": "create",
                    "target": {
                        "entity_type": "agent_identity",
                        "entity_id": "agent_missing_001",
                    },
                    "rule": {"id": "context_rule_bad_target", "mode": "prompt"},
                }
            ]

            with self.assertRaisesRegex(ProposalError, "change_target_ref_not_found"):
                submit_learning_proposal_payload(
                    db_path=db_path,
                    proposal=proposal,
                    schema_path=SCHEMA,
                )

            status = get_database_status(db_path)
            self.assertEqual(status.counts["learning_proposals"], 0)

    def test_submit_rejects_duplicate_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with self.assertRaisesRegex(ProposalError, "proposal_already_exists"):
                submit_learning_proposal(
                    db_path=db_path,
                    proposal_path=VALID_PROPOSAL,
                    schema_path=SCHEMA,
                )

            status = get_database_status(db_path)
            self.assertEqual(status.counts["learning_proposals"], 1)


if __name__ == "__main__":
    unittest.main()
