import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.autonomy import update_autonomy_policy
from kyoko.evals import (
    complete_replay_from_payload,
    create_replay_run,
    generate_evals_for_proposal,
    list_eval_specs,
    run_eval,
)
from kyoko.harness import list_patch_transactions
from kyoko.operator_adapters import register_operator_adapter
from kyoko.profile_next import run_profile_next_step
from kyoko.profiles import list_profiles
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.replay_adapters import register_replay_adapter
from kyoko.storage import ingest_source_fixture, ingest_source_payload, initialize_database
from tests.profile_fixtures import second_profile_payload


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class ProfileTests(unittest.TestCase):
    def test_list_profiles_returns_isolated_counts_and_latest_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            ingest_source_payload(
                db_path=db_path,
                fixture=second_profile_payload(),
                source_label="second-profile",
            )

            profiles = list_profiles(db_path)
            by_id = {profile["id"]: profile for profile in profiles}

            self.assertEqual([profile["id"] for profile in profiles], ["profile_news_research_001", "profile_second"])
            self.assertEqual(by_id["profile_news_research_001"]["counts"]["runs"], 1)
            self.assertEqual(by_id["profile_news_research_001"]["counts"]["spans"], 2)
            self.assertEqual(by_id["profile_news_research_001"]["counts"]["failed_runs"], 0)
            self.assertEqual(by_id["profile_news_research_001"]["counts"]["failed_spans"], 1)
            self.assertEqual(
                [identity["id"] for identity in by_id["profile_news_research_001"]["agent_identities"]],
                ["agent_researcher_001", "agent_writer_001", "agent_operator_codex_001"],
            )
            self.assertEqual(
                by_id["profile_news_research_001"]["agent_identities"][0]["name"],
                "researcher",
            )
            self.assertEqual(by_id["profile_news_research_001"]["latest_run"]["id"], "run_research_topic_001")
            self.assertEqual(by_id["profile_news_research_001"]["routing"]["state"], "needs_analysis")
            self.assertEqual(by_id["profile_news_research_001"]["routing"]["run_id"], "run_research_topic_001")
            self.assertEqual(
                [command["intent"] for command in by_id["profile_news_research_001"]["routing"]["suggested_commands"]],
                ["operator_adapter_bootstrap", "operator_prompt"],
            )
            self.assertEqual(by_id["profile_second"]["counts"]["runs"], 1)
            self.assertEqual(by_id["profile_second"]["counts"]["spans"], 1)
            self.assertEqual(by_id["profile_second"]["counts"]["failed_runs"], 1)
            self.assertEqual(by_id["profile_second"]["counts"]["failed_spans"], 1)
            self.assertEqual(by_id["profile_second"]["latest_run"]["id"], "run_second")
            self.assertEqual(by_id["profile_second"]["routing"]["state"], "needs_analysis")
            self.assertEqual(by_id["profile_second"]["routing"]["next_action"], "analyze")
            self.assertIn(
                "--profile-id",
                by_id["profile_second"]["routing"]["suggested_commands"][0]["cli_args"],
            )

    def test_profile_routing_tracks_next_improvement_step(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            proposed = list_profiles(db_path)[0]["routing"]
            self.assertEqual(proposed["state"], "needs_eval_generation")
            self.assertEqual(proposed["next_action"], "generate_evals")
            self.assertEqual(proposed["proposal_id"], "proposal_context_timeout_001")
            self.assertEqual(proposed["suggested_commands"][0]["intent"], "generate_evals")
            self.assertEqual(
                proposed["suggested_commands"][0]["cli_args"][-2:],
                ["proposal_context_timeout_001", "--json"],
            )

            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=Path(tmpdir) / "replay",
                default_side_effect_mode="network_mocked",
            )
            generate_evals_for_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
            eval_generated = list_profiles(db_path)[0]["routing"]
            self.assertEqual(eval_generated["state"], "needs_replay_or_eval")
            self.assertEqual(eval_generated["next_action"], "run_replay_or_eval")
            self.assertEqual(eval_generated["eval_spec_id"], "eval_proposal_context_timeout_001_1")
            self.assertEqual(eval_generated["eval_run_status"], "not_run")
            self.assertEqual(
                [command["intent"] for command in eval_generated["suggested_commands"]],
                ["run_replay_adapter", "run_eval"],
            )
            self.assertIn("fixture_replay", eval_generated["suggested_commands"][0]["cli_args"])

            replay = create_replay_run(
                db_path=db_path,
                eval_spec_id="eval_proposal_context_timeout_001_1",
            )
            _complete_replay_from_fixture_payload(db_path, replay.replay_run_id)
            run_eval(
                db_path=db_path,
                eval_spec_id="eval_proposal_context_timeout_001_1",
                replay_run_id=replay.replay_run_id,
            )

            ready = list_profiles(db_path)[0]["routing"]
            self.assertEqual(ready["state"], "ready_for_autonomy")
            self.assertEqual(ready["next_action"], "review_proposal")
            self.assertEqual(ready["reason"], "passing_eval_available")
            self.assertEqual(ready["eval_run_status"], "passed")
            self.assertEqual(ready["replay_run_status"], "passed")
            self.assertEqual(ready["suggested_commands"][0]["intent"], "proposal_detail")

            update_autonomy_policy(db_path=db_path, context_mode="autonomous")
            autonomous = list_profiles(db_path)[0]["routing"]
            self.assertEqual(autonomous["state"], "ready_for_autonomy")
            self.assertEqual(autonomous["next_action"], "run_autonomy")
            self.assertEqual(autonomous["autonomy_mode"], "autonomous")
            self.assertEqual(
                [command["intent"] for command in autonomous["suggested_commands"]],
                ["run_autonomy", "proposal_detail"],
            )

    def test_profile_routing_includes_harness_workspace_root_for_autonomous_apply(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            _prepare_ready_harness_proposal(db_path=db_path, workspace=workspace)

            routing = list_profiles(db_path)[0]["routing"]
            run_autonomy = routing["suggested_commands"][0]

            self.assertEqual(routing["state"], "ready_for_autonomy")
            self.assertEqual(routing["next_action"], "run_autonomy")
            self.assertEqual(routing["proposal_section"], "harness")
            self.assertTrue(routing["harness_repo_patch_allowed"])
            self.assertFalse(routing["harness_workspace_root_required"])
            self.assertEqual(routing["harness_workspace_root_status"], "available")
            self.assertEqual(routing["harness_workspace_root"], str(workspace))
            self.assertEqual(run_autonomy["requires"], [])
            self.assertIn("--harness-workspace-root", run_autonomy["cli_args"])
            self.assertIn(str(workspace), run_autonomy["cli_args"])

    def test_profile_next_step_runs_harness_autonomy_with_profile_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "evals/generated_timeout_eval.py"
            _prepare_ready_harness_proposal(db_path=db_path, workspace=workspace)

            report = run_profile_next_step(db_path=db_path, run=True)
            patches = list_patch_transactions(db_path)

            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "ran_autonomy")
            self.assertEqual(report.result["decisions"][0]["action"], "applied")
            self.assertEqual(report.routing_after["state"], "loop_complete")
            self.assertEqual(patches[0]["status"], "applied")
            self.assertTrue(target.exists())
            self.assertIn("TIMEOUT_SPAN_ID", target.read_text())

    def test_profile_next_step_blocks_harness_autonomy_without_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "missing-workspace"
            _prepare_ready_harness_proposal(db_path=db_path, workspace=workspace)

            report = run_profile_next_step(db_path=db_path, run=True)

            self.assertEqual(report.status, "blocked")
            self.assertEqual(report.action, "run_autonomy")
            self.assertEqual(report.reason, f"harness_workspace_root_not_found:{workspace}")
            self.assertIn("pass --harness-workspace-root", report.notes[0])

    def test_profile_next_step_dry_run_and_eval_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            dry_run = run_profile_next_step(db_path=db_path)
            self.assertFalse(dry_run.run_requested)
            self.assertEqual(dry_run.status, "planned")
            self.assertEqual(dry_run.action, "generate_evals")
            self.assertEqual(list_eval_specs(db_path), [])

            report = run_profile_next_step(db_path=db_path, run=True)

            self.assertTrue(report.run_requested)
            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "generated_eval_specs")
            self.assertEqual(report.result["eval_spec_ids"], ["eval_proposal_context_timeout_001_1"])
            self.assertEqual(report.routing_after["state"], "needs_replay_or_eval")
            self.assertEqual(len(list_eval_specs(db_path)), 1)

    def test_profile_next_step_generates_fallback_eval_for_harness_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )

            dry_run = run_profile_next_step(db_path=db_path)
            report = run_profile_next_step(db_path=db_path, run=True)
            eval_specs = list_eval_specs(db_path)

            self.assertEqual(dry_run.action, "generate_evals")
            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "generated_eval_specs")
            self.assertEqual(
                report.result["eval_spec_ids"],
                ["eval_proposal_harness_generated_eval_001_1"],
            )
            self.assertEqual(report.routing_after["state"], "needs_replay_or_eval")
            self.assertEqual(
                eval_specs[0]["definition"]["operator_definition"]["generated_by"],
                "kyoko_fallback_harness_eval",
            )

    def test_profile_next_step_prepares_operator_prompt_for_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator"
            ingest_source_fixture(db_path, FIXTURE)

            report = run_profile_next_step(
                db_path=db_path,
                run=True,
                operator_target="codex",
                operator_output_dir=output_dir,
                schema_path=SCHEMA,
            )

            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "prepared_operator_prompt")
            self.assertEqual(report.result["target"], "codex")
            self.assertTrue(Path(report.result["evidence_path"]).exists())
            self.assertTrue(Path(report.result["prompt_path"]).exists())
            self.assertEqual(report.routing_after["state"], "needs_analysis")
            self.assertEqual(report.routing_after["next_action"], "analyze")

    def test_profile_next_report_exposes_suggested_commands_for_planned_and_blocked_steps(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _create_empty_profile(db_path)

            dry_run = run_profile_next_step(db_path=db_path)
            blocked = run_profile_next_step(db_path=db_path, run=True)

            dry_payload = dry_run.to_json()
            blocked_payload = blocked.to_json()
            self.assertEqual(dry_payload["status"], "planned")
            self.assertEqual(
                dry_payload["suggested_commands"],
                dry_payload["routing_after"]["suggested_commands"],
            )
            self.assertEqual(dry_payload["suggested_commands"][0]["intent"], "discover_sources")
            self.assertEqual(blocked_payload["status"], "blocked")
            self.assertEqual(blocked_payload["reason"], "source_import_required")
            self.assertEqual(
                blocked_payload["suggested_commands"],
                blocked_payload["routing_after"]["suggested_commands"],
            )
            self.assertEqual(blocked_payload["suggested_commands"][0]["intent"], "discover_sources")
            self.assertIn("--profile-id", blocked_payload["suggested_commands"][0]["cli_args"])

    def test_profile_next_step_runs_default_registered_operator_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"
            ingest_source_fixture(db_path, FIXTURE)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                command=[sys.executable, str(OPERATOR_COMMAND)],
                output_dir=output_dir,
            )

            report = run_profile_next_step(
                db_path=db_path,
                run=True,
                schema_path=SCHEMA,
            )

            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "ran_operator_adapter")
            self.assertEqual(report.result["adapter_id"], "fixture_operator")
            self.assertEqual(report.result["operator"], "fixture_operator")
            self.assertEqual(report.result["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertTrue(report.result["operator_run_id"])
            self.assertTrue(Path(report.result["raw_output_path"]).exists())
            self.assertEqual(report.routing_after["state"], "needs_eval_generation")

    def test_profile_next_step_explicit_operator_target_keeps_prompt_only_with_registered_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator"
            ingest_source_fixture(db_path, FIXTURE)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="codex_local",
                name="Codex local",
                command=[sys.executable, "-c", "pass"],
                operator_kind="codex",
            )

            report = run_profile_next_step(
                db_path=db_path,
                run=True,
                operator_target="codex",
                operator_output_dir=output_dir,
                schema_path=SCHEMA,
            )

            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "prepared_operator_prompt")
            self.assertEqual(report.result["target"], "codex")

    def test_profile_next_step_defaults_replay_adapter_from_routing_order(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            generate_evals_for_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
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

            routing = list_profiles(db_path)[0]["routing"]
            report = run_profile_next_step(db_path=db_path, run=True)

            self.assertEqual(routing["suggested_commands"][0]["cli_args"][6], "zzz_replay")
            self.assertEqual(report.status, "executed")
            self.assertEqual(report.reason, "ran_replay_adapter")
            self.assertEqual(report.result["adapter_id"], "zzz_replay")

def _prepare_ready_harness_proposal(*, db_path: Path, workspace: Path) -> None:
    proposal_id = "proposal_harness_profile_next_apply_001"
    proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
    proposal["id"] = proposal_id
    proposal["producer"]["session_id"] = "operator_session_harness_profile_next_apply_001"
    proposal["gate_expectations"]["requires_human_review"] = False
    proposal["proposed_changes"].append(
        {
            "type": "eval_spec",
            "name": "harness generated file profile-next gate",
            "eval_type": "deterministic_assertion",
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
    ingest_source_fixture(db_path, FIXTURE)
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
    generate_evals_for_proposal(db_path=db_path, proposal_id=proposal_id)
    eval_spec_id = f"eval_{proposal_id}_1"
    replay = create_replay_run(db_path=db_path, eval_spec_id=eval_spec_id)
    _complete_replay_from_fixture_payload(db_path, replay.replay_run_id)
    run_eval(
        db_path=db_path,
        eval_spec_id=eval_spec_id,
        replay_run_id=replay.replay_run_id,
    )
    _set_profile_root_path(db_path, workspace)


def _set_profile_root_path(db_path: Path, root_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE profiles SET root_path = ? WHERE id = ?",
            (str(root_path), "profile_news_research_001"),
        )


def _create_empty_profile(db_path: Path) -> None:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO profiles (id, name, root_path, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "profile_empty",
                "Empty profile",
                "",
                "active",
                "2026-06-02T00:00:00Z",
                "2026-06-02T00:00:00Z",
            ),
        )


def _complete_replay_from_fixture_payload(db_path: Path, replay_run_id: str) -> None:
    replay_fixture = json.loads(REPLAY_SUCCESS.read_text())
    replay_fixture["replay"]["replay_run_id"] = replay_run_id
    complete_replay_from_payload(
        db_path=db_path,
        replay_run_id=replay_run_id,
        fixture=replay_fixture,
        source_label=f"profile-next-replay-fixture-{replay_run_id}",
    )
