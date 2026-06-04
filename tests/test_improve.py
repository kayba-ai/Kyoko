import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import list_skills
from kyoko.autonomy import update_autonomy_policy
from kyoko.checks import list_check_runs, list_check_specs, list_replay_runs
from kyoko.harness import list_patch_transactions
from kyoko.improve import run_improvement_loop
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.replay_adapters import register_replay_adapter
from kyoko.storage import ingest_source_fixture, ingest_source_payload


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"


class ImproveTests(unittest.TestCase):
    def test_improvement_loop_runs_check_replay_and_autonomy_for_existing_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=Path(tmpdir) / "replay",
                default_side_effect_mode="network_mocked",
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
                replay_adapter_id="fixture_replay",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.proposal_id, "proposal_context_timeout_001")
            self.assertEqual(report.check_spec_ids, ("check_proposal_context_timeout_001_1",))
            self.assertEqual(report.generated_check_spec_ids, ("check_proposal_context_timeout_001_1",))
            self.assertEqual(report.replay_runs[0]["check_run"]["status"], "passed")
            self.assertEqual(report.autonomy.decisions[0].action, "applied")
            self.assertEqual(
                report.autonomy.decisions[0].applied_skill_ids,
                ("skill_proposal_context_timeout_001_1",),
            )
            self.assertEqual(len(list_check_specs(db_path)), 1)
            self.assertEqual(len(list_replay_runs(db_path)), 1)
            self.assertEqual(len(list_check_runs(db_path)), 1)
            self.assertEqual(len(list_skills(db_path)), 1)

    def test_improvement_loop_defaults_to_latest_enabled_replay_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="aaa_replay",
                name="AAA replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=Path(tmpdir) / "aaa-replay",
                default_side_effect_mode="network_mocked",
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="zzz_replay",
                name="ZZZ replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=Path(tmpdir) / "zzz-replay",
                default_side_effect_mode="network_mocked",
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.replay_runs[0]["adapter_id"], "zzz_replay")
            self.assertEqual(report.replay_runs[0]["check_run"]["status"], "passed")
            self.assertEqual(report.autonomy.decisions[0].action, "applied")

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
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=Path(tmpdir) / "replay",
                default_side_effect_mode="network_mocked",
            )
            update_autonomy_policy(
                db_path=db_path,
                harness_mode="autonomous",
                allow_repo_patch=True,
            )

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
                replay_adapter_id="fixture_replay",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
                harness_workspace_root=workspace,
            )
            patches = list_patch_transactions(db_path)

            self.assertEqual(
                report.generated_check_spec_ids,
                ("check_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(report.replay_runs[0]["check_run"]["status"], "passed")
            self.assertEqual(report.autonomy.decisions[0].action, "applied")
            self.assertEqual(
                report.autonomy.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(patches[0]["status"], "applied")
            self.assertTrue(target.exists())
            self.assertIn("TIMEOUT_SPAN_ID", target.read_text())

    def test_improvement_loop_preserves_profile_root_for_harness_patch_after_replay(self) -> None:
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
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=Path(tmpdir) / "replay",
                default_side_effect_mode="network_mocked",
            )
            update_autonomy_policy(
                db_path=db_path,
                harness_mode="autonomous",
                allow_repo_patch=True,
            )

            report = run_improvement_loop(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
                replay_adapter_id="fixture_replay",
                output_dir=Path(tmpdir) / "improve",
                schema_path=SCHEMA,
            )

            self.assertEqual(report.replay_runs[0]["check_run"]["status"], "passed")
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
            self.assertEqual(report.proposal_id, "proposal_mock_span_openclaw_error_session_failure_1")
            self.assertEqual(report.generated_check_spec_ids, ("check_proposal_mock_span_openclaw_error_session_failure_1_1",))
            self.assertEqual(report.replay_runs, ())
            self.assertIsNone(report.autonomy)
            self.assertTrue(Path(report.source_import.to_json()["import"]["normalized_path"]).exists())


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
