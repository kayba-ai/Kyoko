import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import storage
from kyoko.evals_measure import (
    EvalMeasureError,
    aggregate_boolean,
    aggregate_numeric,
    complete_measure_run,
    create_measure_run,
    fail_measure_run,
    get_eval_definition,
    get_measure_results,
    get_measure_run,
    list_eval_definitions,
    list_measure_runs,
    record_measure_result,
    resolve_corpus,
    upsert_eval_definition,
)


def _seed(db_path: Path, *, runs: int = 3, llm_spans: int = 1, tool_spans: int = 1) -> list[str]:
    """Insert a profile + source + `runs` runs, each with llm/tool spans.

    Returns the ordered run ids. started_at is monotonic so corpus ordering is
    deterministic.
    """
    storage.initialize_database(db_path)
    con = storage.connect(db_path)
    con.execute(
        "INSERT INTO profiles (id, name, root_path, status, created_at, updated_at) "
        "VALUES ('p1','p1','/tmp','active','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )
    con.execute(
        "INSERT INTO sources (id, profile_id, kind, display_name, status, adapter_version, "
        "config_json, capabilities_json) VALUES ('s1','p1','test','src','active','1','{}','{}')"
    )
    run_ids: list[str] = []
    for i in range(runs):
        rid = f"run_{i:02d}"
        run_ids.append(rid)
        con.execute(
            "INSERT INTO runs (id, profile_id, source_id, status, started_at, metadata_json) "
            "VALUES (?,?,?,?,?,?)",
            (rid, "p1", "s1", "succeeded", f"2026-01-0{i+1}T00:00:00Z", "{}"),
        )
        for j in range(llm_spans):
            con.execute(
                "INSERT INTO spans (id, run_id, source_id, kind, name, status, started_at, "
                "usage_json, attributes_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{rid}_llm_{j}", rid, "s1", "llm", "gen", "ok", f"2026-01-0{i+1}T00:00:01Z", "{}", "{}"),
            )
        for j in range(tool_spans):
            con.execute(
                "INSERT INTO spans (id, run_id, source_id, kind, name, status, started_at, "
                "usage_json, attributes_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{rid}_tool_{j}", rid, "s1", "tool", "fetch", "ok", f"2026-01-0{i+1}T00:00:02Z", "{}", "{}"),
            )
    con.commit()
    con.close()
    return run_ids


class MigrationTests(unittest.TestCase):
    def test_measurement_tables_exist_and_idempotent(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            storage.initialize_database(db_path)
            storage.initialize_database(db_path)  # idempotent
            con = storage.connect(db_path)
            names = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            con.close()
            for t in ("eval_definitions", "eval_measure_runs", "eval_measure_results"):
                self.assertIn(t, names)
            status = storage.get_database_status(db_path)
            self.assertEqual(status.schema_version, 27)


class CorpusTests(unittest.TestCase):
    def test_run_units(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_ids = _seed(db_path, runs=3)
            res = resolve_corpus(db_path=db_path, corpus={"unit": "run"})
            self.assertEqual(res.unit_type, "run")
            self.assertEqual(res.unit_refs, run_ids)
            self.assertFalse(res.over_cap)
            self.assertEqual(res.total_matched, 3)

    def test_event_units_resolve_to_runs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_ids = _seed(db_path, runs=2)
            res = resolve_corpus(db_path=db_path, corpus={"unit": "event"})
            self.assertEqual(res.unit_refs, run_ids)

    def test_llm_span_units_filter_by_kind(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=2, llm_spans=1, tool_spans=2)
            res = resolve_corpus(db_path=db_path, corpus={"unit": "llm_span"})
            self.assertEqual(res.unit_type, "llm_span")
            self.assertEqual(res.unit_refs, ["run_00_llm_0", "run_01_llm_0"])
            # explicit tool filter
            res_tool = resolve_corpus(
                db_path=db_path, corpus={"unit": "llm_span", "span_filter": {"kind": "tool"}}
            )
            self.assertEqual(len(res_tool.unit_refs), 4)

    def test_limit_caps_and_reports_dropped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=5)
            res = resolve_corpus(db_path=db_path, corpus={"unit": "run", "limit": 2})
            self.assertEqual(len(res.unit_refs), 2)
            self.assertTrue(res.over_cap)
            self.assertEqual(res.dropped, 3)
            self.assertEqual(res.total_matched, 5)

    def test_run_ids_and_since_filters(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=4)
            res = resolve_corpus(
                db_path=db_path, corpus={"unit": "run", "run_ids": ["run_01", "run_03"]}
            )
            self.assertEqual(res.unit_refs, ["run_01", "run_03"])
            res_since = resolve_corpus(
                db_path=db_path, corpus={"unit": "run", "since": "2026-01-03T00:00:00Z"}
            )
            self.assertEqual(res_since.unit_refs, ["run_02", "run_03"])

    def test_invalid_unit_and_limit(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=1)
            with self.assertRaises(EvalMeasureError):
                resolve_corpus(db_path=db_path, corpus={"unit": "bogus"})
            with self.assertRaises(EvalMeasureError):
                resolve_corpus(db_path=db_path, corpus={"unit": "run", "limit": 0})


class DefinitionTests(unittest.TestCase):
    def test_upsert_get_list(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=1)
            d = upsert_eval_definition(
                db_path=db_path,
                definition_id="hallucination",
                kind="llm",
                name="Hallucination",
                version=1,
                unit_type="llm_span",
                output_type="numeric",
                direction="lower_is_better",
                source="bundled",
                partner=None,
                prompt="Q: {{query}} A: {{generation}}",
                vars=["query", "generation"],
                bindings={"query": "unit.user_query", "generation": "unit.output_text"},
                output={"type": "numeric", "range": [0, 1]},
                severity_bands={"low": 0.2, "medium": 0.5, "high": 0.8},
            )
            self.assertEqual(d["id"], "hallucination")
            self.assertEqual(d["vars"], ["query", "generation"])
            self.assertEqual(d["output"], {"type": "numeric", "range": [0, 1]})
            created = d["created_at"]
            # upsert same id (version bump) preserves created_at, updates version
            d2 = upsert_eval_definition(
                db_path=db_path,
                definition_id="hallucination",
                kind="llm",
                name="Hallucination",
                version=2,
                unit_type="llm_span",
                output_type="numeric",
                direction="lower_is_better",
                source="bundled",
            )
            self.assertEqual(d2["version"], 2)
            self.assertEqual(d2["created_at"], created)
            # a python detector def
            upsert_eval_definition(
                db_path=db_path,
                kind="python",
                name="empty-response",
                version=1,
                unit_type="event",
                output_type="boolean",
                direction="true_is_notable",
                source="user",
                detector_ref="blob_abc",
            )
            llm_defs = list_eval_definitions(db_path=db_path, kind="llm")
            self.assertEqual([d["id"] for d in llm_defs], ["hallucination"])
            all_defs = list_eval_definitions(db_path=db_path)
            self.assertEqual(len(all_defs), 2)

    def test_invalid_enums(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=1)
            with self.assertRaises(EvalMeasureError):
                upsert_eval_definition(
                    db_path=db_path, kind="bogus", name="x", version=1,
                    unit_type="run", output_type="boolean", direction="true_is_notable",
                    source="user",
                )

    def test_get_missing_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=1)
            with self.assertRaises(EvalMeasureError):
                get_eval_definition(db_path=db_path, definition_id="nope")


