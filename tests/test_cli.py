import io
import copy
import importlib
import json
import shlex
import sqlite3
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from kyoko.apply import apply_context_proposal
from kyoko.cli import main
from kyoko.dashboard_smoke import DashboardSmokeError
from kyoko.mcp import McpClientInstallSmokeMatrixReport, McpClientInstallSmokeTargetReport
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.release_smoke import ReleaseInstallSmokeMatrixReport, PythonReleaseSmokeTargetReport
from kyoko.storage import ingest_source_fixture, ingest_source_payload, initialize_database
from tests.profile_fixtures import second_profile_payload, second_profile_proposal
from tests.test_improve import _write_failed_openclaw_session
from tests.test_replay_servers import RunningReplayServer, _fixture_replay_server_command, _free_port


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
OTLP_FIXTURE = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_HARNESS_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-harness-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
INVALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/invalid-hallucinated-span.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
OPERATOR_RETRY_COMMAND = ROOT / "tests/fixtures/operator_command_retry.py"
OPERATOR_BAD_COMMAND = ROOT / "tests/fixtures/operator_command_bad_output.py"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"
JUDGE_COMMAND = ROOT / "tests/fixtures/judge_command.py"


class CliTests(unittest.TestCase):
    def test_bundled_assets_list_export_and_ingest_flow(self) -> None:
        list_out = io.StringIO()
        with redirect_stdout(list_out):
            list_code = main(["bundled-assets", "--json"])
        self.assertEqual(list_code, 0)
        list_payload = json.loads(list_out.getvalue())
        asset_paths = {asset["path"] for asset in list_payload["assets"]}
        self.assertIn("source-events/hermes-news-research-minimal.json", asset_paths)
        self.assertIn("learning-proposals/valid-context-proposal.json", asset_paths)
        self.assertIn("learning-proposals/valid-harness-proposal.json", asset_paths)
        self.assertIn(
            "learning-proposals/valid-harness-generated-file-proposal.json",
            asset_paths,
        )
        self.assertEqual(list_payload["exported"], [])

        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            export_dir = tmp_path / "bundled-assets"
            export_out = io.StringIO()
            with redirect_stdout(export_out):
                export_code = main(
                    [
                        "bundled-assets",
                        "--output-dir",
                        str(export_dir),
                        "--json",
                    ]
                )
            self.assertEqual(export_code, 0)
            export_payload = json.loads(export_out.getvalue())
            exported_paths = {item["asset"] for item in export_payload["exported"]}
            self.assertIn("source-events/hermes-news-research-minimal.json", exported_paths)
            exported_source = export_dir / "source-events/hermes-news-research-minimal.json"
            self.assertTrue(exported_source.exists())

            db_path = tmp_path / "kyoko.db"
            ingest_out = io.StringIO()
            with redirect_stdout(ingest_out):
                ingest_code = main(["ingest-fixture", "--db", str(db_path), str(exported_source)])
            self.assertEqual(ingest_code, 0)
            self.assertIn("profile_news_research_001", ingest_out.getvalue())

    def test_bundled_assets_exports_single_asset_and_rejects_unknown_asset(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "schema.json"
            export_out = io.StringIO()
            with redirect_stdout(export_out):
                export_code = main(
                    [
                        "bundled-assets",
                        "--asset",
                        "schemas/learning-proposal.schema.json",
                        "--output",
                        str(output_path),
                        "--json",
                    ]
                )
            self.assertEqual(export_code, 0)
            payload = json.loads(export_out.getvalue())
            self.assertEqual(
                payload["exported"],
                [
                    {
                        "asset": "schemas/learning-proposal.schema.json",
                        "output_path": str(output_path),
                    }
                ],
            )
            self.assertTrue(output_path.exists())

        error_out = io.StringIO()
        with redirect_stderr(error_out):
            error_code = main(
                [
                    "bundled-assets",
                    "--asset",
                    "../outside.json",
                    "--output",
                    "/tmp/outside.json",
                    "--json",
                ]
            )
        self.assertEqual(error_code, 1)
        self.assertIn("bundled_asset_invalid_path", error_out.getvalue())

    def test_init_ingest_status_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            init_out = io.StringIO()
            with redirect_stdout(init_out):
                init_code = main(["init", "--db", str(db_path)])
            self.assertEqual(init_code, 0)
            self.assertIn("initialized Kyoko database", init_out.getvalue())

            ingest_out = io.StringIO()
            with redirect_stdout(ingest_out):
                ingest_code = main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)])
            self.assertEqual(ingest_code, 0)
            self.assertIn("profile_news_research_001", ingest_out.getvalue())

            status_out = io.StringIO()
            with redirect_stdout(status_out):
                status_code = main(["status", "--db", str(db_path), "--json"])
            self.assertEqual(status_code, 0)

            payload = json.loads(status_out.getvalue())
            self.assertTrue(payload["initialized"])
            self.assertEqual(payload["schema_version"], 25)
            self.assertEqual(payload["counts"]["spans"], 2)
            self.assertEqual(payload["counts"]["issues"], 0)

            metrics_out = io.StringIO()
            with redirect_stdout(metrics_out):
                metrics_code = main(["dashboard-metrics", "--db", str(db_path), "--json"])
            self.assertEqual(metrics_code, 0)
            metrics_payload = json.loads(metrics_out.getvalue())
            self.assertEqual(metrics_payload["profile_id"], "profile_news_research_001")
            self.assertEqual(metrics_payload["runs"]["failed_spans"], 1)
            self.assertEqual(metrics_payload["cards"][0]["id"], "issues")

            checkpoint_out = io.StringIO()
            with redirect_stdout(checkpoint_out):
                checkpoint_code = main(
                    [
                        "wal-checkpoint",
                        "--db",
                        str(db_path),
                        "--mode",
                        "TRUNCATE",
                        "--json",
                    ]
                )
            self.assertEqual(checkpoint_code, 0)
            checkpoint_payload = json.loads(checkpoint_out.getvalue())
            self.assertEqual(checkpoint_payload["mode"], "TRUNCATE")
            self.assertIn("wal_size_before", checkpoint_payload)
            self.assertIn("wal_size_after", checkpoint_payload)
            self.assertEqual(payload["counts"]["handoffs"], 1)

    def test_generic_ingest_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            ingest_out = io.StringIO()
            with redirect_stdout(ingest_out):
                ingest_code = main(["ingest", "--db", str(db_path), str(FIXTURE), "--json"])
            self.assertEqual(ingest_code, 0)
            ingest_payload = json.loads(ingest_out.getvalue())
            self.assertEqual(ingest_payload["profile_id"], "profile_news_research_001")
            self.assertEqual(ingest_payload["ingested_counts"]["runs"], 1)

            status_out = io.StringIO()
            with redirect_stdout(status_out):
                status_code = main(["status", "--db", str(db_path), "--json"])
            self.assertEqual(status_code, 0)
            status_payload = json.loads(status_out.getvalue())
            self.assertEqual(status_payload["counts"]["spans"], 2)

    def test_proposals_command_can_filter_by_profile(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
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

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["proposals", "--db", str(db_path), "--profile-id", "profile_second", "--json"])

            payload = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual([proposal["id"] for proposal in payload["proposals"]], ["proposal_second_context"])
            self.assertEqual(payload["proposals"][0]["section_label"], "Context fix")

    def test_profile_next_flow_plans_and_runs_check_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )

            dry_out = io.StringIO()
            with redirect_stdout(dry_out):
                dry_code = main(["profile-next", "--db", str(db_path), "--json"])

            self.assertEqual(dry_code, 0)
            dry_payload = json.loads(dry_out.getvalue())
            self.assertEqual(dry_payload["status"], "planned")
            self.assertEqual(dry_payload["action"], "generate_checks")

            run_out = io.StringIO()
            with redirect_stdout(run_out):
                run_code = main(["profile-next", "--db", str(db_path), "--run", "--json"])

            self.assertEqual(run_code, 0)
            run_payload = json.loads(run_out.getvalue())
            self.assertEqual(run_payload["status"], "executed")
            self.assertEqual(run_payload["reason"], "generated_check_specs")
            self.assertEqual(run_payload["result"]["check_spec_ids"], ["check_proposal_context_timeout_001_1"])
            self.assertEqual(run_payload["routing_after"]["state"], "needs_replay_or_check")

    def test_profile_next_flow_prepares_operator_prompt_for_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "profile-next",
                        "--db",
                        str(db_path),
                        "--run",
                        "--operator-target",
                        "codex",
                        "--operator-output-dir",
                        str(output_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["status"], "executed")
            self.assertEqual(payload["reason"], "prepared_operator_prompt")
            self.assertEqual(payload["result"]["target"], "codex")
            self.assertTrue(Path(payload["result"]["evidence_path"]).exists())
            self.assertTrue(Path(payload["result"]["prompt_path"]).exists())
            self.assertEqual(payload["routing_after"]["state"], "needs_analysis")

    def test_profile_next_json_exposes_suggested_commands_for_blocked_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _create_empty_profile(db_path)

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["profile-next", "--db", str(db_path), "--run", "--json"])

            payload = json.loads(out.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["status"], "blocked")
            self.assertEqual(payload["reason"], "source_import_required")
            self.assertEqual(
                payload["suggested_commands"],
                payload["routing_after"]["suggested_commands"],
            )
            self.assertEqual(payload["suggested_commands"][0]["intent"], "discover_sources")

    def test_profile_next_explicit_operator_target_keeps_prompt_only_with_registered_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "operator-adapter-register",
                            "--db",
                            str(db_path),
                            "codex_local",
                            "--name",
                            "Codex local",
                            "--kind",
                            "codex",
                            "--command",
                            f"{sys.executable} -c pass",
                            "--json",
                        ]
                    ),
                    0,
                )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "profile-next",
                        "--db",
                        str(db_path),
                        "--run",
                        "--operator-target",
                        "codex",
                        "--operator-output-dir",
                        str(output_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["status"], "executed")
            self.assertEqual(payload["reason"], "prepared_operator_prompt")
            self.assertEqual(payload["result"]["target"], "codex")

    def test_profile_next_runs_registered_operator_adapter_for_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "operator-adapter-register",
                            "--db",
                            str(db_path),
                            "fixture_operator",
                            "--name",
                            "Fixture operator",
                            "--kind",
                            "generic",
                            "--command",
                            f"{shlex.quote(sys.executable)} {shlex.quote(str(OPERATOR_COMMAND))}",
                            "--json",
                        ]
                    ),
                    0,
                )

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "profile-next",
                        "--db",
                        str(db_path),
                        "--run",
                        "--operator-adapter",
                        "fixture_operator",
                        "--operator-output-dir",
                        str(output_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["status"], "executed")
            self.assertEqual(payload["reason"], "ran_operator_adapter")
            self.assertEqual(payload["result"]["adapter_id"], "fixture_operator")
            self.assertEqual(payload["result"]["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertTrue(payload["result"]["operator_run_id"])
            self.assertTrue(Path(payload["result"]["raw_output_path"]).exists())
            self.assertEqual(payload["routing_after"]["state"], "needs_check_generation")

    def test_profile_next_rejects_unknown_all_profiles_flag(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            err = io.StringIO()
            with redirect_stderr(err), self.assertRaises(SystemExit):
                main(
                    [
                        "profile-next",
                        "--db",
                        str(db_path),
                        "--all-profiles",
                        "--json",
                    ]
                )

            self.assertIn("--all-profiles", err.getvalue())

    def test_release_smoke_python_matrix_cli_uses_requested_targets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "release-matrix"
            fake_report = ReleaseInstallSmokeMatrixReport(
                project_root=ROOT,
                output_dir=output_dir,
                python_targets=("3.12",),
                artifact_types=("wheel",),
                install_dependencies=False,
                run_demo=False,
                dashboard_smoke=True,
                targets=(
                    PythonReleaseSmokeTargetReport(
                        target="3.12",
                        python_executable="/usr/bin/python3.12",
                        status="passed",
                        reason=None,
                        report=None,
                    ),
                ),
                passed=True,
                duration_ms=1.0,
            )

            out = io.StringIO()
            with patch("kyoko.cli.run_release_install_smoke_matrix", return_value=fake_report) as smoke:
                with redirect_stdout(out):
                    code = main(
                        [
                            "release-smoke",
                            "--project-root",
                            str(ROOT),
                            "--output-dir",
                            str(output_dir),
                            "--artifact",
                            "wheel",
                            "--skip-demo",
                            "--dashboard-smoke",
                            "--python-version",
                            "3.12",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["summary"]["passed"], 1)
            self.assertTrue(payload["dashboard_smoke"])
            self.assertEqual(smoke.call_args.kwargs["python_targets"], ("3.12",))
            self.assertEqual(smoke.call_args.kwargs["artifact_types"], ("wheel",))
            self.assertTrue(smoke.call_args.kwargs["dashboard_smoke"])

    def test_blob_storage_and_prune_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            payload_path = Path(tmpdir) / "payload.txt"
            payload_path.write_text("temporary payload")

            put_out = io.StringIO()
            with redirect_stdout(put_out):
                put_code = main(
                    [
                        "blob-put",
                        "--db",
                        str(db_path),
                        str(payload_path),
                        "--media-type",
                        "text/plain",
                        "--retention-days",
                        "0",
                        "--json",
                    ]
                )
            self.assertEqual(put_code, 0)
            put_payload = json.loads(put_out.getvalue())
            self.assertTrue(Path(put_payload["path"]).exists())

            report_out = io.StringIO()
            with redirect_stdout(report_out):
                report_code = main(["storage-report", "--db", str(db_path), "--json"])
            self.assertEqual(report_code, 0)
            report_payload = json.loads(report_out.getvalue())
            self.assertEqual(report_payload["registered_blobs"], 1)

            list_out = io.StringIO()
            with redirect_stdout(list_out):
                list_code = main(["blobs", "--db", str(db_path), "--json"])
            self.assertEqual(list_code, 0)
            list_payload = json.loads(list_out.getvalue())
            self.assertEqual(list_payload["payload_blobs"][0]["id"], put_payload["blob_id"])

            dry_run_out = io.StringIO()
            with redirect_stdout(dry_run_out):
                dry_run_code = main(["prune", "--db", str(db_path), "--json"])
            self.assertEqual(dry_run_code, 0)
            dry_run_payload = json.loads(dry_run_out.getvalue())
            self.assertTrue(dry_run_payload["dry_run"])
            self.assertEqual(len(dry_run_payload["pruned_blobs"]), 1)
            self.assertTrue(Path(put_payload["path"]).exists())

            apply_out = io.StringIO()
            with redirect_stdout(apply_out):
                apply_code = main(["prune", "--db", str(db_path), "--apply", "--json"])
            self.assertEqual(apply_code, 0)
            apply_payload = json.loads(apply_out.getvalue())
            self.assertFalse(apply_payload["dry_run"])
            self.assertEqual(len(apply_payload["pruned_blobs"]), 1)
            self.assertFalse(Path(put_payload["path"]).exists())

    def test_prune_retention_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            dry_run_out = io.StringIO()
            with redirect_stdout(dry_run_out):
                dry_run_code = main(
                    [
                        "prune-retention",
                        "--db",
                        str(db_path),
                        "--trace-older-than-days",
                        "0",
                        "--json",
                    ]
                )
            self.assertEqual(dry_run_code, 0)
            dry_run_payload = json.loads(dry_run_out.getvalue())
            self.assertTrue(dry_run_payload["dry_run"])
            self.assertEqual(dry_run_payload["pruned_rows"]["runs"], ["run_research_topic_001"])
            self.assertNotIn("redaction_audit_events", dry_run_payload["pruned_rows"])

            apply_out = io.StringIO()
            with redirect_stdout(apply_out):
                apply_code = main(
                    [
                        "prune-retention",
                        "--db",
                        str(db_path),
                        "--trace-older-than-days",
                        "0",
                        "--apply",
                        "--json",
                    ]
                )
            self.assertEqual(apply_code, 0)
            apply_payload = json.loads(apply_out.getvalue())
            self.assertFalse(apply_payload["dry_run"])
            self.assertEqual(apply_payload["summary"]["pruned_rows"], 8)

    def test_load_smoke_cli_uses_temporary_database_by_default(self) -> None:
        smoke_out = io.StringIO()
        with redirect_stdout(smoke_out):
            smoke_code = main(
                [
                    "load-smoke",
                    "--runs",
                    "4",
                    "--spans-per-run",
                    "2",
                    "--read-workers",
                    "1",
                    "--read-iterations",
                    "1",
                    "--expired-blobs",
                    "1",
                    "--json",
                ]
            )

        self.assertEqual(smoke_code, 0)
        payload = json.loads(smoke_out.getvalue())
        self.assertTrue(payload["temporary"])
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["status"]["counts"]["runs"], 4)
        self.assertEqual(payload["status"]["counts"]["spans"], 8)
        self.assertEqual(len(payload["retention_dry_run"]["pruned_blobs"]), 1)
        self.assertIn("evidence_summary", payload["operation_latency_ms"])

    def test_load_smoke_cli_can_seed_selected_database(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            smoke_out = io.StringIO()
            with redirect_stdout(smoke_out):
                smoke_code = main(
                    [
                        "load-smoke",
                        "--db",
                        str(db_path),
                        "--use-db",
                        "--runs",
                        "3",
                        "--spans-per-run",
                        "2",
                        "--read-workers",
                        "1",
                        "--read-iterations",
                        "1",
                        "--expired-blobs",
                        "1",
                        "--json",
                    ]
                )

            self.assertEqual(smoke_code, 0)
            payload = json.loads(smoke_out.getvalue())
            self.assertFalse(payload["temporary"])
            self.assertEqual(payload["db_path"], str(db_path))
            self.assertEqual(payload["status"]["counts"]["runs"], 3)

    def test_release_smoke_cli_builds_and_installs_wheel(self) -> None:
        smoke_out = io.StringIO()
        with redirect_stdout(smoke_out):
            smoke_code = main(
                [
                    "release-smoke",
                    "--project-root",
                    str(ROOT),
                    "--artifact",
                    "wheel",
                    "--skip-demo",
                    "--timeout-seconds",
                    "120",
                    "--json",
                ]
            )

        self.assertEqual(smoke_code, 0)
        payload = json.loads(smoke_out.getvalue())
        self.assertTrue(payload["temporary"])
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["artifacts"][0]["artifact_type"], "wheel")
        self.assertEqual(payload["artifacts"][0]["installed_version"], "0.1.0")
        self.assertTrue(payload["artifacts"][0]["doctor_ok"])

    def test_runs_and_run_detail_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            runs_out = io.StringIO()
            with redirect_stdout(runs_out):
                runs_code = main(["runs", "--db", str(db_path), "--json"])
            self.assertEqual(runs_code, 0)
            runs_payload = json.loads(runs_out.getvalue())
            self.assertEqual(runs_payload["runs"][0]["id"], "run_research_topic_001")
            self.assertEqual(runs_payload["runs"][0]["failed_span_count"], 1)

            detail_out = io.StringIO()
            with redirect_stdout(detail_out):
                detail_code = main(
                    [
                        "run-detail",
                        "--db",
                        str(db_path),
                        "run_research_topic_001",
                        "--json",
                    ]
                )
            self.assertEqual(detail_code, 0)
            detail_payload = json.loads(detail_out.getvalue())
            self.assertEqual(detail_payload["run"]["id"], "run_research_topic_001")
            self.assertEqual(detail_payload["summary"]["spans"], 2)
            self.assertEqual(detail_payload["span_tree"][0]["children"][0]["id"], "span_fetch_timeout_001")

    def test_policy_and_policy_set_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            policy_out = io.StringIO()
            with redirect_stdout(policy_out):
                policy_code = main(["policy", "--db", str(db_path), "--json"])
            self.assertEqual(policy_code, 0)
            policy_payload = json.loads(policy_out.getvalue())
            self.assertEqual(policy_payload["policy"]["context_mode"], "propose")
            self.assertFalse(policy_payload["policy"]["allow_repo_patch"])

            set_out = io.StringIO()
            with redirect_stdout(set_out):
                set_code = main(
                    [
                        "policy-set",
                        "--db",
                        str(db_path),
                        "--context-mode",
                        "autonomous",
                        "--harness-mode",
                        "propose",
                        "--repo-patch",
                        "on",
                        "--dirty-worktree-policy",
                        "block",
                        "--json",
                    ]
                )
            self.assertEqual(set_code, 0)
            set_payload = json.loads(set_out.getvalue())
            self.assertEqual(set_payload["policy"]["context_mode"], "autonomous")
            self.assertEqual(set_payload["policy"]["harness_mode"], "propose")
            self.assertTrue(set_payload["policy"]["allow_repo_patch"])

    def test_evidence_cli_redacts_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            evidence_path = Path(tmpdir) / "evidence.json"
            evidence_out = io.StringIO()
            with redirect_stdout(evidence_out):
                evidence_code = main(["evidence", "--db", str(db_path), "--output", str(evidence_path)])
            self.assertEqual(evidence_code, 0)

            bundle = json.loads(evidence_path.read_text())
            self.assertEqual(bundle["redaction"]["policy"]["payload_access"], "redacted")
            self.assertTrue(bundle["redaction"]["policy"]["redact_sensitive_values"])
            self.assertEqual(bundle["redaction"]["consumer"], "cli:evidence")

    def test_ingest_otlp_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            normalized_path = Path(tmpdir) / "normalized.json"

            ingest_out = io.StringIO()
            with redirect_stdout(ingest_out):
                ingest_code = main(
                    [
                        "ingest-otlp",
                        "--db",
                        str(db_path),
                        str(OTLP_FIXTURE),
                        "--profile-id",
                        "profile_otlp_news_001",
                        "--profile-name",
                        "OTLP News",
                        "--root-path",
                        tmpdir,
                        "--source-kind",
                        "otlp_http",
                        "--output",
                        str(normalized_path),
                        "--json",
                    ]
                )
            self.assertEqual(ingest_code, 0)
            ingest_payload = json.loads(ingest_out.getvalue())
            self.assertEqual(ingest_payload["profile_id"], "profile_otlp_news_001")
            self.assertEqual(ingest_payload["ingested_counts"]["spans"], 2)
            self.assertEqual(ingest_payload["normalized_path"], str(normalized_path))
            self.assertTrue(normalized_path.exists())

    def test_propose_and_list_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            propose_out = io.StringIO()
            with redirect_stdout(propose_out):
                propose_code = main(
                    [
                        "propose",
                        "--db",
                        str(db_path),
                        "--schema",
                        str(SCHEMA),
                        str(VALID_PROPOSAL),
                    ]
                )
            self.assertEqual(propose_code, 0)
            self.assertIn("proposal accepted: proposal_context_timeout_001", propose_out.getvalue())

            proposals_out = io.StringIO()
            with redirect_stdout(proposals_out):
                proposals_code = main(["proposals", "--db", str(db_path), "--json"])
            self.assertEqual(proposals_code, 0)

            payload = json.loads(proposals_out.getvalue())
            self.assertEqual(len(payload["proposals"]), 1)
            self.assertEqual(payload["proposals"][0]["id"], "proposal_context_timeout_001")
            self.assertEqual(payload["proposals"][0]["kyoko_confidence"], 0.66)

    def test_proposal_detail_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )

            detail_out = io.StringIO()
            with redirect_stdout(detail_out):
                detail_code = main(
                    [
                        "proposal-detail",
                        "--db",
                        str(db_path),
                        "proposal_context_timeout_001",
                        "--json",
                    ]
                )

            self.assertEqual(detail_code, 0)
            payload = json.loads(detail_out.getvalue())
            self.assertEqual(payload["proposal"]["id"], "proposal_context_timeout_001")
            self.assertEqual(payload["proposal"]["section_label"], "Context fix")
            self.assertEqual(payload["target"]["ref"]["entity_id"], "agent_researcher_001")
            self.assertEqual(payload["autonomy_gate"]["reason"], "context_policy_propose")
            self.assertEqual(payload["confidence_assessment"]["kyoko_confidence"], 0.66)
            self.assertEqual(len(payload["evidence"]), 2)
            self.assertEqual(payload["check_guidance"]["gateable_check_types"], ["deterministic_assertion", "regression_replay"])
            self.assertEqual(
                [preset["name"] for preset in payload["check_guidance"]["assertion_presets"]],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertEqual(payload["evidence_chain"]["steps"][0]["stage"], "observed_issue")
            self.assertEqual(payload["evidence_chain"]["steps"][2]["status"], "not_generated")

            text_out = io.StringIO()
            with redirect_stdout(text_out):
                text_code = main(
                    [
                        "proposal-detail",
                        "--db",
                        str(db_path),
                        "proposal_context_timeout_001",
                    ]
                )

            self.assertEqual(text_code, 0)
            self.assertIn("gateable_check_types: deterministic_assertion, regression_replay", text_out.getvalue())
            self.assertIn("assertion_presets: replay_success_shape, replay_handoff_present", text_out.getvalue())

    def test_apply_and_skills_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--repo-patch",
                            "on",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--repo-patch",
                            "on",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )

            apply_out = io.StringIO()
            with redirect_stdout(apply_out):
                apply_code = main(["apply", "--db", str(db_path), "proposal_context_timeout_001"])
            self.assertEqual(apply_code, 0)
            self.assertIn("proposal applied: proposal_context_timeout_001", apply_out.getvalue())
            self.assertIn("skill: skill_proposal_context_timeout_001_1", apply_out.getvalue())

            skills_out = io.StringIO()
            with redirect_stdout(skills_out):
                skills_code = main(["skills", "--db", str(db_path), "--json"])
            self.assertEqual(skills_code, 0)

            payload = json.loads(skills_out.getvalue())
            self.assertEqual(len(payload["skills"]), 1)
            self.assertEqual(payload["skills"][0]["section"], "context")
            self.assertEqual(payload["skills"][0]["source_run_id"], "run_research_topic_001")
            self.assertFalse(payload["skills"][0]["human_locked"])

            lock_out = io.StringIO()
            with redirect_stdout(lock_out):
                lock_code = main(
                    [
                        "skill-lock",
                        "--db",
                        str(db_path),
                        "skill_proposal_context_timeout_001_1",
                        "--reason",
                        "manual owner review",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            self.assertEqual(lock_code, 0)
            lock_payload = json.loads(lock_out.getvalue())
            self.assertTrue(lock_payload["human_locked"])
            self.assertEqual(lock_payload["reason"], "manual owner review")
            self.assertEqual(lock_payload["actor_agent_identity_id"], "agent_researcher_001")

            unlock_out = io.StringIO()
            with redirect_stdout(unlock_out):
                unlock_code = main(
                    [
                        "skill-unlock",
                        "--db",
                        str(db_path),
                        "skill_proposal_context_timeout_001_1",
                        "--reason",
                        "review complete",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            self.assertEqual(unlock_code, 0)
            unlock_payload = json.loads(unlock_out.getvalue())
            self.assertFalse(unlock_payload["human_locked"])
            self.assertEqual(unlock_payload["reason"], "review complete")
            self.assertEqual(unlock_payload["actor_agent_identity_id"], "agent_researcher_001")

    def test_run_autonomy_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--context-mode",
                            "autonomous",
                        ]
                    ),
                    0,
                )

            autonomy_out = io.StringIO()
            with redirect_stdout(autonomy_out):
                autonomy_code = main(["run-autonomy", "--db", str(db_path), "--json"])

            self.assertEqual(autonomy_code, 0)
            payload = json.loads(autonomy_out.getvalue())
            self.assertEqual(payload["profile_id"], "profile_news_research_001")
            self.assertEqual(payload["decisions"][0]["action"], "gated")
            self.assertEqual(payload["decisions"][0]["reason"], "missing_check_run")
            self.assertEqual(
                payload["decisions"][0]["check_spec_ids"],
                ["check_proposal_context_timeout_001_1"],
            )

            detail_out = io.StringIO()
            with redirect_stdout(detail_out):
                detail_code = main(
                    [
                        "proposal-detail",
                        "--db",
                        str(db_path),
                        "proposal_context_timeout_001",
                        "--json",
                    ]
                )
            self.assertEqual(detail_code, 0)
            detail_payload = json.loads(detail_out.getvalue())
            self.assertEqual(detail_payload["gate_history"][-1]["kind"], "autonomy_decision")
            self.assertEqual(detail_payload["gate_history"][-1]["action"], "gated")
            self.assertEqual(detail_payload["gate_history"][-1]["reason"], "missing_check_run")

            autonomy_events_out = io.StringIO()
            with redirect_stdout(autonomy_events_out):
                autonomy_events_code = main(
                    [
                        "autonomy-events",
                        "--db",
                        str(db_path),
                        "--kind",
                        "autonomy_decision",
                        "--entity-type",
                        "learning_proposal",
                        "--entity-id",
                        "proposal_context_timeout_001",
                        "--json",
                    ]
                )
            self.assertEqual(autonomy_events_code, 0)
            autonomy_events_payload = json.loads(autonomy_events_out.getvalue())
            self.assertEqual(len(autonomy_events_payload["autonomy_events"]), 1)
            self.assertEqual(autonomy_events_payload["autonomy_events"][0]["kind"], "autonomy_decision")
            self.assertEqual(
                autonomy_events_payload["autonomy_events"][0]["metadata"]["reason"],
                "missing_check_run",
            )

            autonomy_events_text_out = io.StringIO()
            with redirect_stdout(autonomy_events_text_out):
                autonomy_events_text_code = main(
                    [
                        "autonomy-events",
                        "--db",
                        str(db_path),
                        "--kind",
                        "autonomy_gated",
                    ]
                )
            self.assertEqual(autonomy_events_text_code, 0)
            self.assertIn("autonomy_gated", autonomy_events_text_out.getvalue())
            self.assertIn("learning_proposal:proposal_context_timeout_001", autonomy_events_text_out.getvalue())

            detail_text_out = io.StringIO()
            with redirect_stdout(detail_text_out):
                detail_text_code = main(
                    [
                        "proposal-detail",
                        "--db",
                        str(db_path),
                        "proposal_context_timeout_001",
                    ]
                )
            self.assertEqual(detail_text_code, 0)
            detail_text = detail_text_out.getvalue()
            self.assertIn("evidence_chain:", detail_text)
            self.assertIn("autonomy: gated", detail_text)
            self.assertIn("gate_history:", detail_text)

    def test_run_autonomy_accepts_harness_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            proposal_path = Path(tmpdir) / "harness-proposal.json"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            proposal_path.write_text(json.dumps(proposal))

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(proposal_path),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--harness-mode",
                            "autonomous",
                            "--repo-patch",
                            "on",
                        ]
                    ),
                    0,
                )

            autonomy_out = io.StringIO()
            with redirect_stdout(autonomy_out):
                autonomy_code = main(
                    [
                        "run-autonomy",
                        "--db",
                        str(db_path),
                        "--harness-workspace-root",
                        str(workspace),
                        "--json",
                    ]
                )

            self.assertEqual(autonomy_code, 0)
            payload = json.loads(autonomy_out.getvalue())
            self.assertEqual(payload["decisions"][0]["action"], "gated")
            self.assertEqual(payload["decisions"][0]["reason"], "missing_check_run")
            self.assertEqual(
                payload["decisions"][0]["check_spec_ids"],
                ["check_proposal_harness_generated_check_001_1"],
            )
            self.assertEqual(
                payload["decisions"][0]["patch_transaction_ids"],
                ["patch_proposal_harness_generated_check_001_1"],
            )
            self.assertFalse((workspace / "checks/generated_timeout_check.py").exists())

    def test_harness_target_lock_cli_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            lock_out = io.StringIO()
            with redirect_stdout(lock_out):
                lock_code = main(
                    [
                        "harness-target-lock",
                        "--db",
                        str(db_path),
                        "checks/generated_timeout_check.py",
                        "--reason",
                        "manual owner review",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            list_out = io.StringIO()
            with redirect_stdout(list_out):
                list_code = main(["harness-target-locks", "--db", str(db_path), "--json"])
            unlock_out = io.StringIO()
            with redirect_stdout(unlock_out):
                unlock_code = main(
                    [
                        "harness-target-unlock",
                        "--db",
                        str(db_path),
                        "checks/generated_timeout_check.py",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )

            lock_payload = json.loads(lock_out.getvalue())
            list_payload = json.loads(list_out.getvalue())
            unlock_payload = json.loads(unlock_out.getvalue())
            self.assertEqual(lock_code, 0)
            self.assertEqual(list_code, 0)
            self.assertEqual(unlock_code, 0)
            self.assertTrue(lock_payload["human_locked"])
            self.assertEqual(lock_payload["reason"], "manual owner review")
            self.assertEqual(lock_payload["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(list_payload["harness_target_locks"][0]["target_path"], "checks/generated_timeout_check.py")
            self.assertFalse(unlock_payload["human_locked"])
            self.assertEqual(unlock_payload["actor_agent_identity_id"], "agent_researcher_001")

    def test_prepare_harness_and_list_patches_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_HARNESS_PROPOSAL),
                        ]
                    ),
                    0,
                )

            prepare_out = io.StringIO()
            with redirect_stdout(prepare_out):
                prepare_code = main(
                    [
                        "prepare-harness",
                        "--db",
                        str(db_path),
                        "proposal_harness_timeout_check_001",
                        "--json",
                    ]
                )
            self.assertEqual(prepare_code, 0)
            prepare_payload = json.loads(prepare_out.getvalue())
            self.assertEqual(prepare_payload["state"], "pending")
            self.assertEqual(
                prepare_payload["patch_transaction_ids"],
                ["patch_proposal_harness_timeout_check_001_1"],
            )

            patches_out = io.StringIO()
            with redirect_stdout(patches_out):
                patches_code = main(["harness-patches", "--db", str(db_path), "--json"])
            self.assertEqual(patches_code, 0)
            patches_payload = json.loads(patches_out.getvalue())
            self.assertEqual(patches_payload["patch_transactions"][0]["status"], "ready")
            self.assertEqual(
                patches_payload["patch_transactions"][0]["target_paths"],
                ["checks/news_research_timeout_replay.py"],
            )

    def test_apply_and_rollback_harness_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "checks/generated_timeout_check.py"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--repo-patch",
                            "on",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_GENERATED_FILE_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "prepare-harness",
                            "--db",
                            str(db_path),
                            "proposal_harness_generated_check_001",
                        ]
                    ),
                    0,
                )

            apply_out = io.StringIO()
            with redirect_stdout(apply_out):
                apply_code = main(
                    [
                        "apply-harness",
                        "--db",
                        str(db_path),
                        "patch_proposal_harness_generated_check_001_1",
                        "--workspace-root",
                        str(workspace),
                        "--json",
                    ]
                )
            self.assertEqual(apply_code, 0)
            apply_payload = json.loads(apply_out.getvalue())
            self.assertEqual(apply_payload["status"], "applied")
            self.assertTrue(target.exists())

            rollback_out = io.StringIO()
            with redirect_stdout(rollback_out):
                rollback_code = main(
                    [
                        "rollback-harness",
                        "--db",
                        str(db_path),
                        "patch_proposal_harness_generated_check_001_1",
                        "--workspace-root",
                        str(workspace),
                        "--json",
                    ]
                )
            self.assertEqual(rollback_code, 0)
            rollback_payload = json.loads(rollback_out.getvalue())
            self.assertEqual(rollback_payload["status"], "rolled_back")
            self.assertFalse(target.exists())

    def test_apply_and_rollback_unified_diff_harness_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            target = workspace / "checks/generated_timeout_check.py"
            target.parent.mkdir(parents=True)
            target.write_text("old\n")
            diff_path = Path(tmpdir) / "patch.diff"
            diff_path.write_text(
                "--- a/checks/generated_timeout_check.py\n"
                "+++ b/checks/generated_timeout_check.py\n"
                "@@ -1 +1,2 @@\n"
                "-old\n"
                "+new\n"
                "+added\n"
            )

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(main(["policy-set", "--db", str(db_path), "--repo-patch", "on"]), 0)

            blob_out = io.StringIO()
            with redirect_stdout(blob_out):
                blob_code = main(
                    [
                        "blob-put",
                        "--db",
                        str(db_path),
                        str(diff_path),
                        "--profile-id",
                        "profile_news_research_001",
                        "--kind",
                        "patch_diff",
                        "--media-type",
                        "text/x-diff",
                        "--json",
                    ]
                )
            self.assertEqual(blob_code, 0)
            blob_payload = json.loads(blob_out.getvalue())

            proposal = json.loads(VALID_HARNESS_PROPOSAL.read_text())
            proposal["id"] = "proposal_harness_cli_unified_diff_001"
            proposal["producer"]["session_id"] = "operator_session_harness_cli_unified_diff_001"
            proposal["proposed_changes"][0]["patch_kind"] = "unified_diff"
            proposal["proposed_changes"][0]["diff_ref"] = blob_payload["blob_id"]
            proposal["proposed_changes"][0]["target_paths"] = ["checks/generated_timeout_check.py"]
            proposal["proposed_changes"][0]["command_plan"] = []
            proposal_path = Path(tmpdir) / "unified-proposal.json"
            proposal_path.write_text(json.dumps(proposal))

            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(proposal_path),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "prepare-harness",
                            "--db",
                            str(db_path),
                            "proposal_harness_cli_unified_diff_001",
                        ]
                    ),
                    0,
                )

            apply_out = io.StringIO()
            with redirect_stdout(apply_out):
                apply_code = main(
                    [
                        "apply-harness",
                        "--db",
                        str(db_path),
                        "patch_proposal_harness_cli_unified_diff_001_1",
                        "--workspace-root",
                        str(workspace),
                        "--json",
                    ]
                )
            self.assertEqual(apply_code, 0)
            self.assertEqual(json.loads(apply_out.getvalue())["status"], "applied")
            self.assertEqual(target.read_text(), "new\nadded\n")

            rollback_out = io.StringIO()
            with redirect_stdout(rollback_out):
                rollback_code = main(
                    [
                        "rollback-harness",
                        "--db",
                        str(db_path),
                        "patch_proposal_harness_cli_unified_diff_001_1",
                        "--workspace-root",
                        str(workspace),
                        "--json",
                    ]
                )
            self.assertEqual(rollback_code, 0)
            self.assertEqual(json.loads(rollback_out.getvalue())["status"], "rolled_back")
            self.assertEqual(target.read_text(), "old\n")

    def test_context_and_export_skillbook_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["apply", "--db", str(db_path), "proposal_context_timeout_001"]), 0)

                rule_proposal = json.loads(VALID_PROPOSAL.read_text())
                rule_proposal["id"] = "proposal_context_rule_001"
                rule_proposal["producer"]["session_id"] = "proposal_context_rule_001"
                rule_proposal["proposed_changes"] = [
                    {
                        "type": "context_delivery_rule",
                        "operation": "create",
                        "target": {
                            "entity_type": "agent_identity",
                            "entity_id": "agent_researcher_001",
                        },
                        "rule": {
                            "id": "context_rule_researcher_timeout",
                            "mode": "prompt",
                            "include_keywords": ["timeout"],
                        },
                    }
                ]
                rule_path = Path(tmpdir) / "context-rule-proposal.json"
                rule_path.write_text(json.dumps(rule_proposal))
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(rule_path),
                        ]
                    ),
                    0,
                )
                self.assertEqual(main(["apply", "--db", str(db_path), "proposal_context_rule_001"]), 0)

            context_out = io.StringIO()
            with redirect_stdout(context_out):
                context_code = main(
                    [
                        "context",
                        "--db",
                        str(db_path),
                        "--target-type",
                        "agent_identity",
                        "--target-id",
                        "agent_researcher_001",
                    ]
                )
            self.assertEqual(context_code, 0)
            self.assertIn("## context", context_out.getvalue())
            self.assertIn("skill_proposal_context_timeout_001_1", context_out.getvalue())
            self.assertIn("context_rule_researcher_timeout", context_out.getvalue())

            rules_out = io.StringIO()
            with redirect_stdout(rules_out):
                rules_code = main(["context-rules", "--db", str(db_path), "--json"])
            self.assertEqual(rules_code, 0)
            rules_payload = json.loads(rules_out.getvalue())
            self.assertEqual(
                rules_payload["context_delivery_rules"][0]["id"],
                "context_rule_researcher_timeout",
            )

            rule_revisions_out = io.StringIO()
            with redirect_stdout(rule_revisions_out):
                rule_revisions_code = main(
                    [
                        "context-rule-revisions",
                        "--db",
                        str(db_path),
                        "--rule-id",
                        "context_rule_researcher_timeout",
                        "--json",
                    ]
                )
            self.assertEqual(rule_revisions_code, 0)
            rule_revisions_payload = json.loads(rule_revisions_out.getvalue())
            self.assertEqual(
                rule_revisions_payload["context_delivery_rule_revisions"][0]["operation"],
                "create",
            )

            rule_lock_out = io.StringIO()
            with redirect_stdout(rule_lock_out):
                rule_lock_code = main(
                    [
                        "context-rule-lock",
                        "--db",
                        str(db_path),
                        "context_rule_researcher_timeout",
                        "--reason",
                        "preserve handoff policy",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            rule_unlock_out = io.StringIO()
            with redirect_stdout(rule_unlock_out):
                rule_unlock_code = main(
                    [
                        "context-rule-unlock",
                        "--db",
                        str(db_path),
                        "context_rule_researcher_timeout",
                        "--reason",
                        "policy update approved",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            rule_lock_payload = json.loads(rule_lock_out.getvalue())
            rule_unlock_payload = json.loads(rule_unlock_out.getvalue())
            self.assertEqual(rule_lock_code, 0)
            self.assertEqual(rule_unlock_code, 0)
            self.assertTrue(rule_lock_payload["human_locked"])
            self.assertEqual(rule_lock_payload["reason"], "preserve handoff policy")
            self.assertEqual(rule_lock_payload["actor_agent_identity_id"], "agent_researcher_001")
            self.assertFalse(rule_unlock_payload["human_locked"])
            self.assertEqual(rule_unlock_payload["reason"], "policy update approved")
            self.assertEqual(rule_unlock_payload["actor_agent_identity_id"], "agent_researcher_001")

            rule_rollback_out = io.StringIO()
            with redirect_stdout(rule_rollback_out):
                rule_rollback_code = main(
                    [
                        "context-rule-rollback",
                        "--db",
                        str(db_path),
                        rule_revisions_payload["context_delivery_rule_revisions"][0]["id"],
                        "--json",
                    ]
                )
            self.assertEqual(rule_rollback_code, 0)
            self.assertEqual(json.loads(rule_rollback_out.getvalue())["status"], "rolled_back")

            revisions_out = io.StringIO()
            with redirect_stdout(revisions_out):
                revisions_code = main(
                    [
                        "skill-revisions",
                        "--db",
                        str(db_path),
                        "--skill-id",
                        "skill_proposal_context_timeout_001_1",
                        "--json",
                    ]
                )
            self.assertEqual(revisions_code, 0)
            revisions_payload = json.loads(revisions_out.getvalue())
            self.assertEqual(revisions_payload["skill_revisions"][0]["operation"], "create")

            export_out = io.StringIO()
            with redirect_stdout(export_out):
                export_code = main(["export-skillbook", "--db", str(db_path), "--format", "json"])
            self.assertEqual(export_code, 0)
            payload = json.loads(export_out.getvalue())
            self.assertEqual(payload["schema_version"], "2")
            self.assertIn("skill_proposal_context_timeout_001_1", payload["skills"])

    def test_context_and_export_skillbook_profile_scope(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_context_timeout_001")
            ingest_source_payload(
                db_path=db_path,
                fixture=second_profile_payload(),
                source_label="second-profile",
            )
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=second_profile_proposal(),
                schema_path=SCHEMA,
            )
            apply_context_proposal(db_path=db_path, proposal_id="proposal_second_context")

            context_out = io.StringIO()
            with redirect_stdout(context_out):
                context_code = main(
                    [
                        "context",
                        "--db",
                        str(db_path),
                        "--profile-id",
                        "profile_second",
                    ]
                )
            self.assertEqual(context_code, 0)
            self.assertIn("billing-specific", context_out.getvalue())
            self.assertNotIn("Retry transient fetch failures once before handoff", context_out.getvalue())

            export_out = io.StringIO()
            with redirect_stdout(export_out):
                export_code = main(
                    [
                        "export-skillbook",
                        "--db",
                        str(db_path),
                        "--format",
                        "json",
                        "--profile-id",
                        "profile_second",
                    ]
                )
            self.assertEqual(export_code, 0)
            payload = json.loads(export_out.getvalue())
            self.assertEqual(list(payload["skills"]), ["skill_proposal_second_context_1"])

    def test_ace_diff_proposals_cli_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            before = {
                "schema_version": "2",
                "skills": {},
                "sections": {},
                "next_id": 0,
                "similarity_decisions": {},
            }
            after = copy.deepcopy(before)
            after["skills"]["context-00001"] = {
                "id": "context-00001",
                "section": "context",
                "keywords": ["fetch", "retry"],
                "issue": "Fetch timeouts are treated as final failures.",
                "insight": "Retry transient fetch timeouts before handoff.",
                "occurrences": [],
                "active": True,
            }
            after["sections"]["context"] = ["context-00001"]
            before_path = Path(tmpdir) / "before.json"
            after_path = Path(tmpdir) / "after.json"
            before_path.write_text(json.dumps(before))
            after_path.write_text(json.dumps(after))

            diff_out = io.StringIO()
            with redirect_stdout(diff_out):
                diff_code = main(
                    [
                        "ace-diff-proposals",
                        "--db",
                        str(db_path),
                        "--before",
                        str(before_path),
                        "--after",
                        str(after_path),
                        "--evidence-span-id",
                        "span_fetch_timeout_001",
                        "--persist",
                        "--json",
                    ]
                )

            self.assertEqual(diff_code, 0)
            payload = json.loads(diff_out.getvalue())
            self.assertTrue(payload["persisted"])
            self.assertEqual(len(payload["proposal_ids"]), 1)
            self.assertEqual(payload["proposals"][0]["producer"]["kind"], "native_ace")
            self.assertEqual(payload["proposals"][0]["proposed_changes"][1]["type"], "check_spec")

    def test_ace_native_run_cli_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "ace-native"
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
                        "print('fake native ace mutation complete')",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            command = " ".join(shlex.quote(part) for part in [sys.executable, str(command_path)])
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "ace-native-run",
                        "--db",
                        str(db_path),
                        "--command",
                        command,
                        "--evidence-span-id",
                        "span_fetch_timeout_001",
                        "--output-dir",
                        str(output_dir),
                        "--persist",
                        "--provider-backed",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["returncode"], 0)
            self.assertTrue(Path(payload["before_path"]).exists())
            self.assertTrue(Path(payload["after_path"]).exists())
            self.assertTrue(Path(payload["handoff_path"]).exists())
            self.assertTrue(payload["prepared"])
            self.assertFalse(payload["prepare_only"])
            self.assertTrue(payload["provider_backed"])
            self.assertTrue(payload["external_model_invoked"])
            self.assertEqual(payload["environment"]["KYOKO_ACE_AFTER_PATH"], payload["after_path"])
            self.assertIn("fake native ace mutation complete", payload["stdout_tail"])
            self.assertTrue(payload["diff"]["persisted"])
            self.assertEqual(len(payload["diff"]["proposal_ids"]), 1)
            self.assertEqual(payload["diff"]["proposals"][0]["producer"]["kind"], "native_ace")

    def test_ace_native_run_prepare_only_cli_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "ace-native-prepare"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "ace-native-run",
                        "--db",
                        str(db_path),
                        "--command",
                        "missing-ace-command --after {after_path} --db {db_path}",
                        "--output-dir",
                        str(output_dir),
                        "--prepare-only",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["prepare_only"])
            self.assertFalse(payload["external_command_invoked"])
            self.assertFalse(payload["provider_backed"])
            self.assertFalse(payload["external_model_invoked"])
            self.assertFalse(payload["canonical_mutation"])
            self.assertTrue(Path(payload["before_path"]).exists())
            self.assertTrue(Path(payload["after_path"]).exists())
            self.assertTrue(Path(payload["handoff_path"]).exists())
            self.assertEqual(payload["command"][0], "missing-ace-command")
            self.assertEqual(payload["environment"]["KYOKO_ACE_DB_PATH"], str(db_path.resolve()))
            self.assertIsNone(payload["diff"])

            err = io.StringIO()
            with redirect_stderr(err):
                persist_code = main(
                    [
                        "ace-native-run",
                        "--db",
                        str(db_path),
                        "--command",
                        "missing-ace-command",
                        "--prepare-only",
                        "--persist",
                    ]
                )
            self.assertEqual(persist_code, 1)
            self.assertIn("ace_prepare_only_cannot_persist", err.getvalue())

    def test_ace_native_smoke_cli_flow_when_skillbook_v2_is_available(self) -> None:
        import_output = io.StringIO()
        try:
            with redirect_stdout(import_output), redirect_stderr(import_output):
                skillbook_module = importlib.import_module("ace.core.skillbook")
        except ImportError:
            self.skipTest("ace package with Skillbook v2 API is not installed")
        if not hasattr(skillbook_module, "Skillbook"):
            self.skipTest("installed ace package does not expose the Skillbook v2 API")

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "ace-native-smoke"
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(
                    [
                        "ace-native-smoke",
                        "--db",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                        "--persist",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["passed"])
            self.assertTrue(payload["installed_ace_package_invoked"])
            self.assertFalse(payload["provider_backed"])
            self.assertEqual(payload["native_run"]["returncode"], 0)
            self.assertTrue(Path(payload["native_run"]["after_path"]).exists())
            self.assertEqual(len(payload["native_run"]["diff"]["proposal_ids"]), 1)
            self.assertEqual(
                payload["native_run"]["diff"]["proposals"][0]["producer"]["name"],
                "legacy_ace_offline_adapter",
            )

    def test_improve_cli_defaults_to_registered_replay_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            replay_dir = Path(tmpdir) / "replay"
            command = " ".join(shlex.quote(part) for part in [sys.executable, str(REPLAY_COMMAND)])

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "replay-adapter-register",
                            "--db",
                            str(db_path),
                            "fixture_replay",
                            "--name",
                            "Fixture replay",
                            "--command",
                            command,
                            "--output-dir",
                            str(replay_dir),
                            "--side-effect-mode",
                            "network_mocked",
                            "--json",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--context-mode",
                            "autonomous",
                            "--json",
                        ]
                    ),
                    0,
                )

            improve_out = io.StringIO()
            with redirect_stdout(improve_out):
                improve_code = main(
                    [
                        "improve",
                        "--db",
                        str(db_path),
                        "--proposal-id",
                        "proposal_context_timeout_001",
                        "--json",
                    ]
                )

            self.assertEqual(improve_code, 0)
            payload = json.loads(improve_out.getvalue())
            self.assertEqual(payload["proposal_id"], "proposal_context_timeout_001")
            self.assertEqual(payload["check_spec_ids"], ["check_proposal_context_timeout_001_1"])
            self.assertEqual(payload["replay_runs"][0]["adapter_id"], "fixture_replay")
            self.assertEqual(payload["replay_runs"][0]["check_run"]["status"], "passed")
            self.assertEqual(payload["autonomy"]["decisions"][0]["action"], "applied")

    def test_improve_cli_applies_harness_patch_with_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            replay_dir = Path(tmpdir) / "replay"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            proposal_path = Path(tmpdir) / "harness-proposal.json"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            proposal_path.write_text(json.dumps(proposal), encoding="utf-8")
            command = " ".join(shlex.quote(part) for part in [sys.executable, str(REPLAY_COMMAND)])

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(proposal_path),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "replay-adapter-register",
                            "--db",
                            str(db_path),
                            "fixture_replay",
                            "--name",
                            "Fixture replay",
                            "--command",
                            command,
                            "--output-dir",
                            str(replay_dir),
                            "--side-effect-mode",
                            "network_mocked",
                            "--json",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "policy-set",
                            "--db",
                            str(db_path),
                            "--harness-mode",
                            "autonomous",
                            "--repo-patch",
                            "on",
                            "--json",
                        ]
                    ),
                    0,
                )

            improve_out = io.StringIO()
            with redirect_stdout(improve_out):
                improve_code = main(
                    [
                        "improve",
                        "--db",
                        str(db_path),
                        "--proposal-id",
                        "proposal_harness_generated_check_001",
                        "--replay-adapter",
                        "fixture_replay",
                        "--harness-workspace-root",
                        str(workspace),
                        "--json",
                    ]
                )

            self.assertEqual(improve_code, 0)
            payload = json.loads(improve_out.getvalue())
            target = workspace / "checks/generated_timeout_check.py"
            self.assertEqual(
                payload["generated_check_spec_ids"],
                ["check_proposal_harness_generated_check_001_1"],
            )
            self.assertEqual(payload["replay_runs"][0]["check_run"]["status"], "passed")
            self.assertEqual(payload["autonomy"]["decisions"][0]["action"], "applied")
            self.assertTrue(target.exists())

    def test_improve_cli_can_import_discovered_source_before_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home = tmp_path / "home"
            _write_failed_openclaw_session(home)

            improve_out = io.StringIO()
            with redirect_stdout(improve_out):
                improve_code = main(
                    [
                        "improve",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--source-candidate-id",
                        "openclaw_main",
                        "--source-home",
                        str(home),
                        "--source-import-output-dir",
                        str(tmp_path / "normalized"),
                        "--no-autonomy",
                        "--json",
                    ]
                )

            payload = json.loads(improve_out.getvalue())
            self.assertEqual(improve_code, 0)
            self.assertEqual(payload["source_import"]["candidate"]["id"], "openclaw_main")
            self.assertEqual(payload["profile_id"], "profile_openclaw_main")
            self.assertEqual(payload["proposal_id"], "proposal_mock_span_openclaw_error_session_failure_1")
            self.assertEqual(
                payload["generated_check_spec_ids"],
                ["check_proposal_mock_span_openclaw_error_session_failure_1_1"],
            )

    def test_check_and_replay_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )

            generate_out = io.StringIO()
            with redirect_stdout(generate_out):
                generate_code = main(
                    [
                        "generate-checks",
                        "--db",
                        str(db_path),
                        "proposal_context_timeout_001",
                        "--json",
                    ]
                )
            self.assertEqual(generate_code, 0)
            generate_payload = json.loads(generate_out.getvalue())
            self.assertEqual(
                generate_payload["check_spec_ids"],
                ["check_proposal_context_timeout_001_1"],
            )

            replay_out = io.StringIO()
            with redirect_stdout(replay_out):
                replay_code = main(
                    [
                        "replay",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--json",
                    ]
                )
            self.assertEqual(replay_code, 0)
            replay_payload = json.loads(replay_out.getvalue())
            self.assertEqual(replay_payload["status"], "passed")
            self.assertEqual(replay_payload["source_run_id"], "run_research_topic_001")

            complete_out = io.StringIO()
            with redirect_stdout(complete_out):
                complete_code = main(
                    [
                        "complete-replay",
                        "--db",
                        str(db_path),
                        replay_payload["replay_run_id"],
                        str(REPLAY_SUCCESS),
                        "--json",
                    ]
                )
            self.assertEqual(complete_code, 0)
            complete_payload = json.loads(complete_out.getvalue())
            self.assertEqual(complete_payload["output_run_id"], "run_research_topic_replay_001")

            check_out = io.StringIO()
            with redirect_stdout(check_out):
                check_code = main(
                    [
                        "run-check",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--replay-run-id",
                        replay_payload["replay_run_id"],
                        "--json",
                    ]
                )
            self.assertEqual(check_code, 0)
            check_payload = json.loads(check_out.getvalue())
            self.assertEqual(check_payload["status"], "passed")
            self.assertEqual(check_payload["promoted_trust_level"], "L2_regression")
            self.assertEqual(check_payload["result"]["comparison"], "fail_before_pass_after")

            checks_out = io.StringIO()
            with redirect_stdout(checks_out):
                checks_code = main(["checks", "--db", str(db_path), "--json"])
            self.assertEqual(checks_code, 0)
            checks_payload = json.loads(checks_out.getvalue())
            self.assertEqual(len(checks_payload["check_specs"]), 1)
            self.assertEqual(len(checks_payload["check_runs"]), 1)
            self.assertEqual(len(checks_payload["replay_runs"]), 1)
            self.assertFalse(checks_payload["check_specs"][0]["human_locked"])

            preset_out = io.StringIO()
            with redirect_stdout(preset_out):
                preset_code = main(["check-assertion-presets", "--json"])
            self.assertEqual(preset_code, 0)
            preset_payload = json.loads(preset_out.getvalue())
            self.assertEqual(
                [preset["name"] for preset in preset_payload["assertion_presets"]],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertEqual(
                preset_payload["assertion_presets"][0]["assertions"],
                [
                    "replay_run_status_equals",
                    "replay_no_failed_spans",
                    "replay_span_count_at_least",
                ],
            )

            capabilities_out = io.StringIO()
            with redirect_stdout(capabilities_out):
                capabilities_code = main(["check-capabilities", "--json"])
            self.assertEqual(capabilities_code, 0)
            capabilities_payload = json.loads(capabilities_out.getvalue())
            self.assertEqual(
                capabilities_payload["gateable_check_types"],
                ["deterministic_assertion", "regression_replay"],
            )
            self.assertFalse(capabilities_payload["judge"]["invokes_model"])
            self.assertTrue(capabilities_payload["judge"]["external_command_supported"])
            self.assertEqual(capabilities_payload["judge"]["autonomy_gate"], "unsupported")
            self.assertIn("deterministic_assertion_gap", capabilities_payload["judge"]["recommended_use"])
            self.assertEqual(
                capabilities_payload["replay"]["unsafe_side_effect_modes"],
                ["live_network", "unknown"],
            )

            check_lock_out = io.StringIO()
            with redirect_stdout(check_lock_out):
                check_lock_code = main(
                    [
                        "check-lock",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--reason",
                        "manual review",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            self.assertEqual(check_lock_code, 0)
            check_lock_payload = json.loads(check_lock_out.getvalue())
            self.assertTrue(check_lock_payload["human_locked"])
            self.assertEqual(check_lock_payload["actor_agent_identity_id"], "agent_researcher_001")

            check_locks_out = io.StringIO()
            with redirect_stdout(check_locks_out):
                check_locks_code = main(["check-locks", "--db", str(db_path), "--json"])
            self.assertEqual(check_locks_code, 0)
            check_locks_payload = json.loads(check_locks_out.getvalue())
            self.assertEqual(
                check_locks_payload["check_locks"][0]["check_spec_id"],
                "check_proposal_context_timeout_001_1",
            )

            locked_approve_err = io.StringIO()
            with redirect_stderr(locked_approve_err):
                locked_approve_code = main(
                    [
                        "check-approve",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--reason",
                        "reviewed gate evidence",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            self.assertEqual(locked_approve_code, 1)
            self.assertIn("human_locked_check_spec", locked_approve_err.getvalue())

            check_detail_out = io.StringIO()
            with redirect_stdout(check_detail_out):
                check_detail_code = main(
                    [
                        "check-detail",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--json",
                    ]
                )
            self.assertEqual(check_detail_code, 0)
            check_detail_payload = json.loads(check_detail_out.getvalue())
            self.assertEqual(check_detail_payload["summary"]["latest_status"], "passed")
            self.assertEqual(check_detail_payload["summary"]["latest_comparison"], "fail_before_pass_after")
            self.assertTrue(check_detail_payload["check_spec"]["human_locked"])
            self.assertEqual(len(check_detail_payload["summary"]["latest_assertions"]), 3)
            self.assertEqual(check_detail_payload["summary"]["latest_assertions"][1]["actual"], 1)

            check_unlock_out = io.StringIO()
            with redirect_stdout(check_unlock_out):
                check_unlock_code = main(
                    [
                        "check-unlock",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            self.assertEqual(check_unlock_code, 0)
            check_unlock_payload = json.loads(check_unlock_out.getvalue())
            self.assertFalse(check_unlock_payload["human_locked"])
            self.assertEqual(check_unlock_payload["actor_agent_identity_id"], "agent_researcher_001")

            check_approve_out = io.StringIO()
            with redirect_stdout(check_approve_out):
                check_approve_code = main(
                    [
                        "check-approve",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--reason",
                        "reviewed gate evidence",
                        "--actor-agent-identity-id",
                        "agent_researcher_001",
                        "--json",
                    ]
                )
            self.assertEqual(check_approve_code, 0)
            check_approve_payload = json.loads(check_approve_out.getvalue())
            self.assertEqual(check_approve_payload["previous_trust_level"], "L2_regression")
            self.assertEqual(check_approve_payload["trust_level"], "L3_human_approved")
            self.assertEqual(check_approve_payload["actor_agent_identity_id"], "agent_researcher_001")

            check_detail_text_out = io.StringIO()
            with redirect_stdout(check_detail_text_out):
                check_detail_text_code = main(
                    [
                        "check-detail",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                    ]
                )
            self.assertEqual(check_detail_text_code, 0)
            self.assertIn(
                "pass replay_target_field_equals: field_equals",
                check_detail_text_out.getvalue(),
            )

            replay_detail_out = io.StringIO()
            with redirect_stdout(replay_detail_out):
                replay_detail_code = main(
                    [
                        "replay-detail",
                        "--db",
                        str(db_path),
                        replay_payload["replay_run_id"],
                        "--json",
                    ]
                )
            self.assertEqual(replay_detail_code, 0)
            replay_detail_payload = json.loads(replay_detail_out.getvalue())
            self.assertEqual(replay_detail_payload["source_run"]["id"], "run_research_topic_001")
            self.assertEqual(replay_detail_payload["output_run"]["id"], "run_research_topic_replay_001")

    def test_judge_command_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "judge-command"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "generate-checks",
                            "--db",
                            str(db_path),
                            "proposal_context_timeout_001",
                        ]
                    ),
                    0,
                )
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "UPDATE check_specs SET check_type = ?, definition_json = ? WHERE id = ?",
                    (
                        "judge",
                        json.dumps(
                            {
                                "rubric": "Recovered source evidence is complete and dated.",
                                "evidence_refs": [
                                    {
                                        "entity_type": "span",
                                        "entity_id": "span_fetch_timeout_001",
                                    }
                                ],
                            },
                            sort_keys=True,
                        ),
                        "check_proposal_context_timeout_001_1",
                    ),
                )

            judge_out = io.StringIO()
            with redirect_stdout(judge_out):
                code = main(
                    [
                        "judge-command",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(JUDGE_COMMAND))}",
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            payload = json.loads(judge_out.getvalue())
            self.assertEqual(payload["check_run"]["status"], "passed")
            self.assertEqual(payload["check_run"]["result"]["judge_backend"], "external_command")
            self.assertFalse(payload["check_run"]["result"]["gateable"])
            self.assertIsNone(payload["check_run"]["promoted_trust_level"])
            self.assertEqual(payload["judgment"]["judge"], "fixture_external_judge")
            self.assertTrue(Path(payload["request_path"]).exists())
            self.assertTrue(Path(payload["result_path"]).exists())
            self.assertTrue(Path(payload["raw_output_path"]).exists())

    def test_judge_smoke_prepare_and_fixture_command_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prepare_dir = root / "judge-smoke-prepare"
            run_dir = root / "judge-smoke-run"

            prepare_out = io.StringIO()
            with redirect_stdout(prepare_out):
                prepare_code = main(
                    [
                        "judge-smoke",
                        "--prepare-only",
                        "--output-dir",
                        str(prepare_dir),
                        "--json",
                    ]
                )
            self.assertEqual(prepare_code, 0)
            prepare_payload = json.loads(prepare_out.getvalue())
            self.assertTrue(prepare_payload["passed"])
            self.assertTrue(prepare_payload["prepare_only"])
            self.assertFalse(prepare_payload["external_command_invoked"])
            self.assertEqual(prepare_payload["check_status"], "prepared")
            self.assertTrue(Path(prepare_payload["request_path"]).exists())
            self.assertTrue(Path(prepare_payload["handoff_path"]).exists())

            command = " ".join(shlex.quote(part) for part in [sys.executable, str(JUDGE_COMMAND)])
            run_out = io.StringIO()
            with redirect_stdout(run_out):
                run_code = main(
                    [
                        "judge-smoke",
                        "--command",
                        command,
                        "--output-dir",
                        str(run_dir),
                        "--json",
                    ]
                )
            self.assertEqual(run_code, 0)
            run_payload = json.loads(run_out.getvalue())
            self.assertTrue(run_payload["passed"])
            self.assertFalse(run_payload["prepare_only"])
            self.assertTrue(run_payload["external_command_invoked"])
            self.assertFalse(run_payload["provider_backed"])
            self.assertEqual(run_payload["check_status"], "passed")
            self.assertEqual(run_payload["judgment"]["judge"], "fixture_external_judge")
            self.assertIsNone(run_payload["promoted_trust_level"])
            self.assertTrue(Path(run_payload["result_path"]).exists())
            self.assertTrue(Path(run_payload["raw_output_path"]).exists())

    def test_replay_command_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "replay-command"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "generate-checks",
                            "--db",
                            str(db_path),
                            "proposal_context_timeout_001",
                        ]
                    ),
                    0,
                )

            replay_command_out = io.StringIO()
            with redirect_stdout(replay_command_out):
                replay_command_code = main(
                    [
                        "replay-command",
                        "--db",
                        str(db_path),
                        "check_proposal_context_timeout_001_1",
                        "--command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(REPLAY_COMMAND))}",
                        "--output-dir",
                        str(output_dir),
                        "--run-check",
                        "--json",
                    ]
                )

            self.assertEqual(replay_command_code, 0)
            payload = json.loads(replay_command_out.getvalue())
            self.assertEqual(payload["status"], "passed")
            self.assertEqual(payload["output_run_id"], "run_research_topic_replay_001")
            self.assertEqual(payload["check_run"]["status"], "passed")
            self.assertEqual(payload["check_run"]["promoted_trust_level"], "L2_regression")
            self.assertTrue(Path(payload["request_path"]).exists())
            self.assertTrue(Path(payload["result_path"]).exists())

            detail_out = io.StringIO()
            with redirect_stdout(detail_out):
                detail_code = main(
                    [
                        "replay-detail",
                        "--db",
                        str(db_path),
                        payload["replay_run_id"],
                        "--json",
                    ]
                )
            self.assertEqual(detail_code, 0)
            detail_payload = json.loads(detail_out.getvalue())
            artifacts = {artifact["kind"]: artifact for artifact in detail_payload["artifacts"]}
            self.assertEqual(detail_payload["summary"]["artifacts"], 3)
            self.assertIn("BEGIN_KYOKO_REPLAY_RESULT_JSON", artifacts["replay_command_output"]["preview"])

            detail_text_out = io.StringIO()
            with redirect_stdout(detail_text_out):
                detail_text_code = main(
                    [
                        "replay-detail",
                        "--db",
                        str(db_path),
                        payload["replay_run_id"],
                    ]
                )
            self.assertEqual(detail_text_code, 0)
            self.assertIn("replay_command_output", detail_text_out.getvalue())

    def test_replay_adapter_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "replay-adapter"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "generate-checks",
                            "--db",
                            str(db_path),
                            "proposal_context_timeout_001",
                        ]
                    ),
                    0,
                )

            register_out = io.StringIO()
            with redirect_stdout(register_out):
                register_code = main(
                    [
                        "replay-adapter-register",
                        "--db",
                        str(db_path),
                        "fixture_replay",
                        "--name",
                        "Fixture replay",
                        "--command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(REPLAY_COMMAND))}",
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )
            self.assertEqual(register_code, 0)
            register_payload = json.loads(register_out.getvalue())
            self.assertEqual(register_payload["adapter_id"], "fixture_replay")

            adapters_out = io.StringIO()
            with redirect_stdout(adapters_out):
                adapters_code = main(["replay-adapters", "--db", str(db_path), "--json"])
            self.assertEqual(adapters_code, 0)
            adapters_payload = json.loads(adapters_out.getvalue())
            self.assertEqual(adapters_payload["replay_adapters"][0]["id"], "fixture_replay")

            run_out = io.StringIO()
            with redirect_stdout(run_out):
                run_code = main(
                    [
                        "replay-adapter-run",
                        "--db",
                        str(db_path),
                        "fixture_replay",
                        "check_proposal_context_timeout_001_1",
                        "--run-check",
                        "--json",
                    ]
                )
            self.assertEqual(run_code, 0)
            run_payload = json.loads(run_out.getvalue())
            self.assertEqual(run_payload["adapter_id"], "fixture_replay")
            self.assertEqual(run_payload["status"], "passed")
            self.assertEqual(run_payload["check_run"]["promoted_trust_level"], "L2_regression")

    def test_replay_server_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "generate-checks",
                            "--db",
                            str(db_path),
                            "proposal_context_timeout_001",
                        ]
                    ),
                    0,
                )

            with RunningReplayServer() as server:
                health_out = io.StringIO()
                with redirect_stdout(health_out):
                    health_code = main(["replay-server-health", server.base_url, "--json"])
                self.assertEqual(health_code, 0)
                health_payload = json.loads(health_out.getvalue())
                self.assertTrue(health_payload["ok"])

                run_out = io.StringIO()
                with redirect_stdout(run_out):
                    run_code = main(
                        [
                            "replay-server-run",
                            "--db",
                            str(db_path),
                            server.base_url,
                            "check_proposal_context_timeout_001_1",
                            "--run-check",
                            "--json",
                        ]
                    )
                self.assertEqual(run_code, 0)
                run_payload = json.loads(run_out.getvalue())

            self.assertEqual(run_payload["server_url"], server.base_url)
            self.assertEqual(run_payload["output_run_id"], "run_research_topic_replay_001")
            self.assertEqual(run_payload["check_run"]["status"], "passed")
            self.assertEqual(run_payload["check_run"]["promoted_trust_level"], "L2_regression")

    def test_managed_replay_adapter_cli_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "managed-adapter"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "generate-checks",
                            "--db",
                            str(db_path),
                            "proposal_context_timeout_001",
                        ]
                    ),
                    0,
                )

            register_out = io.StringIO()
            with redirect_stdout(register_out):
                register_code = main(
                    [
                        "replay-adapter-register",
                        "--db",
                        str(db_path),
                        "managed_http_replay",
                        "--name",
                        "Managed HTTP replay",
                        "--command",
                        shlex.join(_fixture_replay_server_command(port)),
                        "--server-url",
                        server_url,
                        "--output-dir",
                        str(output_dir),
                        "--startup-timeout",
                        "5",
                        "--json",
                    ]
                )
            self.assertEqual(register_code, 0)
            register_payload = json.loads(register_out.getvalue())
            self.assertEqual(register_payload["kind"], "managed_http_server")

            run_out = io.StringIO()
            with redirect_stdout(run_out):
                run_code = main(
                    [
                        "replay-adapter-run",
                        "--db",
                        str(db_path),
                        "managed_http_replay",
                        "check_proposal_context_timeout_001_1",
                        "--run-check",
                        "--json",
                    ]
                )
            self.assertEqual(run_code, 0)
            run_payload = json.loads(run_out.getvalue())
            self.assertEqual(run_payload["server_url"], server_url)
            self.assertEqual(run_payload["status"], "passed")
            self.assertEqual(run_payload["check_run"]["promoted_trust_level"], "L2_regression")
            self.assertTrue(Path(run_payload["stdout_path"]).exists())
            self.assertTrue(Path(run_payload["stderr_path"]).exists())

    def test_replay_server_process_cli_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "server-process"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)
                self.assertEqual(
                    main(
                        [
                            "propose",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            str(VALID_PROPOSAL),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "generate-checks",
                            "--db",
                            str(db_path),
                            "proposal_context_timeout_001",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "replay-adapter-register",
                            "--db",
                            str(db_path),
                            "persistent_http_replay",
                            "--name",
                            "Persistent HTTP replay",
                            "--command",
                            shlex.join(_fixture_replay_server_command(port)),
                            "--server-url",
                            server_url,
                            "--output-dir",
                            str(output_dir),
                            "--startup-timeout",
                            "5",
                        ]
                    ),
                    0,
                )

            start_out = io.StringIO()
            stop_payload = None
            try:
                with redirect_stdout(start_out):
                    start_code = main(
                        [
                            "replay-server-start",
                            "--db",
                            str(db_path),
                            "persistent_http_replay",
                            "--json",
                        ]
                    )
                self.assertEqual(start_code, 0)
                start_payload = json.loads(start_out.getvalue())
                self.assertTrue(start_payload["running"])
                self.assertTrue(start_payload["healthy"])

                status_out = io.StringIO()
                with redirect_stdout(status_out):
                    status_code = main(
                        [
                            "replay-server-status",
                            "--db",
                            str(db_path),
                            "persistent_http_replay",
                            "--json",
                        ]
                    )
                self.assertEqual(status_code, 0)
                status_payload = json.loads(status_out.getvalue())
                self.assertEqual(status_payload["pid"], start_payload["pid"])
                self.assertTrue(status_payload["healthy"])

                logs_out = io.StringIO()
                with redirect_stdout(logs_out):
                    logs_code = main(
                        [
                            "replay-server-logs",
                            "--db",
                            str(db_path),
                            "persistent_http_replay",
                            "--max-bytes",
                            "2000",
                            "--json",
                        ]
                    )
                self.assertEqual(logs_code, 0)
                logs_payload = json.loads(logs_out.getvalue())
                self.assertEqual(logs_payload["adapter_id"], "persistent_http_replay")
                self.assertEqual(logs_payload["max_bytes"], 2000)
                self.assertIn("kyoko fixture replay server listening", logs_payload["stdout"])
            finally:
                stop_out = io.StringIO()
                with redirect_stdout(stop_out):
                    stop_code = main(
                        [
                            "replay-server-stop",
                            "--db",
                            str(db_path),
                            "persistent_http_replay",
                            "--json",
                        ]
                    )
                self.assertEqual(stop_code, 0)
                stop_payload = json.loads(stop_out.getvalue())

            self.assertTrue(stop_payload["stopped"])
            self.assertFalse(stop_payload["running"])

    def test_demo_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "demo-output"

            demo_out = io.StringIO()
            with redirect_stdout(demo_out):
                demo_code = main(
                    [
                        "demo",
                        "--db",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )

            self.assertEqual(demo_code, 0)
            payload = json.loads(demo_out.getvalue())
            self.assertEqual(payload["profile_id"], "profile_news_research_001")
            self.assertEqual(payload["proposal_id"], "proposal_context_timeout_001")
            self.assertEqual(payload["check_status"], "passed")
            self.assertEqual(payload["promoted_trust_level"], "L2_regression")
            self.assertEqual(payload["applied_skill_ids"], ["skill_proposal_context_timeout_001_1"])
            self.assertEqual(payload["status"]["counts"]["replay_adapters"], 1)
            self.assertEqual(payload["status"]["counts"]["skills"], 1)

    def test_evidence_and_analyze_mock_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            evidence_path = Path(tmpdir) / "evidence.json"
            analysis_dir = Path(tmpdir) / "analysis"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            evidence_out = io.StringIO()
            with redirect_stdout(evidence_out):
                evidence_code = main(
                    [
                        "evidence",
                        "--db",
                        str(db_path),
                        "--output",
                        str(evidence_path),
                    ]
                )
            self.assertEqual(evidence_code, 0)
            self.assertTrue(evidence_path.exists())
            self.assertIn("failed_spans: 1", evidence_out.getvalue())

            analyze_out = io.StringIO()
            with redirect_stdout(analyze_out):
                analyze_code = main(
                    [
                        "analyze",
                        "--db",
                        str(db_path),
                        "--operator",
                        "mock",
                        "--output-dir",
                        str(analysis_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )
            self.assertEqual(analyze_code, 0)

            payload = json.loads(analyze_out.getvalue())
            self.assertEqual(payload["proposal_id"], "proposal_mock_span_fetch_timeout_001")
            self.assertTrue(payload["operator_run_id"])
            self.assertTrue(Path(payload["evidence_path"]).exists())
            self.assertTrue(Path(payload["prompt_path"]).exists())
            self.assertTrue(Path(payload["proposal_path"]).exists())

    def test_operator_prompt_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-prompt"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            prompt_out = io.StringIO()
            with redirect_stdout(prompt_out):
                prompt_code = main(
                    [
                        "operator-prompt",
                        "--db",
                        str(db_path),
                        "--target",
                        "codex",
                        "--output-dir",
                        str(output_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )

            self.assertEqual(prompt_code, 0)
            payload = json.loads(prompt_out.getvalue())
            self.assertEqual(payload["target"], "codex")
            self.assertEqual(payload["profile_id"], "profile_news_research_001")
            self.assertEqual(payload["proposal_block_begin"], "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON")
            self.assertTrue(Path(payload["evidence_path"]).exists())
            self.assertNotIn("redaction_audit_event_id", payload)
            evidence = json.loads(Path(payload["evidence_path"]).read_text())
            self.assertEqual(evidence["redaction"]["policy"]["payload_access"], "redacted")
            prompt_path = Path(payload["prompt_path"])
            self.assertTrue(prompt_path.exists())
            prompt = prompt_path.read_text()
            self.assertIn("Codex note", prompt)
            self.assertIn("Evidence Privacy And Audit", prompt)
            self.assertNotIn("Disclosure audit event id", prompt)
            self.assertNotIn("redaction-audit-acknowledge", prompt)

    def test_analyze_command_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            analysis_dir = Path(tmpdir) / "analysis"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            analyze_out = io.StringIO()
            with redirect_stdout(analyze_out):
                analyze_code = main(
                    [
                        "analyze",
                        "--db",
                        str(db_path),
                        "--operator",
                        "command",
                        "--command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(OPERATOR_COMMAND))}",
                        "--output-dir",
                        str(analysis_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )
            self.assertEqual(analyze_code, 0)

            payload = json.loads(analyze_out.getvalue())
            self.assertEqual(payload["operator"], "command")
            self.assertEqual(payload["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertTrue(payload["operator_run_id"])
            self.assertEqual(payload["attempts"], 1)
            self.assertTrue(Path(payload["prompt_path"]).exists())
            self.assertTrue(Path(payload["raw_output_path"]).exists())

            runs_out = io.StringIO()
            with redirect_stdout(runs_out):
                runs_code = main(["operator-runs", "--db", str(db_path), "--json"])
            self.assertEqual(runs_code, 0)
            runs_payload = json.loads(runs_out.getvalue())
            self.assertEqual(runs_payload["operator_runs"][0]["status"], "succeeded")
            self.assertEqual(
                runs_payload["operator_runs"][0]["proposal_id"],
                "proposal_command_span_fetch_timeout_001",
            )

    def test_analyze_command_retries_malformed_operator_output(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            analysis_dir = Path(tmpdir) / "analysis"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            analyze_out = io.StringIO()
            with redirect_stdout(analyze_out):
                analyze_code = main(
                    [
                        "analyze",
                        "--db",
                        str(db_path),
                        "--operator",
                        "command",
                        "--command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(OPERATOR_RETRY_COMMAND))}",
                        "--output-dir",
                        str(analysis_dir),
                        "--schema",
                        str(SCHEMA),
                        "--max-retries",
                        "1",
                        "--json",
                    ]
                )

            self.assertEqual(analyze_code, 0)
            payload = json.loads(analyze_out.getvalue())
            self.assertEqual(payload["proposal_id"], "proposal_retry_span_fetch_timeout_001")
            self.assertEqual(payload["attempts"], 2)

            runs_out = io.StringIO()
            with redirect_stdout(runs_out):
                self.assertEqual(main(["operator-runs", "--db", str(db_path), "--json"]), 0)
            runs_payload = json.loads(runs_out.getvalue())
            metadata = runs_payload["operator_runs"][0]["metadata"]
            self.assertEqual(metadata["attempts"], 2)
            self.assertEqual(metadata["attempt_results"][0]["status"], "invalid_output")
            self.assertEqual(metadata["attempt_results"][1]["status"], "succeeded")

    def test_operator_smoke_expect_failure_returns_captured_report(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-failure-smoke"

            smoke_out = io.StringIO()
            with redirect_stdout(smoke_out):
                smoke_code = main(
                    [
                        "operator-smoke",
                        "--operator",
                        "command",
                        "--command",
                        " ".join(
                            shlex.quote(part)
                            for part in [
                                sys.executable,
                                str(OPERATOR_BAD_COMMAND),
                                "partial-json",
                            ]
                        ),
                        "--output-dir",
                        str(output_dir),
                        "--schema",
                        str(SCHEMA),
                        "--expect-failure",
                        "--json",
                    ]
                )

            self.assertEqual(smoke_code, 0)
            payload = json.loads(smoke_out.getvalue())
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["status"], "captured")
            self.assertEqual(payload["failure_kind"], "invalid_output")
            self.assertFalse(payload["persisted"])
            self.assertTrue(Path(payload["raw_output_path"]).exists())

    def test_operator_adapter_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            register_out = io.StringIO()
            with redirect_stdout(register_out):
                register_code = main(
                    [
                        "operator-adapter-register",
                        "--db",
                        str(db_path),
                        "fixture_operator",
                        "--name",
                        "Fixture operator",
                        "--kind",
                        "generic",
                        "--command",
                        f"{shlex.quote(sys.executable)} {shlex.quote(str(OPERATOR_COMMAND))}",
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )
            self.assertEqual(register_code, 0)
            register_payload = json.loads(register_out.getvalue())
            self.assertEqual(register_payload["adapter_id"], "fixture_operator")

            adapters_out = io.StringIO()
            with redirect_stdout(adapters_out):
                adapters_code = main(["operator-adapters", "--db", str(db_path), "--json"])
            self.assertEqual(adapters_code, 0)
            adapters_payload = json.loads(adapters_out.getvalue())
            self.assertEqual(adapters_payload["operator_adapters"][0]["id"], "fixture_operator")

            analyze_out = io.StringIO()
            with redirect_stdout(analyze_out):
                analyze_code = main(
                    [
                        "analyze",
                        "--db",
                        str(db_path),
                        "--operator",
                        "fixture_operator",
                        "--output-dir",
                        str(output_dir),
                        "--schema",
                        str(SCHEMA),
                        "--json",
                    ]
                )
            self.assertEqual(analyze_code, 0)
            analyze_payload = json.loads(analyze_out.getvalue())
            self.assertEqual(analyze_payload["operator"], "fixture_operator")
            self.assertEqual(analyze_payload["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertTrue(analyze_payload["operator_run_id"])
            self.assertTrue(Path(analyze_payload["prompt_path"]).exists())

    def test_operator_adapter_bootstrap_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            presets_out = io.StringIO()
            with redirect_stdout(presets_out):
                presets_code = main(["operator-adapter-bootstrap", "--db", str(db_path), "--list-presets", "--json"])
            self.assertEqual(presets_code, 0)
            presets_payload = json.loads(presets_out.getvalue())
            self.assertEqual(
                {preset["adapter_id"] for preset in presets_payload["operator_presets"]},
                {"codex", "claude", "hermes", "openclaw"},
            )

            with patch("kyoko.operator_presets.shutil.which", return_value="/usr/local/bin/codex"):
                bootstrap_out = io.StringIO()
                with redirect_stdout(bootstrap_out):
                    bootstrap_code = main(
                        [
                            "operator-adapter-bootstrap",
                            "--db",
                            str(db_path),
                            "codex",
                            "--output-dir",
                            str(output_dir),
                            "--json",
                        ]
                    )

            self.assertEqual(bootstrap_code, 0)
            bootstrap_payload = json.loads(bootstrap_out.getvalue())
            self.assertEqual(bootstrap_payload["registered"][0]["adapter_id"], "codex")
            self.assertEqual(bootstrap_payload["registered"][0]["operator_kind"], "codex")
            self.assertIn("--sandbox", bootstrap_payload["registered"][0]["command"])

            adapters_out = io.StringIO()
            with redirect_stdout(adapters_out):
                adapters_code = main(["operator-adapters", "--db", str(db_path), "--json"])
            self.assertEqual(adapters_code, 0)
            adapters_payload = json.loads(adapters_out.getvalue())
            self.assertEqual(adapters_payload["operator_adapters"][0]["id"], "codex")

    def test_operator_smoke_flow_uses_demo_database_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-smoke"

            smoke_out = io.StringIO()
            with redirect_stdout(smoke_out):
                smoke_code = main(
                    [
                        "operator-smoke",
                        "--operator",
                        "mock",
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )

            self.assertEqual(smoke_code, 0)
            payload = json.loads(smoke_out.getvalue())
            self.assertTrue(payload["used_demo_database"])
            self.assertEqual(payload["operator"], "mock")
            self.assertEqual(payload["proposal_id"], "proposal_mock_span_fetch_timeout_001")
            self.assertTrue(Path(payload["db_path"]).exists())
            self.assertTrue(Path(payload["prompt_path"]).exists())
            self.assertTrue(Path(payload["proposal_path"]).exists())

    def test_operator_smoke_prepare_only_returns_command_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-smoke"

            smoke_out = io.StringIO()
            with redirect_stdout(smoke_out):
                smoke_code = main(
                    [
                        "operator-smoke",
                        "--operator",
                        "command",
                        "--command",
                        f"{shlex.quote(sys.executable)} {{prompt_path}} {{evidence_path}}",
                        "--output-dir",
                        str(output_dir),
                        "--prepare-only",
                        "--json",
                    ]
                )

            self.assertEqual(smoke_code, 0)
            payload = json.loads(smoke_out.getvalue())
            self.assertFalse(payload["live_operator_invoked"])
            self.assertTrue(Path(payload["evidence_path"]).exists())
            self.assertTrue(Path(payload["prompt_path"]).exists())
            self.assertIn(str(payload["prompt_path"]), payload["expanded_command"])
            self.assertIn("KYOKO_PROPOSAL_BLOCK_BEGIN", payload["environment"])
            self.assertIsNotNone(payload["shell_command"])

    def test_operator_smoke_all_presets_prepare_only_returns_matrix(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-smoke-matrix"

            smoke_out = io.StringIO()
            with patch("kyoko.operator_smoke.shutil.which", return_value="/usr/bin/operator"):
                with redirect_stdout(smoke_out):
                    smoke_code = main(
                        [
                            "operator-smoke",
                            "--all-presets",
                            "--prepare-only",
                            "--output-dir",
                            str(output_dir),
                            "--schema",
                            str(SCHEMA),
                            "--json",
                        ]
                    )

            self.assertEqual(smoke_code, 0)
            payload = json.loads(smoke_out.getvalue())
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["summary"]["prepared"], 4)
            self.assertEqual(
                [target["operator"] for target in payload["targets"]],
                ["codex", "claude", "hermes", "openclaw"],
            )
            for target in payload["targets"]:
                self.assertEqual(target["status"], "prepared")
                self.assertTrue(Path(target["plan"]["prompt_path"]).exists())

    def test_project_bootstrap_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "agent-project"

            with patch("kyoko.operator_presets.shutil.which", return_value="/usr/local/bin/codex"):
                bootstrap_out = io.StringIO()
                with redirect_stdout(bootstrap_out):
                    bootstrap_code = main(
                        [
                            "project-bootstrap",
                            "--project-dir",
                            str(project_dir),
                            "--profile-name",
                            "news-research",
                            "--source-framework",
                            "langgraph-python",
                            "--replay-framework",
                            "hermes-python",
                            "--mcp-target",
                            "codex",
                            "--json",
                        ]
                    )

            self.assertEqual(bootstrap_code, 0)
            payload = json.loads(bootstrap_out.getvalue())
            self.assertEqual(payload["project_dir"], str(project_dir.resolve()))
            self.assertEqual(payload["source_adapter"]["framework"], "langgraph-python")
            self.assertEqual(payload["replay_server"]["framework"], "hermes-python")
            self.assertEqual(payload["mcp_config"]["target"], "codex")
            self.assertTrue(Path(payload["db_path"]).exists())
            self.assertTrue(Path(payload["source_adapter"]["output_path"]).exists())
            self.assertTrue(Path(payload["replay_server"]["output_path"]).exists())
            self.assertTrue(Path(payload["mcp_config_path"]).exists())
            self.assertTrue(Path(payload["next_steps_path"]).exists())
            self.assertNotIn("profiles", payload["commands"])
            self.assertIn("--safe-smokes", payload["commands"]["doctor_safe_smokes"])
            self.assertIn("profile-next", payload["commands"]["profile_next"])
            self.assertIn("discover-sources", payload["commands"]["discover_sources"])
            self.assertIn("integration-smoke replay-server", payload["commands"]["replay_smoke"])
            self.assertIn("--run-replay", payload["commands"]["replay_smoke"])
            self.assertIn("replay-adapter-register", payload["commands"]["replay_adapter_register"])
            self.assertIn("import-hermes-kanban", payload["commands"]["import_hermes_kanban"])
            self.assertIn("import-openclaw-sessions", payload["commands"]["import_openclaw_sessions"])
            self.assertIn("--profile-id profile_news_research", payload["commands"]["discover_sources"])
            self.assertIn("profile_news_research_replay", payload["commands"]["replay_adapter_register"])
            self.assertIn("--profile-id profile_news_research", payload["commands"]["import_openclaw_sessions"])

            register_replay_out = io.StringIO()
            register_replay_args = shlex.split(payload["commands"]["replay_adapter_register"])[3:]
            with redirect_stdout(register_replay_out):
                register_replay_code = main(register_replay_args)
            register_replay_payload = json.loads(register_replay_out.getvalue())
            self.assertEqual(register_replay_code, 0)
            self.assertEqual(register_replay_payload["adapter_id"], "profile_news_research_replay")
            self.assertEqual(register_replay_payload["kind"], "managed_http_server")

    def test_mcp_config_and_install_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_path = Path(tmpdir) / "kyoko-mcp.json"
            output_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing": {
                                "command": "existing",
                                "args": [],
                            }
                        },
                        "custom": "preserved",
                    }
                )
            )

            config_out = io.StringIO()
            with redirect_stdout(config_out):
                config_code = main(
                    [
                        "mcp",
                        "config",
                        "--db",
                        str(db_path),
                        "--schema",
                        str(SCHEMA),
                        "--name",
                        "kyoko-dev",
                        "--target",
                        "codex",
                    ]
                )
            self.assertEqual(config_code, 0)
            config_payload = json.loads(config_out.getvalue())
            self.assertEqual(config_payload["target"], "codex")
            self.assertIn("kyoko-dev", config_payload["mcpServers"])
            self.assertIn("serve", config_payload["mcpServers"]["kyoko-dev"]["args"])

            install_plan_out = io.StringIO()
            with redirect_stdout(install_plan_out):
                install_plan_code = main(
                    [
                        "mcp",
                        "install-plan",
                        "--db",
                        str(db_path),
                        "--schema",
                        str(SCHEMA),
                        "--name",
                        "kyoko-dev",
                        "--target",
                        "codex",
                        "--json",
                    ]
                )
            self.assertEqual(install_plan_code, 0)
            install_plan_payload = json.loads(install_plan_out.getvalue())
            self.assertFalse(install_plan_payload["requires_manual_config"])
            self.assertEqual(
                install_plan_payload["command"][0:4],
                ["codex", "mcp", "add", "kyoko-dev"],
            )
            self.assertIn("codex mcp add kyoko-dev", install_plan_payload["shell_command"])

            install_out = io.StringIO()
            with redirect_stdout(install_out):
                install_code = main(
                    [
                        "mcp",
                        "install",
                        "--db",
                        str(db_path),
                        "--schema",
                        str(SCHEMA),
                        "--output",
                        str(output_path),
                        "--json",
                    ]
                )
            self.assertEqual(install_code, 0)
            install_payload = json.loads(install_out.getvalue())
            written_payload = json.loads(output_path.read_text())
            self.assertEqual(install_payload["output"], str(output_path))
            self.assertEqual(written_payload["custom"], "preserved")
            self.assertIn("existing", written_payload["mcpServers"])
            self.assertEqual(written_payload["mcpServers"]["kyoko"]["args"][0:4], ["-m", "kyoko", "mcp", "serve"])

            fake_codex = Path(tmpdir) / "codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import json\n"
                "import os\n"
                "from pathlib import Path\n"
                "import sys\n"
                "config = Path(os.environ['CODEX_HOME']) / 'config.toml'\n"
                "config.parent.mkdir(parents=True, exist_ok=True)\n"
                "if sys.argv[1:] == ['mcp', 'list']:\n"
                "    print(config.read_text() if config.exists() else '')\n"
                "    raise SystemExit(0)\n"
                "config.write_text(' '.join(sys.argv[1:]))\n"
                "print(json.dumps({'client': 'codex', 'args': sys.argv[1:]}))\n"
            )
            fake_codex.chmod(fake_codex.stat().st_mode | 0o111)
            smoke_out = io.StringIO()
            with redirect_stdout(smoke_out):
                smoke_code = main(
                    [
                        "mcp",
                        "install-smoke",
                        "--db",
                        str(db_path),
                        "--schema",
                        str(SCHEMA),
                        "--name",
                        "kyoko-dev",
                        "--target",
                        "codex",
                        "--client-command",
                        str(fake_codex),
                        "--json",
                    ]
                )
            self.assertEqual(smoke_code, 0)
            smoke_payload = json.loads(smoke_out.getvalue())
            self.assertTrue(smoke_payload["passed"])
            self.assertTrue(smoke_payload["temporary"])
            self.assertEqual(smoke_payload["target"], "codex")
            self.assertTrue(smoke_payload["config_exists"])
            self.assertEqual(smoke_payload["list_returncode"], 0)
            self.assertTrue(smoke_payload["list_verified"])

    def test_mcp_install_smoke_all_targets_uses_matrix_runner(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "mcp-smoke"
            fake_report = McpClientInstallSmokeMatrixReport(
                targets=("codex", "claude"),
                server="kyoko-dev",
                output_dir=output_dir,
                passed=True,
                results=(
                    McpClientInstallSmokeTargetReport(
                        target="codex",
                        status="skipped",
                        reason="mcp_client_not_found:codex",
                    ),
                    McpClientInstallSmokeTargetReport(
                        target="claude",
                        status="passed",
                        reason=None,
                    ),
                ),
            )

            out = io.StringIO()
            with patch("kyoko.cli.run_mcp_install_smoke_matrix", return_value=fake_report) as smoke:
                with redirect_stdout(out):
                    code = main(
                        [
                            "mcp",
                            "install-smoke",
                            "--db",
                            str(db_path),
                            "--schema",
                            str(SCHEMA),
                            "--name",
                            "kyoko-dev",
                            "--all-targets",
                            "--output-dir",
                            str(output_dir),
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["summary"]["passed"], 1)
            self.assertEqual(payload["summary"]["skipped"], 1)
            self.assertEqual(smoke.call_args.kwargs["server_name"], "kyoko-dev")
            self.assertTrue(smoke.call_args.kwargs["skip_missing"])

    def test_mcp_install_smoke_without_db_uses_isolated_smoke_database(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "mcp-smoke"
            fake_report = McpClientInstallSmokeMatrixReport(
                targets=("codex", "claude"),
                server="kyoko-dev",
                output_dir=output_dir,
                passed=True,
                results=(
                    McpClientInstallSmokeTargetReport(
                        target="codex",
                        status="passed",
                        reason=None,
                    ),
                ),
            )

            out = io.StringIO()
            with patch("kyoko.cli.run_mcp_install_smoke_matrix", return_value=fake_report) as smoke:
                with redirect_stdout(out):
                    code = main(
                        [
                            "mcp",
                            "install-smoke",
                            "--name",
                            "kyoko-dev",
                            "--all-targets",
                            "--output-dir",
                            str(output_dir),
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertIsNone(smoke.call_args.kwargs["db_path"])

    def test_serve_calls_local_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            serve_out = io.StringIO()
            with patch("kyoko.cli.serve") as serve_mock:
                with redirect_stdout(serve_out):
                    code = main(
                        [
                            "serve",
                            "--db",
                            str(db_path),
                            "--host",
                            "127.0.0.1",
                            "--port",
                            "0",
                            "--default-lock-actor-agent-identity-id",
                            "agent_researcher_001",
                        ]
                    )

            self.assertEqual(code, 0)
            serve_mock.assert_called_once_with(
                db_path=db_path,
                host="127.0.0.1",
                port=0,
                auth_token=None,
                default_lock_actor_agent_identity_id="agent_researcher_001",
            )
            self.assertIn("serving Kyoko dashboard", serve_out.getvalue())
            self.assertIn(
                "default_lock_actor_agent_identity_id: agent_researcher_001",
                serve_out.getvalue(),
            )

    def test_dashboard_smoke_cli_runs_browser_smoke(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "dashboard-smoke"

            class FakeDashboardSmokeReport:
                def __init__(self, selected_db_path: Path, selected_output_dir: Path) -> None:
                    self.passed = True
                    self.db_path = selected_db_path
                    self.output_dir = selected_output_dir
                    self.server_url = "http://127.0.0.1:1"
                    self.viewports = []
                    self.console_errors = ()
                    self.page_errors = ()
                    self.request_failures = ()

                def to_json(self):
                    return {
                        "kind": "dashboard_browser_smoke",
                        "db_path": str(self.db_path),
                        "output_dir": str(self.output_dir),
                        "passed": True,
                        "viewports": [
                            {"name": "desktop", "passed": True},
                            {"name": "mobile", "passed": True},
                        ],
                    }

            out = io.StringIO()
            with patch(
                "kyoko.cli.run_dashboard_browser_smoke",
                return_value=FakeDashboardSmokeReport(db_path, output_dir),
            ) as smoke:
                with redirect_stdout(out):
                    code = main(
                        [
                            "dashboard-smoke",
                            "--db",
                            str(db_path),
                            "--output-dir",
                            str(output_dir),
                            "--screenshot",
                            "--timeout",
                            "12",
                            "--json",
                        ]
                    )

            self.assertEqual(code, 0)
            smoke.assert_called_once_with(
                db_path=db_path,
                output_dir=output_dir,
                seed_demo=True,
                screenshot=True,
                install_browser_deps=False,
                timeout_seconds=12,
            )
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["passed"])
            self.assertEqual(payload["viewports"][0]["name"], "desktop")

    def test_dashboard_smoke_cli_reports_browser_dependency_error_as_json(self) -> None:
        with patch(
            "kyoko.cli.run_dashboard_browser_smoke",
            side_effect=DashboardSmokeError("playwright_missing: install playwright"),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["dashboard-smoke", "--json"])

        self.assertEqual(code, 1)
        payload = json.loads(out.getvalue())
        self.assertFalse(payload["passed"])
        self.assertEqual(payload["kind"], "dashboard_browser_smoke")
        self.assertIn("playwright_missing", payload["error"])

    def test_propose_rejects_invalid_evidence(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(["ingest-fixture", "--db", str(db_path), str(FIXTURE)]), 0)

            invalid_err = io.StringIO()
            with redirect_stderr(invalid_err):
                invalid_code = main(
                    [
                        "propose",
                        "--db",
                        str(db_path),
                        "--schema",
                        str(SCHEMA),
                        str(INVALID_PROPOSAL),
                    ]
                )
            self.assertEqual(invalid_code, 1)
            self.assertIn("evidence_ref_not_found", invalid_err.getvalue())


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


if __name__ == "__main__":
    unittest.main()
