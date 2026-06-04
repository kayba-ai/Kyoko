import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import storage
from kyoko.blobs import put_json_blob
from kyoko.cli import main
from kyoko.eval_detectors import (
    DetectorError,
    export_run_trace,
    get_detector,
    list_detectors,
    parse_corpus,
    register_detector,
    run_detector,
    seed_bundled_detectors,
)


def _seed(db_path: Path, *, runs: int = 2) -> None:
    storage.initialize_database(db_path)
    con = storage.connect(db_path)
    con.execute(
        "INSERT INTO profiles VALUES ('p1','p1','/tmp','active','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')"
    )
    con.execute(
        "INSERT INTO sources (id,profile_id,kind,display_name,status,adapter_version,config_json,capabilities_json) "
        "VALUES ('s1','p1','t','s','active','1','{}','{}')"
    )
    for i in range(runs):
        rid = f"run_{i}"
        con.execute(
            "INSERT INTO runs (id,profile_id,source_id,status,started_at,metadata_json) VALUES (?,?,?,?,?,?)",
            (rid, "p1", "s1", "succeeded", f"2026-01-0{i+1}T00:00:00Z", "{}"),
        )
        # one llm span (with completion attr) + one tool span; run_1's tool fails
        con.execute(
            "INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{rid}_llm", rid, "s1", "llm", "gen", "ok", f"2026-01-0{i+1}T00:00:01Z", "{}",
             json.dumps({"gen_ai.system": "openai", "gen_ai.request.model": "gpt-4o",
                         "gen_ai.completion.0.content": "" if i == 0 else "an answer"})),
        )
        con.execute(
            "INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{rid}_tool", rid, "s1", "tool", "fetch", "failed" if i == 1 else "ok",
             f"2026-01-0{i+1}T00:00:02Z", "{}", "{}"),
        )
    con.commit()
    con.close()


def _register_code(db_path: Path, code: str, name: str) -> dict:
    with TemporaryDirectory() as d:
        p = Path(d) / f"{name}.py"
        p.write_text(code)
        return register_detector(db_path=db_path, path=p, source="user")


