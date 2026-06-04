import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.details import get_issue_detail
from kyoko.issues import (
    IssueError,
    create_issue,
    get_issue,
    link_proposal_to_issue,
    list_issues,
    set_issue_diagnosis,
    set_issue_evaluator,
    set_issue_rank,
    update_issue_status,
)
from kyoko.mcp import (
    MCP_DIRECT_APPLY_TOOL_NAMES,
    MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES,
    KyokoMcpServer,
)
from kyoko.proposals import submit_learning_proposal
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"


def _seed(db_path: Path) -> None:
    ingest_source_fixture(db_path, FIXTURE)


def _seed_with_proposal(db_path: Path) -> None:
    _seed(db_path)
    submit_learning_proposal(db_path=db_path, proposal_path=VALID_PROPOSAL, schema_path=SCHEMA)


class IssueModelTests(unittest.TestCase):
    def test_create_resolves_single_profile_and_defaults(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)

            issue = create_issue(db_path=db_path, title="Fetch repeatedly times out")

            self.assertTrue(issue["id"].startswith("issue_"))
            self.assertEqual(issue["profile_id"], "profile_news_research_001")
            self.assertEqual(issue["status"], "open")
            self.assertIsNone(issue["section"])
            self.assertIsNone(issue["severity"])
            self.assertEqual(issue["evidence_refs"], [])
            self.assertEqual(issue["proposal_ids"], [])
            self.assertIsNone(issue["updated_at"])

    def test_create_validates_enums(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)

            with self.assertRaises(IssueError):
                create_issue(db_path=db_path, title="x", section="nope")
            with self.assertRaises(IssueError):
                create_issue(db_path=db_path, title="x", severity="critical")
            with self.assertRaises(IssueError):
                create_issue(db_path=db_path, title="x", status="archived")
            with self.assertRaises(IssueError):
                create_issue(db_path=db_path, title="   ")

    def test_create_counts_in_status(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            create_issue(db_path=db_path, title="One")
            create_issue(db_path=db_path, title="Two")

            status = get_database_status(db_path)
            self.assertEqual(status.counts["issues"], 2)

    def test_list_filters_by_status_and_section(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            create_issue(db_path=db_path, title="open context", section="context")
            harness = create_issue(db_path=db_path, title="open harness", section="harness")
            create_issue(db_path=db_path, title="resolved one", status="resolved")

            all_open = list_issues(db_path=db_path, status="open")
            self.assertEqual({i["title"] for i in all_open}, {"open context", "open harness"})

            harness_only = list_issues(db_path=db_path, section="harness")
            self.assertEqual([i["id"] for i in harness_only], [harness["id"]])

            resolved = list_issues(db_path=db_path, status="resolved")
            self.assertEqual([i["title"] for i in resolved], ["resolved one"])

            with self.assertRaises(IssueError):
                list_issues(db_path=db_path, status="bogus")

    def test_get_issue_roundtrips(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            created = create_issue(
                db_path=db_path,
                title="Timeout",
                body="details",
                section="context",
                category="reliability",
                severity="high",
                affected_span_ids=["span_fetch_timeout_001"],
                affected_agent_identity_ids=["agent_researcher_001"],
            )

            fetched = get_issue(db_path=db_path, issue_id=created["id"])
            self.assertEqual(fetched["title"], "Timeout")
            self.assertEqual(fetched["severity"], "high")
            self.assertEqual(fetched["affected_span_ids"], ["span_fetch_timeout_001"])
            self.assertEqual(fetched["affected_agent_identity_ids"], ["agent_researcher_001"])

            with self.assertRaises(IssueError):
                get_issue(db_path=db_path, issue_id="issue_missing")

    def test_update_status_lifecycle(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(db_path=db_path, title="Lifecycle")

            resolved = update_issue_status(db_path=db_path, issue_id=issue["id"], status="resolved")
            self.assertEqual(resolved["status"], "resolved")
            self.assertIsNotNone(resolved["updated_at"])

            # Lifecycle is not one-way: reopen is allowed.
            reopened = update_issue_status(db_path=db_path, issue_id=issue["id"], status="open")
            self.assertEqual(reopened["status"], "open")

            with self.assertRaises(IssueError):
                update_issue_status(db_path=db_path, issue_id=issue["id"], status="archived")
            with self.assertRaises(IssueError):
                update_issue_status(db_path=db_path, issue_id="issue_missing", status="open")

    def test_detail_resolves_affected_and_links_proposals(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed_with_proposal(db_path)
            issue = create_issue(
                db_path=db_path,
                title="Context timeout",
                section="context",
                affected_span_ids=["span_fetch_timeout_001", "span_does_not_exist"],
                affected_agent_identity_ids=["agent_researcher_001"],
                evidence_refs=[{"entity_type": "run", "entity_id": "run_research_topic_001"}],
                proposal_ids=["proposal_context_timeout_001"],
            )

            detail = get_issue_detail(db_path=db_path, issue_id=issue["id"])
            self.assertEqual(detail["issue"]["id"], issue["id"])

            spans = detail["affected"]["spans"]
            found = {item["entity_id"]: item["found"] for item in spans}
            self.assertTrue(found["span_fetch_timeout_001"])
            self.assertFalse(found["span_does_not_exist"])

            self.assertEqual(detail["summary"]["affected_agent_identities"], 1)
            self.assertEqual(detail["summary"]["evidence_refs"], 1)
            self.assertEqual(detail["summary"]["resolved_evidence_refs"], 1)

            linked = detail["linked_proposals"]
            self.assertTrue(any(entry["proposal"]["id"] == "proposal_context_timeout_001" for entry in linked))
            explicit = [e for e in linked if e["link"] == "explicit"]
            self.assertEqual([e["proposal"]["id"] for e in explicit], ["proposal_context_timeout_001"])

    def test_detail_evidence_payloads_are_not_inlined_on_export(self) -> None:
        # Authored content is not redacted, but resolved evidence stays reference-based:
        # the span row exposes only blob *_ref pointers, never raw payload bytes inline.
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(
                db_path=db_path,
                title="Evidence stays referenced",
                evidence_refs=[{"entity_type": "span", "entity_id": "span_fetch_timeout_001"}],
            )

            detail = get_issue_detail(db_path=db_path, issue_id=issue["id"])
            evidence = detail["evidence"]
            self.assertEqual(len(evidence), 1)
            self.assertTrue(evidence[0]["found"])
            resolved = evidence[0]["resolved"]
            serialized = json.dumps(resolved)
            # No inline payload fields leaked; only blob references.
            self.assertNotIn("input_payload", serialized)
            self.assertNotIn("output_payload", serialized)
            self.assertIn("input_ref", resolved)


class IssueLifecycleTests(unittest.TestCase):
    """The v29 issue-centric spine: provenance, prioritize → diagnose → propose →
    guarded, and the forward-link/guard mutators that Phase 2–4 drive."""

    def test_create_records_source_root_cause_and_rank(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(
                db_path=db_path,
                title="Fetch step times out",
                source="eval",
                root_cause="retry budget exhausted before fetch returns",
                rank=3,
            )
            self.assertEqual(issue["source"], "eval")
            self.assertEqual(issue["rank"], 3)
            self.assertEqual(issue["evaluator_id"], None)
            fetched = get_issue(db_path=db_path, issue_id=issue["id"])
            self.assertEqual(fetched["root_cause"], "retry budget exhausted before fetch returns")
            self.assertEqual(fetched["source"], "eval")

    def test_create_rejects_unknown_source(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            with self.assertRaises(IssueError):
                create_issue(db_path=db_path, title="x", source="telemetry")

    def test_prioritize_diagnose_propose_guard_advances_status(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(db_path=db_path, title="Loop fails")
            self.assertEqual(issue["status"], "open")

            ranked = set_issue_rank(db_path=db_path, issue_id=issue["id"], rank=1)
            self.assertEqual(ranked["status"], "prioritized")
            self.assertEqual(ranked["rank"], 1)

            diagnosed = set_issue_diagnosis(
                db_path=db_path,
                issue_id=issue["id"],
                root_cause="missing tool result handling",
                section="context",
            )
            self.assertEqual(diagnosed["status"], "diagnosed")
            self.assertEqual(diagnosed["section"], "context")
            self.assertEqual(diagnosed["root_cause"], "missing tool result handling")

            linked = link_proposal_to_issue(
                db_path=db_path, issue_id=issue["id"], proposal_id="proposal_abc"
            )
            self.assertEqual(linked["status"], "proposed")
            self.assertEqual(linked["proposal_ids"], ["proposal_abc"])
            self.assertNotIn("proposal_ids_json", linked)

            guarded = set_issue_evaluator(
                db_path=db_path, issue_id=issue["id"], evaluator_id="guard_xyz"
            )
            self.assertEqual(guarded["status"], "guarded")
            self.assertEqual(guarded["evaluator_id"], "guard_xyz")

    def test_link_proposal_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(db_path=db_path, title="dup link")
            link_proposal_to_issue(db_path=db_path, issue_id=issue["id"], proposal_id="p1")
            twice = link_proposal_to_issue(
                db_path=db_path, issue_id=issue["id"], proposal_id="p1"
            )
            self.assertEqual(twice["proposal_ids"], ["p1"])

    def test_diagnosis_requires_root_cause(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            issue = create_issue(db_path=db_path, title="needs cause")
            with self.assertRaises(IssueError):
                set_issue_diagnosis(db_path=db_path, issue_id=issue["id"], root_cause="  ")

    def test_mutators_reject_missing_issue(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            with self.assertRaises(IssueError):
                set_issue_evaluator(db_path=db_path, issue_id="issue_missing", evaluator_id="g")


class IssueMcpSafetyTests(unittest.TestCase):
    def test_create_issue_tool_is_propose_not_apply(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            tools = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            tool_names = {tool["name"] for tool in tools["result"]["tools"]}
            self.assertIn("kyoko_create_issue", tool_names)
            self.assertIn("kyoko_list_issues", tool_names)
            self.assertIn("kyoko_get_issue", tool_names)

            # The write tool must not be an apply/harness-write tool.
            self.assertNotIn("kyoko_create_issue", MCP_DIRECT_APPLY_TOOL_NAMES)
            self.assertNotIn("kyoko_create_issue", MCP_DIRECT_HARNESS_WRITE_TOOL_NAMES)

            safety = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "kyoko_mcp_safety_contract", "arguments": {}},
                }
            )["result"]["structuredContent"]
            self.assertTrue(safety["passed"])
            self.assertEqual(safety["direct_apply_tools_exposed"], [])
            self.assertEqual(safety["direct_harness_write_tools_exposed"], [])

    def test_create_issue_tool_persists_evidence_only(self) -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "kyoko.db"
            _seed(db_path)
            server = KyokoMcpServer(db_path=db_path, schema_path=SCHEMA)

            result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "kyoko_create_issue",
                        "arguments": {
                            "title": "Agent-proposed issue",
                            "severity": "medium",
                            "section": "context",
                        },
                    },
                }
            )["result"]["structuredContent"]["issue"]
            self.assertTrue(result["id"].startswith("issue_"))
            self.assertEqual(result["severity"], "medium")

            # Creating an issue never touches skills/proposals/harness — pure evidence.
            status = get_database_status(db_path)
            self.assertEqual(status.counts["issues"], 1)
            self.assertEqual(status.counts["skills"], 0)
            self.assertEqual(status.counts["learning_proposals"], 0)
            self.assertEqual(status.counts["patch_transactions"], 0)


if __name__ == "__main__":
    unittest.main()
