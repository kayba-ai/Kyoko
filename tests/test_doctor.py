from __future__ import annotations

import io
import importlib.metadata
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from kyoko.cli import main
from kyoko.ace_bridge import ACE_NATIVE_RUN_REPORT_FILENAME, AceBridgeError
from kyoko.bundled_assets import bundled_asset_path
from kyoko.doctor import (
    _check_package_metadata,
    _check_release_python_targets,
    doctor_report_text,
    run_doctor,
)
from kyoko.improve_smoke import ImproveSmokeError
from kyoko.integration_smoke import IntegrationSmokeError
from kyoko.otlp_smoke import OtlpSmokeError
from kyoko.storage import connect, initialize_database


class FakeOperatorSmokeMatrix:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_json(self) -> dict[str, object]:
        return self.payload


class FakeJsonReport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.ok = bool(payload.get("ok", True))

    def to_json(self, *args, **kwargs) -> dict[str, object]:
        return self.payload


def fake_mcp_install_smoke_report(output_dir: Path) -> FakeJsonReport:
    return FakeJsonReport(
        {
            "targets": ["codex"],
            "server": "kyoko",
            "output_dir": str(output_dir),
            "summary": {
                "total": 1,
                "passed": 1,
                "failed": 0,
                "skipped": 0,
                "available": 1,
            },
            "results": [],
            "passed": True,
        }
    )


def fake_improve_smoke_report(output_dir: Path, db_path=None) -> FakeJsonReport:
    selected_db = db_path or output_dir / "doctor-improve.db"
    return FakeJsonReport(
        {
            "kind": "improve_smoke",
            "framework": "generic-python",
            "db_path": str(selected_db),
            "output_dir": str(output_dir),
            "replay_adapter_id": "framework_improve_smoke_replay",
            "source_smoke": {
                "kind": "source_adapter",
                "profile_id": "profile_framework_improve_smoke",
                "ingested_counts": {"runs": 1, "spans": 2},
                "status": {"counts": {"runs": 1, "spans": 2}},
            },
            "improve": {
                "operator": "mock",
                "profile_id": "profile_framework_improve_smoke",
                "proposal_id": "proposal_mock_span_framework_fetch_timeout_001",
                "generated_check_spec_ids": [
                    "check_proposal_mock_span_framework_fetch_timeout_001_1"
                ],
                "replay_runs": [
                    {
                        "status": "passed",
                        "check_run": {"status": "passed"},
                    }
                ],
                "autonomy": {"decisions": [{"action": "applied"}]},
            },
            "status": {
                "counts": {
                    "runs": 2,
                    "spans": 4,
                    "learning_proposals": 1,
                    "check_specs": 1,
                    "check_runs": 1,
                    "replay_runs": 1,
                    "skills": 1,
                }
            },
            "passed": True,
            "live_operator_invoked": False,
            "external_model_invoked": False,
            "generated_source_adapter_invoked": True,
            "managed_replay_server_invoked": True,
        }
    )


def fake_opentelemetry_smoke_report(output_dir: Path, db_path=None) -> FakeJsonReport:
    selected_db = db_path or output_dir / "doctor-opentelemetry.db"
    return FakeJsonReport(
        {
            "kind": "opentelemetry_python_smoke",
            "python_executable": "/tmp/otel-venv/bin/python",
            "opentelemetry_sdk_version": "9.9.0",
            "db_path": str(selected_db),
            "output_dir": str(output_dir),
            "workspace_root": str(output_dir / "workspace"),
            "script_path": str(output_dir / "opentelemetry_sdk_smoke.py"),
            "otlp_payload_path": str(output_dir / "otlp-payload.json"),
            "normalized_path": str(output_dir / "normalized-source-events.json"),
            "stdout_path": str(output_dir / "opentelemetry-sdk.stdout.txt"),
            "stderr_path": str(output_dir / "opentelemetry-sdk.stderr.txt"),
            "exit_code": 0,
            "profile_id": "profile_opentelemetry_sdk_smoke",
            "run_ids": ["run_otlp_001"],
            "span_ids": ["span_otlp_agent", "span_otlp_tool"],
            "ingested_counts": {
                "runs": 1,
                "spans": 2,
                "timeline_events": 1,
            },
            "status": {
                "counts": {
                    "runs": 1,
                    "spans": 2,
                    "timeline_events": 1,
                    "sources": 1,
                }
            },
            "opentelemetry_sdk_invoked": True,
            "external_model_invoked": False,
            "live_operator_invoked": False,
            "passed": True,
        }
    )


def fake_ace_native_smoke_report(output_dir: Path, db_path=None) -> FakeJsonReport:
    selected_db = db_path or output_dir / "doctor-ace-native.db"
    return FakeJsonReport(
        {
            "kind": "legacy_ace_offline_adapter_smoke",
            "db_path": str(selected_db),
            "output_dir": str(output_dir),
            "source_fixture_path": "/tmp/source-events.json",
            "command_path": "/tmp/ace_legacy_smoke_command.py",
            "profile_id": "profile_news_research_001",
            "passed": True,
            "external_command_invoked": True,
            "installed_ace_package_invoked": True,
            "provider_backed": False,
            "live_operator_invoked": False,
            "external_model_invoked": False,
            "native_run": {
                "stdout_tail": "legacy ace smoke complete\n",
                "stderr_tail": "",
                "diff": {
                    "proposal_ids": ["proposal_native_ace_smoke"],
                    "unsupported_changes": [],
                },
            },
        }
    )


def fake_dashboard_smoke_report(output_dir: Path, db_path=None) -> FakeJsonReport:
    selected_db = db_path or output_dir / "dashboard-smoke.db"
    return FakeJsonReport(
        {
            "kind": "dashboard_browser_smoke",
            "db_path": str(selected_db),
            "output_dir": str(output_dir),
            "temporary": False,
            "server_url": "http://127.0.0.1:61234",
            "seeded_demo": True,
            "api_status": {"counts": {"runs": 2, "spans": 4}},
            "api_metric_cards_count": 6,
            "console_errors": [],
            "page_errors": [],
            "request_failures": [],
            "viewports": [
                {
                    "name": "desktop",
                    "width": 1440,
                    "height": 1000,
                    "metric_count": 22,
                    "metric_overflows": [],
                    "screenshot_path": str(output_dir / "dashboard-desktop.png"),
                    "passed": True,
                },
                {
                    "name": "mobile",
                    "width": 390,
                    "height": 844,
                    "metric_count": 22,
                    "metric_overflows": [],
                    "screenshot_path": str(output_dir / "dashboard-mobile.png"),
                    "passed": True,
                },
            ],
            "browser_backend": "npx-playwright",
            "passed": True,
        }
    )


