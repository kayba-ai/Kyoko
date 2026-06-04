from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.eval_detectors import get_detector, run_detector
from kyoko.issue_guard import (
    GuardError,
    generate_guard_detector_source,
    mint_guard_for_issue,
)
from kyoko.issues import create_issue, get_issue, list_issues
from kyoko.storage import ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


def _seed(db_path: Path) -> None:
    ingest_source_fixture(db_path, FIXTURE)


class IssueGuardTests(unittest.TestCase):
    def test_codegen_compiles_and_escapes_title(self) -> None:
        src = generate_guard_detector_source(
            issue_id="issue_x1",
            title='Fetch "step" \n times out',
            span_names=["fetch", "parse"],
        )
        compile(src, "<guard>", "exec")  # must be valid Python
        self.assertIn('"id": "guard_issue_x1"', src)

    def test_mint_creates_bound_deterministic_guard(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(
                db_path=db_path,
                title="Fetch step times out",
                source="analysis",
                root_cause="retry budget exhausted",
                status="diagnosed",
            )
            report = mint_guard_for_issue(db_path=db_path, issue_id=issue["id"])

            self.assertTrue(report.deterministic)
            self.assertEqual(report.evaluator_kind, "python")
            self.assertEqual(report.evaluator_id, f"guard_{issue['id']}")

            definition = get_detector(db_path=db_path, detector_id=report.evaluator_id)
            self.assertEqual(definition["kind"], "python")
            self.assertEqual(definition["source"], "guard")
            self.assertEqual(definition["issue_id"], issue["id"])

            refreshed = get_issue(db_path=db_path, issue_id=issue["id"])
            self.assertEqual(refreshed["status"], "guarded")
            self.assertEqual(refreshed["evaluator_id"], report.evaluator_id)

    def test_mint_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(db_path=db_path, title="loop fails", status="diagnosed")
            first = mint_guard_for_issue(db_path=db_path, issue_id=issue["id"])
            second = mint_guard_for_issue(db_path=db_path, issue_id=issue["id"])
            self.assertEqual(first.evaluator_id, second.evaluator_id)

    def test_guard_detects_recurrence_and_raises_issue(self) -> None:
        # Close the loop: the minted guard, run over traces with a recurring failure,
        # raises a fresh Issue that re-enters the spine with source="eval".
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(
                db_path=db_path, title="Fetch step times out", status="diagnosed"
            )
            report = mint_guard_for_issue(db_path=db_path, issue_id=issue["id"])

            before = len(list_issues(db_path=db_path))
            run = run_detector(
                db_path=db_path,
                detector_id=report.evaluator_id,
                corpus={"unit": "event"},
                persist=True,
                raise_issues=True,
                issue_threshold=0.3,
            )
            self.assertTrue(run.raised_issue_id)
            issues = list_issues(db_path=db_path)
            self.assertEqual(len(issues), before + 1)
            raised = get_issue(db_path=db_path, issue_id=run.raised_issue_id)
            self.assertEqual(raised["source"], "eval")

    def test_mint_rejects_missing_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            with self.assertRaises((GuardError, Exception)):
                mint_guard_for_issue(db_path=db_path, issue_id="issue_missing")


if __name__ == "__main__":
    unittest.main()
