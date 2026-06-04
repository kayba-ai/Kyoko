import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import inspection
from kyoko.otlp import ingest_otlp_json
from kyoko.subagents import detect_subagents

ROOT = Path(__file__).resolve().parents[1]
OTLP = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"


class SubagentTests(unittest.TestCase):
    def test_agent_with_llm_and_tool_descendants(self) -> None:
        agent = {
            "id": "A",
            "kind": "agent",
            "attributes": {
                "gen_ai.agent.name": "researcher",
                "gen_ai.request.model": "gpt-x",
            },
            "started_at": "2026-01-01T00:00:00Z",
        }
        llm = {"id": "B", "parent_span_id": "A", "kind": "llm", "attributes": {}}
        tool = {"id": "C", "parent_span_id": "B", "kind": "tool", "attributes": {}}

        detected = detect_subagents([agent, llm, tool])
        self.assertEqual(len(detected), 1)
        entry = detected[0]
        self.assertEqual(entry["root_span_id"], "A")
        self.assertEqual(entry["llm_count"], 1)
        self.assertEqual(entry["tool_count"], 1)
        self.assertEqual(entry["model"], "gpt-x")
        self.assertTrue({"A", "B", "C"}.issubset(set(entry["span_ids"])))

    def test_all_other_tree_yields_nothing(self) -> None:
        spans = [
            {"id": "A", "kind": "other", "attributes": {}},
            {"id": "B", "parent_span_id": "A", "kind": "other", "attributes": {}},
            {"id": "C", "parent_span_id": "B", "kind": "other", "attributes": {}},
        ]
        self.assertEqual(detect_subagents(spans), [])

    def test_nested_agents_report_only_outermost(self) -> None:
        outer = {
            "id": "A",
            "kind": "agent",
            "attributes": {"gen_ai.agent.name": "outer"},
            "started_at": "2026-01-01T00:00:00Z",
        }
        inner = {
            "id": "B",
            "parent_span_id": "A",
            "kind": "agent",
            "attributes": {"gen_ai.agent.name": "inner"},
            "started_at": "2026-01-01T00:00:01Z",
        }
        leaf = {"id": "C", "parent_span_id": "B", "kind": "llm", "attributes": {}}

        detected = detect_subagents([outer, inner, leaf])
        self.assertEqual(len(detected), 1)
        self.assertEqual(detected[0]["root_span_id"], "A")


class SubagentInspectionTests(unittest.TestCase):
    def test_run_outline_surfaces_subagents(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            report = ingest_otlp_json(
                db_path=db_path, payload_path=OTLP, profile_id="p1"
            )
            outline = inspection.get_run_outline(
                db_path=db_path, run_id=report.run_ids[0]
            )
            self.assertEqual(outline["summary"]["subagents"], 1)
            self.assertIn(
                outline["span_tree"][0]["normalized"]["kind"],
                {"llm", "tool", "other"},
            )


if __name__ == "__main__":
    unittest.main()