def write_retained_operator_success_evidence(output_dir: Path, operators: tuple[str, ...]) -> None:
    output_dir.mkdir(parents=True)
    db_path = output_dir / "smoke.db"
    initialize_database(db_path)
    with connect(db_path) as connection:
        _insert_smoke_profile(connection)
        for operator in operators:
            operator_dir = output_dir / operator
            operator_dir.mkdir()
            raw_output = operator_dir / "operator-output.txt"
            raw_output.write_text("BEGIN_KYOKO_LEARNING_PROPOSAL_JSON\n{}\n")
            proposal_id = f"proposal_{operator}_live_001"
            _insert_smoke_proposal(connection, proposal_id)
            connection.execute(
                """
                INSERT INTO operator_runs (
                  id, profile_id, adapter_id, operator_label, operator_kind, status,
                  started_at, ended_at, evidence_ref, prompt_ref, raw_output_ref,
                  proposal_id, error, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"oprun_{operator}_live",
                    "profile_news_research_001",
                    None,
                    operator,
                    operator,
                    "succeeded",
                    "2026-06-03T00:00:00Z",
                    "2026-06-03T00:00:01Z",
                    str(operator_dir / "evidence-bundle.json"),
                    str(operator_dir / "operator-instructions.md"),
                    str(raw_output),
                    proposal_id,
                    None,
                    json.dumps(
                        {
                            "attempt_results": [{"attempt": 1, "status": "succeeded"}],
                            "max_retries": 1,
                        },
                        sort_keys=True,
                    ),
                    "2026-06-03T00:00:00Z",
                    "2026-06-03T00:00:01Z",
                ),
            )


def write_retained_operator_failure_evidence(output_dir: Path, operators: tuple[str, ...]) -> None:
    output_dir.mkdir(parents=True)
    db_path = output_dir / "smoke.db"
    initialize_database(db_path)
    with connect(db_path) as connection:
        _insert_smoke_profile(connection)
        for operator in operators:
            operator_dir = output_dir / operator
            operator_dir.mkdir()
            raw_output = operator_dir / "operator-output.txt"
            raw_output.write_text("not valid proposal output\n")
            connection.execute(
                """
                INSERT INTO operator_runs (
                  id, profile_id, adapter_id, operator_label, operator_kind, status,
                  started_at, ended_at, evidence_ref, prompt_ref, raw_output_ref,
                  proposal_id, error, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"oprun_{operator}_failure",
                    "profile_news_research_001",
                    None,
                    operator,
                    operator,
                    "failed",
                    "2026-06-03T00:00:00Z",
                    "2026-06-03T00:00:01Z",
                    str(operator_dir / "evidence-bundle.json"),
                    str(operator_dir / "operator-instructions.md"),
                    str(raw_output),
                    None,
                    "operator_output_must_contain_exactly_one_proposal_block",
                    json.dumps(
                        {
                            "attempt_results": [{"attempt": 1, "status": "invalid_output"}],
                            "max_retries": 0,
                        },
                        sort_keys=True,
                    ),
                    "2026-06-03T00:00:00Z",
                    "2026-06-03T00:00:01Z",
                ),
            )


def write_retained_judge_provider_evidence(output_dir: Path) -> None:
    output_dir.mkdir(parents=True)
    db_path = output_dir / "smoke.db"
    initialize_database(db_path)
    request_path = output_dir / "judge-request.json"
    raw_output_path = output_dir / "judge-command-output.txt"
    result_path = output_dir / "judge-result.json"
    handoff_path = output_dir / "judge-command.handoff.json"
    request_path.write_text("{}\n")
    raw_output_path.write_text("BEGIN_KYOKO_JUDGE_RESULT_JSON\n{}\n")
    result_path.write_text(
        json.dumps(
            {
                "schema_version": "kyoko.judge_result.v1",
                "judgment": {
                    "verdict": "passed",
                    "judge": "claude_live_judge_smoke",
                    "score": 0.9,
                    "reasoning": "Sufficient evidence.",
                    "evidence_refs": [],
                },
                "metadata": {"provider": "claude"},
            },
            sort_keys=True,
        )
        + "\n"
    )
    handoff_path.write_text(
        json.dumps(
            {
                "schema_version": "kyoko.judge_smoke_handoff.v1",
                "db_path": str(db_path),
                "provider_backed": True,
                "external_model_invoked": True,
                "prepare_only": False,
                "artifacts": {
                    "request_path": str(request_path),
                    "raw_output_path": str(raw_output_path),
                    "result_path": str(result_path),
                },
            },
            sort_keys=True,
        )
        + "\n"
    )
    with connect(db_path) as connection:
        _insert_smoke_profile(connection)
        connection.execute(
            """
            INSERT INTO check_specs (
              id, profile_id, proposal_id, name, check_type, trust_level,
              side_effect_mode, target_json, definition_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "check_judge_smoke_001",
                "profile_news_research_001",
                None,
                "judge smoke",
                "judge",
                "L0_generated",
                "none",
                json.dumps({"entity_type": "span", "entity_id": "span_001"}),
                json.dumps({}),
                "active",
                "2026-06-03T00:00:00Z",
                "2026-06-03T00:00:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO check_runs (
              id, profile_id, check_spec_id, proposal_id, replay_run_id, status,
              started_at, ended_at, result_json, artifact_refs_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "checkrun_judge_smoke_001",
                "profile_news_research_001",
                "check_judge_smoke_001",
                None,
                None,
                "passed",
                "2026-06-03T00:00:00Z",
                "2026-06-03T00:00:01Z",
                json.dumps({"check_type": "judge", "judge_backend": "external_command"}),
                json.dumps([]),
                "2026-06-03T00:00:00Z",
                "2026-06-03T00:00:01Z",
            ),
        )


def write_retained_ace_native_provider_evidence(output_dir: Path) -> None:
    output_dir.mkdir(parents=True)
    proposal_output_dir = output_dir / "proposals"
    proposal_output_dir.mkdir()
    db_path = output_dir / "kyoko.db"
    before_path = output_dir / "before.skillbook.json"
    after_path = output_dir / "after.skillbook.json"
    handoff_path = output_dir / "ace-command.handoff.json"
    stdout_path = output_dir / "ace-command.stdout.txt"
    stderr_path = output_dir / "ace-command.stderr.txt"
    report_path = output_dir / ACE_NATIVE_RUN_REPORT_FILENAME
    proposal_id = "proposal_native_ace_provider_live_001"

    initialize_database(db_path)
    with connect(db_path) as connection:
        _insert_smoke_profile(connection)
        _insert_smoke_proposal(connection, proposal_id)

    before_path.write_text('{"schema_version":"2","skills":{},"sections":{}}\n')
    after_path.write_text(
        '{"schema_version":"2","skills":{"context-00001":{}},"sections":{"context":["context-00001"]}}\n'
    )
    handoff_path.write_text(
        json.dumps(
            {
                "prepare_only": True,
                "provider_backed": True,
                "external_command_invoked": False,
                "external_model_invoked": False,
                "db_path": str(db_path),
            },
            sort_keys=True,
        )
        + "\n"
    )
    stdout_path.write_text("BEGIN_KYOKO_ACE_SKILL_JSON\n{}\nEND_KYOKO_ACE_SKILL_JSON\n")
    stderr_path.write_text("")
    (proposal_output_dir / f"{proposal_id}.json").write_text("{}\n")
    report_path.write_text(
        json.dumps(
            {
                "profile_id": "profile_news_research_001",
                "db_path": str(db_path),
                "output_dir": str(output_dir),
                "before_path": str(before_path),
                "after_path": str(after_path),
                "proposal_output_dir": str(proposal_output_dir),
                "handoff_path": str(handoff_path),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
                "report_path": str(report_path),
                "returncode": 0,
                "prepare_only": False,
                "prepared": True,
                "external_command_invoked": True,
                "provider_backed": True,
                "external_model_invoked": True,
                "live_operator_invoked": False,
                "canonical_mutation": False,
                "passed": True,
                "diff": {
                    "persisted": True,
                    "profile_id": "profile_news_research_001",
                    "proposal_ids": [proposal_id],
                    "proposal_paths": [str(proposal_output_dir / f"{proposal_id}.json")],
                    "unsupported_changes": [],
                },
            },
            sort_keys=True,
        )
        + "\n"
    )


def _insert_smoke_profile(connection) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO profiles (id, name, root_path, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "profile_news_research_001",
            "news-research",
            ".",
            "active",
            "2026-06-03T00:00:00Z",
            "2026-06-03T00:00:00Z",
        ),
    )


def _insert_smoke_proposal(connection, proposal_id: str) -> None:
    connection.execute(
        """
        INSERT INTO learning_proposals (
          id, schema_version, profile_id, producer_json, state, section, title, summary,
          confidence, evidence_refs_json, problem_json, insight, proposed_changes_json,
          gate_expectations_json, validation_errors_json, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposal_id,
            "kyoko.learning_proposal.v1",
            "profile_news_research_001",
            json.dumps({"name": "operator"}),
            "proposed",
            "context",
            "Retained smoke proposal",
            "Retained live smoke proposal.",
            0.6,
            json.dumps([]),
            json.dumps({"target": {"entity_type": "span", "entity_id": "span_001"}}),
            "Retained evidence.",
            json.dumps([]),
            json.dumps([]),
            json.dumps([]),
            "2026-06-03T00:00:00Z",
            "2026-06-03T00:00:00Z",
        ),
    )


