import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
import unittest

from kyoko.evals import (
    EvalError,
    approve_eval_spec,
    complete_replay_from_fixture,
    complete_replay_from_payload,
    complete_replay_from_server_response,
    create_replay_run,
    extract_judge_result_from_output,
    extract_replay_result_from_output,
    generate_evals_for_proposal,
    list_eval_capabilities,
    list_eval_runs,
    list_eval_spec_locks,
    list_eval_specs,
    list_replay_runs,
    run_eval,
    run_judge_command,
    run_replay_command,
    set_eval_spec_lock,
)
from kyoko.analyze import analyze_with_mock_operator
from kyoko.blobs import list_payload_blobs
from kyoko.proposals import submit_learning_proposal
from kyoko.storage import get_database_status, ingest_source_fixture, ingest_source_payload


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"
JUDGE_COMMAND = ROOT / "tests/fixtures/judge_command.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _timeline_events(db_path: Path, *, kind: str) -> list[dict]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT entity_type, entity_id, kind, agent_identity_id, metadata_json
            FROM timeline_events
            WHERE kind = ?
            ORDER BY rowid
            """,
            (kind,),
        ).fetchall()
    events = []
    for row in rows:
        payload = dict(row)
        payload["metadata"] = json.loads(payload.pop("metadata_json"))
        events.append(payload)
    return events


class EvalTests(unittest.TestCase):
    def test_eval_capabilities_describe_gateable_and_informational_types(self) -> None:
        capabilities = list_eval_capabilities()
        eval_types = {entry["name"]: entry for entry in capabilities["eval_types"]}

        self.assertEqual(
            capabilities["executable_eval_types"],
            ["deterministic_assertion", "judge", "regression_replay", "smoke_run"],
        )
        self.assertEqual(capabilities["gateable_eval_types"], ["deterministic_assertion", "regression_replay"])
        self.assertTrue(eval_types["deterministic_assertion"]["gateable"])
        self.assertTrue(eval_types["regression_replay"]["requires_replay"])
        self.assertFalse(eval_types["judge"]["gateable"])
        self.assertFalse(eval_types["smoke_run"]["gateable"])
        self.assertEqual(
            [assertion["name"] for assertion in capabilities["deterministic_assertions"]],
            [
                "target_status_not_failed",
                "replay_target_field_equals",
                "replay_entity_field_equals",
                "replay_run_status_equals",
                "replay_no_failed_spans",
                "replay_span_count_at_least",
                "replay_handoff_count_at_least",
            ],
        )
        self.assertEqual(
            [preset["name"] for preset in capabilities["assertion_presets"]],
            ["replay_success_shape", "replay_handoff_present"],
        )
        self.assertFalse(capabilities["judge"]["invokes_model"])
        self.assertEqual(capabilities["judge"]["autonomy_gate"], "unsupported")
        self.assertIn("api:POST /api/judge-command", capabilities["judge"]["handoff_surfaces"])
        self.assertIn("subjective_quality_review", capabilities["judge"]["recommended_use"])
        self.assertEqual(
            capabilities["replay"]["safe_side_effect_modes"],
            ["none", "filesystem_read", "sandboxed_filesystem", "network_mocked"],
        )
        self.assertEqual(capabilities["replay"]["unsafe_side_effect_modes"], ["live_network", "unknown"])

    def test_generate_evals_persists_eval_spec_from_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            report = generate_evals_for_proposal(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )
            status = get_database_status(db_path)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(report.eval_spec_ids, ("eval_proposal_context_timeout_001_1",))
            self.assertEqual(report.existing_eval_spec_ids, ())
            self.assertEqual(status.counts["eval_specs"], 1)
            self.assertEqual(eval_specs[0]["proposal_id"], "proposal_context_timeout_001")
            self.assertEqual(eval_specs[0]["eval_type"], "deterministic_assertion")
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")
            self.assertFalse(eval_specs[0]["human_locked"])
            self.assertIsNone(eval_specs[0]["human_lock_reason"])
            self.assertEqual(eval_specs[0]["target"]["entity_type"], "span")
            self.assertEqual(eval_specs[0]["target"]["entity_id"], "span_fetch_timeout_001")
            self.assertEqual(len(eval_specs[0]["definition"]["assertions"]), 3)
            self.assertEqual(eval_specs[0]["definition"]["assertions"][1]["type"], "replay_target_field_equals")

    def test_generate_evals_falls_back_for_context_proposal_without_explicit_eval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            analyze = analyze_with_mock_operator(
                db_path=db_path,
                output_dir=Path(tmpdir) / "analysis",
                schema_path=SCHEMA,
            )

            report = generate_evals_for_proposal(db_path=db_path, proposal_id=analyze.proposal_id)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(report.eval_spec_ids, (f"eval_{analyze.proposal_id}_1",))
            self.assertEqual(eval_specs[0]["proposal_id"], analyze.proposal_id)
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")
            self.assertEqual(eval_specs[0]["side_effect_mode"], "network_mocked")
            self.assertEqual(eval_specs[0]["definition"]["operator_definition"]["generated_by"], "kyoko_fallback_context_eval")
            self.assertEqual(eval_specs[0]["definition"]["assertions"], [{"type": "target_status_not_failed"}])

    def test_generate_evals_falls_back_for_harness_proposal_without_explicit_eval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )

            report = generate_evals_for_proposal(
                db_path=db_path,
                proposal_id="proposal_harness_generated_eval_001",
            )
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(
                report.eval_spec_ids,
                ("eval_proposal_harness_generated_eval_001_1",),
            )
            self.assertEqual(eval_specs[0]["proposal_id"], "proposal_harness_generated_eval_001")
            self.assertEqual(eval_specs[0]["target"]["entity_id"], "span_fetch_timeout_001")
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")
            self.assertEqual(eval_specs[0]["side_effect_mode"], "network_mocked")
            self.assertEqual(
                eval_specs[0]["definition"]["operator_definition"]["generated_by"],
                "kyoko_fallback_harness_eval",
            )
            self.assertEqual(
                eval_specs[0]["definition"]["assertions"],
                [{"type": "target_status_not_failed"}],
            )

    def test_generate_evals_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            generate_evals_for_proposal(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )
            report = generate_evals_for_proposal(
                db_path=db_path,
                proposal_id="proposal_context_timeout_001",
            )

            self.assertEqual(report.eval_spec_ids, ())
            self.assertEqual(report.existing_eval_spec_ids, ("eval_proposal_context_timeout_001_1",))
            self.assertEqual(get_database_status(db_path).counts["eval_specs"], 1)

    def test_replay_records_bounded_dry_run_without_invoking_agent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            report = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            replay_runs = list_replay_runs(db_path)

            self.assertEqual(report.replay_run_id, "replay_eval_proposal_context_timeout_001_1_001")
            self.assertEqual(report.status, "passed")
            self.assertEqual(report.source_run_id, "run_research_topic_001")
            self.assertEqual(report.side_effect_mode, "network_mocked")
            self.assertFalse(report.result["executed_agent"])
            self.assertEqual(replay_runs[0]["result"]["actual_side_effect_mode"], "none")

    def test_eval_run_fails_against_original_failed_span_and_promotes_when_repeated(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            first = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            second = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            eval_runs = list_eval_runs(db_path)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(first.status, "failed")
            self.assertEqual(first.result["observed_status"], "failed")
            self.assertIsNone(first.promoted_trust_level)
            self.assertEqual(second.status, "failed")
            self.assertEqual(second.promoted_trust_level, "L1_repeated")
            self.assertEqual(len(eval_runs), 2)
            self.assertEqual(eval_specs[0]["trust_level"], "L1_repeated")

    def test_human_approval_sets_l3_trust_and_records_audit_event(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            report = approve_eval_spec(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                reason="reviewed baseline and replay evidence",
                actor_agent_identity_id="agent_researcher_001",
            )
            eval_specs = list_eval_specs(db_path)
            events = _timeline_events(db_path, kind="eval_spec_human_approved")

            self.assertEqual(report.eval_spec_id, eval_spec_id)
            self.assertEqual(report.previous_trust_level, "L0_generated")
            self.assertEqual(report.trust_level, "L3_human_approved")
            self.assertEqual(report.reason, "reviewed baseline and replay evidence")
            self.assertEqual(report.actor_agent_identity_id, "agent_researcher_001")
            self.assertEqual(eval_specs[0]["trust_level"], "L3_human_approved")
            self.assertEqual(events[0]["entity_type"], "eval_spec")
            self.assertEqual(events[0]["entity_id"], eval_spec_id)
            self.assertEqual(events[0]["agent_identity_id"], "agent_researcher_001")
            self.assertEqual(events[0]["metadata"]["previous_trust_level"], "L0_generated")
            self.assertEqual(events[0]["metadata"]["trust_level"], "L3_human_approved")
            self.assertEqual(events[0]["metadata"]["reason"], "reviewed baseline and replay evidence")

            with self.assertRaisesRegex(EvalError, "actor_agent_identity_not_found"):
                approve_eval_spec(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    actor_agent_identity_id="agent_missing",
                )

    def test_human_locked_eval_spec_blocks_human_approval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            set_eval_spec_lock(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                locked=True,
                reason="freeze eval",
                actor_agent_identity_id="agent_researcher_001",
            )

            with self.assertRaisesRegex(EvalError, f"human_locked_eval_spec:{eval_spec_id}"):
                approve_eval_spec(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    reason="reviewed anyway",
                    actor_agent_identity_id="agent_researcher_001",
                )

            self.assertEqual(list_eval_specs(db_path)[0]["trust_level"], "L0_generated")

    def test_human_locked_eval_spec_blocks_trust_promotion(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            lock = set_eval_spec_lock(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                locked=True,
                reason="human baseline review",
                actor_agent_identity_id="agent_researcher_001",
            )
            first = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            second = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            eval_specs = list_eval_specs(db_path)
            locks = list_eval_spec_locks(db_path)

            self.assertTrue(lock.human_locked)
            self.assertEqual(lock.reason, "human baseline review")
            self.assertEqual(lock.actor_agent_identity_id, "agent_researcher_001")
            self.assertIsNone(first.promoted_trust_level)
            self.assertIsNone(second.promoted_trust_level)
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")
            self.assertTrue(eval_specs[0]["human_locked"])
            self.assertEqual(eval_specs[0]["human_lock_reason"], "human baseline review")
            self.assertEqual(locks[0]["eval_spec_id"], eval_spec_id)
            self.assertTrue(locks[0]["human_locked"])

            unlock = set_eval_spec_lock(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                locked=False,
                reason="review complete",
                actor_agent_identity_id="agent_researcher_001",
            )

            self.assertFalse(unlock.human_locked)
            self.assertEqual(unlock.actor_agent_identity_id, "agent_researcher_001")
            self.assertEqual(list_eval_spec_locks(db_path), [])
            inactive_locks = list_eval_spec_locks(db_path, locked_only=False)

            self.assertEqual(inactive_locks[0]["eval_spec_id"], eval_spec_id)
            self.assertFalse(inactive_locks[0]["human_locked"])
            self.assertEqual(inactive_locks[0]["reason"], "review complete")

            with self.assertRaisesRegex(EvalError, "actor_agent_identity_not_found"):
                set_eval_spec_lock(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    locked=True,
                    actor_agent_identity_id="agent_missing",
                )

    def test_controlled_replay_fixture_enables_before_after_eval_pass(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)

            completion = complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )
            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )
            status = get_database_status(db_path)
            eval_specs = list_eval_specs(db_path)
            replay_runs = list_replay_runs(db_path)

            self.assertEqual(completion.output_run_id, "run_research_topic_replay_001")
            self.assertEqual(completion.status, "passed")
            self.assertEqual(completion.result["target_map"]["span_fetch_timeout_001"], "span_fetch_retry_success_001")
            self.assertEqual(eval_report.status, "passed")
            self.assertEqual(eval_report.promoted_trust_level, "L2_regression")
            self.assertEqual(eval_report.result["comparison"], "fail_before_pass_after")
            self.assertEqual(eval_report.result["baseline_status"], "failed")
            self.assertEqual(eval_report.result["replay_observed_status"], "succeeded")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 3, "passed": 3, "failed": 0})
            self.assertEqual(eval_report.result["assertions"][1]["actual"], 1)
            self.assertEqual(eval_report.result["assertions"][2]["actual"], "complete")
            self.assertEqual(eval_specs[0]["trust_level"], "L2_regression")
            self.assertEqual(replay_runs[0]["output_ref"], "run_research_topic_replay_001")
            self.assertEqual(status.counts["runs"], 2)
            self.assertEqual(status.counts["spans"], 4)
            self.assertEqual(status.counts["replay_runs"], 1)
            self.assertEqual(status.counts["eval_runs"], 1)

    def test_replay_command_completes_replay_and_runs_eval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "replay-command"
            eval_spec_id = _create_eval_spec(db_path)

            report = run_replay_command(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                output_dir=output_dir,
                command=[sys.executable, str(REPLAY_COMMAND)],
                run_eval_after=True,
            )

            self.assertEqual(report.replay_run_id, "replay_eval_proposal_context_timeout_001_1_001")
            self.assertEqual(report.completion.output_run_id, "run_research_topic_replay_001")
            self.assertTrue(report.request_path.exists())
            self.assertTrue(report.result_path.exists())
            self.assertTrue(report.raw_output_path.exists())
            self.assertIsNotNone(report.eval_run)
            self.assertEqual(report.eval_run.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")

            request = json.loads(report.request_path.read_text())
            replay_result = json.loads(report.result_path.read_text())
            self.assertEqual(request["schema_version"], "kyoko.replay_request.v1")
            self.assertEqual(request["replay_run"]["id"], report.replay_run_id)
            self.assertEqual(request["source_run"]["input_ref"], "[REDACTED:payload_ref]")
            self.assertEqual(request["redaction"]["consumer"], "replay:command")
            self.assertEqual(replay_result["replay"]["replay_run_id"], report.replay_run_id)

    def test_replay_server_response_is_retained_as_payload_blob(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            replay_output_fixture = json.loads(REPLAY_SUCCESS.read_text())
            ingest_source_payload(
                db_path=db_path,
                fixture=replay_output_fixture,
                source_label="preloaded replay output",
            )

            response = {
                "replay_run_id": replay.replay_run_id,
                "idempotency_key": replay.replay_run_id,
                "run_id": "run_research_topic_replay_001",
                "status": "success",
                "actual_side_effect_mode": "network_mocked",
                "target_map": {
                    "span_fetch_timeout_001": "span_fetch_retry_success_001",
                },
                "note": "server completed",
                "raw_payload": {
                    "authorization": "Bearer replay-response-secret-token",
                    "body": "x" * 2048,
                },
            }

            completion = complete_replay_from_server_response(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                response=response,
                source_label="replay server",
            )
            blobs = list_payload_blobs(db_path)
            replay_runs = list_replay_runs(db_path)

            self.assertNotIn("server_response", completion.result)
            self.assertEqual(
                completion.result["server_response_keys"],
                sorted(response.keys()),
            )
            self.assertTrue(str(completion.result["server_response_ref"]).startswith("blob_sha256_"))
            response_blob = next(blob for blob in blobs if blob["kind"] == "replay_server_response")
            self.assertEqual(response_blob["id"], completion.result["server_response_ref"])
            self.assertEqual(response_blob["metadata"]["replay_run_id"], replay.replay_run_id)
            self.assertEqual(response_blob["metadata"]["eval_spec_id"], eval_spec_id)
            self.assertEqual(response_blob["metadata"]["source_label"], "replay server")
            self.assertEqual(response_blob["redaction_mode"], "redacted")
            self.assertEqual(response_blob["preview"], "[REDACTED:blob_preview]")
            stored_response = json.loads(Path(response_blob["path"]).read_text())
            self.assertEqual(stored_response["raw_payload"]["body"], "x" * 2048)
            self.assertEqual(
                stored_response["raw_payload"]["authorization"],
                "Bearer replay-response-secret-token",
            )
            self.assertEqual(replay_runs[0]["result"]["server_response_ref"], response_blob["id"])

    def test_replay_server_response_requires_matching_identity_echo(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)

            with self.assertRaisesRegex(EvalError, "replay_server_identity_required"):
                complete_replay_from_server_response(
                    db_path=db_path,
                    replay_run_id=replay.replay_run_id,
                    response={
                        "run_id": "run_research_topic_replay_001",
                        "status": "success",
                        "actual_side_effect_mode": "network_mocked",
                    },
                    source_label="replay server",
                )

            with self.assertRaisesRegex(EvalError, "replay_server_identity_mismatch:replay_run_id"):
                complete_replay_from_server_response(
                    db_path=db_path,
                    replay_run_id=replay.replay_run_id,
                    response={
                        "replay_run_id": "replay_other_001",
                        "run_id": "run_research_topic_replay_001",
                        "status": "success",
                        "actual_side_effect_mode": "network_mocked",
                    },
                    source_label="replay server",
                )

    def test_replay_completion_rejects_actual_side_effects_outside_requested_boundary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                side_effect_mode="none",
            )
            replay_output_fixture = json.loads(REPLAY_SUCCESS.read_text())
            replay_output_fixture["replay"]["replay_run_id"] = replay.replay_run_id

            with self.assertRaisesRegex(
                EvalError,
                "replay_side_effect_mode_exceeds_request:network_mocked:none",
            ):
                complete_replay_from_payload(
                    db_path=db_path,
                    replay_run_id=replay.replay_run_id,
                    fixture=replay_output_fixture,
                    source_label="unsafe replay fixture",
                )

            with self.assertRaisesRegex(
                EvalError,
                "replay_side_effect_mode_exceeds_request:network_mocked:none",
            ):
                complete_replay_from_server_response(
                    db_path=db_path,
                    replay_run_id=replay.replay_run_id,
                    response={
                        "replay_run_id": replay.replay_run_id,
                        "run_id": "run_research_topic_replay_001",
                        "status": "success",
                        "actual_side_effect_mode": "network_mocked",
                    },
                    source_label="replay server",
                )

            with sqlite3.connect(db_path) as connection:
                replay_output_count = connection.execute(
                    "SELECT COUNT(*) FROM runs WHERE id = ?",
                    ("run_research_topic_replay_001",),
                ).fetchone()[0]
            self.assertEqual(replay_output_count, 0)
            self.assertFalse(
                [
                    blob
                    for blob in list_payload_blobs(db_path)
                    if blob["kind"] == "replay_server_response"
                ]
            )

    def test_extract_replay_result_rejects_missing_block(self) -> None:
        with self.assertRaisesRegex(EvalError, "exactly_one_result_block"):
            extract_replay_result_from_output("no replay json")

    def test_eval_fails_when_replay_field_assertion_does_not_match(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            broken_fixture = json.loads(REPLAY_SUCCESS.read_text())
            broken_fixture["spans"][1]["attributes_json"]["retry_count"] = 0

            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=broken_fixture,
                source_label="broken replay fixture",
            )
            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )

            self.assertEqual(eval_report.status, "failed")
            self.assertEqual(eval_report.result["comparison"], "fail_before_pass_after")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 3, "passed": 2, "failed": 1})
            self.assertEqual(eval_report.result["assertions"][1]["reason"], "field_mismatch")
            self.assertEqual(eval_report.result["assertions"][1]["actual"], 0)

    def test_trace_shape_assertions_validate_replay_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            fixture = json.loads(REPLAY_SUCCESS.read_text())
            fixture["profile"]["id"] = "profile_news_research_001"

            _set_eval_assertions(
                db_path,
                eval_spec_id,
                [
                    {"type": "replay_run_status_equals", "equals": "succeeded"},
                    {"type": "replay_no_failed_spans"},
                    {"type": "replay_span_count_at_least", "min": 2},
                    {"type": "replay_handoff_count_at_least", "min": 1},
                ],
            )
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=fixture,
                source_label="shape replay fixture",
            )
            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )

            self.assertEqual(eval_report.status, "passed")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 4, "passed": 4, "failed": 0})
            self.assertEqual(eval_report.result["assertions"][0]["actual"], "succeeded")
            self.assertEqual(eval_report.result["assertions"][2]["actual"], 2)
            self.assertEqual(eval_report.result["assertions"][3]["actual"], 1)

    def test_trace_shape_assertions_report_replay_failures(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            fixture = json.loads(REPLAY_SUCCESS.read_text())
            fixture["spans"][1]["status"] = "failed"
            fixture["handoffs"] = []

            _set_eval_assertions(
                db_path,
                eval_spec_id,
                [
                    {"type": "replay_no_failed_spans"},
                    {"type": "replay_handoff_count_at_least", "min": 1},
                ],
            )
            complete_replay_from_payload(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture=fixture,
                source_label="broken shape replay fixture",
            )
            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )

            self.assertEqual(eval_report.status, "failed")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 2, "passed": 0, "failed": 2})
            self.assertEqual(eval_report.result["assertions"][0]["reason"], "failed_spans_present")
            self.assertEqual(eval_report.result["assertions"][0]["actual"], 1)
            self.assertEqual(eval_report.result["assertions"][1]["reason"], "handoff_count_too_low")
            self.assertEqual(eval_report.result["assertions"][1]["actual"], 0)

    def test_assertion_presets_expand_to_replay_shape_checks(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "assertion_presets": ["replay_success_shape", "replay_handoff_present"],
                    "min_spans": 2,
                    "min_handoffs": 1,
                },
            )
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )

            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )

            self.assertEqual(eval_report.status, "passed")
            self.assertEqual(
                [assertion["type"] for assertion in eval_report.result["assertions"]],
                [
                    "replay_run_status_equals",
                    "replay_no_failed_spans",
                    "replay_span_count_at_least",
                    "replay_handoff_count_at_least",
                ],
            )
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 4, "passed": 4, "failed": 0})
            self.assertEqual(eval_report.result["assertions"][2]["actual"], 2)
            self.assertEqual(eval_report.result["assertions"][3]["actual"], 1)

    def test_unknown_assertion_preset_fails_with_supported_names(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "assertion_preset": "unknown_framework_shape",
                },
            )
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )

            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )

            self.assertEqual(eval_report.status, "failed")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 1, "passed": 0, "failed": 1})
            self.assertEqual(
                eval_report.result["assertions"][0]["reason"],
                "unsupported_assertion_preset:unknown_framework_shape",
            )
            self.assertEqual(
                eval_report.result["assertions"][0]["supported_presets"],
                ["replay_success_shape", "replay_handoff_present"],
            )

    def test_smoke_run_eval_executes_against_completed_replay_output_without_promoting_trust(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "smoke_run")
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "min_spans": 2,
                    "min_handoffs": 1,
                    "no_failed_spans": True,
                },
            )
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )

            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(eval_report.status, "passed")
            self.assertEqual(eval_report.promoted_trust_level, None)
            self.assertEqual(eval_report.result["comparison"], "smoke_run_checks_passed")
            self.assertEqual(eval_report.result["reason"], "all_smoke_checks_passed")
            self.assertEqual(eval_report.result["smoke_run_id"], "run_research_topic_replay_001")
            self.assertEqual(eval_report.result["smoke_run_source"], "replay_output")
            self.assertFalse(eval_report.result["gateable"])
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 5, "passed": 5, "failed": 0})
            self.assertEqual(
                [check["type"] for check in eval_report.result["assertions"]],
                [
                    "smoke_run_status_not_failed",
                    "smoke_replay_run_passed",
                    "smoke_no_failed_spans",
                    "smoke_span_count_at_least",
                    "smoke_handoff_count_at_least",
                ],
            )
            self.assertEqual(eval_specs[0]["eval_type"], "smoke_run")
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")

    def test_smoke_run_eval_reports_failed_source_trace_shape(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "smoke_run")
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "min_spans": 99,
                    "no_failed_spans": True,
                },
            )

            eval_report = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)

            self.assertEqual(eval_report.status, "failed")
            self.assertEqual(eval_report.result["comparison"], "smoke_run_checks_failed")
            self.assertEqual(eval_report.result["smoke_run_id"], "run_research_topic_001")
            self.assertEqual(eval_report.result["smoke_run_source"], "target")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 3, "passed": 1, "failed": 2})
            self.assertEqual(eval_report.result["assertions"][0]["reason"], "run_status_is_acceptable")
            self.assertEqual(eval_report.result["assertions"][1]["reason"], "failed_spans_present")
            self.assertEqual(eval_report.result["assertions"][2]["reason"], "span_count_too_low")
            self.assertLess(eval_report.result["assertions"][2]["actual"], 99)

    def test_regression_replay_eval_requires_replay_evidence(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "regression_replay")

            eval_report = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(eval_report.status, "errored")
            self.assertEqual(eval_report.result["error"], "replay_required")
            self.assertTrue(eval_report.result["required_replay"])
            self.assertTrue(eval_report.result["gateable"])
            self.assertIsNone(eval_report.promoted_trust_level)
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")

    def test_regression_replay_eval_promotes_with_completed_replay(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "regression_replay")
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )

            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(eval_report.status, "passed")
            self.assertEqual(eval_report.promoted_trust_level, "L2_regression")
            self.assertEqual(eval_report.result["eval_type"], "regression_replay")
            self.assertTrue(eval_report.result["required_replay"])
            self.assertTrue(eval_report.result["gateable"])
            self.assertEqual(eval_report.result["comparison"], "fail_before_pass_after")
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 3, "passed": 3, "failed": 0})
            self.assertEqual(eval_specs[0]["trust_level"], "L2_regression")

    def test_regression_replay_adds_before_after_assertion_when_operator_omits_it(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "regression_replay")
            _set_eval_assertions(
                db_path,
                eval_spec_id,
                [
                    {"type": "replay_span_count_at_least", "min": 2},
                ],
            )
            replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
            complete_replay_from_fixture(
                db_path=db_path,
                replay_run_id=replay.replay_run_id,
                fixture_path=REPLAY_SUCCESS,
            )

            eval_report = run_eval(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                replay_run_id=replay.replay_run_id,
            )

            self.assertEqual(eval_report.status, "passed")
            self.assertEqual(
                [assertion["type"] for assertion in eval_report.result["assertions"]],
                ["target_status_not_failed", "replay_span_count_at_least"],
            )
            self.assertEqual(eval_report.result["comparison"], "fail_before_pass_after")

    def test_recorded_judge_eval_executes_without_promoting_trust(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "judge")
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "rubric": "Recovered source evidence is complete and dated.",
                    "judgment": {
                        "verdict": "passed",
                        "judge": "operator_review_fixture",
                        "score": 0.91,
                        "reasoning": "The replay handoff includes recovered source evidence.",
                        "evidence_refs": [
                            {"entity_type": "span", "entity_id": "span_fetch_timeout_001"},
                        ],
                    },
                },
            )

            eval_report = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(eval_report.status, "passed")
            self.assertIsNone(eval_report.promoted_trust_level)
            self.assertEqual(eval_report.result["eval_type"], "judge")
            self.assertEqual(eval_report.result["judge_backend"], "recorded_judgment")
            self.assertEqual(eval_report.result["verdict"], "passed")
            self.assertEqual(eval_report.result["comparison"], "judge_verdict_passed")
            self.assertFalse(eval_report.result["gateable"])
            self.assertEqual(eval_report.result["assertion_counts"], {"total": 1, "passed": 1, "failed": 0})
            self.assertEqual(eval_report.result["assertions"][0]["type"], "recorded_judge_verdict")
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")

    def test_judge_command_captures_external_verdict_without_promoting_trust(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "judge")
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "rubric": "Recovered source evidence is complete and dated.",
                    "evidence_refs": [
                        {"entity_type": "span", "entity_id": "span_fetch_timeout_001"},
                    ],
                },
            )
            _add_sensitive_span_attribute(db_path)

            report = run_judge_command(
                db_path=db_path,
                eval_spec_id=eval_spec_id,
                output_dir=Path(tmpdir) / "judge",
                command=[sys.executable, str(JUDGE_COMMAND)],
            )
            request = json.loads(report.request_path.read_text())
            eval_specs = list_eval_specs(db_path)
            eval_runs = list_eval_runs(db_path)

            self.assertEqual(report.eval_run.status, "passed")
            self.assertIsNone(report.eval_run.promoted_trust_level)
            self.assertEqual(report.eval_run.result["eval_type"], "judge")
            self.assertEqual(report.eval_run.result["judge_backend"], "external_command")
            self.assertEqual(report.eval_run.result["verdict"], "passed")
            self.assertFalse(report.eval_run.result["gateable"])
            self.assertEqual(report.judgment["judge_backend"], "external_command")
            self.assertEqual(eval_specs[0]["definition"]["recorded_judgment"]["judge"], "fixture_external_judge")
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")
            request_spans = {
                span["id"]: span for span in request["evidence_bundle"]["spans"]
            }
            self.assertEqual(
                request_spans["span_fetch_timeout_001"]["input_ref"],
                "[REDACTED:payload_ref]",
            )
            self.assertEqual(
                request_spans["span_fetch_timeout_001"]["attributes_json"]["authorization"],
                "[REDACTED:secret]",
            )
            self.assertEqual(request["redaction"]["consumer"], "judge:command")
            artifact_kinds = {artifact["kind"] for artifact in eval_runs[0]["artifact_refs"]}
            self.assertEqual(
                artifact_kinds,
                {"judge_request", "judge_command_output", "judge_result"},
            )

    def test_recorded_judge_eval_requires_explicit_verdict(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            _set_eval_type(db_path, eval_spec_id, "judge")
            _set_eval_definition(
                db_path,
                eval_spec_id,
                {
                    "rubric": "Recovered source evidence is complete and dated.",
                    "judgment": {
                        "judge": "operator_review_fixture",
                        "score": 0.91,
                    },
                },
            )

            eval_report = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(eval_report.status, "errored")
            self.assertEqual(eval_report.result["error"], "judge_verdict_required")
            self.assertEqual(eval_report.result["comparison"], "judge_verdict_missing")
            self.assertFalse(eval_report.result["gateable"])
            self.assertIsNone(eval_report.promoted_trust_level)
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")

    def test_extract_judge_result_rejects_missing_block(self) -> None:
        with self.assertRaisesRegex(EvalError, "judge_output_must_contain_exactly_one_result_block"):
            extract_judge_result_from_output("no judge json")

    def test_judge_command_requires_judge_eval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            with self.assertRaisesRegex(EvalError, "judge_command_requires_judge_eval"):
                run_judge_command(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    output_dir=Path(tmpdir) / "judge",
                    command=[sys.executable, str(JUDGE_COMMAND)],
                )

    def test_unknown_eval_type_is_stored_but_not_executed_in_v0(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            _set_eval_type(db_path, eval_spec_id, "live_judge")
            eval_report = run_eval(db_path=db_path, eval_spec_id=eval_spec_id)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(eval_report.status, "errored")
            self.assertEqual(eval_report.result["error"], "unsupported_eval_type:live_judge")
            self.assertEqual(eval_report.result["supported_eval_type"], "deterministic_assertion")
            self.assertEqual(
                eval_report.result["supported_eval_types"],
                ["deterministic_assertion", "judge", "regression_replay", "smoke_run"],
            )
            self.assertIsNone(eval_report.promoted_trust_level)
            self.assertEqual(eval_specs[0]["trust_level"], "L0_generated")

    def test_replay_rejects_live_network(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)

            with self.assertRaisesRegex(EvalError, "unsafe_replay_side_effect_mode"):
                create_replay_run(
                    db_path=db_path,
                    eval_spec_id=eval_spec_id,
                    side_effect_mode="live_network",
                )


def _create_eval_spec(db_path: Path) -> str:
    ingest_source_fixture(db_path, FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    report = generate_evals_for_proposal(
        db_path=db_path,
        proposal_id="proposal_context_timeout_001",
    )
    return report.eval_spec_ids[0]


def _set_eval_assertions(db_path: Path, eval_spec_id: str, assertions: list[dict]) -> None:
    import sqlite3

    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT definition_json FROM eval_specs WHERE id = ?",
            (eval_spec_id,),
        ).fetchone()
        definition = json.loads(row[0])
        definition["assertions"] = assertions
        connection.execute(
            "UPDATE eval_specs SET definition_json = ? WHERE id = ?",
            (json.dumps(definition, sort_keys=True), eval_spec_id),
        )
        connection.commit()
    finally:
        connection.close()


def _set_eval_definition(db_path: Path, eval_spec_id: str, definition: dict) -> None:
    import sqlite3

    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute(
            "UPDATE eval_specs SET definition_json = ? WHERE id = ?",
            (json.dumps(definition, sort_keys=True), eval_spec_id),
        )
        connection.commit()
    finally:
        connection.close()


def _set_eval_type(db_path: Path, eval_spec_id: str, eval_type: str) -> None:
    import sqlite3

    connection = sqlite3.connect(str(db_path))
    try:
        connection.execute(
            "UPDATE eval_specs SET eval_type = ? WHERE id = ?",
            (eval_type, eval_spec_id),
        )
        connection.commit()
    finally:
        connection.close()


def _add_sensitive_span_attribute(db_path: Path) -> None:
    connection = sqlite3.connect(str(db_path))
    try:
        row = connection.execute(
            "SELECT attributes_json FROM spans WHERE id = ?",
            ("span_fetch_timeout_001",),
        ).fetchone()
        attributes = json.loads(row[0])
        attributes["authorization"] = "Bearer judge-command-secret-token"
        connection.execute(
            "UPDATE spans SET attributes_json = ? WHERE id = ?",
            (json.dumps(attributes, sort_keys=True), "span_fetch_timeout_001"),
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
