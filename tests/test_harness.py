import copy
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from kyoko.harness import (
    HarnessError,
    apply_patch_transaction,
    list_harness_target_locks,
    list_patch_transactions,
    prepare_harness_proposal,
    rollback_patch_transaction,
    set_harness_target_lock,
)
from kyoko.autonomy import update_autonomy_policy
from kyoko.blobs import put_blob
from kyoko.proposals import list_learning_proposals, submit_learning_proposal, submit_learning_proposal_payload
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_HARNESS_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-harness-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class HarnessTests(unittest.TestCase):
    def test_prepare_harness_proposal_creates_patch_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_HARNESS_PROPOSAL,
                schema_path=SCHEMA,
            )

            report = prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_timeout_eval_001",
            )
            patch_transactions = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)
            status = get_database_status(db_path)

            self.assertEqual(report.state, "pending")
            self.assertEqual(
                report.patch_transaction_ids,
                ("patch_proposal_harness_timeout_eval_001_1",),
            )
            self.assertEqual(status.counts["patch_transactions"], 1)
            self.assertEqual(status.counts["timeline_events"], 4)
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(patch_transactions[0]["status"], "ready")
            self.assertEqual(patch_transactions[0]["patch_kind"], "command_plan")
            self.assertEqual(
                patch_transactions[0]["target_paths"],
                ["evals/news_research_timeout_replay.py"],
            )
            self.assertFalse(patch_transactions[0]["rollback"]["available"])

    def test_prepare_harness_proposal_rejects_protected_path(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            proposal = json.loads(VALID_HARNESS_PROPOSAL.read_text())
            proposal = copy.deepcopy(proposal)
            proposal["id"] = "proposal_harness_protected_env_001"
            proposal["proposed_changes"][0]["target_paths"] = [".env"]
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )

            with self.assertRaisesRegex(HarnessError, "protected_path"):
                prepare_harness_proposal(
                    db_path=db_path,
                    proposal_id="proposal_harness_protected_env_001",
                )

            self.assertEqual(get_database_status(db_path).counts["patch_transactions"], 0)

    def test_prepare_generated_file_rejects_secret_like_content(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_generated_secret_001"
            proposal["producer"]["session_id"] = "operator_session_harness_secret_001"
            proposal["proposed_changes"][0]["files"][0][
                "content"
            ] = 'OPENAI_API_KEY = "sk-test_abcdefghijklmnopqrstuvwxyz"\n'
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )

            with self.assertRaisesRegex(HarnessError, "secret_scan_failed"):
                prepare_harness_proposal(
                    db_path=db_path,
                    proposal_id="proposal_harness_generated_secret_001",
                )

            self.assertEqual(get_database_status(db_path).counts["patch_transactions"], 0)

    def test_human_locked_harness_target_blocks_prepare(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            lock = set_harness_target_lock(
                db_path=db_path,
                target_path="evals/generated_timeout_eval.py",
                locked=True,
                reason="manual owner review",
                actor_agent_identity_id="agent_researcher_001",
            )

            with self.assertRaisesRegex(HarnessError, "human_locked_harness_target"):
                prepare_harness_proposal(
                    db_path=db_path,
                    proposal_id="proposal_harness_generated_eval_001",
                )

            locks = list_harness_target_locks(db_path)

            self.assertTrue(lock.human_locked)
            self.assertEqual(lock.target_path, "evals/generated_timeout_eval.py")
            self.assertEqual(lock.actor_agent_identity_id, "agent_researcher_001")
            self.assertTrue(locks[0]["human_locked"])
            self.assertEqual(locks[0]["reason"], "manual owner review")
            self.assertEqual(get_database_status(db_path).counts["patch_transactions"], 0)

            with self.assertRaisesRegex(HarnessError, "actor_agent_identity_not_found"):
                set_harness_target_lock(
                    db_path=db_path,
                    target_path="evals/generated_timeout_eval.py",
                    locked=True,
                    actor_agent_identity_id="agent_missing",
                )

    def test_prepare_harness_rejects_context_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(HarnessError, "proposal_not_found"):
                prepare_harness_proposal(
                    db_path=db_path,
                    proposal_id="proposal_missing_001",
                )

    def test_apply_and_rollback_generated_file_patch_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "evals/generated_timeout_eval.py"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, allow_repo_patch=True)
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )

            apply_report = apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                workspace_root=workspace,
            )
            applied_patches = list_patch_transactions(db_path)

            self.assertEqual(apply_report.status, "applied")
            self.assertTrue(target.exists())
            self.assertIn("TIMEOUT_SPAN_ID", target.read_text())
            self.assertEqual(applied_patches[0]["status"], "applied")
            self.assertTrue(applied_patches[0]["rollback"]["available"])
            self.assertFalse(applied_patches[0]["rollback"]["preimages"][0]["existed"])

            rollback_report = rollback_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                workspace_root=workspace,
            )
            rolled_back_patches = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(rollback_report.status, "rolled_back")
            self.assertFalse(target.exists())
            self.assertEqual(rolled_back_patches[0]["status"], "rolled_back")
            self.assertEqual(proposals[0]["state"], "rolled_back")

    def test_human_locked_harness_target_blocks_prepared_patch_apply_until_unlocked(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "evals/generated_timeout_eval.py"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, allow_repo_patch=True)
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )
            set_harness_target_lock(
                db_path=db_path,
                target_path="evals/generated_timeout_eval.py",
                locked=True,
                actor_agent_identity_id="agent_researcher_001",
            )

            with self.assertRaisesRegex(HarnessError, "human_locked_harness_target"):
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                    workspace_root=workspace,
                )
            self.assertFalse(target.exists())
            self.assertEqual(list_patch_transactions(db_path)[0]["status"], "ready")

            unlock = set_harness_target_lock(
                db_path=db_path,
                target_path="evals/generated_timeout_eval.py",
                locked=False,
                actor_agent_identity_id="agent_researcher_001",
            )
            apply_report = apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                workspace_root=workspace,
            )

            self.assertFalse(unlock.human_locked)
            self.assertEqual(unlock.actor_agent_identity_id, "agent_researcher_001")
            self.assertEqual(apply_report.status, "applied")
            self.assertTrue(target.exists())

    def test_apply_generated_file_patch_captures_existing_preimage(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            target = workspace / "evals/generated_timeout_eval.py"
            target.parent.mkdir(parents=True)
            target.write_text("previous content\n")
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, allow_repo_patch=True)
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )

            apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                workspace_root=workspace,
            )
            rollback_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                workspace_root=workspace,
            )

            self.assertEqual(target.read_text(), "previous content\n")

    def test_dirty_worktree_block_policy_rejects_unrelated_dirty_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
            (workspace / "notes.txt").write_text("unrelated dirty file\n")
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                allow_repo_patch=True,
                dirty_worktree_policy="block",
            )
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )

            with self.assertRaisesRegex(HarnessError, "dirty_worktree_blocks_harness_apply"):
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                    workspace_root=workspace,
                )

    def test_allow_touched_only_policy_allows_unrelated_dirty_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "evals/generated_timeout_eval.py"
            subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
            (workspace / "notes.txt").write_text("unrelated dirty file\n")
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                allow_repo_patch=True,
                dirty_worktree_policy="allow_touched_only",
            )
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )

            report = apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                workspace_root=workspace,
            )

            self.assertEqual(report.status, "applied")
            self.assertTrue(target.exists())

    def test_allow_touched_only_policy_rejects_dirty_target_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            target = workspace / "evals/generated_timeout_eval.py"
            target.parent.mkdir(parents=True)
            target.write_text("dirty target\n")
            subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True)
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                allow_repo_patch=True,
                dirty_worktree_policy="allow_touched_only",
            )
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )

            with self.assertRaisesRegex(HarnessError, "dirty_target_paths_block_harness_apply"):
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                    workspace_root=workspace,
                )

    def test_apply_and_rollback_unified_diff_patch_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            target = workspace / "evals/generated_timeout_eval.py"
            target.parent.mkdir(parents=True)
            target.write_text("old\n")
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            diff_blob = put_blob(
                db_path=db_path,
                profile_id="profile_news_research_001",
                kind="patch_diff",
                media_type="text/x-diff",
                data=(
                    "diff --git a/evals/generated_timeout_eval.py b/evals/generated_timeout_eval.py\n"
                    "index 1111111..2222222 100644\n"
                    "--- a/evals/generated_timeout_eval.py\n"
                    "+++ b/evals/generated_timeout_eval.py\n"
                    "@@ -1 +1,2 @@\n"
                    "-old\n"
                    "+new\n"
                    "+added\n"
                ).encode("utf-8"),
            )
            proposal = json.loads(VALID_HARNESS_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_unified_diff_001"
            proposal["producer"]["session_id"] = "operator_session_harness_unified_diff_001"
            proposal["proposed_changes"][0]["patch_kind"] = "unified_diff"
            proposal["proposed_changes"][0]["diff_ref"] = diff_blob.blob_id
            proposal["proposed_changes"][0]["target_paths"] = ["evals/generated_timeout_eval.py"]
            proposal["proposed_changes"][0]["command_plan"] = []
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, allow_repo_patch=True)
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_unified_diff_001",
            )

            apply_report = apply_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_unified_diff_001_1",
                workspace_root=workspace,
            )
            applied_patches = list_patch_transactions(db_path)

            self.assertEqual(apply_report.status, "applied")
            self.assertEqual(target.read_text(), "new\nadded\n")
            self.assertEqual(applied_patches[0]["patch_kind"], "unified_diff")
            self.assertTrue(applied_patches[0]["rollback"]["available"])
            self.assertEqual(applied_patches[0]["rollback"]["preimages"][0]["content"], "old\n")

            rollback_report = rollback_patch_transaction(
                db_path=db_path,
                patch_transaction_id="patch_proposal_harness_unified_diff_001_1",
                workspace_root=workspace,
            )

            self.assertEqual(rollback_report.status, "rolled_back")
            self.assertEqual(target.read_text(), "old\n")

    def test_apply_unified_diff_rejects_context_mismatch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            target = workspace / "evals/generated_timeout_eval.py"
            target.parent.mkdir(parents=True)
            target.write_text("unexpected\n")
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            diff_blob = put_blob(
                db_path=db_path,
                profile_id="profile_news_research_001",
                kind="patch_diff",
                media_type="text/x-diff",
                data=(
                    "--- a/evals/generated_timeout_eval.py\n"
                    "+++ b/evals/generated_timeout_eval.py\n"
                    "@@ -1 +1 @@\n"
                    "-old\n"
                    "+new\n"
                ).encode("utf-8"),
            )
            proposal = json.loads(VALID_HARNESS_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_unified_mismatch_001"
            proposal["producer"]["session_id"] = "operator_session_harness_unified_mismatch_001"
            proposal["proposed_changes"][0]["patch_kind"] = "unified_diff"
            proposal["proposed_changes"][0]["diff_ref"] = diff_blob.blob_id
            proposal["proposed_changes"][0]["target_paths"] = ["evals/generated_timeout_eval.py"]
            proposal["proposed_changes"][0]["command_plan"] = []
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, allow_repo_patch=True)
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_unified_mismatch_001",
            )

            with self.assertRaisesRegex(HarnessError, "unified_diff_context_mismatch"):
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id="patch_proposal_harness_unified_mismatch_001_1",
                    workspace_root=workspace,
                )

            self.assertEqual(target.read_text(), "unexpected\n")
            self.assertEqual(list_patch_transactions(db_path)[0]["status"], "ready")

    def test_apply_rejects_command_plan_patch_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_HARNESS_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, allow_repo_patch=True)
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_timeout_eval_001",
            )

            with self.assertRaisesRegex(HarnessError, "unsupported_patch_apply_kind"):
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id="patch_proposal_harness_timeout_eval_001_1",
                    workspace_root=workspace,
                )

    def test_apply_rejects_when_repo_patch_policy_is_off(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )
            prepare_harness_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )

            with self.assertRaisesRegex(HarnessError, "repo_patch_not_allowed"):
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id="patch_proposal_harness_generated_eval_001_1",
                    workspace_root=workspace,
                )


if __name__ == "__main__":
    unittest.main()
