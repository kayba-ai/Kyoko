"""API + MCP parity for the `eval` (Python detector) measurement plane."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from kyoko import storage
from kyoko.mcp import KyokoMcpServer
from tests.test_mcp import SCHEMA, _call_tool
from tests.test_web import RunningServer


def _seed(db_path: Path) -> None:
    storage.initialize_database(db_path)
    con = storage.connect(db_path)
    con.execute(
        "INSERT INTO profiles VALUES ('p1','p1','/tmp','active','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )
    con.execute(
        "INSERT INTO sources (id,profile_id,kind,display_name,status,adapter_version,config_json,capabilities_json) "
        "VALUES ('s1','p1','t','s','active','1','{}','{}')"
    )
    con.execute(
        "INSERT INTO runs (id,profile_id,source_id,status,started_at,metadata_json) "
        "VALUES ('run_0','p1','s1','succeeded','2026-01-01T00:00:00Z','{}')"
    )
    con.execute(
        "INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) "
        "VALUES ('run_0_ok','run_0','s1','tool','a','ok','2026-01-01T00:00:01Z','{}','{}')"
    )
    con.execute(
        "INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) "
        "VALUES ('run_0_bad','run_0','s1','tool','b','failed','2026-01-01T00:00:02Z','{}','{}')"
    )
    con.commit()
    con.close()


class EvalPlaneApiTests(unittest.TestCase):
    def test_api_eval_plane_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            with RunningServer(db_path) as server:
                detectors = server.get_json("/api/evals")["detectors"]
                self.assertIn("failed_span", {d["id"] for d in detectors})

                detail = server.get_json("/api/evals/detail?id=failed_span")["detector"]
                self.assertEqual(detail["id"], "failed_span")

                run = server.post_json(
                    "/api/run-eval",
                    {"detector_id": "failed_span", "corpus": {"unit": "event"}, "persist": True},
                )
                self.assertEqual(run["aggregate"]["denominator"], 2)
                self.assertEqual(run["aggregate"]["numerator"], 1)
                eval_run_id = run["eval_run_id"]

                runs = server.get_json("/api/eval-runs")["eval_runs"]
                self.assertEqual([r["id"] for r in runs], [eval_run_id])

                run_detail = server.get_json(f"/api/eval-runs/detail?id={quote(eval_run_id)}")
                self.assertEqual(run_detail["eval_run"]["id"], eval_run_id)
                self.assertEqual(len(run_detail["results"]), 2)

    def test_mcp_eval_plane_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            tools = server.handle_message(
                {"jsonrpc": "2.0", "id": "t", "method": "tools/list", "params": {}}
            )["result"]["tools"]
            by_name = {t["name"]: t for t in tools}
            self.assertIn("kyoko_list_evals", by_name)
            self.assertIn("kyoko_eval_run_detail", by_name)
            self.assertIn("kyoko_run_eval", by_name)
            self.assertTrue(by_name["kyoko_list_evals"]["annotations"]["readOnlyHint"])
            self.assertFalse(by_name["kyoko_run_eval"]["annotations"]["readOnlyHint"])

            listed = _call_tool(server, "kyoko_list_evals", {})["structuredContent"]
            self.assertIn("failed_span", {d["id"] for d in listed["detectors"]})

            run = _call_tool(
                server,
                "kyoko_run_eval",
                {"detector_id": "failed_span", "corpus": {"unit": "event"}, "persist": True},
            )["structuredContent"]
            self.assertEqual(run["aggregate"]["denominator"], 2)
            eval_run_id = run["eval_run_id"]

            detail = _call_tool(server, "kyoko_eval_run_detail", {"eval_run_id": eval_run_id})[
                "structuredContent"
            ]
            self.assertEqual(detail["eval_run"]["id"], eval_run_id)
            self.assertEqual(len(detail["results"]), 2)

            # boundary: no apply/gate tool exposed by this plane
            safety = _call_tool(server, "kyoko_mcp_safety_contract", {})["structuredContent"]
            self.assertTrue(safety["passed"])


if __name__ == "__main__":
    unittest.main()
