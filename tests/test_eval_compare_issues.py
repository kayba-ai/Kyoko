"""Phase 4 (compare) + Phase 5 (raise-issues) for both measurement planes."""

import io
import json
import shlex
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import storage
from kyoko.cli import main
from kyoko.eval_detectors import DetectorError, run_detector
from kyoko.eval_issues import problem_value, severity_band
from kyoko.evals_measure import EvalMeasureError, compare_eval_runs
from kyoko.issues import list_issues
from kyoko.llm_evals import LlmEvalError, run_llm_eval

ROOT = Path(__file__).resolve().parents[1]
JUDGE = [sys.executable, str(ROOT / "tests/fixtures/llm_eval_judge.py")]


def _seed_runs(db_path: Path, specs: dict[str, list[str]]) -> None:
    """specs: {run_id: [span_status, ...]} of tool spans under profile p1."""
    storage.initialize_database(db_path)
    con = storage.connect(db_path)
    con.execute("INSERT INTO profiles VALUES ('p1','p1','/tmp','active','t','t')")
    con.execute(
        "INSERT INTO sources (id,profile_id,kind,display_name,status,adapter_version,config_json,capabilities_json) "
        "VALUES ('s1','p1','t','s','active','1','{}','{}')"
    )
    for i, (rid, statuses) in enumerate(specs.items()):
        con.execute(
            "INSERT INTO runs (id,profile_id,source_id,status,started_at,metadata_json) VALUES (?,?,?,?,?,?)",
            (rid, "p1", "s1", "succeeded", f"2026-01-0{i+1}T00:00:00Z", "{}"),
        )
        for j, status in enumerate(statuses):
            con.execute(
                "INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (f"{rid}_{j}", rid, "s1", "tool", "t", status, f"2026-01-0{i+1}T00:00:0{j}Z", "{}", "{}"),
            )
    con.commit()
    con.close()


