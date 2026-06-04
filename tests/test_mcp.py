import io
import json
import os
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from kyoko.mcp import (
    KyokoMcpServer,
    MCP_DIRECT_APPLY_TOOL_NAMES,
    MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES,
    McpTool,
    McpError,
    _assert_default_mcp_tool_safety,
    build_mcp_config,
    build_mcp_install_plan,
    merge_mcp_config,
    run_mcp_install_smoke,
    run_mcp_install_smoke_matrix,
    serve_stdio,
    write_mcp_config,
)
from kyoko.blobs import put_blob
from kyoko.operator_adapters import register_operator_adapter
from kyoko.proposals import submit_learning_proposal
from kyoko.storage import ingest_source_fixture
from tests.test_improve import _write_failed_openclaw_session


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
JUDGE_COMMAND = ROOT / "tests/fixtures/judge_command.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class McpTests(unittest.TestCase):
    def test_initialize_and_tools_list(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            initialize = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"},
                }
            )
            tools = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                }
            )

            self.assertEqual(initialize["result"]["serverInfo"]["name"], "kyoko")
            self.assertIn("tools", initialize["result"]["capabilities"])
            tool_names = {tool["name"] for tool in tools["result"]["tools"]}
            tools_by_name = {tool["name"]: tool for tool in tools["result"]["tools"]}
            self.assertIn("kyoko_status", tool_names)
            self.assertIn("kyoko_mcp_safety_contract", tool_names)
            self.assertIn("kyoko_list_profiles", tool_names)
            self.assertIn("kyoko_run_profile_next_step", tool_names)
            self.assertIn("kyoko_get_dashboard_metrics", tool_names)
            self.assertIn("kyoko_run_doctor", tool_names)
            self.assertIn("kyoko_discover_sources", tool_names)
            self.assertIn("kyoko_get_storage_report", tool_names)
            self.assertIn("kyoko_list_payload_blobs", tool_names)
            self.assertIn("kyoko_prune_payload_blobs_dry_run", tool_names)
            self.assertIn("kyoko_get_evidence", tool_names)
            self.assertIn("kyoko_list_runs", tool_names)
            self.assertIn("kyoko_get_run_detail", tool_names)
            self.assertIn("kyoko_submit_proposal", tool_names)
            self.assertIn("kyoko_list_context_rules", tool_names)
            self.assertIn("kyoko_list_context_rule_revisions", tool_names)
            self.assertIn("kyoko_rollback_context_rule_revision", tool_names)
            self.assertIn("kyoko_list_skill_revisions", tool_names)
            self.assertIn("kyoko_rollback_skill_revision", tool_names)
            self.assertIn("kyoko_run_replay_adapter", tool_names)
            self.assertIn("kyoko_run_improve", tool_names)
            self.assertIn("kyoko_prepare_operator_smoke_matrix", tool_names)
            self.assertIn("kyoko_list_operator_runs", tool_names)
            self.assertIn("kyoko_list_harness_patches", tool_names)
            self.assertIn("kyoko_list_harness_target_locks", tool_names)
            self.assertIn("kyoko_get_policy", tool_names)
            self.assertIn("kyoko_prune_retention_dry_run", tool_names)
            self.assertIn("kyoko_get_proposal_detail", tool_names)
            self.assertIn("kyoko_get_check_detail", tool_names)
            self.assertIn("kyoko_list_check_assertion_presets", tool_names)
            self.assertIn("kyoko_get_check_capabilities", tool_names)
            self.assertIn("kyoko_run_judge_command", tool_names)
            self.assertIn("kyoko_list_check_locks", tool_names)
            self.assertIn("kyoko_get_replay_detail", tool_names)
            self.assertIn("kyoko_list_issues", tool_names)
            self.assertIn("kyoko_get_issue", tool_names)
            self.assertIn("kyoko_create_issue", tool_names)
            # Issue tools are read/propose evidence — never direct-apply or harness-write.
            self.assertFalse(tools_by_name["kyoko_create_issue"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools_by_name["kyoko_create_issue"]["annotations"]["destructiveHint"])
            self.assertNotIn("kyoko_create_issue", MCP_DIRECT_APPLY_TOOL_NAMES)
            self.assertNotIn("kyoko_create_issue", MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES)
            self.assertTrue(tools_by_name["kyoko_list_issues"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools_by_name["kyoko_get_issue"]["annotations"]["readOnlyHint"])
            self.assertTrue(
                tools_by_name["kyoko_prune_payload_blobs_dry_run"]["annotations"]["readOnlyHint"]
            )
            self.assertFalse(
                tools_by_name["kyoko_prune_payload_blobs_dry_run"]["annotations"]["destructiveHint"]
            )
            self.assertFalse(tools_by_name["kyoko_get_evidence"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools_by_name["kyoko_get_evidence"]["annotations"]["destructiveHint"])
            self.assertFalse(tools_by_name["kyoko_get_evidence"]["annotations"]["idempotentHint"])
            self.assertFalse(tools_by_name["kyoko_run_judge_command"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools_by_name["kyoko_run_judge_command"]["annotations"]["destructiveHint"])
            self.assertFalse(tools_by_name["kyoko_run_judge_command"]["annotations"]["idempotentHint"])
            self.assertTrue(
                tools_by_name["kyoko_rollback_skill_revision"]["annotations"]["destructiveHint"]
            )
            self.assertTrue(
                tools_by_name["kyoko_mcp_safety_contract"]["annotations"]["readOnlyHint"]
            )
            self.assertFalse(MCP_DIRECT_APPLY_TOOL_NAMES & tool_names)
            self.assertFalse(MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES & tool_names)
            next_step_schema = tools_by_name["kyoko_run_profile_next_step"]["inputSchema"]["properties"]
            self.assertNotIn("all_profiles", next_step_schema)
            self.assertNotIn("max_steps", next_step_schema)
            self.assertIn("profile_id", next_step_schema)
            self.assertIn("operator_adapter_id", next_step_schema)
            doctor_schema = tools_by_name["kyoko_run_doctor"]["inputSchema"]["properties"]
            self.assertIn("safe_smokes", doctor_schema)
            self.assertIn("improve_smoke", doctor_schema)
            self.assertIn("opentelemetry_smoke", doctor_schema)
            self.assertIn("opentelemetry_python_executable", doctor_schema)
            self.assertIn("ace_native_prepare", doctor_schema)
            self.assertIn("ace_native_smoke", doctor_schema)
            self.assertIn("dashboard_smoke", doctor_schema)
            self.assertIn("dashboard_smoke_screenshot", doctor_schema)
            self.assertIn("dashboard_smoke_install_browser_deps", doctor_schema)
            self.assertIn("dashboard_smoke_timeout_seconds", doctor_schema)
            self.assertIn("smoke_output_dir", doctor_schema)
            self.assertIn("smoke_evidence_dir", doctor_schema)
            self.assertFalse(tools_by_name["kyoko_run_doctor"]["annotations"]["readOnlyHint"])
            smoke_schema = tools_by_name["kyoko_prepare_operator_smoke_matrix"]["inputSchema"]["properties"]
            self.assertIn("operators", smoke_schema)
            self.assertFalse(
                tools_by_name["kyoko_prepare_operator_smoke_matrix"]["annotations"]["readOnlyHint"]
            )

            safety = _call_tool(server, "kyoko_mcp_safety_contract", {})["structuredContent"]
            self.assertTrue(safety["passed"])
            self.assertEqual(safety["direct_apply_tools_exposed"], [])
            self.assertEqual(safety["direct_harness_write_tools_exposed"], [])
            self.assertIn("kyoko_run_improve", safety["mcp_autonomy_disabled_tools"])
            self.assertIn("kyoko_rollback_skill_revision", safety["destructive_tools"])

    def test_mcp_safety_guard_rejects_direct_apply_tool(self) -> None:
        tools = {
            "kyoko_run_improve": McpTool(
                name="kyoko_run_improve",
                title="Run Kyoko Improve",
                description="non-applying improve",
                input_schema={"type": "object"},
                handler=lambda _args: {},
            ),
            "kyoko_apply": McpTool(
                name="kyoko_apply",
                title="Apply Kyoko Proposal",
                description="direct apply",
                input_schema={"type": "object"},
                handler=lambda _args: {},
                read_only=False,
                destructive=True,
                idempotent=False,
            ),
        }

        with self.assertRaisesRegex(
            McpError,
            "mcp_default_surface_exposes_prohibited_tools:kyoko_apply",
        ):
            _assert_default_mcp_tool_safety(tools)

    def test_profile_next_mcp_explicit_operator_target_keeps_prompt_only_with_registered_adapter(self) -> None:
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
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            result = _call_tool(
                server,
                "kyoko_run_profile_next_step",
                {
                    "run": True,
                    "operator_target": "codex",
                    "operator_output_dir": str(output_dir),
                    "schema_path": str(SCHEMA),
                },
            )["structuredContent"]

            self.assertEqual(result["status"], "executed")
            self.assertEqual(result["reason"], "prepared_operator_prompt")
            self.assertEqual(result["result"]["target"], "codex")

    def test_profile_next_mcp_runs_registered_operator_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-output"
            ingest_source_fixture(db_path, FIXTURE)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                command=[sys.executable, str(OPERATOR_COMMAND)],
            )
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            result = _call_tool(
                server,
                "kyoko_run_profile_next_step",
                {
                    "run": True,
                    "operator_adapter_id": "fixture_operator",
                    "operator_output_dir": str(output_dir),
                    "schema_path": str(SCHEMA),
                },
            )["structuredContent"]

            self.assertEqual(result["status"], "executed")
            self.assertEqual(result["reason"], "ran_operator_adapter")
            self.assertEqual(result["result"]["adapter_id"], "fixture_operator")
            self.assertEqual(result["result"]["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertEqual(result["routing_after"]["state"], "needs_check_generation")

    def test_mcp_prepare_operator_smoke_matrix_writes_prompt_artifacts(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator-smoke"
            ingest_source_fixture(db_path, FIXTURE)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            with patch("kyoko.operator_smoke.shutil.which", return_value="/usr/bin/codex"):
                result = _call_tool(
                    server,
                    "kyoko_prepare_operator_smoke_matrix",
                    {
                        "operators": ["codex"],
                        "output_dir": str(output_dir),
                        "schema_path": str(SCHEMA),
                    },
                )["structuredContent"]

            self.assertTrue(result["passed"])
            self.assertFalse(result["live_operator_invoked"])
            self.assertEqual(result["summary"]["prepared"], 1)
            self.assertEqual(result["targets"][0]["operator"], "codex")
            self.assertEqual(result["targets"][0]["status"], "prepared")
            self.assertTrue(Path(result["targets"][0]["plan"]["prompt_path"]).exists())

    def test_mcp_doctor_tool_runs_safe_smokes_with_artifact_dir(self) -> None:
        class FakeDoctorReport:
            def to_json(self) -> dict[str, object]:
                return {
                    "ok": True,
                    "summary": {"passed": 2, "warnings": 0, "failed": 0},
                    "checks": [
                        {
                            "id": "python",
                            "status": "pass",
                            "message": "Python ready",
                            "detail": {},
                        }
                    ],
                    "suggested_commands": [
                        {
                            "intent": "mcp_install_smoke_matrix",
                            "cli_args": [
                                "python3",
                                "-m",
                                "kyoko",
                                "mcp",
                                "install-smoke",
                                "--all-targets",
                                "--json",
                            ],
                            "mutating": False,
                            "requires": [],
                        }
                    ],
                }

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "doctor-smoke"
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            with patch("kyoko.mcp.run_doctor", return_value=FakeDoctorReport()) as doctor:
                result = _call_tool(
                    server,
                    "kyoko_run_doctor",
                    {
                        "safe_smokes": True,
                        "improve_smoke": True,
                        "opentelemetry_smoke": True,
                        "opentelemetry_python_executable": str(output_dir / "bin/python"),
                        "ace_native_prepare": True,
                        "ace_native_smoke": True,
                        "dashboard_smoke": True,
                        "dashboard_smoke_screenshot": True,
                        "dashboard_smoke_install_browser_deps": True,
                        "dashboard_smoke_timeout_seconds": 45,
                        "smoke_output_dir": str(output_dir),
                        "host": "127.0.0.1",
                        "port": 9876,
                    },
                )["structuredContent"]

        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["passed"], 2)
        self.assertEqual(result["checks"][0]["id"], "python")
        self.assertEqual(
            result["suggested_commands"][0]["intent"],
            "mcp_install_smoke_matrix",
        )
        self.assertEqual(doctor.call_args.kwargs["db_path"], db_path)
        self.assertTrue(doctor.call_args.kwargs["safe_smokes"])
        self.assertTrue(doctor.call_args.kwargs["improve_smoke"])
        self.assertTrue(doctor.call_args.kwargs["opentelemetry_smoke"])
        self.assertEqual(
            doctor.call_args.kwargs["opentelemetry_python_executable"],
            output_dir / "bin/python",
        )
        self.assertTrue(doctor.call_args.kwargs["ace_native_prepare"])
        self.assertTrue(doctor.call_args.kwargs["ace_native_smoke"])
        self.assertTrue(doctor.call_args.kwargs["dashboard_smoke"])
        self.assertTrue(doctor.call_args.kwargs["dashboard_smoke_screenshot"])
        self.assertTrue(doctor.call_args.kwargs["dashboard_smoke_install_browser_deps"])
        self.assertEqual(doctor.call_args.kwargs["dashboard_smoke_timeout_seconds"], 45)
        self.assertEqual(doctor.call_args.kwargs["smoke_output_dir"], output_dir)
        self.assertEqual(doctor.call_args.kwargs["smoke_evidence_dir"], Path(".kyoko/smoke"))
        self.assertEqual(doctor.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(doctor.call_args.kwargs["port"], 9876)

    def test_tool_calls_return_structured_content(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            blob = put_blob(
                db_path=db_path,
                profile_id="profile_news_research_001",
                data=b"expired payload",
                media_type="text/plain",
                retained_until="2000-01-01T00:00:00Z",
            )
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            status = _call_tool(server, "kyoko_status", {})
            profiles = _call_tool(server, "kyoko_list_profiles", {})
            source_discovery = _call_tool(
                server,
                "kyoko_discover_sources",
                {"home": str(Path(tmpdir) / "empty-home"), "include_missing": True},
            )
            storage = _call_tool(server, "kyoko_get_storage_report", {})
            blobs = _call_tool(server, "kyoko_list_payload_blobs", {})
            payload_prune = _call_tool(server, "kyoko_prune_payload_blobs_dry_run", {})
            policy = _call_tool(server, "kyoko_get_policy", {})
            retention_prune = _call_tool(server, "kyoko_prune_retention_dry_run", {})
            evidence = _call_tool(server, "kyoko_get_evidence", {})
            runs = _call_tool(server, "kyoko_list_runs", {})
            run_detail = _call_tool(
                server,
                "kyoko_get_run_detail",
                {"run_id": "run_research_topic_001"},
            )
            context_rules = _call_tool(server, "kyoko_list_context_rules", {})
            context_rule_revisions = _call_tool(server, "kyoko_list_context_rule_revisions", {})
            harness_target_locks = _call_tool(server, "kyoko_list_harness_target_locks", {})
            check_assertion_presets = _call_tool(server, "kyoko_list_check_assertion_presets", {})
            check_capabilities = _call_tool(server, "kyoko_get_check_capabilities", {})
            check_locks = _call_tool(server, "kyoko_list_check_locks", {})
            skill_revisions = _call_tool(server, "kyoko_list_skill_revisions", {})
            profile_next_analysis = _call_tool(
                server,
                "kyoko_run_profile_next_step",
                {
                    "profile_id": "profile_news_research_001",
                    "run": True,
                    "operator_target": "codex",
                    "operator_output_dir": str(Path(tmpdir) / "operator"),
                    "schema_path": str(SCHEMA),
                },
            )
            proposal = json.loads(VALID_PROPOSAL.read_text())
            submit = _call_tool(server, "kyoko_submit_proposal", {"proposal": proposal})
            profile_next = _call_tool(
                server,
                "kyoko_run_profile_next_step",
                {"profile_id": "profile_news_research_001"},
            )
            dashboard_metrics = _call_tool(server, "kyoko_get_dashboard_metrics", {})
            filtered_proposals = _call_tool(
                server,
                "kyoko_list_proposals",
                {"profile_id": "profile_news_research_001"},
            )
            detail = _call_tool(
                server,
                "kyoko_get_proposal_detail",
                {"proposal_id": "proposal_context_timeout_001"},
            )
            checks = _call_tool(
                server,
                "kyoko_generate_checks",
                {"proposal_id": "proposal_context_timeout_001"},
            )
            check_detail = _call_tool(
                server,
                "kyoko_get_check_detail",
                {"check_spec_id": "check_proposal_context_timeout_001_1"},
            )

            self.assertFalse(status["isError"])
            self.assertEqual(status["structuredContent"]["schema_version"], 28)
            self.assertEqual(
                profiles["structuredContent"]["profiles"][0]["id"],
                "profile_news_research_001",
            )
            self.assertEqual(profiles["structuredContent"]["profiles"][0]["counts"]["spans"], 2)
            self.assertEqual(
                profiles["structuredContent"]["profiles"][0]["routing"]["state"],
                "needs_analysis",
            )
            self.assertEqual(
                profiles["structuredContent"]["profiles"][0]["routing"]["next_action"],
                "analyze",
            )
            self.assertEqual(
                profiles["structuredContent"]["profiles"][0]["routing"]["suggested_commands"][0]["intent"],
                "operator_adapter_bootstrap",
            )
            self.assertEqual(len(source_discovery["structuredContent"]["candidates"]), 2)
            self.assertTrue(
                any(
                    "import-openclaw-sessions" in candidate["import_command"]
                    for candidate in source_discovery["structuredContent"]["candidates"]
                )
            )
            self.assertEqual(storage["structuredContent"]["registered_blobs"], 1)
            self.assertEqual(blobs["structuredContent"]["payload_blobs"][0]["id"], blob.blob_id)
            self.assertTrue(payload_prune["structuredContent"]["dry_run"])
            self.assertEqual(payload_prune["structuredContent"]["pruned_blobs"][0]["blob_id"], blob.blob_id)
            self.assertEqual(policy["structuredContent"]["policy"]["context_mode"], "propose")
            self.assertTrue(retention_prune["structuredContent"]["dry_run"])
            self.assertEqual(retention_prune["structuredContent"]["summary"]["pruned_rows"], 0)
            self.assertEqual(evidence["structuredContent"]["summary"]["failed_spans"], 1)
            self.assertEqual(
                evidence["structuredContent"]["redaction"]["consumer"],
                "mcp:kyoko_get_evidence",
            )
            self.assertEqual(runs["structuredContent"]["runs"][0]["id"], "run_research_topic_001")
            self.assertEqual(run_detail["structuredContent"]["summary"]["failed_spans"], 1)
            self.assertEqual(context_rules["structuredContent"]["context_delivery_rules"], [])
            self.assertEqual(context_rule_revisions["structuredContent"]["context_delivery_rule_revisions"], [])
            self.assertEqual(harness_target_locks["structuredContent"]["harness_target_locks"], [])
            self.assertEqual(
                [
                    preset["name"]
                    for preset in check_assertion_presets["structuredContent"]["assertion_presets"]
                ],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertEqual(
                check_capabilities["structuredContent"]["gateable_check_types"],
                ["deterministic_assertion", "regression_replay"],
            )
            self.assertFalse(check_capabilities["structuredContent"]["judge"]["invokes_model"])
            self.assertIn(
                "dashboard:Run judge",
                check_capabilities["structuredContent"]["judge"]["handoff_surfaces"],
            )
            self.assertEqual(check_locks["structuredContent"]["check_locks"], [])
            self.assertEqual(skill_revisions["structuredContent"]["skill_revisions"], [])
            self.assertEqual(profile_next_analysis["structuredContent"]["status"], "executed")
            self.assertEqual(profile_next_analysis["structuredContent"]["reason"], "prepared_operator_prompt")
            self.assertEqual(profile_next_analysis["structuredContent"]["result"]["target"], "codex")
            self.assertEqual(submit["structuredContent"]["proposal_id"], "proposal_context_timeout_001")
            self.assertEqual(profile_next["structuredContent"]["status"], "planned")
            self.assertEqual(profile_next["structuredContent"]["action"], "generate_checks")
            self.assertEqual(
                dashboard_metrics["structuredContent"]["issues"]["total"],
                1,
            )
            self.assertEqual(
                dashboard_metrics["structuredContent"]["cards"][0]["id"],
                "issues",
            )
            self.assertEqual(
                [proposal["id"] for proposal in filtered_proposals["structuredContent"]["proposals"]],
                ["proposal_context_timeout_001"],
            )
            self.assertEqual(
                filtered_proposals["structuredContent"]["proposals"][0]["section_label"],
                "Context fix",
            )
            self.assertEqual(
                detail["structuredContent"]["proposal"]["section_label"],
                "Context fix",
            )
            self.assertEqual(
                detail["structuredContent"]["target"]["ref"]["entity_id"],
                "agent_researcher_001",
            )
            self.assertEqual(
                detail["structuredContent"]["evidence_chain"]["steps"][0]["stage"],
                "observed_issue",
            )
            self.assertEqual(
                detail["structuredContent"]["check_guidance"]["gateable_check_types"],
                ["deterministic_assertion", "regression_replay"],
            )
            self.assertEqual(
                [
                    preset["name"]
                    for preset in detail["structuredContent"]["check_guidance"]["assertion_presets"]
                ],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertEqual(
                checks["structuredContent"]["check_spec_ids"],
                ["check_proposal_context_timeout_001_1"],
            )
            self.assertEqual(check_detail["structuredContent"]["summary"]["latest_status"], "not_run")

    def test_run_improve_tool_imports_source_without_autonomy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            home = root / "home"
            _write_failed_openclaw_session(home)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            result = _call_tool(
                server,
                "kyoko_run_improve",
                {
                    "source_candidate_id": "openclaw_main",
                    "source_home": str(home),
                    "source_import_output_dir": str(root / "normalized"),
                },
            )
            payload = result["structuredContent"]

            self.assertFalse(result["isError"])
            self.assertTrue(payload["mcp_autonomy_disabled"])
            self.assertEqual(payload["source_import"]["candidate"]["id"], "openclaw_main")
            self.assertEqual(payload["profile_id"], "profile_openclaw_main")
            self.assertEqual(
                payload["proposal_id"],
                "proposal_mock_span_openclaw_error_session_failure_1",
            )
            self.assertEqual(
                payload["generated_check_spec_ids"],
                ["check_proposal_mock_span_openclaw_error_session_failure_1_1"],
            )
            self.assertEqual(payload["replay_runs"], [])
            self.assertIsNone(payload["autonomy"])

    def test_run_judge_command_tool_captures_external_verdict(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "judge-command"
            ingest_source_fixture(db_path, FIXTURE)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            proposal = json.loads(VALID_PROPOSAL.read_text())
            _call_tool(server, "kyoko_submit_proposal", {"proposal": proposal})
            _call_tool(
                server,
                "kyoko_generate_checks",
                {"proposal_id": "proposal_context_timeout_001"},
            )
            _set_mcp_check_type(
                db_path,
                "check_proposal_context_timeout_001_1",
                "judge",
                {
                    "rubric": "Recovered source evidence is complete and dated.",
                    "evidence_refs": [
                        {"entity_type": "span", "entity_id": "span_fetch_timeout_001"},
                    ],
                },
            )

            report = _call_tool(
                server,
                "kyoko_run_judge_command",
                {
                    "check_spec_id": "check_proposal_context_timeout_001_1",
                    "command": [sys.executable, str(JUDGE_COMMAND)],
                    "output_dir": str(output_dir),
                },
            )

            self.assertFalse(report["isError"])
            payload = report["structuredContent"]
            self.assertEqual(payload["check_run"]["status"], "passed")
            self.assertEqual(payload["check_run"]["result"]["judge_backend"], "external_command")
            self.assertFalse(payload["check_run"]["result"]["gateable"])
            self.assertIsNone(payload["check_run"]["promoted_trust_level"])
            self.assertEqual(payload["judgment"]["judge"], "fixture_external_judge")
            self.assertTrue(Path(payload["request_path"]).exists())
            self.assertTrue(Path(payload["result_path"]).exists())

    def test_tool_errors_are_returned_as_mcp_tool_results(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            result = _call_tool(server, "kyoko_get_evidence", {})

            self.assertTrue(result["isError"])
            self.assertIn("no profiles found", result["structuredContent"]["error"])

    def test_stdio_server_handles_jsonrpc_lines(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            stdin = io.StringIO(
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
                + "\n"
                + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                + "\n"
                + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                + "\n"
            )
            stdout = io.StringIO()

            serve_stdio(db_path=db_path, schema_path=SCHEMA, stdin=stdin, stdout=stdout)
            responses = [json.loads(line) for line in stdout.getvalue().splitlines()]

            self.assertEqual([response["id"] for response in responses], [1, 2])
            self.assertEqual(responses[0]["result"]["serverInfo"]["name"], "kyoko")
            self.assertGreater(len(responses[1]["result"]["tools"]), 5)

    def test_build_mcp_config_uses_kyoko_stdio_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            config = build_mcp_config(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="codex",
            )

            server = config["mcpServers"]["kyoko-dev"]
            self.assertEqual(config["target"], "codex")
            self.assertIn("-m", server["args"])
            self.assertIn("kyoko", server["args"])
            self.assertIn("mcp", server["args"])
            self.assertIn("serve", server["args"])
            self.assertIn(str(db_path), server["args"])
            self.assertTrue(Path(server["env"]["PYTHONPATH"]).exists())

    def test_codex_install_plan_uses_native_mcp_command(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            codex_home = Path(tmpdir) / "codex-home"

            plan = build_mcp_install_plan(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="codex",
                home=Path(tmpdir) / "home",
                env={"CODEX_HOME": str(codex_home)},
            )
            payload = plan.to_json()

            self.assertFalse(payload["requires_manual_config"])
            self.assertEqual(payload["command"][0:4], ["codex", "mcp", "add", "kyoko-dev"])
            self.assertIn("--env", payload["command"])
            self.assertTrue(
                any(arg.startswith("PYTHONPATH=") for arg in payload["command"])
            )
            self.assertIn("--", payload["command"])
            self.assertIn("-m", payload["command"])
            self.assertIn("kyoko", payload["command"])
            self.assertIn("mcp", payload["command"])
            self.assertIn("serve", payload["command"])
            self.assertIn(str(db_path), payload["command"])
            self.assertEqual(payload["config_path_hint"], str(codex_home / "config.toml"))
            self.assertIn("codex mcp add kyoko-dev", payload["shell_command"])

    def test_claude_install_plan_uses_add_json_command(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            plan = build_mcp_install_plan(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="claude",
                scope="user",
            )
            payload = plan.to_json()
            server_config = json.loads(payload["command"][-1])

            self.assertFalse(payload["requires_manual_config"])
            self.assertEqual(
                payload["command"][0:5],
                ["claude", "mcp", "add-json", "--scope", "user"],
            )
            self.assertEqual(payload["command"][5], "kyoko-dev")
            self.assertEqual(payload["config_path_hint"], str(Path.home() / ".claude.json"))
            self.assertEqual(server_config["command"], sys.executable)
            self.assertEqual(server_config["args"][0:4], ["-m", "kyoko", "mcp", "serve"])
            self.assertIn(str(db_path), server_config["args"])
            self.assertTrue(Path(server_config["env"]["PYTHONPATH"]).exists())

    def test_codex_install_smoke_runs_client_in_isolated_home(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            fake_codex = _fake_client(
                root / "codex",
                """
import json
import os
from pathlib import Path
import sys

config = Path(os.environ["CODEX_HOME"]) / "config.toml"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print(config.read_text() if config.exists() else "")
    raise SystemExit(0)
config.write_text(" ".join(sys.argv[1:]))
print(json.dumps({"client": "codex", "args": sys.argv[1:], "config": str(config)}))
""",
            )

            report = run_mcp_install_smoke(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="codex",
                output_dir=root / "smoke",
                client_command=fake_codex,
            )
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertEqual(payload["target"], "codex")
            self.assertEqual(payload["command"][0], str(fake_codex))
            self.assertTrue(payload["config_exists"])
            self.assertEqual(payload["list_command"], [str(fake_codex), "mcp", "list"])
            self.assertEqual(payload["list_returncode"], 0)
            self.assertTrue(payload["list_verified"])
            self.assertIn("kyoko-dev", Path(payload["config_path_hint"]).read_text())
            self.assertIn("codex", payload["stdout_tail"])

    def test_install_smoke_uses_isolated_database_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_codex = _fake_client(
                root / "codex",
                """
import json
import os
from pathlib import Path
import sys

config = Path(os.environ["CODEX_HOME"]) / "config.toml"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print(config.read_text() if config.exists() else "")
    raise SystemExit(0)
config.write_text(" ".join(sys.argv[1:]))
print(json.dumps({"client": "codex", "args": sys.argv[1:], "config": str(config)}))
""",
            )
            output_dir = root / "smoke"

            report = run_mcp_install_smoke(
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="codex",
                output_dir=output_dir,
                client_command=fake_codex,
            )
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertIn(str((output_dir / "kyoko.db").resolve()), payload["command"])
            self.assertNotIn(str(Path.home() / ".kyoko" / "kyoko.db"), payload["command"])

    def test_install_smoke_resolves_relative_output_dir_for_client_env(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            fake_codex = _fake_client(
                root / "codex",
                """
import json
import os
from pathlib import Path
import sys

home = Path(os.environ["HOME"])
codex_home = Path(os.environ["CODEX_HOME"])
xdg_home = Path(os.environ["XDG_CONFIG_HOME"])
if not home.is_absolute() or not codex_home.is_absolute() or not xdg_home.is_absolute():
    print("isolated paths must be absolute", file=sys.stderr)
    raise SystemExit(7)
config = codex_home / "config.toml"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print(config.read_text() if config.exists() else "")
    raise SystemExit(0)
config.write_text(" ".join(sys.argv[1:]))
print(json.dumps({"client": "codex", "args": sys.argv[1:], "config": str(config)}))
""",
            )
            original_cwd = Path.cwd()
            try:
                os.chdir(root)
                report = run_mcp_install_smoke(
                    schema_path=SCHEMA,
                    server_name="kyoko-dev",
                    target="codex",
                    output_dir=Path("relative-smoke"),
                    client_command=fake_codex,
                )
            finally:
                os.chdir(original_cwd)
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertTrue(Path(payload["home"]).is_absolute())
            self.assertTrue(Path(payload["cwd"]).is_absolute())
            self.assertTrue(Path(payload["config_path_hint"]).is_absolute())
            self.assertIn(str((root / "relative-smoke" / "kyoko.db").resolve()), payload["command"])

    def test_claude_install_smoke_runs_client_in_isolated_home(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            fake_claude = _fake_client(
                root / "claude",
                """
import json
import os
from pathlib import Path
import sys

config = Path(os.environ["HOME"]) / ".claude.json"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print(config.read_text() if config.exists() else "")
    raise SystemExit(0)
config.write_text(json.dumps({"args": sys.argv[1:]}))
print(json.dumps({"client": "claude", "args": sys.argv[1:], "config": str(config)}))
""",
            )

            report = run_mcp_install_smoke(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="claude",
                scope="user",
                output_dir=root / "smoke",
                client_command=fake_claude,
            )
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertEqual(payload["target"], "claude")
            self.assertEqual(payload["command"][0], str(fake_claude))
            self.assertTrue(payload["config_exists"])
            self.assertEqual(payload["list_command"], [str(fake_claude), "mcp", "list"])
            self.assertEqual(payload["list_returncode"], 0)
            self.assertTrue(payload["list_verified"])
            written = json.loads(Path(payload["config_path_hint"]).read_text())
            self.assertIn("kyoko-dev", written["args"])
            self.assertIn("claude", payload["stdout_tail"])

    def test_install_smoke_fails_when_client_list_does_not_show_server(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            fake_codex = _fake_client(
                root / "codex",
                """
import json
import os
from pathlib import Path
import sys

config = Path(os.environ["CODEX_HOME"]) / "config.toml"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print("other-server")
    raise SystemExit(0)
config.write_text(" ".join(sys.argv[1:]))
print(json.dumps({"client": "codex", "args": sys.argv[1:], "config": str(config)}))
""",
            )

            report = run_mcp_install_smoke(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="codex",
                output_dir=root / "smoke",
                client_command=fake_codex,
            )
            payload = report.to_json()

            self.assertFalse(payload["passed"])
            self.assertEqual(payload["list_returncode"], 0)
            self.assertFalse(payload["list_verified"])
            self.assertIn("other-server", payload["list_stdout_tail"])

    def test_install_smoke_fails_when_client_list_reports_connection_failure(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            fake_claude = _fake_client(
                root / "claude",
                """
import json
import os
from pathlib import Path
import sys

config = Path(os.environ["HOME"]) / ".claude.json"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print("kyoko-dev - Failed to connect")
    raise SystemExit(0)
config.write_text(json.dumps({"args": sys.argv[1:]}))
print(json.dumps({"client": "claude", "args": sys.argv[1:], "config": str(config)}))
""",
            )

            report = run_mcp_install_smoke(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="claude",
                output_dir=root / "smoke",
                client_command=fake_claude,
            )
            payload = report.to_json()

            self.assertFalse(payload["passed"])
            self.assertEqual(payload["list_returncode"], 0)
            self.assertFalse(payload["list_verified"])
            self.assertIn("Failed to connect", payload["list_stdout_tail"])

    def test_install_smoke_matrix_runs_codex_and_claude_clients(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            fake_codex = _fake_client(
                root / "codex",
                """
import os
from pathlib import Path
import sys

config = Path(os.environ["CODEX_HOME"]) / "config.toml"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print(config.read_text() if config.exists() else "")
    raise SystemExit(0)
config.write_text(" ".join(sys.argv[1:]))
print("codex installed")
""",
            )
            fake_claude = _fake_client(
                root / "claude",
                """
import json
import os
from pathlib import Path
import sys

config = Path(os.environ["HOME"]) / ".claude.json"
config.parent.mkdir(parents=True, exist_ok=True)
if sys.argv[1:] == ["mcp", "list"]:
    print(config.read_text() if config.exists() else "")
    raise SystemExit(0)
config.write_text(json.dumps({"args": sys.argv[1:]}))
print("claude installed")
""",
            )

            report = run_mcp_install_smoke_matrix(
                db_path=db_path,
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                output_dir=root / "smoke-matrix",
                client_commands={"codex": fake_codex, "claude": fake_claude},
            )
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertEqual(payload["summary"]["passed"], 2)
            self.assertEqual(payload["summary"]["skipped"], 2)
            self.assertEqual(
                [result["target"] for result in payload["results"]],
                ["codex", "claude", "hermes", "openclaw"],
            )
            for result in payload["results"][:2]:
                self.assertEqual(result["status"], "passed")
                self.assertTrue(result["report"]["list_verified"])
            for result in payload["results"][2:]:
                self.assertEqual(result["status"], "skipped")
                self.assertTrue(result["reason"].startswith("mcp_install_smoke_no_native_command:"))

    def test_install_smoke_matrix_skips_missing_clients(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with patch("kyoko.mcp.shutil.which", return_value=None):
                report = run_mcp_install_smoke_matrix(
                    db_path=Path(tmpdir) / "kyoko.db",
                    schema_path=SCHEMA,
                    targets=("codex",),
                    output_dir=Path(tmpdir) / "smoke-matrix",
                )
            payload = report.to_json()

            self.assertFalse(payload["passed"])
            self.assertEqual(payload["summary"]["skipped"], 1)
            self.assertEqual(payload["results"][0]["status"], "skipped")
            self.assertEqual(payload["results"][0]["reason"], "mcp_client_not_found:codex")

    def test_install_smoke_rejects_unverified_targets(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(McpError, "mcp_install_smoke_no_native_command:openclaw"):
                run_mcp_install_smoke(
                    db_path=Path(tmpdir) / "kyoko.db",
                    schema_path=SCHEMA,
                    target="openclaw",
                    output_dir=Path(tmpdir) / "smoke",
                )

    def test_generic_install_plan_requires_manual_config(self) -> None:
        plan = build_mcp_install_plan(
            db_path=Path("/tmp/kyoko.db"),
            schema_path=SCHEMA,
            target="openclaw",
        )
        payload = plan.to_json()

        self.assertTrue(payload["requires_manual_config"])
        self.assertEqual(payload["command"], [])
        self.assertIsNone(payload["shell_command"])
        self.assertIn("mcpServers", payload["config"])

    def test_merge_mcp_config_preserves_existing_servers(self) -> None:
        generated = build_mcp_config(
            db_path=Path("/tmp/kyoko.db"),
            schema_path=SCHEMA,
            server_name="kyoko",
            target="claude",
        )

        merged = merge_mcp_config(
            existing={
                "theme": "dark",
                "target": "codex",
                "mcpServers": {
                    "filesystem": {
                        "command": "node",
                        "args": ["server.js"],
                    },
                    "kyoko": {
                        "command": "old",
                        "args": ["old"],
                    },
                },
            },
            generated=generated,
        )

        self.assertEqual(merged["target"], "claude")
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["mcpServers"]["filesystem"]["command"], "node")
        self.assertEqual(merged["mcpServers"]["kyoko"]["args"][0:4], ["-m", "kyoko", "mcp", "serve"])

    def test_write_mcp_config_merges_existing_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "mcp.json"
            output_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing": {
                                "command": "existing-command",
                                "args": [],
                            }
                        },
                        "custom": True,
                    }
                )
            )

            payload = write_mcp_config(
                output_path=output_path,
                db_path=Path(tmpdir) / "kyoko.db",
                schema_path=SCHEMA,
                server_name="kyoko-dev",
                target="openclaw",
            )
            written = json.loads(output_path.read_text())

            self.assertEqual(payload, written)
            self.assertTrue(written["custom"])
            self.assertIn("existing", written["mcpServers"])
            self.assertIn("kyoko-dev", written["mcpServers"])
            self.assertEqual(written["target"], "openclaw")


def _set_mcp_check_type(db_path: Path, check_spec_id: str, check_type: str, definition: dict) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE check_specs SET check_type = ?, definition_json = ? WHERE id = ?",
            (check_type, json.dumps(definition, sort_keys=True), check_spec_id),
        )


def _call_tool(server: KyokoMcpServer, name: str, arguments: dict) -> dict:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": f"call_{name}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    return response["result"]


def _fake_client(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body.lstrip()}")
    path.chmod(path.stat().st_mode | 0o111)
    return path


if __name__ == "__main__":
    unittest.main()
