"""API + MCP parity for the `eval` (Python detector) + `llm_eval` planes."""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote

from kyoko import storage
from kyoko.mcp import KyokoMcpServer
from tests.test_mcp import SCHEMA, _call_tool
from tests.test_web import RunningServer

ROOT = Path(__file__).resolve().parents[1]
LLM_JUDGE = [sys.executable, str(ROOT / "tests/fixtures/llm_eval_judge.py")]


def _seed_llm(db_path: Path) -> None:
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
        "VALUES ('run_0_llm','run_0','s1','llm','gen','ok','2026-01-01T00:00:01Z','{}',?)",
        (json.dumps({"gen_ai.prompt.0.role": "user", "gen_ai.prompt.0.content": "What is the capital?",
                     "gen_ai.completion.0.content": "The capital is Paris."}),),
    )
    con.commit()
    con.close()


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

    def test_api_compare_and_raise_issues(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)  # 2 spans, 1 failed -> problem 0.5
            with RunningServer(db_path) as server:
                # raise-issues pass-through on the run POST
                run = server.post_json(
                    "/api/run-eval",
                    {"detector_id": "failed_span", "corpus": {"unit": "event"},
                     "persist": True, "raise_issues": True, "threshold": 0.3},
                )
                self.assertIsNotNone(run["raised_issue_id"])
                base = run["eval_run_id"]
                # a second (identical) run, then compare
                run2 = server.post_json(
                    "/api/run-eval",
                    {"detector_id": "failed_span", "corpus": {"unit": "event"}, "persist": True},
                )
                comp = server.get_json(
                    f"/api/eval-compare?baseline={quote(base)}&compare={quote(run2['eval_run_id'])}"
                )
                self.assertEqual(comp["direction"], "unchanged")
                self.assertEqual(comp["eval_id"], "failed_span")

    def test_mcp_compare(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)
            tools = {t["name"] for t in server.handle_message(
                {"jsonrpc": "2.0", "id": "t", "method": "tools/list", "params": {}}
            )["result"]["tools"]}
            self.assertIn("kyoko_eval_compare", tools)
            self.assertIn("kyoko_llm_eval_compare", tools)
            a = _call_tool(server, "kyoko_run_eval",
                           {"detector_id": "failed_span", "corpus": {"unit": "event"}, "persist": True})["structuredContent"]
            b = _call_tool(server, "kyoko_run_eval",
                           {"detector_id": "failed_span", "corpus": {"unit": "event"}, "persist": True})["structuredContent"]
            comp = _call_tool(server, "kyoko_eval_compare",
                              {"baseline_run_id": a["eval_run_id"], "compare_run_id": b["eval_run_id"]})["structuredContent"]
            self.assertEqual(comp["direction"], "unchanged")


class LlmEvalPlaneApiTests(unittest.TestCase):
    def test_api_llm_eval_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_llm(db_path)
            with RunningServer(db_path) as server:
                templates = server.get_json("/api/llm-evals")["llm_evals"]
                self.assertEqual(len(templates), 10)

                detail = server.get_json("/api/llm-evals/detail?id=hallucination")["llm_eval"]
                self.assertEqual(detail["id"], "hallucination")

                run = server.post_json(
                    "/api/run-llm-eval",
                    {"llm_eval_id": "hallucination", "corpus": {"unit": "llm_span"},
                     "command": LLM_JUDGE, "persist": True},
                )
                self.assertAlmostEqual(run["aggregate"]["value"], 0.3)
                eval_run_id = run["eval_run_id"]

                runs = server.get_json("/api/llm-eval-runs")["eval_runs"]
                self.assertEqual([r["id"] for r in runs], [eval_run_id])

                run_detail = server.get_json(f"/api/llm-eval-runs/detail?id={quote(eval_run_id)}")
                self.assertEqual(run_detail["eval_run"]["id"], eval_run_id)
                self.assertEqual(len(run_detail["results"]), 1)

    def test_mcp_llm_eval_flow(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_llm(db_path)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)
            tools = server.handle_message(
                {"jsonrpc": "2.0", "id": "t", "method": "tools/list", "params": {}}
            )["result"]["tools"]
            by_name = {t["name"]: t for t in tools}
            self.assertIn("kyoko_list_llm_evals", by_name)
            self.assertIn("kyoko_llm_eval_run_detail", by_name)
            self.assertIn("kyoko_run_llm_eval", by_name)
            self.assertFalse(by_name["kyoko_run_llm_eval"]["annotations"]["readOnlyHint"])

            listed = _call_tool(server, "kyoko_list_llm_evals", {})["structuredContent"]
            self.assertEqual(len(listed["llm_evals"]), 10)

            run = _call_tool(
                server, "kyoko_run_llm_eval",
                {"llm_eval_id": "hallucination", "corpus": {"unit": "llm_span"},
                 "command": LLM_JUDGE, "persist": True},
            )["structuredContent"]
            eval_run_id = run["eval_run_id"]
            detail = _call_tool(server, "kyoko_llm_eval_run_detail", {"eval_run_id": eval_run_id})[
                "structuredContent"
            ]
            self.assertEqual(detail["eval_run"]["id"], eval_run_id)
            self.assertEqual(len(detail["results"]), 1)

            safety = _call_tool(server, "kyoko_mcp_safety_contract", {})["structuredContent"]
            self.assertTrue(safety["passed"])


if __name__ == "__main__":
    unittest.main()
