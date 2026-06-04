import json
import io
import re
import shutil
import socket
import struct
import subprocess
import time
from contextlib import redirect_stderr
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Thread
from typing import Optional
from unittest.mock import patch
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from kyoko.apply import apply_context_proposal
from kyoko.blobs import put_blob
from kyoko.proposals import submit_learning_proposal, submit_learning_proposal_payload
from kyoko.operator_adapters import register_operator_adapter
from kyoko.replay_adapters import register_replay_adapter
from kyoko.storage import get_database_status, ingest_source_fixture, ingest_source_payload
from kyoko.web import WebError, _dashboard_html, make_handler, serve
from tests.profile_fixtures import second_profile_payload, second_profile_proposal
from tests.test_hermes_import import _write_hermes_kanban_db
from tests.test_improve import _source_fixture_with_root, _write_failed_openclaw_session
from tests.test_openclaw_import import _write_openclaw_sessions
from tests.test_replay_servers import _free_port
from tests.test_source_templates import _source_hook


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
VALID_HARNESS_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-harness-proposal.json"
VALID_GENERATED_FILE_PROPOSAL = (
    ROOT / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json"
)
REPLAY_SUCCESS = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
OTLP_FIXTURE = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"
JUDGE_COMMAND = ROOT / "tests/fixtures/judge_command.py"
OPERATOR_COMMAND = ROOT / "tests/fixtures/operator_command.py"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


class _DashboardHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.id_counts: dict[str, int] = {}
        self.ids: set[str] = set()
        self.scripts: list[str] = []
        self._in_inline_script = False
        self._current: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attr_map = {name.lower(): value for name, value in attrs}
        element_id = attr_map.get("id")
        if element_id:
            self.id_counts[element_id] = self.id_counts.get(element_id, 0) + 1
            self.ids.add(element_id)
        if tag.lower() != "script" or "src" in attr_map:
            return
        self._in_inline_script = True
        self._current = []

    def handle_data(self, data: str) -> None:
        if self._in_inline_script:
            self._current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or not self._in_inline_script:
            return
        self.scripts.append("".join(self._current))
        self._in_inline_script = False
        self._current = []


def _context_rule_proposal() -> dict:
    proposal = json.loads(VALID_PROPOSAL.read_text())
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
    return proposal


class RunningServer:
    def __init__(self, db_path: Path, auth_token=None, default_lock_actor_agent_identity_id=None) -> None:
        self.db_path = db_path
        self.auth_token = auth_token
        self.default_lock_actor_agent_identity_id = default_lock_actor_agent_identity_id
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            make_handler(
                db_path,
                auth_token=auth_token,
                default_lock_actor_agent_identity_id=default_lock_actor_agent_identity_id,
            ),
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "RunningServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get_json(self, path: str) -> dict:
        request = Request(f"{self.base_url}{path}", headers=self._headers())
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_text(self, path: str) -> str:
        request = Request(f"{self.base_url}{path}", headers=self._headers())
        with urlopen(request, timeout=5) as response:
            return response.read().decode("utf-8")

    def post_json(self, path: str, payload: dict) -> dict:
        request = Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", **self._headers()},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.auth_token}"} if self.auth_token else {}


