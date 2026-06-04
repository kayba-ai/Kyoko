import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from kyoko.blobs import list_payload_blobs
from kyoko.storage import (
    StorageError,
    checkpoint_database,
    connect,
    get_database_status,
    ingest_source_payload,
    ingest_source_json,
    ingest_source_fixture,
    initialize_database,
    status_to_json,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
LEGACY_SCHEMA_FIXTURE = ROOT / "docs/fixtures/storage/legacy-schema-v14.sql"


class StorageTests(unittest.TestCase):
    def test_initialize_database_creates_schema(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            initialize_database(db_path)
            status = get_database_status(db_path)

            self.assertTrue(status.initialized)
            self.assertEqual(status.schema_version, 27)
            self.assertEqual(status.migration_versions, tuple(range(1, 28)))
            self.assertEqual(status.counts["profiles"], 0)
            self.assertEqual(status.counts["runs"], 0)
            self.assertEqual(status.counts["check_specs"], 0)
            self.assertEqual(status.counts["check_runs"], 0)
            self.assertEqual(status.counts["replay_runs"], 0)
            self.assertEqual(status.counts["replay_adapters"], 0)
            self.assertEqual(status.counts["operator_adapters"], 0)
            self.assertEqual(status.counts["operator_runs"], 0)
            self.assertEqual(status.counts["patch_transactions"], 0)
            self.assertEqual(status.counts["harness_target_locks"], 0)
            self.assertEqual(status.counts["check_locks"], 0)
            self.assertEqual(status.counts["context_delivery_rules"], 0)
            self.assertEqual(status.counts["skill_revisions"], 0)
            self.assertEqual(status.counts["context_delivery_rule_revisions"], 0)
            self.assertEqual(status.counts["issues"], 0)

    def test_ingest_source_fixture_populates_core_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            report = ingest_source_fixture(db_path, FIXTURE)
            status = get_database_status(db_path)

            self.assertEqual(report.profile_id, "profile_news_research_001")
            self.assertEqual(status.counts["profiles"], 1)
            self.assertEqual(status.counts["sources"], 2)
            self.assertEqual(status.counts["agent_identities"], 3)
            self.assertEqual(status.counts["workflow_nodes"], 2)
            self.assertEqual(status.counts["queues"], 1)
            self.assertEqual(status.counts["tasks"], 1)
            self.assertEqual(status.counts["task_attempts"], 1)
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 2)
            self.assertEqual(status.counts["handoffs"], 1)
            self.assertEqual(status.counts["timeline_events"], 2)
            self.assertEqual(status.counts["autonomy_policies"], 1)
            self.assertEqual(status.counts["payload_blobs"], 0)
            self.assertEqual(status.counts["context_delivery_rules"], 0)
            self.assertEqual(status.counts["skill_revisions"], 0)
            self.assertEqual(status.counts["context_delivery_rule_revisions"], 0)
            self.assertEqual(status.counts["check_specs"], 0)
            self.assertEqual(status.counts["check_runs"], 0)
            self.assertEqual(status.counts["replay_runs"], 0)
            self.assertEqual(status.counts["replay_adapters"], 0)
            self.assertEqual(status.counts["operator_adapters"], 0)
            self.assertEqual(status.counts["operator_runs"], 0)
            self.assertEqual(status.counts["patch_transactions"], 0)
            self.assertEqual(status.counts["harness_target_locks"], 0)
            self.assertEqual(status.counts["check_locks"], 0)
            self.assertEqual(status.counts["issues"], 0)

    def test_ingest_source_json_matches_fixture_ingest(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            report = ingest_source_json(db_path, FIXTURE)
            status = get_database_status(db_path)

            self.assertEqual(report.profile_id, "profile_news_research_001")
            self.assertEqual(report.inserted_counts["runs"], 1)
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 2)

    def test_large_source_ingest_and_wal_checkpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            payload = _large_source_payload(run_count=40, spans_per_run=5)

            report = ingest_source_payload(
                db_path=db_path,
                fixture=payload,
                source_label="generated-large-source",
            )
            status = get_database_status(db_path)
            checkpoint = checkpoint_database(db_path, mode="TRUNCATE")

            self.assertEqual(report.profile_id, "profile_large_load")
            self.assertEqual(status.counts["profiles"], 1)
            self.assertEqual(status.counts["runs"], 40)
            self.assertEqual(status.counts["spans"], 200)
            self.assertEqual(status.counts["timeline_events"], 40)
            self.assertEqual(checkpoint.mode, "TRUNCATE")
            self.assertGreaterEqual(checkpoint.wal_size_before, checkpoint.wal_size_after)
            self.assertGreaterEqual(checkpoint.log_frames, 0)
            self.assertGreaterEqual(checkpoint.checkpointed_frames, 0)

    def test_wal_checkpoint_rejects_unknown_mode(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            with self.assertRaisesRegex(StorageError, "unsupported_wal_checkpoint_mode"):
                checkpoint_database(db_path, mode="VACUUM")

    def test_status_json_is_machine_readable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            payload = status_to_json(get_database_status(db_path))
            encoded = json.dumps(payload, sort_keys=True)
            decoded = json.loads(encoded)

            self.assertEqual(decoded["db_path"], str(db_path))
            self.assertTrue(decoded["initialized"])
            self.assertEqual(decoded["schema_version"], 27)
            self.assertEqual(decoded["migration_versions"], list(range(1, 28)))
            self.assertEqual(decoded["counts"]["spans"], 2)

    def test_initialize_database_rejects_future_schema(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            with sqlite3.connect(str(db_path)) as connection:
                connection.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY)")
                connection.execute("INSERT INTO schema_migrations(version) VALUES (999)")

            with self.assertRaisesRegex(StorageError, "database_schema_too_new:999:supported:27"):
                initialize_database(db_path)

    def test_initialize_database_migrates_legacy_schema_fixture(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            with sqlite3.connect(str(db_path)) as connection:
                connection.executescript(LEGACY_SCHEMA_FIXTURE.read_text())

            initialize_database(db_path)
            status = get_database_status(db_path)

            self.assertTrue(status.initialized)
            self.assertEqual(status.schema_version, 27)
            self.assertEqual(status.migration_versions, tuple(range(1, 28)))
            self.assertEqual(status.counts["profiles"], 1)
            self.assertEqual(status.counts["skills"], 1)
            self.assertEqual(status.counts["context_delivery_rules"], 1)
            # SCOPE simplification: the legacy per-profile redaction/retention
            # policy tables and the redaction audit ledger are dropped on migration.
            self.assertNotIn("retention_policies", status.counts)
            self.assertNotIn("redaction_policies", status.counts)
            self.assertNotIn("redaction_audit_events", status.counts)

            with connect(db_path) as connection:
                user_version = connection.execute("PRAGMA user_version").fetchone()[0]
                skills_columns = _table_columns(connection, "skills")
                rules_columns = _table_columns(connection, "context_delivery_rules")
                existing_tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                skill = connection.execute(
                    "SELECT human_locked, human_lock_reason FROM skills WHERE id = ?",
                    ("skill_legacy_migration_001",),
                ).fetchone()
                rule = connection.execute(
                    """
                    SELECT human_locked, human_lock_reason
                    FROM context_delivery_rules
                    WHERE id = ?
                    """,
                    ("context_rule_legacy_migration_001",),
                ).fetchone()

            self.assertEqual(user_version, 27)
            self.assertIn("human_lock_reason", skills_columns)
            self.assertIn("human_lock_reason", rules_columns)
            self.assertNotIn("retention_policies", existing_tables)
            self.assertNotIn("redaction_policies", existing_tables)
            self.assertNotIn("redaction_audit_events", existing_tables)
            self.assertEqual(skill["human_locked"], 1)
            self.assertIsNone(skill["human_lock_reason"])
            self.assertEqual(rule["human_locked"], 1)
            self.assertIsNone(rule["human_lock_reason"])

    def test_ingest_materializes_inline_payloads_to_registered_blobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            payload = json.loads(FIXTURE.read_text())
            payload["runs"][0]["input_ref"] = None
            payload["runs"][0]["input_payload"] = {
                "content": "research request text",
                "media_type": "text/plain",
                "kind": "run_input",
                "metadata": {"fixture": "inline"},
            }
            payload["spans"][0]["input_ref"] = None
            payload["spans"][0]["input_payload"] = {
                "content": "research request text",
                "media_type": "text/plain",
                "kind": "span_input",
            }
            payload["spans"][1]["output_ref"] = None
            payload["spans"][1]["output_payload"] = {
                "content": {"error": "timeout", "retry_count": 0},
                "encoding": "json",
                "kind": "tool_output",
                "media_type": "application/json",
            }
            payload["timeline_events"][0]["payload_ref"] = None
            payload["timeline_events"][0]["payload"] = "timeout quote"

            report = ingest_source_payload(
                db_path=db_path,
                fixture=payload,
                source_label="inline-payload-fixture",
            )
            status = get_database_status(db_path)
            blobs = list_payload_blobs(db_path)
            blobs_by_kind = {blob["kind"]: blob for blob in blobs}

            self.assertEqual(report.inserted_counts["payload_blobs"], 4)
            self.assertEqual(status.counts["payload_blobs"], 3)
            self.assertEqual(blobs_by_kind["run_input"]["media_type"], "text/plain")
            self.assertEqual(blobs_by_kind["run_input"]["preview"], "research request text")
            self.assertEqual(
                blobs_by_kind["run_input"]["metadata"]["inline_payload_occurrences"],
                [
                    {
                        "source_label": "inline-payload-fixture",
                        "collection": "runs",
                        "row_id": "run_research_topic_001",
                        "ref_field": "input_ref",
                        "payload_field": "input_payload",
                    },
                    {
                        "source_label": "inline-payload-fixture",
                        "collection": "spans",
                        "row_id": "span_research_root_001",
                        "ref_field": "input_ref",
                        "payload_field": "input_payload",
                    }
                ],
            )
            self.assertEqual(blobs_by_kind["run_input"]["metadata"]["fixture"], "inline")
            self.assertEqual(blobs_by_kind["tool_output"]["media_type"], "application/json")
            self.assertTrue(Path(blobs_by_kind["tool_output"]["path"]).exists())

            with connect(db_path) as connection:
                run = connection.execute(
                    "SELECT input_ref FROM runs WHERE id = ?",
                    ("run_research_topic_001",),
                ).fetchone()
                span = connection.execute(
                    "SELECT output_ref FROM spans WHERE id = ?",
                    ("span_fetch_timeout_001",),
                ).fetchone()
                event = connection.execute(
                    "SELECT payload_ref FROM timeline_events WHERE id = ?",
                    ("event_fetch_timeout_001",),
                ).fetchone()
            self.assertTrue(str(run["input_ref"]).startswith("blob_sha256_"))
            self.assertTrue(str(span["output_ref"]).startswith("blob_sha256_"))
            self.assertTrue(str(event["payload_ref"]).startswith("blob_sha256_"))

    def test_ingest_rejects_inline_payload_when_ref_is_already_set(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            payload = json.loads(FIXTURE.read_text())
            payload["runs"][0]["input_payload"] = "conflicting inline payload"

            with self.assertRaisesRegex(StorageError, "input_payload_conflicts_with_input_ref"):
                ingest_source_payload(
                    db_path=db_path,
                    fixture=payload,
                    source_label="inline-conflict-fixture",
                )


def _large_source_payload(*, run_count: int, spans_per_run: int) -> dict:
    profile_id = "profile_large_load"
    source_id = "source_large_load"
    agent_id = "agent_large_load"
    node_id = "node_large_load"
    runs = []
    spans = []
    timeline_events = []

    for run_index in range(run_count):
        run_id = f"run_large_{run_index:04d}"
        root_span_id = f"span_large_{run_index:04d}_0000"
        runs.append(
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": f"external-run-{run_index}",
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": "2026-05-31T12:00:00Z",
                "ended_at": "2026-05-31T12:01:00Z",
                "input_ref": f"blob_run_input_{run_index:04d}",
                "output_ref": f"blob_run_output_{run_index:04d}",
                "summary": f"Generated load run {run_index}",
                "metadata_json": {"load_fixture": True, "run_index": run_index},
            }
        )
        for span_index in range(spans_per_run):
            span_id = f"span_large_{run_index:04d}_{span_index:04d}"
            failed = span_index == spans_per_run - 1 and run_index % 10 == 0
            spans.append(
                {
                    "id": span_id,
                    "run_id": run_id,
                    "source_id": source_id,
                    "external_id": f"external-span-{run_index}-{span_index}",
                    "parent_span_id": None if span_index == 0 else root_span_id,
                    "workflow_node_id": node_id,
                    "agent_identity_id": agent_id,
                    "kind": "agent" if span_index == 0 else "tool",
                    "name": "root" if span_index == 0 else f"tool_{span_index}",
                    "status": "failed" if failed else "succeeded",
                    "started_at": "2026-05-31T12:00:00Z",
                    "ended_at": "2026-05-31T12:00:30Z",
                    "input_ref": f"blob_span_input_{run_index:04d}_{span_index:04d}",
                    "output_ref": f"blob_span_output_{run_index:04d}_{span_index:04d}",
                    "usage_json": {"input_tokens": span_index, "output_tokens": span_index + 1},
                    "attributes_json": {
                        "load_fixture": True,
                        "run_index": run_index,
                        "span_index": span_index,
                    },
                    "raw_ref": f"blob_raw_span_{run_index:04d}_{span_index:04d}",
                }
            )
        timeline_events.append(
            {
                "id": f"event_large_{run_index:04d}",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "run",
                "entity_id": run_id,
                "kind": "run_completed",
                "at": "2026-05-31T12:01:00Z",
                "agent_identity_id": agent_id,
                "payload_ref": f"blob_event_{run_index:04d}",
                "metadata_json": {"load_fixture": True},
            }
        )

    return {
        "profile": {
            "id": profile_id,
            "name": "Large Load",
            "root_path": ".",
            "status": "active",
            "created_at": "2026-05-31T12:00:00Z",
            "updated_at": "2026-05-31T12:00:00Z",
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": "generated",
                "display_name": "Generated large source",
                "status": "active",
                "adapter_version": "test",
                "config_json": {},
                "capabilities_json": {"load_fixture": True},
                "last_seen_at": "2026-05-31T12:01:00Z",
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "large-agent",
                "name": "large-agent",
                "kind": "agent",
                "role": "researcher",
                "model": "test-model",
                "workspace_path": ".",
                "metadata_json": {"load_fixture": True},
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "large-node",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "large-node",
                "metadata_json": {"load_fixture": True},
            }
        ],
        "runs": runs,
        "spans": spans,
        "timeline_events": timeline_events,
    }


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


if __name__ == "__main__":
    unittest.main()
