import io
import json
import re
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import inspection, storage
from kyoko.blobs import put_json_blob
from kyoko.cli import main
from kyoko.inspection import InspectionError
from kyoko.otlp import ingest_otlp_json
from tests.test_web import RunningServer

ROOT = Path(__file__).resolve().parents[1]
OTLP = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"
HERMES = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


def _seed_otlp(db_path: Path) -> tuple[str, list[str]]:
    """Seed an OTLP run (2 spans: agent succeeded, tool failed) under profile 'p1'."""
    report = ingest_otlp_json(db_path=db_path, payload_path=OTLP, profile_id="p1")
    return report.run_ids[0], list(report.span_ids)


def _seed_with_payload(db_path: Path) -> tuple[str, str, str]:
    """Seed a run with one span carrying a redacted input payload blob.

    Returns (profile_id, run_id, span_id).
    """
    storage.ingest_source_fixture(db_path, HERMES)
    con = storage.connect(db_path)
    profile_id = con.execute("SELECT id FROM profiles LIMIT 1").fetchone()[0]
    run_id = con.execute("SELECT id FROM runs LIMIT 1").fetchone()[0]
    span_id = con.execute(
        "SELECT id FROM spans WHERE run_id=? LIMIT 1", (run_id,)
    ).fetchone()[0]
    con.close()
    blob = put_json_blob(
        db_path=db_path,
        payload={
            "messages": [{"role": "user", "content": "hello"}],
            "api_key": "SUPERSECRET",
        },
        profile_id=profile_id,
        redaction_mode="redacted",
    )
    con = storage.connect(db_path)
    con.execute("UPDATE spans SET input_ref=? WHERE id=?", (blob.blob_id, span_id))
    con.commit()
    con.close()
    return profile_id, run_id, span_id


