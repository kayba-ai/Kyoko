"""ST1 of the analysis/proposal decoupling: the issue-authoring contract (diagnosis turn)
and the proposal-authoring turn (`propose_for_issue`). These are additive — the existing
proposal-first path is untouched here."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.analyze import (
    AnalyzeError,
    extract_issues_from_output,
    mock_issues_from_bundle,
    mock_proposal_from_issue,
    propose_for_issue,
)
from kyoko.issues import (
    accept_issue,
    get_issue,
    surface_issue,
    validate_issue,
)
from kyoko.operator_prompts import (
    BEGIN_ISSUES_BLOCK,
    END_ISSUES_BLOCK,
    write_diagnosis_prompt_artifacts,
)
from kyoko.proposals import list_learning_proposals, submit_learning_proposal_payload
from kyoko.storage import connect, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
ISSUE_SCHEMA = ROOT / "kyoko/assets/schemas/issue.schema.json"
PROPOSAL_SCHEMA = ROOT / "kyoko/assets/schemas/learning-proposal.schema.json"
PROFILE = "profile_news_research_001"


def _seed(db_path: Path) -> None:
    ingest_source_fixture(db_path, FIXTURE)


def _mock_issue(db_path: Path, out: Path) -> dict:
    report = write_diagnosis_prompt_artifacts(
        db_path=db_path, output_dir=out, profile_id=PROFILE
    )
    return mock_issues_from_bundle(report.bundle)[0]


def _surface(db_path: Path, mi: dict) -> dict:
    surfaced, _ = surface_issue(
        db_path=db_path,
        title=mi["title"],
        body=mi.get("body"),
        section=mi["section"],
        severity=mi.get("severity"),
        root_cause=mi["root_cause"],
        status="diagnosed",
        evidence_refs=mi["evidence_refs"],
        affected_span_ids=mi.get("affected_span_ids"),
        affected_agent_identity_ids=mi.get("affected_agent_identity_ids"),
        source="analysis",
        profile_id=PROFILE,
    )
    return surfaced


class IssueAuthoringSchemaTests(unittest.TestCase):
    def test_schema_validates_a_good_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            mi = _mock_issue(db_path, Path(tmp) / "out")
            with connect(db_path) as connection:
                result = validate_issue(
                    connection=connection,
                    issue={**mi, "schema_version": "kyoko.issue.v1"},
                    schema_path=ISSUE_SCHEMA,
                    require_jsonschema=True,
                )
            self.assertTrue(result.ok, result.errors)

    def test_schema_rejects_missing_required_and_bad_enum(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            base = _mock_issue(db_path, Path(tmp) / "out")
            with connect(db_path) as connection:
                missing_rc = dict(base)
                missing_rc.pop("root_cause")
                self.assertFalse(
                    validate_issue(
                        connection=connection, issue=missing_rc, schema_path=ISSUE_SCHEMA
                    ).ok
                )
                bad_section = {**base, "section": "nonsense"}
                self.assertFalse(
                    validate_issue(
                        connection=connection, issue=bad_section, schema_path=ISSUE_SCHEMA
                    ).ok
                )

    def test_schema_rejects_dangling_evidence_ref(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            base = _mock_issue(db_path, Path(tmp) / "out")
            dangling = {
                **base,
                "evidence_refs": [{"entity_type": "span", "entity_id": "span_nope"}],
            }
            with connect(db_path) as connection:
                result = validate_issue(
                    connection=connection, issue=dangling, schema_path=ISSUE_SCHEMA
                )
            self.assertFalse(result.ok)
            self.assertTrue(any("span_nope" in e for e in result.errors), result.errors)


class ExtractIssuesTests(unittest.TestCase):
    def test_extract_happy(self) -> None:
        block = (
            "preamble\n"
            + BEGIN_ISSUES_BLOCK
            + '\n[{"title": "x"}, {"title": "y"}]\n'
            + END_ISSUES_BLOCK
            + "\ntrailer"
        )
        issues = extract_issues_from_output(block)
        self.assertEqual([i["title"] for i in issues], ["x", "y"])

    def test_extract_rejects_missing_block(self) -> None:
        with self.assertRaises(AnalyzeError):
            extract_issues_from_output("no block here")

    def test_extract_rejects_non_array(self) -> None:
        block = BEGIN_ISSUES_BLOCK + "\n{}\n" + END_ISSUES_BLOCK
        with self.assertRaises(AnalyzeError):
            extract_issues_from_output(block)


class MockSplitTests(unittest.TestCase):
    def test_mock_issues_from_bundle_is_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            mi = _mock_issue(db_path, Path(tmp) / "out")
            self.assertEqual(mi["schema_version"], "kyoko.issue.v1")
            self.assertEqual(mi["section"], "context")
            with connect(db_path) as connection:
                self.assertTrue(
                    validate_issue(
                        connection=connection,
                        issue=mi,
                        schema_path=ISSUE_SCHEMA,
                        require_jsonschema=True,
                    ).ok
                )

    def test_mock_proposal_from_issue_submits(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            mi = _mock_issue(db_path, Path(tmp) / "out")
            surfaced = _surface(db_path, mi)
            proposal = mock_proposal_from_issue(surfaced)
            proposal["issue_id"] = surfaced["id"]
            # Must validate + persist against the real proposal schema.
            submit_learning_proposal_payload(
                db_path=db_path, proposal=proposal, schema_path=PROPOSAL_SCHEMA
            )
            stored = {p["id"]: p for p in list_learning_proposals(db_path=db_path)}
            self.assertIn(proposal["id"], stored)
            self.assertEqual(stored[proposal["id"]]["issue_id"], surfaced["id"])


class ProposeForIssueTests(unittest.TestCase):
    def test_propose_for_issue_mock_authors_and_links(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            out = Path(tmp) / "out"
            _seed(db_path)
            mi = _mock_issue(db_path, out)
            surfaced = _surface(db_path, mi)
            accept_issue(db_path=db_path, issue_id=surfaced["id"])

            report = propose_for_issue(
                db_path=db_path,
                output_dir=out,
                issue_id=surfaced["id"],
                operator="mock",
                schema_path=PROPOSAL_SCHEMA,
            )
            self.assertEqual(report.issue_id, surfaced["id"])
            self.assertTrue(report.proposal_id.startswith("proposal_mock_"))

            # The issue advanced to `proposed` and the proposal carries the issue_id.
            issue_after = get_issue(db_path=db_path, issue_id=surfaced["id"])
            self.assertEqual(issue_after["status"], "proposed")
            self.assertIn(report.proposal_id, issue_after["proposal_ids"])
            stored = {p["id"]: p for p in list_learning_proposals(db_path=db_path)}
            self.assertEqual(stored[report.proposal_id]["issue_id"], surfaced["id"])


class AuthorProposalForIssueTests(unittest.TestCase):
    """The targeted gate-#1 path the dashboard "approve issue" button drives:
    accept one already-surfaced issue and author a proposal for it (no re-diagnosis)."""

    def test_author_proposal_for_issue_accepts_and_authors(self) -> None:
        from kyoko.improve import author_proposal_for_issue

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            mi = _mock_issue(db_path, Path(tmp) / "out")
            surfaced = _surface(db_path, mi)

            report = author_proposal_for_issue(
                db_path=db_path,
                issue_id=surfaced["id"],
                operator="mock",
                run_autonomy_after=False,
            )
            self.assertEqual(len(report.proposal_ids), 1)
            issue_after = get_issue(db_path=db_path, issue_id=surfaced["id"])
            self.assertEqual(issue_after["status"], "proposed")
            self.assertIn(report.proposal_ids[0], issue_after["proposal_ids"])

    def test_issue_propose_job_authors_via_runner(self) -> None:
        from kyoko.analysis_runner import AnalysisJob, execute_analysis_job

        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            mi = _mock_issue(db_path, Path(tmp) / "out")
            surfaced = _surface(db_path, mi)

            job = AnalysisJob(
                analyzer="mock",
                issue_id=surfaced["id"],
                profile_id=PROFILE,
                run_autonomy=False,
            )
            result = execute_analysis_job(db_path, job)
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["scope"], "issue")
            self.assertEqual(result["issue_id"], surfaced["id"])
            self.assertEqual(len(result["proposal_ids"]), 1)
            issue_after = get_issue(db_path=db_path, issue_id=surfaced["id"])
            self.assertEqual(issue_after["status"], "proposed")


if __name__ == "__main__":
    unittest.main()