class RunLifecycleTests(unittest.TestCase):
    def _definition(self, db_path: Path) -> dict:
        return upsert_eval_definition(
            db_path=db_path,
            definition_id="helpfulness",
            kind="llm",
            name="Helpfulness",
            version=1,
            unit_type="llm_span",
            output_type="numeric",
            direction="higher_is_better",
            source="bundled",
        )

    def test_lifecycle_counters_and_aggregate(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=2)
            definition = self._definition(db_path)
            corpus = {"unit": "llm_span"}
            run_id = create_measure_run(db_path=db_path, definition=definition, corpus=corpus)
            self.assertTrue(run_id.startswith("evalrun_"))

            record_measure_result(
                db_path=db_path, eval_run_id=run_id, unit_type="llm_span",
                unit_ref="run_00_llm_0", status="scored", score_numeric=0.8, detail={},
            )
            record_measure_result(
                db_path=db_path, eval_run_id=run_id, unit_type="llm_span",
                unit_ref="run_01_llm_0", status="scored", score_numeric=0.6, detail={},
            )
            record_measure_result(
                db_path=db_path, eval_run_id=run_id, unit_type="llm_span",
                unit_ref="run_02_llm_0", status="skipped", detail={"reason": "missing_var:query"},
            )

            run = get_measure_run(db_path=db_path, eval_run_id=run_id)
            self.assertEqual(run["unit_total"], 3)
            self.assertEqual(run["unit_scored"], 2)
            self.assertEqual(run["unit_skipped"], 1)
            self.assertEqual(run["status"], "running")

            agg = aggregate_numeric([0.8, 0.6], skipped=1)
            completed = complete_measure_run(db_path=db_path, eval_run_id=run_id, aggregate=agg)
            self.assertEqual(completed["status"], "complete")
            self.assertAlmostEqual(completed["aggregate"]["value"], 0.7)
            self.assertIsNotNone(completed["ended_at"])

            results = get_measure_results(db_path=db_path, eval_run_id=run_id)
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0]["unit_ref"], "run_00_llm_0")

            runs = list_measure_runs(db_path=db_path, kind="llm")
            self.assertEqual(len(runs), 1)

    def test_fail_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=1)
            definition = self._definition(db_path)
            run_id = create_measure_run(db_path=db_path, definition=definition, corpus={"unit": "llm_span"})
            failed = fail_measure_run(db_path=db_path, eval_run_id=run_id, detail="boom")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["aggregate"]["error"], "boom")

    def test_record_into_missing_run_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path, runs=1)
            with self.assertRaises(EvalMeasureError):
                record_measure_result(
                    db_path=db_path, eval_run_id="evalrun_missing", unit_type="run",
                    unit_ref="run_00", status="scored", detail={},
                )


class AggregateTests(unittest.TestCase):
    def test_boolean_prevalence(self) -> None:
        self.assertEqual(aggregate_boolean(6, 50)["value"], 0.12)
        empty = aggregate_boolean(0, 0)
        self.assertEqual(empty["value"], 0.0)
        self.assertEqual(empty["denominator"], 0)

    def test_numeric_mean_histogram(self) -> None:
        agg = aggregate_numeric([0.1, 0.3, 0.9, 0.95], skipped=2)
        self.assertEqual(agg["scored"], 4)
        self.assertEqual(agg["skipped"], 2)
        self.assertAlmostEqual(agg["value"], (0.1 + 0.3 + 0.9 + 0.95) / 4)
        self.assertEqual(agg["histogram"]["0-0.2"], 1)
        self.assertEqual(agg["histogram"]["0.2-0.5"], 1)
        self.assertEqual(agg["histogram"]["0.8-1"], 2)

    def test_numeric_empty(self) -> None:
        agg = aggregate_numeric([])
        self.assertEqual(agg["value"], 0.0)
        self.assertEqual(agg["scored"], 0)


if __name__ == "__main__":
    unittest.main()
