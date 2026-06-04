import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import mcp_log
from kyoko.cli import main
from kyoko.mcp import KyokoMcpServer
from kyoko.storage import ingest_source_fixture
from tests.test_web import RunningServer

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


def _seed(db_path: Path) -> None:
    ingest_source_fixture(db_path, FIXTURE)


def _drive(server: KyokoMcpServer) -> None:
    server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "claude-code", "version": "1.0"}},
        }
    )
    server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})


class McpLogServerTests(unittest.TestCase):
    def test_records_request_and_response_pairs_with_timing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=True)
            _drive(server)
            entries = mcp_log.list_mcp_log(db_path=db_path)
            directions = [(e["direction"], e["method"]) for e in entries]
            self.assertIn(("request", "initialize"), directions)
            self.assertIn(("response", "initialize"), directions)
            # Notifications have no response.
            self.assertEqual(
                [e for e in entries if e["method"] == "notifications/initialized"][0]["direction"],
                "notification",
            )
            response = [e for e in entries if e["direction"] == "response"][0]
            self.assertIsNotNone(response["duration_ms"])

    def test_captures_client_name_from_initialize(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=True)
            _drive(server)
            entries = mcp_log.list_mcp_log(db_path=db_path)
            self.assertTrue(all(e["client_id"] == "claude-code" for e in entries))

    def test_tool_call_args_are_redacted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=True)
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "kyoko_status", "arguments": {"api_key": "SECRET-XYZ"}},
                }
            )
            request = [
                e
                for e in mcp_log.list_mcp_log(db_path=db_path)
                if e["tool_name"] == "kyoko_status" and e["direction"] == "request"
            ][0]
            self.assertNotIn("SECRET-XYZ", request["params_preview"])
            self.assertIn("[REDACTED", request["params_preview"])

    def test_logging_can_be_disabled(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=False)
            _drive(server)
            self.assertEqual(mcp_log.list_mcp_log(db_path=db_path), [])

    def test_get_mcp_log_tool_is_read_only_and_present(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=True)
            tool = server.tools.get("kyoko_get_mcp_log")
            self.assertIsNotNone(tool)
            self.assertTrue(tool.read_only)
            self.assertFalse(tool.destructive)

    def test_env_flag_parsing(self) -> None:
        self.assertTrue(mcp_log.log_enabled_from_env({}))
        self.assertTrue(mcp_log.log_enabled_from_env({"KYOKO_MCP_LOG": "1"}))
        for value in ("0", "false", "no", "off"):
            self.assertFalse(mcp_log.log_enabled_from_env({"KYOKO_MCP_LOG": value}))


class McpLogCliTests(unittest.TestCase):
    def test_mcp_log_cli_outputs_recorded_entries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=True)
            _drive(server)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["mcp-log", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)
            events = json.loads(buffer.getvalue())["events"]
            self.assertTrue(any(e["method"] == "initialize" for e in events))

    def test_mcp_log_cli_empty_text(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = main(["mcp-log", "--db", str(db_path)])
            self.assertEqual(code, 0)
            self.assertIn("(no mcp log entries)", buffer.getvalue())


class McpLogWebTests(unittest.TestCase):
    def test_api_mcp_log_returns_entries(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, log_enabled=True)
            _drive(server)
            with RunningServer(db_path) as web:
                listed = web.get_json("/api/mcp-log?tool_name=&limit=50")
                self.assertTrue(any(e["method"] == "initialize" for e in listed["events"]))


if __name__ == "__main__":
    unittest.main()
