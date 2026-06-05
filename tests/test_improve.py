import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import list_skills
from kyoko.autonomy import update_autonomy_policy
from kyoko.harness import list_patch_transactions
from kyoko.improve import run_improvement_loop
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.storage import ingest_source_fixture, ingest_source_payload


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ImproveTests(unittest.TestCase):
    def test_improvement_loop_auto_applies_existing_proposal_in_autonomous_mode(self) -> None:
        # Spec 0018: the loop no longer wires check/replay. A direct proposal skips gate #1
        # and, in autonomous mode, gate #2 auto-applies it (validation is post-hoc).
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, mode="autonomous")

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.proposal_id, "proposal_context_timeout_001")
            self.assertEqual(report.autonomy.decisions[0].action, "applied")
            self.assertEqual(report.autonomy.decisions[0].reason, "autonomous_auto_apply")
            self.assertEqual(
                report.autonomy.decisions[0].applied_skill_ids,
                ("skill_proposal_context_timeout_001_1",),
            )
            self.assertEqual(len(list_skills(db_path)), 1)

    def test_improvement_loop_holds_existing_proposal_in_hitl_mode(self) -> None:
        # In HITL (default) gate #2 applies nothing: the proposal awaits a human approve.
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.proposal_id, "proposal_context_timeout_001")
            self.assertEqual(report.autonomy.decisions[0].action, "awaiting_human_review")
            self.assertEqual(
                report.autonomy.decisions[0].reason, "hitl_awaiting_human_approve"
            )
            # Nothing applied: skillbook stays empty.
            self.assertEqual(len(list_skills(db_path)), 0)

    def test_improvement_loop_applies_harness_patch_with_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                mode="autonomous",
                allow_repo_patch=True,
            )

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
                harness_workspace_root=workspace,
            )
            patches = list_patch_transactions(db_path)

            self.assertEqual(report.autonomy.decisions[0].action, "applied")
            self.assertEqual(
                report.autonomy.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(patches[0]["status"], "applied")
            self.assertTrue(target.exists())
            self.assertIn("TIMEOUT_SPAN_ID", target.read_text())

    def test_improvement_loop_preserves_profile_root_for_harness_patch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            ingest_source_payload(
                db_path=db_path,
                fixture=_source_fixture_with_root(workspace),
                source_label="source-with-profile-root",
            )
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                mode="autonomous",
                allow_repo_patch=True,
            )

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.autonomy.decisions[0].action, "applied")
            self.assertTrue(target.exists())
            self.assertIn("TIMEOUT_SPAN_ID", target.read_text())

    def test_improvement_loop_can_import_discovered_source_before_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            home = tmp_path / "home"
            _write_failed_openclaw_session(home)

            report = run_improvement_loop(
                db_path=db_path,
                source_candidate_id="openclaw_main",
                source_home=home,
                source_import_output_dir=tmp_path / "normalized",
                output_dir=tmp_path / "improve",
                schema_path=SCHEMA,
                run_autonomy_after=False,
            )

            self.assertIsNotNone(report.source_import)
            self.assertEqual(report.source_import.candidate["id"], "openclaw_main")
            self.assertEqual(report.profile_id, "profile_openclaw_main")
            # Default mode is `hitl`: analysis surfaces+diagnoses the issue but gate #1 holds
            # it for a human to accept — no proposal is authored this run.
            self.assertIsNone(report.proposal_id)
            self.assertEqual(report.proposal_ids, ())
            self.assertIsNotNone(report.analyze)
            self.assertEqual(len(report.analyze.new_issue_ids), 1)
            self.assertIsNone(report.autonomy)
            self.assertEqual(len(report.gate1_outcomes), 1)
            self.assertEqual(report.gate1_outcomes[0]["mode"], "hitl")
            self.assertFalse(report.gate1_outcomes[0]["allow"])
            self.assertEqual(
                report.gate1_outcomes[0]["reason"], "hitl_awaiting_human_accept"
            )
            self.assertTrue(
                any(
                    note.startswith("gate1_hold:")
                    and note.endswith(":hitl_awaiting_human_accept")
                    for note in report.notes
                )
            )
            self.assertTrue(Path(report.source_import.to_json()["import"]["normalized_path"]).exists())

    def test_improvement_loop_autonomous_authors_proposal_at_recurrence_threshold(self) -> None:
        # Spec 0018 gate #1: in autonomous mode analysis surfaces the issue and the loop
        # authors a proposal only once recurrence_count >= recurrence_threshold. We set the
        # threshold to 1 so a freshly surfaced issue (recurrence_count == 1) clears the gate;
        # the proposal then auto-applies through gate #2.
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            update_autonomy_policy(
                db_path=db_path, mode="autonomous", recurrence_threshold=1
            )

            report = run_improvement_loop(
                db_path=db_path,
                output_dir=tmp_path / "improve",
                schema_path=SCHEMA,
                run_autonomy_after=True,
            )

            self.assertIsNotNone(report.analyze)
            self.assertEqual(len(report.analyze.new_issue_ids), 1)
            self.assertEqual(len(report.proposal_ids), 1)
            self.assertEqual(report.proposal_id, report.proposal_ids[0])
            self.assertIsNotNone(report.autonomy)
            self.assertEqual(report.gate1_outcomes[0]["mode"], "autonomous")
            self.assertTrue(report.gate1_outcomes[0]["allow"])

    def test_improvement_loop_autonomous_holds_below_recurrence_threshold(self) -> None:
        # Below threshold the autonomous gate #1 holds: the issue is surfaced but no proposal
        # is authored until the failure recurs enough times in production.
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            update_autonomy_policy(
                db_path=db_path, mode="autonomous", recurrence_threshold=3
            )

            report = run_improvement_loop(
                db_path=db_path,
                output_dir=tmp_path / "improve",
                schema_path=SCHEMA,
                run_autonomy_after=True,
            )

            self.assertEqual(len(report.analyze.new_issue_ids), 1)
            # recurrence_count starts at 1 < threshold 3 -> nothing authored.
            self.assertEqual(report.proposal_ids, ())
            self.assertIsNone(report.proposal_id)
            self.assertEqual(report.gate1_outcomes[0]["mode"], "autonomous")
            self.assertFalse(report.gate1_outcomes[0]["allow"])
            self.assertTrue(
                report.gate1_outcomes[0]["reason"].startswith(
                    "recurrence_below_threshold:"
                )
            )


def _source_fixture_with_root(root_path: Path) -> dict:
    fixture = json.loads(SOURCE_FIXTURE.read_text())
    fixture["profile"]["root_path"] = str(root_path)
    return fixture


def _write_failed_openclaw_session(home: Path) -> Path:
    sessions_dir = home / ".openclaw" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    store = {
        "agent:main:error-session": {
            "sessionId": "error-session",
            "title": "Failing OpenClaw session",
            "workspacePath": str(home / "workspace"),
            "createdAt": "2026-05-31T12:00:00Z",
            "updatedAt": "2026-05-31T12:01:00Z",
            "transcriptPath": "error-session.jsonl",
        }
    }
    (sessions_dir / "sessions.json").write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    records = [
        {
            "id": "failure-1",
            "type": "error",
            "agentId": "main",
            "error": "source fetch timeout",
            "timestamp": "2026-05-31T12:01:00Z",
        }
    ]
    transcript = "\n".join(json.dumps(record, sort_keys=True) for record in records)
    (sessions_dir / "error-session.jsonl").write_text(transcript + "\n", encoding="utf-8")
    return sessions_dir


if __name__ == "__main__":
    unittest.main()