def _run_json(args: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(args)
    out = buf.getvalue().strip()
    return code, (json.loads(out.splitlines()[-1]) if out else {})


class BundledDetectorTests(unittest.TestCase):
    def test_seed_idempotent_and_list(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db)
            seed_bundled_detectors(db_path=db)
            seed_bundled_detectors(db_path=db)  # idempotent
            ids = sorted(d["id"] for d in list_detectors(db_path=db))
            self.assertEqual(ids, ["empty_llm_output", "failed_span"])
            det = get_detector(db_path=db, detector_id="failed_span")
            self.assertEqual(det["kind"], "python")
            self.assertEqual(det["direction"], "true_is_notable")

    def test_failed_span_prevalence(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            report = run_detector(db_path=db, detector_id="failed_span", corpus={"unit": "event"})
            # 4 spans, 1 failed (run_1_tool) -> num=3 (not failed), den=4
            self.assertEqual(report.aggregate["numerator"], 3)
            self.assertEqual(report.aggregate["denominator"], 4)

    def test_empty_llm_output_uses_normalized(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            report = run_detector(db_path=db, detector_id="empty_llm_output", corpus={"unit": "event"})
            # 2 llm spans, run_0 empty completion -> 1 problem; num=1 (not problem), den=2
            self.assertEqual(report.aggregate["denominator"], 2)
            self.assertEqual(report.aggregate["numerator"], 1)


class DetectorDispatchTests(unittest.TestCase):
    def test_per_trace_list_shape(self) -> None:
        code = (
            "DETECTOR = {'id':'d_list','name':'list','direction':'true_is_notable'}\n"
            "def detect(trace_data, trace_id):\n"
            "    return [{'event_id': s['id'], 'has_problem': s['status']=='failed'}"
            " for s in trace_data['spans']]\n"
        )
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            _register_code(db, code, "d_list")
            report = run_detector(db_path=db, detector_id="d_list", corpus={"unit": "event"})
            self.assertEqual(report.aggregate["denominator"], 4)
            self.assertEqual(report.aggregate["numerator"], 3)

    def test_per_trace_tuple_shape(self) -> None:
        code = (
            "DETECTOR = {'id':'d_tuple','name':'tuple','direction':'true_is_notable'}\n"
            "def detect(trace_data, trace_id):\n"
            "    bad = [s['id'] for s in trace_data['spans'] if s['status']=='failed']\n"
            "    return (len(bad), len(trace_data['spans']), bad)\n"
        )
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            _register_code(db, code, "d_tuple")
            report = run_detector(db_path=db, detector_id="d_tuple", corpus={"unit": "event"})
            # tuple num = flagged (bad) summed across traces = 1; den = 4 spans
            self.assertEqual(report.aggregate["numerator"], 1)
            self.assertEqual(report.aggregate["denominator"], 4)
            flagged = [e for e in report.events if e["has_problem"]]
            self.assertEqual([e["event_id"] for e in flagged], ["run_1_tool"])

    def test_folder_mode(self) -> None:
        code = (
            "DETECTOR = {'id':'d_folder','name':'folder','direction':'true_is_notable'}\n"
            "import os, json\n"
            "def detect(traces_folder):\n"
            "    files = [f for f in os.listdir(traces_folder) if f.endswith('.json')]\n"
            "    return (len(files), len(files), [])\n"
        )
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            _register_code(db, code, "d_folder")
            report = run_detector(db_path=db, detector_id="d_folder", corpus={"unit": "event"})
            self.assertEqual(report.aggregate["numerator"], 2)
            self.assertEqual(report.aggregate["denominator"], 2)

    def test_detect_discovery_fallback_single_function(self) -> None:
        code = (
            "DETECTOR = {'id':'d_fallback','name':'fallback','direction':'true_is_notable'}\n"
            "def my_only_detector(trace_data, trace_id):\n"
            "    return [{'event_id': trace_data['run']['id'], 'has_problem': False}]\n"
        )
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            _register_code(db, code, "d_fallback")
            report = run_detector(db_path=db, detector_id="d_fallback", corpus={"unit": "event"})
            self.assertEqual(report.aggregate["denominator"], 2)
            self.assertEqual(report.aggregate["numerator"], 2)

    def test_missing_detect_raises(self) -> None:
        code = (
            "DETECTOR = {'id':'d_bad','name':'bad','direction':'true_is_notable'}\n"
            "def a(x, y):\n    return []\n"
            "def b(x, y):\n    return []\n"
        )
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            _register_code(db, code, "d_bad")
            with self.assertRaises(DetectorError):
                run_detector(db_path=db, detector_id="d_bad", corpus={"unit": "event"})

    def test_register_rejects_non_function_file(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            with self.assertRaises(DetectorError):
                _register_code(db, "X = 1\n", "nofn")


class ExportTests(unittest.TestCase):
    def test_export_run_trace_includes_normalized(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            trace = export_run_trace(db_path=db, run_id="run_0")
            self.assertEqual(trace["run"]["id"], "run_0")
            kinds = {s["normalized"]["kind"] for s in trace["spans"]}
            self.assertIn("llm", kinds)


class ParseCorpusTests(unittest.TestCase):
    def test_inline_and_default_and_file(self) -> None:
        self.assertEqual(parse_corpus(None), {"unit": "event"})
        self.assertEqual(parse_corpus('{"unit":"run","limit":5}'), {"unit": "run", "limit": 5})
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / "c.json"
            p.write_text('{"unit":"llm_span"}')
            self.assertEqual(parse_corpus(str(p)), {"unit": "llm_span"})
        with self.assertRaises(DetectorError):
            parse_corpus("not json")


class CliTests(unittest.TestCase):
    def test_cli_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            code, payload = _run_json(["evals", "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertIn("failed_span", {d["id"] for d in payload["detectors"]})

            code, payload = _run_json(["eval-detail", "failed_span", "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["detector"]["id"], "failed_span")

            code, payload = _run_json(
                ["run-eval", "failed_span", "--db", str(db), "--corpus", '{"unit":"event"}',
                 "--persist", "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["aggregate"]["denominator"], 4)
            self.assertTrue(payload["persisted"])
            run_id = payload["eval_run_id"]

            code, payload = _run_json(["eval-runs", "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual([r["id"] for r in payload["eval_runs"]], [run_id])

            code, payload = _run_json(["eval-run-detail", run_id, "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["eval_run"]["id"], run_id)
            self.assertEqual(len(payload["results"]), 4)


if __name__ == "__main__":
    unittest.main()
