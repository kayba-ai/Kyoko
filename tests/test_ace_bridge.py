import copy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from kyoko.ace_bridge import (
    build_learning_proposals_from_ace_diff,
    check_ace_compatibility,
    prepare_native_ace_command,
    run_native_ace_command,
)
from kyoko.apply import apply_context_proposal
from kyoko.proposals import submit_learning_proposal_payload, submit_learning_proposal
from kyoko.skillbook import export_skillbook
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _ingested_db(tmpdir: str) -> Path:
    db_path = Path(tmpdir) / "kyoko.db"
    ingest_source_fixture(db_path, SOURCE_FIXTURE)
    return db_path


def _db_with_skill(tmpdir: str) -> Path:
    db_path = _ingested_db(tmpdir)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
    return db_path


class AceBridgeTests(unittest.TestCase):
    def test_ace_diff_generates_valid_native_ace_create_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _ingested_db(tmpdir)
            before = export_skillbook(db_path)
            after = copy.deepcopy(before)
            after["skills"]["context-00001"] = {
                "id": "context-00001",
                "section": "context",
                "keywords": ["fetch", "retry"],
                "issue": "Fetch timeouts are treated as final failures.",
                "insight": "Retry transient fetch timeouts once before handoff.",
                "occurrences": [
                    {
                        "trace_uid": "kyoko:run_research_topic_001",
                        "source_system": "kyoko",
                        "trace_id": "run_research_topic_001",
                        "display_name": "run:run_research_topic_001",
                        "relation": "failure",
                    }
                ],
                "active": True,
                "used_count": 0,
                "helpful_count": 0,
                "harmful_count": 0,
                "neutral_count": 0,
                "created_at": "2026-05-31T12:00:00Z",
                "updated_at": "2026-05-31T12:00:00Z",
            }
            after["sections"]["context"] = ["context-00001"]

            report = build_learning_proposals_from_ace_diff(
                db_path=db_path,
                before_skillbook=before,
                after_skillbook=after,
                schema_path=SCHEMA,
            )

            self.assertEqual(len(report.proposals), 1)
            proposal = report.proposals[0]
            self.assertEqual(proposal["producer"]["kind"], "native_ace")
            self.assertEqual(proposal["section"], "context")
            self.assertEqual(proposal["evidence_refs"][0]["entity_type"], "run")
            self.assertEqual(proposal["evidence_refs"][0]["entity_id"], "run_research_topic_001")
            self.assertEqual(proposal["proposed_changes"][0]["operation"], "create")
            self.assertTrue(proposal["proposed_changes"][0]["skill_id"].startswith("skill_proposal_native_ace_"))
            self.assertEqual(proposal["proposed_changes"][1]["type"], "eval_spec")
            self.assertEqual(
                proposal["proposed_changes"][1]["definition"]["assertions"][1]["type"],
                "replay_no_failed_spans",
            )

            submit_report = submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            self.assertEqual(submit_report.proposal_id, proposal["id"])

    def test_ace_diff_uses_fallback_evidence_when_occurrences_are_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _ingested_db(tmpdir)
            before = export_skillbook(db_path)
            after = copy.deepcopy(before)
            after["skills"]["context-00001"] = {
                "id": "context-00001",
                "section": "context",
                "keywords": ["handoff"],
                "issue": "Handoffs omit source completeness.",
                "insight": "Include source completeness in handoff payloads.",
                "occurrences": [],
                "active": True,
            }
            after["sections"]["context"] = ["context-00001"]

            report = build_learning_proposals_from_ace_diff(
                db_path=db_path,
                before_skillbook=before,
                after_skillbook=after,
                evidence_refs=[
                    {
                        "entity_type": "span",
                        "entity_id": "span_fetch_timeout_001",
                        "role": "failure",
                    }
                ],
            )

            proposal = report.proposals[0]
            self.assertEqual(proposal["evidence_refs"][0]["entity_type"], "span")
            self.assertEqual(proposal["evidence_refs"][0]["entity_id"], "span_fetch_timeout_001")

    def test_ace_compatibility_loads_export_through_public_skillbook_api(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _db_with_skill(tmpdir)
            fake_ace_root = Path(tmpdir) / "fake_ace"
            skillbook_module = fake_ace_root / "ace/core/skillbook.py"
            skillbook_module.parent.mkdir(parents=True)
            (fake_ace_root / "ace/__init__.py").write_text("")
            (fake_ace_root / "ace/core/__init__.py").write_text("")
            skillbook_module.write_text(
                "\n".join(
                    [
                        "class Skillbook:",
                        "    def __init__(self, payload):",
                        "        self.payload = payload",
                        "    @classmethod",
                        "    def from_dict(cls, payload):",
                        "        if payload.get('schema_version') != '2':",
                        "            raise ValueError('bad schema')",
                        "        return cls(payload)",
                        "    def to_dict(self):",
                        "        return self.payload",
                        "    def stats(self):",
                        "        return {'skills': len(self.payload.get('skills', {}))}",
                        "",
                    ]
                )
            )

            report = check_ace_compatibility(db_path=db_path, ace_path=fake_ace_root)

            self.assertTrue(report["available"])
            self.assertEqual(report["schema_version"], "2")
            self.assertEqual(report["roundtrip_schema_version"], "2")
            self.assertEqual(report["roundtrip_skill_count"], 1)
            self.assertEqual(report["stats"], {"skills": 1})

    def test_prepare_native_ace_command_writes_handoff_without_invoking_command(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _ingested_db(tmpdir)
            output_dir = Path(tmpdir) / "ace-prepare"

            report = prepare_native_ace_command(
                db_path,
                command=[
                    "missing-ace-command",
                    "--before",
                    "{before_path}",
                    "--after",
                    "{after_path}",
                    "--db",
                    "{db_path}",
                    "--profile",
                    "{profile_id}",
                    "--schema",
                    "{schema_path}",
                ],
                output_dir=output_dir,
                schema_path=SCHEMA,
            )

            payload = report.to_json()
            self.assertTrue(report.before_path.exists())
            self.assertTrue(report.after_path.exists())
            self.assertEqual(
                report.before_path.read_text(encoding="utf-8"),
                report.after_path.read_text(encoding="utf-8"),
            )
            self.assertTrue(report.handoff_path.exists())
            handoff = json.loads(report.handoff_path.read_text(encoding="utf-8"))
            self.assertEqual(handoff["command"], payload["command"])
            self.assertEqual(payload["command"][0], "missing-ace-command")
            self.assertEqual(payload["command"][2], str(report.before_path))
            self.assertEqual(payload["environment"]["KYOKO_ACE_AFTER_PATH"], str(report.after_path))
            self.assertFalse(payload["external_command_invoked"])
            self.assertFalse(payload["provider_backed"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertFalse(payload["live_operator_invoked"])
            self.assertFalse(payload["canonical_mutation"])
            self.assertTrue(payload["passed"])
            self.assertIsNone(payload["diff"])
            self.assertEqual(list(report.proposal_output_dir.iterdir()), [])

    def test_native_ace_command_runs_against_clone_and_imports_diff(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = _ingested_db(tmpdir)
            output_dir = Path(tmpdir) / "ace-run"
            command_path = Path(tmpdir) / "fake_ace_command.py"
            command_path.write_text(
                "\n".join(
                    [
                        "import json",
                        "import os",
                        "from pathlib import Path",
                        "after_path = Path(os.environ['KYOKO_ACE_AFTER_PATH'])",
                        "payload = json.loads(after_path.read_text(encoding='utf-8'))",
                        "payload.setdefault('skills', {})['context-00001'] = {",
                        "    'id': 'context-00001',",
                        "    'section': 'context',",
                        "    'keywords': ['fetch', 'retry'],",
                        "    'issue': 'Fetch timeouts are treated as final failures.',",
                        "    'insight': 'Retry transient fetch timeouts before handoff.',",
                        "    'occurrences': [],",
                        "    'active': True,",
                        "}",
                        "payload.setdefault('sections', {})['context'] = ['context-00001']",
                        "after_path.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')",
                        "print('mutated cloned skillbook')",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            report = run_native_ace_command(
                db_path=db_path,
                command=[sys.executable, str(command_path)],
                output_dir=output_dir,
                persist=True,
                schema_path=SCHEMA,
                evidence_refs=[
                    {
                        "entity_type": "span",
                        "entity_id": "span_fetch_timeout_001",
                        "role": "failure",
                    }
                ],
            )

            self.assertEqual(report.returncode, 0)
            self.assertTrue(report.before_path.exists())
            self.assertTrue(report.after_path.exists())
            self.assertTrue(report.handoff_path.exists())
            self.assertIsNotNone(report.report_path)
            self.assertTrue(report.report_path.exists())
            handoff = json.loads(report.handoff_path.read_text(encoding="utf-8"))
            self.assertTrue(handoff["prepared"])
            self.assertFalse(handoff["external_command_invoked"])
            self.assertFalse(handoff["provider_backed"])
            self.assertFalse(handoff["external_model_invoked"])
            self.assertEqual(handoff["environment"]["KYOKO_ACE_AFTER_PATH"], str(report.after_path))
            payload = report.to_json()
            persisted_report = json.loads(report.report_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted_report["report_path"], str(report.report_path))
            self.assertEqual(persisted_report["diff"]["proposal_ids"], list(report.diff.proposal_ids))
            self.assertTrue(persisted_report["external_command_invoked"])
            self.assertFalse(payload["provider_backed"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertIn("mutated cloned skillbook", report.stdout_tail)
            self.assertTrue(report.diff.persisted)
            self.assertEqual(len(report.diff.proposal_ids), 1)
            self.assertEqual(report.diff.proposals[0]["producer"]["kind"], "native_ace")
            self.assertEqual(report.diff.proposals[0]["evidence_refs"][0]["entity_id"], "span_fetch_timeout_001")


if __name__ == "__main__":
    unittest.main()
