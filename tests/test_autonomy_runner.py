import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.apply import (
    list_context_delivery_rules,
    list_context_delivery_rule_revisions,
    list_skill_revisions,
    list_skills,
)
from kyoko.autonomy import update_autonomy_policy
from kyoko.autonomy_runner import run_autonomy
from kyoko.checks import (
    approve_check_spec,
    complete_replay_from_fixture,
    complete_replay_from_payload,
    create_replay_run,
    list_check_specs,
    run_check,
)
from kyoko.harness import list_patch_transactions, set_harness_target_lock
from kyoko.proposals import (
    list_learning_proposals,
    submit_learning_proposal,
    submit_learning_proposal_payload,
)
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_CONTEXT_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_HARNESS_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-harness-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class AutonomyRunnerTests(unittest.TestCase):
    def test_propose_mode_does_not_mutate_context_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_CONTEXT_PROPOSAL,
                schema_path=SCHEMA,
            )

            report = run_autonomy(db_path=db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.decisions[0].action, "awaiting_human_review")
            self.assertEqual(report.decisions[0].reason, "context_policy_propose")
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(list_check_specs(db_path), [])
            self.assertEqual(list_skills(db_path), [])

    def test_autonomous_context_waits_for_check_gate_then_applies(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_CONTEXT_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            gated = run_autonomy(db_path=db_path)
            check_specs = list_check_specs(db_path)
            proposals_after_gate = list_learning_proposals(db_path)

            self.assertEqual(gated.decisions[0].action, "gated")
            self.assertEqual(gated.decisions[0].reason, "missing_check_run")
            self.assertEqual(gated.decisions[0].check_spec_ids, ("check_proposal_context_timeout_001_1",))
            self.assertEqual(proposals_after_gate[0]["state"], "pending")
            self.assertEqual(len(check_specs), 1)
            self.assertEqual(list_skills(db_path), [])

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
            )
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )
            check_run = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
                replay_run_id=replay.replay_run_id,
            )
            self.assertEqual(check_run.status, "passed")
            self.assertEqual(check_run.promoted_trust_level, "L2_regression")

            applied = run_autonomy(db_path=db_path)
            skills = list_skills(db_path)
            proposals_after_apply = list_learning_proposals(db_path)

            self.assertEqual(applied.decisions[0].action, "applied")
            self.assertEqual(applied.decisions[0].reason, "check_gate_passed")
            self.assertEqual(
                applied.decisions[0].applied_skill_ids,
                ("skill_proposal_context_timeout_001_1",),
            )
            self.assertEqual(proposals_after_apply[0]["state"], "applied")
            self.assertEqual(len(skills), 1)

    def test_smoke_run_check_does_not_satisfy_autonomy_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            proposal = json.loads(VALID_CONTEXT_PROPOSAL.read_text())
            proposal["id"] = "proposal_context_smoke_only_001"
            proposal["producer"]["session_id"] = "proposal_context_smoke_only_001"
            proposal["proposed_changes"][-1]["name"] = "smoke check retry replay output"
            proposal["proposed_changes"][-1]["check_type"] = "smoke_run"
            proposal["proposed_changes"][-1]["definition"] = {
                "target": {
                    "entity_type": "span",
                    "entity_id": "span_fetch_timeout_001",
                },
                "min_spans": 2,
                "min_handoffs": 1,
                "no_failed_spans": True,
            }
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            gated = run_autonomy(db_path=db_path)
            self.assertEqual(gated.decisions[0].action, "gated")
            self.assertEqual(gated.decisions[0].reason, "unsupported_gate_check_type:smoke_run")

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_context_smoke_only_001_1",
            )
            replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_fixture["replay"]["replay_run_id"] = replay.replay_run_id
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=replay_fixture,
                source_label="context-smoke-run-replay-fixture",
            )
            check_run = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_smoke_only_001_1",
                replay_run_id=replay.replay_run_id,
            )
            approve_check_spec(
                db_path=db_path,
                check_spec_id="check_proposal_context_smoke_only_001_1",
                reason="reviewed smoke check",
            )

            still_gated = run_autonomy(db_path=db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(check_run.status, "passed")
            self.assertIsNone(check_run.promoted_trust_level)
            self.assertEqual(still_gated.decisions[0].action, "gated")
            self.assertEqual(still_gated.decisions[0].reason, "unsupported_gate_check_type:smoke_run")
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(list_skills(db_path), [])

    def test_regression_replay_check_satisfies_context_autonomy_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            proposal = json.loads(VALID_CONTEXT_PROPOSAL.read_text())
            proposal["id"] = "proposal_context_regression_replay_001"
            proposal["producer"]["session_id"] = "proposal_context_regression_replay_001"
            proposal["proposed_changes"][-1]["check_type"] = "regression_replay"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            gated = run_autonomy(db_path=db_path)
            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_context_regression_replay_001_1",
            )
            replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_fixture["replay"]["replay_run_id"] = replay.replay_run_id
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=replay_fixture,
                source_label="context-regression-replay-fixture",
            )
            check_run = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_regression_replay_001_1",
                replay_run_id=replay.replay_run_id,
            )

            applied = run_autonomy(db_path=db_path)

            self.assertEqual(gated.decisions[0].action, "gated")
            self.assertEqual(gated.decisions[0].reason, "missing_check_run")
            self.assertEqual(check_run.status, "passed")
            self.assertEqual(check_run.promoted_trust_level, "L2_regression")
            self.assertEqual(applied.decisions[0].action, "applied")
            self.assertEqual(applied.decisions[0].reason, "check_gate_passed")
            self.assertEqual(list_learning_proposals(db_path)[0]["state"], "applied")
            self.assertEqual(len(list_skills(db_path)), 1)

    def test_recorded_judge_check_does_not_satisfy_autonomy_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            proposal = json.loads(VALID_CONTEXT_PROPOSAL.read_text())
            proposal["id"] = "proposal_context_judge_only_001"
            proposal["producer"]["session_id"] = "proposal_context_judge_only_001"
            proposal["proposed_changes"][-1]["check_type"] = "judge"
            proposal["proposed_changes"][-1]["definition"] = {
                "rubric": "Recovered source evidence is complete and dated.",
                "judgment": {
                    "verdict": "passed",
                    "judge": "operator_review_fixture",
                    "reasoning": "The replay evidence is credible.",
                },
            }
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")

            gated = run_autonomy(db_path=db_path)
            check_run = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_judge_only_001_1",
            )
            approve_check_spec(
                db_path=db_path,
                check_spec_id="check_proposal_context_judge_only_001_1",
                reason="reviewed recorded judge output",
            )
            still_gated = run_autonomy(db_path=db_path)

            self.assertEqual(gated.decisions[0].action, "gated")
            self.assertEqual(gated.decisions[0].reason, "unsupported_gate_check_type:judge")
            self.assertEqual(check_run.status, "passed")
            self.assertIsNone(check_run.promoted_trust_level)
            self.assertEqual(still_gated.decisions[0].action, "gated")
            self.assertEqual(still_gated.decisions[0].reason, "unsupported_gate_check_type:judge")
            self.assertEqual(list_learning_proposals(db_path)[0]["state"], "pending")
            self.assertEqual(list_skills(db_path), [])

    def test_context_regression_rolls_back_created_skill_when_policy_enabled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_CONTEXT_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            run_autonomy(db_path=db_path)

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
            )
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )
            run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
                replay_run_id=replay.replay_run_id,
            )
            applied = run_autonomy(db_path=db_path)
            self.assertEqual(applied.decisions[0].action, "applied")
            self.assertTrue(list_skills(db_path)[0]["active"])

            failed = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
            )
            self.assertEqual(failed.status, "failed")

            rollback = run_autonomy(db_path=db_path)
            skills = list_skills(db_path)
            revisions = list_skill_revisions(db_path, skill_id="skill_proposal_context_timeout_001_1")
            proposals = list_learning_proposals(db_path)

            self.assertEqual(rollback.decisions[0].action, "rolled_back")
            self.assertEqual(rollback.decisions[0].check_run_ids, (failed.check_run_id,))
            self.assertTrue(rollback.decisions[0].reason.startswith("regression_check_failed:"))
            self.assertEqual(proposals[0]["state"], "failed")
            self.assertFalse(skills[0]["active"])
            self.assertEqual(revisions[0]["operation"], "rollback")
            self.assertTrue(revisions[0]["before"]["active"])
            self.assertFalse(revisions[0]["after"]["active"])

    def test_context_regression_rolls_back_context_delivery_rule_when_policy_enabled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            proposal = json.loads(VALID_CONTEXT_PROPOSAL.read_text())
            proposal["id"] = "proposal_context_rule_regression_001"
            proposal["producer"]["session_id"] = "proposal_context_rule_regression_001"
            proposal["title"] = "Context delivery rule regression"
            proposal["proposed_changes"] = [
                {
                    "type": "context_delivery_rule",
                    "operation": "create",
                    "target": {
                        "entity_type": "agent_identity",
                        "entity_id": "agent_researcher_001",
                    },
                    "rule": {
                        "id": "context_rule_researcher_regression",
                        "mode": "prompt",
                        "include_keywords": ["timeout"],
                    },
                },
                proposal["proposed_changes"][1],
            ]

            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            run_autonomy(db_path=db_path)

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_context_rule_regression_001_1",
            )
            replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_fixture["replay"]["replay_run_id"] = replay.replay_run_id
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=replay_fixture,
                source_label="context-rule-regression-replay-fixture",
            )
            run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_rule_regression_001_1",
                replay_run_id=replay.replay_run_id,
            )
            applied = run_autonomy(db_path=db_path)
            self.assertEqual(applied.decisions[0].action, "applied")
            failed = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_context_rule_regression_001_1",
            )
            self.assertEqual(failed.status, "failed")

            rollback = run_autonomy(db_path=db_path)
            rules = list_context_delivery_rules(db_path, active_only=False)
            revisions = list_context_delivery_rule_revisions(
                db_path,
                rule_id="context_rule_researcher_regression",
            )
            proposals = list_learning_proposals(db_path)

            self.assertEqual(rollback.decisions[0].action, "rolled_back")
            self.assertEqual(rollback.decisions[0].check_run_ids, (failed.check_run_id,))
            self.assertTrue(rollback.decisions[0].reason.startswith("regression_check_failed:"))
            self.assertEqual(
                rollback.decisions[0].detail["context_delivery_rule_revision_ids"],
                [revisions[1]["id"]],
            )
            self.assertEqual(
                rollback.decisions[0].detail["rollback_context_delivery_rule_revision_ids"],
                [revisions[0]["id"]],
            )
            self.assertEqual(proposals[0]["state"], "failed")
            self.assertFalse(rules[0]["active"])
            self.assertEqual(revisions[0]["operation"], "rollback")
            self.assertTrue(revisions[0]["before"]["active"])
            self.assertFalse(revisions[0]["after"]["active"])

    def test_autonomous_harness_respects_human_review_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_HARNESS_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, harness_mode="autonomous")

            report = run_autonomy(db_path=db_path)
            patches = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.decisions[0].action, "blocked")
            self.assertEqual(report.decisions[0].reason, "human_review_required")
            self.assertEqual(report.decisions[0].patch_transaction_ids, ())
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(patches, [])

    def test_autonomous_harness_prepares_generated_file_but_waits_for_check_run(self) -> None:
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
                harness_mode="autonomous",
                allow_repo_patch=True,
            )

            report = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            check_specs = list_check_specs(db_path)
            patches = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(report.decisions[0].action, "gated")
            self.assertEqual(report.decisions[0].reason, "missing_check_run")
            self.assertEqual(
                report.decisions[0].check_spec_ids,
                ("check_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(
                report.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_generated_check_001_1",),
            )
            self.assertEqual(
                check_specs[0]["definition"]["operator_definition"]["generated_by"],
                "kyoko_fallback_harness_check",
            )
            self.assertEqual(proposals[0]["state"], "pending")
            self.assertEqual(patches[0]["status"], "ready")
            self.assertFalse(target.exists())

    def test_autonomous_harness_applies_generated_file_after_check_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_autonomous_apply_001"
            proposal["producer"]["session_id"] = "operator_session_harness_autonomous_apply_001"
            proposal["gate_expectations"]["requires_human_review"] = False
            proposal["proposed_changes"].append(
                {
                    "type": "check_spec",
                    "name": "harness generated file is gated by timeout replay",
                    "check_type": "deterministic_assertion",
                    "trust_level": "L0_generated",
                    "side_effect_mode": "network_mocked",
                    "definition": {
                        "target": {
                            "entity_type": "span",
                            "entity_id": "span_fetch_timeout_001",
                        },
                        "assertions": [
                            {"type": "target_status_not_failed"},
                            {
                                "type": "replay_target_field_equals",
                                "path": "attributes.retry_count",
                                "equals": 1,
                            },
                        ],
                    },
                }
            )

            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                harness_mode="autonomous",
                allow_repo_patch=True,
            )

            gated = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            self.assertEqual(gated.decisions[0].action, "gated")
            self.assertEqual(gated.decisions[0].reason, "missing_check_run")
            self.assertEqual(
                gated.decisions[0].check_spec_ids,
                ("check_proposal_harness_autonomous_apply_001_1",),
            )
            self.assertFalse(target.exists())

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_harness_autonomous_apply_001_1",
            )
            replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_fixture["replay"]["replay_run_id"] = replay.replay_run_id
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=replay_fixture,
                source_label="harness-autonomous-replay-fixture",
            )
            check_run = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_harness_autonomous_apply_001_1",
                replay_run_id=replay.replay_run_id,
            )
            self.assertEqual(check_run.status, "passed")
            self.assertEqual(check_run.promoted_trust_level, "L2_regression")

            set_harness_target_lock(
                db_path=db_path,
                target_path="checks/generated_timeout_check.py",
                locked=True,
            )
            blocked = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            self.assertEqual(blocked.decisions[0].action, "blocked")
            self.assertEqual(
                blocked.decisions[0].reason,
                "human_locked_harness_target:checks/generated_timeout_check.py",
            )
            self.assertFalse(target.exists())

            set_harness_target_lock(
                db_path=db_path,
                target_path="checks/generated_timeout_check.py",
                locked=False,
            )
            applied = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            patches = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(applied.decisions[0].action, "applied")
            self.assertEqual(applied.decisions[0].reason, "check_gate_passed")
            self.assertEqual(
                applied.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_autonomous_apply_001_1",),
            )
            self.assertEqual(proposals[0]["state"], "applied")
            self.assertEqual(patches[0]["status"], "applied")
            self.assertTrue(target.exists())
            self.assertIn("TIMEOUT_SPAN_ID", target.read_text())

    def test_autonomous_harness_rolls_back_applied_patch_after_check_regression(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_regression_rollback_001"
            proposal["producer"]["session_id"] = "operator_session_harness_regression_rollback_001"
            proposal["gate_expectations"]["requires_human_review"] = False
            proposal["proposed_changes"].append(
                {
                    "type": "check_spec",
                    "name": "harness generated file regression rollback",
                    "check_type": "deterministic_assertion",
                    "trust_level": "L0_generated",
                    "side_effect_mode": "network_mocked",
                    "definition": {
                        "target": {
                            "entity_type": "span",
                            "entity_id": "span_fetch_timeout_001",
                        },
                        "assertions": [{"type": "target_status_not_failed"}],
                    },
                }
            )

            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                harness_mode="autonomous",
                allow_repo_patch=True,
            )
            run_autonomy(db_path=db_path, harness_workspace_root=workspace)

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_harness_regression_rollback_001_1",
            )
            replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_fixture["replay"]["replay_run_id"] = replay.replay_run_id
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=replay_fixture,
                source_label="harness-regression-rollback-replay-fixture",
            )
            passed = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_harness_regression_rollback_001_1",
                replay_run_id=replay.replay_run_id,
            )
            self.assertEqual(passed.status, "passed")
            applied = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            self.assertEqual(applied.decisions[0].action, "applied")
            self.assertTrue(target.exists())

            failed = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_harness_regression_rollback_001_1",
            )
            self.assertEqual(failed.status, "failed")

            rollback = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            patches = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(rollback.decisions[0].action, "rolled_back")
            self.assertEqual(
                rollback.decisions[0].patch_transaction_ids,
                ("patch_proposal_harness_regression_rollback_001_1",),
            )
            self.assertEqual(rollback.decisions[0].check_run_ids, (failed.check_run_id,))
            self.assertTrue(rollback.decisions[0].reason.startswith("regression_check_failed:"))
            self.assertEqual(proposals[0]["state"], "failed")
            self.assertEqual(patches[0]["status"], "rolled_back")
            self.assertFalse(target.exists())

    def test_harness_regression_rollback_respects_policy_toggle(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_regression_policy_off_001"
            proposal["producer"]["session_id"] = "operator_session_harness_regression_policy_off_001"
            proposal["gate_expectations"]["requires_human_review"] = False
            proposal["proposed_changes"].append(
                {
                    "type": "check_spec",
                    "name": "harness generated file regression rollback disabled",
                    "check_type": "deterministic_assertion",
                    "trust_level": "L0_generated",
                    "side_effect_mode": "network_mocked",
                    "definition": {
                        "target": {
                            "entity_type": "span",
                            "entity_id": "span_fetch_timeout_001",
                        },
                        "assertions": [{"type": "target_status_not_failed"}],
                    },
                }
            )

            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(
                db_path=db_path,
                harness_mode="autonomous",
                allow_repo_patch=True,
                rollback_on_regression=False,
            )
            run_autonomy(db_path=db_path, harness_workspace_root=workspace)

            replay = create_replay_run(
                db_path=db_path,
                check_spec_id="check_proposal_harness_regression_policy_off_001_1",
            )
            replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_fixture["replay"]["replay_run_id"] = replay.replay_run_id
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=replay_fixture,
                source_label="harness-regression-policy-off-replay-fixture",
            )
            run_check(
                db_path=db_path,
                check_spec_id="check_proposal_harness_regression_policy_off_001_1",
                replay_run_id=replay.replay_run_id,
            )
            run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            failed = run_check(
                db_path=db_path,
                check_spec_id="check_proposal_harness_regression_policy_off_001_1",
            )
            self.assertEqual(failed.status, "failed")

            ignored = run_autonomy(db_path=db_path, harness_workspace_root=workspace)
            patches = list_patch_transactions(db_path)
            proposals = list_learning_proposals(db_path)

            self.assertEqual(ignored.decisions, ())
            self.assertEqual(proposals[0]["state"], "applied")
            self.assertEqual(patches[0]["status"], "applied")
            self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
