import json
import os
import py_compile
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.cli import main
from kyoko.blobs import list_payload_blobs
from kyoko.source_templates import SourceTemplateError, write_source_adapter_template
from kyoko.storage import connect, get_database_status, ingest_source_json


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_HOOKS = ROOT / "examples" / "source-hooks"


class SourceTemplateTests(unittest.TestCase):
    def test_generated_source_adapter_emits_ingestable_canonical_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            adapter_path = tmp_path / "kyoko_source_adapter.py"
            hook_path = tmp_path / "source_hook.py"
            output_path = tmp_path / "source-events.json"
            db_path = tmp_path / "kyoko.db"

            report = write_source_adapter_template(
                output_path=adapter_path,
                framework="langgraph-python",
                profile_name="news-research",
            )
            py_compile.compile(str(adapter_path), doraise=True)
            hook_path.write_text(_source_hook(), encoding="utf-8")

            env = os.environ.copy()
            env["KYOKO_SOURCE_HOOK"] = f"{hook_path}:collect"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(adapter_path),
                    "--output",
                    str(output_path),
                    "--profile-id",
                    "profile_template_news",
                    "--agent-id",
                    "agent_template_researcher",
                    "--source-id",
                    "source_template_langgraph",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            payload = json.loads(output_path.read_text())
            ingest = ingest_source_json(db_path, output_path)
            status = get_database_status(db_path)

            self.assertEqual(report.framework, "langgraph-python")
            self.assertEqual(payload["profile"]["id"], "profile_template_news")
            self.assertEqual(ingest.profile_id, "profile_template_news")
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 1)

    def test_generated_typescript_source_adapter_emits_ingestable_canonical_json(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is not installed")
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            adapter_path = tmp_path / "kyoko_source_adapter.mjs"
            hook_path = tmp_path / "source_hook.mjs"
            output_path = tmp_path / "source-events.json"
            db_path = tmp_path / "kyoko.db"

            report = write_source_adapter_template(
                output_path=adapter_path,
                framework="ai-sdk-typescript",
                profile_name="ai-sdk-news",
            )
            check = subprocess.run(
                [node, "--check", str(adapter_path)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(check.returncode, 0, check.stderr)
            hook_path.write_text(_typescript_source_hook(), encoding="utf-8")

            env = os.environ.copy()
            env["KYOKO_SOURCE_HOOK"] = f"{hook_path}:collect"
            completed = subprocess.run(
                [
                    node,
                    str(adapter_path),
                    "--output",
                    str(output_path),
                    "--profile-id",
                    "profile_template_ai_sdk",
                    "--agent-id",
                    "agent_template_planner",
                    "--source-id",
                    "source_template_ai_sdk",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            payload = json.loads(output_path.read_text())
            ingest = ingest_source_json(db_path, output_path)
            status = get_database_status(db_path)

            self.assertEqual(report.framework, "ai-sdk-typescript")
            self.assertEqual(payload["profile"]["id"], "profile_template_ai_sdk")
            self.assertEqual(payload["sources"][0]["kind"], "ai-sdk-typescript")
            self.assertEqual(ingest.profile_id, "profile_template_ai_sdk")
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 1)

    def test_template_refuses_overwrite_without_force(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "kyoko_source_adapter.py"
            write_source_adapter_template(output_path=output_path)

            with self.assertRaisesRegex(SourceTemplateError, "exists"):
                write_source_adapter_template(output_path=output_path)

            report = write_source_adapter_template(output_path=output_path, force=True)
            self.assertTrue(report.wrote)

    def test_cli_writes_source_template_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "kyoko_source_adapter.py"
            stdout = StringIO()

            with redirect_stdout(stdout):
                code = main(
                    [
                        "source-adapter-template",
                        str(output_path),
                        "--framework",
                        "openai-agents-python",
                        "--profile-name",
                        "openai-research",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["framework"], "openai-agents-python")
            self.assertEqual(payload["profile_name"], "openai-research")
            self.assertTrue(output_path.exists())

    def test_langgraph_example_hook_runs_through_generated_adapter(self) -> None:
        self._assert_python_example_hook(
            framework="langgraph-python",
            hook=EXAMPLE_HOOKS / "langgraph_source_hook.py",
            profile_id="profile_example_langgraph",
            source_id="source_example_langgraph",
            expected_runs=1,
            expected_spans=2,
            expected_handoffs=1,
            expected_min_blobs=8,
        )

    def test_pydantic_ai_example_hook_runs_through_generated_adapter(self) -> None:
        self._assert_python_example_hook(
            framework="pydantic-ai-python",
            hook=EXAMPLE_HOOKS / "pydantic_ai_source_hook.py",
            profile_id="profile_example_pydantic_ai",
            source_id="source_example_pydantic_ai",
            expected_runs=1,
            expected_spans=2,
            expected_handoffs=0,
            expected_min_blobs=6,
        )

    def test_openai_agents_example_hook_runs_through_generated_adapter(self) -> None:
        self._assert_python_example_hook(
            framework="openai-agents-python",
            hook=EXAMPLE_HOOKS / "openai_agents_source_hook.py",
            profile_id="profile_example_openai_agents",
            source_id="source_example_openai_agents",
            expected_runs=1,
            expected_spans=3,
            expected_handoffs=1,
            expected_min_blobs=10,
        )

    def _assert_python_example_hook(
        self,
        *,
        framework: str,
        hook: Path,
        profile_id: str,
        source_id: str,
        expected_runs: int,
        expected_spans: int,
        expected_handoffs: int,
        expected_min_blobs: int,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            adapter_path = tmp_path / "kyoko_source_adapter.py"
            output_path = tmp_path / "source-events.json"
            db_path = tmp_path / "kyoko.db"

            report = write_source_adapter_template(
                output_path=adapter_path,
                framework=framework,
                profile_name="example-profile",
            )
            py_compile.compile(str(adapter_path), doraise=True)

            env = os.environ.copy()
            env["KYOKO_SOURCE_HOOK"] = f"{hook}:collect"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(adapter_path),
                    "--output",
                    str(output_path),
                    "--profile-id",
                    profile_id,
                    "--agent-id",
                    "agent_example_primary",
                    "--source-id",
                    source_id,
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)

            payload = json.loads(output_path.read_text())
            ingest = ingest_source_json(db_path, output_path)
            status = get_database_status(db_path)
            blobs = list_payload_blobs(db_path)

            self.assertEqual(report.framework, framework)
            self.assertEqual(payload["profile"]["id"], profile_id)
            self.assertEqual(payload["sources"][0]["kind"], framework)
            self.assertEqual(ingest.profile_id, profile_id)
            self.assertEqual(status.counts["runs"], expected_runs)
            self.assertEqual(status.counts["spans"], expected_spans)
            self.assertEqual(status.counts["handoffs"], expected_handoffs)
            self.assertGreaterEqual(status.counts["payload_blobs"], expected_min_blobs)
            self.assertEqual(status.counts["payload_blobs"], len(blobs))
            self.assertTrue(all(Path(blob["path"]).exists() for blob in blobs))
            self.assertTrue(_has_blob_ref(db_path, "runs", "input_ref"))
            self.assertTrue(_has_blob_ref(db_path, "spans", "input_ref"))
            self.assertTrue(_has_blob_ref(db_path, "timeline_events", "payload_ref"))
            if expected_handoffs:
                self.assertTrue(_has_blob_ref(db_path, "handoffs", "payload_ref"))


def _source_hook() -> str:
    return """
import sys


def collect(context):
    if __name__ not in sys.modules:
        raise KeyError(__name__)
    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    agent_id = context["agent_id"]
    node_id = "node_template_researcher"
    run_id = "run_template_001"
    span_id = "span_template_001"
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        },
        "sources": [{
            "id": source_id,
            "profile_id": profile_id,
            "kind": context["framework"],
            "display_name": "Template source",
            "status": "active",
            "adapter_version": "test",
            "config_json": {},
            "capabilities_json": ["trace"],
            "last_seen_at": now,
        }],
        "agent_identities": [{
            "id": agent_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": "researcher",
            "name": context["agent_name"],
            "kind": "agent",
            "role": None,
            "model": None,
            "workspace_path": context["root_path"],
            "metadata_json": {},
        }],
        "workflow_nodes": [{
            "id": node_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": "researcher",
            "agent_identity_id": agent_id,
            "kind": "agent",
            "name": context["agent_name"],
            "metadata_json": {},
        }],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [{
            "id": run_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": run_id,
            "root_span_id": span_id,
            "agent_identity_id": agent_id,
            "task_attempt_id": None,
            "status": "succeeded",
            "started_at": now,
            "ended_at": now,
            "input_ref": "input://template",
            "output_ref": "output://template",
            "summary": "Template run",
            "metadata_json": {},
        }],
        "spans": [{
            "id": span_id,
            "run_id": run_id,
            "source_id": source_id,
            "external_id": span_id,
            "parent_span_id": None,
            "workflow_node_id": node_id,
            "agent_identity_id": agent_id,
            "kind": "agent",
            "name": "Template run",
            "status": "succeeded",
            "started_at": now,
            "ended_at": now,
            "input_ref": "input://template",
            "output_ref": "output://template",
            "usage_json": {},
            "attributes_json": {},
            "raw_ref": None,
        }],
        "handoffs": [],
        "timeline_events": [],
    }
"""


def _has_blob_ref(db_path: Path, table: str, column: str) -> bool:
    with connect(db_path) as connection:
        row = connection.execute(
            f"SELECT 1 FROM {table} WHERE {column} LIKE 'blob_sha256_%' LIMIT 1"
        ).fetchone()
    return row is not None


def _typescript_source_hook() -> str:
    return """
export async function collect(context) {
  const now = "2026-01-01T00:00:00Z";
  const runId = "run_template_ts_001";
  const spanId = "span_template_ts_001";
  return {
    runs: [{
      id: runId,
      profile_id: context.profile_id,
      source_id: context.source_id,
      external_id: runId,
      root_span_id: spanId,
      agent_identity_id: context.agent_id,
      task_attempt_id: null,
      status: "succeeded",
      started_at: now,
      ended_at: now,
      input_ref: "input://template-ts",
      output_ref: "output://template-ts",
      summary: "Template TypeScript run",
      metadata_json: { framework: context.framework }
    }],
    spans: [{
      id: spanId,
      run_id: runId,
      source_id: context.source_id,
      external_id: spanId,
      parent_span_id: null,
      workflow_node_id: "node_" + context.agent_name.replace(/[^a-zA-Z0-9]+/g, "_").toLowerCase(),
      agent_identity_id: context.agent_id,
      kind: "agent",
      name: "Template TypeScript run",
      status: "succeeded",
      started_at: now,
      ended_at: now,
      input_ref: "input://template-ts",
      output_ref: "output://template-ts",
      usage_json: {},
      attributes_json: {},
      raw_ref: null
    }]
  };
}
"""


if __name__ == "__main__":
    unittest.main()
