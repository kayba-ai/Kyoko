import io
import importlib
import importlib.metadata
import json
import os
import shlex
import sqlite3
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional
from unittest.mock import patch
import unittest

from kyoko.cli import main
from tests.test_hermes_import import _write_hermes_kanban_db
from tests.test_openclaw_import import _write_openclaw_sessions
from tests.test_replay_servers import (
    RunningReplayServer,
    _fixture_replay_server_command,
    _free_port,
)
from tests.test_integration_smoke import _write_fake_langgraph_package
from tests.test_otlp import _write_fake_opentelemetry_package
from tests.test_source_templates import _source_hook


ROOT = Path(__file__).resolve().parents[1]
HERMES_GOLDEN = ROOT / "docs/fixtures/cli-json/import-hermes-kanban.golden.json"
OPENCLAW_GOLDEN = ROOT / "docs/fixtures/cli-json/import-openclaw-sessions.golden.json"
BUNDLED_ASSETS_GOLDEN = ROOT / "docs/fixtures/cli-json/bundled-assets.contract.golden.json"
BUNDLED_ASSETS_EXPORT_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/bundled-assets-export.contract.golden.json"
)
DEMO_GOLDEN = ROOT / "docs/fixtures/cli-json/demo.contract.golden.json"
STATUS_GOLDEN = ROOT / "docs/fixtures/cli-json/status.contract.golden.json"
LOAD_SMOKE_GOLDEN = ROOT / "docs/fixtures/cli-json/load-smoke.contract.golden.json"
ACE_COMPAT_GOLDEN = ROOT / "docs/fixtures/cli-json/ace-compat.contract.golden.json"
ACE_DIFF_GOLDEN = ROOT / "docs/fixtures/cli-json/ace-diff-proposals.contract.golden.json"
ACE_NATIVE_RUN_GOLDEN = ROOT / "docs/fixtures/cli-json/ace-native-run.contract.golden.json"
ACE_NATIVE_RUN_PREPARE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/ace-native-run-prepare.contract.golden.json"
)
ACE_NATIVE_SMOKE_GOLDEN = ROOT / "docs/fixtures/cli-json/ace-native-smoke.contract.golden.json"
BLOB_PUT_GOLDEN = ROOT / "docs/fixtures/cli-json/blob-put.contract.golden.json"
BLOBS_GOLDEN = ROOT / "docs/fixtures/cli-json/blobs.contract.golden.json"
STORAGE_REPORT_GOLDEN = ROOT / "docs/fixtures/cli-json/storage-report.contract.golden.json"
PRUNE_GOLDEN = ROOT / "docs/fixtures/cli-json/prune.contract.golden.json"
PRUNE_RETENTION_GOLDEN = ROOT / "docs/fixtures/cli-json/prune-retention.contract.golden.json"
DASHBOARD_METRICS_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/dashboard-metrics.contract.golden.json"
)
DASHBOARD_SMOKE_GOLDEN = ROOT / "docs/fixtures/cli-json/dashboard-smoke.contract.golden.json"
RUNS_GOLDEN = ROOT / "docs/fixtures/cli-json/runs.contract.golden.json"
RUN_DETAIL_GOLDEN = ROOT / "docs/fixtures/cli-json/run-detail.contract.golden.json"
POLICY_GOLDEN = ROOT / "docs/fixtures/cli-json/policy.contract.golden.json"
POLICY_SET_GOLDEN = ROOT / "docs/fixtures/cli-json/policy-set.contract.golden.json"
PREPARE_HARNESS_GOLDEN = ROOT / "docs/fixtures/cli-json/prepare-harness.contract.golden.json"
HARNESS_PATCHES_GOLDEN = ROOT / "docs/fixtures/cli-json/harness-patches.contract.golden.json"
HARNESS_TARGET_LOCKS_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/harness-target-locks.contract.golden.json"
)
HARNESS_TARGET_LOCK_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/harness-target-lock.contract.golden.json"
)
HARNESS_TARGET_UNLOCK_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/harness-target-unlock.contract.golden.json"
)
APPLY_HARNESS_GOLDEN = ROOT / "docs/fixtures/cli-json/apply-harness.contract.golden.json"
ROLLBACK_HARNESS_GOLDEN = ROOT / "docs/fixtures/cli-json/rollback-harness.contract.golden.json"
SKILLS_GOLDEN = ROOT / "docs/fixtures/cli-json/skills.contract.golden.json"
SKILL_REVISIONS_GOLDEN = ROOT / "docs/fixtures/cli-json/skill-revisions.contract.golden.json"
SKILL_LOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/skill-lock.contract.golden.json"
SKILL_UNLOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/skill-unlock.contract.golden.json"
SKILL_ROLLBACK_GOLDEN = ROOT / "docs/fixtures/cli-json/skill-rollback.contract.golden.json"
CONTEXT_RULES_GOLDEN = ROOT / "docs/fixtures/cli-json/context-rules.contract.golden.json"
CONTEXT_RULE_REVISIONS_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/context-rule-revisions.contract.golden.json"
)
CONTEXT_RULE_LOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/context-rule-lock.contract.golden.json"
CONTEXT_RULE_UNLOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/context-rule-unlock.contract.golden.json"
CONTEXT_RULE_ROLLBACK_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/context-rule-rollback.contract.golden.json"
)
INGEST_GOLDEN = ROOT / "docs/fixtures/cli-json/ingest.contract.golden.json"
INGEST_OTLP_GOLDEN = ROOT / "docs/fixtures/cli-json/ingest-otlp.contract.golden.json"
WAL_CHECKPOINT_GOLDEN = ROOT / "docs/fixtures/cli-json/wal-checkpoint.contract.golden.json"
RUN_AUTONOMY_GOLDEN = ROOT / "docs/fixtures/cli-json/run-autonomy.contract.golden.json"
OPERATOR_PROMPT_GOLDEN = ROOT / "docs/fixtures/cli-json/operator-prompt.contract.golden.json"
ANALYZE_MOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/analyze-mock.contract.golden.json"
MCP_INSTALL_PLAN_GOLDEN = ROOT / "docs/fixtures/cli-json/mcp-install-plan.contract.golden.json"
MCP_INSTALL_GOLDEN = ROOT / "docs/fixtures/cli-json/mcp-install.contract.golden.json"
OPERATOR_PRESETS_GOLDEN = ROOT / "docs/fixtures/cli-json/operator-presets.contract.golden.json"
OPERATOR_ADAPTER_BOOTSTRAP_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/operator-adapter-bootstrap.contract.golden.json"
)
OPERATOR_ADAPTERS_GOLDEN = ROOT / "docs/fixtures/cli-json/operator-adapters.contract.golden.json"
OPERATOR_ADAPTER_REGISTER_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/operator-adapter-register.contract.golden.json"
)
OPERATOR_ADAPTER_RUN_GOLDEN = ROOT / "docs/fixtures/cli-json/operator-adapter-run.contract.golden.json"
OPERATOR_RUNS_GOLDEN = ROOT / "docs/fixtures/cli-json/operator-runs.contract.golden.json"
REPLAY_ADAPTER_REGISTER_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/replay-adapter-register.contract.golden.json"
)
REPLAY_ADAPTERS_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-adapters.contract.golden.json"
REPLAY_ADAPTER_RUN_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-adapter-run.contract.golden.json"
REPLAY_GOLDEN = ROOT / "docs/fixtures/cli-json/replay.contract.golden.json"
COMPLETE_REPLAY_GOLDEN = ROOT / "docs/fixtures/cli-json/complete-replay.contract.golden.json"
REPLAY_COMMAND_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-command.contract.golden.json"
JUDGE_COMMAND_GOLDEN = ROOT / "docs/fixtures/cli-json/judge-command.contract.golden.json"
JUDGE_SMOKE_GOLDEN = ROOT / "docs/fixtures/cli-json/judge-smoke.contract.golden.json"
SOURCE_ADAPTER_TEMPLATE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/source-adapter-template.contract.golden.json"
)
INTEGRATION_SMOKE_SOURCE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-source.contract.golden.json"
)
INTEGRATION_SMOKE_FRAMEWORK_SOURCE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-framework-source.contract.golden.json"
)
INTEGRATION_SMOKE_FRAMEWORK_REPLAY_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-framework-replay.contract.golden.json"
)
INTEGRATION_SMOKE_FRAMEWORK_IMPROVE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-framework-improve.contract.golden.json"
)
INTEGRATION_SMOKE_OPENTELEMETRY_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-opentelemetry-python.contract.golden.json"
)
INTEGRATION_SMOKE_REPLAY_SERVER_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-replay-server.contract.golden.json"
)
INTEGRATION_SMOKE_IMPROVE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/integration-smoke-improve.contract.golden.json"
)
REPLAY_SERVER_TEMPLATE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/replay-server-template.contract.golden.json"
)
REPLAY_SERVER_HEALTH_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/replay-server-health.contract.golden.json"
)
REPLAY_SERVER_RUN_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-server-run.contract.golden.json"
REPLAY_SERVER_START_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-server-start.contract.golden.json"
REPLAY_SERVER_STATUS_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-server-status.contract.golden.json"
REPLAY_SERVER_LOGS_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-server-logs.contract.golden.json"
REPLAY_SERVER_STOP_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-server-stop.contract.golden.json"
PROPOSALS_GOLDEN = ROOT / "docs/fixtures/cli-json/proposals-context.golden.json"
PROPOSAL_DETAIL_GOLDEN = ROOT / "docs/fixtures/cli-json/proposal-detail-context.contract.golden.json"
ISSUES_GOLDEN = ROOT / "docs/fixtures/cli-json/issues.contract.golden.json"
ISSUE_DETAIL_GOLDEN = ROOT / "docs/fixtures/cli-json/issue-detail.contract.golden.json"
PROFILE_NEXT_GOLDEN = ROOT / "docs/fixtures/cli-json/profile-next-context.contract.golden.json"
IMPROVE_GOLDEN = ROOT / "docs/fixtures/cli-json/improve-existing-proposal.contract.golden.json"
AUTONOMY_EVENTS_GOLDEN = ROOT / "docs/fixtures/cli-json/autonomy-events.contract.golden.json"
CHECK_CAPABILITIES_GOLDEN = ROOT / "docs/fixtures/cli-json/check-capabilities.contract.golden.json"
GENERATE_CHECKS_GOLDEN = ROOT / "docs/fixtures/cli-json/generate-checks.contract.golden.json"
CHECKS_GOLDEN = ROOT / "docs/fixtures/cli-json/checks.contract.golden.json"
CHECK_ASSERTION_PRESETS_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/check-assertion-presets.contract.golden.json"
)
RUN_CHECK_GOLDEN = ROOT / "docs/fixtures/cli-json/run-check.contract.golden.json"
CHECK_DETAIL_GOLDEN = ROOT / "docs/fixtures/cli-json/check-detail.contract.golden.json"
CHECK_LOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/check-lock.contract.golden.json"
CHECK_LOCKS_GOLDEN = ROOT / "docs/fixtures/cli-json/check-locks.contract.golden.json"
CHECK_UNLOCK_GOLDEN = ROOT / "docs/fixtures/cli-json/check-unlock.contract.golden.json"
CHECK_APPROVE_GOLDEN = ROOT / "docs/fixtures/cli-json/check-approve.contract.golden.json"
REPLAY_DETAIL_GOLDEN = ROOT / "docs/fixtures/cli-json/replay-detail.contract.golden.json"
DOCTOR_GOLDEN = ROOT / "docs/fixtures/cli-json/doctor-readiness.contract.golden.json"
DISCOVER_SOURCES_GOLDEN = ROOT / "docs/fixtures/cli-json/discover-sources.contract.golden.json"
IMPORT_DISCOVERED_SOURCE_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/import-discovered-source.contract.golden.json"
)
OPERATOR_SMOKE_MATRIX_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/operator-smoke-prepare-matrix.contract.golden.json"
)
OPERATOR_SMOKE_COMMAND_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/operator-smoke-command.contract.golden.json"
)
OPERATOR_SMOKE_FAILURE_COMMAND_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/operator-smoke-failure-command.contract.golden.json"
)
RELEASE_SMOKE_GOLDEN = ROOT / "docs/fixtures/cli-json/release-smoke.contract.golden.json"
RELEASE_SMOKE_MATRIX_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/release-smoke-matrix.contract.golden.json"
)
MCP_INSTALL_SMOKE_MATRIX_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/mcp-install-smoke-matrix.contract.golden.json"
)
PROJECT_BOOTSTRAP_GOLDEN = (
    ROOT / "docs/fixtures/cli-json/project-bootstrap.contract.golden.json"
)
SOURCE_FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_GENERATED_HARNESS_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
OTLP_FIXTURE = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
OPERATOR_BAD_COMMAND = ROOT / "tests/fixtures/operator_command_bad_output.py"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"
JUDGE_COMMAND = ROOT / "tests/fixtures/judge_command.py"