def _run_json(args: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(args)
    out = buf.getvalue().strip()
    return code, (json.loads(out.splitlines()[-1]) if out else {})


class SeverityTests(unittest.TestCase):
    def test_problem_value_orientation(self) -> None:
        # lower-is-better / notable: value is the problem level
        self.assertEqual(problem_value(0.8, "true_is_notable"), 0.8)
        self.assertEqual(problem_value(0.8, "lower_is_better"), 0.8)
        # higher-is-better: problem = 1 - value
        self.assertAlmostEqual(problem_value(0.8, "higher_is_better"), 0.2)

    def test_severity_bands(self) -> None:
        self.assertEqual(severity_band(0.9, None), "high")
        self.assertEqual(severity_band(0.6, None), "medium")
        self.assertEqual(severity_band(0.3, None), "low")
        self.assertIsNone(severity_band(0.1, None))


class CompareTests(unittest.TestCase):
    def _two_runs(self, db, base_statuses, comp_statuses):
        _seed_runs(db, {"run_a": base_statuses, "run_b": comp_statuses})
        a = run_detector(db_path=db, detector_id="failed_span",
                         corpus={"unit": "event", "run_ids": ["run_a"]}, persist=True)
        b = run_detector(db_path=db, detector_id="failed_span",
                         corpus={"unit": "event", "run_ids": ["run_b"]}, persist=True)
        return a.eval_run_id, b.eval_run_id

    def test_improved(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            a, b = self._two_runs(db, ["failed", "ok"], ["ok", "ok"])  # 0.5 -> 0.0
            cmp = compare_eval_runs(db_path=db, baseline_run_id=a, compare_run_id=b)
            self.assertEqual(cmp["direction"], "improved")
            self.assertAlmostEqual(cmp["delta"], -0.5)

    def test_regressed(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            a, b = self._two_runs(db, ["ok", "ok"], ["failed", "ok"])  # 0.0 -> 0.5
            cmp = compare_eval_runs(db_path=db, baseline_run_id=a, compare_run_id=b)
            self.assertEqual(cmp["direction"], "regressed")

    def test_unchanged_within_epsilon(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            a, b = self._two_runs(db, ["failed", "ok"], ["failed", "ok"])  # 0.5 -> 0.5
            cmp = compare_eval_runs(db_path=db, baseline_run_id=a, compare_run_id=b)
            self.assertEqual(cmp["direction"], "unchanged")

    def test_definition_mismatch_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed_runs(db, {"run_a": ["failed"]})
            a = run_detector(db_path=db, detector_id="failed_span",
                             corpus={"unit": "event", "run_ids": ["run_a"]}, persist=True)
            b = run_detector(db_path=db, detector_id="empty_llm_output",
                             corpus={"unit": "event", "run_ids": ["run_a"]}, persist=True)
            with self.assertRaises(EvalMeasureError):
                compare_eval_runs(db_path=db, baseline_run_id=a.eval_run_id, compare_run_id=b.eval_run_id)

    def test_cli_eval_compare(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            a, b = self._two_runs(db, ["failed", "ok"], ["ok", "ok"])
            code, payload = _run_json(["eval-compare", a, b, "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["direction"], "improved")


class RaiseIssuesTests(unittest.TestCase):
    def test_detector_raises_issue_above_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed_runs(db, {"run_a": ["failed", "ok"]})  # problem 0.5
            report = run_detector(db_path=db, detector_id="failed_span",
                                  corpus={"unit": "event"}, raise_issues=True, issue_threshold=0.3)
            self.assertIsNotNone(report.raised_issue_id)
            self.assertTrue(report.persisted)  # forced
            issues = list_issues(db_path=db)
            self.assertEqual(len(issues), 1)
            self.assertEqual(issues[0]["severity"], "medium")
            self.assertEqual(issues[0]["category"], "measurement")

    def test_detector_no_issue_below_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed_runs(db, {"run_a": ["ok", "ok"]})  # problem 0.0
            report = run_detector(db_path=db, detector_id="failed_span",
                                  corpus={"unit": "event"}, raise_issues=True, issue_threshold=0.3)
            self.assertIsNone(report.raised_issue_id)
            self.assertEqual(list_issues(db_path=db), [])

    def test_raise_issues_requires_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed_runs(db, {"run_a": ["failed"]})
            with self.assertRaises(DetectorError):
                run_detector(db_path=db, detector_id="failed_span", corpus={"unit": "event"},
                             raise_issues=True)

    def test_llm_eval_raises_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            storage.initialize_database(db)
            con = storage.connect(db)
            con.execute("INSERT INTO profiles VALUES ('p1','p1','/tmp','active','t','t')")
            con.execute("INSERT INTO sources (id,profile_id,kind,display_name,status,adapter_version,config_json,capabilities_json) VALUES ('s1','p1','t','s','active','1','{}','{}')")
            con.execute("INSERT INTO runs (id,profile_id,source_id,status,started_at,metadata_json) VALUES ('run_0','p1','s1','succeeded','2026-01-01T00:00:00Z','{}')")
            con.execute("INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) VALUES ('run_0_llm','run_0','s1','llm','gen','ok','2026-01-01T00:00:01Z','{}',?)",
                        (json.dumps({"gen_ai.prompt.0.role":"user","gen_ai.prompt.0.content":"What is the capital?","gen_ai.completion.0.content":"The capital is Paris."}),))
            con.commit(); con.close()
            import os
            os.environ["MOCK_BOOL"] = "true"  # user_distress true_is_notable -> problem 1.0
            try:
                report = run_llm_eval(db_path=db, llm_eval_id="user_distress", corpus={"unit": "run"},
                                      command=JUDGE, raise_issues=True, issue_threshold=0.5)
            finally:
                del os.environ["MOCK_BOOL"]
            self.assertIsNotNone(report.raised_issue_id)
            self.assertEqual(list_issues(db_path=db)[0]["severity"], "high")

    def test_cli_run_eval_raise_issues(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed_runs(db, {"run_a": ["failed", "ok"]})
            code, payload = _run_json([
                "run-eval", "failed_span", "--db", str(db), "--corpus", '{"unit":"event"}',
                "--raise-issues", "--threshold", "0.3", "--json",
            ])
            self.assertEqual(code, 0)
            self.assertIsNotNone(payload["raised_issue_id"])


if __name__ == "__main__":
    unittest.main()
