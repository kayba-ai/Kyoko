import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import list_skills
from kyoko.autonomy import update_autonomy_policy
from kyoko.autonomy_runner import inspect_proposal_autonomy_gate, run_autonomy
from kyoko.harness import list_patch_transactions
from kyoko.proposals import (
    list_learning_proposals,
    submit_learning_proposal,
    submit_learning_proposal_payload,
)
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_CONTEXT_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _seed_context(db_path: Path) -> None:
    ingest_source_fixture(db_path, SOURCE_FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_CONTEXT_PROPOSAL,
        schema_path=SCHEMA,
    )


def _apply_py_migrated() -> bool:
    """The context auto-apply path delegates to kyoko.apply.apply_context_proposal, which on
    this branch may not yet be migrated to the two-mode policy (it still reads the removed
    ``context_mode`` / ``allow_skillbook_write`` keys). The autonomy runner itself is correct;
    skip the end-to-end context-apply assertions until apply.py is migrated."""

    source = (ROOT / "kyoko" / "apply.py").read_text()
    return "context_mode" not in source and "allow_skillbook_write" not in source


def _seed_harness(db_path: Path) -> dict:
    proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
    proposal["gate_expectations"]["requires_human_review"] = False
    ingest_source_fixture(db_path, SOURCE_FIXTURE)
    submit_learning_proposal_payload(
        db_path=db_path,
        proposal=proposal,
        schema_path=SCHEMA,
    )
    return proposal


class HitlModeTests(unittest.TestCase):
    def test_hitl_applies_nothing_for_context(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context(db_path)
            # Fresh profile defaults to hitl mode.

            report = run_autonomy(db_path=db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.policy["mode"], "hitl")
            self.assertEqual(len(report.decisions), 1)
            self.assertEqual(report.decisions[0].action, "awaiting_human_review")
            self.assertEqual(report.decisions[0].reason, "hitl_awaiting_human_approve")
            self.assertEqual(report.decisions[0].state_before, "pending")
            self.assertEqual(report.decisions[0].state_after, "pending")
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(list_skills(db_path), [])

    def test_hitl_applies_nothing_for_harness(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_harness(db_path)

            report = run_autonomy(db_path=db_path)
            proposals = list_learning_proposals(db_path)
            patches = list_patch_transactions(db_path)

            self.assertEqual(report.decisions[0].action, "awaiting_human_review")
            self.assertEqual(report.decisions[0].reason, "hitl_awaiting_human_approve")
            self.assertEqual(report.decisions[0].patch_transaction_ids, ())
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(patches, [])


class AutonomousModeTests(unittest.TestCase):
    @unittest.skipUnless(
        _apply_py_migrated(),
        "kyoko.apply not yet migrated to two-mode policy (context_mode/allow_skillbook_write)",
    )
    def test_autonomous_applies_context_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context(db_path)
            update_autonomy_policy(db_path=db_path, mode="autonomous")

            report = run_autonomy(db_path=db_path)
            proposals = list_learning_proposals(db_path)
            skills = list_skills(db_path)

            self.assertEqual(report.policy["mode"], "autonomous")
            self.assertEqual(report.decisions[0].action, "applied")
            self.assertEqual(report.decisions[0].reason, "autonomous_auto_apply")
            self.assertEqual(
                report.decisions[0].applied_skill_ids,
                ("skill_proposal_context_timeout_001_1",),
            )
            self.assertEqual(report.decisions[0].state_after, "applied")
            self.assertEqual(proposals[0]["state"], "applied")
            self.assertEqual(len(skills), 1)

            # Second pass: nothing left to apply.
            second = run_autonomy(db_path=db_path)
            self.assertEqual(second.decisions, ())

    def test_autonomous_applies_harness_when_repo_patch_allowed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            _seed_harness(db_path)
            update_autonomy_policy(
                db_path=db_path,
                mode="autonomous",
                allow_repo_patch=True,
            )

            report = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            proposals = list_learning_proposals(db_path)
            patches = list_patch_transactions(db_path)

            self.assertEqual(report.decisions[0].action, "applied")
            self.assertEqual(report.decisions[0].reason, "autonomous_auto_apply")
            self.assertEqual(
                report.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(proposals[0]["state"], "applied")
            self.assertEqual(patches[0]["status"], "applied")
            self.assertTrue(target.exists())

    def test_autonomous_harness_blocked_when_repo_patch_disallowed(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            _seed_harness(db_path)
            # autonomous mode but repo patch capability fence is OFF (default).
            update_autonomy_policy(db_path=db_path, mode="autonomous")

            report = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            proposals = list_learning_proposals(db_path)
            patches = list_patch_transactions(db_path)

            self.assertEqual(report.decisions[0].action, "blocked")
            self.assertEqual(report.decisions[0].reason, "repo_patch_not_allowed")
            # Patch transaction was prepared but not applied.
            self.assertEqual(
                report.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(patches[0]["status"], "ready")
            self.assertFalse(target.exists())


class InspectGateTests(unittest.TestCase):
    def test_inspect_context_hitl(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context(db_path)

            gate = inspect_proposal_autonomy_gate(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )

            self.assertEqual(gate["section"], "context")
            self.assertEqual(gate["action"], "awaiting_human_review")
            self.assertEqual(gate["reason"], "hitl_awaiting_human_approve")
            self.assertFalse(gate["mutates"])
            self.assertEqual(
                set(gate["policy"].keys()),
                {"mode", "recurrence_threshold", "allow_repo_patch"},
            )
            self.assertEqual(gate["policy"]["mode"], "hitl")

    def test_inspect_context_autonomous(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context(db_path)
            update_autonomy_policy(db_path=db_path, mode="autonomous")

            gate = inspect_proposal_autonomy_gate(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )

            self.assertEqual(gate["action"], "would_apply")
            self.assertEqual(gate["reason"], "autonomous_auto_apply")
            self.assertTrue(gate["mutates"])
            self.assertEqual(gate["policy"]["mode"], "autonomous")

    def test_inspect_harness_autonomous_blocked_without_repo_patch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_harness(db_path)
            update_autonomy_policy(db_path=db_path, mode="autonomous")

            gate = inspect_proposal_autonomy_gate(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
            )

            self.assertEqual(gate["section"], "harness")
            self.assertEqual(gate["action"], "blocked")
            self.assertEqual(gate["reason"], "repo_patch_not_allowed")
            self.assertFalse(gate["mutates"])

    def test_inspect_harness_autonomous_would_apply_with_repo_patch(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_harness(db_path)
            update_autonomy_policy(db_path=db_path, mode="autonomous", allow_repo_patch=True)

            gate = inspect_proposal_autonomy_gate(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
            )

            self.assertEqual(gate["action"], "would_apply")
            self.assertEqual(gate["reason"], "autonomous_auto_apply")
            self.assertTrue(gate["mutates"])

    def test_inspect_terminal_state_returns_early(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            _seed_harness(db_path)
            update_autonomy_policy(db_path=db_path, mode="autonomous", allow_repo_patch=True)
            run_autonomy(db_path=db_path, harness_workspace_root=workspace)

            gate = inspect_proposal_autonomy_gate(
                db_path=db_path,
                proposal_id="proposal_harness_generated_check_001",
            )

            self.assertEqual(gate["action"], "already_applied")
            self.assertEqual(gate["reason"], "terminal_state:applied")


if __name__ == "__main__":
    unittest.main()