class CliJsonContractTests(unittest.TestCase):
    def test_bundled_assets_json_matches_golden_contract(self) -> None:
        code, payload = _run_json(["bundled-assets", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload, _load_json(BUNDLED_ASSETS_GOLDEN))

    def test_bundled_assets_export_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "bundled-assets"

            code, payload = _run_json(
                [
                    "bundled-assets",
                    "--output-dir",
                    str(output_dir),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _bundled_assets_export_contract(payload, output_dir),
                _load_json(BUNDLED_ASSETS_EXPORT_GOLDEN),
            )

    def test_demo_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "demo-output"

            code, payload = _run_json(
                [
                    "demo",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _demo_contract(payload, db_path, output_dir),
                _load_json(DEMO_GOLDEN),
            )

    def test_status_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(["status", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _status_contract(payload, db_path),
                _load_json(STATUS_GOLDEN),
            )

    def test_load_smoke_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            code, payload = _run_json(
                [
                    "load-smoke",
                    "--db",
                    str(db_path),
                    "--use-db",
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
                    "--checkpoint-mode",
                    "TRUNCATE",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _load_smoke_contract(payload, db_path),
                _load_json(LOAD_SMOKE_GOLDEN),
            )

    def test_ace_compat_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            ace_path = _write_fake_ace_runtime(root / "ace-runtime")
            _seed_applied_context_proposal_db(db_path)

            with patch(
                "kyoko.ace_bridge.importlib.metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError,
            ):
                code, payload = _run_json(
                    [
                        "ace-compat",
                        "--db",
                        str(db_path),
                        "--ace-path",
                        str(ace_path),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                _ace_compat_contract(payload, ace_path),
                _load_json(ACE_COMPAT_GOLDEN),
            )

    def test_ace_diff_proposals_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            before_path = root / "before.json"
            after_path = root / "after.json"
            output_dir = root / "ace-proposals"
            _seed_source_fixture_db(db_path)
            before_path.write_text(
                json.dumps(
                    {
                        "next_id": 0,
                        "schema_version": "2",
                        "sections": {},
                        "similarity_decisions": {},
                        "skills": {},
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            after_path.write_text(
                json.dumps(
                    {
                        "next_id": 1,
                        "schema_version": "2",
                        "sections": {"context": ["context-00001"]},
                        "similarity_decisions": {},
                        "skills": {
                            "context-00001": {
                                "active": True,
                                "id": "context-00001",
                                "insight": "Retry transient fetch timeouts before handoff.",
                                "issue": "Fetch timeouts are treated as final failures.",
                                "keywords": ["fetch", "retry"],
                                "occurrences": [],
                                "section": "context",
                            }
                        },
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            code, payload = _run_json(
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
                    "--output-dir",
                    str(output_dir),
                    "--persist",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _ace_diff_contract(payload, output_dir),
                _load_json(ACE_DIFF_GOLDEN),
            )

    def test_ace_native_run_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "ace-native"
            command_path = _write_fake_ace_native_command(root / "fake_ace_command.py")
            _seed_source_fixture_db(db_path)

            command = " ".join(shlex.quote(part) for part in [sys.executable, str(command_path)])
            code, payload = _run_json(
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
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _ace_native_run_contract(payload, output_dir, command_path, db_path),
                _load_json(ACE_NATIVE_RUN_GOLDEN),
            )

    def test_ace_native_run_prepare_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "ace-native-prepare"
            _seed_source_fixture_db(db_path)

            command = " ".join(
                shlex.quote(part)
                for part in [
                    sys.executable,
                    "--after",
                    "{after_path}",
                    "--db",
                    "{db_path}",
                    "--profile",
                    "{profile_id}",
                    "--schema",
                    "{schema_path}",
                ]
            )
            code, payload = _run_json(
                [
                    "ace-native-run",
                    "--db",
                    str(db_path),
                    "--command",
                    command,
                    "--output-dir",
                    str(output_dir),
                    "--prepare-only",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _ace_native_prepare_contract(payload, output_dir, db_path),
                _load_json(ACE_NATIVE_RUN_PREPARE_GOLDEN),
            )

    def test_ace_native_smoke_json_matches_golden_contract_projection(self) -> None:
        import_output = io.StringIO()
        try:
            with redirect_stdout(import_output), redirect_stderr(import_output):
                skillbook_module = importlib.import_module("ace.core.skillbook")
        except ImportError:
            self.skipTest("ace package with Skillbook v2 API is not installed")
        if not hasattr(skillbook_module, "Skillbook"):
            self.skipTest("installed ace package does not expose the Skillbook v2 API")

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "ace-native-smoke"
            code, payload = _run_json(
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
            self.assertEqual(
                _ace_native_smoke_contract(payload, output_dir, db_path),
                _load_json(ACE_NATIVE_SMOKE_GOLDEN),
            )

    def test_blob_put_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            blob_input = _write_fixture_blob_input(root)
            _seed_source_fixture_db(db_path)

            code, payload = _run_fixture_blob_put(db_path, blob_input)

            self.assertEqual(code, 0)
            self.assertEqual(
                _blob_put_contract(payload, db_path),
                _load_json(BLOB_PUT_GOLDEN),
            )

    def test_blobs_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            blob_input = _write_fixture_blob_input(root)
            _seed_source_fixture_db(db_path)
            code, _ = _run_fixture_blob_put(db_path, blob_input)
            self.assertEqual(code, 0)

            code, payload = _run_json(["blobs", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _blobs_contract(payload, db_path),
                _load_json(BLOBS_GOLDEN),
            )

    def test_storage_report_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            blob_input = _write_fixture_blob_input(root)
            _seed_source_fixture_db(db_path)
            code, _ = _run_fixture_blob_put(db_path, blob_input)
            self.assertEqual(code, 0)

            code, payload = _run_json(["storage-report", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _storage_report_contract(payload, db_path),
                _load_json(STORAGE_REPORT_GOLDEN),
            )

    def test_prune_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            blob_input = _write_fixture_blob_input(root)
            _seed_source_fixture_db(db_path)
            code, _ = _run_fixture_blob_put(db_path, blob_input)
            self.assertEqual(code, 0)

            code, payload = _run_json(["prune", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _prune_contract(payload, db_path),
                _load_json(PRUNE_GOLDEN),
            )

    def test_prune_retention_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(
                [
                    "prune-retention",
                    "--db",
                    str(db_path),
                    "--trace-older-than-days",
                    "0",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _prune_retention_contract(payload),
                _load_json(PRUNE_RETENTION_GOLDEN),
            )

    def test_dashboard_metrics_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(db_path)

            code, payload = _run_json(["dashboard-metrics", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _dashboard_metrics_contract(payload),
                _load_json(DASHBOARD_METRICS_GOLDEN),
            )

    def test_dashboard_smoke_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "dashboard-smoke.db"
            output_dir = root / "dashboard-smoke"
            screenshot_dir = output_dir / "screenshots"
            screenshot_dir.mkdir(parents=True)
            for name in ("desktop", "mobile"):
                (screenshot_dir / f"dashboard-{name}.png").write_bytes(b"png")

            class FakeDashboardSmokeReport:
                passed = True

                def to_json(self) -> dict:
                    return {
                        "kind": "dashboard_browser_smoke",
                        "db_path": str(db_path),
                        "output_dir": str(output_dir),
                        "temporary": False,
                        "server_url": "http://127.0.0.1:61234",
                        "seeded_demo": True,
                        "api_status": {
                            "initialized": True,
                            "schema_version": 26,
                            "counts": {
                                "profiles": 1,
                                "runs": 2,
                                "spans": 4,
                                "learning_proposals": 1,
                                "check_specs": 1,
                                "replay_runs": 1,
                                "skills": 1,
                            },
                        },
                        "api_metric_cards_count": 6,
                        "console_errors": [],
                        "page_errors": [],
                        "request_failures": [],
                        "browser_backend": "npx-playwright",
                        "passed": True,
                        "viewports": [
                            {
                                "name": "desktop",
                                "width": 1440,
                                "height": 1000,
                                "metric_count": 22,
                                "metric_overflows": [],
                                "screenshot_path": str(screenshot_dir / "dashboard-desktop.png"),
                                "passed": True,
                            },
                            {
                                "name": "mobile",
                                "width": 390,
                                "height": 844,
                                "metric_count": 22,
                                "metric_overflows": [],
                                "screenshot_path": str(screenshot_dir / "dashboard-mobile.png"),
                                "passed": True,
                            },
                        ],
                    }

            with patch("kyoko.cli.run_dashboard_browser_smoke", return_value=FakeDashboardSmokeReport()):
                code, payload = _run_json(
                    [
                        "dashboard-smoke",
                        "--db",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                        "--screenshot",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                _dashboard_smoke_contract(payload, output_dir, db_path),
                _load_json(DASHBOARD_SMOKE_GOLDEN),
            )

    def test_runs_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(["runs", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(_runs_contract(payload), _load_json(RUNS_GOLDEN))

    def test_run_detail_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(db_path)

            code, payload = _run_json(
                [
                    "run-detail",
                    "--db",
                    str(db_path),
                    "run_research_topic_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _run_detail_cli_contract(payload),
                _load_json(RUN_DETAIL_GOLDEN),
            )

    def test_policy_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(["policy", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _policy_payload_contract(payload),
                _load_json(POLICY_GOLDEN),
            )

    def test_policy_set_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(
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
                    "allow_touched_only",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _policy_payload_contract(payload),
                _load_json(POLICY_SET_GOLDEN),
            )

    def test_prepare_harness_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_generated_harness_proposal_db(db_path)

            code, payload = _run_json(
                [
                    "prepare-harness",
                    "--db",
                    str(db_path),
                    "proposal_harness_generated_check_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(PREPARE_HARNESS_GOLDEN))

    def test_harness_patches_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_prepared_generated_harness_db(db_path)

            code, payload = _run_json(["harness-patches", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _harness_patches_contract(payload),
                _load_json(HARNESS_PATCHES_GOLDEN),
            )

    def test_harness_target_lock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(HARNESS_TARGET_LOCK_GOLDEN))

    def test_harness_target_locks_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)
            code, _ = _run_json(
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
            self.assertEqual(code, 0)

            code, payload = _run_json(["harness-target-locks", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _harness_target_locks_contract(payload),
                _load_json(HARNESS_TARGET_LOCKS_GOLDEN),
            )

    def test_harness_target_unlock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)
            code, _ = _run_json(
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
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "harness-target-unlock",
                    "--db",
                    str(db_path),
                    "checks/generated_timeout_check.py",
                    "--reason",
                    "review complete",
                    "--actor-agent-identity-id",
                    "agent_researcher_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(HARNESS_TARGET_UNLOCK_GOLDEN))

    def test_apply_harness_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            workspace = root / "workspace"
            workspace.mkdir()
            _seed_prepared_generated_harness_db(db_path, repo_patch=True)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(
                _harness_apply_contract(payload, workspace),
                _load_json(APPLY_HARNESS_GOLDEN),
            )

    def test_rollback_harness_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            workspace = root / "workspace"
            workspace.mkdir()
            _seed_prepared_generated_harness_db(db_path, repo_patch=True)
            code, _ = _run_json(
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
            self.assertEqual(code, 0)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(
                _harness_apply_contract(payload, workspace),
                _load_json(ROLLBACK_HARNESS_GOLDEN),
            )

    def test_skills_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_applied_context_proposal_db(db_path)

            code, payload = _run_json(["skills", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(_skills_contract(payload), _load_json(SKILLS_GOLDEN))

    def test_skill_revisions_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_applied_context_proposal_db(db_path)

            code, payload = _run_json(
                [
                    "skill-revisions",
                    "--db",
                    str(db_path),
                    "--skill-id",
                    "skill_proposal_context_timeout_001_1",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _skill_revisions_contract(payload),
                _load_json(SKILL_REVISIONS_GOLDEN),
            )

    def test_skill_lock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_applied_context_proposal_db(db_path)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(SKILL_LOCK_GOLDEN))

    def test_skill_unlock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_applied_context_proposal_db(db_path)
            code, _ = _run_json(
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
            self.assertEqual(code, 0)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(SKILL_UNLOCK_GOLDEN))

    def test_skill_rollback_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_applied_context_proposal_db(db_path)
            code, revisions = _run_json(
                [
                    "skill-revisions",
                    "--db",
                    str(db_path),
                    "--skill-id",
                    "skill_proposal_context_timeout_001_1",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            revision_id = revisions["skill_revisions"][0]["id"]

            code, payload = _run_json(["skill-rollback", "--db", str(db_path), revision_id, "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _skill_rollback_contract(payload),
                _load_json(SKILL_ROLLBACK_GOLDEN),
            )

    def test_context_rules_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_rule_db(db_path)

            code, payload = _run_json(["context-rules", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(_context_rules_contract(payload), _load_json(CONTEXT_RULES_GOLDEN))

    def test_context_rule_revisions_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_rule_db(db_path)

            code, payload = _run_json(
                [
                    "context-rule-revisions",
                    "--db",
                    str(db_path),
                    "--rule-id",
                    "context_rule_researcher_timeout",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _context_rule_revisions_contract(payload),
                _load_json(CONTEXT_RULE_REVISIONS_GOLDEN),
            )

    def test_context_rule_lock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_rule_db(db_path)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(CONTEXT_RULE_LOCK_GOLDEN))

    def test_context_rule_unlock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_rule_db(db_path)
            code, _ = _run_json(
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
            self.assertEqual(code, 0)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(CONTEXT_RULE_UNLOCK_GOLDEN))

    def test_context_rule_rollback_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_rule_db(db_path)
            code, revisions = _run_json(
                [
                    "context-rule-revisions",
                    "--db",
                    str(db_path),
                    "--rule-id",
                    "context_rule_researcher_timeout",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            revision_id = revisions["context_delivery_rule_revisions"][0]["id"]

            code, payload = _run_json(
                ["context-rule-rollback", "--db", str(db_path), revision_id, "--json"]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _context_rule_rollback_contract(payload),
                _load_json(CONTEXT_RULE_ROLLBACK_GOLDEN),
            )

    def test_ingest_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            payload_path = root / "source-events.json"
            payload_path.write_text(SOURCE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

            code, payload = _run_json(["ingest", "--db", str(db_path), str(payload_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(INGEST_GOLDEN))

    def test_ingest_otlp_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            normalized_path = root / "normalized.json"

            code, payload = _run_json(
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
                    str(root),
                    "--source-kind",
                    "otlp_http",
                    "--output",
                    str(normalized_path),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _ingest_otlp_contract(payload, root),
                _load_json(INGEST_OTLP_GOLDEN),
            )

    def test_wal_checkpoint_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(
                [
                    "wal-checkpoint",
                    "--db",
                    str(db_path),
                    "--mode",
                    "TRUNCATE",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _wal_checkpoint_contract(payload, db_path),
                _load_json(WAL_CHECKPOINT_GOLDEN),
            )

    def test_run_autonomy_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(db_path)
            code, _ = _run_json(
                [
                    "policy-set",
                    "--db",
                    str(db_path),
                    "--context-mode",
                    "autonomous",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(["run-autonomy", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _run_autonomy_contract(payload),
                _load_json(RUN_AUTONOMY_GOLDEN),
            )

    def test_operator_prompt_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-prompt"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_prompt_cli_contract(payload, output_dir),
                _load_json(OPERATOR_PROMPT_GOLDEN),
            )

    def test_analyze_mock_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "analysis"
            _seed_source_fixture_db(db_path)

            code, payload = _run_json(
                [
                    "analyze",
                    "--db",
                    str(db_path),
                    "--operator",
                    "mock",
                    "--output-dir",
                    str(output_dir),
                    "--schema",
                    str(SCHEMA),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _analyze_mock_contract(payload, output_dir),
                _load_json(ANALYZE_MOCK_GOLDEN),
            )

    def test_mcp_install_plan_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            code, payload = _run_json(
                [
                    "mcp",
                    "install-plan",
                    "--db",
                    str(db_path),
                    "--schema",
                    str(SCHEMA),
                    "--target",
                    "codex",
                    "--name",
                    "kyoko-dev",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _mcp_install_plan_contract(payload, db_path),
                _load_json(MCP_INSTALL_PLAN_GOLDEN),
            )

    def test_mcp_install_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_path = root / "mcp.json"

            code, payload = _run_json(
                [
                    "mcp",
                    "install",
                    "--db",
                    str(db_path),
                    "--schema",
                    str(SCHEMA),
                    "--target",
                    "codex",
                    "--name",
                    "kyoko-dev",
                    "--output",
                    str(output_path),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _mcp_install_contract(payload, output_path, db_path),
                _load_json(MCP_INSTALL_GOLDEN),
            )

    def test_operator_presets_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            code, payload = _run_json(
                [
                    "operator-adapter-bootstrap",
                    "--db",
                    str(Path(tmpdir) / "kyoko.db"),
                    "--list-presets",
                    "--json",
                ]
            )

        self.assertEqual(code, 0)
        self.assertEqual(payload, _load_json(OPERATOR_PRESETS_GOLDEN))

    def test_operator_adapter_bootstrap_json_matches_golden_contract_projection(self) -> None:
        def fake_which(command: str):
            return {
                "codex": "/usr/local/bin/codex",
                "claude": None,
                "hermes": "/usr/local/bin/hermes",
                "openclaw": None,
            }.get(command)

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            _seed_source_fixture_db(db_path)

            with patch("kyoko.operator_presets.shutil.which", side_effect=fake_which):
                code, payload = _run_json(
                    [
                        "operator-adapter-bootstrap",
                        "--db",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                        "--timeout",
                        "300",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_adapter_bootstrap_contract(payload, output_dir),
                _load_json(OPERATOR_ADAPTER_BOOTSTRAP_GOLDEN),
            )

    def test_operator_adapters_json_matches_golden_contract_projection(self) -> None:
        def fake_which(command: str):
            return {
                "codex": "/usr/local/bin/codex",
                "claude": None,
                "hermes": "/usr/local/bin/hermes",
                "openclaw": None,
            }.get(command)

        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            _seed_source_fixture_db(db_path)
            with patch("kyoko.operator_presets.shutil.which", side_effect=fake_which):
                code, _ = _run_json(
                    [
                        "operator-adapter-bootstrap",
                        "--db",
                        str(db_path),
                        "--output-dir",
                        str(output_dir),
                        "--timeout",
                        "300",
                        "--json",
                    ]
                )
            self.assertEqual(code, 0)

            code, payload = _run_json(["operator-adapters", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_adapters_contract(payload, output_dir),
                _load_json(OPERATOR_ADAPTERS_GOLDEN),
            )

    def test_operator_adapter_register_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            _seed_source_fixture_db(db_path)

            code, payload = _register_fixture_operator_adapter(db_path, output_dir)

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_adapter_register_contract(payload, output_dir),
                _load_json(OPERATOR_ADAPTER_REGISTER_GOLDEN),
            )

    def test_operator_adapter_run_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            _seed_source_fixture_db(db_path)
            code, _ = _register_fixture_operator_adapter(db_path, output_dir)
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "operator-adapter-run",
                    "--db",
                    str(db_path),
                    "fixture_operator",
                    "--schema",
                    str(SCHEMA),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_adapter_run_contract(payload, output_dir),
                _load_json(OPERATOR_ADAPTER_RUN_GOLDEN),
            )

    def test_operator_runs_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "operator-output"
            _seed_source_fixture_db(db_path)
            code, _ = _register_fixture_operator_adapter(db_path, output_dir)
            self.assertEqual(code, 0)
            code, _ = _run_json(
                [
                    "operator-adapter-run",
                    "--db",
                    str(db_path),
                    "fixture_operator",
                    "--schema",
                    str(SCHEMA),
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(["operator-runs", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_runs_contract(payload, output_dir),
                _load_json(OPERATOR_RUNS_GOLDEN),
            )

    def test_replay_adapter_register_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "replay-adapter"
            _seed_source_fixture_db(db_path)

            code, payload = _register_fixture_replay_adapter(db_path, output_dir)

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_adapter_register_contract(payload, output_dir),
                _load_json(REPLAY_ADAPTER_REGISTER_GOLDEN),
            )

    def test_replay_adapters_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "replay-adapter"
            _seed_source_fixture_db(db_path)
            code, _ = _register_fixture_replay_adapter(db_path, output_dir)
            self.assertEqual(code, 0)

            code, payload = _run_json(["replay-adapters", "--db", str(db_path), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_adapters_contract(payload, output_dir),
                _load_json(REPLAY_ADAPTERS_GOLDEN),
            )

    def test_replay_adapter_run_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "replay-adapter"
            _seed_check_spec_db(db_path)
            code, _ = _register_fixture_replay_adapter(db_path, output_dir)
            self.assertEqual(code, 0)

            code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_adapter_run_contract(payload, output_dir),
                _load_json(REPLAY_ADAPTER_RUN_GOLDEN),
            )

    def test_replay_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(db_path)

            code, payload = _run_json(
                [
                    "replay",
                    "--db",
                    str(db_path),
                    "check_proposal_context_timeout_001_1",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_replay_contract(payload), _load_json(REPLAY_GOLDEN))

    def test_complete_replay_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(db_path)
            replay_payload, completion_payload = _complete_fixture_replay(db_path)

            self.assertEqual(replay_payload["replay_run_id"], completion_payload["replay_run_id"])
            self.assertEqual(
                _complete_replay_contract(completion_payload),
                _load_json(COMPLETE_REPLAY_GOLDEN),
            )

    def test_replay_command_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "replay-command"
            _seed_check_spec_db(db_path)

            code, payload = _run_fixture_replay_command(db_path, output_dir)

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_command_contract(payload, output_dir),
                _load_json(REPLAY_COMMAND_GOLDEN),
            )

    def test_judge_command_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "judge-command"
            _seed_judge_check_spec_db(db_path)

            code, payload = _run_fixture_judge_command(db_path, output_dir)

            self.assertEqual(code, 0)
            self.assertEqual(
                _judge_command_contract(payload, output_dir),
                _load_json(JUDGE_COMMAND_GOLDEN),
            )

    def test_judge_smoke_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "judge-smoke"

            code, payload = _run_fixture_judge_smoke(output_dir)

            self.assertEqual(code, 0)
            self.assertEqual(
                _judge_smoke_contract(payload, output_dir),
                _load_json(JUDGE_SMOKE_GOLDEN),
            )

    def test_source_adapter_template_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "source" / "kyoko_source_adapter.py"

            code, payload = _run_json(
                [
                    "source-adapter-template",
                    str(output_path),
                    "--framework",
                    "langgraph-python",
                    "--profile-name",
                    "news-research",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _source_adapter_template_contract(payload, output_path),
                _load_json(SOURCE_ADAPTER_TEMPLATE_GOLDEN),
            )

    def test_integration_smoke_source_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            adapter_path = root / "kyoko_source_adapter.py"
            hook_path = root / "source_hook.py"
            output_dir = root / "source-smoke"
            hook_path.write_text(_source_hook(), encoding="utf-8")
            code, _ = _run_json(
                [
                    "source-adapter-template",
                    str(adapter_path),
                    "--framework",
                    "langgraph-python",
                    "--profile-name",
                    "news-research",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "source",
                    "--db",
                    str(db_path),
                    str(adapter_path),
                    "--hook",
                    f"{hook_path}:collect",
                    "--output-dir",
                    str(output_dir),
                    "--profile-id",
                    "profile_cli_smoke",
                    "--source-id",
                    "source_cli_smoke",
                    "--agent-id",
                    "agent_cli_smoke",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_source_contract(payload, output_dir),
                _load_json(INTEGRATION_SMOKE_SOURCE_GOLDEN),
            )

    def test_integration_smoke_framework_source_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "framework-source"
            _write_fake_langgraph_package(output_dir)

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "framework-source",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--python-executable",
                    sys.executable,
                    "--timeout",
                    "10",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_framework_source_contract(payload, output_dir),
                _load_json(INTEGRATION_SMOKE_FRAMEWORK_SOURCE_GOLDEN),
            )

    def test_integration_smoke_framework_replay_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "framework-replay"
            _write_fake_langgraph_package(output_dir)

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "framework-replay",
                    "--output-dir",
                    str(output_dir),
                    "--python-executable",
                    sys.executable,
                    "--timeout",
                    "10",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_framework_replay_contract(payload, output_dir),
                _load_json(INTEGRATION_SMOKE_FRAMEWORK_REPLAY_GOLDEN),
            )

    def test_integration_smoke_framework_improve_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "framework-improve"
            _write_fake_langgraph_package(output_dir)

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "framework-improve",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--python-executable",
                    sys.executable,
                    "--timeout",
                    "10",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_framework_improve_contract(payload, output_dir),
                _load_json(INTEGRATION_SMOKE_FRAMEWORK_IMPROVE_GOLDEN),
            )

    def test_integration_smoke_opentelemetry_python_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "opentelemetry-python"
            _write_fake_opentelemetry_package(output_dir)

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "opentelemetry-python",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--python-executable",
                    sys.executable,
                    "--timeout",
                    "10",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_opentelemetry_contract(payload, output_dir),
                _load_json(INTEGRATION_SMOKE_OPENTELEMETRY_GOLDEN),
            )

    def test_integration_smoke_replay_server_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            server_path = root / "kyoko_replay_server.py"
            hook_path = root / "replay_hook.py"
            output_dir = root / "replay-smoke"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            hook_path.write_text(
                """
def replay(request):
    return {
        "status": "passed",
        "output_run_id": "run_contract_smoke_replay_001",
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {"span_source": "span_replay"},
        "executed_agent": False,
        "note": "bounded contract replay",
    }
""",
                encoding="utf-8",
            )
            code, _ = _run_json(
                [
                    "replay-server-template",
                    str(server_path),
                    "--framework",
                    "generic-python",
                    "--profile-name",
                    "news-research",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "replay-server",
                    "--command",
                    shlex.join([sys.executable, str(server_path), "--port", str(port)]),
                    "--server-url",
                    server_url,
                    "--output-dir",
                    str(output_dir),
                    "--startup-timeout",
                    "5",
                    "--hook",
                    f"{hook_path}:replay",
                    "--run-replay",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_replay_server_contract(payload, output_dir, server_url),
                _load_json(INTEGRATION_SMOKE_REPLAY_SERVER_GOLDEN),
            )

    def test_integration_smoke_improve_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "improve-smoke"

            code, payload = _run_json(
                [
                    "integration-smoke",
                    "improve",
                    "--db",
                    str(db_path),
                    "--output-dir",
                    str(output_dir),
                    "--timeout",
                    "10",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _integration_smoke_improve_contract(payload, output_dir),
                _load_json(INTEGRATION_SMOKE_IMPROVE_GOLDEN),
            )

    def test_replay_server_template_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "server" / "kyoko_replay_server.py"

            code, payload = _run_json(
                [
                    "replay-server-template",
                    str(output_path),
                    "--framework",
                    "langgraph-python",
                    "--profile-name",
                    "news-research",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_server_template_contract(payload, output_path),
                _load_json(REPLAY_SERVER_TEMPLATE_GOLDEN),
            )

    def test_replay_server_health_json_matches_golden_contract_projection(self) -> None:
        with RunningReplayServer() as server:
            code, payload = _run_json(["replay-server-health", server.base_url, "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_server_health_contract(payload, server.base_url),
                _load_json(REPLAY_SERVER_HEALTH_GOLDEN),
            )

    def test_replay_server_run_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(db_path)

            with RunningReplayServer() as server:
                code, payload = _run_json(
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

                self.assertEqual(code, 0)
                self.assertEqual(
                    _replay_server_run_contract(payload, server.base_url),
                    _load_json(REPLAY_SERVER_RUN_GOLDEN),
                )

    def test_replay_server_start_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "server-process"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            _seed_check_spec_db(db_path)
            code, _ = _register_fixture_managed_replay_adapter(
                db_path,
                output_dir,
                server_url,
                port,
            )
            self.assertEqual(code, 0)

            try:
                code, payload = _run_json(
                    [
                        "replay-server-start",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )

                self.assertEqual(code, 0)
                self.assertEqual(
                    _replay_server_process_contract(payload, output_dir, server_url),
                    _load_json(REPLAY_SERVER_START_GOLDEN),
                )
            finally:
                _run_json(
                    [
                        "replay-server-stop",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )

    def test_replay_server_status_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "server-process"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            _seed_check_spec_db(db_path)
            code, _ = _register_fixture_managed_replay_adapter(
                db_path,
                output_dir,
                server_url,
                port,
            )
            self.assertEqual(code, 0)

            try:
                code, _ = _run_json(
                    [
                        "replay-server-start",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )
                self.assertEqual(code, 0)

                code, payload = _run_json(
                    [
                        "replay-server-status",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )

                self.assertEqual(code, 0)
                self.assertEqual(
                    _replay_server_process_contract(payload, output_dir, server_url),
                    _load_json(REPLAY_SERVER_STATUS_GOLDEN),
                )
            finally:
                _run_json(
                    [
                        "replay-server-stop",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )

    def test_replay_server_logs_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "server-process"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            _seed_check_spec_db(db_path)
            code, _ = _register_fixture_managed_replay_adapter(
                db_path,
                output_dir,
                server_url,
                port,
            )
            self.assertEqual(code, 0)

            try:
                code, _ = _run_json(
                    [
                        "replay-server-start",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )
                self.assertEqual(code, 0)

                code, payload = _run_json(
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

                self.assertEqual(code, 0)
                self.assertEqual(
                    _replay_server_logs_contract(payload, output_dir),
                    _load_json(REPLAY_SERVER_LOGS_GOLDEN),
                )
            finally:
                _run_json(
                    [
                        "replay-server-stop",
                        "--db",
                        str(db_path),
                        "persistent_http_replay",
                        "--json",
                    ]
                )

    def test_replay_server_stop_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "kyoko.db"
            output_dir = root / "server-process"
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            _seed_check_spec_db(db_path)
            code, _ = _register_fixture_managed_replay_adapter(
                db_path,
                output_dir,
                server_url,
                port,
            )
            self.assertEqual(code, 0)

            code, _ = _run_json(
                [
                    "replay-server-start",
                    "--db",
                    str(db_path),
                    "persistent_http_replay",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "replay-server-stop",
                    "--db",
                    str(db_path),
                    "persistent_http_replay",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_server_process_contract(payload, output_dir, server_url),
                _load_json(REPLAY_SERVER_STOP_GOLDEN),
            )

    def test_import_hermes_kanban_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kanban_db = root / "kanban.db"
            kyoko_db = root / "kyoko.db"
            _write_hermes_kanban_db(kanban_db)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "import-hermes-kanban",
                        "--db",
                        str(kyoko_db),
                        str(kanban_db),
                        "--profile-id",
                        "profile_cli_hermes",
                        "--board",
                        "news",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            payload["kanban_db_path"] = "<KANBAN_DB_PATH>"

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(HERMES_GOLDEN))

    def test_import_openclaw_sessions_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            sessions_dir = _write_openclaw_sessions(root)
            kyoko_db = root / "kyoko.db"

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "import-openclaw-sessions",
                        "--db",
                        str(kyoko_db),
                        str(sessions_dir),
                        "--profile-id",
                        "profile_cli_openclaw",
                        "--session-key",
                        "agent:main:session-news",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            payload["source_path"] = "<OPENCLAW_SESSION_PATH>"

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(OPENCLAW_GOLDEN))

    def test_proposals_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(kyoko_db)

            code, payload = _run_json(["proposals", "--db", str(kyoko_db), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(PROPOSALS_GOLDEN))

    def test_proposal_detail_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(kyoko_db)

            code, payload = _run_json(
                [
                    "proposal-detail",
                    "--db",
                    str(kyoko_db),
                    "proposal_context_timeout_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _proposal_detail_contract(payload),
                _load_json(PROPOSAL_DETAIL_GOLDEN),
            )

    def test_issues_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_issue_db(kyoko_db)

            code, payload = _run_json(["issues", "--db", str(kyoko_db), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(_issues_contract(payload), _load_json(ISSUES_GOLDEN))

    def test_issue_detail_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            issue_id = _seed_issue_db(kyoko_db)

            code, payload = _run_json(
                ["issue-detail", "--db", str(kyoko_db), issue_id, "--json"]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_issue_detail_contract(payload), _load_json(ISSUE_DETAIL_GOLDEN))

    def test_profile_next_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(kyoko_db)

            code, payload = _run_json(["profile-next", "--db", str(kyoko_db), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _profile_next_contract(payload, kyoko_db),
                _load_json(PROFILE_NEXT_GOLDEN),
            )

    def test_improve_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kyoko_db = root / "kyoko.db"
            _seed_context_proposal_db(kyoko_db)
            _register_replay_adapter(kyoko_db, root / "replay")
            code, _ = _run_json(
                [
                    "policy-set",
                    "--db",
                    str(kyoko_db),
                    "--context-mode",
                    "autonomous",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "improve",
                    "--db",
                    str(kyoko_db),
                    "--proposal-id",
                    "proposal_context_timeout_001",
                    "--replay-adapter",
                    "fixture_replay",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_improve_contract(payload), _load_json(IMPROVE_GOLDEN))

    def test_autonomy_events_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(kyoko_db)
            code, _ = _run_json(
                [
                    "policy-set",
                    "--db",
                    str(kyoko_db),
                    "--context-mode",
                    "autonomous",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            code, _ = _run_json(["run-autonomy", "--db", str(kyoko_db), "--json"])
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "autonomy-events",
                    "--db",
                    str(kyoko_db),
                    "--kind",
                    "autonomy_decision",
                    "--entity-type",
                    "learning_proposal",
                    "--entity-id",
                    "proposal_context_timeout_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_autonomy_events_contract(payload), _load_json(AUTONOMY_EVENTS_GOLDEN))

    def test_check_capabilities_json_matches_golden_contract(self) -> None:
        code, payload = _run_json(["check-capabilities", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload, _load_json(CHECK_CAPABILITIES_GOLDEN))

    def test_generate_checks_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_context_proposal_db(kyoko_db)

            code, payload = _run_json(
                [
                    "generate-checks",
                    "--db",
                    str(kyoko_db),
                    "proposal_context_timeout_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_generate_checks_contract(payload), _load_json(GENERATE_CHECKS_GOLDEN))

    def test_checks_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)

            code, payload = _run_json(["checks", "--db", str(kyoko_db), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(_checks_contract(payload), _load_json(CHECKS_GOLDEN))

    def test_check_assertion_presets_json_matches_golden_contract(self) -> None:
        code, payload = _run_json(["check-assertion-presets", "--json"])

        self.assertEqual(code, 0)
        self.assertEqual(payload, _load_json(CHECK_ASSERTION_PRESETS_GOLDEN))

    def test_run_check_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)
            replay_payload, _ = _complete_fixture_replay(kyoko_db)

            code, payload = _run_json(
                [
                    "run-check",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--replay-run-id",
                    replay_payload["replay_run_id"],
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_run_check_contract(payload), _load_json(RUN_CHECK_GOLDEN))

    def test_check_detail_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)
            replay_payload, _ = _complete_fixture_replay(kyoko_db)
            code, _ = _run_json(
                [
                    "run-check",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--replay-run-id",
                    replay_payload["replay_run_id"],
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "check-detail",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(_check_detail_contract(payload), _load_json(CHECK_DETAIL_GOLDEN))

    def test_check_lock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)

            code, payload = _run_json(
                [
                    "check-lock",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--reason",
                    "manual review",
                    "--actor-agent-identity-id",
                    "agent_researcher_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(CHECK_LOCK_GOLDEN))

    def test_check_locks_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)
            code, _ = _lock_fixture_check_spec(kyoko_db)
            self.assertEqual(code, 0)

            code, payload = _run_json(["check-locks", "--db", str(kyoko_db), "--json"])

            self.assertEqual(code, 0)
            self.assertEqual(
                _check_locks_contract(payload),
                _load_json(CHECK_LOCKS_GOLDEN),
            )

    def test_check_unlock_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)
            code, _ = _lock_fixture_check_spec(kyoko_db)
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "check-unlock",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--actor-agent-identity-id",
                    "agent_researcher_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(CHECK_UNLOCK_GOLDEN))

    def test_check_approve_json_matches_golden_contract(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kyoko_db = Path(tmpdir) / "kyoko.db"
            _seed_check_spec_db(kyoko_db)
            replay_payload, _ = _complete_fixture_replay(kyoko_db)
            code, _ = _run_json(
                [
                    "run-check",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--replay-run-id",
                    replay_payload["replay_run_id"],
                    "--json",
                ]
            )
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "check-approve",
                    "--db",
                    str(kyoko_db),
                    "check_proposal_context_timeout_001_1",
                    "--reason",
                    "reviewed gate evidence",
                    "--actor-agent-identity-id",
                    "agent_researcher_001",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(payload, _load_json(CHECK_APPROVE_GOLDEN))

    def test_replay_detail_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            kyoko_db = root / "kyoko.db"
            output_dir = root / "replay-command"
            _seed_check_spec_db(kyoko_db)
            code, replay_payload = _run_fixture_replay_command(kyoko_db, output_dir)
            self.assertEqual(code, 0)

            code, payload = _run_json(
                [
                    "replay-detail",
                    "--db",
                    str(kyoko_db),
                    replay_payload["replay_run_id"],
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _replay_detail_contract(payload, output_dir),
                _load_json(REPLAY_DETAIL_GOLDEN),
            )

    def test_doctor_json_matches_golden_contract_projection(self) -> None:
        real_import_module = importlib.import_module

        def fake_which(command: str):
            return {
                "python3.12": "/opt/python/3.12/bin/python3.12",
                "python3.13": "/opt/python/3.13/bin/python3.13",
                "codex": "/usr/local/bin/codex",
                "claude": "/usr/local/bin/claude",
                "hermes": None,
                "openclaw": None,
            }.get(command)

        def fake_build_backend_reason(*, python_executable: str, timeout_seconds: int):
            if python_executable.endswith("python3.12"):
                return None
            return "python_build_backend_unavailable:setuptools.build_meta"

        def fake_import_module(name: str):
            if name == "jsonschema":
                return object()
            return real_import_module(name)

        with TemporaryDirectory() as tmpdir:
            empty_evidence_dir = Path(tmpdir) / "no-retained-smoke"
            with patch("kyoko.doctor.shutil.which", side_effect=fake_which):
                with patch(
                    "kyoko.doctor.python_build_backend_reason",
                    side_effect=fake_build_backend_reason,
                ):
                    with patch(
                        "kyoko.doctor.importlib.metadata.version",
                        side_effect=importlib.metadata.PackageNotFoundError,
                    ):
                        with patch(
                            "kyoko.doctor.importlib.import_module",
                            side_effect=fake_import_module,
                        ):
                            code, payload = _run_json(
                                [
                                    "doctor",
                                    "--port",
                                    "0",
                                    "--smoke-evidence-dir",
                                    str(empty_evidence_dir),
                                    "--json",
                                ]
                            )

        self.assertEqual(code, 0)
        self.assertEqual(_doctor_contract(payload), _load_json(DOCTOR_GOLDEN))

    def test_discover_sources_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "home"
            board_db = home / ".hermes" / "kanban" / "boards" / "news" / "kanban.db"
            board_db.parent.mkdir(parents=True)
            _write_hermes_kanban_db(board_db)
            _write_openclaw_sessions(home)
            db_path = root / "kyoko.db"
            root_path = root / "workspace root"

            code, payload = _run_json(
                [
                    "discover-sources",
                    "--db",
                    str(db_path),
                    "--home",
                    str(home),
                    "--profile-id",
                    "profile_discovery_contract",
                    "--profile-name",
                    "Discovery Contract",
                    "--root-path",
                    str(root_path),
                    "--include-missing",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _source_discovery_contract(payload, db_path, home.resolve(), root_path),
                _load_json(DISCOVER_SOURCES_GOLDEN),
            )

    def test_import_discovered_source_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home = root / "home"
            _write_openclaw_sessions(home)
            db_path = root / "kyoko.db"
            root_path = root / "workspace root"
            output_dir = root / "normalized"

            code, payload = _run_json(
                [
                    "import-discovered-source",
                    "--db",
                    str(db_path),
                    "--home",
                    str(home),
                    "--profile-id",
                    "profile_discovered_import_contract",
                    "--profile-name",
                    "Discovered Import Contract",
                    "--root-path",
                    str(root_path),
                    "--output-dir",
                    str(output_dir),
                    "openclaw_main",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _discovered_source_import_contract(
                    payload,
                    db_path,
                    home.resolve(),
                    root_path,
                    output_dir,
                ),
                _load_json(IMPORT_DISCOVERED_SOURCE_GOLDEN),
            )

    def test_operator_smoke_prepare_matrix_json_matches_golden_contract_projection(self) -> None:
        def fake_which(command: str):
            return {
                "codex": "/usr/local/bin/codex",
                "claude": "/usr/local/bin/claude",
                "hermes": None,
                "openclaw": None,
            }.get(command)

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-smoke"
            with patch("kyoko.operator_smoke.shutil.which", side_effect=fake_which):
                code, payload = _run_json(
                    [
                        "operator-smoke",
                        "--all-presets",
                        "--prepare-only",
                        "--output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_smoke_matrix_contract(payload, output_dir),
                _load_json(OPERATOR_SMOKE_MATRIX_GOLDEN),
            )

    def test_operator_smoke_command_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-smoke-command"
            command = " ".join(
                shlex.quote(part)
                for part in [sys.executable, str(OPERATOR_COMMAND)]
            )
            code, payload = _run_json(
                [
                    "operator-smoke",
                    "--operator",
                    "command",
                    "--command",
                    command,
                    "--output-dir",
                    str(output_dir),
                    "--schema",
                    str(SCHEMA),
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_smoke_report_contract(payload, output_dir),
                _load_json(OPERATOR_SMOKE_COMMAND_GOLDEN),
            )

    def test_operator_smoke_failure_command_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "operator-smoke-failure-command"
            command = " ".join(
                shlex.quote(part)
                for part in [sys.executable, str(OPERATOR_BAD_COMMAND), "partial-json"]
            )
            code, payload = _run_json(
                [
                    "operator-smoke",
                    "--operator",
                    "command",
                    "--command",
                    command,
                    "--output-dir",
                    str(output_dir),
                    "--schema",
                    str(SCHEMA),
                    "--expect-failure",
                    "--json",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(
                _operator_failure_smoke_report_contract(payload, output_dir),
                _load_json(OPERATOR_SMOKE_FAILURE_COMMAND_GOLDEN),
            )

    def test_release_smoke_json_matches_golden_contract_projection(self) -> None:
        class FakeReleaseReport:
            passed = True

            def __init__(self, output_dir: Path, python_executable: str) -> None:
                self.output_dir = output_dir
                self.python_executable = python_executable

            def to_json(self) -> dict:
                return {
                    "artifact_dir": str(self.output_dir / "artifacts"),
                    "artifacts": [
                        {
                            "artifact_path": str(
                                self.output_dir / "artifacts" / "kyoko-0.1.0-py3-none-any.whl"
                            ),
                            "artifact_type": "wheel",
                            "commands": [
                                {
                                    "command": ["/opt/python/3.11/bin/python3.11", "-m", "kyoko", "doctor"],
                                    "cwd": str(self.output_dir),
                                    "duration_ms": 1.23,
                                    "name": "wheel_doctor",
                                    "returncode": 0,
                                    "stdout_tail": "{\"ok\": true}",
                                }
                            ],
                            "doctor_ok": True,
                            "doctor_summary": {"failed": 0, "passed": 9, "warnings": 1},
                            "dashboard_smoke_ok": None,
                            "dashboard_smoke_summary": None,
                            "install_ok": True,
                            "install_strategy": "pip",
                            "installed_version": "0.1.0",
                            "legacy_fallback_used": False,
                            "modern_install_returncode": 0,
                            "run_cwd": str(self.output_dir / "run-wheel"),
                            "venv_path": str(self.output_dir / "venv-wheel"),
                        }
                    ],
                    "build_commands": [
                        {
                            "command": ["/opt/python/3.11/bin/python3.11", "-m", "pip", "wheel"],
                            "cwd": str(self.output_dir / "source"),
                            "duration_ms": 4.56,
                            "name": "build_wheel",
                            "returncode": 0,
                            "stdout_tail": "built wheel",
                        }
                    ],
                    "duration_ms": 9.87,
                    "dashboard_smoke": False,
                    "install_dependencies": False,
                    "output_dir": str(self.output_dir),
                    "passed": True,
                    "project_root": str(ROOT),
                    "python_executable": "/opt/python/3.11/bin/python3.11",
                    "run_demo": False,
                }

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "release-smoke"

            with patch(
                "kyoko.cli.run_release_install_smoke",
                side_effect=lambda *, output_dir, **_kwargs: FakeReleaseReport(
                    output_dir,
                    "/opt/python/3.11/bin/python3.11",
                ),
            ):
                code, payload = _run_json(
                    [
                        "release-smoke",
                        "--project-root",
                        str(ROOT),
                        "--output-dir",
                        str(output_dir),
                        "--artifact",
                        "wheel",
                        "--skip-demo",
                        "--json",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(
                _release_smoke_contract(payload, output_dir),
                _load_json(RELEASE_SMOKE_GOLDEN),
            )

    def test_release_smoke_matrix_json_matches_golden_contract_projection(self) -> None:
        class FakeReleaseReport:
            passed = True

            def __init__(self, output_dir: Path, python_executable: str) -> None:
                self.output_dir = output_dir
                self.python_executable = python_executable

            def to_json(self) -> dict:
                artifact_path = self.output_dir / "artifacts" / "kyoko-0.1.0-py3-none-any.whl"
                venv_path = self.output_dir / "venv-wheel"
                return {
                    "artifact_dir": str(self.output_dir / "artifacts"),
                    "artifacts": [
                        {
                            "artifact_path": str(artifact_path),
                            "artifact_type": "wheel",
                            "commands": [
                                {
                                    "command": [self.python_executable, "-m", "kyoko", "doctor"],
                                    "cwd": str(self.output_dir),
                                    "duration_ms": 1.23,
                                    "name": "wheel_doctor",
                                    "returncode": 0,
                                    "stdout_tail": "{\"ok\": true}",
                                }
                            ],
                            "doctor_ok": True,
                            "doctor_summary": {"failed": 0, "passed": 9, "warnings": 1},
                            "dashboard_smoke_ok": None,
                            "dashboard_smoke_summary": None,
                            "install_ok": True,
                            "install_strategy": "pip",
                            "installed_version": "0.1.0",
                            "legacy_fallback_used": False,
                            "modern_install_returncode": 0,
                            "run_cwd": str(self.output_dir / "run-wheel"),
                            "venv_path": str(venv_path),
                        }
                    ],
                    "build_commands": [
                        {
                            "command": [self.python_executable, "-m", "pip", "wheel"],
                            "cwd": str(self.output_dir / "source"),
                            "duration_ms": 4.56,
                            "name": "build_wheel",
                            "returncode": 0,
                            "stdout_tail": "built wheel",
                        }
                    ],
                    "duration_ms": 9.87,
                    "dashboard_smoke": False,
                    "install_dependencies": False,
                    "output_dir": str(self.output_dir),
                    "artifact_dir": str(self.output_dir / "artifacts"),
                    "passed": True,
                    "project_root": str(ROOT),
                    "python_executable": self.python_executable,
                    "run_demo": False,
                }

        def fake_resolve(target: str):
            return {
                "3.10": "/opt/python/3.10/bin/python3.10",
                "3.11": None,
                "3.12": "/opt/python/3.12/bin/python3.12",
            }[target]

        def fake_build_backend_reason(*, python_executable: str, timeout_seconds: int):
            if python_executable.endswith("python3.12"):
                return "python_build_backend_unavailable:setuptools.build_meta"
            return None

        def fake_release_smoke(*, output_dir: Path, python_executable: str, **kwargs):
            return FakeReleaseReport(output_dir, python_executable)

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "release-matrix"
            with patch("kyoko.release_smoke._resolve_python_executable", side_effect=fake_resolve):
                with patch(
                    "kyoko.release_smoke.python_build_backend_reason",
                    side_effect=fake_build_backend_reason,
                ):
                    with patch(
                        "kyoko.release_smoke.run_release_install_smoke",
                        side_effect=fake_release_smoke,
                    ):
                        code, payload = _run_json(
                            [
                                "release-smoke",
                                "--project-root",
                                str(ROOT),
                                "--output-dir",
                                str(output_dir),
                                "--python-matrix",
                                "--python-target",
                                "3.10",
                                "--python-target",
                                "3.11",
                                "--python-target",
                                "3.12",
                                "--artifact",
                                "wheel",
                                "--skip-demo",
                                "--json",
                            ]
                        )

            self.assertEqual(code, 0)
            self.assertEqual(
                _release_smoke_matrix_contract(payload, output_dir),
                _load_json(RELEASE_SMOKE_MATRIX_GOLDEN),
            )

    def test_mcp_install_smoke_matrix_json_matches_golden_contract_projection(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            output_dir = root / "mcp-install-smoke"
            kyoko_db = root / "kyoko.db"
            _write_fake_executable(
                bin_dir / "codex",
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
            _write_fake_executable(
                bin_dir / "claude",
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

            env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
            with patch.dict(os.environ, env):
                code, payload = _run_json(
                    [
                        "mcp",
                        "install-smoke",
                        "--db",
                        str(kyoko_db),
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
            self.assertEqual(
                _mcp_install_smoke_matrix_contract(payload, output_dir),
                _load_json(MCP_INSTALL_SMOKE_MATRIX_GOLDEN),
            )

    def test_project_bootstrap_json_matches_golden_contract_projection(self) -> None:
        def fake_which(command: str):
            return f"/usr/local/bin/{command}"

        with TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir) / "agent-project"
            with patch("kyoko.operator_presets.shutil.which", side_effect=fake_which):
                code, payload = _run_json(
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

            self.assertEqual(code, 0)
            self.assertEqual(
                _project_bootstrap_contract(payload, project_dir.resolve()),
                _load_json(PROJECT_BOOTSTRAP_GOLDEN),
            )


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _run_json(args: list[str]) -> tuple[int, dict]:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(args)
    return code, json.loads(stdout.getvalue())


def _bundled_assets_export_contract(payload: dict, output_dir: Path) -> dict:
    exported = []
    for item in payload["exported"]:
        exported.append(
            {
                "asset": item["asset"],
                "exists": Path(item["output_path"]).exists(),
                "output_path": _output_path_contract(item["output_path"], output_dir),
            }
        )
    return {
        "assets": payload["assets"],
        "exported": exported,
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
    }


def _demo_contract(payload: dict, db_path: Path, output_dir: Path) -> dict:
    return {
        "adapter_id": payload["adapter_id"],
        "applied_skill_ids": payload["applied_skill_ids"],
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "check_run_id": payload["check_run_id"],
        "check_spec_created_ids": payload["check_spec_created_ids"],
        "check_spec_existing_ids": payload["check_spec_existing_ids"],
        "check_spec_ids": payload["check_spec_ids"],
        "check_status": payload["check_status"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "output_dir_exists": output_dir.exists(),
        "profile_id": payload["profile_id"],
        "promoted_trust_level": payload["promoted_trust_level"],
        "proposal_created": payload["proposal_created"],
        "proposal_id": payload["proposal_id"],
        "replay_run_id": payload["replay_run_id"],
        "status": _status_contract(payload["status"], db_path),
    }


def _status_contract(payload: dict, db_path: Path) -> dict:
    return {
        "counts": payload["counts"],
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "initialized": payload["initialized"],
        "migration_versions": payload["migration_versions"],
        "schema_version": payload["schema_version"],
    }


def _load_smoke_contract(payload: dict, db_path: Path) -> dict:
    return {
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "duration_ms_positive": payload["duration_ms"] > 0,
        "errors": payload["errors"],
        "latency_ms": _latency_summary_contract(payload["latency_ms"]),
        "operation_latency_ms": {
            name: _latency_summary_contract(payload["operation_latency_ms"][name])
            for name in sorted(payload["operation_latency_ms"])
        },
        "parameters": payload["parameters"],
        "passed": payload["passed"],
        "profile_id": payload["profile_id"],
        "retention_dry_run": _prune_contract(payload["retention_dry_run"], db_path),
        "seeded": payload["seeded"],
        "status": _status_contract(payload["status"], db_path),
        "storage": _storage_report_contract(payload["storage"], db_path),
        "temporary": payload["temporary"],
        "total_read_operations": payload["total_read_operations"],
        "wal_checkpoint": _wal_checkpoint_contract(payload["wal_checkpoint"], db_path),
    }


def _latency_summary_contract(summary: dict) -> dict:
    return {
        "count": summary["count"],
        "max_nonnegative": summary["max"] >= 0,
        "min_nonnegative": summary["min"] >= 0,
        "ordered": summary["min"] <= summary["p50"] <= summary["p95"] <= summary["max"],
        "p50_nonnegative": summary["p50"] >= 0,
        "p95_nonnegative": summary["p95"] >= 0,
    }


def _ace_compat_contract(payload: dict, ace_path: Path) -> dict:
    return {
        "ace_import_error": payload["ace_import_error"],
        "ace_import_path": _output_path_contract(payload["ace_import_path"], ace_path),
        "ace_import_stderr": payload["ace_import_stderr"],
        "ace_import_stdout": payload["ace_import_stdout"],
        "ace_importable": payload["ace_importable"],
        "ace_module_version": payload["ace_module_version"],
        "ace_package_version": payload["ace_package_version"],
        "ace_path": _output_path_contract(payload["ace_path"], ace_path),
        "ace_source_version": payload["ace_source_version"],
        "available": payload["available"],
        "detected_api": payload["detected_api"],
        "error": payload["error"],
        "expected_api": payload["expected_api"],
        "import_path": _output_path_contract(payload["import_path"], ace_path),
        "import_stderr": payload["import_stderr"],
        "import_stdout": payload["import_stdout"],
        "python_version_segments": len(str(payload["python_version"]).split(".")),
        "roundtrip_schema_version": payload["roundtrip_schema_version"],
        "roundtrip_skill_count": payload["roundtrip_skill_count"],
        "schema_version": payload["schema_version"],
        "skill_count": payload["skill_count"],
        "skillbook_api_error": payload["skillbook_api_error"],
        "skillbook_import_path": _output_path_contract(payload["skillbook_import_path"], ace_path),
        "stats": payload["stats"],
    }


def _ace_diff_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "persisted": payload["persisted"],
        "profile_id": payload["profile_id"],
        "proposal_ids": payload["proposal_ids"],
        "proposal_paths": [
            {
                "exists": Path(path).exists(),
                "path": _output_path_contract(path, output_dir),
            }
            for path in payload["proposal_paths"]
        ],
        "proposals": [
            _ace_diff_proposal_contract(proposal)
            for proposal in payload["proposals"]
        ],
        "unsupported_changes": payload["unsupported_changes"],
    }


def _ace_native_run_contract(payload: dict, output_dir: Path, command_path: Path, db_path: Path) -> dict:
    return {
        "after_path": {
            "exists": Path(payload["after_path"]).exists(),
            "path": _output_path_contract(payload["after_path"], output_dir),
        },
        "before_path": {
            "exists": Path(payload["before_path"]).exists(),
            "path": _output_path_contract(payload["before_path"], output_dir),
        },
        "canonical_mutation": payload["canonical_mutation"],
        "command": [
            "<PYTHON>" if part == sys.executable else _output_path_contract(part, command_path.parent)
            for part in payload["command"]
        ],
        "diff": _ace_diff_contract(payload["diff"], output_dir / "proposals"),
        "environment": {
            key: _ace_run_env_value_contract(value, output_dir, db_path)
            for key, value in sorted(payload["environment"].items())
        },
        "environment_keys": payload["environment_keys"],
        "expanded_command": [
            "<PYTHON>" if part == sys.executable else _output_path_contract(part, command_path.parent)
            for part in payload["expanded_command"]
        ],
        "external_command_invoked": payload["external_command_invoked"],
        "external_model_invoked": payload["external_model_invoked"],
        "handoff_path": {
            "exists": Path(payload["handoff_path"]).exists(),
            "path": _output_path_contract(payload["handoff_path"], output_dir),
        },
        "live_operator_invoked": payload["live_operator_invoked"],
        "original_command": [
            "<PYTHON>" if part == sys.executable else _output_path_contract(part, command_path.parent)
            for part in payload["original_command"]
        ],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "prepare_only": payload["prepare_only"],
        "prepared": payload["prepared"],
        "profile_id": payload["profile_id"],
        "proposal_output_dir": _output_path_contract(payload["proposal_output_dir"], output_dir),
        "provider_backed": payload["provider_backed"],
        "report_path": {
            "exists": Path(payload["report_path"]).exists(),
            "path": _output_path_contract(payload["report_path"], output_dir),
        },
        "returncode": payload["returncode"],
        "shell_command": _ace_run_shell_contract(payload["shell_command"], output_dir, command_path, db_path),
        "stderr_path": {
            "exists": Path(payload["stderr_path"]).exists(),
            "path": _output_path_contract(payload["stderr_path"], output_dir),
        },
        "stderr_tail": payload["stderr_tail"],
        "stdout_path": {
            "exists": Path(payload["stdout_path"]).exists(),
            "path": _output_path_contract(payload["stdout_path"], output_dir),
        },
        "stdout_tail": payload["stdout_tail"],
        "timeout_seconds": payload["timeout_seconds"],
        "used_temporary_output_dir": payload["used_temporary_output_dir"],
    }


def _ace_run_env_value_contract(value: str, output_dir: Path, db_path: Path) -> str:
    if Path(value).resolve() == db_path.resolve():
        return "<DB_PATH>"
    schema_path = str((ROOT / "docs/schemas/learning-proposal.schema.json").resolve())
    if value in {"docs/schemas/learning-proposal.schema.json", schema_path}:
        return "docs/schemas/learning-proposal.schema.json"
    return _output_path_contract(value, output_dir)


def _ace_run_shell_contract(value: str, output_dir: Path, command_path: Path, db_path: Path) -> str:
    return (
        value.replace(sys.executable, "<PYTHON>")
        .replace(str(command_path), "<COMMAND_PATH>")
        .replace(str(output_dir), "<OUTPUT_DIR>")
        .replace(str(db_path), "<DB_PATH>")
    )


def _ace_native_prepare_contract(payload: dict, output_dir: Path, db_path: Path) -> dict:
    return {
        "after_initialized_from_before": payload["after_initialized_from_before"],
        "after_path": {
            "exists": Path(payload["after_path"]).exists(),
            "path": _output_path_contract(payload["after_path"], output_dir),
        },
        "before_path": {
            "exists": Path(payload["before_path"]).exists(),
            "path": _output_path_contract(payload["before_path"], output_dir),
        },
        "before_schema_version": payload["before_schema_version"],
        "before_skill_count": payload["before_skill_count"],
        "canonical_mutation": payload["canonical_mutation"],
        "command": _ace_prepare_command_contract(payload["command"], output_dir, db_path),
        "diff": payload["diff"],
        "environment": {
            key: _ace_prepare_env_value_contract(value, output_dir, db_path)
            for key, value in sorted(payload["environment"].items())
        },
        "environment_keys": payload["environment_keys"],
        "expanded_command": _ace_prepare_command_contract(payload["expanded_command"], output_dir, db_path),
        "external_command_invoked": payload["external_command_invoked"],
        "external_model_invoked": payload["external_model_invoked"],
        "handoff_path": {
            "exists": Path(payload["handoff_path"]).exists(),
            "path": _output_path_contract(payload["handoff_path"], output_dir),
        },
        "include_inactive": payload["include_inactive"],
        "live_operator_invoked": payload["live_operator_invoked"],
        "original_command": [
            "<PYTHON>" if part == sys.executable else part
            for part in payload["original_command"]
        ],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "prepare_only": payload["prepare_only"],
        "prepared": payload["prepared"],
        "profile_id": payload["profile_id"],
        "proposal_output_dir": {
            "exists": Path(payload["proposal_output_dir"]).exists(),
            "path": _output_path_contract(payload["proposal_output_dir"], output_dir),
        },
        "provider_backed": payload["provider_backed"],
        "returncode": payload["returncode"],
        "schema_path": _ace_prepare_env_value_contract(payload["schema_path"], output_dir, db_path),
        "shell_command_contains_output_dir": "<OUTPUT_DIR>" in _ace_prepare_shell_contract(
            payload["shell_command"], output_dir, db_path
        ),
        "stderr_path": {
            "exists": Path(payload["stderr_path"]).exists(),
            "path": _output_path_contract(payload["stderr_path"], output_dir),
        },
        "stderr_tail": payload["stderr_tail"],
        "stdout_path": {
            "exists": Path(payload["stdout_path"]).exists(),
            "path": _output_path_contract(payload["stdout_path"], output_dir),
        },
        "stdout_tail": payload["stdout_tail"],
        "timeout_seconds": payload["timeout_seconds"],
        "used_temporary_output_dir": payload["used_temporary_output_dir"],
    }


def _ace_prepare_command_contract(command: list[str], output_dir: Path, db_path: Path) -> list[str]:
    return [
        _ace_prepare_env_value_contract("<PYTHON>" if part == sys.executable else part, output_dir, db_path)
        for part in command
    ]


def _ace_prepare_env_value_contract(value: str, output_dir: Path, db_path: Path) -> str:
    if Path(value).resolve() == db_path.resolve():
        return "<DB_PATH>"
    if value == str(output_dir):
        return "<OUTPUT_DIR>"
    if value == sys.executable:
        return "<PYTHON>"
    schema_path = str((ROOT / "docs/schemas/learning-proposal.schema.json").resolve())
    if value in {"docs/schemas/learning-proposal.schema.json", schema_path}:
        return "docs/schemas/learning-proposal.schema.json"
    return _output_path_contract(value, output_dir)


def _ace_prepare_shell_contract(value: str, output_dir: Path, db_path: Path) -> str:
    return value.replace(str(output_dir), "<OUTPUT_DIR>").replace(str(db_path), "<DB_PATH>")


def _ace_native_smoke_contract(payload: dict, output_dir: Path, db_path: Path) -> dict:
    native = payload["native_run"]
    command_path = Path(payload["command_path"])
    return {
        "command_path": _repo_path_contract(payload["command_path"]),
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "external_command_invoked": payload["external_command_invoked"],
        "external_model_invoked": payload["external_model_invoked"],
        "installed_ace_package_invoked": payload["installed_ace_package_invoked"],
        "kind": payload["kind"],
        "live_operator_invoked": payload["live_operator_invoked"],
        "native_run": {
            "after_path": {
                "exists": Path(native["after_path"]).exists(),
                "path": _output_path_contract(native["after_path"], output_dir),
            },
            "before_path": {
                "exists": Path(native["before_path"]).exists(),
                "path": _output_path_contract(native["before_path"], output_dir),
            },
            "canonical_mutation": native["canonical_mutation"],
            "command": [
                "<PYTHON>" if part == sys.executable else _repo_path_contract(part)
                for part in native["command"]
            ],
            "command_path_matches": native["command"][1] == str(command_path),
            "db_path": _db_path_contract(native["db_path"], db_path),
            "diff": _ace_diff_contract(native["diff"], output_dir / "proposals"),
            "external_command_invoked": native["external_command_invoked"],
            "live_operator_invoked": native["live_operator_invoked"],
            "output_dir": _output_path_contract(native["output_dir"], output_dir),
            "passed": native["passed"],
            "profile_id": native["profile_id"],
            "proposal_output_dir": _output_path_contract(
                native["proposal_output_dir"],
                output_dir,
            ),
            "returncode": native["returncode"],
            "stderr_path": {
                "exists": Path(native["stderr_path"]).exists(),
                "path": _output_path_contract(native["stderr_path"], output_dir),
            },
            "stderr_tail": native["stderr_tail"],
            "stdout_path": {
                "exists": Path(native["stdout_path"]).exists(),
                "path": _output_path_contract(native["stdout_path"], output_dir),
            },
            "stdout_tail_contains_command_kind": (
                "legacy_ace_offline_adapter_command" in native["stdout_tail"]
            ),
            "timeout_seconds": native["timeout_seconds"],
            "used_temporary_output_dir": native["used_temporary_output_dir"],
        },
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "profile_id": payload["profile_id"],
        "provider_backed": payload["provider_backed"],
        "source_fixture_path": _repo_path_contract(payload["source_fixture_path"]),
    }


def _ace_diff_proposal_contract(proposal: dict) -> dict:
    changes = proposal["proposed_changes"]
    skill_change = changes[0]
    check_change = changes[1]
    return {
        "confidence": proposal["confidence"],
        "created_at_present": bool(proposal["created_at"]),
        "evidence_refs": proposal["evidence_refs"],
        "gate_expectations": proposal["gate_expectations"],
        "id": proposal["id"],
        "insight": proposal["insight"],
        "problem": proposal["problem"],
        "producer": proposal["producer"],
        "profile_id": proposal["profile_id"],
        "proposed_changes": [
            {
                "insight": skill_change["insight"],
                "issue": skill_change["issue"],
                "keywords": skill_change["keywords"],
                "occurrence_refs": skill_change["occurrence_refs"],
                "operation": skill_change["operation"],
                "section": skill_change["section"],
                "skill_id": skill_change["skill_id"],
                "type": skill_change["type"],
            },
            {
                "definition": check_change["definition"],
                "check_type": check_change["check_type"],
                "name": check_change["name"],
                "side_effect_mode": check_change["side_effect_mode"],
                "trust_level": check_change["trust_level"],
                "type": check_change["type"],
            },
        ],
        "schema_version": proposal["schema_version"],
        "section": proposal["section"],
        "state": proposal["state"],
        "summary": proposal["summary"],
        "title": proposal["title"],
    }


def _blob_put_contract(payload: dict, db_path: Path) -> dict:
    return {
        "blob_id_present": bool(payload["blob_id"]),
        "blob_id_prefix": str(payload["blob_id"]).split("_", 2)[:2],
        "created": payload["created"],
        "path_contract": _blob_path_contract(payload["path"], db_path),
        "path_exists": Path(payload["path"]).exists(),
        "sha256_length": len(payload["sha256"]),
        "size_bytes": payload["size_bytes"],
    }


def _blobs_contract(payload: dict, db_path: Path) -> dict:
    return {
        "payload_blobs": [
            _payload_blob_contract(row, db_path)
            for row in payload["payload_blobs"]
        ],
    }


def _payload_blob_contract(row: dict, db_path: Path) -> dict:
    return {
        "blob_id_present": bool(row["id"]),
        "blob_id_prefix": str(row["id"]).split("_", 2)[:2],
        "kind": row["kind"],
        "media_type": row["media_type"],
        "metadata": {
            "source_path": _tmp_path_contract(row["metadata"]["source_path"], db_path.parent),
        },
        "path_contract": _blob_path_contract(row["path"], db_path),
        "path_exists": Path(row["path"]).exists(),
        "preview": row["preview"],
        "profile_id": row["profile_id"],
        "redaction_mode": row["redaction_mode"],
        "retained_until_present": bool(row["retained_until"]),
        "sha256_length": len(row["sha256"]),
        "size_bytes": row["size_bytes"],
        "timestamps_present": _timestamps_present(row, ("created_at", "updated_at")),
    }


def _storage_report_contract(payload: dict, db_path: Path) -> dict:
    return {
        "blob_root": _blob_root_contract(payload["blob_root"], db_path),
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "db_size_bytes_positive": payload["db_size_bytes"] > 0,
        "missing_blobs": payload["missing_blobs"],
        "orphan_files": payload["orphan_files"],
        "registered_blob_bytes": payload["registered_blob_bytes"],
        "registered_blobs": payload["registered_blobs"],
        "wal_size_bytes_nonnegative": payload["wal_size_bytes"] >= 0,
    }


def _prune_contract(payload: dict, db_path: Path) -> dict:
    return {
        "cutoff": payload["cutoff"],
        "dry_run": payload["dry_run"],
        "pruned_blobs": [
            _pruned_blob_contract(row, db_path)
            for row in payload["pruned_blobs"]
        ],
        "pruned_bytes": payload["pruned_bytes"],
    }


def _pruned_blob_contract(row: dict, db_path: Path) -> dict:
    return {
        "blob_id_present": bool(row["blob_id"]),
        "blob_id_prefix": str(row["blob_id"]).split("_", 2)[:2],
        "path_contract": _blob_path_contract(row["path"], db_path),
        "path_exists": Path(row["path"]).exists(),
        "reason": row["reason"],
        "size_bytes": row["size_bytes"],
    }


def _prune_retention_contract(payload: dict) -> dict:
    return {
        "cutoffs_present": {
            key: bool(value)
            for key, value in payload["cutoffs"].items()
        },
        "dry_run": payload["dry_run"],
        "profile_id": payload["profile_id"],
        "pruned_rows": payload["pruned_rows"],
        "skipped_rows": payload["skipped_rows"],
        "summary": payload["summary"],
    }


def _dashboard_metrics_contract(payload: dict) -> dict:
    return {
        "autonomy": payload["autonomy"],
        "before_after": payload["before_after"],
        "cards": payload["cards"],
        "checks": payload["checks"],
        "issues": payload["issues"],
        "profile_id": payload["profile_id"],
        "profile_name": payload["profile_name"],
        "replay": payload["replay"],
        "runs": payload["runs"],
        "scope": payload["scope"],
    }


def _dashboard_smoke_contract(payload: dict, output_dir: Path, db_path: Path) -> dict:
    status = payload["api_status"]
    counts = status["counts"]
    return {
        "api_metric_cards_count": payload["api_metric_cards_count"],
        "api_status": {
            "initialized": status["initialized"],
            "schema_version": status["schema_version"],
            "counts": {
                "profiles": counts["profiles"],
                "runs": counts["runs"],
                "spans": counts["spans"],
                "learning_proposals": counts["learning_proposals"],
                "check_specs": counts["check_specs"],
                "replay_runs": counts["replay_runs"],
                "skills": counts["skills"],
            },
        },
        "browser_backend": payload["browser_backend"],
        "console_errors": payload["console_errors"],
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "kind": payload["kind"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "page_errors": payload["page_errors"],
        "passed": payload["passed"],
        "request_failures": payload["request_failures"],
        "seeded_demo": payload["seeded_demo"],
        "server_url_loopback": str(payload["server_url"]).startswith("http://127.0.0.1:"),
        "temporary": payload["temporary"],
        "viewports": [
            {
                "height": viewport["height"],
                "metric_count": viewport["metric_count"],
                "metric_overflows": viewport["metric_overflows"],
                "name": viewport["name"],
                "passed": viewport["passed"],
                "screenshot_path": {
                    "exists": Path(viewport["screenshot_path"]).exists(),
                    "path": _output_path_contract(viewport["screenshot_path"], output_dir),
                },
                "width": viewport["width"],
            }
            for viewport in payload["viewports"]
        ],
    }


def _runs_contract(payload: dict) -> dict:
    return {
        "runs": [_run_summary_contract(run) for run in payload["runs"]],
    }


def _run_summary_contract(run: dict) -> dict:
    return {
        "agent_identity_id": run["agent_identity_id"],
        "agent_kind": run["agent_kind"],
        "agent_name": run["agent_name"],
        "external_id": run["external_id"],
        "failed_span_count": run["failed_span_count"],
        "handoff_count": run["handoff_count"],
        "id": run["id"],
        "input_ref": run["input_ref"],
        "metadata": run["metadata"],
        "output_ref": run["output_ref"],
        "profile_id": run["profile_id"],
        "root_span_id": run["root_span_id"],
        "source_id": run["source_id"],
        "span_count": run["span_count"],
        "status": run["status"],
        "summary": run["summary"],
        "task_attempt_id": run["task_attempt_id"],
        "timestamps_present": _timestamps_present(run, ("ended_at", "started_at")),
    }


def _run_detail_cli_contract(payload: dict) -> dict:
    return {
        "agent_identity": _run_detail_agent_contract(payload["agent_identity"]),
        "handoffs": [_run_detail_handoff_contract(handoff) for handoff in payload["handoffs"]],
        "related_proposals": [
            _run_detail_related_proposal_contract(item)
            for item in payload["related_proposals"]
        ],
        "replay_runs": payload["replay_runs"],
        "run": _run_detail_run_contract(payload["run"]),
        "source": _run_detail_source_contract(payload["source"]),
        "span_tree": [_span_tree_node_contract(node) for node in payload["span_tree"]],
        "spans": [_run_detail_span_contract(span) for span in payload["spans"]],
        "summary": payload["summary"],
        "task": _run_detail_task_contract(payload["task"]),
        "task_attempt": _run_detail_task_attempt_contract(payload["task_attempt"]),
        "timeline_events": [
            _run_detail_timeline_event_contract(event)
            for event in payload["timeline_events"]
        ],
    }


def _policy_payload_contract(payload: dict) -> dict:
    return {"policy": _policy_contract(payload["policy"])}


def _policy_contract(policy: dict) -> dict:
    return {
        "allow_check_write": policy["allow_check_write"],
        "allow_profile_config_write": policy["allow_profile_config_write"],
        "allow_replay_server_patch": policy["allow_replay_server_patch"],
        "allow_repo_patch": policy["allow_repo_patch"],
        "allow_skillbook_write": policy["allow_skillbook_write"],
        "allowed_paths": policy["allowed_paths"],
        "context_mode": policy["context_mode"],
        "dirty_worktree_policy": policy["dirty_worktree_policy"],
        "harness_mode": policy["harness_mode"],
        "profile_id": policy["profile_id"],
        "protected_paths": policy["protected_paths"],
        "required_check_level_context": policy["required_check_level_context"],
        "required_check_level_harness": policy["required_check_level_harness"],
        "rollback_on_regression": policy["rollback_on_regression"],
        "timestamps_present": _timestamps_present(policy, ("created_at", "updated_at")),
    }


def _harness_patches_contract(payload: dict) -> dict:
    return {
        "patch_transactions": [
            _harness_patch_transaction_contract(patch)
            for patch in payload["patch_transactions"]
        ],
    }


def _harness_patch_transaction_contract(patch: dict) -> dict:
    return {
        "command_plan": patch["command_plan"],
        "diff_ref": patch["diff_ref"],
        "id": patch["id"],
        "patch_kind": patch["patch_kind"],
        "profile_id": patch["profile_id"],
        "proposal_id": patch["proposal_id"],
        "rollback": _harness_rollback_contract(patch["rollback"]),
        "side_effect_mode": patch["side_effect_mode"],
        "status": patch["status"],
        "target_paths": patch["target_paths"],
        "timestamps_present": _timestamps_present(patch, ("created_at", "updated_at")),
    }


def _harness_rollback_contract(rollback: dict) -> dict:
    return {
        "available": rollback["available"],
        "preimages": [
            {
                "content_present": preimage.get("content") is not None,
                "existed": preimage["existed"],
                "path": preimage["path"],
            }
            for preimage in rollback.get("preimages", [])
        ],
        "reason": rollback.get("reason"),
        "required": rollback["required"],
        "timestamps_present": {
            "applied_at": bool(rollback.get("applied_at")),
            "rolled_back_at": bool(rollback.get("rolled_back_at")),
        },
        "workspace_root_present": bool(rollback.get("workspace_root")),
    }


def _harness_target_locks_contract(payload: dict) -> dict:
    return {
        "harness_target_locks": [
            _harness_target_lock_row_contract(lock)
            for lock in payload["harness_target_locks"]
        ],
    }


def _harness_target_lock_row_contract(lock: dict) -> dict:
    return {
        "human_locked": lock["human_locked"],
        "profile_id": lock["profile_id"],
        "reason": lock["reason"],
        "target_path": lock["target_path"],
        "timestamps_present": _timestamps_present(lock, ("created_at", "updated_at")),
    }


def _harness_apply_contract(payload: dict, workspace: Path) -> dict:
    return {
        "patch_transaction_id": payload["patch_transaction_id"],
        "profile_id": payload["profile_id"],
        "proposal_id": payload["proposal_id"],
        "status": payload["status"],
        "target_files_exist": {
            target_path: (workspace / target_path).exists()
            for target_path in payload["target_paths"]
        },
        "target_paths": payload["target_paths"],
    }


def _skills_contract(payload: dict) -> dict:
    return {"skills": [_skill_contract(skill) for skill in payload["skills"]]}


def _skill_contract(skill: dict) -> dict:
    return {
        "active": skill["active"],
        "counters": {
            "harmful": skill["harmful_count"],
            "helpful": skill["helpful_count"],
            "neutral": skill["neutral_count"],
        },
        "human_lock_reason": skill["human_lock_reason"],
        "human_locked": skill["human_locked"],
        "id": skill["id"],
        "insight": skill["insight"],
        "issue": skill["issue"],
        "keywords": skill["keywords"],
        "occurrences": skill["occurrences"],
        "profile_id": skill["profile_id"],
        "proposal_id": skill["proposal_id"],
        "section": skill["section"],
        "source_run_id": skill["source_run_id"],
        "timestamps_present": _timestamps_present(skill, ("created_at", "updated_at")),
    }


def _skill_revisions_contract(payload: dict) -> dict:
    return {
        "skill_revisions": [
            _skill_revision_contract(revision)
            for revision in payload["skill_revisions"]
        ],
    }


def _skill_revision_contract(revision: dict) -> dict:
    after = revision["after"]
    return {
        "after": _skill_contract(after),
        "before_present": revision["before"] is not None,
        "operation": revision["operation"],
        "profile_id": revision["profile_id"],
        "proposal_id": revision["proposal_id"],
        "revision_id": _revision_id_contract(revision["id"]),
        "skill_id": revision["skill_id"],
        "timestamps_present": _timestamps_present(revision, ("created_at",)),
    }


def _skill_rollback_contract(payload: dict) -> dict:
    return {
        "profile_id": payload["profile_id"],
        "revision_id": _revision_id_contract(payload["revision_id"]),
        "rollback_revision_id": _revision_id_contract(payload["rollback_revision_id"]),
        "rollback_revision_differs": payload["rollback_revision_id"] != payload["revision_id"],
        "skill_id": payload["skill_id"],
        "status": payload["status"],
    }


def _context_rules_contract(payload: dict) -> dict:
    return {
        "context_delivery_rules": [
            _context_rule_contract(rule)
            for rule in payload["context_delivery_rules"]
        ],
    }


def _context_rule_contract(rule: dict) -> dict:
    return {
        "active": rule["active"],
        "human_lock_reason": rule["human_lock_reason"],
        "human_locked": rule["human_locked"],
        "id": rule["id"],
        "profile_id": rule["profile_id"],
        "proposal_id": rule["proposal_id"],
        "rule": rule["rule"],
        "target": rule["target"],
        "timestamps_present": _timestamps_present(rule, ("created_at", "updated_at")),
    }


def _context_rule_revisions_contract(payload: dict) -> dict:
    return {
        "context_delivery_rule_revisions": [
            _context_rule_revision_contract(revision)
            for revision in payload["context_delivery_rule_revisions"]
        ],
    }


def _context_rule_revision_contract(revision: dict) -> dict:
    return {
        "after": _context_rule_contract(revision["after"]),
        "before_present": revision["before"] is not None,
        "operation": revision["operation"],
        "profile_id": revision["profile_id"],
        "proposal_id": revision["proposal_id"],
        "revision_id": _revision_id_contract(revision["id"]),
        "rule_id": revision["rule_id"],
        "timestamps_present": _timestamps_present(revision, ("created_at",)),
    }


def _context_rule_rollback_contract(payload: dict) -> dict:
    return {
        "profile_id": payload["profile_id"],
        "revision_id": _revision_id_contract(payload["revision_id"]),
        "rollback_revision_id": _revision_id_contract(payload["rollback_revision_id"]),
        "rollback_revision_differs": payload["rollback_revision_id"] != payload["revision_id"],
        "rule_id": payload["rule_id"],
        "status": payload["status"],
    }


def _revision_id_contract(value: str) -> dict:
    prefix, separator, suffix = str(value).rpartition("_")
    return {
        "present": bool(value),
        "prefix": prefix if separator else value,
        "suffix_length": len(suffix) if separator else 0,
    }


def _ingest_otlp_contract(payload: dict, root: Path) -> dict:
    return {
        "ingested_counts": payload["ingested_counts"],
        "normalized_path": _output_path_contract(payload["normalized_path"], root),
        "normalized_path_exists": Path(payload["normalized_path"]).exists(),
        "profile_id": payload["profile_id"],
        "run_ids": [_generated_id_contract(run_id) for run_id in payload["run_ids"]],
        "span_ids": [_generated_id_contract(span_id) for span_id in payload["span_ids"]],
    }


def _wal_checkpoint_contract(payload: dict, db_path: Path) -> dict:
    return {
        "busy": payload["busy"],
        "checkpointed_frames_nonnegative": payload["checkpointed_frames"] >= 0,
        "db_path": _db_path_contract(payload["db_path"], db_path),
        "log_frames_nonnegative": payload["log_frames"] >= 0,
        "mode": payload["mode"],
        "wal_path": _tmp_path_contract(payload["wal_path"], db_path.parent),
        "wal_size_after_nonnegative": payload["wal_size_after"] >= 0,
        "wal_size_before_nonnegative": payload["wal_size_before"] >= 0,
    }


def _run_autonomy_contract(payload: dict) -> dict:
    return {
        "decisions": [
            {
                "action": decision["action"],
                "applied_context_rule_ids": decision["applied_context_rule_ids"],
                "applied_skill_ids": decision["applied_skill_ids"],
                "detail": decision["detail"],
                "check_run_ids": decision["check_run_ids"],
                "check_spec_ids": decision["check_spec_ids"],
                "patch_transaction_ids": decision["patch_transaction_ids"],
                "profile_id": decision["profile_id"],
                "proposal_id": decision["proposal_id"],
                "reason": decision["reason"],
                "required_check_level": decision["required_check_level"],
                "section": decision["section"],
                "state_after": decision["state_after"],
                "state_before": decision["state_before"],
            }
            for decision in payload["decisions"]
        ],
        "policy": _policy_contract(payload["policy"]),
        "profile_id": payload["profile_id"],
    }


def _operator_prompt_cli_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "evidence_path": _output_path_contract(payload["evidence_path"], output_dir),
        "evidence_path_exists": Path(payload["evidence_path"]).exists(),
        "profile_id": payload["profile_id"],
        "prompt_path": _output_path_contract(payload["prompt_path"], output_dir),
        "prompt_path_exists": Path(payload["prompt_path"]).exists(),
        "proposal_block_begin": payload["proposal_block_begin"],
        "proposal_block_end": payload["proposal_block_end"],
        "schema_path": _repo_path_contract(payload["schema_path"]),
        "target": payload["target"],
    }


def _analyze_mock_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "attempts": payload["attempts"],
        "evidence_path": _output_path_contract(payload["evidence_path"], output_dir),
        "evidence_path_exists": Path(payload["evidence_path"]).exists(),
        "operator": payload["operator"],
        "operator_run_id": _generated_id_contract(payload["operator_run_id"]),
        "persisted": payload["persisted"],
        "profile_id": payload["profile_id"],
        "prompt_path": _output_path_contract(payload["prompt_path"], output_dir),
        "prompt_path_exists": Path(payload["prompt_path"]).exists(),
        "proposal_id": payload["proposal_id"],
        "proposal_path": _output_path_contract(payload["proposal_path"], output_dir),
        "proposal_path_exists": Path(payload["proposal_path"]).exists(),
        "raw_output_path": payload["raw_output_path"],
    }


def _mcp_install_plan_contract(payload: dict, db_path: Path) -> dict:
    return {
        "command": _mcp_native_install_command_contract(payload["command"], db_path),
        "config": _mcp_config_payload_contract(payload["config"], db_path),
        "config_path_hint": _home_path_tail(payload["config_path_hint"]),
        "notes": payload["notes"],
        "requires_manual_config": payload["requires_manual_config"],
        "server": payload["server"],
        "shell_command_present": bool(payload["shell_command"]),
        "target": payload["target"],
    }


def _mcp_install_contract(payload: dict, output_path: Path, db_path: Path) -> dict:
    return {
        "config": _mcp_config_payload_contract(payload["config"], db_path),
        "output": _output_path_contract(payload["output"], output_path.parent),
        "output_exists": output_path.exists(),
        "server": payload["server"],
        "target": payload["target"],
    }


def _mcp_native_install_command_contract(command: list[str], db_path: Path) -> dict:
    server_args = command[7:]
    return {
        "client_command": command[:4],
        "env_key": command[4],
        "env_repo_path": _repo_path_contract(command[5].split("=", 1)[1]),
        "separator": command[6],
        "server": _mcp_server_command_contract(server_args, db_path),
    }


def _mcp_config_payload_contract(payload: dict, db_path: Path) -> dict:
    server = payload["mcpServers"]["kyoko-dev"]
    return {
        "server_names": sorted(payload["mcpServers"]),
        "target": payload["target"],
        "kyoko-dev": {
            "command_present": bool(server["command"]),
            "env": {"PYTHONPATH": _repo_path_contract(server["env"]["PYTHONPATH"])},
            "server": _mcp_server_command_contract(server["args"], db_path),
        },
    }


def _mcp_server_command_contract(args: list[str], db_path: Path) -> dict:
    command_present = False
    if args and args[0] != "-m":
        command_present = bool(args[0])
        args = args[1:]
    return {
        "command_present": command_present,
        "module_args": args[:4],
        "db_flag": args[4],
        "db_path": _db_path_contract(args[5], db_path),
        "schema_flag": args[6],
        "schema_path": _repo_path_contract(args[7]),
    }


def _home_path_tail(value: str) -> str:
    path = Path(value)
    parts = path.parts
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return str(path)


def _generated_id_contract(value: str) -> dict:
    return {
        "present": bool(value),
        "prefix": str(value).split("_", 1)[0],
        "segments": len(str(value).split("_")),
    }


def _run_detail_agent_contract(agent: dict) -> dict:
    return {
        "external_id": agent["external_id"],
        "id": agent["id"],
        "kind": agent["kind"],
        "metadata": agent["metadata"],
        "model": agent["model"],
        "name": agent["name"],
        "profile_id": agent["profile_id"],
        "role": agent["role"],
        "source_id": agent["source_id"],
        "workspace_path": _fixture_workspace_contract(agent["workspace_path"]),
    }


def _run_detail_handoff_contract(handoff: dict) -> dict:
    return {
        "from_agent_identity_id": handoff["from_agent_identity_id"],
        "from_task_id": handoff["from_task_id"],
        "from_workflow_node_id": handoff["from_workflow_node_id"],
        "id": handoff["id"],
        "kind": handoff["kind"],
        "metadata": handoff["metadata"],
        "payload_ref": handoff["payload_ref"],
        "profile_id": handoff["profile_id"],
        "reason_ref": handoff["reason_ref"],
        "run_id": handoff["run_id"],
        "source_id": handoff["source_id"],
        "span_id": handoff["span_id"],
        "timestamps_present": _timestamps_present(handoff, ("created_at",)),
        "to_agent_identity_id": handoff["to_agent_identity_id"],
        "to_task_id": handoff["to_task_id"],
        "to_workflow_node_id": handoff["to_workflow_node_id"],
    }


def _run_detail_related_proposal_contract(item: dict) -> dict:
    proposal = item["proposal"]
    return {
        "matched_evidence_refs": item["matched_evidence_refs"],
        "proposal": {
            "confidence": proposal["confidence"],
            "id": proposal["id"],
            "section": proposal["section"],
            "state": proposal["state"],
            "summary": proposal["summary"],
            "title": proposal["title"],
            "timestamps_present": _timestamps_present(proposal, ("created_at",)),
        },
    }


def _run_detail_run_contract(run: dict) -> dict:
    return {
        "agent_identity_id": run["agent_identity_id"],
        "external_id": run["external_id"],
        "id": run["id"],
        "input_ref": run["input_ref"],
        "metadata": run["metadata"],
        "output_ref": run["output_ref"],
        "profile_id": run["profile_id"],
        "root_span_id": run["root_span_id"],
        "source_id": run["source_id"],
        "status": run["status"],
        "summary": run["summary"],
        "task_attempt_id": run["task_attempt_id"],
        "timestamps_present": _timestamps_present(run, ("ended_at", "started_at")),
    }


def _run_detail_source_contract(source: dict) -> dict:
    return {
        "adapter_version": source["adapter_version"],
        "capabilities": source["capabilities"],
        "config": source["config"],
        "display_name": source["display_name"],
        "id": source["id"],
        "kind": source["kind"],
        "profile_id": source["profile_id"],
        "status": source["status"],
        "timestamps_present": _timestamps_present(source, ("last_seen_at",)),
    }


def _run_detail_span_contract(span: dict) -> dict:
    return {
        "agent_identity_id": span["agent_identity_id"],
        "attributes": span["attributes"],
        "external_id": span["external_id"],
        "id": span["id"],
        "input_ref": span["input_ref"],
        "kind": span["kind"],
        "name": span["name"],
        "output_ref": span["output_ref"],
        "parent_span_id": span["parent_span_id"],
        "raw_ref": span["raw_ref"],
        "run_id": span["run_id"],
        "source_id": span["source_id"],
        "status": span["status"],
        "timestamps_present": _timestamps_present(span, ("ended_at", "started_at")),
        "usage": span["usage"],
        "workflow_node_id": span["workflow_node_id"],
    }


def _span_tree_node_contract(node: dict) -> dict:
    return {
        **_run_detail_span_contract(node),
        "children": [_span_tree_node_contract(child) for child in node["children"]],
    }


def _run_detail_task_contract(task: dict) -> dict:
    return {
        "assignee_agent_identity_id": task["assignee_agent_identity_id"],
        "body_ref": task["body_ref"],
        "created_by_agent_identity_id": task["created_by_agent_identity_id"],
        "external_id": task["external_id"],
        "id": task["id"],
        "metadata": task["metadata"],
        "priority": task["priority"],
        "profile_id": task["profile_id"],
        "queue_id": task["queue_id"],
        "source_id": task["source_id"],
        "status": task["status"],
        "timestamps_present": _timestamps_present(
            task,
            ("completed_at", "created_at", "started_at"),
        ),
        "title": task["title"],
        "workspace_kind": task["workspace_kind"],
        "workspace_path": _fixture_workspace_contract(task["workspace_path"]),
    }


def _run_detail_task_attempt_contract(attempt: dict) -> dict:
    return {
        "agent_identity_id": attempt["agent_identity_id"],
        "claim_token_hash_present": bool(attempt["claim_token_hash"]),
        "error_ref": attempt["error_ref"],
        "id": attempt["id"],
        "metadata": attempt["metadata"],
        "outcome": attempt["outcome"],
        "run_id": attempt["run_id"],
        "status": attempt["status"],
        "summary_ref": attempt["summary_ref"],
        "task_id": attempt["task_id"],
        "timestamps_present": _timestamps_present(
            attempt,
            ("ended_at", "last_heartbeat_at", "started_at"),
        ),
        "worker_pid_present": attempt["worker_pid"] is not None,
    }


def _run_detail_timeline_event_contract(event: dict) -> dict:
    return {
        "agent_identity_id": event["agent_identity_id"],
        "entity_id": event["entity_id"],
        "entity_type": event["entity_type"],
        "id": event["id"],
        "kind": event["kind"],
        "metadata": event["metadata"],
        "payload_ref": event["payload_ref"],
        "profile_id": event["profile_id"],
        "source_id": event["source_id"],
        "timestamps_present": _timestamps_present(event, ("at",)),
    }


def _operator_adapter_bootstrap_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "registered": [
            _operator_adapter_registration_contract(item, output_dir)
            for item in payload["registered"]
        ],
        "skipped": payload["skipped"],
    }


def _operator_adapters_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "operator_adapters": sorted(
            [
                {
                    "command": adapter["command"],
                    "created_at_present": bool(adapter["created_at"]),
                    "enabled": adapter["enabled"],
                    "id": adapter["id"],
                    "metadata": adapter["metadata"],
                    "name": adapter["name"],
                    "operator_kind": adapter["operator_kind"],
                    "output_dir": _output_path_contract(adapter["output_dir"], output_dir),
                    "profile_id": adapter["profile_id"],
                    "timeout_seconds": adapter["timeout_seconds"],
                    "updated_at_present": bool(adapter["updated_at"]),
                }
                for adapter in payload["operator_adapters"]
            ],
            key=lambda item: item["id"],
        ),
    }


def _operator_adapter_registration_contract(item: dict, output_dir: Path) -> dict:
    return {
        "adapter_id": item["adapter_id"],
        "command": item["command"],
        "enabled": item["enabled"],
        "name": item["name"],
        "operator_kind": item["operator_kind"],
        "output_dir": _output_path_contract(item["output_dir"], output_dir),
        "profile_id": item["profile_id"],
        "timeout_seconds": item["timeout_seconds"],
    }


def _operator_adapter_register_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "adapter_id": payload["adapter_id"],
        "command": _operator_command_contract(payload["command"], output_dir),
        "enabled": payload["enabled"],
        "name": payload["name"],
        "operator_kind": payload["operator_kind"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "profile_id": payload["profile_id"],
        "timeout_seconds": payload["timeout_seconds"],
    }


def _operator_adapter_run_contract(payload: dict, output_dir: Path) -> dict:
    proposal = json.loads(Path(payload["proposal_path"]).read_text(encoding="utf-8"))
    raw_output = Path(payload["raw_output_path"]).read_text(encoding="utf-8")
    return {
        "adapter_id": payload["adapter_id"],
        "artifact_exists": {
            "evidence_path": Path(payload["evidence_path"]).exists(),
            "prompt_path": Path(payload["prompt_path"]).exists(),
            "proposal_path": Path(payload["proposal_path"]).exists(),
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
        },
        "artifact_paths": {
            "evidence_path": _output_path_contract(payload["evidence_path"], output_dir),
            "prompt_path": _output_path_contract(payload["prompt_path"], output_dir),
            "proposal_path": _output_path_contract(payload["proposal_path"], output_dir),
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
        },
        "attempts": payload["attempts"],
        "operator": payload["operator"],
        "operator_run_id_present": bool(payload["operator_run_id"]),
        "persisted": payload["persisted"],
        "profile_id": payload["profile_id"],
        "proposal_file": {
            "id": proposal["id"],
            "producer_name": proposal["producer"]["name"],
            "producer_session_id": proposal["producer"]["session_id"],
            "section": proposal["section"],
        },
        "proposal_id": payload["proposal_id"],
        "raw_output_contract": {
            "contains_begin_marker": "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" in raw_output,
            "contains_done_marker": "Done." in raw_output,
            "contains_end_marker": "END_KYOKO_LEARNING_PROPOSAL_JSON" in raw_output,
        },
    }


def _operator_runs_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "operator_runs": [
            _operator_run_contract(run, output_dir)
            for run in payload["operator_runs"]
        ],
    }


def _operator_run_contract(run: dict, output_dir: Path) -> dict:
    metadata = run["metadata"]
    return {
        "adapter_id": run["adapter_id"],
        "attempt_count": run["attempt_count"],
        "error": run["error"],
        "failure_kind": run["failure_kind"],
        "id_present": bool(run["id"]),
        "last_attempt_status": run["last_attempt_status"],
        "max_retries": run["max_retries"],
        "metadata": {
            "attempt_results": [
                {
                    "attempt": attempt["attempt"],
                    "error": attempt["error"],
                    "prompt_path": _output_path_contract(attempt["prompt_path"], output_dir),
                    "returncode": attempt["returncode"],
                    "status": attempt["status"],
                    "stderr_chars": attempt["stderr_chars"],
                    "stdout_chars_positive": attempt["stdout_chars"] > 0,
                }
                for attempt in metadata["attempt_results"]
            ],
            "attempts": metadata["attempts"],
            "command": _operator_command_contract(metadata["command"], output_dir),
            "max_retries": metadata["max_retries"],
            "schema_path": _repo_path_contract(metadata["schema_path"]),
        },
        "operator_kind": run["operator_kind"],
        "operator_label": run["operator_label"],
        "path_refs": {
            "evidence_ref": _output_path_contract(run["evidence_ref"], output_dir),
            "prompt_ref": _output_path_contract(run["prompt_ref"], output_dir),
            "raw_output_ref": _output_path_contract(run["raw_output_ref"], output_dir),
        },
        "profile_id": run["profile_id"],
        "proposal_id": run["proposal_id"],
        "status": run["status"],
        "timestamps_present": {
            "created_at": bool(run["created_at"]),
            "ended_at": bool(run["ended_at"]),
            "started_at": bool(run["started_at"]),
            "updated_at": bool(run["updated_at"]),
        },
    }


def _operator_command_contract(command: list[str], output_dir: Path) -> list[str]:
    contracted = []
    for arg in command:
        if arg == sys.executable:
            contracted.append("<PYTHON>")
        else:
            repo_path = _repo_path_contract(arg)
            contracted.append(_output_path_contract(repo_path, output_dir))
    return contracted


def _replay_adapter_register_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "adapter_id": payload["adapter_id"],
        "allow_remote_server": payload["allow_remote_server"],
        "command": _operator_command_contract(payload["command"], output_dir),
        "cwd": payload["cwd"],
        "default_mode": payload["default_mode"],
        "default_side_effect_mode": payload["default_side_effect_mode"],
        "enabled": payload["enabled"],
        "health_path": payload["health_path"],
        "kind": payload["kind"],
        "name": payload["name"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "profile_id": payload["profile_id"],
        "replay_path": payload["replay_path"],
        "server_url": payload["server_url"],
        "startup_timeout_seconds": payload["startup_timeout_seconds"],
        "timeout_seconds": payload["timeout_seconds"],
    }


def _replay_adapters_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "replay_adapters": [
            {
                "command": _operator_command_contract(adapter["command"], output_dir),
                "created_at_present": bool(adapter["created_at"]),
                "default_mode": adapter["default_mode"],
                "default_side_effect_mode": adapter["default_side_effect_mode"],
                "allow_remote_server": adapter["allow_remote_server"],
                "enabled": adapter["enabled"],
                "id": adapter["id"],
                "kind": adapter["kind"],
                "metadata": adapter["metadata"],
                "name": adapter["name"],
                "output_dir": _output_path_contract(adapter["output_dir"], output_dir),
                "profile_id": adapter["profile_id"],
                "timeout_seconds": adapter["timeout_seconds"],
                "updated_at_present": bool(adapter["updated_at"]),
            }
            for adapter in payload["replay_adapters"]
        ],
    }


def _replay_adapter_run_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "adapter_id": payload["adapter_id"],
        "artifact_exists": {
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
            "request_path": Path(payload["request_path"]).exists(),
            "result_path": Path(payload["result_path"]).exists(),
        },
        "artifact_paths": {
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
            "request_path": _output_path_contract(payload["request_path"], output_dir),
            "result_path": _output_path_contract(payload["result_path"], output_dir),
        },
        "check_run": {
            "check_run_id": payload["check_run"]["check_run_id"],
            "promoted_trust_level": payload["check_run"]["promoted_trust_level"],
            "result": payload["check_run"]["result"],
            "status": payload["check_run"]["status"],
        },
        "check_spec_id": payload["check_spec_id"],
        "output_run_id": payload["output_run_id"],
        "profile_id": payload["profile_id"],
        "replay_run_id": payload["replay_run_id"],
        "result": {
            "actual_side_effect_mode": payload["result"]["actual_side_effect_mode"],
            "executed_agent": payload["result"]["executed_agent"],
            "mode": payload["result"]["mode"],
            "output_run_id": payload["result"]["output_run_id"],
            "requested_side_effect_mode": payload["result"]["requested_side_effect_mode"],
            "source_run_id": payload["result"]["source_run_id"],
            "target_map": payload["result"]["target_map"],
        },
        "status": payload["status"],
    }


def _replay_contract(payload: dict) -> dict:
    return {
        "check_spec_id": payload["check_spec_id"],
        "mode": payload["mode"],
        "profile_id": payload["profile_id"],
        "proposal_id": payload["proposal_id"],
        "replay_run_id": payload["replay_run_id"],
        "result": _replay_result_contract(payload["result"]),
        "side_effect_mode": payload["side_effect_mode"],
        "source_run_id": payload["source_run_id"],
        "status": payload["status"],
    }


def _complete_replay_contract(payload: dict) -> dict:
    return {
        "check_spec_id": payload["check_spec_id"],
        "ingested_counts": payload["ingested_counts"],
        "output_run_id": payload["output_run_id"],
        "profile_id": payload["profile_id"],
        "replay_run_id": payload["replay_run_id"],
        "result": _replay_result_contract(payload["result"]),
        "status": payload["status"],
    }


def _replay_command_contract(payload: dict, output_dir: Path) -> dict:
    raw_output = Path(payload["raw_output_path"]).read_text(encoding="utf-8")
    return {
        "artifact_exists": {
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
            "request_path": Path(payload["request_path"]).exists(),
            "result_path": Path(payload["result_path"]).exists(),
        },
        "artifact_paths": {
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
            "request_path": _output_path_contract(payload["request_path"], output_dir),
            "result_path": _output_path_contract(payload["result_path"], output_dir),
        },
        "check_run": {
            "check_run_id": payload["check_run"]["check_run_id"],
            "promoted_trust_level": payload["check_run"]["promoted_trust_level"],
            "result": _check_result_contract(payload["check_run"]["result"]),
            "status": payload["check_run"]["status"],
        },
        "check_spec_id": payload["check_spec_id"],
        "output_run_id": payload["output_run_id"],
        "profile_id": payload["profile_id"],
        "raw_output_contract": {
            "contains_begin_marker": "BEGIN_KYOKO_REPLAY_RESULT_JSON" in raw_output,
            "contains_done_marker": "Done." in raw_output,
            "contains_end_marker": "END_KYOKO_REPLAY_RESULT_JSON" in raw_output,
            "contains_result_schema": "kyoko.replay_result.v1" in raw_output,
        },
        "replay_run_id": payload["replay_run_id"],
        "result": _replay_result_contract(payload["result"]),
        "status": payload["status"],
    }


def _judge_command_contract(payload: dict, output_dir: Path) -> dict:
    raw_output = Path(payload["raw_output_path"]).read_text(encoding="utf-8")
    return {
        "artifact_exists": {
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
            "request_path": Path(payload["request_path"]).exists(),
            "result_path": Path(payload["result_path"]).exists(),
        },
        "artifact_paths": {
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
            "request_path": _output_path_contract(payload["request_path"], output_dir),
            "result_path": _output_path_contract(payload["result_path"], output_dir),
        },
        "check_run": {
            "check_run_id": payload["check_run"]["check_run_id"],
            "promoted_trust_level": payload["check_run"]["promoted_trust_level"],
            "result": _judge_check_result_contract(payload["check_run"]["result"]),
            "status": payload["check_run"]["status"],
        },
        "check_spec_id": payload["check_spec_id"],
        "judgment": {
            "backend": payload["judgment"]["backend"],
            "judge": payload["judgment"]["judge"],
            "judge_backend": payload["judgment"]["judge_backend"],
            "score": payload["judgment"]["score"],
            "verdict": payload["judgment"]["verdict"],
        },
        "profile_id": payload["profile_id"],
        "proposal_id": payload["proposal_id"],
        "raw_output_contract": {
            "contains_begin_marker": "BEGIN_KYOKO_JUDGE_RESULT_JSON" in raw_output,
            "contains_end_marker": "END_KYOKO_JUDGE_RESULT_JSON" in raw_output,
            "contains_result_schema": "kyoko.judge_result.v1" in raw_output,
        },
    }


def _judge_check_result_contract(result: dict) -> dict:
    return {
        "assertion_counts": result["assertion_counts"],
        "assertions": [_check_assertion_contract(assertion) for assertion in result["assertions"]],
        "comparison": result["comparison"],
        "check_type": result["check_type"],
        "gateable": result["gateable"],
        "judge": result["judge"],
        "judge_backend": result["judge_backend"],
        "reason": result["reason"],
        "score": result["score"],
        "target": result["target"],
        "verdict": result["verdict"],
    }


def _judge_smoke_contract(payload: dict, output_dir: Path) -> dict:
    raw_output = Path(payload["raw_output_path"]).read_text(encoding="utf-8")
    handoff = json.loads(Path(payload["handoff_path"]).read_text(encoding="utf-8"))
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "handoff_path": Path(payload["handoff_path"]).exists(),
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
            "request_path": Path(payload["request_path"]).exists(),
            "result_path": Path(payload["result_path"]).exists(),
        },
        "artifact_paths": {
            "db_path": _output_path_contract(payload["db_path"], output_dir),
            "handoff_path": _output_path_contract(payload["handoff_path"], output_dir),
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
            "request_path": _output_path_contract(payload["request_path"], output_dir),
            "result_path": _output_path_contract(payload["result_path"], output_dir),
        },
        "command": _operator_command_contract(payload["command"], output_dir),
        "check_run_id": payload["check_run_id"],
        "check_spec_id": payload["check_spec_id"],
        "check_status": payload["check_status"],
        "external_command_invoked": payload["external_command_invoked"],
        "external_model_invoked": payload["external_model_invoked"],
        "handoff": {
            "artifact_keys": sorted(handoff["artifacts"]),
            "command": _operator_command_contract(handoff["command"], output_dir),
            "environment_keys": sorted(handoff["environment"]),
            "external_model_invoked": handoff["external_model_invoked"],
            "prepare_only": handoff["prepare_only"],
            "provider_backed": handoff["provider_backed"],
            "schema_version": handoff["schema_version"],
        },
        "judgment": {
            "backend": payload["judgment"]["backend"],
            "judge": payload["judgment"]["judge"],
            "judge_backend": payload["judgment"]["judge_backend"],
            "score": payload["judgment"]["score"],
            "verdict": payload["judgment"]["verdict"],
        },
        "kind": payload["kind"],
        "passed": payload["passed"],
        "prepare_only": payload["prepare_only"],
        "profile_id": payload["profile_id"],
        "promoted_trust_level": payload["promoted_trust_level"],
        "proposal_created": payload["proposal_created"],
        "proposal_id": payload["proposal_id"],
        "provider_backed": payload["provider_backed"],
        "raw_output_contract": {
            "contains_begin_marker": "BEGIN_KYOKO_JUDGE_RESULT_JSON" in raw_output,
            "contains_end_marker": "END_KYOKO_JUDGE_RESULT_JSON" in raw_output,
            "contains_result_schema": "kyoko.judge_result.v1" in raw_output,
        },
        "used_demo_database": payload["used_demo_database"],
    }


def _source_adapter_template_contract(payload: dict, output_path: Path) -> dict:
    template = output_path.read_text(encoding="utf-8")
    return {
        "artifact_exists": {
            "output_path": output_path.exists(),
            "output_path_executable": bool(output_path.stat().st_mode & 0o111),
        },
        "framework": payload["framework"],
        "output_path": _output_path_contract(payload["output_path"], output_path.parent),
        "profile_name": payload["profile_name"],
        "template_contract": {
            "contains_canonical_schema_marker": "kyoko.source_events.v1" in template,
            "contains_framework": 'FRAMEWORK = "langgraph-python"' in template,
            "contains_hook_env": "KYOKO_SOURCE_HOOK" in template,
            "contains_output_argument": "--output" in template,
            "contains_post_url_argument": "--post-url" in template,
            "contains_profile_name": 'PROFILE_NAME = "news-research"' in template,
        },
        "wrote": payload["wrote"],
    }


def _integration_smoke_source_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "adapter_path": _output_or_outside_path_contract(payload["adapter_path"], output_dir),
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "source_events_path": Path(payload["source_events_path"]).exists(),
            "stderr_path": Path(payload["stderr_path"]).exists(),
            "stdout_path": Path(payload["stdout_path"]).exists(),
        },
        "db_path": _outside_path_contract(payload["db_path"], output_dir),
        "exit_code": payload["exit_code"],
        "hook": _hook_contract(payload["hook"], output_dir),
        "ingested_counts": payload["ingested_counts"],
        "kind": payload["kind"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "paths": {
            "source_events_path": _output_path_contract(
                payload["source_events_path"],
                output_dir,
            ),
            "stderr_path": _output_path_contract(payload["stderr_path"], output_dir),
            "stdout_path": _output_path_contract(payload["stdout_path"], output_dir),
        },
        "profile_id": payload["profile_id"],
        "status": {
            "counts": payload["status"]["counts"],
            "db_path": _outside_path_contract(payload["status"]["db_path"], output_dir),
            "schema_version": payload["status"]["schema_version"],
        },
    }


def _integration_smoke_framework_source_contract(payload: dict, output_dir: Path) -> dict:
    status_counts = payload["status"]["counts"]
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "source_adapter_path": Path(payload["source_adapter_path"]).exists(),
            "source_hook_path": Path(payload["source_hook_path"]).exists(),
        },
        "db_path": _outside_path_contract(payload["db_path"], output_dir),
        "external_model_invoked": payload["external_model_invoked"],
        "flags": {
            "generated_source_adapter_invoked": payload["generated_source_adapter_invoked"],
            "installed_framework_invoked": payload["installed_framework_invoked"],
            "live_operator_invoked": payload["live_operator_invoked"],
        },
        "framework": payload["framework"],
        "framework_package": payload["framework_package"],
        "framework_version": payload["framework_version"],
        "kind": payload["kind"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "paths": {
            "source_adapter_path": _output_path_contract(payload["source_adapter_path"], output_dir),
            "source_hook_path": _output_path_contract(payload["source_hook_path"], output_dir),
            "workspace_root": _output_path_contract(payload["workspace_root"], output_dir),
        },
        "python_executable": (
            "<PYTHON>" if payload["python_executable"] == sys.executable else payload["python_executable"]
        ),
        "source_smoke": _integration_smoke_source_contract(payload["source_smoke"], output_dir),
        "status_counts": {
            "agent_identities": status_counts["agent_identities"],
            "runs": status_counts["runs"],
            "sources": status_counts["sources"],
            "spans": status_counts["spans"],
            "workflow_nodes": status_counts["workflow_nodes"],
        },
    }


def _integration_smoke_framework_replay_contract(payload: dict, output_dir: Path) -> dict:
    server_url = payload["replay_server_url"]
    return {
        "artifact_exists": {
            "replay_hook_path": Path(payload["replay_hook_path"]).exists(),
            "replay_server_path": Path(payload["replay_server_path"]).exists(),
        },
        "external_model_invoked": payload["external_model_invoked"],
        "flags": {
            "generated_replay_server_invoked": payload["generated_replay_server_invoked"],
            "installed_framework_invoked": payload["installed_framework_invoked"],
            "live_operator_invoked": payload["live_operator_invoked"],
        },
        "framework": payload["framework"],
        "framework_package": payload["framework_package"],
        "framework_version": payload["framework_version"],
        "kind": payload["kind"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "paths": {
            "replay_hook_path": _output_path_contract(payload["replay_hook_path"], output_dir),
            "replay_server_path": _output_path_contract(payload["replay_server_path"], output_dir),
            "workspace_root": _output_path_contract(payload["workspace_root"], output_dir),
        },
        "python_executable": (
            "<PYTHON>" if payload["python_executable"] == sys.executable else payload["python_executable"]
        ),
        "replay_server_url": _server_url_contract(server_url, server_url),
        "replay_smoke": _integration_smoke_replay_server_contract(
            payload["replay_smoke"],
            output_dir,
            server_url,
        ),
    }


def _integration_smoke_replay_server_contract(
    payload: dict,
    output_dir: Path,
    server_url: str,
) -> dict:
    logs = payload["logs"]
    return {
        "artifact_exists": {
            "state_path": Path(payload["state_path"]).exists(),
            "stderr_path": Path(payload["stderr_path"]).exists(),
            "stdout_path": Path(payload["stdout_path"]).exists(),
        },
        "command": _integration_smoke_command_contract(
            payload["command"],
            output_dir,
            server_url,
        ),
        "health": _replay_server_health_contract(payload["health"], server_url),
        "health_path": payload["health_path"],
        "healthy": payload["healthy"],
        "kind": payload["kind"],
        "logs": {
            "max_bytes": logs["max_bytes"],
            "paths": {
                "stderr_path": _output_path_contract(logs["stderr_path"], output_dir),
                "stdout_path": _output_path_contract(logs["stdout_path"], output_dir),
            },
            "stderr": logs["stderr"],
            "stderr_truncated": logs["stderr_truncated"],
            "stdout_contract": {
                "stdout_present": bool(logs["stdout"]),
            },
            "stdout_truncated": logs["stdout_truncated"],
        },
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "paths": {
            "state_path": _output_path_contract(payload["state_path"], output_dir),
            "stderr_path": _output_path_contract(payload["stderr_path"], output_dir),
            "stdout_path": _output_path_contract(payload["stdout_path"], output_dir),
        },
        "pid_present": bool(payload["pid"]),
        "replay_ok": payload["replay_ok"],
        "replay_path": payload["replay_path"],
        "replay_request": payload["replay_request"],
        "replay_response": payload["replay_response"],
        "server_url": _server_url_contract(payload["server_url"], server_url),
        "started": payload["started"],
        "stopped": payload["stopped"],
    }


def _integration_smoke_improve_contract(payload: dict, output_dir: Path) -> dict:
    server_url = payload["replay_server_url"]
    replay_adapter = payload["replay_adapter"]
    status_counts = payload["status"]["counts"]
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "replay_hook_path": Path(payload["replay_hook_path"]).exists(),
            "replay_server_path": Path(payload["replay_server_path"]).exists(),
            "source_adapter_path": Path(payload["source_adapter_path"]).exists(),
            "source_hook_path": Path(payload["source_hook_path"]).exists(),
        },
        "db_path": _outside_path_contract(payload["db_path"], output_dir),
        "external_model_invoked": payload["external_model_invoked"],
        "flags": {
            "generated_source_adapter_invoked": payload["generated_source_adapter_invoked"],
            "live_operator_invoked": payload["live_operator_invoked"],
            "managed_replay_server_invoked": payload["managed_replay_server_invoked"],
        },
        "framework": payload["framework"],
        "improve": _improve_contract(payload["improve"]),
        "kind": payload["kind"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "paths": {
            "replay_hook_path": _output_path_contract(payload["replay_hook_path"], output_dir),
            "replay_server_path": _output_path_contract(payload["replay_server_path"], output_dir),
            "source_adapter_path": _output_path_contract(payload["source_adapter_path"], output_dir),
            "source_hook_path": _output_path_contract(payload["source_hook_path"], output_dir),
            "workspace_root": _output_path_contract(payload["workspace_root"], output_dir),
        },
        "replay_adapter": {
            "adapter_id": replay_adapter["adapter_id"],
            "command": _replay_server_command_contract(
                replay_adapter["command"],
                output_dir,
                server_url,
            ),
            "default_mode": replay_adapter["default_mode"],
            "default_side_effect_mode": replay_adapter["default_side_effect_mode"],
            "enabled": replay_adapter["enabled"],
            "health_path": replay_adapter["health_path"],
            "kind": replay_adapter["kind"],
            "name": replay_adapter["name"],
            "output_dir": _output_path_contract(replay_adapter["output_dir"], output_dir),
            "profile_id": replay_adapter["profile_id"],
            "replay_path": replay_adapter["replay_path"],
            "server_url": _server_url_contract(replay_adapter["server_url"], server_url),
            "startup_timeout_seconds": replay_adapter["startup_timeout_seconds"],
            "timeout_seconds": replay_adapter["timeout_seconds"],
        },
        "replay_adapter_id": payload["replay_adapter_id"],
        "replay_server_url": _server_url_contract(server_url, server_url),
        "source_smoke": _integration_smoke_source_contract(payload["source_smoke"], output_dir),
        "status_counts": {
            "check_runs": status_counts["check_runs"],
            "check_specs": status_counts["check_specs"],
            "learning_proposals": status_counts["learning_proposals"],
            "operator_runs": status_counts["operator_runs"],
            "replay_adapters": status_counts["replay_adapters"],
            "replay_runs": status_counts["replay_runs"],
            "runs": status_counts["runs"],
            "skills": status_counts["skills"],
            "sources": status_counts["sources"],
            "spans": status_counts["spans"],
        },
    }


def _integration_smoke_framework_improve_contract(payload: dict, output_dir: Path) -> dict:
    contract = _integration_smoke_improve_contract(payload, output_dir)
    contract["framework_package"] = payload["framework_package"]
    contract["framework_version"] = payload["framework_version"]
    contract["installed_framework_flags"] = {
        "installed_framework_invoked": payload["installed_framework_invoked"],
        "installed_framework_source_invoked": payload["installed_framework_source_invoked"],
        "installed_framework_replay_invoked": payload["installed_framework_replay_invoked"],
        "generated_replay_server_invoked": payload["generated_replay_server_invoked"],
    }
    contract["python_executable"] = (
        "<PYTHON>" if payload["python_executable"] == sys.executable else payload["python_executable"]
    )
    replay_adapter = payload["replay_adapter"]
    contract["replay_adapter"]["cwd"] = _output_path_contract(replay_adapter["cwd"], output_dir)
    return contract


def _integration_smoke_opentelemetry_contract(payload: dict, output_dir: Path) -> dict:
    status_counts = payload["status"]["counts"]
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "normalized_path": Path(payload["normalized_path"]).exists(),
            "otlp_payload_path": Path(payload["otlp_payload_path"]).exists(),
            "script_path": Path(payload["script_path"]).exists(),
            "stderr_path": Path(payload["stderr_path"]).exists(),
            "stdout_path": Path(payload["stdout_path"]).exists(),
        },
        "db_path": _outside_path_contract(payload["db_path"], output_dir),
        "external_model_invoked": payload["external_model_invoked"],
        "ingested_counts": payload["ingested_counts"],
        "kind": payload["kind"],
        "live_operator_invoked": payload["live_operator_invoked"],
        "opentelemetry_sdk_invoked": payload["opentelemetry_sdk_invoked"],
        "opentelemetry_sdk_version": payload["opentelemetry_sdk_version"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "paths": {
            "normalized_path": _output_path_contract(payload["normalized_path"], output_dir),
            "otlp_payload_path": _output_path_contract(payload["otlp_payload_path"], output_dir),
            "script_path": _output_path_contract(payload["script_path"], output_dir),
            "stderr_path": _output_path_contract(payload["stderr_path"], output_dir),
            "stdout_path": _output_path_contract(payload["stdout_path"], output_dir),
            "workspace_root": _output_path_contract(payload["workspace_root"], output_dir),
        },
        "profile_id": payload["profile_id"],
        "python_executable": (
            "<PYTHON>" if payload["python_executable"] == sys.executable else payload["python_executable"]
        ),
        "run_count": len(payload["run_ids"]),
        "span_count": len(payload["span_ids"]),
        "status_counts": {
            "agent_identities": status_counts["agent_identities"],
            "profiles": status_counts["profiles"],
            "runs": status_counts["runs"],
            "sources": status_counts["sources"],
            "spans": status_counts["spans"],
            "timeline_events": status_counts["timeline_events"],
            "workflow_nodes": status_counts["workflow_nodes"],
        },
    }


def _replay_server_template_contract(payload: dict, output_path: Path) -> dict:
    template = output_path.read_text(encoding="utf-8")
    return {
        "artifact_exists": {
            "output_path": output_path.exists(),
            "output_path_executable": bool(output_path.stat().st_mode & 0o111),
        },
        "framework": payload["framework"],
        "output_path": _output_path_contract(payload["output_path"], output_path.parent),
        "profile_name": payload["profile_name"],
        "template_contract": {
            "contains_framework": "FRAMEWORK = \"langgraph-python\"" in template,
            "contains_health_handler": "def do_GET" in template and "/health" in template,
            "contains_profile_name": "PROFILE_NAME = \"news-research\"" in template,
            "contains_replay_handler": "def do_POST" in template and "/replay" in template,
            "contains_replay_hook_env": "KYOKO_REPLAY_HOOK" in template,
            "contains_result_schema": "kyoko.replay_result.v1" in template,
        },
        "wrote": payload["wrote"],
    }


def _replay_server_health_contract(payload: dict, server_url: str) -> dict:
    return {
        "health_path": payload["health_path"],
        "ok": payload["ok"],
        "response": payload["response"],
        "server_url": _server_url_contract(payload["server_url"], server_url),
    }


def _replay_server_run_contract(payload: dict, server_url: str) -> dict:
    return {
        "adapter_id": payload["adapter_id"],
        "check_run": {
            "check_run_id": payload["check_run"]["check_run_id"],
            "promoted_trust_level": payload["check_run"]["promoted_trust_level"],
            "result": _check_result_contract(payload["check_run"]["result"]),
            "status": payload["check_run"]["status"],
        },
        "check_spec_id": payload["check_spec_id"],
        "health": _replay_server_health_contract(payload["health"], server_url),
        "output_run_id": payload["output_run_id"],
        "profile_id": payload["profile_id"],
        "replay_path": payload["replay_path"],
        "replay_run_id": payload["replay_run_id"],
        "result": _replay_result_contract(payload["result"]),
        "server_url": _server_url_contract(payload["server_url"], server_url),
        "status": payload["status"],
    }


def _replay_server_process_contract(payload: dict, output_dir: Path, server_url: str) -> dict:
    health = payload["health"]
    return {
        "adapter_id": payload["adapter_id"],
        "artifact_exists": {
            "state_path": Path(payload["state_path"]).exists(),
            "stderr_path": Path(payload["stderr_path"]).exists(),
            "stdout_path": Path(payload["stdout_path"]).exists(),
        },
        "command": _replay_server_command_contract(payload["command"], output_dir, server_url),
        "error": payload["error"],
        "health": _replay_server_health_contract(health, server_url) if health else None,
        "health_path": payload["health_path"],
        "healthy": payload["healthy"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "paths": {
            "state_path": _output_path_contract(payload["state_path"], output_dir),
            "stderr_path": _output_path_contract(payload["stderr_path"], output_dir),
            "stdout_path": _output_path_contract(payload["stdout_path"], output_dir),
        },
        "pid_present": bool(payload["pid"]),
        "running": payload["running"],
        "server_url": _server_url_contract(payload["server_url"], server_url),
        "started": payload["started"],
        "stopped": payload["stopped"],
    }


def _replay_server_logs_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "adapter_id": payload["adapter_id"],
        "max_bytes": payload["max_bytes"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "paths": {
            "stderr_path": _output_path_contract(payload["stderr_path"], output_dir),
            "stdout_path": _output_path_contract(payload["stdout_path"], output_dir),
        },
        "stderr": payload["stderr"],
        "stderr_truncated": payload["stderr_truncated"],
        "stdout_contract": {
            "contains_listening_marker": "kyoko fixture replay server listening"
            in payload["stdout"],
            "stdout_present": bool(payload["stdout"]),
        },
        "stdout_truncated": payload["stdout_truncated"],
    }


def _replay_server_command_contract(
    command: list[str],
    output_dir: Path,
    server_url: str,
) -> list[str]:
    port = server_url.rsplit(":", 1)[-1]
    contracted = []
    for arg in _operator_command_contract(command, output_dir):
        if arg == port:
            contracted.append("<PORT>")
        else:
            contracted.append(arg)
    return contracted


def _integration_smoke_command_contract(
    command: list[str],
    output_dir: Path,
    server_url: str,
) -> list[str]:
    port = server_url.rsplit(":", 1)[-1]
    contracted = []
    for arg in command:
        if arg == sys.executable:
            contracted.append("<PYTHON>")
        elif arg == port:
            contracted.append("<PORT>")
        elif arg.startswith("-"):
            contracted.append(arg)
        else:
            repo_path = _repo_path_contract(arg)
            contracted.append(_outside_path_contract(repo_path, output_dir))
    return contracted


def _hook_contract(value: str, output_dir: Path) -> str:
    module_ref, separator, function_name = value.rpartition(":")
    if not separator:
        return value
    return f"{_output_or_outside_path_contract(module_ref, output_dir)}:{function_name}"


def _server_url_contract(value: str, server_url: str) -> str:
    if value == server_url:
        return "<SERVER_URL>"
    return value


def _generate_checks_contract(payload: dict) -> dict:
    return {
        "check_spec_ids": payload["check_spec_ids"],
        "existing_check_spec_ids": payload["existing_check_spec_ids"],
        "profile_id": payload["profile_id"],
        "proposal_id": payload["proposal_id"],
    }


def _checks_contract(payload: dict) -> dict:
    return {
        "check_specs": [_check_spec_contract(spec) for spec in payload["check_specs"]],
        "check_runs": [_check_run_contract(run) for run in payload["check_runs"]],
        "replay_runs": [_replay_run_contract(run) for run in payload["replay_runs"]],
    }


def _run_check_contract(payload: dict) -> dict:
    return {
        "check_run_id": payload["check_run_id"],
        "check_spec_id": payload["check_spec_id"],
        "profile_id": payload["profile_id"],
        "promoted_trust_level": payload["promoted_trust_level"],
        "proposal_id": payload["proposal_id"],
        "replay_run_id": payload["replay_run_id"],
        "result": _check_result_contract(payload["result"]),
        "status": payload["status"],
    }


def _check_detail_contract(payload: dict) -> dict:
    return {
        "counts": {
            "check_runs": len(payload["check_runs"]),
            "replay_runs": len(payload["replay_runs"]),
            "timeline_events": len(payload["timeline_events"]),
        },
        "check_runs": [_check_run_contract(run) for run in payload["check_runs"]],
        "check_spec": _check_spec_contract(payload["check_spec"]),
        "latest_check_run": _check_run_contract(payload["latest_check_run"]),
        "latest_replay_run": _replay_run_contract(payload["latest_replay_run"]),
        "proposal": _check_detail_proposal_contract(payload["proposal"]),
        "replay_runs": [_replay_run_contract(run) for run in payload["replay_runs"]],
        "source_run": _check_detail_source_run_contract(payload["source_run"]),
        "summary": _check_detail_summary_contract(payload["summary"]),
        "target": _check_detail_target_contract(payload["target"]),
        "timeline_events": sorted(
            [
                {
                    "agent_identity_id": event["agent_identity_id"],
                    "entity_id": event["entity_id"],
                    "entity_type": event["entity_type"],
                    "kind": event["kind"],
                    "metadata": event["metadata"],
                    "profile_id": event["profile_id"],
                    "source_id": event["source_id"],
                }
                for event in payload["timeline_events"]
            ],
            key=lambda event: (event["kind"], event["entity_type"], event["entity_id"]),
        ),
    }


def _check_locks_contract(payload: dict) -> dict:
    return {
        "check_locks": [
            {
                "check_spec_id": lock["check_spec_id"],
                "human_locked": lock["human_locked"],
                "profile_id": lock["profile_id"],
                "reason": lock["reason"],
                "timestamps_present": _timestamps_present(
                    lock,
                    ("created_at", "updated_at"),
                ),
            }
            for lock in payload["check_locks"]
        ],
    }


def _replay_detail_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "artifacts": [
            _replay_detail_artifact_contract(artifact, output_dir)
            for artifact in payload["artifacts"]
        ],
        "counts": {
            "artifacts": len(payload["artifacts"]),
            "check_runs": len(payload["check_runs"]),
            "output_spans": len(payload["output_spans"]),
            "source_spans": len(payload["source_spans"]),
            "timeline_events": len(payload["timeline_events"]),
        },
        "check_runs": [_check_run_contract(run) for run in payload["check_runs"]],
        "check_spec": _check_spec_contract(payload["check_spec"]),
        "output_run": _check_detail_source_run_contract(payload["output_run"]),
        "output_spans": [_span_contract(span) for span in payload["output_spans"]],
        "proposal": _check_detail_proposal_contract(payload["proposal"]),
        "replay_run": _replay_detail_run_contract(payload["replay_run"], output_dir),
        "source_run": _check_detail_source_run_contract(payload["source_run"]),
        "source_spans": [_span_contract(span) for span in payload["source_spans"]],
        "summary": payload["summary"],
        "timeline_events": sorted(
            [
                {
                    "agent_identity_id": event["agent_identity_id"],
                    "entity_id": event["entity_id"],
                    "entity_type": event["entity_type"],
                    "kind": event["kind"],
                    "metadata": event["metadata"],
                    "profile_id": event["profile_id"],
                    "source_id": event["source_id"],
                }
                for event in payload["timeline_events"]
            ],
            key=lambda event: (event["kind"], event["entity_type"], event["entity_id"]),
        ),
    }


def _replay_detail_artifact_contract(artifact: dict, output_dir: Path) -> dict:
    preview = artifact.get("preview") or ""
    return {
        "exists": artifact["exists"],
        "kind": artifact["kind"],
        "media_type": artifact["media_type"],
        "path": _output_path_contract(artifact["path"], output_dir),
        "preview_contract": {
            "contains_replay_result_begin": "BEGIN_KYOKO_REPLAY_RESULT_JSON" in preview,
            "contains_replay_result_end": "END_KYOKO_REPLAY_RESULT_JSON" in preview,
            "contains_replay_result_schema": "kyoko.replay_result.v1" in preview,
            "contains_replay_run_id": "replay_check_proposal_context_timeout_001_1_001" in preview,
            "contains_replay_target_map": "span_fetch_retry_success_001" in preview,
            "contains_request_schema": "kyoko.replay_request.v1" in preview,
            "preview_present": bool(preview),
            "preview_truncated": artifact["preview_truncated"],
            "size_bytes_positive": artifact["size_bytes"] > 0,
        },
    }


def _replay_detail_run_contract(run: dict, output_dir: Path) -> dict:
    return {
        "artifact_refs": [
            {
                "kind": ref["kind"],
                "media_type": ref["media_type"],
                "path": _output_path_contract(ref["path"], output_dir),
            }
            for ref in run["artifact_refs"]
        ],
        "check_spec_id": run["check_spec_id"],
        "id": run["id"],
        "input_ref": run["input_ref"],
        "mode": run["mode"],
        "output_ref": run["output_ref"],
        "profile_id": run["profile_id"],
        "proposal_id": run["proposal_id"],
        "result": _replay_result_contract(run["result"]),
        "side_effect_mode": run["side_effect_mode"],
        "source_run_id": run["source_run_id"],
        "status": run["status"],
        "task_attempt_id": run["task_attempt_id"],
        "timestamps_present": _timestamps_present(
            run,
            ("created_at", "ended_at", "started_at", "updated_at"),
        ),
    }


def _check_spec_contract(spec: dict) -> dict:
    return {
        "definition": _check_definition_contract(spec["definition"]),
        "check_type": spec["check_type"],
        "human_lock_reason": spec["human_lock_reason"],
        "human_locked": spec["human_locked"],
        "id": spec["id"],
        "name": spec["name"],
        "profile_id": spec["profile_id"],
        "proposal_id": spec["proposal_id"],
        "side_effect_mode": spec["side_effect_mode"],
        "status": spec["status"],
        "target": spec["target"],
        "timestamps_present": _timestamps_present(spec, ("created_at", "updated_at")),
        "trust_level": spec["trust_level"],
    }


def _check_definition_contract(definition: dict) -> dict:
    return {
        "assertion": definition["assertion"],
        "assertions": definition["assertions"],
        "evidence_refs": definition["evidence_refs"],
        "failure_statuses": definition["failure_statuses"],
        "operator_definition": definition["operator_definition"],
        "proposal_summary": definition["proposal_summary"],
        "proposal_title": definition["proposal_title"],
    }


def _check_run_contract(run: dict) -> dict:
    return {
        "artifact_refs": run["artifact_refs"],
        "check_spec_id": run["check_spec_id"],
        "id": run["id"],
        "profile_id": run["profile_id"],
        "proposal_id": run["proposal_id"],
        "replay_run_id": run["replay_run_id"],
        "result": _check_result_contract(run["result"]),
        "status": run["status"],
        "timestamps_present": _timestamps_present(
            run,
            ("created_at", "ended_at", "started_at", "updated_at"),
        ),
    }


def _replay_run_contract(run: dict) -> dict:
    return {
        "artifact_refs": run["artifact_refs"],
        "check_spec_id": run["check_spec_id"],
        "id": run["id"],
        "input_ref": run["input_ref"],
        "mode": run["mode"],
        "output_ref": run["output_ref"],
        "profile_id": run["profile_id"],
        "proposal_id": run["proposal_id"],
        "result": _replay_result_contract(run["result"]),
        "side_effect_mode": run["side_effect_mode"],
        "source_run_id": run["source_run_id"],
        "status": run["status"],
        "task_attempt_id": run["task_attempt_id"],
        "timestamps_present": _timestamps_present(
            run,
            ("created_at", "ended_at", "started_at", "updated_at"),
        ),
    }


def _check_result_contract(result: dict) -> dict:
    return {
        "assertion": result["assertion"],
        "assertion_counts": result["assertion_counts"],
        "assertions": [
            _check_assertion_contract(assertion)
            for assertion in result["assertions"]
        ],
        "baseline_status": result["baseline_status"],
        "comparison": result["comparison"],
        "failure_statuses": result["failure_statuses"],
        "observed_status": result["observed_status"],
        "reason": result["reason"],
        "replay_observed_status": result["replay_observed_status"],
        "replay_result": _replay_result_contract(result["replay_result"]),
        "replay_run_id": result["replay_run_id"],
        "replay_side_effect_mode": result["replay_side_effect_mode"],
        "replay_target": result["replay_target"],
        "target": result["target"],
    }


def _check_assertion_contract(assertion: dict) -> dict:
    contracted = {}
    for key in (
        "actual",
        "comparison",
        "entity",
        "expected",
        "index",
        "observed_status",
        "passed",
        "path",
        "preset",
        "reason",
        "replay_observed_status",
        "supported_presets",
        "type",
    ):
        if key in assertion:
            contracted[key] = assertion[key]
    return contracted


def _replay_result_contract(result: dict) -> dict:
    return {
        "actual_side_effect_mode": result["actual_side_effect_mode"],
        "executed_agent": result["executed_agent"],
        "mode": result["mode"],
        "note": result.get("note"),
        "output_run_id": result.get("output_run_id"),
        "requested_side_effect_mode": result["requested_side_effect_mode"],
        "source_run_id": result["source_run_id"],
        "target_map": result.get("target_map"),
    }


def _check_detail_proposal_contract(proposal: dict) -> dict:
    return {
        "confidence": proposal["confidence"],
        "gate_expectations": proposal["gate_expectations"],
        "id": proposal["id"],
        "problem_severity": proposal["problem"]["severity"],
        "profile_id": proposal["profile_id"],
        "proposed_change_types": [
            change["type"] for change in proposal["proposed_changes"]
        ],
        "section": proposal["section"],
        "state": proposal["state"],
        "summary": proposal["summary"],
        "title": proposal["title"],
        "validation_errors": proposal["validation_errors"],
    }


def _check_detail_source_run_contract(run: dict) -> dict:
    return {
        "agent_identity_id": run["agent_identity_id"],
        "id": run["id"],
        "profile_id": run["profile_id"],
        "source_id": run["source_id"],
        "status": run["status"],
        "summary": run["summary"],
        "task_attempt_id": run["task_attempt_id"],
    }


def _check_detail_summary_contract(summary: dict) -> dict:
    return {
        "check_runs": summary["check_runs"],
        "failed_check_runs": summary["failed_check_runs"],
        "latest_assertion_counts": summary["latest_assertion_counts"],
        "latest_assertions": [
            _check_assertion_contract(assertion)
            for assertion in summary["latest_assertions"]
        ],
        "latest_comparison": summary["latest_comparison"],
        "latest_replay_status": summary["latest_replay_status"],
        "latest_status": summary["latest_status"],
        "passed_check_runs": summary["passed_check_runs"],
        "passed_replay_runs": summary["passed_replay_runs"],
        "replay_runs": summary["replay_runs"],
        "side_effect_mode": summary["side_effect_mode"],
        "trust_level": summary["trust_level"],
    }


def _check_detail_target_contract(target: dict) -> dict:
    resolved = target["resolved"]
    return {
        "found": target["found"],
        "ref": target["ref"],
        "resolved": {
            "agent_identity_id": resolved["agent_identity_id"],
            "attributes": resolved["attributes"],
            "id": resolved["id"],
            "kind": resolved["kind"],
            "name": resolved["name"],
            "run_id": resolved["run_id"],
            "status": resolved["status"],
        },
    }


def _span_contract(span: dict) -> dict:
    return {
        "agent_identity_id": span["agent_identity_id"],
        "attributes": span["attributes"],
        "id": span["id"],
        "kind": span["kind"],
        "name": span["name"],
        "parent_span_id": span["parent_span_id"],
        "run_id": span["run_id"],
        "source_id": span["source_id"],
        "status": span["status"],
        "workflow_node_id": span["workflow_node_id"],
    }


def _timestamps_present(row: dict, fields: tuple[str, ...]) -> dict:
    return {field: bool(row.get(field)) for field in fields}


def _register_fixture_operator_adapter(db_path: Path, output_dir: Path) -> tuple[int, dict]:
    command = " ".join(
        shlex.quote(part)
        for part in [sys.executable, str(OPERATOR_COMMAND)]
    )
    return _run_json(
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
            command,
            "--output-dir",
            str(output_dir),
            "--timeout",
            "180",
            "--json",
        ]
    )


def _register_fixture_replay_adapter(db_path: Path, output_dir: Path) -> tuple[int, dict]:
    command = " ".join(
        shlex.quote(part)
        for part in [sys.executable, str(REPLAY_COMMAND)]
    )
    return _run_json(
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
            str(output_dir),
            "--side-effect-mode",
            "network_mocked",
            "--timeout",
            "180",
            "--json",
        ]
    )


def _write_fixture_blob_input(root: Path) -> Path:
    path = root / "operator-output.json"
    path.write_text(
        json.dumps({"token": "redacted"}, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _write_fixture_evidence_bundle(db_path: Path, output_path: Path) -> int:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        return main(["evidence", "--db", str(db_path), "--output", str(output_path)])


def _run_fixture_blob_put(db_path: Path, blob_input: Path) -> tuple[int, dict]:
    return _run_json(
        [
            "blob-put",
            "--db",
            str(db_path),
            str(blob_input),
            "--profile-id",
            "profile_news_research_001",
            "--kind",
            "operator_output",
            "--media-type",
            "application/json",
            "--retention-days",
            "0",
            "--json",
        ]
    )


def _register_fixture_managed_replay_adapter(
    db_path: Path,
    output_dir: Path,
    server_url: str,
    port: int,
) -> tuple[int, dict]:
    return _run_json(
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
            "--json",
        ]
    )


def _seed_source_fixture_db(db_path: Path) -> None:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(["ingest-fixture", "--db", str(db_path), str(SOURCE_FIXTURE)])
    if code != 0:
        raise AssertionError("failed to seed source fixture")


def _seed_context_proposal_db(db_path: Path) -> None:
    _seed_source_fixture_db(db_path)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(
            [
                "propose",
                "--db",
                str(db_path),
                "--schema",
                str(SCHEMA),
                str(VALID_PROPOSAL),
            ]
        )
    if code != 0:
        raise AssertionError("failed to seed proposal")


def _seed_issue_db(db_path: Path) -> str:
    """Seed one deterministic issue (over the context proposal fixture) and return its id."""
    _seed_context_proposal_db(db_path)
    code, payload = _run_json(
        [
            "issue-create",
            "--db",
            str(db_path),
            "Fetch step repeatedly times out",
            "--body",
            "The research fetch span keeps timing out before returning evidence.",
            "--section",
            "context",
            "--category",
            "reliability",
            "--severity",
            "high",
            "--proposal-id",
            "proposal_context_timeout_001",
            "--json",
        ]
    )
    if code != 0:
        raise AssertionError("failed to seed issue")
    return str(payload["issue"]["id"])


def _seed_generated_harness_proposal_db(db_path: Path) -> None:
    _seed_source_fixture_db(db_path)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(
            [
                "propose",
                "--db",
                str(db_path),
                "--schema",
                str(SCHEMA),
                str(VALID_GENERATED_HARNESS_PROPOSAL),
            ]
        )
    if code != 0:
        raise AssertionError("failed to seed generated harness proposal")


def _seed_prepared_generated_harness_db(db_path: Path, *, repo_patch: bool = False) -> None:
    _seed_generated_harness_proposal_db(db_path)
    if repo_patch:
        code, _ = _run_json(
            [
                "policy-set",
                "--db",
                str(db_path),
                "--repo-patch",
                "on",
                "--json",
            ]
        )
        if code != 0:
            raise AssertionError("failed to enable repo patch policy")
    code, _ = _run_json(
        [
            "prepare-harness",
            "--db",
            str(db_path),
            "proposal_harness_generated_check_001",
            "--json",
        ]
    )
    if code != 0:
        raise AssertionError("failed to prepare generated harness proposal")


def _seed_check_spec_db(db_path: Path) -> None:
    _seed_context_proposal_db(db_path)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(
            [
                "generate-checks",
                "--db",
                str(db_path),
                "proposal_context_timeout_001",
            ]
        )
    if code != 0:
        raise AssertionError("failed to seed check spec")


def _seed_judge_check_spec_db(db_path: Path) -> None:
    _seed_check_spec_db(db_path)
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


def _complete_fixture_replay(db_path: Path) -> tuple[dict, dict]:
    code, replay_payload = _run_json(
        [
            "replay",
            "--db",
            str(db_path),
            "check_proposal_context_timeout_001_1",
            "--json",
        ]
    )
    if code != 0:
        raise AssertionError("failed to create replay")
    code, completion_payload = _run_json(
        [
            "complete-replay",
            "--db",
            str(db_path),
            replay_payload["replay_run_id"],
            str(REPLAY_SUCCESS),
            "--json",
        ]
    )
    if code != 0:
        raise AssertionError("failed to complete replay")
    return replay_payload, completion_payload


def _lock_fixture_check_spec(db_path: Path) -> tuple[int, dict]:
    return _run_json(
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


def _run_fixture_replay_command(db_path: Path, output_dir: Path) -> tuple[int, dict]:
    command = " ".join(
        shlex.quote(part)
        for part in [sys.executable, str(REPLAY_COMMAND)]
    )
    return _run_json(
        [
            "replay-command",
            "--db",
            str(db_path),
            "check_proposal_context_timeout_001_1",
            "--command",
            command,
            "--output-dir",
            str(output_dir),
            "--run-check",
            "--json",
        ]
    )


def _run_fixture_judge_command(db_path: Path, output_dir: Path) -> tuple[int, dict]:
    command = " ".join(
        shlex.quote(part)
        for part in [sys.executable, str(JUDGE_COMMAND)]
    )
    return _run_json(
        [
            "judge-command",
            "--db",
            str(db_path),
            "check_proposal_context_timeout_001_1",
            "--command",
            command,
            "--output-dir",
            str(output_dir),
            "--json",
        ]
    )


def _run_fixture_judge_smoke(output_dir: Path) -> tuple[int, dict]:
    command = " ".join(
        shlex.quote(part)
        for part in [sys.executable, str(JUDGE_COMMAND)]
    )
    return _run_json(
        [
            "judge-smoke",
            "--command",
            command,
            "--output-dir",
            str(output_dir),
            "--json",
        ]
    )


def _seed_applied_context_proposal_db(db_path: Path) -> None:
    _seed_context_proposal_db(db_path)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(["apply", "--db", str(db_path), "proposal_context_timeout_001"])
    if code != 0:
        raise AssertionError("failed to apply proposal")


def _seed_context_rule_db(db_path: Path) -> None:
    _seed_applied_context_proposal_db(db_path)
    proposal = json.loads(VALID_PROPOSAL.read_text(encoding="utf-8"))
    proposal["id"] = "proposal_context_rule_001"
    proposal["producer"]["session_id"] = "proposal_context_rule_001"
    proposal["proposed_changes"] = [
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
    proposal_path = db_path.parent / "context-rule-proposal.json"
    proposal_path.write_text(json.dumps(proposal, sort_keys=True), encoding="utf-8")
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(
            [
                "propose",
                "--db",
                str(db_path),
                "--schema",
                str(SCHEMA),
                str(proposal_path),
            ]
        )
    if code != 0:
        raise AssertionError("failed to seed context rule proposal")
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        code = main(["apply", "--db", str(db_path), "proposal_context_rule_001"])
    if code != 0:
        raise AssertionError("failed to apply context rule proposal")


def _register_replay_adapter(db_path: Path, output_dir: Path) -> None:
    command = " ".join(
        shlex.quote(part) for part in [sys.executable, str(REPLAY_COMMAND)]
    )
    code, _ = _run_json(
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
            str(output_dir),
            "--side-effect-mode",
            "network_mocked",
            "--json",
        ]
    )
    if code != 0:
        raise AssertionError("failed to register replay adapter")


def _profile_next_contract(payload: dict, db_path: Path) -> dict:
    return {
        "action": payload["action"],
        "notes": payload["notes"],
        "profile_id": payload["profile_id"],
        "reason": payload["reason"],
        "result": payload["result"],
        "routing_after": _profile_next_routing_contract(
            payload["routing_after"],
            db_path,
        ),
        "routing_before": _profile_next_routing_contract(
            payload["routing_before"],
            db_path,
        ),
        "run_requested": payload["run_requested"],
        "status": payload["status"],
        "suggested_commands": [
            _suggested_command_contract(command, db_path)
            for command in payload["suggested_commands"]
        ],
    }


def _profile_next_routing_contract(routing: dict, db_path: Path) -> dict:
    return {
        "check_run_id": routing.get("check_run_id"),
        "check_spec_id": routing.get("check_spec_id"),
        "next_action": routing.get("next_action"),
        "proposal_id": routing.get("proposal_id"),
        "proposal_section": routing.get("proposal_section"),
        "proposal_state": routing.get("proposal_state"),
        "reason": routing.get("reason"),
        "replay_run_id": routing.get("replay_run_id"),
        "run_id": routing.get("run_id"),
        "state": routing.get("state"),
        "suggested_commands": [
            _suggested_command_contract(command, db_path)
            for command in routing.get("suggested_commands", [])
        ],
    }


def _suggested_command_contract(command: dict, db_path: Path) -> dict:
    db_marker = str(db_path)
    db_parent_marker = str(db_path.parent)
    return {
        "cli_args": [_normalize_cli_arg(arg, db_marker, db_parent_marker) for arg in command["cli_args"]],
        "intent": command["intent"],
        "label": command["label"],
        "mutating": command["mutating"],
        "requires": command["requires"],
    }


def _normalize_cli_arg(arg: str, db_marker: str, db_parent_marker: str) -> str:
    if arg == db_marker:
        return "<DB_PATH>"
    if arg.startswith(f"{db_parent_marker}/"):
        return arg.replace(db_parent_marker, "<DB_PARENT>", 1)
    return arg


def _proposal_detail_contract(payload: dict) -> dict:
    proposal = payload["proposal"]
    confidence = payload["confidence_assessment"]
    evidence_summary = confidence["evidence"]
    verification = confidence["verification"]
    gate = payload["autonomy_gate"]
    target_ref = payload["target"]["ref"]
    return {
        "autonomy_gate": {
            "action": gate["action"],
            "mutates": gate["mutates"],
            "reason": gate["reason"],
            "section": gate["section"],
        },
        "confidence_assessment": {
            "evidence": {
                "resolved_refs": evidence_summary["resolved_refs"],
                "target_found": evidence_summary["target_found"],
                "total_refs": evidence_summary["total_refs"],
            },
            "kyoko_confidence": confidence["kyoko_confidence"],
            "level": confidence["level"],
            "operator_confidence": confidence["operator_confidence"],
            "verification": {
                "check_runs": verification["check_runs"],
                "latest_check_status": verification["latest_check_status"],
                "latest_replay_status": verification["latest_replay_status"],
                "replay_runs": verification["replay_runs"],
            },
        },
        "counts": {
            "check_runs": len(payload["check_runs"]),
            "check_specs": len(payload["check_specs"]),
            "evidence": len(payload["evidence"]),
            "gate_history": len(payload["gate_history"]),
            "patch_transactions": len(payload["patch_transactions"]),
            "replay_runs": len(payload["replay_runs"]),
            "timeline_events": len(payload["timeline_events"]),
        },
        "evidence": [
            {
                "entity_id": item["ref"]["entity_id"],
                "entity_type": item["ref"]["entity_type"],
                "found": item["found"],
                "role": item["ref"]["role"],
            }
            for item in payload["evidence"]
        ],
        "check_guidance": {
            "assertion_presets": [
                {
                    "assertions": preset["assertions"],
                    "gateable_check_types": preset["gateable_check_types"],
                    "name": preset["name"],
                }
                for preset in payload["check_guidance"]["assertion_presets"]
            ],
            "gateable_check_types": payload["check_guidance"]["gateable_check_types"],
            "informational_check_types": payload["check_guidance"]["informational_check_types"],
            "recorded_judge_only": payload["check_guidance"]["recorded_judge_only"],
            "safe_replay_side_effect_modes": payload["check_guidance"]["safe_replay_side_effect_modes"],
        },
        "evidence_chain": {
            "blocking_reason": payload["evidence_chain"]["blocking_reason"],
            "ready_to_apply": payload["evidence_chain"]["ready_to_apply"],
            "steps": [
                {
                    "stage": step["stage"],
                    "status": step["status"],
                    "title": step["title"],
                }
                for step in payload["evidence_chain"]["steps"]
            ],
        },
        "proposal": {
            "id": proposal["id"],
            "problem_severity": proposal["problem"]["severity"],
            "section": proposal["section"],
            "section_description": proposal["section_description"],
            "section_label": proposal["section_label"],
            "state": proposal["state"],
            "title": proposal["title"],
            "validation_errors": proposal["validation_errors"],
        },
        "target": {
            "entity_id": target_ref["entity_id"],
            "entity_type": target_ref["entity_type"],
            "found": payload["target"]["found"],
            "name": target_ref["name"],
        },
    }


def _issue_summary_contract(issue: dict) -> dict:
    # Issue ids (issue_<uuid>) and timestamps are volatile; project the stable fields.
    return {
        "id_prefix": str(issue["id"]).split("_")[0],
        "title": issue["title"],
        "section": issue["section"],
        "category": issue["category"],
        "severity": issue["severity"],
        "status": issue["status"],
        "proposal_ids": issue["proposal_ids"],
        "affected_span_ids": issue["affected_span_ids"],
        "affected_agent_identity_ids": issue["affected_agent_identity_ids"],
        "affected_workflow_node_ids": issue["affected_workflow_node_ids"],
        "affected_task_ids": issue["affected_task_ids"],
        "evidence_refs": issue["evidence_refs"],
        "has_created_at": bool(issue["created_at"]),
        "updated_at": issue["updated_at"],
    }


def _issues_contract(payload: dict) -> dict:
    return {"issues": [_issue_summary_contract(issue) for issue in payload["issues"]]}


def _issue_detail_contract(payload: dict) -> dict:
    return {
        "issue": _issue_summary_contract(payload["issue"]),
        "section_label": payload["section_label"],
        "section_description": payload["section_description"],
        "evidence": [
            {
                "entity_id": item["ref"]["entity_id"],
                "entity_type": item["ref"]["entity_type"],
                "found": item["found"],
            }
            for item in payload["evidence"]
        ],
        "affected": {
            group: [
                {
                    "entity_type": item["entity_type"],
                    "entity_id": item["entity_id"],
                    "found": item["found"],
                }
                for item in items
            ]
            for group, items in sorted(payload["affected"].items())
        },
        "linked_proposals": [
            {
                "id": entry["proposal"]["id"],
                "link": entry["link"],
                "section": entry["proposal"]["section"],
                "state": entry["proposal"]["state"],
            }
            for entry in payload["linked_proposals"]
        ],
        "summary": payload["summary"],
    }


def _improve_contract(payload: dict) -> dict:
    autonomy = payload["autonomy"]
    replay_runs = []
    for run in payload["replay_runs"]:
        replay_runs.append(
            {
                "adapter_id": run["adapter_id"],
                "check_run": run["check_run"],
                "check_spec_id": run["check_spec_id"],
                "output_run_id": run["output_run_id"],
                "path_fields_present": {
                    "raw_output_path": bool(run.get("raw_output_path")),
                    "request_path": bool(run.get("request_path")),
                    "result_path": bool(run.get("result_path")),
                },
                "profile_id": run["profile_id"],
                "replay_run_id": run["replay_run_id"],
                "status": run["status"],
            }
        )
    return {
        "analyze_present": payload["analyze"] is not None,
        "autonomy": {
            "decisions": [
                {
                    "action": decision["action"],
                    "applied_context_rule_ids": decision["applied_context_rule_ids"],
                    "applied_skill_ids": decision["applied_skill_ids"],
                    "check_run_ids": decision["check_run_ids"],
                    "check_spec_ids": decision["check_spec_ids"],
                    "patch_transaction_ids": decision["patch_transaction_ids"],
                    "proposal_id": decision["proposal_id"],
                    "reason": decision["reason"],
                    "required_check_level": decision["required_check_level"],
                    "section": decision["section"],
                    "state_after": decision["state_after"],
                    "state_before": decision["state_before"],
                }
                for decision in autonomy["decisions"]
            ],
            "policy": {
                "allow_repo_patch": autonomy["policy"]["allow_repo_patch"],
                "allow_skillbook_write": autonomy["policy"]["allow_skillbook_write"],
                "context_mode": autonomy["policy"]["context_mode"],
                "harness_mode": autonomy["policy"]["harness_mode"],
                "required_check_level_context": autonomy["policy"]["required_check_level_context"],
                "required_check_level_harness": autonomy["policy"]["required_check_level_harness"],
                "rollback_on_regression": autonomy["policy"]["rollback_on_regression"],
            },
            "profile_id": autonomy["profile_id"],
        },
        "check_spec_ids": payload["check_spec_ids"],
        "existing_check_spec_ids": payload["existing_check_spec_ids"],
        "generated_check_spec_ids": payload["generated_check_spec_ids"],
        "notes": payload["notes"],
        "operator": payload["operator"],
        "profile_id": payload["profile_id"],
        "proposal_id": payload["proposal_id"],
        "replay_runs": replay_runs,
        "source_import_present": payload["source_import"] is not None,
    }


def _autonomy_events_contract(payload: dict) -> dict:
    events = []
    for event in payload["autonomy_events"]:
        metadata = event["metadata"]
        events.append(
            {
                "entity_id": event["entity_id"],
                "entity_type": event["entity_type"],
                "kind": event["kind"],
                "metadata": {
                    "action": metadata.get("action"),
                    "applied_context_rule_ids": metadata.get("applied_context_rule_ids"),
                    "applied_skill_ids": metadata.get("applied_skill_ids"),
                    "decision_kind": metadata.get("decision_kind"),
                    "check_run_ids": metadata.get("check_run_ids"),
                    "check_spec_ids": metadata.get("check_spec_ids"),
                    "patch_transaction_ids": metadata.get("patch_transaction_ids"),
                    "profile_id": metadata.get("profile_id"),
                    "reason": metadata.get("reason"),
                    "required_check_level": metadata.get("required_check_level"),
                    "section": metadata.get("section"),
                    "state_after": metadata.get("state_after"),
                    "state_before": metadata.get("state_before"),
                },
                "profile_id": event["profile_id"],
            }
        )
    return {"autonomy_events": events}


def _doctor_contract(payload: dict) -> dict:
    checks = {check["id"]: check for check in payload["checks"]}
    release_detail = checks["release_python_targets"]["detail"]
    commands = [
        {
            "cli_args": command["cli_args"],
            "intent": command["intent"],
            "mutating": command["mutating"],
            "requires": command["requires"],
        }
        for command in payload["suggested_commands"]
    ]
    return {
        "ok": payload["ok"],
        "readiness": payload["readiness"],
        "summary": payload["summary"],
        "checks": [
            {
                "detail_keys": sorted(check["detail"]),
                "id": check["id"],
                "status": check["status"],
            }
            for check in payload["checks"]
        ],
        "bundled_assets": checks["bundled_assets"]["detail"]["assets"],
        "release_python_targets": {
            "bootstrap_required_targets": release_detail["bootstrap_required_targets"],
            "build_backend_install_commands": release_detail["build_backend_install_commands"],
            "build_backend_reasons": release_detail["build_backend_reasons"],
            "missing_targets": release_detail["missing_targets"],
            "ready_matrix_command": release_detail["ready_matrix_command"],
            "ready_targets": release_detail["ready_targets"],
            "unready_targets": release_detail["unready_targets"],
        },
        "suggested_commands": commands,
    }


def _source_discovery_contract(
    payload: dict,
    db_path: Path,
    home: Path,
    root_path: Path,
) -> dict:
    return {
        "candidates": [
            _source_candidate_contract(candidate, db_path, home, root_path)
            for candidate in payload["candidates"]
        ],
        "db_path": _source_path_contract(payload["db_path"], db_path, home, root_path),
        "home": _source_path_contract(payload["home"], db_path, home, root_path),
    }


def _discovered_source_import_contract(
    payload: dict,
    db_path: Path,
    home: Path,
    root_path: Path,
    output_dir: Path,
) -> dict:
    imported = payload["import"]
    normalized_path = imported.get("normalized_path")
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "normalized_path": normalized_path is not None and Path(normalized_path).exists(),
        },
        "candidate": _source_candidate_contract(payload["candidate"], db_path, home, root_path),
        "db_path": _source_path_contract(payload["db_path"], db_path, home, root_path),
        "import": {
            "counts": imported["counts"],
            "ingested_counts": imported["ingested_counts"],
            "normalized_path": _source_path_contract(
                imported["normalized_path"],
                db_path,
                home,
                root_path,
                output_dir=output_dir,
            ),
            "profile_id": imported["profile_id"],
            "source_path": _source_path_contract(
                imported["source_path"],
                db_path,
                home,
                root_path,
            ),
        },
    }


def _source_candidate_contract(
    candidate: dict,
    db_path: Path,
    home: Path,
    root_path: Path,
) -> dict:
    return {
        "exists": candidate["exists"],
        "id": candidate["id"],
        "import_command_args": [
            _source_path_contract(arg, db_path, home, root_path)
            for arg in shlex.split(candidate["import_command"])
        ],
        "kind": candidate["kind"],
        "label": candidate["label"],
        "metadata": _source_candidate_metadata_contract(
            candidate["metadata"],
            db_path,
            home,
            root_path,
        ),
        "path": _source_path_contract(candidate["path"], db_path, home, root_path),
        "status": candidate["status"],
    }


def _source_candidate_metadata_contract(
    metadata: dict,
    db_path: Path,
    home: Path,
    root_path: Path,
) -> dict:
    contracted = dict(metadata)
    if "sessions_json" in contracted:
        contracted["sessions_json"] = _source_path_contract(
            contracted["sessions_json"],
            db_path,
            home,
            root_path,
        )
    return contracted


def _source_path_contract(
    value: Optional[str],
    db_path: Path,
    home: Path,
    root_path: Path,
    *,
    output_dir: Optional[Path] = None,
) -> Optional[str]:
    if value is None:
        return None
    replacements = [
        (db_path, "<DB_PATH>"),
        (home, "<HOME>"),
        (root_path, "<ROOT_PATH>"),
    ]
    if output_dir is not None:
        replacements.insert(0, (output_dir, "<OUTPUT_DIR>"))
    text = str(value)
    for path, marker in replacements:
        path_text = str(path)
        if text == path_text:
            return marker
        if text.startswith(f"{path_text}/"):
            return text.replace(path_text, marker, 1)
    return text


def _operator_smoke_matrix_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "db_path": _output_path_contract(payload["db_path"], output_dir),
        "operators": payload["operators"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "prepare_only": payload["prepare_only"],
        "summary": payload["summary"],
        "targets": [
            _operator_smoke_target_contract(target, output_dir)
            for target in payload["targets"]
        ],
        "used_demo_database": payload["used_demo_database"],
    }


def _operator_smoke_target_contract(target: dict, output_dir: Path) -> dict:
    plan = target.get("plan")
    return {
        "has_plan": plan is not None,
        "has_report": target.get("report") is not None,
        "operator": target["operator"],
        "plan": (
            _operator_smoke_plan_contract(plan, output_dir)
            if isinstance(plan, dict)
            else None
        ),
        "reason": target["reason"],
        "status": target["status"],
    }


def _operator_smoke_plan_contract(plan: dict, output_dir: Path) -> dict:
    environment = plan["environment"]
    return {
        "artifact_exists": {
            "db_path": Path(plan["db_path"]).exists(),
            "evidence_path": Path(plan["evidence_path"]).exists(),
            "output_dir": Path(plan["output_dir"]).exists(),
            "prompt_path": Path(plan["prompt_path"]).exists(),
            "raw_output_path": Path(plan["raw_output_path"]).exists(),
        },
        "artifact_paths": {
            "db_path": _output_path_contract(plan["db_path"], output_dir),
            "evidence_path": _output_path_contract(plan["evidence_path"], output_dir),
            "output_dir": _output_path_contract(plan["output_dir"], output_dir),
            "prompt_path": _output_path_contract(plan["prompt_path"], output_dir),
            "raw_output_path": _output_path_contract(plan["raw_output_path"], output_dir),
        },
        "command": plan["command"],
        "environment_contract": {
            "evidence_path": _output_path_contract(
                environment["KYOKO_EVIDENCE_PATH"],
                output_dir,
            ),
            "operator_target": environment["KYOKO_OPERATOR_TARGET"],
            "profile_id": environment["KYOKO_PROFILE_ID"],
            "prompt_path": _output_path_contract(
                environment["KYOKO_OPERATOR_PROMPT_PATH"],
                output_dir,
            ),
            "proposal_block_begin": environment["KYOKO_PROPOSAL_BLOCK_BEGIN"],
            "proposal_block_end": environment["KYOKO_PROPOSAL_BLOCK_END"],
            "schema_path": _repo_path_contract(
                environment["KYOKO_LEARNING_PROPOSAL_SCHEMA_PATH"]
            ),
        },
        "environment_keys": sorted(environment),
        "expanded_command": plan["expanded_command"],
        "live_operator_invoked": plan["live_operator_invoked"],
        "operator": plan["operator"],
        "operator_kind": plan["operator_kind"],
        "profile_id": plan["profile_id"],
        "shell_command": plan["shell_command"],
        "used_demo_database": plan["used_demo_database"],
    }


def _operator_smoke_report_contract(payload: dict, output_dir: Path) -> dict:
    proposal = json.loads(Path(payload["proposal_path"]).read_text(encoding="utf-8"))
    raw_output = Path(payload["raw_output_path"]).read_text(encoding="utf-8")
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "evidence_path": Path(payload["evidence_path"]).exists(),
            "output_dir": Path(payload["output_dir"]).exists(),
            "prompt_path": Path(payload["prompt_path"]).exists(),
            "proposal_path": Path(payload["proposal_path"]).exists(),
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
        },
        "artifact_paths": {
            "db_path": _output_path_contract(payload["db_path"], output_dir),
            "evidence_path": _output_path_contract(payload["evidence_path"], output_dir),
            "output_dir": _output_path_contract(payload["output_dir"], output_dir),
            "prompt_path": _output_path_contract(payload["prompt_path"], output_dir),
            "proposal_path": _output_path_contract(payload["proposal_path"], output_dir),
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
        },
        "attempts": payload["attempts"],
        "live_operator_invoked": payload["live_operator_invoked"],
        "operator": payload["operator"],
        "operator_run_id_present": bool(payload["operator_run_id"]),
        "persisted": payload["persisted"],
        "profile_id": payload["profile_id"],
        "proposal_file": {
            "change_types": [
                change["type"]
                for change in proposal["proposed_changes"]
            ],
            "evidence_refs": [
                {
                    "entity_id": ref["entity_id"],
                    "entity_type": ref["entity_type"],
                    "role": ref["role"],
                }
                for ref in proposal["evidence_refs"]
            ],
            "id": proposal["id"],
            "producer_name": proposal["producer"]["name"],
            "producer_session_id": proposal["producer"]["session_id"],
            "section": proposal["section"],
        },
        "proposal_id": payload["proposal_id"],
        "raw_output_contract": {
            "contains_begin_marker": "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" in raw_output,
            "contains_done_marker": "Done." in raw_output,
            "contains_end_marker": "END_KYOKO_LEARNING_PROPOSAL_JSON" in raw_output,
        },
        "used_demo_database": payload["used_demo_database"],
    }


def _operator_failure_smoke_report_contract(payload: dict, output_dir: Path) -> dict:
    raw_output = Path(payload["raw_output_path"]).read_text(encoding="utf-8")
    prompt = Path(payload["prompt_path"]).read_text(encoding="utf-8")
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "evidence_path": Path(payload["evidence_path"]).exists(),
            "output_dir": Path(payload["output_dir"]).exists(),
            "prompt_path": Path(payload["prompt_path"]).exists(),
            "raw_output_path": Path(payload["raw_output_path"]).exists(),
        },
        "artifact_paths": {
            "db_path": _output_path_contract(payload["db_path"], output_dir),
            "evidence_path": _output_path_contract(payload["evidence_path"], output_dir),
            "output_dir": _output_path_contract(payload["output_dir"], output_dir),
            "prompt_path": _output_path_contract(payload["prompt_path"], output_dir),
            "raw_output_path": _output_path_contract(payload["raw_output_path"], output_dir),
        },
        "attempts": payload["attempts"],
        "error_prefix": str(payload["error"]).split(":", 1)[0],
        "expected_failure_kind": payload["expected_failure_kind"],
        "failure_kind": payload["failure_kind"],
        "last_attempt_status": payload["last_attempt_status"],
        "live_operator_invoked": payload["live_operator_invoked"],
        "operator": payload["operator"],
        "operator_run_id_present": bool(payload["operator_run_id"]),
        "passed": payload["passed"],
        "persisted": payload["persisted"],
        "profile_id": payload["profile_id"],
        "prompt_contract": {
            "contains_failure_capture": "Expected Failure Capture" in prompt,
            "contains_invalid_line": "KYOKO_EXPECTED_INVALID_OPERATOR_OUTPUT" in prompt,
        },
        "prompt_failure_mode": payload["prompt_failure_mode"],
        "proposal_id": payload["proposal_id"],
        "raw_output_contract": {
            "contains_attempt_header": "attempt 1 status=invalid_output" in raw_output,
            "contains_begin_marker": "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" in raw_output,
            "contains_end_marker": "END_KYOKO_LEARNING_PROPOSAL_JSON" in raw_output,
        },
        "status": payload["status"],
        "used_demo_database": payload["used_demo_database"],
    }


def _release_smoke_matrix_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "artifact_types": payload["artifact_types"],
        "dashboard_smoke": payload["dashboard_smoke"],
        "install_dependencies": payload["install_dependencies"],
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "project_root": _repo_path_contract(payload["project_root"]),
        "python_targets": payload["python_targets"],
        "run_demo": payload["run_demo"],
        "summary": payload["summary"],
        "targets": [
            _release_smoke_target_contract(target, output_dir)
            for target in payload["targets"]
        ],
        "temporary": payload["temporary"],
    }


def _release_smoke_contract(payload: dict, output_dir: Path) -> dict:
    return {
        **_release_smoke_report_contract(payload, output_dir),
        "temporary": payload["temporary"],
    }


def _release_smoke_target_contract(target: dict, output_dir: Path) -> dict:
    report = target.get("report")
    return {
        "has_report": report is not None,
        "python_executable": target["python_executable"],
        "reason": target["reason"],
        "report": (
            _release_smoke_report_contract(report, output_dir)
            if isinstance(report, dict)
            else None
        ),
        "status": target["status"],
        "target": target["target"],
    }


def _release_smoke_report_contract(report: dict, output_dir: Path) -> dict:
    return {
        "artifact_dir": _output_path_contract(report["artifact_dir"], output_dir),
        "artifact_reports": [
            {
                "artifact_path": _output_path_contract(artifact["artifact_path"], output_dir),
                "artifact_type": artifact["artifact_type"],
                "command_names": [command["name"] for command in artifact["commands"]],
                "dashboard_smoke_ok": artifact["dashboard_smoke_ok"],
                "dashboard_smoke_summary": artifact["dashboard_smoke_summary"],
                "doctor_ok": artifact["doctor_ok"],
                "doctor_summary": artifact["doctor_summary"],
                "install_ok": artifact["install_ok"],
                "install_strategy": artifact["install_strategy"],
                "installed_version": artifact["installed_version"],
                "legacy_fallback_used": artifact["legacy_fallback_used"],
                "modern_install_returncode": artifact["modern_install_returncode"],
                "run_cwd": _output_path_contract(artifact["run_cwd"], output_dir),
                "venv_path": _output_path_contract(artifact["venv_path"], output_dir),
            }
            for artifact in report["artifacts"]
        ],
        "build_commands": [
            {
                "command": command["command"],
                "cwd": _output_path_contract(command["cwd"], output_dir),
                "name": command["name"],
                "returncode": command["returncode"],
                "stdout_tail_present": bool(command["stdout_tail"]),
            }
            for command in report["build_commands"]
        ],
        "dashboard_smoke": report["dashboard_smoke"],
        "install_dependencies": report["install_dependencies"],
        "output_dir": _output_path_contract(report["output_dir"], output_dir),
        "passed": report["passed"],
        "project_root": _repo_path_contract(report["project_root"]),
        "python_executable": report["python_executable"],
        "run_demo": report["run_demo"],
    }


def _mcp_install_smoke_matrix_contract(payload: dict, output_dir: Path) -> dict:
    return {
        "output_dir": _output_path_contract(payload["output_dir"], output_dir),
        "passed": payload["passed"],
        "results": [
            _mcp_install_smoke_result_contract(result, output_dir)
            for result in payload["results"]
        ],
        "server": payload["server"],
        "summary": payload["summary"],
        "targets": payload["targets"],
        "temporary": payload["temporary"],
    }


def _mcp_install_smoke_result_contract(result: dict, output_dir: Path) -> dict:
    report = result.get("report")
    return {
        "has_report": report is not None,
        "reason": result["reason"],
        "report": (
            _mcp_install_smoke_report_contract(report, output_dir)
            if isinstance(report, dict)
            else None
        ),
        "status": result["status"],
        "target": result["target"],
    }


def _mcp_install_smoke_report_contract(report: dict, output_dir: Path) -> dict:
    return {
        "command_contract": _mcp_command_contract(report["target"], report["command"], output_dir),
        "config_exists": report["config_exists"],
        "config_path_hint": _output_path_contract(report["config_path_hint"], output_dir),
        "cwd": _output_path_contract(report["cwd"], output_dir),
        "home": _output_path_contract(report["home"], output_dir),
        "list_command": report["list_command"],
        "list_returncode": report["list_returncode"],
        "list_stdout_tail_present": bool(report["list_stdout_tail"]),
        "list_verified": report["list_verified"],
        "notes_contract": {
            "has_config_check_note": any(
                "Isolated config path checked:" in note
                for note in report["notes"]
            ),
            "has_list_verified_note": any(
                "registry/list output verified" in note
                for note in report["notes"]
            ),
            "note_count": len(report["notes"]),
        },
        "passed": report["passed"],
        "returncode": report["returncode"],
        "server": report["server"],
        "stdout_tail_present": bool(report["stdout_tail"]),
        "target": report["target"],
    }


def _mcp_command_contract(target: str, command: list[str], output_dir: Path) -> dict:
    if target == "codex":
        separator = command.index("--")
        server_command = command[separator + 1:]
        env_values = [
            value
            for index, value in enumerate(command)
            if index > 0 and command[index - 1] == "--env"
        ]
        return {
            "env_keys": sorted(value.split("=", 1)[0] for value in env_values),
            "prefix": command[:4],
            "server_args_prefix": server_command[1:5],
            "server_db_path": _outside_path_contract(server_command[6], output_dir),
            "server_schema_path": _repo_path_contract(server_command[8]),
        }
    if target == "claude":
        server_config = json.loads(command[-1])
        return {
            "prefix": command[:6],
            "scope": command[4],
            "server_args_prefix": server_config["args"][:4],
            "server_db_path": _outside_path_contract(server_config["args"][5], output_dir),
            "server_env_keys": sorted(server_config.get("env", {})),
            "server_schema_path": _repo_path_contract(server_config["args"][7]),
        }
    raise AssertionError(f"unexpected MCP target: {target}")


def _project_bootstrap_contract(payload: dict, project_dir: Path) -> dict:
    next_steps = Path(payload["next_steps_path"]).read_text(encoding="utf-8")
    embedded_commands = _embedded_next_step_commands(next_steps)
    mcp_servers = payload["mcp_config"]["mcpServers"]
    mcp_server = mcp_servers["kyoko"]
    return {
        "artifact_exists": {
            "db_path": Path(payload["db_path"]).exists(),
            "mcp_config_path": Path(payload["mcp_config_path"]).exists(),
            "next_steps_path": Path(payload["next_steps_path"]).exists(),
            "replay_server": Path(payload["replay_server"]["output_path"]).exists(),
            "source_adapter": Path(payload["source_adapter"]["output_path"]).exists(),
        },
        "commands": {
            key: _project_string_contract(value, project_dir)
            for key, value in payload["commands"].items()
        },
        "embedded_commands_match": embedded_commands == payload["commands"],
        "mcp_config": {
            "server": {
                "args": [
                    _project_string_contract(arg, project_dir)
                    for arg in mcp_server["args"]
                ],
                "command_is_current_python": mcp_server["command"] == sys.executable,
                "env_keys": sorted(mcp_server.get("env", {})),
            },
            "server_names": sorted(mcp_servers),
            "target": payload["mcp_config"]["target"],
        },
        "next_steps_contract": {
            "contains_discover_sources": "discover-sources" in next_steps,
            "contains_machine_readable_commands": "Machine-readable commands" in next_steps,
            "contains_no_live_notice": "No live operator model" in next_steps,
            "contains_native_ace_prepare": "native ACE prepare" in next_steps,
            "contains_replay_smoke": "integration-smoke replay-server" in next_steps,
            "contains_safe_smokes": "--safe-smokes" in next_steps,
        },
        "operator_bootstrap": {
            "registered": [
                {
                    "adapter_id": adapter["adapter_id"],
                    "command": adapter["command"],
                    "enabled": adapter["enabled"],
                    "name": adapter["name"],
                    "operator_kind": adapter["operator_kind"],
                    "output_dir": _project_string_contract(adapter["output_dir"], project_dir),
                    "profile_id": adapter["profile_id"],
                    "timeout_seconds": adapter["timeout_seconds"],
                }
                for adapter in payload["operator_bootstrap"]["registered"]
            ],
            "skipped": payload["operator_bootstrap"]["skipped"],
        },
        "paths": {
            "db_path": _project_string_contract(payload["db_path"], project_dir),
            "mcp_config_path": _project_string_contract(payload["mcp_config_path"], project_dir),
            "next_steps_path": _project_string_contract(payload["next_steps_path"], project_dir),
            "project_dir": _project_string_contract(payload["project_dir"], project_dir),
            "replay_server": _project_string_contract(
                payload["replay_server"]["output_path"],
                project_dir,
            ),
            "source_adapter": _project_string_contract(
                payload["source_adapter"]["output_path"],
                project_dir,
            ),
        },
        "replay_server": {
            "framework": payload["replay_server"]["framework"],
            "profile_name": payload["replay_server"]["profile_name"],
            "wrote": payload["replay_server"]["wrote"],
        },
        "source_adapter": {
            "framework": payload["source_adapter"]["framework"],
            "profile_name": payload["source_adapter"]["profile_name"],
            "wrote": payload["source_adapter"]["wrote"],
        },
    }


def _embedded_next_step_commands(next_steps: str) -> dict:
    marker = "```json\n"
    start = next_steps.index(marker) + len(marker)
    end = next_steps.index("\n```", start)
    return json.loads(next_steps[start:end])


def _project_string_contract(value: str, project_dir: Path) -> str:
    if value is None:
        return value
    return str(value).replace(str(project_dir), "<PROJECT_DIR>")


def _db_path_contract(value: str, db_path: Path) -> str:
    if Path(value).resolve() == db_path.resolve():
        return "<DB_PATH>"
    return _tmp_path_contract(value, db_path.parent)


def _blob_root_contract(value: str, db_path: Path) -> str:
    if Path(value) == db_path.parent / "blobs":
        return "<BLOB_ROOT>"
    return _tmp_path_contract(value, db_path.parent)


def _blob_path_contract(value: str, db_path: Path) -> str:
    path = Path(value)
    try:
        path.relative_to(db_path.parent / "blobs")
    except ValueError:
        return _tmp_path_contract(value, db_path.parent)
    return "<BLOB_PATH>"


def _fixture_workspace_contract(value: str) -> str:
    prefix = "/tmp/kyoko-fixtures"
    if value.startswith(prefix):
        suffix = value[len(prefix):].lstrip("/")
        return "<FIXTURE_ROOT>" if not suffix else f"<FIXTURE_ROOT>/{suffix}"
    return value


def _tmp_path_contract(value: str, root: Path) -> str:
    path = Path(value)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return str(path)
    if relative == Path("."):
        return "<TMP>"
    return f"<TMP>/{relative.as_posix()}"


def _output_path_contract(value: str, output_dir: Path) -> str:
    if value.startswith("<"):
        return value
    path_value = Path(value)
    if not path_value.is_absolute() and not str(path_value).startswith("."):
        return value
    path = path_value.resolve()
    output_dir = output_dir.resolve()
    try:
        relative = path.relative_to(output_dir)
    except ValueError:
        return str(path)
    if relative == Path("."):
        return "<OUTPUT_DIR>"
    return f"<OUTPUT_DIR>/{relative.as_posix()}"


def _outside_path_contract(value: str, output_dir: Path) -> str:
    if value.startswith("<"):
        return value
    path_value = Path(value)
    if not path_value.is_absolute() and not str(path_value).startswith("."):
        return value
    path = path_value.resolve()
    output_dir = output_dir.resolve()
    try:
        relative = path.relative_to(output_dir.parent)
    except ValueError:
        return str(path)
    return f"<TMP>/{relative.as_posix()}"


def _output_or_outside_path_contract(value: str, output_dir: Path) -> str:
    if value.startswith("<"):
        return value
    path_value = Path(value)
    if not path_value.is_absolute() and not str(path_value).startswith("."):
        return value
    path = path_value.resolve()
    output_dir = output_dir.resolve()
    try:
        relative = path.relative_to(output_dir)
    except ValueError:
        return _outside_path_contract(value, output_dir)
    if relative == Path("."):
        return "<OUTPUT_DIR>"
    return f"<OUTPUT_DIR>/{relative.as_posix()}"


def _repo_path_contract(value: str) -> str:
    path = Path(value)
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return str(path)
    if relative == Path("."):
        return "<REPO>"
    return f"<REPO>/{relative.as_posix()}"


def _write_fake_executable(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body.lstrip()}", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _write_fake_ace_runtime(path: Path) -> Path:
    package = path / "ace" / "core"
    package.mkdir(parents=True)
    (path / "pyproject.toml").write_text(
        '[project]\nname = "fake-ace"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    (path / "ace" / "__init__.py").write_text("", encoding="utf-8")
    (path / "ace" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (path / "ace" / "core" / "skillbook.py").write_text(
        """
class Skillbook:
    def __init__(self, payload):
        self._payload = payload

    @classmethod
    def from_dict(cls, payload):
        return cls(payload)

    def to_dict(self):
        return self._payload

    def stats(self):
        return {
            "sections": len(self._payload.get("sections", {})),
            "skills": len(self._payload.get("skills", {})),
        }
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _write_fake_ace_native_command(path: Path) -> Path:
    path.write_text(
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
    return path


if __name__ == "__main__":
    unittest.main()
