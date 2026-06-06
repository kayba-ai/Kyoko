import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

from kyoko import storage
from kyoko.annotations import create_annotation
from kyoko.cli import main
from kyoko.evals_measure import EvalMeasureError
from kyoko.llm_evals import (
    LlmEvalError,
    get_llm_eval,
    list_llm_evals,
    run_llm_eval,
    set_llm_eval_status,
)
from kyoko.metric_bindings import resolve_bindings

ROOT = Path(__file__).resolve().parents[1]
JUDGE = [sys.executable, str(ROOT / "tests/fixtures/llm_eval_judge.py")]
OP_JUDGE = str(ROOT / "tests/fixtures/llm_eval_operator_judge.py")


def _seed(db_path: Path, *, runs: int = 1, empty_completion: bool = False) -> None:
    storage.initialize_database(db_path)
    con = storage.connect(db_path)
    con.execute(
        "INSERT INTO profiles VALUES ('p1','p1','/tmp','active','2026-01-01T00:00:00Z','2026-01-01T00:00:00Z',NULL)"
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
        attrs = {
            "gen_ai.prompt.0.role": "user",
            "gen_ai.prompt.0.content": f"What is the capital of country {i}?",
        }
        if not empty_completion:
            attrs["gen_ai.completion.0.content"] = f"The capital is city {i}."
        con.execute(
            "INSERT INTO spans (id,run_id,source_id,kind,name,status,started_at,usage_json,attributes_json) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (f"{rid}_llm", rid, "s1", "llm", "gen", "ok", f"2026-01-0{i+1}T00:00:01Z", "{}", json.dumps(attrs)),
        )
    con.commit()
    con.close()


def _run_json(args: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(args)
    out = buf.getvalue().strip()
    return code, (json.loads(out.splitlines()[-1]) if out else {})


class CatalogTests(unittest.TestCase):
    def test_ten_templates_seeded(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db)
            templates = list_llm_evals(db_path=db)
            self.assertEqual(len(templates), 10)
            ids = {t["id"] for t in templates}
            self.assertEqual(
                ids,
                {"hallucination", "helpfulness", "relevance", "toxicity", "conciseness",
                 "faithfulness_v1", "user_distress", "user_disagreement",
                 "out_of_scope_request", "goal_accuracy"},
            )
            # ragas attribution preserved
            faith = get_llm_eval(db_path=db, llm_eval_id="faithfulness_v1")
            self.assertEqual(faith["partner"], "ragas")
            self.assertEqual(get_llm_eval(db_path=db, llm_eval_id="goal_accuracy")["partner"], "ragas")
            # vars/bindings/output present
            hall = get_llm_eval(db_path=db, llm_eval_id="hallucination")
            self.assertEqual(set(hall["vars"]), {"query", "generation"})
            self.assertEqual(hall["output"]["type"], "numeric")


class BindingTests(unittest.TestCase):
    def test_llm_span_bindings(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            r = resolve_bindings(
                db_path=db, unit_type="llm_span", unit_ref="run_0_llm",
                bindings={"query": "unit.user_query", "generation": "unit.output_text"},
            )
            self.assertEqual(r.missing, [])
            self.assertEqual(r.values["query"], "What is the capital of country 0?")
            self.assertEqual(r.values["generation"], "The capital is city 0.")

    def test_run_bindings(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            r = resolve_bindings(
                db_path=db, unit_type="run", unit_ref="run_0",
                bindings={"conversation_history": "run.transcript",
                          "last_user_message": "run.last_user_message"},
            )
            self.assertEqual(r.missing, [])
            self.assertIn("user:", r.values["conversation_history"])
            self.assertEqual(r.values["last_user_message"], "What is the capital of country 0?")

    def test_missing_var_when_no_completion(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1, empty_completion=True)
            r = resolve_bindings(
                db_path=db, unit_type="llm_span", unit_ref="run_0_llm",
                bindings={"query": "unit.user_query", "generation": "unit.output_text"},
            )
            self.assertEqual(r.missing, ["generation"])

    def test_goal_accuracy_annotation_degrade(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            bindings = {"desired_outcome": "annotation.desired_outcome|run.first_user_message"}
            # no annotation -> degrade to first_user_message
            r = resolve_bindings(db_path=db, unit_type="run", unit_ref="run_0", bindings=bindings)
            self.assertTrue(r.degraded)
            self.assertEqual(r.values["desired_outcome"], "What is the capital of country 0?")
            # with a desired_outcome note -> not degraded
            create_annotation(
                db_path=db, run_id="run_0", kind="note", note="Return the capital city name.",
                metadata={"label_type": "desired_outcome"},
            )
            r2 = resolve_bindings(db_path=db, unit_type="run", unit_ref="run_0", bindings=bindings)
            self.assertFalse(r2.degraded)
            self.assertEqual(r2.values["desired_outcome"], "Return the capital city name.")


class RunTests(unittest.TestCase):
    def test_numeric_run_persisted(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            report = run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                command=JUDGE, persist=True,
            )
            self.assertEqual(report.aggregate["type"], "numeric")
            self.assertAlmostEqual(report.aggregate["value"], 0.3)
            self.assertEqual(report.aggregate["scored"], 2)
            self.assertTrue(report.persisted)
            self.assertTrue(all("mock reasoning" in r["reasoning"] for r in report.results))

    def test_boolean_run_notable(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            report = run_llm_eval(
                db_path=db, llm_eval_id="user_distress", corpus={"unit": "run"}, command=JUDGE,
            )
            # mock returns true; true_is_notable -> all notable
            self.assertEqual(report.aggregate["type"], "boolean")
            self.assertEqual(report.aggregate["numerator"], 2)
            self.assertEqual(report.aggregate["denominator"], 2)

    def test_skip_on_missing_var(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1, empty_completion=True)
            report = run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"}, command=JUDGE,
            )
            self.assertEqual(report.aggregate["scored"], 0)
            self.assertEqual(report.results[0]["status"], "skipped")
            self.assertTrue(report.results[0]["detail"]["reason"].startswith("missing_var:generation"))

    def test_prepare_only_writes_requests(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            out = Path(tmp) / "prep"
            report = run_llm_eval(
                db_path=db, llm_eval_id="helpfulness", corpus={"unit": "llm_span"},
                prepare_only=True, output_dir=out,
            )
            self.assertTrue(report.prepared_only)
            self.assertTrue((out / "handoff.json").exists())
            self.assertTrue((out / "run_0_llm.json").exists())
            req = json.loads((out / "run_0_llm.json").read_text())
            self.assertEqual(req["schema_version"], "kyoko.llm_eval_request.v1")
            self.assertIn("capital", req["prompt"])  # rendered

    def test_command_required_unless_prepare_only(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            with self.assertRaises(LlmEvalError):
                run_llm_eval(db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"})

    def test_score_out_of_range_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            import os
            env_judge = JUDGE
            os.environ["MOCK_SCORE"] = "5.0"
            try:
                with self.assertRaises(LlmEvalError):
                    run_llm_eval(
                        db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                        command=env_judge,
                    )
            finally:
                del os.environ["MOCK_SCORE"]


class SseProgressTests(unittest.TestCase):
    def test_bus_emits_progress_and_complete(self) -> None:
        from kyoko.live import LiveBus

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            bus = LiveBus()
            sub = bus.subscribe()
            run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                command=JUDGE, persist=True, bus=bus,
            )
            kinds = []
            while not sub.empty():
                msg = sub.get_nowait()
                kinds.append(msg["data"]["kind"])
            # progress per scored unit (2) + a terminal complete
            self.assertEqual(kinds.count("eval_progress"), 2)
            self.assertEqual(kinds.count("eval_complete"), 1)


class CliTests(unittest.TestCase):
    def test_cli_flow(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            code, payload = _run_json(["llm-evals", "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(len(payload["llm_evals"]), 10)

            code, payload = _run_json(["llm-eval-detail", "toxicity", "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["llm_eval"]["direction"], "lower_is_better")

            import shlex
            code, payload = _run_json([
                "run-llm-eval", "hallucination", "--db", str(db), "--corpus", '{"unit":"llm_span"}',
                "--command", shlex.join(JUDGE), "--persist", "--json",
            ])
            self.assertEqual(code, 0)
            self.assertAlmostEqual(payload["aggregate"]["value"], 0.3)
            run_id = payload["eval_run_id"]

            code, payload = _run_json(["llm-eval-runs", "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual([r["id"] for r in payload["eval_runs"]], [run_id])

            code, payload = _run_json(["llm-eval-run-detail", run_id, "--db", str(db), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(payload["eval_run"]["id"], run_id)
            self.assertEqual(len(payload["results"]), 1)


class SetStatusTests(unittest.TestCase):
    def test_status_persists_across_reseed(self) -> None:
        # The crux: bundled templates re-seed on every list/get; archiving a
        # judge must survive that, and must not touch any other judge.
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db)
            out = set_llm_eval_status(db_path=db, llm_eval_id="conciseness", status="archived")
            self.assertEqual(out["status"], "archived")
            by_id = {e["id"]: e["status"] for e in list_llm_evals(db_path=db)}  # re-seeds
            self.assertEqual(by_id["conciseness"], "archived")
            self.assertTrue(all(s == "active" for i, s in by_id.items() if i != "conciseness"))
            # Reactivation works too.
            set_llm_eval_status(db_path=db, llm_eval_id="conciseness", status="active")
            self.assertEqual(get_llm_eval(db_path=db, llm_eval_id="conciseness")["status"], "active")

    def test_invalid_status_and_missing_id_rejected(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db)
            with self.assertRaises(EvalMeasureError):
                set_llm_eval_status(db_path=db, llm_eval_id="conciseness", status="bogus")
            with self.assertRaises(EvalMeasureError):
                set_llm_eval_status(db_path=db, llm_eval_id="does_not_exist", status="active")

    def test_cli_set_status(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db)
            code, payload = _run_json(
                ["llm-eval-set-status", "toxicity", "archived", "--db", str(db), "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(payload["llm_eval"]["status"], "archived")
            self.assertEqual(get_llm_eval(db_path=db, llm_eval_id="toxicity")["status"], "archived")


def _register_op_judge(db: Path, *, with_placeholder: bool = True) -> None:
    from kyoko.operator_adapters import register_operator_adapter

    command = [sys.executable, OP_JUDGE]
    if with_placeholder:
        command.append("{prompt_path}")
    register_operator_adapter(
        db_path=db, adapter_id="judge_claude", name="Judge",
        command=command, operator_kind="claude", profile_id="p1",
    )


class OperatorJudgeTests(unittest.TestCase):
    """The backend-agnostic judge path: an operator adapter (any agent CLI) scores via
    {prompt_path}/{prompt} or stdin, and stdout is parsed tolerantly."""

    def test_operator_numeric_persisted_placeholder(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            _register_op_judge(db, with_placeholder=True)
            report = run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                operator_adapter_id="judge_claude", persist=True, profile_id="p1",
            )
            # 0.3 survives the echoed-prompt chatter (tolerant parse picks the last block)
            self.assertEqual(report.aggregate["scored"], 2)
            self.assertAlmostEqual(report.aggregate["value"], 0.3)
            self.assertTrue(report.persisted)
            self.assertTrue(all("operator mock" in r["reasoning"] for r in report.results))

    def test_operator_stdin_delivery(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            _register_op_judge(db, with_placeholder=False)  # no placeholder -> prompt on stdin
            report = run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                operator_adapter_id="judge_claude", profile_id="p1",
            )
            self.assertEqual(report.aggregate["scored"], 1)
            self.assertAlmostEqual(report.aggregate["value"], 0.3)

    def test_operator_boolean_template(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            _register_op_judge(db)
            report = run_llm_eval(
                db_path=db, llm_eval_id="user_distress", corpus={"unit": "run"},
                operator_adapter_id="judge_claude", profile_id="p1",
            )
            # numeric 0.3 coerces truthy -> notable under true_is_notable
            self.assertEqual(report.aggregate["type"], "boolean")
            self.assertEqual(report.aggregate["denominator"], 1)
            self.assertEqual(report.aggregate["numerator"], 1)

    def test_operator_alone_satisfies_command_requirement(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            _register_op_judge(db)
            # neither --command nor prepare_only, but operator_adapter_id is enough
            report = run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                operator_adapter_id="judge_claude", profile_id="p1",
            )
            self.assertEqual(report.status, "complete")

    def test_cli_run_llm_eval_operator_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            _register_op_judge(db)
            code, payload = _run_json([
                "run-llm-eval", "hallucination", "--db", str(db),
                "--corpus", '{"unit":"llm_span"}', "--operator", "judge_claude",
                "--persist", "--json",
            ])
            self.assertEqual(code, 0)
            self.assertAlmostEqual(payload["aggregate"]["value"], 0.3)


class TruncationTests(unittest.TestCase):
    def test_truncate_text_head_tail(self) -> None:
        from kyoko.llm_evals import _truncate_text

        kept, was = _truncate_text("x" * 100, 100)
        self.assertFalse(was)
        marker = "\n…[truncated for length]…\n"
        kept, was = _truncate_text("a" * 300 + "b" * 300, 200)
        self.assertTrue(was)
        self.assertLessEqual(len(kept), 200 + len(marker))
        self.assertTrue(kept.startswith("a"))
        self.assertTrue(kept.endswith("b"))  # head AND tail retained, middle elided
        self.assertIn(marker, kept)

    def test_long_var_flagged_truncated_in_results(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            # overwrite the completion with a >budget blob so the generation var truncates
            con = storage.connect(db)
            attrs = {
                "gen_ai.prompt.0.role": "user",
                "gen_ai.prompt.0.content": "What is the capital of country 0?",
                "gen_ai.completion.0.content": "z" * 60000,
            }
            con.execute(
                "UPDATE spans SET attributes_json = ? WHERE id = 'run_0_llm'",
                (json.dumps(attrs),),
            )
            con.commit()
            con.close()
            report = run_llm_eval(
                db_path=db, llm_eval_id="hallucination", corpus={"unit": "llm_span"},
                command=JUDGE, profile_id="p1",
            )
            self.assertEqual(report.results[0]["status"], "scored")
            self.assertEqual(report.results[0]["truncated"], ["generation"])


class LlmJudgeScheduleTests(unittest.TestCase):
    """The 'llm_judge' analysis schedule: judges new traces via an operator adapter,
    advances a watermark, and is idempotent (a second fire with no new traces skips)."""

    def _schedule(self, db: Path, **meta):
        from kyoko.storage import create_analysis_schedule

        return create_analysis_schedule(
            db_path=db, analyzer_kind="llm_judge", adapter_id="judge_claude",
            interval_hours=6, profile_id="p1",
            metadata={"llm_eval_ids": meta["templates"]} if meta.get("templates") else None,
        )

    def test_schedule_scores_new_runs_then_skips(self) -> None:
        from kyoko.analysis_runner import execute_analysis_job, job_from_schedule
        from kyoko.storage import get_analysis_schedule

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=2)
            _register_op_judge(db)
            sched = self._schedule(db, templates=["hallucination"])

            res = execute_analysis_job(db, job_from_schedule(sched))
            self.assertEqual(res["status"], "succeeded")
            judge = res["llm_judge"]
            self.assertEqual(judge["template_count"], 1)
            self.assertEqual(judge["runs"][0]["llm_eval_id"], "hallucination")
            self.assertEqual(judge["runs"][0]["aggregate"]["scored"], 2)

            # watermark advanced -> a second fire sees no new traces and skips
            updated = get_analysis_schedule(db_path=db, schedule_id=sched["id"])
            self.assertIsNotNone(updated["watermark"])
            res2 = execute_analysis_job(db, job_from_schedule(updated))
            self.assertEqual(res2["status"], "skipped")
            self.assertEqual(res2["reason"], "no_new_traces")

    def test_schedule_defaults_to_all_active_templates(self) -> None:
        from kyoko.analysis_runner import execute_analysis_job, job_from_schedule

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            _register_op_judge(db)
            sched = self._schedule(db)  # no templates -> all active
            res = execute_analysis_job(db, job_from_schedule(sched))
            self.assertEqual(res["status"], "succeeded")
            self.assertEqual(res["llm_judge"]["template_count"], 10)

    def test_schedule_requires_adapter(self) -> None:
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "k.db"
            _seed(db, runs=1)
            with self.assertRaises(storage.StorageError):
                storage.create_analysis_schedule(
                    db_path=db, analyzer_kind="llm_judge", adapter_id=None,
                    interval_hours=6, profile_id="p1",
                )


if __name__ == "__main__":
    unittest.main()