class DoctorTests(unittest.TestCase):
    def test_doctor_package_metadata_passes_from_source_checkout(self) -> None:
        with patch(
            "kyoko.doctor.importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            check = _check_package_metadata()

        self.assertEqual(check.status, "pass")
        self.assertEqual(check.detail["source"], "source_checkout")
        self.assertEqual(check.detail["name"], "kyoko")
        self.assertEqual(check.detail["version"], check.detail["module_version"])

    def test_doctor_reports_local_readiness(self) -> None:
        report = run_doctor()
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["python"].status, "pass")
        self.assertEqual(checks["sqlite"].status, "pass")
        self.assertEqual(checks["bundled_assets"].status, "pass")
        self.assertIn(
            "learning-proposals/hermes-one-shot-proposal.json",
            checks["bundled_assets"].detail["assets"],
        )
        self.assertIn(
            "learning-proposals/openclaw-local-operator-proposal.json",
            checks["bundled_assets"].detail["assets"],
        )
        self.assertIn(
            "learning-proposals/valid-harness-proposal.json",
            checks["bundled_assets"].detail["assets"],
        )
        self.assertIn(
            "learning-proposals/valid-harness-generated-file-proposal.json",
            checks["bundled_assets"].detail["assets"],
        )
        self.assertIn(
            "learning-proposals/invalid-hallucinated-span.json",
            checks["bundled_assets"].detail["assets"],
        )
        self.assertEqual(checks["fixture_replay"].status, "pass")
        self.assertEqual(checks["fixture_replay_server"].status, "pass")
        self.assertEqual(checks["sqlite"].detail["temporary"], True)
        self.assertIn("release_python_targets", checks)
        self.assertIn("mcp_clients", checks)
        self.assertEqual(
            checks["release_python_targets"].detail["matrix_command"],
            "python3 -m kyoko release-smoke --python-matrix --artifact both --json",
        )
        self.assertIn("missing_targets", checks["release_python_targets"].detail)
        self.assertIn("ready_targets", checks["release_python_targets"].detail)
        self.assertIn("unready_targets", checks["release_python_targets"].detail)
        self.assertIn("ready_matrix_command", checks["release_python_targets"].detail)
        self.assertEqual(
            checks["mcp_clients"].detail["matrix_command"],
            "python3 -m kyoko mcp install-smoke --all-targets --json",
        )
        readiness = report.to_json()["readiness"]
        self.assertTrue(readiness["local_runtime_ready"])
        self.assertFalse(readiness["local_v0_ready"])
        self.assertFalse(readiness["safe_smokes_complete"])
        self.assertEqual(
            readiness["pending_safe_smoke_checks"],
            [
                "demo_smoke",
                "operator_smoke_prepare",
                "judge_smoke_prepare",
                "ace_native_prepare",
                "integration_smoke",
                "improve_smoke",
                "mcp_install_smoke",
            ],
        )
        self.assertEqual(readiness["blocking_checks"], [])
        suggestions = {command["intent"]: command for command in report.to_json()["suggested_commands"]}
        self.assertEqual(
            suggestions["doctor_safe_smokes"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--safe-smokes", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_smoke_demo"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--smoke-demo", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_operator_smoke_prepare"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--operator-smoke-prepare", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_judge_smoke_prepare"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--judge-smoke-prepare", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_ace_native_prepare"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--ace-native-prepare", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_integration_smoke"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--integration-smoke", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_improve_smoke"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--improve-smoke", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_opentelemetry_smoke"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--opentelemetry-smoke", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_ace_native_smoke"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--ace-native-smoke", "--json"],
        )
        self.assertEqual(
            suggestions["doctor_dashboard_smoke"]["cli_args"],
            ["python3", "-m", "kyoko", "doctor", "--dashboard-smoke", "--json"],
        )
        self.assertFalse(suggestions["doctor_smoke_demo"]["mutating"])

        text = doctor_report_text(report)
        self.assertIn("PASS: python", text)
        self.assertIn("readiness: local_runtime_ready=true", text)
        self.assertIn("local_v0_ready=false", text)
        self.assertIn(
            "pending_safe_smoke_checks: demo_smoke, operator_smoke_prepare, "
            "judge_smoke_prepare, ace_native_prepare, integration_smoke, improve_smoke, "
            "mcp_install_smoke",
            text,
        )
        self.assertIn("suggested_commands:", text)
        self.assertIn("doctor_safe_smokes: python3 -m kyoko doctor --safe-smokes --json", text)
        self.assertIn(
            "doctor_opentelemetry_smoke: python3 -m kyoko doctor --opentelemetry-smoke --json",
            text,
        )
        self.assertIn(
            "doctor_dashboard_smoke: python3 -m kyoko doctor --dashboard-smoke --json",
            text,
        )
        if "release_smoke_matrix" in suggestions:
            self.assertIn("release_smoke_matrix: python3 -m kyoko release-smoke", text)
        else:
            self.assertEqual(checks["release_python_targets"].status, "pass")
            self.assertNotIn("release_smoke_matrix:", text)
        self.assertIn("requires: ", text)
        self.assertIn("overall: ok", text)

    def test_doctor_suggests_live_operator_smoke_for_available_operator_commands(self) -> None:
        def fake_which(command: str):
            return {
                "codex": "/usr/local/bin/codex",
                "claude": "/usr/local/bin/claude",
                "hermes": None,
                "openclaw": None,
                "python3.10": None,
                "python3.11": None,
                "python3.12": None,
            }.get(command)

        with patch("kyoko.doctor.shutil.which", side_effect=fake_which):
            report = run_doctor()

        payload = report.to_json()
        suggestions = {command["intent"]: command for command in payload["suggested_commands"]}
        command = suggestions["operator_smoke_live_installed_presets"]
        self.assertEqual(
            command["cli_args"],
            [
                "python3",
                "-m",
                "kyoko",
                "operator-smoke",
                "--all-presets",
                "--output-dir",
                ".kyoko/smoke/operator-live",
                "--json",
            ],
        )
        self.assertTrue(command["mutating"])
        self.assertIn(
            "installed/authenticated operator CLI: claude, codex",
            command["requires"],
        )
        self.assertIn("invokes live operator model/subscription", command["requires"])
        self.assertIn(
            "operator_smoke_live_installed_presets",
            payload["readiness"]["pending_external_evidence_commands"],
        )
        failure_command = suggestions["operator_smoke_live_expected_failure_installed_presets"]
        self.assertEqual(
            failure_command["cli_args"],
            [
                "python3",
                "-m",
                "kyoko",
                "operator-smoke",
                "--all-presets",
                "--expect-failure",
                "--output-dir",
                ".kyoko/smoke/operator-failure-live",
                "--json",
            ],
        )
        self.assertTrue(failure_command["mutating"])
        self.assertIn(
            "passes only when the expected failure kind is captured",
            failure_command["requires"],
        )
        self.assertIn(
            "operator_smoke_live_expected_failure_installed_presets",
            payload["readiness"]["pending_external_evidence_commands"],
        )

    def test_doctor_uses_retained_external_evidence_to_filter_live_followups(self) -> None:
        def fake_which(command: str):
            return {
                "codex": "/usr/local/bin/codex",
                "claude": "/usr/local/bin/claude",
                "hermes": None,
                "openclaw": None,
                "python3.10": None,
                "python3.11": None,
                "python3.12": None,
            }.get(command)

        with TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "smoke"
            write_retained_operator_success_evidence(
                evidence_dir / "operator-live-latest",
                ("codex", "claude"),
            )
            write_retained_operator_failure_evidence(
                evidence_dir / "operator-failure-live-latest",
                ("codex", "claude"),
            )
            write_retained_judge_provider_evidence(evidence_dir / "judge-provider-live")
            write_retained_ace_native_provider_evidence(evidence_dir / "ace-provider-live")

            with patch("kyoko.doctor.shutil.which", side_effect=fake_which):
                report = run_doctor(smoke_evidence_dir=evidence_dir)

        payload = report.to_json()
        suggestions = {command["intent"] for command in payload["suggested_commands"]}
        readiness = payload["readiness"]

        self.assertNotIn("operator_smoke_live_installed_presets", suggestions)
        self.assertNotIn("operator_smoke_live_expected_failure_installed_presets", suggestions)
        self.assertNotIn("judge_smoke_live_provider_backed", suggestions)
        self.assertEqual(
            readiness["satisfied_external_evidence_commands"],
            [
                "operator_smoke_live_installed_presets",
                "operator_smoke_live_expected_failure_installed_presets",
                "judge_smoke_live_provider_backed",
                "ace_native_run_provider_backed",
            ],
        )
        self.assertNotIn(
            "operator_smoke_live_installed_presets",
            readiness["pending_external_evidence_commands"],
        )
        self.assertNotIn(
            "operator_smoke_live_expected_failure_installed_presets",
            readiness["pending_external_evidence_commands"],
        )
        self.assertNotIn(
            "judge_smoke_live_provider_backed",
            readiness["pending_external_evidence_commands"],
        )
        self.assertEqual(
            [evidence["intent"] for evidence in payload["retained_external_evidence"]],
            readiness["satisfied_external_evidence_commands"],
        )
        text = doctor_report_text(report)
        self.assertIn(
            "satisfied_external_evidence_commands: "
            "operator_smoke_live_installed_presets, "
            "operator_smoke_live_expected_failure_installed_presets, "
            "judge_smoke_live_provider_backed, "
            "ace_native_run_provider_backed",
            text,
        )

    def test_release_python_target_check_reports_actionable_matrix_detail(self) -> None:
        def fake_which(command: str):
            return {
                "python3.12": "/opt/python/3.12/bin/python3.12",
                "python3.13": None,
            }.get(command)

        def fake_build_backend_reason(
            *,
            python_executable: str,
            timeout_seconds: int,
        ):
            return "python_build_backend_unavailable:setuptools.build_meta"

        with patch("kyoko.doctor.shutil.which", side_effect=fake_which):
            with patch(
                "kyoko.doctor.python_build_backend_reason",
                side_effect=fake_build_backend_reason,
            ):
                check = _check_release_python_targets()

        self.assertEqual(check.status, "warn")
        self.assertEqual(check.detail["missing_targets"], ["3.13"])
        self.assertEqual(check.detail["ready_targets"], ["3.12"])
        self.assertEqual(check.detail["bootstrap_required_targets"], ["3.12"])
        self.assertEqual(check.detail["unready_targets"], {})
        self.assertEqual(
            check.detail["ready_matrix_command"],
            "python3 -m kyoko release-smoke --python-target 3.12 --artifact both --json",
        )
        self.assertEqual(check.detail["build_backend_install_commands"], {})

    def test_doctor_smoke_demo_runs_bundled_loop(self) -> None:
        report = run_doctor(smoke_demo=True)
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["demo_smoke"].status, "pass")
        self.assertEqual(checks["demo_smoke"].detail["check_status"], "passed")
        self.assertEqual(checks["demo_smoke"].detail["promoted_trust_level"], "L2_regression")
        self.assertEqual(
            checks["demo_smoke"].detail["applied_skill_ids"],
            ["skill_proposal_context_timeout_001_1"],
        )

    def test_doctor_operator_smoke_prepare_runs_safe_matrix(self) -> None:
        fake_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex", "claude", "hermes", "openclaw"],
                "prepare_only": True,
                "summary": {
                    "total": 4,
                    "prepared": 2,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 2,
                    "available": 2,
                },
                "targets": [],
            }
        )

        with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_report) as smoke:
            report = run_doctor(operator_smoke_prepare=True)
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["operator_smoke_prepare"].status, "pass")
        self.assertFalse(checks["operator_smoke_prepare"].detail["live_operator_invoked"])
        self.assertEqual(
            checks["operator_smoke_prepare"].detail["matrix_command"],
            "python3 -m kyoko operator-smoke --all-presets --prepare-only --json",
        )
        self.assertTrue(smoke.call_args.kwargs["prepare_only"])

    def test_doctor_operator_smoke_prepare_retains_requested_output_dir(self) -> None:
        fake_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex"],
                "prepare_only": True,
                "summary": {
                    "total": 1,
                    "prepared": 1,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "available": 1,
                },
                "targets": [],
            }
        )

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_report) as smoke:
                report = run_doctor(
                    operator_smoke_prepare=True,
                    smoke_output_dir=output_dir,
                )
        checks = {check.id: check for check in report.checks}

        self.assertEqual(
            smoke.call_args.kwargs["output_dir"],
            output_dir / "operator-smoke-prepare",
        )
        self.assertFalse(checks["operator_smoke_prepare"].detail["temporary"])
        self.assertTrue(checks["operator_smoke_prepare"].detail["artifacts_retained"])

    def test_doctor_operator_smoke_prepare_warns_when_all_presets_missing(self) -> None:
        fake_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex", "claude", "hermes", "openclaw"],
                "prepare_only": True,
                "summary": {
                    "total": 4,
                    "prepared": 0,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 4,
                    "available": 0,
                },
                "targets": [],
            }
        )

        with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_report):
            report = run_doctor(operator_smoke_prepare=True)
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["operator_smoke_prepare"].status, "warn")

    def test_doctor_integration_smoke_runs_generated_contracts(self) -> None:
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1, "spans": 1},
                "status": {"counts": {"runs": 1, "spans": 1}},
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "replay_ok": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
            }
        )

        with patch("kyoko.doctor.write_source_adapter_template") as source_template:
            with patch("kyoko.doctor.write_replay_server_template") as replay_template:
                with patch(
                    "kyoko.doctor.run_source_adapter_smoke",
                    return_value=source_report,
                ) as source_smoke:
                    with patch(
                        "kyoko.doctor.run_replay_server_smoke",
                        return_value=replay_report,
                    ) as replay_smoke:
                        report = run_doctor(integration_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["integration_smoke"].status, "pass")
        self.assertFalse(checks["integration_smoke"].detail["live_operator_invoked"])
        self.assertEqual(
            checks["integration_smoke"].detail["source_adapter"]["status_counts"]["runs"],
            1,
        )
        self.assertTrue(checks["integration_smoke"].detail["replay_server"]["healthy"])
        self.assertTrue(checks["integration_smoke"].detail["replay_server"]["replay_ok"])
        self.assertEqual(source_template.call_args.kwargs["framework"], "langgraph-python")
        self.assertTrue(source_template.call_args.kwargs["force"])
        self.assertEqual(replay_template.call_args.kwargs["framework"], "generic-python")
        self.assertTrue(replay_template.call_args.kwargs["force"])
        self.assertEqual(source_smoke.call_args.kwargs["profile_id"], "profile_doctor_integration_smoke")
        self.assertTrue(replay_smoke.call_args.kwargs["server_url"].startswith("http://127.0.0.1:"))
        self.assertTrue(replay_smoke.call_args.kwargs["run_replay"])
        self.assertIn("doctor_replay_hook.py", replay_smoke.call_args.kwargs["replay_hook"])

    def test_doctor_integration_smoke_retains_requested_output_dir(self) -> None:
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1},
                "status": {"counts": {"runs": 1}},
                "source_events_path": "/tmp/source-events.json",
                "stdout_path": "/tmp/source.stdout",
                "stderr_path": "/tmp/source.stderr",
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
                "state_path": "/tmp/replay.state",
                "stdout_path": "/tmp/replay.stdout",
                "stderr_path": "/tmp/replay.stderr",
            }
        )

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            with patch("kyoko.doctor.write_source_adapter_template"):
                with patch("kyoko.doctor.write_replay_server_template"):
                    with patch("kyoko.doctor.run_source_adapter_smoke", return_value=source_report):
                        with patch("kyoko.doctor.run_replay_server_smoke", return_value=replay_report):
                            report = run_doctor(
                                integration_smoke=True,
                                smoke_output_dir=output_dir,
                            )
        checks = {check.id: check for check in report.checks}
        detail = checks["integration_smoke"].detail

        self.assertFalse(detail["temporary"])
        self.assertTrue(detail["artifacts_retained"])
        self.assertEqual(detail["output_dir"], str(output_dir / "integration-smoke"))
        self.assertEqual(
            detail["source_adapter"]["source_events_path"],
            "/tmp/source-events.json",
        )
        self.assertEqual(detail["replay_server"]["state_path"], "/tmp/replay.state")

    def test_doctor_integration_smoke_failure_is_readiness_failure(self) -> None:
        with patch("kyoko.doctor.write_source_adapter_template"):
            with patch(
                "kyoko.doctor.run_source_adapter_smoke",
                side_effect=IntegrationSmokeError("source_adapter_failed:1"),
            ):
                report = run_doctor(integration_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertFalse(report.ok)
        self.assertEqual(checks["integration_smoke"].status, "fail")
        self.assertIn("source_adapter_failed:1", checks["integration_smoke"].message)

    def test_doctor_improve_smoke_runs_generated_improve_loop(self) -> None:
        def fake_improve(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_improve_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_generated_improve_smoke", side_effect=fake_improve) as improve:
            report = run_doctor(improve_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["improve_smoke"].status, "pass")
        self.assertFalse(checks["improve_smoke"].detail["live_operator_invoked"])
        self.assertFalse(checks["improve_smoke"].detail["external_model_invoked"])
        self.assertTrue(checks["improve_smoke"].detail["generated_source_adapter_invoked"])
        self.assertTrue(checks["improve_smoke"].detail["managed_replay_server_invoked"])
        self.assertEqual(checks["improve_smoke"].detail["improve"]["replay_run_count"], 1)
        self.assertEqual(checks["improve_smoke"].detail["improve"]["autonomy_actions"], ["applied"])
        self.assertEqual(improve.call_args.kwargs["timeout_seconds"], 20)
        self.assertTrue(str(improve.call_args.kwargs["schema_path"]).endswith("learning-proposal.schema.json"))

    def test_doctor_eval_smoke_runs_bundled_detector(self) -> None:
        report = run_doctor(eval_smoke=True)
        checks = {check.id: check for check in report.checks}
        self.assertIn("eval_smoke", checks)
        self.assertEqual(checks["eval_smoke"].status, "pass")
        agg = checks["eval_smoke"].detail["aggregate"]
        self.assertEqual(agg["numerator"], 1)
        self.assertEqual(agg["denominator"], 2)

    def test_doctor_eval_smoke_absent_by_default(self) -> None:
        report = run_doctor()
        self.assertNotIn("eval_smoke", {check.id for check in report.checks})

    def test_doctor_improve_smoke_retains_requested_output_dir(self) -> None:
        def fake_improve(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_improve_smoke_report(output_dir, db_path=db_path)

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            with patch("kyoko.doctor.run_generated_improve_smoke", side_effect=fake_improve):
                report = run_doctor(
                    improve_smoke=True,
                    smoke_output_dir=output_dir,
                )
        checks = {check.id: check for check in report.checks}
        detail = checks["improve_smoke"].detail

        self.assertFalse(detail["temporary"])
        self.assertTrue(detail["artifacts_retained"])
        self.assertEqual(detail["output_dir"], str(output_dir / "improve-smoke"))
        self.assertEqual(detail["db_path"], str(output_dir / "improve-smoke" / "doctor-improve.db"))

    def test_doctor_improve_smoke_failure_is_readiness_failure(self) -> None:
        with patch(
            "kyoko.doctor.run_generated_improve_smoke",
            side_effect=ImproveSmokeError("replay_failed"),
        ):
            report = run_doctor(improve_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertFalse(report.ok)
        self.assertEqual(checks["improve_smoke"].status, "fail")
        self.assertIn("replay_failed", checks["improve_smoke"].message)

    def test_doctor_ace_native_smoke_runs_installed_ace_boundary(self) -> None:
        def fake_ace_smoke(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_ace_native_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_legacy_ace_offline_adapter_smoke", side_effect=fake_ace_smoke) as smoke:
            report = run_doctor(ace_native_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["ace_native_smoke"].status, "pass")
        self.assertTrue(checks["ace_native_smoke"].detail["external_command_invoked"])
        self.assertTrue(checks["ace_native_smoke"].detail["installed_ace_package_invoked"])
        self.assertFalse(checks["ace_native_smoke"].detail["provider_backed"])
        self.assertFalse(checks["ace_native_smoke"].detail["external_model_invoked"])
        self.assertEqual(checks["ace_native_smoke"].detail["proposal_ids"], ["proposal_native_ace_smoke"])
        self.assertEqual(smoke.call_args.kwargs["timeout_seconds"], 30)
        self.assertTrue(str(smoke.call_args.kwargs["schema_path"]).endswith("learning-proposal.schema.json"))

    def test_doctor_ace_native_smoke_retains_requested_output_dir(self) -> None:
        def fake_ace_smoke(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_ace_native_smoke_report(output_dir, db_path=db_path)

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            with patch("kyoko.doctor.run_legacy_ace_offline_adapter_smoke", side_effect=fake_ace_smoke):
                report = run_doctor(
                    ace_native_smoke=True,
                    smoke_output_dir=output_dir,
                )
        checks = {check.id: check for check in report.checks}
        detail = checks["ace_native_smoke"].detail

        self.assertFalse(detail["temporary"])
        self.assertTrue(detail["artifacts_retained"])
        self.assertEqual(detail["output_dir"], str(output_dir / "ace-native-smoke"))
        self.assertEqual(
            detail["db_path"],
            str(output_dir / "ace-native-smoke" / "doctor-ace-native.db"),
        )

    def test_doctor_ace_native_prepare_writes_handoff_without_invoking_ace(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            report = run_doctor(
                ace_native_prepare=True,
                smoke_output_dir=output_dir,
            )
            checks = {check.id: check for check in report.checks}
            detail = checks["ace_native_prepare"].detail

            self.assertTrue(report.ok)
            self.assertEqual(checks["ace_native_prepare"].status, "pass")
            self.assertFalse(detail["temporary"])
            self.assertTrue(detail["artifacts_retained"])
            self.assertEqual(detail["output_dir"], str(output_dir / "ace-native-prepare"))
            self.assertEqual(
                detail["db_path"],
                str(output_dir / "ace-native-prepare" / "doctor-ace-native-prepare.db"),
            )
            self.assertTrue(Path(detail["before_path"]).exists())
            self.assertTrue(Path(detail["after_path"]).exists())
            self.assertTrue(Path(detail["handoff_path"]).exists())
            self.assertTrue(detail["prepare_only"])
            self.assertTrue(detail["prepared"])
            self.assertTrue(detail["passed"])
            self.assertFalse(detail["external_command_invoked"])
            self.assertTrue(detail["provider_backed"])
            self.assertFalse(detail["external_model_invoked"])
            self.assertFalse(detail["canonical_mutation"])
            self.assertIn("KYOKO_ACE_AFTER_PATH", detail["environment_keys"])
            self.assertEqual(detail["before_schema_version"], "2")

    def test_doctor_ace_native_smoke_failure_is_readiness_failure(self) -> None:
        with patch(
            "kyoko.doctor.run_legacy_ace_offline_adapter_smoke",
            side_effect=AceBridgeError("ace_command_failed:1"),
        ):
            report = run_doctor(ace_native_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertFalse(report.ok)
        self.assertEqual(checks["ace_native_smoke"].status, "fail")
        self.assertIn("ace_command_failed:1", checks["ace_native_smoke"].message)

    def test_doctor_opentelemetry_smoke_runs_sdk_ingest(self) -> None:
        def fake_opentelemetry(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_opentelemetry_smoke_report(output_dir, db_path=db_path)

        python_executable = Path("/tmp/otel-venv/bin/python")
        with patch("kyoko.doctor.run_opentelemetry_sdk_smoke", side_effect=fake_opentelemetry) as smoke:
            report = run_doctor(
                opentelemetry_smoke=True,
                opentelemetry_python_executable=python_executable,
            )
        checks = {check.id: check for check in report.checks}
        detail = checks["opentelemetry_smoke"].detail

        self.assertTrue(report.ok)
        self.assertEqual(checks["opentelemetry_smoke"].status, "pass")
        self.assertTrue(detail["opentelemetry_sdk_invoked"])
        self.assertFalse(detail["external_model_invoked"])
        self.assertFalse(detail["live_operator_invoked"])
        self.assertEqual(detail["opentelemetry_sdk_version"], "9.9.0")
        self.assertEqual(detail["run_count"], 1)
        self.assertEqual(detail["span_count"], 2)
        self.assertEqual(detail["ingested_counts"]["timeline_events"], 1)
        self.assertEqual(smoke.call_args.kwargs["python_executable"], python_executable)
        self.assertEqual(smoke.call_args.kwargs["timeout_seconds"], 30)

    def test_doctor_opentelemetry_smoke_retains_requested_output_dir(self) -> None:
        def fake_opentelemetry(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_opentelemetry_smoke_report(output_dir, db_path=db_path)

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            with patch("kyoko.doctor.run_opentelemetry_sdk_smoke", side_effect=fake_opentelemetry):
                report = run_doctor(
                    opentelemetry_smoke=True,
                    smoke_output_dir=output_dir,
                )
        checks = {check.id: check for check in report.checks}
        detail = checks["opentelemetry_smoke"].detail

        self.assertFalse(detail["temporary"])
        self.assertTrue(detail["artifacts_retained"])
        self.assertEqual(detail["output_dir"], str(output_dir / "opentelemetry-smoke"))
        self.assertEqual(
            detail["db_path"],
            str(output_dir / "opentelemetry-smoke" / "doctor-opentelemetry.db"),
        )

    def test_doctor_opentelemetry_smoke_failure_is_readiness_failure(self) -> None:
        with patch(
            "kyoko.doctor.run_opentelemetry_sdk_smoke",
            side_effect=OtlpSmokeError("opentelemetry_sdk_not_importable"),
        ):
            report = run_doctor(opentelemetry_smoke=True)
        checks = {check.id: check for check in report.checks}

        self.assertFalse(report.ok)
        self.assertEqual(checks["opentelemetry_smoke"].status, "fail")
        self.assertIn("opentelemetry_sdk_not_importable", checks["opentelemetry_smoke"].message)

    def test_doctor_safe_smokes_runs_all_no_live_model_checks(self) -> None:
        fake_operator_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex"],
                "prepare_only": True,
                "summary": {
                    "total": 1,
                    "prepared": 1,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "available": 1,
                },
                "targets": [],
            }
        )
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1},
                "status": {"counts": {"runs": 1}},
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
            }
        )

        def fake_mcp_smoke(*, output_dir: Path, **kwargs):
            return fake_mcp_install_smoke_report(output_dir)

        def fake_improve(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_improve_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_demo_setup") as demo:
            demo.return_value.check_status = "passed"
            demo.return_value.promoted_trust_level = "L2_regression"
            demo.return_value.applied_skill_ids = ("skill_demo",)
            with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_operator_report):
                with patch("kyoko.doctor.write_source_adapter_template"):
                    with patch("kyoko.doctor.write_replay_server_template"):
                        with patch("kyoko.doctor.run_source_adapter_smoke", return_value=source_report):
                            with patch("kyoko.doctor.run_replay_server_smoke", return_value=replay_report):
                                with patch("kyoko.doctor.run_generated_improve_smoke", side_effect=fake_improve):
                                    with patch(
                                        "kyoko.mcp.run_mcp_install_smoke_matrix",
                                        side_effect=fake_mcp_smoke,
                                    ) as mcp_smoke:
                                        report = run_doctor(safe_smokes=True)
        checks = {check.id: check for check in report.checks}
        intents = {command["intent"] for command in report.to_json()["suggested_commands"]}

        self.assertTrue(report.ok)
        self.assertEqual(checks["demo_smoke"].status, "pass")
        self.assertEqual(checks["operator_smoke_prepare"].status, "pass")
        self.assertEqual(checks["judge_smoke_prepare"].status, "pass")
        self.assertEqual(checks["ace_native_prepare"].status, "pass")
        self.assertEqual(checks["integration_smoke"].status, "pass")
        self.assertEqual(checks["improve_smoke"].status, "pass")
        self.assertEqual(checks["mcp_install_smoke"].status, "pass")
        self.assertEqual(
            mcp_smoke.call_args.kwargs["schema_path"],
            bundled_asset_path("schemas/learning-proposal.schema.json"),
        )
        self.assertNotIn("doctor_safe_smokes", intents)
        self.assertNotIn("doctor_smoke_demo", intents)
        self.assertNotIn("doctor_operator_smoke_prepare", intents)
        self.assertNotIn("doctor_judge_smoke_prepare", intents)
        self.assertNotIn("doctor_ace_native_prepare", intents)
        self.assertNotIn("doctor_integration_smoke", intents)
        self.assertNotIn("doctor_improve_smoke", intents)
        self.assertIn("doctor_opentelemetry_smoke", intents)
        self.assertIn("doctor_ace_native_smoke", intents)
        self.assertNotIn("mcp_install_smoke_matrix", intents)
        readiness = report.to_json()["readiness"]
        self.assertTrue(readiness["safe_smokes_complete"])
        self.assertTrue(readiness["local_v0_ready"])
        self.assertEqual(readiness["pending_safe_smoke_checks"], [])

    def test_doctor_safe_smokes_retains_demo_database(self) -> None:
        fake_operator_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex"],
                "prepare_only": True,
                "summary": {
                    "total": 1,
                    "prepared": 1,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "available": 1,
                },
                "targets": [],
            }
        )
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1},
                "status": {"counts": {"runs": 1}},
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
            }
        )

        def fake_mcp_smoke(*, output_dir: Path, **kwargs):
            return fake_mcp_install_smoke_report(output_dir)

        def fake_improve(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_improve_smoke_report(output_dir, db_path=db_path)

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "smoke-artifacts"
            with patch("kyoko.doctor.run_demo_setup") as demo:
                demo.return_value.check_status = "passed"
                demo.return_value.promoted_trust_level = "L2_regression"
                demo.return_value.applied_skill_ids = ("skill_demo",)
                with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_operator_report):
                    with patch("kyoko.doctor.write_source_adapter_template"):
                        with patch("kyoko.doctor.write_replay_server_template"):
                            with patch("kyoko.doctor.run_source_adapter_smoke", return_value=source_report):
                                with patch("kyoko.doctor.run_replay_server_smoke", return_value=replay_report):
                                    with patch("kyoko.doctor.run_generated_improve_smoke", side_effect=fake_improve):
                                        with patch(
                                            "kyoko.mcp.run_mcp_install_smoke_matrix",
                                            side_effect=fake_mcp_smoke,
                                        ):
                                            report = run_doctor(
                                                safe_smokes=True,
                                                smoke_output_dir=output_dir,
                                            )
        checks = {check.id: check for check in report.checks}

        self.assertFalse(checks["demo_smoke"].detail["temporary"])
        self.assertTrue(checks["demo_smoke"].detail["artifacts_retained"])
        self.assertEqual(
            checks["demo_smoke"].detail["db_path"],
            str(output_dir / "demo" / "doctor-demo.db"),
        )
        self.assertFalse(checks["mcp_install_smoke"].detail["temporary"])
        self.assertTrue(checks["mcp_install_smoke"].detail["artifacts_retained"])
        self.assertEqual(
            checks["mcp_install_smoke"].detail["output_dir"],
            str(output_dir / "mcp-install-smoke"),
        )
        self.assertFalse(checks["judge_smoke_prepare"].detail["temporary"])
        self.assertTrue(checks["judge_smoke_prepare"].detail["artifacts_retained"])
        self.assertEqual(
            checks["judge_smoke_prepare"].detail["output_dir"],
            str(output_dir / "judge-smoke-prepare"),
        )
        self.assertFalse(checks["ace_native_prepare"].detail["temporary"])
        self.assertTrue(checks["ace_native_prepare"].detail["artifacts_retained"])
        self.assertEqual(
            checks["ace_native_prepare"].detail["output_dir"],
            str(output_dir / "ace-native-prepare"),
        )
        self.assertFalse(checks["improve_smoke"].detail["temporary"])
        self.assertTrue(checks["improve_smoke"].detail["artifacts_retained"])
        self.assertEqual(
            checks["improve_smoke"].detail["output_dir"],
            str(output_dir / "improve-smoke"),
        )

    def test_doctor_cli_uses_temporary_database_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            fake_home = Path(tmpdir) / "home"
            fake_home.mkdir()
            out = io.StringIO()

            with patch.dict(os.environ, {"HOME": str(fake_home)}), redirect_stdout(out):
                exit_code = main(["doctor", "--json"])

            self.assertEqual(exit_code, 0)
            payload = json.loads(out.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIn("suggested_commands", payload)
            self.assertFalse((fake_home / ".kyoko").exists())

            checks = {check["id"]: check for check in payload["checks"]}
            self.assertEqual(checks["sqlite"]["status"], "pass")
            self.assertEqual(checks["sqlite"]["detail"]["temporary"], True)

    def test_doctor_cli_accepts_operator_smoke_prepare_flag(self) -> None:
        fake_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex"],
                "prepare_only": True,
                "summary": {
                    "total": 1,
                    "prepared": 1,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "available": 1,
                },
                "targets": [],
            }
        )
        out = io.StringIO()

        with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_report):
            with redirect_stdout(out):
                exit_code = main(["doctor", "--operator-smoke-prepare", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["operator_smoke_prepare"]["status"], "pass")

    def test_doctor_cli_accepts_judge_smoke_prepare_flag(self) -> None:
        out = io.StringIO()

        with redirect_stdout(out):
            exit_code = main(["doctor", "--judge-smoke-prepare", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["judge_smoke_prepare"]["status"], "pass")
        self.assertTrue(checks["judge_smoke_prepare"]["detail"]["prepare_only"])
        self.assertFalse(checks["judge_smoke_prepare"]["detail"]["external_command_invoked"])
        self.assertFalse(checks["judge_smoke_prepare"]["detail"]["external_model_invoked"])

    def test_doctor_cli_accepts_integration_smoke_flag(self) -> None:
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1},
                "status": {"counts": {"runs": 1}},
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
            }
        )
        out = io.StringIO()

        with patch("kyoko.doctor.write_source_adapter_template"):
            with patch("kyoko.doctor.write_replay_server_template"):
                with patch("kyoko.doctor.run_source_adapter_smoke", return_value=source_report):
                    with patch("kyoko.doctor.run_replay_server_smoke", return_value=replay_report):
                        with redirect_stdout(out):
                            exit_code = main(["doctor", "--integration-smoke", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["integration_smoke"]["status"], "pass")

    def test_doctor_cli_accepts_improve_smoke_flag(self) -> None:
        out = io.StringIO()

        def fake_improve(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_improve_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_generated_improve_smoke", side_effect=fake_improve):
            with redirect_stdout(out):
                exit_code = main(["doctor", "--improve-smoke", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["improve_smoke"]["status"], "pass")

    def test_doctor_cli_accepts_opentelemetry_smoke_flag(self) -> None:
        out = io.StringIO()
        python_executable = Path("/tmp/otel-venv/bin/python")

        def fake_opentelemetry(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_opentelemetry_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_opentelemetry_sdk_smoke", side_effect=fake_opentelemetry) as smoke:
            with redirect_stdout(out):
                exit_code = main(
                    [
                        "doctor",
                        "--opentelemetry-smoke",
                        "--opentelemetry-python-executable",
                        str(python_executable),
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["opentelemetry_smoke"]["status"], "pass")
        self.assertEqual(smoke.call_args.kwargs["python_executable"], python_executable)

    def test_doctor_cli_accepts_ace_native_smoke_flag(self) -> None:
        out = io.StringIO()

        def fake_ace_smoke(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_ace_native_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_legacy_ace_offline_adapter_smoke", side_effect=fake_ace_smoke):
            with redirect_stdout(out):
                exit_code = main(["doctor", "--ace-native-smoke", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["ace_native_smoke"]["status"], "pass")

    def test_doctor_cli_accepts_dashboard_smoke_flag(self) -> None:
        out = io.StringIO()
        output_dir = Path("/tmp/doctor-smoke")

        def fake_dashboard(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_dashboard_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.dashboard_smoke.run_dashboard_browser_smoke", side_effect=fake_dashboard) as smoke:
            with redirect_stdout(out):
                exit_code = main(
                    [
                        "doctor",
                        "--dashboard-smoke",
                        "--dashboard-smoke-screenshot",
                        "--dashboard-smoke-install-browser-deps",
                        "--dashboard-smoke-timeout",
                        "45",
                        "--smoke-output-dir",
                        str(output_dir),
                        "--json",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["dashboard_smoke"]["status"], "pass")
        self.assertEqual(checks["dashboard_smoke"]["detail"]["browser_backend"], "npx-playwright")
        self.assertTrue(smoke.call_args.kwargs["screenshot"])
        self.assertTrue(smoke.call_args.kwargs["install_browser_deps"])
        self.assertEqual(smoke.call_args.kwargs["timeout_seconds"], 45)
        self.assertEqual(smoke.call_args.kwargs["output_dir"], output_dir / "dashboard-smoke")

    def test_doctor_cli_accepts_safe_smokes_flag(self) -> None:
        fake_operator_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex"],
                "prepare_only": True,
                "summary": {
                    "total": 1,
                    "prepared": 1,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "available": 1,
                },
                "targets": [],
            }
        )
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1},
                "status": {"counts": {"runs": 1}},
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
            }
        )
        out = io.StringIO()

        def fake_mcp_smoke(*, output_dir: Path, **kwargs):
            return fake_mcp_install_smoke_report(output_dir)

        def fake_improve(*, db_path: Path, output_dir: Path, **kwargs):
            return fake_improve_smoke_report(output_dir, db_path=db_path)

        with patch("kyoko.doctor.run_demo_setup") as demo:
            demo.return_value.check_status = "passed"
            demo.return_value.promoted_trust_level = "L2_regression"
            demo.return_value.applied_skill_ids = ("skill_demo",)
            with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_operator_report):
                with patch("kyoko.doctor.write_source_adapter_template"):
                    with patch("kyoko.doctor.write_replay_server_template"):
                        with patch("kyoko.doctor.run_source_adapter_smoke", return_value=source_report):
                            with patch("kyoko.doctor.run_replay_server_smoke", return_value=replay_report):
                                with patch("kyoko.doctor.run_generated_improve_smoke", side_effect=fake_improve):
                                    with patch(
                                        "kyoko.mcp.run_mcp_install_smoke_matrix",
                                        side_effect=fake_mcp_smoke,
                                    ):
                                        with redirect_stdout(out):
                                            exit_code = main(["doctor", "--safe-smokes", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(out.getvalue())
        checks = {check["id"]: check for check in payload["checks"]}
        self.assertEqual(checks["demo_smoke"]["status"], "pass")
        self.assertEqual(checks["operator_smoke_prepare"]["status"], "pass")
        self.assertEqual(checks["ace_native_prepare"]["status"], "pass")
        self.assertEqual(checks["integration_smoke"]["status"], "pass")
        self.assertEqual(checks["improve_smoke"]["status"], "pass")
        self.assertEqual(checks["mcp_install_smoke"]["status"], "pass")

    def test_doctor_cli_accepts_smoke_output_dir(self) -> None:
        fake_report = FakeJsonReport(
            {
                "ok": True,
                "checks": [],
                "summary": {"passed": 0, "warnings": 0, "failed": 0},
                "suggested_commands": [],
            }
        )
        out = io.StringIO()

        with TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "artifacts"
            with patch("kyoko.cli.run_doctor", return_value=fake_report) as doctor:
                with redirect_stdout(out):
                    exit_code = main(
                        [
                            "doctor",
                            "--safe-smokes",
                            "--smoke-output-dir",
                            str(output_dir),
                            "--json",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertEqual(doctor.call_args.kwargs["smoke_output_dir"], output_dir)
        self.assertEqual(doctor.call_args.kwargs["smoke_evidence_dir"], Path(".kyoko/smoke"))

    def test_doctor_cli_accepts_smoke_evidence_dir(self) -> None:
        fake_report = FakeJsonReport(
            {
                "ok": True,
                "checks": [],
                "summary": {"passed": 0, "warnings": 0, "failed": 0},
                "suggested_commands": [],
                "retained_external_evidence": [],
            }
        )
        out = io.StringIO()

        with TemporaryDirectory() as tmpdir:
            evidence_dir = Path(tmpdir) / "retained-smoke"
            with patch("kyoko.cli.run_doctor", return_value=fake_report) as doctor:
                with redirect_stdout(out):
                    exit_code = main(
                        [
                            "doctor",
                            "--smoke-evidence-dir",
                            str(evidence_dir),
                            "--json",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertEqual(doctor.call_args.kwargs["smoke_evidence_dir"], evidence_dir)

    def test_doctor_json_omits_already_requested_safe_smokes_from_suggestions(self) -> None:
        fake_operator_report = FakeOperatorSmokeMatrix(
            {
                "operators": ["codex"],
                "prepare_only": True,
                "summary": {
                    "total": 1,
                    "prepared": 1,
                    "passed": 0,
                    "failed": 0,
                    "skipped": 0,
                    "available": 1,
                },
                "targets": [],
            }
        )
        source_report = FakeJsonReport(
            {
                "kind": "source_adapter",
                "profile_id": "profile_doctor_integration_smoke",
                "ingested_counts": {"runs": 1},
                "status": {"counts": {"runs": 1}},
            }
        )
        replay_report = FakeJsonReport(
            {
                "kind": "replay_server",
                "started": True,
                "healthy": True,
                "stopped": True,
                "health": {"response": {"profile": "doctor-smoke"}},
            }
        )

        with patch("kyoko.doctor.run_demo_setup") as demo:
            demo.return_value.check_status = "passed"
            demo.return_value.promoted_trust_level = "L2_regression"
            demo.return_value.applied_skill_ids = ("skill_demo",)
            with patch("kyoko.doctor.run_operator_smoke_matrix", return_value=fake_operator_report):
                with patch("kyoko.doctor.write_source_adapter_template"):
                    with patch("kyoko.doctor.write_replay_server_template"):
                        with patch("kyoko.doctor.run_source_adapter_smoke", return_value=source_report):
                            with patch("kyoko.doctor.run_replay_server_smoke", return_value=replay_report):
                                with patch(
                                    "kyoko.doctor.run_generated_improve_smoke",
                                    return_value=fake_improve_smoke_report(Path("/tmp/improve-smoke")),
                                ):
                                    report = run_doctor(
                                        smoke_demo=True,
                                        operator_smoke_prepare=True,
                                        judge_smoke_prepare=True,
                                        integration_smoke=True,
                                        improve_smoke=True,
                                    )
        intents = {command["intent"] for command in report.to_json()["suggested_commands"]}

        self.assertNotIn("doctor_smoke_demo", intents)
        self.assertNotIn("doctor_operator_smoke_prepare", intents)
        self.assertNotIn("doctor_judge_smoke_prepare", intents)
        self.assertNotIn("doctor_integration_smoke", intents)
        self.assertNotIn("doctor_improve_smoke", intents)

    def test_doctor_reports_matrix_readiness_when_targets_are_available(self) -> None:
        def fake_which(command: str) -> str | None:
            known = {
                "python3.12": "/usr/bin/python3.12",
                "python3.13": "/usr/bin/python3.13",
                "codex": "/usr/local/bin/codex",
                "claude": "/usr/local/bin/claude",
                "hermes": "/usr/local/bin/hermes",
                "openclaw": "/usr/local/bin/openclaw",
            }
            return known.get(command)

        with patch("kyoko.doctor.shutil.which", side_effect=fake_which), patch(
            "kyoko.doctor.python_build_backend_reason",
            return_value=None,
        ):
            report = run_doctor()
        checks = {check.id: check for check in report.checks}

        self.assertEqual(checks["release_python_targets"].status, "pass")
        self.assertEqual(checks["mcp_clients"].status, "pass")
        self.assertEqual(checks["operator_commands"].status, "pass")
        self.assertEqual(
            checks["release_python_targets"].detail["targets"]["3.12"],
            "/usr/bin/python3.12",
        )
        self.assertEqual(
            checks["release_python_targets"].detail["build_backend_reasons"]["3.12"],
            None,
        )
        self.assertEqual(
            checks["mcp_clients"].detail["clients"]["codex"],
            "/usr/local/bin/codex",
        )
        suggestions = {command["intent"]: command for command in report.to_json()["suggested_commands"]}
        self.assertNotIn("release_smoke_matrix", suggestions)
        self.assertIn("mcp_install_smoke_matrix", suggestions)

    def test_doctor_marks_available_release_target_as_bootstrap_required(self) -> None:
        def fake_which(command: str) -> str | None:
            known = {
                "python3.12": "/usr/bin/python3.12",
                "python3.13": "/usr/bin/python3.13",
            }
            return known.get(command)

        def fake_backend_reason(
            *,
            python_executable: str,
            timeout_seconds: int,
        ) -> str | None:
            if python_executable == "/usr/bin/python3.12":
                return "python_build_backend_unavailable:setuptools.build_meta"
            return None

        with patch("kyoko.doctor.shutil.which", side_effect=fake_which), patch(
            "kyoko.doctor.python_build_backend_reason",
            side_effect=fake_backend_reason,
        ):
            report = run_doctor()
        checks = {check.id: check for check in report.checks}

        self.assertTrue(report.ok)
        self.assertEqual(checks["release_python_targets"].status, "pass")
        self.assertEqual(
            checks["release_python_targets"].detail["build_backend_reasons"]["3.12"],
            "python_build_backend_unavailable:setuptools.build_meta",
        )
        self.assertEqual(
            checks["release_python_targets"].detail["bootstrap_required_targets"],
            ["3.12"],
        )
        self.assertEqual(checks["release_python_targets"].detail["unready_targets"], {})
        suggestions = {command["intent"]: command for command in report.to_json()["suggested_commands"]}
        self.assertNotIn("release_build_backend_install_3_12", suggestions)
        self.assertNotIn("release_smoke_matrix", suggestions)


if __name__ == "__main__":
    unittest.main()
