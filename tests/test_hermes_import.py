import io
import json
import sqlite3
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.cli import main
from kyoko.hermes_import import ingest_hermes_kanban_db, normalize_hermes_kanban_db
from kyoko.storage import get_database_status


class HermesImportTests(unittest.TestCase):
    def test_normalize_hermes_kanban_db_preserves_coordination_entities(self) -> None:
        with TemporaryDirectory() as tmpdir:
            kanban_db = Path(tmpdir) / "kanban.db"
            _write_hermes_kanban_db(kanban_db)

            payload = normalize_hermes_kanban_db(
                kanban_db_path=kanban_db,
                profile_id="profile_hermes_news",
                profile_name="Hermes News",
                root_path=Path(tmpdir),
                board="news",
            )

            self.assertEqual(payload["profile"]["id"], "profile_hermes_news")
            self.assertEqual(payload["sources"][0]["kind"], "hermes_kanban")
            self.assertEqual(payload["sources"][0]["adapter_version"], "kyoko.hermes_kanban_import.v0")
            self.assertEqual(payload["queues"][0]["kind"], "hermes_board")
            self.assertEqual(len(payload["tasks"]), 2)
            self.assertEqual(len(payload["task_attempts"]), 1)
            self.assertEqual(len(payload["runs"]), 1)
            self.assertEqual(len(payload["spans"]), 1)
            self.assertEqual(len(payload["handoffs"]), 1)
            self.assertEqual(payload["handoffs"][0]["kind"], "queue_dependency")
            self.assertEqual(payload["handoffs"][0]["from_task_id"], "task_hermes_t_parent")
            self.assertEqual(payload["handoffs"][0]["to_task_id"], "task_hermes_t_child")
            self.assertEqual(
                {agent["name"] for agent in payload["agent_identities"]},
                {"researcher", "writer", "unknown"},
            )
            self.assertEqual(
                {event["kind"] for event in payload["timeline_events"]},
                {"created", "claimed", "completed", "commented"},
            )

    def test_ingest_hermes_kanban_db_populates_kyoko_tables(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            kanban_db = tmp_path / "kanban.db"
            kyoko_db = tmp_path / "kyoko.db"
            normalized = tmp_path / "hermes-source-events.json"
            _write_hermes_kanban_db(kanban_db)

            report = ingest_hermes_kanban_db(
                db_path=kyoko_db,
                kanban_db_path=kanban_db,
                profile_id="profile_hermes_news",
                profile_name="Hermes News",
                root_path=tmp_path,
                board="news",
                output_path=normalized,
            )
            status = get_database_status(kyoko_db)

            self.assertEqual(report.profile_id, "profile_hermes_news")
            self.assertTrue(normalized.exists())
            self.assertEqual(status.counts["profiles"], 1)
            self.assertEqual(status.counts["sources"], 1)
            self.assertEqual(status.counts["queues"], 1)
            self.assertEqual(status.counts["tasks"], 2)
            self.assertEqual(status.counts["task_attempts"], 1)
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 1)
            self.assertEqual(status.counts["handoffs"], 1)
            self.assertEqual(status.counts["timeline_events"], 4)

    def test_cli_import_hermes_kanban_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            kanban_db = tmp_path / "kanban.db"
            kyoko_db = tmp_path / "kyoko.db"
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

            self.assertEqual(code, 0)
            self.assertEqual(payload["profile_id"], "profile_cli_hermes")
            self.assertEqual(payload["counts"]["tasks"], 2)
            self.assertEqual(payload["counts"]["handoffs"], 1)
            self.assertEqual(payload["ingested_counts"]["runs"], 1)


def _write_hermes_kanban_db(path: Path) -> None:
    with sqlite3.connect(str(path)) as connection:
        connection.executescript(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT,
                assignee TEXT,
                status TEXT NOT NULL,
                priority INTEGER DEFAULT 0,
                created_by TEXT,
                created_at INTEGER NOT NULL,
                started_at INTEGER,
                completed_at INTEGER,
                workspace_kind TEXT NOT NULL DEFAULT 'scratch',
                workspace_path TEXT,
                claim_lock TEXT,
                claim_expires INTEGER,
                tenant TEXT,
                result TEXT,
                idempotency_key TEXT,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                worker_pid INTEGER,
                last_failure_error TEXT,
                max_runtime_seconds INTEGER,
                last_heartbeat_at INTEGER,
                current_run_id INTEGER,
                workflow_template_id TEXT,
                current_step_key TEXT,
                skills TEXT,
                max_retries INTEGER
            );
            CREATE TABLE task_links (
                parent_id TEXT NOT NULL,
                child_id TEXT NOT NULL,
                PRIMARY KEY (parent_id, child_id)
            );
            CREATE TABLE task_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                author TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                run_id INTEGER,
                kind TEXT NOT NULL,
                payload TEXT,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE task_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                profile TEXT,
                step_key TEXT,
                status TEXT NOT NULL,
                claim_lock TEXT,
                claim_expires INTEGER,
                worker_pid INTEGER,
                max_runtime_seconds INTEGER,
                last_heartbeat_at INTEGER,
                started_at INTEGER NOT NULL,
                ended_at INTEGER,
                outcome TEXT,
                summary TEXT,
                metadata TEXT,
                error TEXT
            );
            """
        )
        connection.execute(
            """
            INSERT INTO tasks (
                id, title, body, assignee, status, priority, created_by,
                created_at, started_at, completed_at, workspace_kind,
                workspace_path, result, current_run_id, skills
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "t_parent",
                "Research source coverage",
                "Find two source leads.",
                "researcher",
                "done",
                2,
                "writer",
                1770000000,
                1770000010,
                1770000100,
                "scratch",
                None,
                "Completed with one follow-up.",
                None,
                json.dumps(["kanban-worker"]),
            ),
        )
        connection.execute(
            """
            INSERT INTO tasks (
                id, title, body, assignee, status, priority, created_by,
                created_at, workspace_kind, workspace_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "t_child",
                "Draft article",
                "Use the research handoff.",
                "writer",
                "ready",
                1,
                "researcher",
                1770000110,
                "worktree",
                "/tmp/news-worktree",
            ),
        )
        connection.execute(
            "INSERT INTO task_links (parent_id, child_id) VALUES (?, ?)",
            ("t_parent", "t_child"),
        )
        connection.execute(
            """
            INSERT INTO task_runs (
                id, task_id, profile, status, started_at, ended_at, outcome,
                summary, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "t_parent",
                "researcher",
                "done",
                1770000010,
                1770000100,
                "completed",
                "Found source leads and created t_child.",
                json.dumps({"sources_found": 2}),
            ),
        )
        connection.executemany(
            """
            INSERT INTO task_events (task_id, run_id, kind, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "t_parent",
                    None,
                    "created",
                    json.dumps({"assignee": "researcher"}),
                    1770000000,
                ),
                (
                    "t_parent",
                    1,
                    "claimed",
                    json.dumps({"run_id": 1}),
                    1770000010,
                ),
                (
                    "t_parent",
                    1,
                    "completed",
                    json.dumps({"summary": "Found source leads", "verified_cards": ["t_child"]}),
                    1770000100,
                ),
            ],
        )
        connection.execute(
            """
            INSERT INTO task_comments (task_id, author, body, created_at)
            VALUES (?, ?, ?, ?)
            """,
            ("t_child", "researcher", "Use source A and source B.", 1770000115),
        )


if __name__ == "__main__":
    unittest.main()