class WebTests(unittest.TestCase):
    def test_server_ignores_client_disconnect_during_response_write(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                with RunningServer(db_path) as server:
                    host, port_text = server.base_url.removeprefix("http://").split(":")
                    with socket.create_connection((host, int(port_text)), timeout=5) as sock:
                        sock.setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_LINGER,
                            struct.pack("ii", 1, 0),
                        )
                        sock.sendall(b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                    time.sleep(0.2)

        self.assertNotIn("BrokenPipeError", stderr.getvalue())
        self.assertNotIn("ConnectionResetError", stderr.getvalue())

    def test_dashboard_inline_javascript_parses(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            script_path = Path(tmpdir) / "dashboard-inline.js"
            with RunningServer(db_path) as server:
                html = _dashboard_html()

            parser = _DashboardHtmlParser()
            parser.feed(html)
            self.assertGreater(len(parser.scripts), 0)
            script_path.write_text("\n;\n".join(parser.scripts), encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(script_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dashboard_static_element_references_exist(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            with RunningServer(db_path) as server:
                html = _dashboard_html()

            parser = _DashboardHtmlParser()
            parser.feed(html)
            scripts = "\n".join(parser.scripts)
            referenced_ids = set(
                re.findall(r'document\.querySelector(?:All)?\("#([^"]+)"\)', scripts)
            )
            self.assertGreater(len(referenced_ids), 0)
            self.assertEqual(sorted(referenced_ids - parser.ids), [])
            duplicate_ids = sorted(
                element_id for element_id, count in parser.id_counts.items() if count > 1
            )
            self.assertEqual(duplicate_ids, [])

    def test_dashboard_and_api_return_runtime_data(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            empty_home = Path(tmpdir) / "empty-home"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                status = server.get_json("/api/status")
                dashboard_metrics = server.get_json("/api/dashboard-metrics")
                source_discovery = server.get_json(
                    "/api/source-discovery?"
                    f"include_missing=true&profile_id=profile_news_research_001&home={quote(str(empty_home))}"
                )
                policy = server.get_json("/api/policy")
                proposals = server.get_json("/api/proposals")
                runs = server.get_json("/api/runs")
                skills = server.get_json("/api/skills")
                context_rules = server.get_json("/api/context-rules")
                context_rule_revisions = server.get_json("/api/context-rule-revisions")
                context = server.get_json("/api/context")
                evals = server.get_json("/api/evals")
                eval_assertion_presets = server.get_json("/api/eval-assertion-presets")
                eval_capabilities = server.get_json("/api/eval-capabilities")
                replay_adapters = server.get_json("/api/replay-adapters")
                operator_adapters = server.get_json("/api/operator-adapters")
                operator_runs = server.get_json("/api/operator-runs")
                storage_report = server.get_json("/api/storage-report")
                harness_patches = server.get_json("/api/harness-patches")
                autonomy_events = server.get_json("/api/autonomy-events")
                evidence = server.get_json("/api/evidence-summary")

            self.assertIn("<title>Kyoko</title>", html)
            self.assertIn("Runs", html)
            self.assertIn("Learning Proposals", html)
            self.assertNotIn("Active Profile", html)
            self.assertNotIn("profile-select", html)
            self.assertIn("dashboard-actor-identity-id", html)
            self.assertIn("dashboard-actor-identities", html)
            self.assertIn("renderDashboardActorIdentityOptions", html)
            self.assertIn("activeProfileAgentIdentities", html)
            self.assertIn("kyoko_actor_agent_identity_id", html)
            self.assertIn("dashboard-lock-reason", html)
            self.assertIn("kyoko_lock_reason", html)
            self.assertIn("actor_agent_identity_id", html)
            self.assertIn("withDashboardLockMetadata", html)
            self.assertIn("Evals And Replay", html)
            self.assertIn("/api/eval-capabilities", html)
            self.assertIn("Eval Capabilities", html)
            self.assertIn("appendEvalCapabilities", html)
            self.assertIn("Gateable evals", html)
            self.assertIn("Assertion presets", html)
            self.assertIn("/api/judge-command", html)
            self.assertIn("judge-command-input", html)
            self.assertIn("judge-output-dir", html)
            self.assertIn("runJudgeCommand", html)
            self.assertIn("/api/eval-specs/lock", html)
            self.assertIn("/api/eval-specs/approve", html)
            self.assertIn("Approve L3", html)
            self.assertIn("approveEvalSpec", html)
            self.assertIn("Autonomy Policy", html)
            self.assertIn("Harness Root", html)
            self.assertIn("harness-workspace-root", html)
            self.assertIn("kyoko_harness_workspace_root", html)
            self.assertIn("withHarnessWorkspaceRoot", html)
            self.assertIn("harness_workspace_root", html)
            self.assertIn("Replay Adapter", html)
            self.assertIn("replay-adapter-select", html)
            self.assertIn("kyoko_replay_adapter_id", html)
            self.assertIn("renderReplayAdapterSelector", html)
            self.assertIn("withSelectedReplayAdapter", html)
            self.assertIn("selectedReplayAdapterId", html)
            self.assertIn("Operator Adapter", html)
            self.assertIn("operator-adapter-select", html)
            self.assertIn("kyoko_operator_adapter_id", html)
            self.assertIn("renderOperatorAdapterSelector", html)
            self.assertIn("withSelectedOperatorAdapter", html)
            self.assertIn("selectedOperatorAdapterId", html)
            self.assertIn("request.operator_adapter_id = operatorAdapterId", html)
            self.assertIn("selectedProfilePayload(withSelectedReplayAdapter(withSelectedOperatorAdapter({", html)
            self.assertIn("latestSourceDiscoveryReport", html)
            self.assertIn("latestSourceImportReport", html)
            self.assertIn("latestSourceImproveReport", html)
            self.assertIn("state.latestSourceImportReport = { candidateId, payload }", html)
            self.assertIn("state.latestSourceImproveReport = { candidateId, payload }", html)
            self.assertIn("renderDiscoveredImportReport(importDetail, state.latestSourceImportReport.payload || {})", html)
            self.assertIn("renderSourceDiscoveryReport(detail, state.latestSourceDiscoveryReport)", html)
            self.assertIn("Autonomy History", html)
            self.assertIn("latestProposalImproveReport", html)
            self.assertIn("renderImproveReport(detail, state.latestProposalImproveReport)", html)
            self.assertIn("improveOperatorLabel", html)
            self.assertIn("improveReplayAdapterLabel", html)
            self.assertIn("Replay adapters", html)
            self.assertIn("Patch tx", html)
            self.assertIn("autonomy-events", html)
            self.assertIn("autonomy-kind-filter", html)
            self.assertIn("autonomy-entity-type-filter", html)
            self.assertIn("autonomy-entity-id-filter", html)
            self.assertIn("autonomyEventsPath", html)
            self.assertIn("renderAutonomyEvents", html)
            self.assertIn("/api/autonomy-events?", html)
            self.assertNotIn("Human Lock History", html)
            self.assertNotIn("/api/human-lock-events", html)
            self.assertNotIn("/api/human-locks/bulk", html)
            self.assertIn("Storage", html)
            self.assertNotIn("/api/profiles", html)
            self.assertNotIn("<h2>Profiles</h2>", html)
            self.assertNotIn("profile-count", html)
            self.assertNotIn('const profilesEl = document.querySelector("#profiles");', html)
            self.assertNotIn("renderProfiles(state.profiles)", html)
            self.assertNotIn("function runProfileNextForProfile", html)
            self.assertNotIn("selectProfileFromPanel", html)
            self.assertIn("/api/dashboard-metrics", html)
            self.assertIn("/api/source-discovery", html)
            self.assertIn("Local Source Discovery", html)
            self.assertIn("improveDiscoveredSource", html)
            self.assertIn("/api/storage-report", html)
            self.assertIn("/api/prune-retention", html)
            self.assertIn("/api/wal-checkpoint", html)
            self.assertIn("/api/load-smoke", html)
            self.assertIn("Checkpoint WAL", html)
            self.assertIn("Load smoke", html)
            self.assertIn("Relational Retention", html)
            self.assertIn("Dry-run data prune", html)
            self.assertIn("/api/harness-target-locks", html)
            self.assertIn("/api/harness-targets/lock", html)
            self.assertIn("Context Delivery Rules", html)
            self.assertIn("/api/context-rules", html)
            self.assertIn("Run autonomy", html)
            self.assertIn("Run next", html)
            self.assertNotIn("All-Profile Steps", html)
            self.assertNotIn("profile-next-max-steps", html)
            self.assertNotIn("clampedProfileNextMaxSteps", html)
            self.assertNotIn("all_profiles", html)
            self.assertNotIn("profile-next-all", html)
            self.assertIn('const payload = await postJson("/api/profile-next", request);', html)
            self.assertIn("/api/profile-next", html)
            self.assertIn("policy-action-detail", html)
            self.assertIn("renderPolicyActionReport", html)
            self.assertNotIn("renderProfileActionReports", html)
            self.assertNotIn("profileActionResultLabel", html)
            self.assertNotIn("profile-action-results", html)
            self.assertNotIn('["Max steps", `${payload.summary?.max_steps || 1}`]', html)
            self.assertIn('renderPolicyActionReport(policyActionDetailEl, "Run autonomy", payload)', html)
            self.assertNotIn('renderPolicyActionReport(policyActionDetailEl, "Run all next", payload)', html)
            self.assertIn("Details", html)
            self.assertIn("section_label", html)
            self.assertIn("Fix type", html)
            self.assertIn(".badge.context", html)
            self.assertIn(".badge.harness", html)
            self.assertIn("/api/improve", html)
            self.assertTrue(status["initialized"])
            self.assertEqual(len(source_discovery["candidates"]), 2)
            self.assertTrue(
                any(
                    "import-hermes-kanban" in candidate["import_command"]
                    for candidate in source_discovery["candidates"]
                )
            )
            self.assertEqual(policy["policy"]["context_mode"], "propose")
            self.assertFalse(policy["policy"]["allow_repo_patch"])
            self.assertEqual(status["counts"]["runs"], 1)
            self.assertEqual(status["counts"]["spans"], 2)
            self.assertEqual(dashboard_metrics["profile_id"], "profile_news_research_001")
            self.assertEqual(dashboard_metrics["issues"]["total"], 1)
            self.assertEqual(dashboard_metrics["runs"]["failed_spans"], 1)
            self.assertEqual(dashboard_metrics["cards"][0]["id"], "issues")
            self.assertEqual(dashboard_metrics["cards"][-1]["id"], "before_after")
            self.assertEqual(runs["runs"][0]["id"], "run_research_topic_001")
            self.assertEqual(runs["runs"][0]["failed_span_count"], 1)
            self.assertEqual(proposals["proposals"][0]["id"], "proposal_context_timeout_001")
            self.assertEqual(proposals["proposals"][0]["section_label"], "Context fix")
            self.assertIn("agent-facing", proposals["proposals"][0]["section_description"])
            self.assertEqual(proposals["proposals"][0]["kyoko_confidence"], 0.66)
            self.assertEqual(proposals["proposals"][0]["confidence_level"], "medium")
            self.assertEqual(skills["skills"], [])
            self.assertEqual(context_rules["context_delivery_rules"], [])
            self.assertEqual(context_rule_revisions["context_delivery_rule_revisions"], [])
            self.assertEqual(context["context"], "")
            self.assertEqual(evals["eval_specs"], [])
            self.assertEqual(evals["eval_runs"], [])
            self.assertEqual(evals["replay_runs"], [])
            self.assertEqual(
                [preset["name"] for preset in eval_assertion_presets["assertion_presets"]],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertEqual(
                eval_capabilities["gateable_eval_types"],
                ["deterministic_assertion", "regression_replay"],
            )
            self.assertFalse(eval_capabilities["judge"]["invokes_model"])
            self.assertIn("mcp:kyoko_run_judge_command", eval_capabilities["judge"]["handoff_surfaces"])
            self.assertIn("rubric_scoring", eval_capabilities["judge"]["recommended_use"])
            self.assertEqual(replay_adapters["replay_adapters"], [])
            self.assertEqual(operator_adapters["operator_adapters"], [])
            self.assertEqual(operator_runs["operator_runs"], [])
            self.assertEqual(storage_report["registered_blobs"], 0)
            self.assertEqual(harness_patches["patch_transactions"], [])
            self.assertEqual(autonomy_events["autonomy_events"], [])
            self.assertEqual(evidence["summary"]["failed_spans"], 1)
            self.assertEqual(evidence["redaction"]["policy"]["payload_access"], "redacted")
            self.assertEqual(evidence["redaction"]["consumer"], "api:evidence-summary")

    def test_storage_report_and_prune_endpoints(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            blob = put_blob(
                db_path=db_path,
                data=b"expired",
                media_type="text/plain",
                retained_until="2000-01-01T00:00:00Z",
            )

            with RunningServer(db_path) as server:
                storage_before = server.get_json("/api/storage-report")
                dry_run = server.post_json("/api/prune", {})
                applied = server.post_json("/api/prune", {"apply": True})
                checkpoint = server.post_json("/api/wal-checkpoint", {"mode": "TRUNCATE"})
                storage_after = server.get_json("/api/storage-report")

            self.assertEqual(storage_before["registered_blobs"], 1)
            self.assertTrue(dry_run["dry_run"])
            self.assertEqual(len(dry_run["pruned_blobs"]), 1)
            self.assertFalse(applied["dry_run"])
            self.assertEqual(len(applied["pruned_blobs"]), 1)
            self.assertEqual(checkpoint["mode"], "TRUNCATE")
            self.assertIn("wal_size_before", checkpoint)
            self.assertIn("wal_size_after", checkpoint)
            self.assertFalse(blob.path.exists())
            self.assertEqual(storage_after["registered_blobs"], 0)

    def test_prune_retention_endpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                evidence = server.get_json("/api/evidence-summary")
                dry_run = server.post_json("/api/prune-retention", {"trace_older_than_days": 0})
                applied = server.post_json(
                    "/api/prune-retention",
                    {"trace_older_than_days": 0, "apply": True},
                )
                status = server.get_json("/api/status")

            self.assertEqual(evidence["summary"]["failed_spans"], 1)
            self.assertTrue(dry_run["dry_run"])
            self.assertEqual(dry_run["pruned_rows"]["runs"], ["run_research_topic_001"])
            self.assertFalse(applied["dry_run"])
            self.assertEqual(applied["summary"]["pruned_rows"], 8)
            self.assertEqual(status["counts"]["runs"], 0)
            self.assertNotIn("retention_policies", status["counts"])

    def test_load_smoke_endpoint_seeds_and_measures_ui_reads(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                report = server.post_json(
                    "/api/load-smoke",
                    {
                        "runs": 4,
                        "spans_per_run": 2,
                        "read_workers": 1,
                        "read_iterations": 1,
                        "expired_blobs": 1,
                    },
                )
                status = server.get_json("/api/status")

            self.assertIn("/api/load-smoke", html)
            self.assertTrue(report["passed"])
            self.assertEqual(report["status"]["counts"]["runs"], 4)
            self.assertEqual(report["status"]["counts"]["spans"], 8)
            self.assertEqual(len(report["retention_dry_run"]["pruned_blobs"]), 1)
            self.assertIn("evidence_summary", report["operation_latency_ms"])
            self.assertEqual(status["counts"]["runs"], 4)

    def test_auth_token_protects_dashboard_and_api(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path, auth_token="secret-token") as server:
                with self.assertRaises(HTTPError) as html_error:
                    urlopen(f"{server.base_url}/", timeout=5)
                self.assertEqual(html_error.exception.code, 401)

                with self.assertRaises(HTTPError) as api_error:
                    urlopen(f"{server.base_url}/api/status", timeout=5)
                self.assertEqual(api_error.exception.code, 401)

                query_html = urlopen(f"{server.base_url}/?token=secret-token", timeout=5).read().decode("utf-8")
                authed_request = Request(
                    f"{server.base_url}/api/status",
                    headers={"Authorization": "Bearer secret-token"},
                )
                status = json.loads(urlopen(authed_request, timeout=5).read().decode("utf-8"))

            self.assertIn("<title>Kyoko</title>", query_html)
            self.assertTrue(status["initialized"])

    def test_post_requires_json_content_type_for_mutating_api(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                request = Request(
                    f"{server.base_url}/api/apply",
                    data=json.dumps({"proposal_id": "proposal_context_timeout_001"}).encode("utf-8"),
                    headers={"Content-Type": "text/plain"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as error:
                    urlopen(request, timeout=5)
                payload = json.loads(error.exception.read().decode("utf-8"))
                proposals = server.get_json("/api/proposals")
                status_request = Request(f"{server.base_url}/api/status")
                with urlopen(status_request, timeout=5) as response:
                    content_type_options = response.headers.get("X-Content-Type-Options")
                    status = json.loads(response.read().decode("utf-8"))

            self.assertEqual(error.exception.code, 415)
            self.assertEqual(payload["error"], "unsupported_media_type")
            self.assertEqual(proposals["proposals"][0]["state"], "pending")
            self.assertEqual(status["counts"]["skills"], 0)
            self.assertEqual(content_type_options, "nosniff")

    def test_remote_serve_requires_auth_token(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            with self.assertRaisesRegex(WebError, "auth_token_required"):
                serve(db_path=db_path, host="0.0.0.0", port=0)

    def test_demo_endpoint_runs_first_run_loop(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                demo = server.post_json("/api/demo", {})
                status = server.get_json("/api/status")
                proposals = server.get_json("/api/proposals")
                skills = server.get_json("/api/skills")
                evals = server.get_json("/api/evals")

            self.assertIn("Run demo", html)
            self.assertEqual(demo["profile_id"], "profile_news_research_001")
            self.assertEqual(demo["eval_status"], "passed")
            self.assertEqual(demo["promoted_trust_level"], "L2_regression")
            self.assertEqual(demo["applied_skill_ids"], ["skill_proposal_context_timeout_001_1"])
            self.assertEqual(status["counts"]["profiles"], 1)
            self.assertEqual(status["counts"]["learning_proposals"], 1)
            self.assertEqual(status["counts"]["skills"], 1)
            self.assertEqual(status["counts"]["eval_runs"], 1)
            self.assertEqual(proposals["proposals"][0]["id"], "proposal_context_timeout_001")
            self.assertEqual(skills["skills"][0]["id"], "skill_proposal_context_timeout_001_1")
            self.assertEqual(evals["eval_runs"][0]["status"], "passed")

    def test_profile_next_endpoint_plans_and_runs_eval_generation(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                dry_run = server.post_json("/api/profile-next", {"profile_id": "profile_news_research_001"})
                executed = server.post_json(
                    "/api/profile-next",
                    {"profile_id": "profile_news_research_001", "run": True},
                )
                evals = server.get_json("/api/evals")

            self.assertEqual(dry_run["status"], "planned")
            self.assertEqual(dry_run["action"], "generate_evals")
            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["reason"], "generated_eval_specs")
            self.assertEqual(executed["routing_after"]["state"], "needs_replay_or_eval")
            self.assertEqual(evals["eval_specs"][0]["id"], "eval_proposal_context_timeout_001_1")

    def test_profile_next_endpoint_runs_selected_replay_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            replay_dir = Path(tmpdir) / "selected-replay"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="selected_replay",
                name="Selected replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=replay_dir,
                default_side_effect_mode="network_mocked",
            )

            with RunningServer(db_path) as server:
                server.post_json(
                    "/api/evals/generate",
                    {"proposal_id": "proposal_context_timeout_001"},
                )
                executed = server.post_json(
                    "/api/profile-next",
                    {
                        "profile_id": "profile_news_research_001",
                        "run": True,
                        "replay_adapter_id": "selected_replay",
                    },
                )

            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["reason"], "ran_replay_adapter")
            self.assertEqual(executed["result"]["adapter_id"], "selected_replay")
            self.assertEqual(executed["result"]["status"], "passed")
            self.assertEqual(executed["result"]["eval_run"]["status"], "passed")

    def test_profile_next_endpoint_prepares_operator_prompt_for_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                executed = server.post_json(
                    "/api/profile-next",
                    {
                        "profile_id": "profile_news_research_001",
                        "run": True,
                        "operator_target": "codex",
                        "operator_output_dir": str(output_dir),
                        "schema_path": str(SCHEMA),
                    },
                )

            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["reason"], "prepared_operator_prompt")
            self.assertEqual(executed["result"]["target"], "codex")
            self.assertTrue(Path(executed["result"]["evidence_path"]).exists())
            self.assertTrue(Path(executed["result"]["prompt_path"]).exists())
            self.assertEqual(executed["routing_after"]["state"], "needs_analysis")

    def test_profile_next_endpoint_explicit_operator_target_keeps_prompt_only_with_registered_adapter(self) -> None:
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

            with RunningServer(db_path) as server:
                executed = server.post_json(
                    "/api/profile-next",
                    {
                        "profile_id": "profile_news_research_001",
                        "run": True,
                        "operator_target": "codex",
                        "operator_output_dir": str(output_dir),
                        "schema_path": str(SCHEMA),
                    },
                )

            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["reason"], "prepared_operator_prompt")
            self.assertEqual(executed["result"]["target"], "codex")

    def test_profile_next_endpoint_runs_registered_operator_adapter(self) -> None:
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

            with RunningServer(db_path) as server:
                executed = server.post_json(
                    "/api/profile-next",
                    {
                        "profile_id": "profile_news_research_001",
                        "run": True,
                        "operator_adapter_id": "fixture_operator",
                        "operator_output_dir": str(output_dir),
                        "schema_path": str(SCHEMA),
                    },
                )

            self.assertEqual(executed["status"], "executed")
            self.assertEqual(executed["reason"], "ran_operator_adapter")
            self.assertEqual(executed["result"]["adapter_id"], "fixture_operator")
            self.assertEqual(executed["result"]["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertEqual(executed["routing_after"]["state"], "needs_eval_generation")

    def test_profile_next_endpoint_ignores_all_profiles_and_runs_single(self) -> None:
        # Single implicit profile (SCOPE Decision 1): no multi-profile batch mode.
        # A stray all_profiles flag is ignored; the endpoint returns a single report.
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "operator"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                executed = server.post_json(
                    "/api/profile-next",
                    {
                        "all_profiles": True,
                        "run": True,
                        "operator_target": "codex",
                        "operator_output_dir": str(output_dir),
                        "schema_path": str(SCHEMA),
                    },
                )

            self.assertNotIn("profiles", executed)
            self.assertNotIn("summary", executed)
            self.assertEqual(executed["profile_id"], "profile_news_research_001")
            self.assertEqual(executed["reason"], "prepared_operator_prompt")

    def test_ingest_endpoint_accepts_canonical_source_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            source_events = json.loads(FIXTURE.read_text())

            with RunningServer(db_path) as server:
                ingest = server.post_json("/api/ingest", source_events)
                status = server.get_json("/api/status")
                evidence = server.get_json("/api/evidence-summary")

            self.assertEqual(ingest["profile_id"], "profile_news_research_001")
            self.assertEqual(ingest["ingested_counts"]["runs"], 1)
            self.assertEqual(status["counts"]["runs"], 1)
            self.assertEqual(status["counts"]["spans"], 2)
            self.assertEqual(evidence["summary"]["failed_spans"], 1)

    def test_ingest_endpoint_accepts_source_events_wrapper(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            source_events = json.loads(FIXTURE.read_text())

            with RunningServer(db_path) as server:
                ingest = server.post_json("/api/ingest", {"source_events": source_events})
                status = server.get_json("/api/status")

            self.assertEqual(ingest["profile_id"], "profile_news_research_001")
            self.assertEqual(status["counts"]["runs"], 1)

    def test_import_discovered_source_endpoint_imports_openclaw_candidate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            home = tmp_path / "home"
            _write_openclaw_sessions(home)

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                discovery = server.get_json(f"/api/source-discovery?home={quote(str(home))}")
                imported = server.post_json(
                    "/api/import-discovered-source",
                    {
                        "candidate_id": "openclaw_main",
                        "home": str(home),
                        "profile_id": "profile_web_discovered_openclaw",
                    },
                )
                status = server.get_json("/api/status")

            self.assertIn("/api/import-discovered-source", html)
            self.assertEqual(discovery["candidates"][0]["id"], "openclaw_main")
            self.assertEqual(imported["candidate"]["id"], "openclaw_main")
            self.assertEqual(imported["import"]["profile_id"], "profile_web_discovered_openclaw")
            self.assertEqual(imported["import"]["counts"]["spans"], 6)
            self.assertEqual(status["counts"]["runs"], 1)

    def test_otlp_ingest_endpoints_accept_json_payloads(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            otlp_payload = json.loads(OTLP_FIXTURE.read_text())
            normalized_path = Path(tmpdir) / "otlp-normalized.json"

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                api_ingest = server.post_json(
                    "/api/ingest-otlp",
                    {
                        "otlp": otlp_payload,
                        "profile_id": "profile_web_otlp",
                        "source_kind": "pydantic_ai",
                        "source_name": "Pydantic AI",
                        "output_path": str(normalized_path),
                    },
                )
                otlp_ingest = server.post_json(
                    "/v1/traces?profile_id=profile_web_v1&source_kind=otlp_http",
                    otlp_payload,
                )
                status = server.get_json("/api/status")

            self.assertIn("/api/ingest-otlp", html)
            self.assertIn("/v1/traces", html)
            self.assertEqual(api_ingest["profile_id"], "profile_web_otlp")
            self.assertEqual(api_ingest["ingested_counts"]["runs"], 1)
            self.assertEqual(len(api_ingest["span_ids"]), 2)
            self.assertTrue(normalized_path.exists())
            self.assertEqual(otlp_ingest["profile_id"], "profile_web_v1")
            self.assertEqual(otlp_ingest["ingested_counts"]["spans"], 2)
            self.assertEqual(status["counts"]["profiles"], 2)
            self.assertEqual(status["counts"]["runs"], 2)
            self.assertEqual(status["counts"]["spans"], 4)

    def test_apply_endpoint_applies_context_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                apply_report = server.post_json(
                    "/api/apply",
                    {"proposal_id": "proposal_context_timeout_001"},
                )
                lock_report = server.post_json(
                    "/api/skills/lock",
                    {
                        "skill_id": "skill_proposal_context_timeout_001_1",
                        "locked": True,
                        "reason": "manual owner review",
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                proposals = server.get_json("/api/proposals")
                skills = server.get_json("/api/skills")
                revisions = server.get_json("/api/skill-revisions?skill_id=skill_proposal_context_timeout_001_1")
                context = server.get_json("/api/context")

            self.assertIn("/api/skills/lock", html)
            self.assertEqual(apply_report["state"], "applied")
            self.assertTrue(lock_report["human_locked"])
            self.assertEqual(lock_report["reason"], "manual owner review")
            self.assertEqual(lock_report["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(
                apply_report["applied_skill_ids"],
                ["skill_proposal_context_timeout_001_1"],
            )
            self.assertEqual(apply_report["applied_context_rule_ids"], [])
            self.assertEqual(proposals["proposals"][0]["state"], "applied")
            self.assertEqual(len(skills["skills"]), 1)
            self.assertTrue(skills["skills"][0]["human_locked"])
            self.assertEqual(skills["skills"][0]["human_lock_reason"], "manual owner review")
            self.assertEqual(revisions["skill_revisions"][0]["operation"], "create")
            self.assertIn("skill_proposal_context_timeout_001_1", context["context"])

    def test_human_lock_endpoint_uses_default_actor_when_payload_omits_actor(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(
                db_path,
                default_lock_actor_agent_identity_id="agent_researcher_001",
            ) as server:
                server.post_json(
                    "/api/apply",
                    {"proposal_id": "proposal_context_timeout_001"},
                )
                lock_report = server.post_json(
                    "/api/skills/lock",
                    {
                        "skill_id": "skill_proposal_context_timeout_001_1",
                        "locked": True,
                        "reason": "server default actor",
                    },
                )
                skills = server.get_json("/api/skills")

            self.assertTrue(lock_report["human_locked"])
            self.assertEqual(lock_report["actor_agent_identity_id"], "agent_researcher_001")
            self.assertTrue(skills["skills"][0]["human_locked"])

    def test_context_rule_endpoints_apply_list_lock_and_render(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=_context_rule_proposal(),
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                apply_report = server.post_json(
                    "/api/apply",
                    {"proposal_id": "proposal_context_rule_001"},
                )
                revisions = server.get_json(
                    "/api/context-rule-revisions?rule_id=context_rule_researcher_timeout"
                )
                context = server.get_json(
                    "/api/context?target_type=agent_identity&target_id=agent_researcher_001"
                )
                lock_report = server.post_json(
                    "/api/context-rules/lock",
                    {
                        "rule_id": "context_rule_researcher_timeout",
                        "locked": True,
                        "reason": "preserve handoff policy",
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                unlock_report = server.post_json(
                    "/api/context-rules/lock",
                    {
                        "rule_id": "context_rule_researcher_timeout",
                        "locked": False,
                        "reason": "policy update approved",
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                rollback = server.post_json(
                    "/api/context-rule-revisions/rollback",
                    {"revision_id": revisions["context_delivery_rule_revisions"][0]["id"]},
                )
                rules = server.get_json("/api/context-rules?include_inactive=true")

            self.assertEqual(
                apply_report["applied_context_rule_ids"],
                ["context_rule_researcher_timeout"],
            )
            self.assertEqual(revisions["context_delivery_rule_revisions"][0]["operation"], "create")
            self.assertIn("context_rule_researcher_timeout", context["context"])
            self.assertTrue(lock_report["human_locked"])
            self.assertEqual(lock_report["reason"], "preserve handoff policy")
            self.assertEqual(lock_report["actor_agent_identity_id"], "agent_researcher_001")
            self.assertFalse(unlock_report["human_locked"])
            self.assertEqual(unlock_report["reason"], "policy update approved")
            self.assertEqual(unlock_report["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(rollback["status"], "rolled_back")
            self.assertEqual(rules["context_delivery_rules"][0]["id"], "context_rule_researcher_timeout")
            self.assertFalse(rules["context_delivery_rules"][0]["human_locked"])
            self.assertFalse(rules["context_delivery_rules"][0]["active"])

    def test_context_endpoint_respects_profile_id(self) -> None:
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

            with RunningServer(db_path) as server:
                second_runs = server.get_json("/api/runs?profile_id=profile_second")
                second_proposals = server.get_json("/api/proposals?profile_id=profile_second")
                second_policy = server.get_json("/api/policy?profile_id=profile_second")
                second_skills = server.get_json("/api/skills?profile_id=profile_second")
                second_evidence = server.get_json("/api/evidence-summary?profile_id=profile_second")
                first = server.get_json(
                    "/api/context?target_type=agent_identity&target_id=agent_researcher_001"
                )
                second = server.get_json("/api/context?profile_id=profile_second")
                missing = server.get_json(
                    "/api/context?target_type=agent_identity&target_id=agent_missing"
                )

            self.assertEqual(second_runs["runs"][0]["id"], "run_second")
            self.assertEqual([proposal["id"] for proposal in second_proposals["proposals"]], ["proposal_second_context"])
            self.assertEqual(second_policy["policy"]["profile_id"], "profile_second")
            self.assertEqual([skill["profile_id"] for skill in second_skills["skills"]], ["profile_second"])
            self.assertEqual(second_evidence["profile_id"], "profile_second")
            self.assertEqual(second_evidence["summary"]["failed_spans"], 1)
            self.assertIn("Retry transient fetch failures once before handoff", first["context"])
            self.assertNotIn("billing-specific", first["context"])
            self.assertEqual(second["profile_id"], "profile_second")
            self.assertIn("billing-specific", second["context"])
            self.assertNotIn("Retry transient fetch failures once before handoff", second["context"])
            self.assertEqual(missing["context"], "")

    def test_proposal_detail_endpoint_returns_evidence_and_gate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                detail = server.get_json("/api/proposal-detail?id=proposal_context_timeout_001")

            self.assertEqual(detail["proposal"]["id"], "proposal_context_timeout_001")
            self.assertEqual(detail["proposal"]["section_label"], "Context fix")
            self.assertIn("agent-facing", detail["proposal"]["section_description"])
            self.assertEqual(detail["target"]["ref"]["entity_id"], "agent_researcher_001")
            self.assertEqual(detail["autonomy_gate"]["action"], "awaiting_human_review")
            self.assertEqual(len(detail["evidence"]), 2)
            self.assertEqual(detail["eval_guidance"]["gateable_eval_types"], ["deterministic_assertion", "regression_replay"])
            self.assertEqual(
                [preset["name"] for preset in detail["eval_guidance"]["assertion_presets"]],
                ["replay_success_shape", "replay_handoff_present"],
            )
            self.assertIn("evidence_chain", detail)
            self.assertEqual(detail["evidence_chain"]["steps"][0]["stage"], "observed_issue")
            self.assertEqual(detail["evidence_chain"]["steps"][2]["status"], "not_generated")

    def test_run_detail_endpoint_returns_trace_and_linked_proposals(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                detail = server.get_json("/api/run-detail?id=run_research_topic_001")

            self.assertEqual(detail["run"]["id"], "run_research_topic_001")
            self.assertEqual(detail["summary"]["spans"], 2)
            self.assertEqual(detail["summary"]["failed_spans"], 1)
            self.assertEqual(detail["related_proposals"][0]["proposal"]["id"], "proposal_context_timeout_001")

    def test_autonomy_endpoint_gates_context_proposal(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                policy = server.post_json("/api/policy", {"context_mode": "autonomous"})
                autonomy = server.post_json("/api/autonomy/run", {})
                autonomy_events = server.get_json("/api/autonomy-events?limit=10")
                decision_events = server.get_json(
                    "/api/autonomy-events?"
                    "kind=autonomy_decision&entity_type=learning_proposal&"
                    "entity_id=proposal_context_timeout_001"
                )
                gated_events = server.get_json("/api/autonomy-events?kind=autonomy_gated")
                proposals = server.get_json("/api/proposals")
                evals = server.get_json("/api/evals")
                lock = server.post_json(
                    "/api/eval-specs/lock",
                    {
                        "eval_spec_id": "eval_proposal_context_timeout_001_1",
                        "locked": True,
                        "reason": "manual eval review",
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                locks = server.get_json("/api/eval-spec-locks")
                detail = server.get_json("/api/proposal-detail?id=proposal_context_timeout_001")
                unlock = server.post_json(
                    "/api/eval-specs/lock",
                    {
                        "eval_spec_id": "eval_proposal_context_timeout_001_1",
                        "locked": False,
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                approval = server.post_json(
                    "/api/eval-specs/approve",
                    {
                        "eval_spec_id": "eval_proposal_context_timeout_001_1",
                        "reason": "human gate approval",
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                active_locks_after_unlock = server.get_json("/api/eval-spec-locks")
                evals_after_approval = server.get_json("/api/evals")

            self.assertEqual(policy["policy"]["context_mode"], "autonomous")
            self.assertEqual(autonomy["decisions"][0]["action"], "gated")
            self.assertEqual(autonomy["decisions"][0]["reason"], "missing_eval_run")
            self.assertEqual(
                {event["kind"] for event in autonomy_events["autonomy_events"]},
                {"autonomy_gated", "autonomy_decision"},
            )
            self.assertEqual(len(decision_events["autonomy_events"]), 1)
            self.assertEqual(decision_events["autonomy_events"][0]["kind"], "autonomy_decision")
            self.assertEqual(
                decision_events["autonomy_events"][0]["metadata"]["reason"],
                "missing_eval_run",
            )
            self.assertEqual(len(gated_events["autonomy_events"]), 1)
            self.assertEqual(gated_events["autonomy_events"][0]["kind"], "autonomy_gated")
            self.assertEqual(proposals["proposals"][0]["state"], "pending")
            self.assertEqual(evals["eval_specs"][0]["id"], "eval_proposal_context_timeout_001_1")
            self.assertFalse(evals["eval_specs"][0]["human_locked"])
            self.assertTrue(lock["human_locked"])
            self.assertEqual(lock["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(locks["eval_spec_locks"][0]["eval_spec_id"], "eval_proposal_context_timeout_001_1")
            self.assertTrue(detail["eval_specs"][0]["human_locked"])
            self.assertFalse(unlock["human_locked"])
            self.assertEqual(unlock["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(approval["previous_trust_level"], "L0_generated")
            self.assertEqual(approval["trust_level"], "L3_human_approved")
            self.assertEqual(approval["reason"], "human gate approval")
            self.assertEqual(approval["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(active_locks_after_unlock["eval_spec_locks"], [])
            self.assertEqual(evals_after_approval["eval_specs"][0]["trust_level"], "L3_human_approved")
            self.assertEqual(detail["gate_history"][-1]["kind"], "autonomy_decision")
            self.assertEqual(detail["gate_history"][-1]["reason"], "missing_eval_run")
            self.assertEqual(detail["evidence_chain"]["steps"][-1]["status"], "gated")

    def test_evidence_summary_is_redacted_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                evidence = server.get_json("/api/evidence-summary")

            self.assertEqual(evidence["redaction"]["policy"]["payload_access"], "redacted")
            self.assertTrue(evidence["redaction"]["policy"]["redact_sensitive_values"])

    def test_harness_prepare_endpoint_creates_patch_transaction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_HARNESS_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                prepare = server.post_json(
                    "/api/harness/prepare",
                    {"proposal_id": "proposal_harness_timeout_eval_001"},
                )
                proposals = server.get_json("/api/proposals")
                harness_patches = server.get_json("/api/harness-patches")
                status = server.get_json("/api/status")

            self.assertIn("Harness Patches", html)
            self.assertIn("Harness Target Locks", html)
            self.assertEqual(prepare["state"], "pending")
            self.assertEqual(
                prepare["patch_transaction_ids"],
                ["patch_proposal_harness_timeout_eval_001_1"],
            )
            self.assertEqual(proposals["proposals"][0]["state"], "pending")
            self.assertEqual(harness_patches["patch_transactions"][0]["status"], "ready")
            self.assertEqual(status["counts"]["patch_transactions"], 1)

    def test_harness_apply_and_rollback_endpoints_require_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            target = workspace / "evals/generated_timeout_eval.py"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_GENERATED_FILE_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                policy = server.post_json("/api/policy", {"allow_repo_patch": True})
                prepare = server.post_json(
                    "/api/harness/prepare",
                    {"proposal_id": "proposal_harness_generated_eval_001"},
                )
                apply = server.post_json(
                    "/api/harness/apply",
                    {
                        "patch_transaction_id": prepare["patch_transaction_ids"][0],
                        "workspace_root": str(workspace),
                    },
                )
                applied_file_exists = target.exists()
                patches_after_apply = server.get_json("/api/harness-patches")
                rollback = server.post_json(
                    "/api/harness/rollback",
                    {
                        "patch_transaction_id": prepare["patch_transaction_ids"][0],
                        "workspace_root": str(workspace),
                    },
                )
                patches_after_rollback = server.get_json("/api/harness-patches")

            self.assertTrue(policy["policy"]["allow_repo_patch"])
            self.assertEqual(apply["status"], "applied")
            self.assertTrue(applied_file_exists)
            self.assertFalse(target.exists())
            self.assertEqual(patches_after_apply["patch_transactions"][0]["status"], "applied")
            self.assertEqual(rollback["status"], "rolled_back")
            self.assertEqual(patches_after_rollback["patch_transactions"][0]["status"], "rolled_back")

    def test_harness_target_lock_endpoints(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                lock = server.post_json(
                    "/api/harness-targets/lock",
                    {
                        "target_path": "evals/generated_timeout_eval.py",
                        "locked": True,
                        "reason": "manual owner review",
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                locks = server.get_json("/api/harness-target-locks")
                unlock = server.post_json(
                    "/api/harness-targets/lock",
                    {
                        "target_path": "evals/generated_timeout_eval.py",
                        "locked": False,
                        "actor_agent_identity_id": "agent_researcher_001",
                    },
                )
                active_locks_after_unlock = server.get_json("/api/harness-target-locks")

            self.assertTrue(lock["human_locked"])
            self.assertEqual(lock["reason"], "manual owner review")
            self.assertEqual(lock["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(locks["harness_target_locks"][0]["target_path"], "evals/generated_timeout_eval.py")
            self.assertFalse(unlock["human_locked"])
            self.assertEqual(unlock["actor_agent_identity_id"], "agent_researcher_001")
            self.assertEqual(active_locks_after_unlock["harness_target_locks"], [])

    def test_autonomy_run_endpoint_accepts_harness_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                server.post_json(
                    "/api/policy",
                    {
                        "harness_mode": "autonomous",
                        "allow_repo_patch": True,
                    },
                )
                report = server.post_json(
                    "/api/autonomy/run",
                    {"harness_workspace_root": str(workspace)},
                )

            self.assertEqual(report["decisions"][0]["action"], "gated")
            self.assertEqual(report["decisions"][0]["reason"], "missing_eval_run")
            self.assertEqual(
                report["decisions"][0]["eval_spec_ids"],
                ["eval_proposal_harness_generated_eval_001_1"],
            )
            self.assertEqual(
                report["decisions"][0]["patch_transaction_ids"],
                ["patch_proposal_harness_generated_eval_001_1"],
            )
            self.assertFalse((workspace / "evals/generated_timeout_eval.py").exists())

    def test_harness_apply_and_rollback_endpoints_support_unified_diff(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            target = workspace / "evals/generated_timeout_eval.py"
            target.parent.mkdir(parents=True)
            target.write_text("old\n")
            ingest_source_fixture(db_path, FIXTURE)
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
            proposal["id"] = "proposal_harness_web_unified_diff_001"
            proposal["producer"]["session_id"] = "operator_session_harness_web_unified_diff_001"
            proposal["proposed_changes"][0]["patch_kind"] = "unified_diff"
            proposal["proposed_changes"][0]["diff_ref"] = diff_blob.blob_id
            proposal["proposed_changes"][0]["target_paths"] = ["evals/generated_timeout_eval.py"]
            proposal["proposed_changes"][0]["command_plan"] = []
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                server.post_json("/api/policy", {"allow_repo_patch": True})
                prepare = server.post_json(
                    "/api/harness/prepare",
                    {"proposal_id": "proposal_harness_web_unified_diff_001"},
                )
                apply = server.post_json(
                    "/api/harness/apply",
                    {
                        "patch_transaction_id": prepare["patch_transaction_ids"][0],
                        "workspace_root": str(workspace),
                    },
                )
                applied_content = target.read_text()
                rollback = server.post_json(
                    "/api/harness/rollback",
                    {
                        "patch_transaction_id": prepare["patch_transaction_ids"][0],
                        "workspace_root": str(workspace),
                    },
                )

            self.assertEqual(apply["status"], "applied")
            self.assertEqual(applied_content, "new\n")
            self.assertEqual(rollback["status"], "rolled_back")
            self.assertEqual(target.read_text(), "old\n")

    def test_eval_and_replay_endpoints(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                generate = server.post_json(
                    "/api/evals/generate",
                    {"proposal_id": "proposal_context_timeout_001"},
                )
                replay = server.post_json(
                    "/api/replay",
                    {"eval_spec_id": "eval_proposal_context_timeout_001_1"},
                )
                complete = server.post_json(
                    "/api/replay/complete",
                    {
                        "replay_run_id": replay["replay_run_id"],
                        "fixture_path": str(REPLAY_SUCCESS),
                    },
                )
                eval_run = server.post_json(
                    "/api/evals/run",
                    {
                        "eval_spec_id": "eval_proposal_context_timeout_001_1",
                        "replay_run_id": replay["replay_run_id"],
                    },
                )
                evals = server.get_json("/api/evals")
                eval_detail = server.get_json("/api/eval-detail?id=eval_proposal_context_timeout_001_1")
                replay_detail = server.get_json(f"/api/replay-detail?id={replay['replay_run_id']}")
                status = server.get_json("/api/status")

            self.assertEqual(generate["eval_spec_ids"], ["eval_proposal_context_timeout_001_1"])
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["source_run_id"], "run_research_topic_001")
            self.assertEqual(complete["output_run_id"], "run_research_topic_replay_001")
            self.assertEqual(eval_run["status"], "passed")
            self.assertEqual(eval_run["promoted_trust_level"], "L2_regression")
            self.assertEqual(eval_detail["summary"]["latest_comparison"], "fail_before_pass_after")
            self.assertEqual(replay_detail["summary"]["actual_side_effect_mode"], "network_mocked")
            self.assertEqual(len(evals["eval_specs"]), 1)
            self.assertEqual(len(evals["eval_runs"]), 1)
            self.assertEqual(len(evals["replay_runs"]), 1)
            self.assertEqual(status["counts"]["eval_specs"], 1)
            self.assertEqual(status["counts"]["eval_runs"], 1)
            self.assertEqual(status["counts"]["replay_runs"], 1)
            self.assertEqual(len(eval_detail["summary"]["latest_assertions"]), 3)
            self.assertEqual(eval_detail["summary"]["latest_assertions"][1]["actual"], 1)
            self.assertEqual(eval_detail["summary"]["latest_assertions"][2]["path"], "metadata.source_status")

    def test_judge_command_endpoint_captures_external_verdict(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "judge-command"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )

            with RunningServer(db_path) as server:
                server.post_json(
                    "/api/evals/generate",
                    {"proposal_id": "proposal_context_timeout_001"},
                )
                _set_web_eval_type(
                    db_path,
                    "eval_proposal_context_timeout_001_1",
                    "judge",
                    {
                        "rubric": "Recovered source evidence is complete and dated.",
                        "evidence_refs": [
                            {"entity_type": "span", "entity_id": "span_fetch_timeout_001"},
                        ],
                    },
                )
                judge = server.post_json(
                    "/api/judge-command",
                    {
                        "eval_spec_id": "eval_proposal_context_timeout_001_1",
                        "command": [sys.executable, str(JUDGE_COMMAND)],
                        "output_dir": str(output_dir),
                    },
                )
                evals = server.get_json("/api/evals")

            self.assertEqual(judge["eval_run"]["status"], "passed")
            self.assertEqual(judge["eval_run"]["result"]["judge_backend"], "external_command")
            self.assertFalse(judge["eval_run"]["result"]["gateable"])
            self.assertIsNone(judge["eval_run"]["promoted_trust_level"])
            self.assertEqual(judge["judgment"]["judge"], "fixture_external_judge")
            self.assertTrue(Path(judge["request_path"]).exists())
            self.assertTrue(Path(judge["result_path"]).exists())
            self.assertTrue(Path(judge["raw_output_path"]).exists())
            self.assertEqual(len(evals["eval_runs"]), 1)

    def test_replay_adapter_endpoint_runs_registered_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "adapter-output"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=output_dir,
            )

            with RunningServer(db_path) as server:
                server.post_json(
                    "/api/evals/generate",
                    {"proposal_id": "proposal_context_timeout_001"},
                )
                adapters = server.get_json("/api/replay-adapters")
                replay = server.post_json(
                    "/api/replay-adapters/run",
                    {
                        "adapter_id": "fixture_replay",
                        "eval_spec_id": "eval_proposal_context_timeout_001_1",
                        "run_eval": True,
                    },
                )
                evals = server.get_json("/api/evals")
                status = server.get_json("/api/status")

            self.assertEqual(adapters["replay_adapters"][0]["id"], "fixture_replay")
            self.assertEqual(replay["status"], "passed")
            self.assertEqual(replay["eval_run"]["promoted_trust_level"], "L2_regression")
            self.assertEqual(len(evals["eval_runs"]), 1)
            self.assertEqual(status["counts"]["replay_adapters"], 1)
            self.assertEqual(status["counts"]["replay_runs"], 1)

    def test_improve_endpoint_runs_registered_replay_and_autonomy(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "improve-replay"
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal(
                db_path=db_path,
                proposal_path=VALID_PROPOSAL,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=output_dir,
                default_side_effect_mode="network_mocked",
            )

            with RunningServer(db_path) as server:
                policy = server.post_json("/api/policy", {"context_mode": "autonomous"})
                improve = server.post_json(
                    "/api/improve",
                    {
                        "proposal_id": "proposal_context_timeout_001",
                        "replay_adapter_id": "fixture_replay",
                    },
                )
                proposals = server.get_json("/api/proposals")
                skills = server.get_json("/api/skills")
                evals = server.get_json("/api/evals")

            self.assertEqual(policy["policy"]["context_mode"], "autonomous")
            self.assertEqual(improve["proposal_id"], "proposal_context_timeout_001")
            self.assertEqual(improve["eval_spec_ids"], ["eval_proposal_context_timeout_001_1"])
            self.assertEqual(improve["replay_runs"][0]["adapter_id"], "fixture_replay")
            self.assertEqual(improve["replay_runs"][0]["status"], "passed")
            self.assertEqual(improve["replay_runs"][0]["eval_run"]["status"], "passed")
            self.assertEqual(improve["autonomy"]["decisions"][0]["action"], "applied")
            self.assertEqual(proposals["proposals"][0]["state"], "applied")
            self.assertEqual(skills["skills"][0]["id"], "skill_proposal_context_timeout_001_1")
            self.assertEqual(evals["eval_runs"][0]["status"], "passed")

    def test_improve_endpoint_applies_harness_patch_with_workspace_root(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            output_dir = Path(tmpdir) / "improve-replay"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            ingest_source_fixture(db_path, FIXTURE)
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=output_dir,
                default_side_effect_mode="network_mocked",
            )

            with RunningServer(db_path) as server:
                server.post_json(
                    "/api/policy",
                    {
                        "harness_mode": "autonomous",
                        "allow_repo_patch": True,
                    },
                )
                improve = server.post_json(
                    "/api/improve",
                    {
                        "proposal_id": "proposal_harness_generated_eval_001",
                        "replay_adapter_id": "fixture_replay",
                        "harness_workspace_root": str(workspace),
                    },
                )

            target = workspace / "evals/generated_timeout_eval.py"
            self.assertEqual(
                improve["generated_eval_spec_ids"],
                ["eval_proposal_harness_generated_eval_001_1"],
            )
            self.assertEqual(improve["replay_runs"][0]["eval_run"]["status"], "passed")
            self.assertEqual(improve["autonomy"]["decisions"][0]["action"], "applied")
            self.assertTrue(target.exists())

    def test_improve_endpoint_uses_profile_root_for_harness_patch_after_replay(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            workspace = Path(tmpdir) / "workspace"
            workspace.mkdir()
            output_dir = Path(tmpdir) / "improve-replay"
            proposal = json.loads(VALID_GENERATED_FILE_PROPOSAL.read_text())
            proposal["gate_expectations"]["requires_human_review"] = False
            ingest_source_payload(
                db_path=db_path,
                fixture=_source_fixture_with_root(workspace),
                source_label="source-with-profile-root",
            )
            submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=SCHEMA,
            )
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=output_dir,
                default_side_effect_mode="network_mocked",
            )

            with RunningServer(db_path) as server:
                server.post_json(
                    "/api/policy",
                    {
                        "harness_mode": "autonomous",
                        "allow_repo_patch": True,
                    },
                )
                improve = server.post_json(
                    "/api/improve",
                    {
                        "proposal_id": "proposal_harness_generated_eval_001",
                        "replay_adapter_id": "fixture_replay",
                    },
                )

            target = workspace / "evals/generated_timeout_eval.py"
            self.assertEqual(improve["replay_runs"][0]["eval_run"]["status"], "passed")
            self.assertEqual(improve["autonomy"]["decisions"][0]["action"], "applied")
            self.assertTrue(target.exists())

    def test_improve_endpoint_can_import_discovered_source_before_analysis(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            home = tmp_path / "home"
            _write_failed_openclaw_session(home)

            with RunningServer(db_path) as server:
                improve = server.post_json(
                    "/api/improve",
                    {
                        "source_candidate_id": "openclaw_main",
                        "source_home": str(home),
                        "source_import_output_dir": str(tmp_path / "normalized"),
                        "run_autonomy": False,
                    },
                )
                proposals = server.get_json("/api/proposals")
                evals = server.get_json("/api/evals")

            self.assertEqual(improve["source_import"]["candidate"]["id"], "openclaw_main")
            self.assertEqual(improve["profile_id"], "profile_openclaw_main")
            self.assertEqual(improve["proposal_id"], "proposal_mock_span_openclaw_error_session_failure_1")
            self.assertEqual(proposals["proposals"][0]["id"], "proposal_mock_span_openclaw_error_session_failure_1")
            self.assertEqual(
                evals["eval_specs"][0]["id"],
                "eval_proposal_mock_span_openclaw_error_session_failure_1_1",
            )

    def test_improve_endpoint_uses_selected_operator_adapter_for_discovered_source(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            home = tmp_path / "home"
            _write_failed_openclaw_session(home)
            ingest_source_fixture(db_path, FIXTURE)
            register_operator_adapter(
                db_path=db_path,
                adapter_id="fixture_operator",
                name="Fixture operator",
                command=[sys.executable, str(OPERATOR_COMMAND)],
                profile_id="profile_news_research_001",
                output_dir=tmp_path / "operator",
            )

            with RunningServer(db_path) as server:
                improve = server.post_json(
                    "/api/improve",
                    {
                        "source_candidate_id": "openclaw_main",
                        "source_home": str(home),
                        "source_import_output_dir": str(tmp_path / "normalized"),
                        "profile_id": "profile_news_research_001",
                        "operator": "adapter",
                        "operator_adapter": "fixture_operator",
                        "run_autonomy": False,
                    },
                )
                operator_runs = server.get_json("/api/operator-runs")

            self.assertEqual(improve["source_import"]["candidate"]["id"], "openclaw_main")
            self.assertEqual(improve["profile_id"], "profile_news_research_001")
            self.assertEqual(improve["operator"], "adapter")
            self.assertEqual(improve["analyze"]["operator"], "fixture_operator")
            self.assertTrue(improve["proposal_id"].startswith("proposal_command_"))
            self.assertEqual(operator_runs["operator_runs"][0]["operator_label"], "fixture_operator")

    def test_improve_endpoint_runs_selected_replay_adapter_for_discovered_source(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            db_path = tmp_path / "kyoko.db"
            home = tmp_path / "home"
            output_dir = tmp_path / "selected-discovery-replay"
            _write_failed_openclaw_session(home)
            ingest_source_fixture(db_path, FIXTURE)
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                profile_id="profile_news_research_001",
                output_dir=output_dir,
                default_side_effect_mode="network_mocked",
            )

            with RunningServer(db_path) as server:
                improve = server.post_json(
                    "/api/improve",
                    {
                        "source_candidate_id": "openclaw_main",
                        "source_home": str(home),
                        "source_import_output_dir": str(tmp_path / "normalized"),
                        "profile_id": "profile_news_research_001",
                        "replay_adapter_id": "fixture_replay",
                        "run_autonomy": False,
                    },
                )
                evals = server.get_json("/api/evals")

            self.assertEqual(improve["source_import"]["candidate"]["id"], "openclaw_main")
            self.assertEqual(improve["profile_id"], "profile_news_research_001")
            self.assertTrue(improve["replay_runs"])
            self.assertEqual(improve["replay_runs"][0]["adapter_id"], "fixture_replay")
            self.assertEqual(improve["replay_runs"][0]["eval_run"]["status"], "passed")
            self.assertIsNone(improve["autonomy"])
            self.assertEqual(len(evals["replay_runs"]), 1)

    def test_replay_server_lifecycle_endpoints_control_managed_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "server-output"
            ingest_source_fixture(db_path, FIXTURE)
            port = _free_port()
            server_url = f"http://127.0.0.1:{port}"
            register_replay_adapter(
                db_path=db_path,
                adapter_id="web_managed_http_replay",
                name="Web managed HTTP replay",
                command=[sys.executable, "-m", "kyoko.fixture_replay_server", "--port", str(port)],
                server_url=server_url,
                output_dir=output_dir,
                startup_timeout_seconds=5,
            )

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                adapters = server.get_json("/api/replay-adapters")
                start = server.post_json(
                    "/api/replay-servers/start",
                    {"adapter_id": "web_managed_http_replay"},
                )
                try:
                    status_post = server.post_json(
                        "/api/replay-servers/status",
                        {"adapter_id": "web_managed_http_replay"},
                    )
                    status_get = server.get_json(
                        "/api/replay-servers/status?id=web_managed_http_replay"
                    )
                    logs_post = server.post_json(
                        "/api/replay-servers/logs",
                        {"adapter_id": "web_managed_http_replay", "max_bytes": 2000},
                    )
                    logs_get = server.get_json(
                        "/api/replay-servers/logs?id=web_managed_http_replay&max_bytes=2000"
                    )
                finally:
                    stop = server.post_json(
                        "/api/replay-servers/stop",
                        {"adapter_id": "web_managed_http_replay"},
                    )

            self.assertIn("/api/replay-servers/start", html)
            self.assertIn("/api/replay-servers/logs", html)
            self.assertEqual(adapters["replay_adapters"][0]["kind"], "managed_http_server")
            self.assertTrue(start["started"])
            self.assertTrue(start["running"])
            self.assertTrue(start["healthy"])
            self.assertEqual(start["server_url"], server_url)
            self.assertEqual(status_post["pid"], start["pid"])
            self.assertTrue(status_post["running"])
            self.assertTrue(status_post["healthy"])
            self.assertEqual(status_get["pid"], start["pid"])
            self.assertTrue(stop["stopped"])
            self.assertFalse(stop["running"])
            self.assertTrue(Path(start["state_path"]).exists())
            self.assertTrue(Path(start["stdout_path"]).exists())
            self.assertIn("kyoko fixture replay server listening", logs_post["stdout"])
            self.assertEqual(logs_post["stdout"], logs_get["stdout"])
            self.assertEqual(logs_post["max_bytes"], 2000)

    def test_operator_adapter_endpoint_runs_registered_adapter(self) -> None:
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

            with RunningServer(db_path) as server:
                adapters = server.get_json("/api/operator-adapters")
                analysis = server.post_json(
                    "/api/operator-adapters/run",
                    {"adapter_id": "fixture_operator"},
                )
                proposals = server.get_json("/api/proposals")
                operator_runs = server.get_json("/api/operator-runs")
                status = server.get_json("/api/status")

            self.assertEqual(adapters["operator_adapters"][0]["id"], "fixture_operator")
            self.assertEqual(analysis["operator"], "fixture_operator")
            self.assertEqual(analysis["proposal_id"], "proposal_command_span_fetch_timeout_001")
            self.assertTrue(analysis["operator_run_id"])
            self.assertTrue(Path(analysis["prompt_path"]).exists())
            self.assertEqual(proposals["proposals"][0]["id"], "proposal_command_span_fetch_timeout_001")
            self.assertEqual(status["counts"]["operator_adapters"], 1)
            self.assertEqual(status["counts"]["operator_runs"], 1)
            self.assertEqual(operator_runs["operator_runs"][0]["status"], "succeeded")
            self.assertEqual(operator_runs["operator_runs"][0]["attempt_count"], 1)
            self.assertIsNone(operator_runs["operator_runs"][0]["failure_kind"])

    def test_operator_bootstrap_and_smoke_endpoints(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                presets = server.get_json("/api/operator-presets")
                with patch("kyoko.operator_presets.shutil.which", return_value="/usr/local/bin/codex"):
                    bootstrap = server.post_json(
                        "/api/operator-adapters/bootstrap",
                        {"target": "codex"},
                    )
                adapters = server.get_json("/api/operator-adapters")
                prepare = server.post_json(
                    "/api/operator-smoke",
                    {"operator": "mock", "prepare_only": True},
                )
                with patch("kyoko.operator_smoke.shutil.which", return_value="/usr/local/bin/operator"):
                    prepare_all = server.post_json(
                        "/api/operator-smoke",
                        {
                            "all_presets": True,
                            "prepare_only": True,
                            "output_dir": str(Path(tmpdir) / "operator-smoke-matrix"),
                        },
                    )
                smoke = server.post_json("/api/operator-smoke", {"operator": "mock"})
                status = server.get_json("/api/status")

            self.assertIn("/api/operator-adapters/bootstrap", html)
            self.assertIn("/api/operator-smoke", html)
            self.assertIn("/api/operator-runs", html)
            self.assertIn("Operator Runs", html)
            self.assertIn("Prepare mock", html)
            self.assertIn("Prepare all presets", html)
            self.assertIn("Live operator", html)
            self.assertEqual(
                {preset["adapter_id"] for preset in presets["operator_presets"]},
                {"codex", "claude", "hermes", "openclaw"},
            )
            self.assertEqual(bootstrap["registered"][0]["adapter_id"], "codex")
            self.assertEqual(adapters["operator_adapters"][0]["id"], "codex")
            self.assertFalse(prepare["live_operator_invoked"])
            self.assertTrue(Path(prepare["prompt_path"]).exists())
            self.assertTrue(prepare_all["passed"])
            self.assertEqual(prepare_all["summary"]["prepared"], 4)
            self.assertEqual(
                [target["operator"] for target in prepare_all["targets"]],
                ["codex", "claude", "hermes", "openclaw"],
            )
            self.assertTrue(Path(prepare_all["targets"][0]["plan"]["prompt_path"]).exists())
            self.assertTrue(smoke["used_demo_database"])
            self.assertEqual(smoke["proposal_id"], "proposal_mock_span_fetch_timeout_001")
            self.assertEqual(status["counts"]["learning_proposals"], 0)
            self.assertEqual(status["counts"]["operator_adapters"], 1)

    def test_mcp_install_smoke_endpoint_runs_matrix(self) -> None:
        class FakeMcpInstallSmokeReport:
            def __init__(self, payload: dict) -> None:
                self.payload = payload

            def to_json(self) -> dict:
                return self.payload

        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "mcp-install-smoke"
            payload = {
                "targets": ["codex", "claude"],
                "server": "kyoko",
                "output_dir": str(output_dir),
                "passed": True,
                "summary": {
                    "total": 2,
                    "passed": 1,
                    "failed": 0,
                    "skipped": 1,
                    "available": 1,
                },
                "results": [
                    {"target": "codex", "status": "skipped", "reason": "mcp_client_not_found:codex"},
                    {"target": "claude", "status": "passed", "reason": None},
                ],
            }

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                with patch(
                    "kyoko.web.run_mcp_install_smoke_matrix",
                    return_value=FakeMcpInstallSmokeReport(payload),
                ) as smoke:
                    result = server.post_json(
                        "/api/mcp-install-smoke",
                        {
                            "output_dir": str(output_dir),
                            "scope": "user",
                            "skip_list_verify": True,
                        },
                    )

            self.assertIn("/api/mcp-install-smoke", html)
            self.assertIn("Smoke MCP clients", html)
            self.assertTrue(result["passed"])
            self.assertEqual(result["summary"]["skipped"], 1)
            self.assertEqual(smoke.call_args.kwargs["output_dir"], output_dir)
            self.assertFalse(smoke.call_args.kwargs["verify_list"])

    def test_doctor_endpoint_runs_safe_smokes(self) -> None:
        class FakeDoctorReport:
            ok = True

            def to_json(self) -> dict:
                return {
                    "ok": True,
                    "summary": {"passed": 3, "warnings": 1, "failed": 0},
                    "readiness": {
                        "local_runtime_ready": True,
                        "local_v0_ready": True,
                        "safe_smokes_complete": True,
                        "pending_safe_smoke_checks": [],
                        "blocking_checks": [],
                        "warning_checks": ["release_python_targets"],
                        "external_evidence_warnings": ["release_python_targets"],
                        "pending_external_evidence_commands": ["release_smoke_matrix"],
                    },
                    "checks": [
                        {
                            "id": "demo_smoke",
                            "status": "pass",
                            "message": "Bundled demo loop completed.",
                            "detail": {
                                "artifacts_retained": True,
                                "output_dir": "/tmp/doctor/demo",
                            },
                        }
                    ],
                    "suggested_commands": [
                        {
                            "intent": "release_smoke_matrix",
                            "label": "Run release install smoke matrix",
                            "cli_args": [
                                "python3",
                                "-m",
                                "kyoko",
                                "release-smoke",
                                "--python-matrix",
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

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                with patch("kyoko.web.run_doctor", return_value=FakeDoctorReport()) as doctor:
                    payload = server.post_json(
                        "/api/doctor",
                        {
                            "safe_smokes": True,
                            "ace_native_prepare": True,
                            "improve_smoke": True,
                            "opentelemetry_smoke": True,
                            "opentelemetry_python_executable": str(output_dir / "bin/python"),
                            "ace_native_smoke": True,
                            "dashboard_smoke": True,
                            "dashboard_smoke_screenshot": True,
                            "dashboard_smoke_install_browser_deps": True,
                            "dashboard_smoke_timeout_seconds": 45,
                            "smoke_output_dir": str(output_dir),
                        },
                    )

            self.assertIn("/api/doctor", html)
            self.assertIn("First-Run Doctor", html)
            self.assertIn("Run safe doctor", html)
            self.assertIn("native ACE", html)
            self.assertIn("Dashboard browser smoke", html)
            self.assertIn("Local v0", html)
            self.assertIn("External evidence follow-ups", html)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["warnings"], 1)
            self.assertTrue(payload["readiness"]["local_v0_ready"])
            self.assertEqual(
                payload["readiness"]["pending_external_evidence_commands"],
                ["release_smoke_matrix"],
            )
            self.assertTrue(payload["checks"][0]["detail"]["artifacts_retained"])
            self.assertEqual(doctor.call_args.kwargs["db_path"], db_path)
            self.assertTrue(doctor.call_args.kwargs["safe_smokes"])
            self.assertTrue(doctor.call_args.kwargs["ace_native_prepare"])
            self.assertTrue(doctor.call_args.kwargs["improve_smoke"])
            self.assertTrue(doctor.call_args.kwargs["opentelemetry_smoke"])
            self.assertEqual(
                doctor.call_args.kwargs["opentelemetry_python_executable"],
                output_dir / "bin/python",
            )
            self.assertTrue(doctor.call_args.kwargs["ace_native_smoke"])
            self.assertTrue(doctor.call_args.kwargs["dashboard_smoke"])
            self.assertTrue(doctor.call_args.kwargs["dashboard_smoke_screenshot"])
            self.assertTrue(doctor.call_args.kwargs["dashboard_smoke_install_browser_deps"])
            self.assertEqual(doctor.call_args.kwargs["dashboard_smoke_timeout_seconds"], 45)
            self.assertEqual(doctor.call_args.kwargs["smoke_output_dir"], output_dir)
            self.assertEqual(doctor.call_args.kwargs["smoke_evidence_dir"], Path(".kyoko/smoke"))

    def test_integration_template_endpoints_generate_scaffolds(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            tmp_path = Path(tmpdir)
            source_output = Path(tmpdir) / "kyoko_source_adapter.py"
            replay_output = Path(tmpdir) / "kyoko_replay_server.py"
            hermes_db = Path(tmpdir) / "kanban.db"
            hermes_output = Path(tmpdir) / "hermes-source-events.json"
            openclaw_sessions = _write_openclaw_sessions(tmp_path)
            openclaw_output = Path(tmpdir) / "openclaw-source-events.json"
            _write_hermes_kanban_db(hermes_db)
            source_hook = tmp_path / "source_hook.py"
            source_hook.write_text(_source_hook(), encoding="utf-8")
            replay_hook = tmp_path / "replay_hook.py"
            replay_hook.write_text(
                """
def replay(request):
    return {
        "status": "passed",
        "output_run_id": "run_web_smoke_replay_001",
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {},
    }
""",
                encoding="utf-8",
            )
            replay_port = _free_port()

            with RunningServer(db_path) as server:
                html = _dashboard_html()
                frameworks = server.get_json("/api/integration-frameworks")
                source = server.post_json(
                    "/api/source-adapter-template",
                    {
                        "output_path": str(source_output),
                        "framework": "openai-agents-python",
                        "profile_name": "openai-research",
                    },
                )
                replay = server.post_json(
                    "/api/replay-server-template",
                    {
                        "output_path": str(replay_output),
                        "framework": "hermes-python",
                        "profile_name": "hermes-news",
                    },
                )
                source_smoke = server.post_json(
                    "/api/integration-smoke/source",
                    {
                        "adapter_path": str(source_output),
                        "hook": f"{source_hook}:collect",
                        "output_dir": str(tmp_path / "source-smoke"),
                        "profile_id": "profile_web_smoke",
                    },
                )
                replay_smoke = server.post_json(
                    "/api/integration-smoke/replay-server",
                    {
                        "command": f"{sys.executable} {replay_output} --port {replay_port}",
                        "server_url": f"http://127.0.0.1:{replay_port}",
                        "output_dir": str(tmp_path / "replay-smoke"),
                        "hook": f"{replay_hook}:replay",
                        "run_replay": True,
                        "startup_timeout_seconds": 5,
                    },
                )
                hermes_import = server.post_json(
                    "/api/import-hermes-kanban",
                    {
                        "kanban_db_path": str(hermes_db),
                        "board": "news",
                        "profile_id": "profile_web_hermes",
                        "output_path": str(hermes_output),
                    },
                )
                openclaw_import = server.post_json(
                    "/api/import-openclaw-sessions",
                    {
                        "session_path": str(openclaw_sessions),
                        "agent_id": "main",
                        "profile_id": "profile_web_openclaw",
                        "output_path": str(openclaw_output),
                    },
                )

            self.assertIn("/api/source-adapter-template", html)
            self.assertIn("/api/replay-server-template", html)
            self.assertIn("/api/integration-smoke/source", html)
            self.assertIn("/api/integration-smoke/replay-server", html)
            self.assertIn("/api/import-hermes-kanban", html)
            self.assertIn("/api/import-openclaw-sessions", html)
            self.assertIn(
                "openai-agents-python",
                {framework["id"] for framework in frameworks["source_frameworks"]},
            )
            self.assertIn(
                "ai-sdk-typescript",
                {framework["id"] for framework in frameworks["source_frameworks"]},
            )
            self.assertIn(
                "hermes-python",
                {framework["id"] for framework in frameworks["replay_frameworks"]},
            )
            self.assertIn(
                "openai-agents-python",
                {framework["id"] for framework in frameworks["replay_frameworks"]},
            )
            self.assertIn(
                "crewai-python",
                {framework["id"] for framework in frameworks["replay_frameworks"]},
            )
            self.assertIn(
                "ai-sdk-typescript",
                {framework["id"] for framework in frameworks["replay_frameworks"]},
            )
            self.assertEqual(source["framework"], "openai-agents-python")
            self.assertEqual(source["profile_name"], "openai-research")
            self.assertTrue(source_output.exists())
            self.assertEqual(replay["framework"], "hermes-python")
            self.assertEqual(replay["profile_name"], "hermes-news")
            self.assertTrue(replay_output.exists())
            self.assertEqual(source_smoke["kind"], "source_adapter")
            self.assertEqual(source_smoke["profile_id"], "profile_web_smoke")
            self.assertEqual(source_smoke["status"]["counts"]["runs"], 1)
            self.assertEqual(replay_smoke["kind"], "replay_server")
            self.assertTrue(replay_smoke["healthy"])
            self.assertTrue(replay_smoke["replay_ok"])
            self.assertEqual(
                replay_smoke["replay_response"]["output_run_id"],
                "run_web_smoke_replay_001",
            )
            self.assertTrue(replay_smoke["stopped"])
            self.assertEqual(hermes_import["profile_id"], "profile_web_hermes")
            self.assertEqual(hermes_import["counts"]["tasks"], 2)
            self.assertEqual(hermes_import["counts"]["handoffs"], 1)
            self.assertTrue(hermes_output.exists())
            self.assertEqual(openclaw_import["profile_id"], "profile_web_openclaw")
            self.assertEqual(openclaw_import["counts"]["tasks"], 1)
            self.assertEqual(openclaw_import["counts"]["spans"], 6)
            self.assertEqual(openclaw_import["counts"]["handoffs"], 1)
            self.assertTrue(openclaw_output.exists())
            status = get_database_status(db_path)
            self.assertEqual(status.counts["profiles"], 3)
            self.assertEqual(status.counts["tasks"], 3)
            self.assertEqual(status.counts["handoffs"], 2)

    def test_apply_endpoint_rejects_missing_proposal_id(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            with RunningServer(db_path) as server:
                request = Request(
                    f"{server.base_url}/api/apply",
                    data=json.dumps({}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as raised:
                    urlopen(request, timeout=5)

            self.assertEqual(raised.exception.code, 400)


def _set_web_eval_type(db_path: Path, eval_spec_id: str, eval_type: str, definition: dict) -> None:
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE eval_specs SET eval_type = ?, definition_json = ? WHERE id = ?",
            (eval_type, json.dumps(definition, sort_keys=True), eval_spec_id),
        )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    unittest.main()
