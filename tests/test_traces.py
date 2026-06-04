"""Tests for the Langfuse-style trace view enrichments: model params, token/latency/cost
aggregation, per-span/per-trace scores, and trace-level payload."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import storage
from kyoko.blobs import put_json_blob
from kyoko.details import list_runs
from kyoko.inspection import get_run_outline, get_run_payload, get_run_scores
from kyoko.otlp import ingest_otlp_json
from kyoko.pricing import estimate_cost
from kyoko.span_normalize import normalize_span
from tests.test_web import RunningServer

ROOT = Path(__file__).resolve().parents[1]
OTLP = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"


def _seed_llm_run(db_path: Path) -> tuple[str, str, str]:
    """Seed an OTLP run, then make span[0] a gpt-4o LLM span with tokens + params.

    Returns (profile_id, run_id, llm_span_id)."""
    report = ingest_otlp_json(db_path=db_path, payload_path=OTLP, profile_id="p1")
    run_id = report.run_ids[0]
    llm_span_id = report.span_ids[0]
    attributes = {
        "gen_ai.request.model": "gpt-4o",
        "gen_ai.request.temperature": 0.7,
        "gen_ai.request.top_p": 0.95,
        "gen_ai.request.max_tokens": 1024,
        "gen_ai.response.finish_reasons": "stop",
        "gen_ai.operation.name": "chat",
    }
    con = storage.connect(db_path)
    profile_id = con.execute("SELECT profile_id FROM runs WHERE id=?", (run_id,)).fetchone()["profile_id"]
    con.execute(
        "UPDATE spans SET kind='llm', usage_json=?, attributes_json=? WHERE id=?",
        (json.dumps({"input_tokens": 1000, "output_tokens": 500}), json.dumps(attributes), llm_span_id),
    )
    con.execute(
        "UPDATE runs SET started_at='2026-06-04T10:00:00Z', ended_at='2026-06-04T10:00:02Z' WHERE id=?",
        (run_id,),
    )
    con.commit()
    con.close()
    return profile_id, run_id, llm_span_id


def _seed_score(db_path: Path, profile_id: str, run_id: str, span_id: str) -> None:
    """Insert one eval definition + run + two results (one trace-level, one span-level)."""
    con = storage.connect(db_path)
    now = "2026-06-04T10:05:00Z"
    con.execute(
        "INSERT INTO eval_definitions (id, profile_id, kind, name, version, source, unit_type, "
        "output_type, direction, status, created_at, updated_at) VALUES "
        "('def1', ?, 'llm', 'relevance', 1, 'bundled', 'llm_span', 'numeric', "
        "'higher_is_better', 'active', ?, ?)",
        (profile_id, now, now),
    )
    con.execute(
        "INSERT INTO eval_measure_runs (id, profile_id, eval_definition_id, kind, "
        "definition_snapshot_json, corpus_json, unit_type, status, created_at, updated_at) VALUES "
        "('mr1', ?, 'def1', 'llm', '{}', '{}', 'llm_span', 'complete', ?, ?)",
        (profile_id, now, now),
    )
    con.execute(
        "INSERT INTO eval_measure_results (id, eval_run_id, profile_id, unit_type, unit_ref, "
        "status, score_numeric, score_bool, reasoning, detail_json, created_at) VALUES "
        "('res_span', 'mr1', ?, 'llm_span', ?, 'scored', 0.9, NULL, 'looks relevant', '{}', ?)",
        (profile_id, span_id, now),
    )
    con.execute(
        "INSERT INTO eval_measure_results (id, eval_run_id, profile_id, unit_type, unit_ref, "
        "status, score_numeric, score_bool, reasoning, detail_json, created_at) VALUES "
        "('res_run', 'mr1', ?, 'run', ?, 'scored', NULL, 1, 'trace ok', '{}', ?)",
        (profile_id, run_id, now),
    )
    con.commit()
    con.close()


class SpanNormalizeParamTests(unittest.TestCase):
    def test_extracts_model_params_from_gen_ai_attributes(self) -> None:
        normalized = normalize_span(
            name="chat",
            kind="llm",
            attributes={
                "gen_ai.request.model": "gpt-4o",
                "gen_ai.request.temperature": 0.5,
                "gen_ai.request.top_p": 0.9,
                "gen_ai.request.max_tokens": 256,
                "gen_ai.response.finish_reasons": "stop",
                "gen_ai.usage.input_tokens": 12,
                "gen_ai.usage.output_tokens": 7,
                "gen_ai.operation.name": "chat",
            },
        )
        self.assertEqual(normalized["kind"], "llm")
        self.assertEqual(normalized["params"]["temperature"], 0.5)
        self.assertEqual(normalized["params"]["top_p"], 0.9)
        self.assertEqual(normalized["params"]["max_tokens"], 256)
        self.assertEqual(normalized["params"]["finish_reasons"], "stop")
        self.assertEqual(normalized["input_tokens"], 12)
        self.assertEqual(normalized["output_tokens"], 7)

    def test_params_none_when_absent(self) -> None:
        normalized = normalize_span(
            name="chat", kind="llm", attributes={"gen_ai.request.model": "gpt-4o", "gen_ai.operation.name": "chat"}
        )
        self.assertIsNone(normalized["params"])


class PricingTests(unittest.TestCase):
    def test_known_model_cost(self) -> None:
        # 1000 in * 2.50/1M + 500 out * 10.00/1M = 0.0025 + 0.005 = 0.0075
        self.assertAlmostEqual(estimate_cost("gpt-4o", 1000, 500), 0.0075, places=6)

    def test_longest_prefix_wins(self) -> None:
        # gpt-4o-mini must not match the more general gpt-4o entry.
        self.assertAlmostEqual(estimate_cost("gpt-4o-mini-2024", 1000, 0), 0.00015, places=6)

    def test_unknown_model_is_none(self) -> None:
        self.assertIsNone(estimate_cost("totally-unknown-model", 100, 100))
        self.assertIsNone(estimate_cost(None, 100, 100))


class TraceMetricsTests(unittest.TestCase):
    def test_list_runs_aggregates_tokens_duration_cost(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, run_id, _ = _seed_llm_run(db_path)
            summary = next(r for r in list_runs(db_path=db_path) if r["id"] == run_id)
            self.assertEqual(summary["input_tokens"], 1000)
            self.assertEqual(summary["output_tokens"], 500)
            self.assertEqual(summary["total_tokens"], 1500)
            self.assertEqual(summary["llm_span_count"], 1)
            self.assertAlmostEqual(summary["cost_usd"], 0.0075, places=6)
            self.assertEqual(summary["duration_ms"], 2000.0)

    def test_run_outline_metrics_and_span_duration(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, run_id, llm_span_id = _seed_llm_run(db_path)
            outline = get_run_outline(db_path=db_path, run_id=run_id)
            metrics = outline["metrics"]
            self.assertEqual(metrics["total_tokens"], 1500)
            self.assertEqual(metrics["llm_spans"], 1)
            self.assertAlmostEqual(metrics["cost_usd"], 0.0075, places=6)
            self.assertEqual(metrics["total_duration_ms"], 2000.0)
            llm = _find_span(outline["span_tree"], llm_span_id)
            self.assertIsNotNone(llm["duration_ms"])
            self.assertEqual(llm["normalized"]["params"]["temperature"], 0.7)


class RunScoresTests(unittest.TestCase):
    def test_groups_trace_and_span_scores(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id, run_id, span_id = _seed_llm_run(db_path)
            _seed_score(db_path, profile_id, run_id, span_id)
            scores = get_run_scores(db_path=db_path, run_id=run_id)
            self.assertEqual(len(scores["trace"]), 1)
            self.assertEqual(scores["trace"][0]["score_bool"], True)
            self.assertEqual(scores["trace"][0]["name"], "relevance")
            self.assertEqual(len(scores["by_span"][span_id]), 1)
            self.assertAlmostEqual(scores["by_span"][span_id][0]["score_numeric"], 0.9)

    def test_empty_when_no_scores(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, run_id, _ = _seed_llm_run(db_path)
            scores = get_run_scores(db_path=db_path, run_id=run_id)
            self.assertEqual(scores, {"trace": [], "by_span": {}})


class RunPayloadTests(unittest.TestCase):
    def test_trace_payload_is_redacted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id, run_id, _ = _seed_llm_run(db_path)
            blob = put_json_blob(
                db_path=db_path,
                payload={"prompt": "hello", "api_key": "SUPERSECRET"},
                profile_id=profile_id,
                redaction_mode="redacted",
            )
            con = storage.connect(db_path)
            con.execute("UPDATE runs SET input_ref=? WHERE id=?", (blob.blob_id, run_id))
            con.commit()
            con.close()
            payload = get_run_payload(db_path=db_path, run_id=run_id, target="input")
            self.assertTrue(payload["available"])
            self.assertNotIn("SUPERSECRET", payload["content"])

    def test_unavailable_when_no_ref(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, run_id, _ = _seed_llm_run(db_path)
            payload = get_run_payload(db_path=db_path, run_id=run_id, target="output")
            self.assertFalse(payload["available"])


class TraceApiTests(unittest.TestCase):
    def test_run_scores_and_payload_endpoints(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id, run_id, span_id = _seed_llm_run(db_path)
            _seed_score(db_path, profile_id, run_id, span_id)
            with RunningServer(db_path) as server:
                scores = server.get_json(f"/api/run-scores?run_id={run_id}")
                runs = server.get_json("/api/runs")["runs"]
            self.assertEqual(len(scores["trace"]), 1)
            self.assertIn(span_id, scores["by_span"])
            summary = next(r for r in runs if r["id"] == run_id)
            self.assertEqual(summary["total_tokens"], 1500)


def _find_span(tree: list, span_id: str) -> dict:
    for node in tree:
        if node["id"] == span_id:
            return node
        found = _find_span(node.get("children", []), span_id)
        if found is not None:
            return found
    return None


if __name__ == "__main__":
    unittest.main()
