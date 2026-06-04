import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

from kyoko.autonomy import update_autonomy_policy
from kyoko.autonomy_runner import run_autonomy
from kyoko.details import (
    DetailError,
    get_check_detail,
    get_proposal_detail,
    get_replay_detail,
    get_run_detail,
    list_runs,
)
from kyoko.checks import (
    complete_replay_from_fixture,
    create_replay_run,
    generate_checks_for_proposal,
    run_check,
    run_replay_command,
)
from kyoko.proposals import submit_learning_proposal
from kyoko.storage import ingest_source_fixture, ingest_source_payload


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ProposalDetailTests(unittest.TestCase):
    def test_list_runs_returns_recent_run_summaries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            runs = list_runs(db_path=db_path)

            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["id"], "run_research_topic_001")
            self.assertEqual(runs[0]["span_count"], 2)
            self.assertEqual(runs[0]["failed_span_count"], 1)
            self.assertEqual(runs[0]["handoff_count"], 1)
            self.assertEqual(runs[0]["agent_name"], "researcher")

    def test_run_detail_returns_trace_context_and_related_proposals(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            detail = get_run_detail(db_path=db_path, run_id="run_research_topic_001")

            self.assertEqual(detail["run"]["id"], "run_research_topic_001")
            self.assertEqual(detail["agent_identity"]["id"], "agent_researcher_001")
            self.assertEqual(detail["task"]["id"], "task_research_topic_001")
            self.assertEqual(detail["summary"]["spans"], 2)
            self.assertEqual(detail["summary"]["failed_spans"], 1)
            self.assertEqual(detail["summary"]["handoffs"], 1)
            self.assertEqual(detail["summary"]["related_proposals"], 1)
            self.assertEqual(detail["related_proposals"][0]["proposal"]["id"], "proposal_context_timeout_001")
            self.assertEqual(detail["span_tree"][0]["id"], "span_research_root_001")
            self.assertEqual(detail["span_tree"][0]["children"][0]["id"], "span_fetch_timeout_001")

    def test_run_detail_preserves_adapter_versions_across_payload_revisions(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_payload(
                db_path=db_path,
                fixture=_source_adapter_revision_payload(
                    source_id="source_adapter_revision_v0",
                    adapter_version="kyoko.test_adapter.v0",
                    run_id="run_adapter_revision_v0",
                    span_id="span_adapter_revision_v0",
                    agent_id="agent_adapter_revision_v0",
                    started_at="2026-05-31T12:00:00Z",
                ),
                source_label="adapter-revision-v0",
            )
            ingest_source_payload(
                db_path=db_path,
                fixture=_source_adapter_revision_payload(
                    source_id="source_adapter_revision_v1",
                    adapter_version="kyoko.test_adapter.v1",
                    run_id="run_adapter_revision_v1",
                    span_id="span_adapter_revision_v1",
                    agent_id="agent_adapter_revision_v1",
                    started_at="2026-06-01T12:00:00Z",
                ),
                source_label="adapter-revision-v1",
            )

            v0_detail = get_run_detail(db_path=db_path, run_id="run_adapter_revision_v0")
            v1_detail = get_run_detail(db_path=db_path, run_id="run_adapter_revision_v1")

            self.assertEqual(v0_detail["run"]["source_id"], "source_adapter_revision_v0")
            self.assertEqual(v0_detail["source"]["adapter_version"], "kyoko.test_adapter.v0")
            self.assertEqual(v0_detail["spans"][0]["source_id"], "source_adapter_revision_v0")
            self.assertEqual(v1_detail["run"]["source_id"], "source_adapter_revision_v1")
            self.assertEqual(v1_detail["source"]["adapter_version"], "kyoko.test_adapter.v1")
            self.assertEqual(v1_detail["spans"][0]["source_id"], "source_adapter_revision_v1")

    def test_run_detail_rejects_missing_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(DetailError, "run_not_found"):
                get_run_detail(db_path=db_path, run_id="missing")

    def test_proposal_detail_resolves_evidence_target_and_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            detail = get_proposal_detail(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )

            self.assertEqual(detail["proposal"]["id"], "proposal_context_timeout_001")
            self.assertEqual(detail["proposal"]["section_label"], "Context fix")
            self.assertIn("agent-facing", detail["proposal"]["section_description"])
            self.assertEqual(detail["proposal"]["problem"]["severity"], "medium")
            self.assertEqual(detail["target"]["ref"]["entity_id"], "agent_researcher_001")
            self.assertTrue(detail["target"]["found"])
            self.assertEqual(len(detail["evidence"]), 2)
            self.assertTrue(all(item["found"] for item in detail["evidence"]))
            self.assertEqual(detail["autonomy_gate"]["action"], "awaiting_human_review")
            self.assertEqual(detail["autonomy_gate"]["reason"], "context_policy_propose")
            self.assertEqual(detail["confidence_assessment"]["operator_confidence"], 0.82)
            self.assertEqual(detail["confidence_assessment"]["kyoko_confidence"], 0.66)
            self.assertEqual(detail["confidence_assessment"]["level"], "medium")
            self.assertLess(
                detail["confidence_assessment"]["kyoko_confidence"],
                detail["confidence_assessment"]["operator_confidence"],
            )
            self.assertEqual(detail["confidence_assessment"]["evidence"]["resolved_refs"], 2)
            self.assertEqual(detail["confidence_assessment"]["verification"]["check_runs"], 0)
            self.assertEqual(
                detail["check_guidance"]["gateable_check_types"],
                ["deterministic_assertion", "regression_replay"],
            )
            self.assertEqual(
                [preset["name"] for preset in detail["check_guidance"]["assertion_presets"]],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertEqual(detail["check_guidance"]["informational_check_types"], ["judge", "smoke_run"])
            self.assertTrue(detail["check_guidance"]["recorded_judge_only"])
            self.assertEqual(detail["check_specs"], [])
            self.assertEqual(detail["timeline_events"], [])
            chain_by_stage = {
                step["stage"]: step for step in detail["evidence_chain"]["steps"]
            }
            self.assertEqual(chain_by_stage["observed_issue"]["status"], "resolved")
            self.assertEqual(chain_by_stage["observed_issue"]["resolved_refs"], 2)
            self.assertEqual(chain_by_stage["proposed_fix"]["target_label"], "researcher (agent_identity:agent_researcher_001)")
            self.assertEqual(chain_by_stage["check_gate"]["status"], "not_generated")
            self.assertEqual(chain_by_stage["replay"]["status"], "not_run")
            self.assertEqual(chain_by_stage["autonomy"]["status"], "awaiting_human_review")
            self.assertFalse(detail["evidence_chain"]["ready_to_apply"])

    def test_proposal_detail_reports_check_replay_and_would_apply_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            generate_checks_for_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
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

            detail = get_proposal_detail(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )

            self.assertEqual(detail["autonomy_gate"]["action"], "would_apply")
            self.assertEqual(detail["autonomy_gate"]["reason"], "check_gate_passed")
            self.assertEqual(detail["autonomy_gate"]["check_gate"]["passed"], True)
            self.assertEqual(detail["check_specs"][0]["trust_level"], "L2_regression")
            self.assertEqual(detail["check_runs"][0]["status"], "passed")
            self.assertEqual(detail["replay_runs"][0]["status"], "passed")
            self.assertEqual(detail["confidence_assessment"]["kyoko_confidence"], 0.93)
            self.assertEqual(detail["confidence_assessment"]["level"], "high")
            self.assertEqual(detail["confidence_assessment"]["verification"]["verified_trust_level"], "L2_regression")
            self.assertGreater(
                detail["confidence_assessment"]["kyoko_confidence"],
                detail["confidence_assessment"]["operator_confidence"],
            )
            chain_by_stage = {
                step["stage"]: step for step in detail["evidence_chain"]["steps"]
            }
            self.assertEqual(chain_by_stage["check_gate"]["status"], "passed")
            self.assertEqual(chain_by_stage["check_gate"]["latest_trust_level"], "L2_regression")
            self.assertEqual(chain_by_stage["replay"]["status"], "passed")
            self.assertEqual(chain_by_stage["replay"]["side_effect_mode"], "network_mocked")
            self.assertEqual(chain_by_stage["autonomy"]["status"], "would_apply")
            self.assertTrue(detail["evidence_chain"]["ready_to_apply"])

    def test_check_detail_explains_target_replay_and_latest_result(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            replay_run_id = _completed_check_flow(db_path)

            detail = get_check_detail(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
            )

            self.assertEqual(detail["check_spec"]["id"], "check_proposal_context_timeout_001_1")
            self.assertEqual(detail["target"]["ref"]["entity_id"], "span_fetch_timeout_001")
            self.assertTrue(detail["target"]["found"])
            self.assertEqual(detail["source_run"]["id"], "run_research_topic_001")
            self.assertEqual(detail["summary"]["latest_status"], "passed")
            self.assertEqual(detail["summary"]["latest_comparison"], "fail_before_pass_after")
            self.assertEqual(detail["summary"]["latest_assertion_counts"]["passed"], 3)
            self.assertEqual(len(detail["summary"]["latest_assertions"]), 3)
            self.assertEqual(detail["summary"]["latest_assertions"][0]["type"], "target_status_not_failed")
            self.assertTrue(detail["summary"]["latest_assertions"][0]["passed"])
            self.assertEqual(detail["summary"]["latest_assertions"][1]["path"], "attributes.retry_count")
            self.assertEqual(detail["summary"]["latest_assertions"][1]["actual"], 1)
            self.assertEqual(detail["summary"]["latest_assertions"][2]["expected"], "complete")
            self.assertEqual(detail["summary"]["trust_level"], "L2_regression")
            self.assertEqual(detail["latest_replay_run"]["id"], replay_run_id)

    def test_check_detail_includes_unsupported_assertion_preset_context(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _prepare_check(db_path)
            _set_check_definition(
                db_path,
                "check_proposal_context_timeout_001_1",
                {"assertion_preset": "unknown_framework_shape"},
            )
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

            detail = get_check_detail(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
            )

            assertion = detail["summary"]["latest_assertions"][0]
            self.assertEqual(assertion["type"], "unsupported_assertion_preset")
            self.assertEqual(assertion["preset"], "unknown_framework_shape")
            self.assertEqual(
                assertion["supported_presets"],
                ["replay_success_shape", "replay_handoff_present"],
            )

    def test_replay_detail_explains_source_output_and_side_effects(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            replay_run_id = _completed_check_flow(db_path)

            detail = get_replay_detail(db_path=db_path, replay_run_id=replay_run_id)

            self.assertEqual(detail["replay_run"]["id"], replay_run_id)
            self.assertEqual(detail["source_run"]["id"], "run_research_topic_001")
            self.assertEqual(detail["output_run"]["id"], "run_research_topic_replay_001")
            self.assertEqual(detail["summary"]["actual_side_effect_mode"], "network_mocked")
            self.assertEqual(detail["summary"]["source_spans"], 2)
            self.assertEqual(detail["summary"]["output_spans"], 2)
            self.assertEqual(detail["check_runs"][0]["status"], "passed")

    def test_replay_detail_includes_command_artifact_previews(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "replay-command"
            _prepare_check(db_path)
            report = run_replay_command(
                db_path=db_path,
                check_spec_id="check_proposal_context_timeout_001_1",
                output_dir=output_dir,
                command=[sys.executable, str(REPLAY_COMMAND)],
                run_check_after=True,
            )

            detail = get_replay_detail(db_path=db_path, replay_run_id=report.replay_run_id)

            artifacts = {artifact["kind"]: artifact for artifact in detail["artifacts"]}
            self.assertEqual(detail["summary"]["artifacts"], 3)
            self.assertTrue(artifacts["replay_request"]["exists"])
            self.assertTrue(artifacts["replay_result"]["exists"])
            self.assertTrue(artifacts["replay_command_output"]["exists"])
            self.assertIn("BEGIN_KYOKO_REPLAY_RESULT_JSON", artifacts["replay_command_output"]["preview"])
            self.assertIn("kyoko.replay_request.v1", artifacts["replay_request"]["preview"])

    def test_proposal_detail_includes_autonomy_gate_history(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            report = run_autonomy(db_path=db_path)

            detail = get_proposal_detail(db_path=db_path, proposal_id="proposal_context_timeout_001")

            self.assertEqual(report.decisions[0].action, "gated")
            self.assertGreaterEqual(len(detail["gate_history"]), 1)
            decision_events = [
                event for event in detail["gate_history"] if event["kind"] == "autonomy_decision"
            ]
            self.assertEqual(decision_events[-1]["action"], "gated")
            self.assertEqual(decision_events[-1]["reason"], "missing_check_run")
            self.assertEqual(
                decision_events[-1]["check_spec_ids"],
                ["check_proposal_context_timeout_001_1"],
            )

    def test_proposal_detail_rejects_missing_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, SOURCE_FIXTURE)

            with self.assertRaisesRegex(DetailError, "proposal_not_found"):
                get_proposal_detail(db_path=db_path, proposal_id="missing")


def _completed_check_flow(db_path: Path) -> str:
    _prepare_check(db_path)
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
    return replay.replay_run_id


def _prepare_check(db_path: Path) -> None:
    ingest_source_fixture(db_path, SOURCE_FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    generate_checks_for_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")


def _set_check_definition(db_path: Path, check_spec_id: str, definition: dict) -> None:
    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute(
            "UPDATE check_specs SET definition_json = ? WHERE id = ?",
            (json.dumps(definition, sort_keys=True), check_spec_id),
        )
        connection.commit()
    finally:
        connection.close()


def _source_adapter_revision_payload(
    *,
    source_id: str,
    adapter_version: str,
    run_id: str,
    span_id: str,
    agent_id: str,
    started_at: str,
) -> dict:
    profile_id = "profile_adapter_revision_compat"
    return {
        "profile": {
            "id": profile_id,
            "name": "Adapter Revision Compatibility",
            "root_path": ".",
            "status": "active",
            "created_at": "2026-05-31T12:00:00Z",
            "updated_at": started_at,
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "manual",
                "display_name": f"Adapter {adapter_version}",
                "status": "active",
                "adapter_version": adapter_version,
                "config_json": {"fixture": "adapter_revision_compat"},
                "capabilities_json": {"traces": True},
                "last_seen_at": started_at,
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": f"{agent_id}-external",
                "name": f"agent-{adapter_version}",
                "kind": "agent",
                "role": "researcher",
                "model": "test-model",
                "workspace_path": ".",
                "metadata_json": {"adapter_revision": adapter_version},
            }
        ],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": f"{run_id}-external",
                "root_span_id": span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": started_at,
                "ended_at": started_at,
                "input_ref": f"blob_{run_id}_input",
                "output_ref": f"blob_{run_id}_output",
                "summary": f"Run from {adapter_version}",
                "metadata_json": {"adapter_revision": adapter_version},
            }
        ],
        "spans": [
            {
                "id": span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": f"{span_id}-external",
                "parent_span_id": None,
                "workflow_node_id": None,
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": f"root-{adapter_version}",
                "status": "succeeded",
                "started_at": started_at,
                "ended_at": started_at,
                "input_ref": f"blob_{span_id}_input",
                "output_ref": f"blob_{span_id}_output",
                "usage_json": {"input_tokens": 1, "output_tokens": 1},
                "attributes_json": {"adapter_revision": adapter_version},
                "raw_ref": f"blob_{span_id}_raw",
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
