import io
import json
import sqlite3
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.cli import main
from kyoko.openclaw_import import ingest_openclaw_sessions, normalize_openclaw_sessions
from kyoko.storage import get_database_status


class OpenClawImportTests(unittest.TestCase):
    def test_normalize_openclaw_sessions_preserves_session_entities(self) -> None:
        with TemporaryDirectory() as tmpdir:
            sessions_dir = _write_openclaw_sessions(Path(tmpdir))

            payload = normalize_openclaw_sessions(
                source_path=sessions_dir,
                profile_id="profile_openclaw_news",
                profile_name="OpenClaw News",
            )

            self.assertEqual(payload["profile"]["id"], "profile_openclaw_news")
            self.assertEqual(payload["profile"]["root_path"], "/tmp/openclaw-news")
            self.assertEqual(payload["sources"][0]["kind"], "openclaw_sessions")
            self.assertEqual(payload["sources"][0]["adapter_version"], "kyoko.openclaw_session_import.v0")
            self.assertEqual(payload["queues"][0]["kind"], "openclaw_agent_sessions")
            self.assertEqual(len(payload["tasks"]), 1)
            self.assertEqual(len(payload["task_attempts"]), 1)
            self.assertEqual(len(payload["runs"]), 1)
            self.assertEqual(len(payload["spans"]), 6)
            self.assertEqual(len(payload["timeline_events"]), 5)
            self.assertEqual(len(payload["handoffs"]), 1)
            self.assertEqual(payload["handoffs"][0]["kind"], "agent_handoff")
            self.assertEqual(
                {agent["name"] for agent in payload["agent_identities"]},
                {"main", "researcher", "user"},
            )
            self.assertEqual(payload["tasks"][0]["status"], "done")
            self.assertEqual(payload["runs"][0]["status"], "succeeded")

    def test_ingest_openclaw_sessions_populates_kyoko_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sessions_dir = _write_openclaw_sessions(tmp_path)
            kyoko_db = tmp_path / "kyoko.db"
            normalized = tmp_path / "openclaw-source-events.json"

            report = ingest_openclaw_sessions(
                db_path=kyoko_db,
                source_path=sessions_dir,
                profile_id="profile_openclaw_news",
                output_path=normalized,
            )
            status = get_database_status(kyoko_db)

            self.assertEqual(report.profile_id, "profile_openclaw_news")
            self.assertTrue(normalized.exists())
            self.assertEqual(status.counts["profiles"], 1)
            self.assertEqual(status.counts["sources"], 1)
            self.assertEqual(status.counts["queues"], 1)
            self.assertEqual(status.counts["agent_identities"], 3)
            self.assertEqual(status.counts["tasks"], 1)
            self.assertEqual(status.counts["task_attempts"], 1)
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 6)
            self.assertEqual(status.counts["handoffs"], 1)
            self.assertEqual(status.counts["timeline_events"], 5)

    def test_failed_openclaw_session_materializes_error_payload(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            transcript = tmp_path / "failed-session.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "id": "failure-1",
                        "type": "error",
                        "agentId": "main",
                        "error": {"message": "tool failed"},
                        "timestamp": "2026-05-31T12:05:00Z",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            kyoko_db = tmp_path / "kyoko.db"

            payload = normalize_openclaw_sessions(source_path=transcript, profile_id="profile_openclaw_failed")
            report = ingest_openclaw_sessions(
                db_path=kyoko_db,
                source_path=transcript,
                profile_id="profile_openclaw_failed",
            )
            status = get_database_status(kyoko_db)

            self.assertEqual(payload["tasks"][0]["status"], "blocked")
            self.assertEqual(payload["runs"][0]["status"], "failed")
            self.assertIsNone(payload["task_attempts"][0]["error_ref"])
            self.assertEqual(payload["task_attempts"][0]["error_payload"], {"message": "tool failed"})
            self.assertGreater(report.ingested_counts["payload_blobs"], 0)
            self.assertGreater(status.counts["payload_blobs"], 0)
            with sqlite3.connect(str(kyoko_db)) as connection:
                row = connection.execute(
                    "SELECT error_ref FROM task_attempts WHERE id = ?",
                    ("attempt_openclaw_failed_session",),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertTrue(str(row[0]).startswith("blob_"))

    def test_cli_import_openclaw_sessions_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sessions_dir = _write_openclaw_sessions(tmp_path)
            kyoko_db = tmp_path / "kyoko.db"

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

            self.assertEqual(code, 0)
            self.assertEqual(payload["profile_id"], "profile_cli_openclaw")
            self.assertEqual(payload["counts"]["tasks"], 1)
            self.assertEqual(payload["counts"]["spans"], 6)
            self.assertEqual(payload["counts"]["handoffs"], 1)
            self.assertEqual(payload["ingested_counts"]["runs"], 1)


def _write_openclaw_sessions(root: Path) -> Path:
    sessions_dir = root / ".openclaw" / "agents" / "main" / "sessions"
    sessions_dir.mkdir(parents=True)
    store = {
        "agent:main:session-news": {
            "sessionId": "session-news",
            "title": "News research session",
            "workspacePath": "/tmp/openclaw-news",
            "createdAt": "2026-05-31T12:00:00Z",
            "updatedAt": "2026-05-31T12:04:00Z",
            "transcriptPath": "session-news.jsonl",
        }
    }
    (sessions_dir / "sessions.json").write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")
    records = [
        {
            "id": "event-1",
            "type": "message",
            "role": "user",
            "content": "Find current product launch news.",
            "timestamp": "2026-05-31T12:00:00Z",
        },
        {
            "id": "event-2",
            "type": "message",
            "role": "assistant",
            "agentId": "main",
            "content": "I will delegate source discovery.",
            "timestamp": "2026-05-31T12:01:00Z",
            "usage": {"input_tokens": 12, "output_tokens": 8},
        },
        {
            "id": "event-3",
            "type": "delegate_task",
            "fromAgent": "main",
            "toAgent": "researcher",
            "content": "Find supporting sources.",
            "timestamp": "2026-05-31T12:02:00Z",
        },
        {
            "id": "event-4",
            "type": "tool_call",
            "agentId": "researcher",
            "toolName": "search",
            "content": {"query": "product launch news"},
            "timestamp": "2026-05-31T12:03:00Z",
        },
        {
            "id": "event-5",
            "type": "message",
            "role": "assistant",
            "agentId": "researcher",
            "content": "Found two relevant launch updates.",
            "timestamp": "2026-05-31T12:04:00Z",
        },
    ]
    transcript = "\n".join(json.dumps(record, sort_keys=True) for record in records)
    (sessions_dir / "session-news.jsonl").write_text(transcript + "\n", encoding="utf-8")
    return sessions_dir
