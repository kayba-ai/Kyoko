import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.cli import main
from kyoko.source_discovery import discover_local_sources, import_discovered_source
from kyoko.storage import get_database_status
from tests.test_hermes_import import _write_hermes_kanban_db
from tests.test_openclaw_import import _write_openclaw_sessions


class SourceDiscoveryTests(unittest.TestCase):
    def test_discover_local_sources_returns_import_commands(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home = tmp_path / "home"
            _write_hermes_paths(home)
            _write_openclaw_sessions(home)
            db_path = tmp_path / "kyoko.db"
            root_path = tmp_path / "agent workspace"

            report = discover_local_sources(
                db_path=db_path,
                home=home,
                profile_id="profile_news",
                profile_name="News Research",
                root_path=root_path,
            )
            payload = report.to_json()
            by_id = {candidate["id"]: candidate for candidate in payload["candidates"]}

            self.assertEqual(payload["home"], str(home.resolve()))
            self.assertEqual(set(by_id), {"hermes_default", "hermes_news", "openclaw_main"})
            self.assertEqual(by_id["hermes_news"]["metadata"]["board"], "news")
            self.assertEqual(by_id["openclaw_main"]["metadata"]["session_count"], 1)
            self.assertEqual(by_id["openclaw_main"]["metadata"]["transcript_count"], 1)
            self.assertIn("import-hermes-kanban", by_id["hermes_default"]["import_command"])
            self.assertIn("import-openclaw-sessions", by_id["openclaw_main"]["import_command"])
            self.assertIn("--profile-id profile_news", by_id["openclaw_main"]["import_command"])
            self.assertIn("--profile-name 'News Research'", by_id["hermes_news"]["import_command"])
            self.assertIn("--root-path", by_id["openclaw_main"]["import_command"])

    def test_discover_local_sources_can_include_missing_defaults(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home = tmp_path / "empty-home"

            report = discover_local_sources(
                db_path=tmp_path / "kyoko.db",
                home=home,
                include_missing=True,
            )
            by_id = {candidate["id"]: candidate for candidate in report.to_json()["candidates"]}

            self.assertEqual(by_id["hermes_default"]["status"], "missing")
            self.assertEqual(by_id["openclaw_main"]["status"], "missing")

    def test_cli_discover_sources_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home = tmp_path / "home"
            _write_openclaw_sessions(home)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "discover-sources",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--home",
                        str(home),
                        "--profile-id",
                        "profile_cli",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(len(payload["candidates"]), 1)
            self.assertEqual(payload["candidates"][0]["kind"], "openclaw_sessions")
            self.assertIn("--profile-id profile_cli", payload["candidates"][0]["import_command"])

    def test_import_discovered_openclaw_source(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home = tmp_path / "home"
            _write_openclaw_sessions(home)
            db_path = tmp_path / "kyoko.db"
            output_dir = tmp_path / "normalized"

            report = import_discovered_source(
                db_path=db_path,
                candidate_id="openclaw_main",
                home=home,
                profile_id="profile_openclaw_discovered",
                output_dir=output_dir,
            )
            status = get_database_status(db_path)
            payload = report.to_json()

            self.assertEqual(payload["candidate"]["id"], "openclaw_main")
            self.assertEqual(payload["import"]["profile_id"], "profile_openclaw_discovered")
            self.assertEqual(payload["import"]["counts"]["tasks"], 1)
            self.assertTrue(Path(payload["import"]["normalized_path"]).exists())
            self.assertEqual(status.counts["runs"], 1)

    def test_cli_import_discovered_hermes_source_json(self) -> None:
        with TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            home = tmp_path / "home"
            kanban_db = home / ".hermes" / "kanban.db"
            kanban_db.parent.mkdir(parents=True)
            _write_hermes_kanban_db(kanban_db)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "import-discovered-source",
                        "--db",
                        str(tmp_path / "kyoko.db"),
                        "--home",
                        str(home),
                        "--profile-id",
                        "profile_hermes_discovered",
                        "--output-dir",
                        str(tmp_path / "normalized"),
                        "hermes_default",
                        "--json",
                    ]
                )
            payload = json.loads(stdout.getvalue())

            self.assertEqual(code, 0)
            self.assertEqual(payload["candidate"]["id"], "hermes_default")
            self.assertEqual(payload["import"]["profile_id"], "profile_hermes_discovered")
            self.assertEqual(payload["import"]["counts"]["tasks"], 2)
            self.assertTrue(Path(payload["import"]["normalized_path"]).exists())


def _write_hermes_paths(home: Path) -> None:
    default_db = home / ".hermes" / "kanban.db"
    default_db.parent.mkdir(parents=True)
    default_db.write_bytes(b"not a real sqlite db")
    board_db = home / ".hermes" / "kanban" / "boards" / "news" / "kanban.db"
    board_db.parent.mkdir(parents=True)
    board_db.write_bytes(b"not a real sqlite db")