class InspectionModuleTests(unittest.TestCase):
    def test_get_current_run_returns_seeded_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            run = inspection.get_current_run(db_path=db_path)
            self.assertIsNotNone(run)
            self.assertEqual(run["id"], run_id)
            self.assertEqual(run["span_count"], 2)

    def test_get_current_run_none_when_empty(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            self.assertIsNone(inspection.get_current_run(db_path=db_path))

    def test_run_outline_summary_counts_and_nested_tree(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            outline = inspection.get_run_outline(db_path=db_path, run_id=run_id)
            self.assertEqual(outline["summary"]["spans"], 2)
            self.assertEqual(outline["summary"]["failed_spans"], 1)
            # The span tree is nested: a single root with at least one child.
            self.assertEqual(len(outline["span_tree"]), 1)
            self.assertTrue(outline["span_tree"][0]["children"])

    def test_run_outline_unknown_run_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_otlp(db_path)
            with self.assertRaises(InspectionError):
                inspection.get_run_outline(db_path=db_path, run_id="does_not_exist")

    def test_search_run_finds_attribute_match(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            result = inspection.search_run(db_path=db_path, run_id=run_id, pattern="gen_ai")
            self.assertGreater(result["match_count"], 0)
            self.assertEqual(result["match_count"], len(result["matches"]))
            self.assertIn("gen_ai", result["matches"][0]["snippet"])

    def test_search_run_empty_pattern_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            with self.assertRaises(InspectionError):
                inspection.search_run(db_path=db_path, run_id=run_id, pattern="")

    def test_search_run_invalid_regex_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            with self.assertRaises(InspectionError):
                inspection.search_run(
                    db_path=db_path, run_id=run_id, pattern="(unclosed", regex=True
                )

    def test_search_run_fts_finds_name_attribute_and_payload(self) -> None:
        """FTS-backed search reaches span names, attributes, and payload previews."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, run_id, span_id = _seed_with_payload(db_path)
            # Attach a blob whose (unredacted) preview carries a unique token, then
            # re-index the span the way the ingest write-through would. In production
            # every payload-ref is set during ingest and indexed there.
            blob = put_json_blob(
                db_path=db_path,
                payload={"note": "uniquetoken supercalifragilistic"},
                profile_id=storage.connect(db_path)
                .execute("SELECT profile_id FROM runs WHERE id = ?", (run_id,))
                .fetchone()[0],
                redaction_mode="unredacted",
            )
            con = storage.connect(db_path)
            con.execute(
                "UPDATE spans SET output_ref = ? WHERE id = ?", (blob.blob_id, span_id)
            )
            con.commit()
            storage.index_span_fts(con, span_id)
            con.commit()
            con.close()
            # Payload preview (output_ref) is reachable via FTS.
            payload_hit = inspection.search_run(
                db_path=db_path, run_id=run_id, pattern="uniquetoken"
            )
            self.assertGreater(payload_hit["match_count"], 0)
            self.assertTrue(
                any(m.get("kind") == "span_output" for m in payload_hit["matches"])
            )
            # The span name is reachable via FTS too.
            name = (
                storage.connect(db_path)
                .execute("SELECT name FROM spans WHERE id = ?", (span_id,))
                .fetchone()["name"]
            )
            token = str(name).split()[0]
            name_hit = inspection.search_run(
                db_path=db_path, run_id=run_id, pattern=token, scope=["name"]
            )
            self.assertGreater(name_hit["match_count"], 0)
            self.assertTrue(
                all(m.get("kind") == "span_name" for m in name_hit["matches"])
            )

    def test_search_run_regex_still_works(self) -> None:
        """regex=True bypasses FTS and uses the precise regex path."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            result = inspection.search_run(
                db_path=db_path, run_id=run_id, pattern=r"gen_ai\.\w+", regex=True
            )
            self.assertGreater(result["match_count"], 0)
            self.assertTrue(result["matches"][0]["match"].startswith("gen_ai."))

    def test_search_run_scope_filtering(self) -> None:
        """Scope filtering still restricts which kinds of targets are searched."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            attrs_only = inspection.search_run(
                db_path=db_path, run_id=run_id, pattern="gen_ai", scope=["attributes"]
            )
            self.assertGreater(attrs_only["match_count"], 0)
            self.assertTrue(
                all(m["kind"] == "span_attributes" for m in attrs_only["matches"])
            )
            # "gen_ai" lives in attributes, not in span names → name scope finds none.
            name_only = inspection.search_run(
                db_path=db_path, run_id=run_id, pattern="gen_ai", scope=["name"]
            )
            self.assertEqual(name_only["match_count"], 0)

    def test_search_run_mid_token_substring_parity(self) -> None:
        """FTS pre-filter must not miss mid-token substring matches (vs linear scan)."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            for pat in ("en_a", "del", "gen_ai", "model"):
                fts = inspection.search_run(db_path=db_path, run_id=run_id, pattern=pat)
                # regex=True forces the precise linear path with no FTS pre-filter.
                linear = inspection.search_run(
                    db_path=db_path, run_id=run_id, pattern=re.escape(pat), regex=True
                )
                self.assertEqual(
                    fts["match_count"], linear["match_count"], f"mismatch for {pat!r}"
                )

    def test_search_run_coexisting_token_and_mid_token_spans(self) -> None:
        """A pattern at a token boundary in one span and mid-token in another → both."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            fixture = {
                "profile": {
                    "id": "p1",
                    "name": "n",
                    "root_path": "/tmp",
                    "status": "active",
                    "created_at": "2020-01-01T00:00:00Z",
                    "updated_at": "2020-01-01T00:00:00Z",
                },
                "sources": [
                    {
                        "id": "s1",
                        "profile_id": "p1",
                        "kind": "otlp",
                        "display_name": "d",
                        "status": "active",
                        "adapter_version": "1",
                        "config_json": "{}",
                        "capabilities_json": "{}",
                        "last_seen_at": None,
                    }
                ],
                "agent_identities": [],
                "workflow_nodes": [],
                "queues": [],
                "tasks": [],
                "task_attempts": [],
                "runs": [
                    {
                        "id": "r1",
                        "profile_id": "p1",
                        "source_id": "s1",
                        "external_id": None,
                        "root_span_id": None,
                        "agent_identity_id": None,
                        "task_attempt_id": None,
                        "status": "completed",
                        "started_at": "2020-01-01T00:00:00Z",
                        "ended_at": None,
                        "input_ref": None,
                        "output_ref": None,
                        "summary": None,
                        "metadata_json": "{}",
                    }
                ],
                "spans": [
                    {
                        "id": "sp1",
                        "run_id": "r1",
                        "source_id": "s1",
                        "external_id": None,
                        "parent_span_id": None,
                        "workflow_node_id": None,
                        "agent_identity_id": None,
                        "kind": "llm",
                        "name": "alpha",
                        "status": "ok",
                        "started_at": "2020-01-01T00:00:01Z",
                        "ended_at": None,
                        "input_ref": None,
                        "output_ref": None,
                        "usage_json": "{}",
                        "attributes_json": json.dumps({"model": "gpt"}),
                        "raw_ref": None,
                    },
                    {
                        "id": "sp2",
                        "run_id": "r1",
                        "source_id": "s1",
                        "external_id": None,
                        "parent_span_id": None,
                        "workflow_node_id": None,
                        "agent_identity_id": None,
                        "kind": "llm",
                        "name": "beta",
                        "status": "ok",
                        "started_at": "2020-01-01T00:00:02Z",
                        "ended_at": None,
                        "input_ref": None,
                        "output_ref": None,
                        "usage_json": "{}",
                        "attributes_json": json.dumps({"xsubmodelx": "y"}),
                        "raw_ref": None,
                    },
                ],
                "handoffs": [],
                "timeline_events": [],
            }
            storage.ingest_source_payload(
                db_path=db_path, fixture=fixture, source_label="t"
            )
            result = inspection.search_run(db_path=db_path, run_id="r1", pattern="model")
            span_ids = {m.get("span_id") for m in result["matches"]}
            # sp1 has the bare token "model"; sp2 only has it inside "submodel".
            self.assertEqual(span_ids, {"sp1", "sp2"})

    def test_search_run_backfills_preexisting_spans(self) -> None:
        """Spans ingested before the FTS index existed are searchable after backfill."""
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            # Simulate a pre-v24 DB: drop the FTS index and re-initialize so
            # initialize_database recreates it and backfills from existing spans.
            con = storage.connect(db_path)
            con.execute("DROP TABLE IF EXISTS spans_fts")
            con.commit()
            self.assertFalse(storage.spans_fts_ready(con))
            con.close()
            storage.initialize_database(db_path)
            con = storage.connect(db_path)
            self.assertTrue(storage.spans_fts_ready(con))
            self.assertGreater(con.execute("SELECT COUNT(*) FROM spans_fts").fetchone()[0], 0)
            con.close()
            result = inspection.search_run(
                db_path=db_path, run_id=run_id, pattern="gen_ai"
            )
            self.assertGreater(result["match_count"], 0)

    def test_get_span_context_window_includes_target(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, span_ids = _seed_otlp(db_path)
            target_id = span_ids[0]
            context = inspection.get_span_context(db_path=db_path, span_id=target_id)
            self.assertEqual(context["target"]["id"], target_id)
            self.assertIn(target_id, [span["id"] for span in context["context"]])

    def test_get_span_context_unknown_span_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed_otlp(db_path)
            with self.assertRaises(InspectionError):
                inspection.get_span_context(db_path=db_path, span_id="nope")

    def test_get_span_payload_unavailable_without_ref(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, span_ids = _seed_otlp(db_path)
            payload = inspection.get_span_payload(db_path=db_path, span_id=span_ids[0])
            self.assertFalse(payload["available"])

    def test_get_span_payload_is_redacted(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, _, span_id = _seed_with_payload(db_path)
            payload = inspection.get_span_payload(db_path=db_path, span_id=span_id)
            self.assertTrue(payload["available"])
            self.assertIn("[REDACTED", payload["content"])
            self.assertNotIn("SUPERSECRET", payload["content"])

    def test_get_span_payload_path_extraction(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, _, span_id = _seed_with_payload(db_path)
            payload = inspection.get_span_payload(
                db_path=db_path, span_id=span_id, path="messages.0.content"
            )
            self.assertTrue(payload["available"])
            self.assertEqual(payload["content"], "hello")

    def test_get_span_payload_bad_target_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, _, span_id = _seed_with_payload(db_path)
            with self.assertRaises(InspectionError):
                inspection.get_span_payload(db_path=db_path, span_id=span_id, target="bogus")


class InspectionCliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_current_run_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            code, out = self._run(["current-run", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["run"]["id"], run_id)

    def test_run_outline_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            code, out = self._run(["run-outline", run_id, "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["summary"]["spans"], 2)

    def test_span_payload_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, _, span_id = _seed_with_payload(db_path)
            code, out = self._run(["span-payload", span_id, "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)
            parsed = json.loads(out)
            self.assertTrue(parsed["available"])
            self.assertNotIn("SUPERSECRET", parsed["content"])

    def test_search_run_cli(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            code, out = self._run(
                ["search-run", run_id, "gen_ai", "--db", str(db_path), "--json"]
            )
            self.assertEqual(code, 0)
            self.assertGreater(json.loads(out)["match_count"], 0)


class InspectionWebTests(unittest.TestCase):
    def test_current_run_endpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            with RunningServer(db_path) as server:
                listed = server.get_json("/api/current-run")
                self.assertEqual(listed["run"]["id"], run_id)

    def test_run_outline_endpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            with RunningServer(db_path) as server:
                outline = server.get_json(f"/api/run-outline?run_id={run_id}")
                self.assertEqual(outline["summary"]["spans"], 2)
                self.assertEqual(outline["summary"]["failed_spans"], 1)

    def test_span_payload_endpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _, _, span_id = _seed_with_payload(db_path)
            with RunningServer(db_path) as server:
                payload = server.get_json(f"/api/span-payload?span_id={span_id}")
                self.assertTrue(payload["available"])
                self.assertNotIn("SUPERSECRET", payload["content"])

    def test_run_search_endpoint(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_id, _ = _seed_otlp(db_path)
            with RunningServer(db_path) as server:
                result = server.get_json(
                    f"/api/run-search?run_id={run_id}&pattern=gen_ai"
                )
                self.assertGreater(result["match_count"], 0)


if __name__ == "__main__":
    unittest.main()
