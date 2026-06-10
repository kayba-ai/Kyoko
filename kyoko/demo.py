from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .apply import ApplyError, apply_context_proposal, list_skills
from .bundled_assets import AssetError, load_bundled_json
from .checks import CheckError, generate_checks_for_proposal
from .eval_detectors import seed_bundled_detectors
from .llm_evals import seed_bundled_llm_evals
from .proposals import ProposalError, list_learning_proposals, submit_learning_proposal_payload
from .replay_adapters import ReplayAdapterError, register_replay_adapter, run_registered_replay_adapter
from .storage import (
    StorageError,
    connect,
    get_database_status,
    ingest_source_payload,
    initialize_database,
    status_to_json,
)


DEMO_ADAPTER_ID = "fixture_replay"
DEMO_PROPOSAL_ID = "proposal_context_timeout_001"


class DemoError(Exception):
    """Raised when the bundled first-run demo cannot complete."""


@dataclass(frozen=True)
class DemoReport:
    db_path: Path
    profile_id: str
    proposal_id: str
    proposal_created: bool
    check_spec_ids: tuple[str, ...]
    check_spec_created_ids: tuple[str, ...]
    check_spec_existing_ids: tuple[str, ...]
    adapter_id: str
    output_dir: Path
    replay_run_id: Optional[str]
    check_run_id: Optional[str]
    check_status: Optional[str]
    promoted_trust_level: Optional[str]
    applied_skill_ids: tuple[str, ...]
    status: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "profile_id": self.profile_id,
            "proposal_id": self.proposal_id,
            "proposal_created": self.proposal_created,
            "check_spec_ids": list(self.check_spec_ids),
            "check_spec_created_ids": list(self.check_spec_created_ids),
            "check_spec_existing_ids": list(self.check_spec_existing_ids),
            "adapter_id": self.adapter_id,
            "output_dir": str(self.output_dir),
            "replay_run_id": self.replay_run_id,
            "check_run_id": self.check_run_id,
            "check_status": self.check_status,
            "promoted_trust_level": self.promoted_trust_level,
            "applied_skill_ids": list(self.applied_skill_ids),
            "status": self.status,
        }


def run_demo_setup(
    *,
    db_path: Path,
    output_dir: Optional[Path] = None,
    run_loop: bool = True,
    apply_context: bool = True,
    root: Optional[Path] = None,
) -> DemoReport:
    """Run the bundled local demo loop against a Kyoko SQLite database."""

    selected_output_dir = output_dir or db_path.parent / ".kyoko" / "demo-replay"

    try:
        source_payload = _demo_source_payload(root)
        proposal_payload = _demo_proposal_payload(root)
    except AssetError as exc:
        raise DemoError(str(exc)) from exc

    try:
        initialize_database(db_path)
        ingest_report = _ingest_demo_source(
            db_path=db_path,
            source_payload=source_payload,
            root=root,
        )
        proposal_created = _ensure_demo_proposal(
            db_path=db_path,
            proposal=proposal_payload,
        )
        check_report = generate_checks_for_proposal(
            db_path=db_path,
            proposal_id=DEMO_PROPOSAL_ID,
        )
        check_spec_ids = tuple(check_report.check_spec_ids + check_report.existing_check_spec_ids)
        if not check_spec_ids:
            raise DemoError(f"demo_check_not_available:{DEMO_PROPOSAL_ID}")

        register_replay_adapter(
            db_path=db_path,
            adapter_id=DEMO_ADAPTER_ID,
            name="Fixture replay",
            command=[sys.executable, "-m", "kyoko.fixture_replay"],
            profile_id=ingest_report.profile_id,
            output_dir=selected_output_dir,
            default_mode="dry_run",
            default_side_effect_mode="network_mocked",
            timeout_seconds=120,
            enabled=True,
            metadata={"demo": True, "fixture": "hermes-news-research-minimal"},
        )

        replay_run_id = None
        check_run_id = None
        check_status = None
        promoted_trust_level = None
        if run_loop:
            replay_report = run_registered_replay_adapter(
                db_path=db_path,
                adapter_id=DEMO_ADAPTER_ID,
                check_spec_id=check_spec_ids[0],
                run_check_after=True,
            )
            replay_run_id = replay_report.replay_run_id
            if replay_report.check_run is None:
                raise DemoError(f"demo_check_not_run:{check_spec_ids[0]}")
            check_run_id = replay_report.check_run.check_run_id
            check_status = replay_report.check_run.status
            promoted_trust_level = replay_report.check_run.promoted_trust_level

        applied_skill_ids: tuple[str, ...] = ()
        if apply_context:
            if not run_loop:
                raise DemoError("demo_apply_requires_run_loop")
            if check_status != "passed":
                raise DemoError(f"demo_apply_requires_passing_check:{check_status}")
            applied_skill_ids = _ensure_demo_skill_applied(db_path)

        _seed_showcase_artifacts(db_path=db_path, applied_skill_ids=applied_skill_ids)
        database_status = status_to_json(get_database_status(db_path))
    except (ApplyError, CheckError, ProposalError, ReplayAdapterError, StorageError) as exc:
        raise DemoError(str(exc)) from exc

    return DemoReport(
        db_path=db_path,
        profile_id=ingest_report.profile_id,
        proposal_id=DEMO_PROPOSAL_ID,
        proposal_created=proposal_created,
        check_spec_ids=check_spec_ids,
        check_spec_created_ids=tuple(check_report.check_spec_ids),
        check_spec_existing_ids=tuple(check_report.existing_check_spec_ids),
        adapter_id=DEMO_ADAPTER_ID,
        output_dir=selected_output_dir,
        replay_run_id=replay_run_id,
        check_run_id=check_run_id,
        check_status=check_status,
        promoted_trust_level=promoted_trust_level,
        applied_skill_ids=applied_skill_ids,
        status=database_status,
    )


def _ensure_demo_proposal(
    *,
    db_path: Path,
    proposal: dict[str, Any],
) -> bool:
    existing = {proposal["id"] for proposal in list_learning_proposals(db_path)}
    if DEMO_PROPOSAL_ID in existing:
        return False

    submit_learning_proposal_payload(
        db_path=db_path,
        proposal=proposal,
        schema_path=None,
    )
    return True


def _ensure_demo_skill_applied(db_path: Path) -> tuple[str, ...]:
    existing = _skill_ids_for_demo_proposal(db_path)
    if existing:
        return existing

    report = apply_context_proposal(db_path=db_path, proposal_id=DEMO_PROPOSAL_ID)
    return tuple(report.applied_skill_ids)


def _skill_ids_for_demo_proposal(db_path: Path) -> tuple[str, ...]:
    skills = list_skills(db_path)
    return tuple(
        str(skill["id"])
        for skill in skills
        if skill.get("proposal_id") == DEMO_PROPOSAL_ID
    )


def _demo_source_payload(root: Optional[Path]) -> dict[str, Any]:
    if root is not None:
        source_fixture = root / "docs/fixtures/source-events/hermes-news-research-minimal.json"
        _require_file(source_fixture)
        return _showcase_source_payload(_load_json_file(source_fixture))
    return _showcase_source_payload(load_bundled_json("source-events/hermes-news-research-minimal.json"))


def _demo_proposal_payload(root: Optional[Path]) -> dict[str, Any]:
    if root is not None:
        proposal_fixture = root / "docs/fixtures/learning-proposals/valid-context-proposal.json"
        _require_file(proposal_fixture)
        return _load_json_file(proposal_fixture)
    return load_bundled_json("learning-proposals/valid-context-proposal.json")


def _ingest_demo_source(
    *,
    db_path: Path,
    source_payload: dict[str, Any],
    root: Optional[Path],
):
    return ingest_source_payload(
        db_path=db_path,
        fixture=source_payload,
        source_label="bundled:source-events/hermes-news-research-minimal.json",
    )


def _showcase_source_payload(fixture: dict[str, Any]) -> dict[str, Any]:
    """Return the first-run fixture expanded into a dashboard-ready story."""

    payload = json.loads(json.dumps(fixture))
    payload["name"] = "kyoko-first-run-showcase"
    payload["description"] = (
        "A richer local demo corpus: repeated agent failures, evidence spans, "
        "handoffs, and after-fix traces for the first-run dashboard."
    )
    profile_id = "profile_news_research_001"
    source_id = "source_hermes_001"

    _append_once(
        payload["agent_identities"],
        {
            "id": "agent_verifier_001",
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": "hermes-profile-verifier",
            "name": "verifier",
            "kind": "hermes_profile",
            "role": "grounding and handoff QA",
            "model": "gpt-4o-mini",
            "workspace_path": "/tmp/kyoko-fixtures/news-research",
            "metadata_json": {},
        },
    )
    _append_once(
        payload["workflow_nodes"],
        {
            "id": "node_verifier_001",
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": "node-verifier",
            "agent_identity_id": "agent_verifier_001",
            "kind": "agent",
            "name": "Verifier",
            "metadata_json": {},
        },
    )

    scenarios = [
        ("002", "researcher", "succeeded", "fetch_source", "failed", "Source fetch timed out again and no retry was attempted.", "timeout", 0, "2026-06-01T09:10:00Z"),
        ("003", "writer", "succeeded", "draft_answer", "failed", "Draft cited a vendor benchmark that was not present in retrieved evidence.", "hallucinated_citation", 0, "2026-06-01T14:25:00Z"),
        ("004", "researcher", "succeeded", "fetch_source", "failed", "Researcher moved to handoff with two missing source summaries.", "timeout", 0, "2026-06-02T10:05:00Z"),
        ("005", "writer", "succeeded", "handoff_payload", "failed", "Writer omitted required source_status and confidence fields in the handoff.", "handoff_schema", 0, "2026-06-02T16:40:00Z"),
        ("006", "verifier", "succeeded", "verify_grounding", "failed", "Verifier caught an unsupported claim before publication.", "unsupported_claim", 0, "2026-06-03T11:30:00Z"),
        ("007", "researcher", "succeeded", "fetch_source", "succeeded", "Retry guidance recovered the source after one transient timeout.", "timeout_recovered", 1, "2026-06-04T09:55:00Z"),
        ("008", "writer", "succeeded", "draft_answer", "failed", "Concise summary drifted into speculation about market impact.", "speculation", 0, "2026-06-04T15:20:00Z"),
        ("009", "researcher", "succeeded", "fetch_source", "succeeded", "Research completed with complete evidence and clean handoff.", "clean", 0, "2026-06-05T12:05:00Z"),
        ("010", "writer", "succeeded", "handoff_payload", "failed", "Handoff payload included evidence but missed the final citation map.", "handoff_schema", 0, "2026-06-05T17:15:00Z"),
        ("011", "verifier", "succeeded", "verify_grounding", "succeeded", "Verifier approved all claims against cited evidence.", "clean", 0, "2026-06-06T10:45:00Z"),
        ("012", "researcher", "succeeded", "fetch_source", "succeeded", "Researcher retried timeout once and marked source complete.", "timeout_recovered", 1, "2026-06-07T09:40:00Z"),
        ("013", "writer", "succeeded", "draft_answer", "succeeded", "Writer produced a grounded summary with complete citation map.", "clean", 0, "2026-06-07T13:50:00Z"),
    ]
    for index, agent, run_status, failing_name, span_status, summary, category, retry_count, started_at in scenarios:
        _append_showcase_run(
            payload=payload,
            index=index,
            agent=agent,
            run_status=run_status,
            evidence_span_name=failing_name,
            evidence_span_status=span_status,
            summary=summary,
            category=category,
            retry_count=retry_count,
            started_at=started_at,
        )
    return payload


def _append_showcase_run(
    *,
    payload: dict[str, Any],
    index: str,
    agent: str,
    run_status: str,
    evidence_span_name: str,
    evidence_span_status: str,
    summary: str,
    category: str,
    retry_count: int,
    started_at: str,
) -> None:
    profile_id = "profile_news_research_001"
    source_id = "source_hermes_001"
    agent_id = f"agent_{agent}_001"
    node_id = f"node_{agent}_001"
    task_id = f"task_showcase_{index}"
    attempt_id = f"attempt_showcase_{index}"
    run_id = f"run_showcase_{index}"
    root_span_id = f"span_showcase_root_{index}"
    llm_span_id = f"span_showcase_llm_{index}"
    evidence_span_id = f"span_showcase_evidence_{index}"
    handoff_id = f"handoff_showcase_{index}"
    minute = int(index)
    ended_at = started_at.replace(":00Z", ":45Z")

    _append_once(
        payload["tasks"],
        {
            "id": task_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "queue_id": "queue_news_board_001",
            "external_id": f"hermes-task-{index}",
            "title": f"Prepare grounded AI infrastructure brief #{index}",
            "body_ref": None,
            "body_payload": {
                "content": f"Investigate the story, cite every claim, and hand off only complete evidence. Scenario: {category}.",
                "media_type": "text/plain",
            },
            "status": "done",
            "assignee_agent_identity_id": agent_id,
            "created_by_agent_identity_id": "agent_writer_001",
            "priority": "high" if category in {"hallucinated_citation", "handoff_schema"} else "normal",
            "workspace_kind": "repo",
            "workspace_path": "/tmp/kyoko-fixtures/news-research",
            "created_at": started_at,
            "started_at": started_at,
            "completed_at": ended_at,
            "metadata_json": {"demo_category": category},
        },
    )
    _append_once(
        payload["task_attempts"],
        {
            "id": attempt_id,
            "task_id": task_id,
            "run_id": run_id,
            "agent_identity_id": agent_id,
            "status": "done",
            "outcome": "completed_with_issue" if evidence_span_status != "succeeded" else "completed",
            "claim_token_hash": f"fixture-token-{index}",
            "worker_pid": 12000 + minute,
            "started_at": started_at,
            "ended_at": ended_at,
            "last_heartbeat_at": ended_at,
            "summary_ref": None,
            "summary_payload": {"content": summary, "media_type": "text/plain"},
            "metadata_json": {"demo_category": category},
            "error_ref": None,
        },
    )
    _append_once(
        payload["runs"],
        {
            "id": run_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "external_id": f"hermes-run-{index}",
            "root_span_id": root_span_id,
            "agent_identity_id": agent_id,
            "task_attempt_id": attempt_id,
            "status": run_status,
            "started_at": started_at,
            "ended_at": ended_at,
            "input_ref": None,
            "input_payload": {
                "content": {
                    "goal": "Create a grounded, citation-backed brief.",
                    "scenario": category,
                },
                "media_type": "application/json",
            },
            "output_ref": None,
            "output_payload": {"content": {"summary": summary}, "media_type": "application/json"},
            "summary": summary,
            "metadata_json": {"demo_category": category},
        },
    )
    span_base = {
        "run_id": run_id,
        "source_id": source_id,
        "workflow_node_id": node_id,
        "agent_identity_id": agent_id,
    }
    _append_once(
        payload["spans"],
        {
            **span_base,
            "id": root_span_id,
            "external_id": f"root-{index}",
            "parent_span_id": None,
            "kind": "agent",
            "name": f"{agent} task",
            "status": run_status,
            "started_at": started_at,
            "ended_at": ended_at,
            "input_ref": None,
            "output_ref": None,
            "usage_json": {},
            "attributes_json": {"demo.category": category},
            "raw_ref": None,
        },
    )
    _append_once(
        payload["spans"],
        {
            **span_base,
            "id": llm_span_id,
            "external_id": f"llm-{index}",
            "parent_span_id": root_span_id,
            "kind": "llm",
            "name": "reason_about_evidence",
            "status": "succeeded",
            "started_at": started_at,
            "ended_at": ended_at,
            "input_ref": None,
            "output_ref": None,
            "output_payload": {
                "content": f"Evidence analysis for scenario {category}. {summary}",
                "media_type": "text/plain",
            },
            "usage_json": {"input_tokens": 1800 + minute * 37, "output_tokens": 420 + minute * 19},
            "attributes_json": {"model": "gpt-4o-mini", "demo.category": category},
            "raw_ref": None,
        },
    )
    _append_once(
        payload["spans"],
        {
            **span_base,
            "id": evidence_span_id,
            "external_id": f"evidence-{index}",
            "parent_span_id": root_span_id,
            "kind": "tool" if evidence_span_name != "draft_answer" else "llm",
            "name": evidence_span_name,
            "status": evidence_span_status,
            "started_at": started_at,
            "ended_at": ended_at,
            "input_ref": None,
            "output_ref": None,
            "output_payload": {
                "content": {
                    "category": category,
                    "retry_count": retry_count,
                    "finding": summary,
                },
                "media_type": "application/json",
            },
            "usage_json": {"input_tokens": 900, "output_tokens": 180} if evidence_span_name == "draft_answer" else {},
            "attributes_json": {
                "demo.category": category,
                "retry_count": retry_count,
                "error_type": category if evidence_span_status != "succeeded" else None,
                "model": "gpt-4o-mini",
            },
            "raw_ref": None,
        },
    )
    _append_once(
        payload["handoffs"],
        {
            "id": handoff_id,
            "profile_id": profile_id,
            "source_id": source_id,
            "from_agent_identity_id": agent_id,
            "to_agent_identity_id": "agent_writer_001" if agent != "writer" else "agent_verifier_001",
            "from_workflow_node_id": node_id,
            "to_workflow_node_id": "node_writer_001" if agent != "writer" else "node_verifier_001",
            "from_task_id": task_id,
            "to_task_id": None,
            "run_id": run_id,
            "span_id": evidence_span_id,
            "kind": "agent_handoff",
            "reason_ref": None,
            "reason_payload": {"content": summary, "media_type": "text/plain"},
            "payload_ref": None,
            "payload": {
                "content": {
                    "source_status": "complete" if evidence_span_status == "succeeded" else "incomplete",
                    "failure_category": category,
                    "citation_map_present": category != "handoff_schema",
                },
                "media_type": "application/json",
            },
            "created_at": ended_at,
            "metadata_json": {
                "source_status": "complete" if evidence_span_status == "succeeded" else "incomplete",
                "failure_category": category,
            },
        },
    )
    _append_once(
        payload["timeline_events"],
        {
            "id": f"event_showcase_{index}",
            "profile_id": profile_id,
            "source_id": source_id,
            "entity_type": "span",
            "entity_id": evidence_span_id,
            "kind": "failure_detected" if evidence_span_status != "succeeded" else "clean_run",
            "at": ended_at,
            "agent_identity_id": agent_id,
            "payload_ref": None,
            "payload": {"content": summary, "media_type": "text/plain"},
            "metadata_json": {"category": category},
        },
    )


def _seed_showcase_artifacts(*, db_path: Path, applied_skill_ids: tuple[str, ...]) -> None:
    seed_bundled_detectors(db_path=db_path, profile_id="profile_news_research_001")
    seed_bundled_llm_evals(db_path=db_path, profile_id="profile_news_research_001")
    with connect(db_path) as connection:
        _seed_showcase_issues(connection, applied_skill_ids=applied_skill_ids)
        _seed_showcase_proposals(connection, applied_skill_ids=applied_skill_ids)
        _seed_showcase_checks(connection)
        _seed_showcase_measurements(connection)
        _seed_showcase_activity(connection)


def _seed_showcase_issues(connection: Any, *, applied_skill_ids: tuple[str, ...]) -> None:
    now = "2026-06-08T18:00:00Z"
    applied_id = applied_skill_ids[0] if applied_skill_ids else "skill_proposal_context_timeout_001_1"
    connection.execute(
        """
        UPDATE skills
        SET status = 'guarded',
            category = 'Reliability',
            severity = 'medium',
            body = ?,
            root_cause = ?,
            recurrence_count = 4,
            proposal_ids_json = ?,
            evaluator_id = 'failed_span',
            applied_at = COALESCE(applied_at, ?),
            recurrence_count_at_apply = 3,
            source = 'analysis',
            updated_at = ?
        WHERE id = ?
        """,
        (
            "Transient source timeouts repeatedly produced incomplete evidence handoffs.",
            "The researcher lacked explicit retry and incomplete-evidence handoff rules.",
            _json(["proposal_context_timeout_001"]),
            now,
            now,
            applied_id,
        ),
    )
    issues = [
        {
            "id": "issue_citation_grounding_001",
            "issue": "Writer cites claims that are not present in retrieved evidence",
            "body": "Several briefs include vendor benchmark claims without a matching retrieved source.",
            "section": "context",
            "category": "Grounding",
            "severity": "high",
            "status": "accepted",
            "root_cause": "The writer prompt asks for a confident synthesis but does not require claim-by-claim citation mapping.",
            "rank": 1,
            "recurrence_count": 3,
            "affected_span_ids_json": _json(["span_showcase_evidence_003", "span_showcase_evidence_008"]),
            "proposal_ids_json": _json(["proposal_citation_grounding_001"]),
            "signature": "demo:citation-grounding",
        },
        {
            "id": "issue_handoff_schema_001",
            "issue": "Handoffs omit fields downstream agents rely on",
            "body": "Writer handoffs sometimes miss source_status, confidence, or citation_map fields.",
            "section": "harness",
            "category": "Handoff Quality",
            "severity": "medium",
            "status": "proposed",
            "root_cause": "The handoff contract is implicit; no harness check enforces required fields.",
            "rank": 2,
            "recurrence_count": 2,
            "affected_span_ids_json": _json(["span_showcase_evidence_005", "span_showcase_evidence_010"]),
            "proposal_ids_json": _json(["proposal_handoff_schema_001"]),
            "signature": "demo:handoff-schema",
        },
        {
            "id": "issue_speculation_001",
            "issue": "Summaries drift into market speculation when evidence is thin",
            "body": "When sources are incomplete, writer output adds unsupported market-impact language.",
            "section": "context",
            "category": "Answer Quality",
            "severity": "low",
            "status": "open",
            "root_cause": None,
            "rank": 4,
            "recurrence_count": 1,
            "affected_span_ids_json": _json(["span_showcase_evidence_008"]),
            "proposal_ids_json": _json([]),
            "signature": "demo:speculation",
        },
        {
            "id": "issue_empty_llm_output_001",
            "issue": "Verifier occasionally returns an empty rationale",
            "body": "A prior analyzer candidate flagged empty verifier rationale, but evidence was too weak.",
            "section": "context",
            "category": "Observability",
            "severity": "low",
            "status": "dismissed",
            "root_cause": "Single noisy sample from a cancelled local run.",
            "rank": 5,
            "recurrence_count": 1,
            "affected_span_ids_json": _json([]),
            "proposal_ids_json": _json(["proposal_empty_verifier_rejected_001"]),
            "signature": "demo:empty-verifier",
        },
    ]
    for issue in issues:
        connection.execute(
            """
            INSERT INTO skills (
              id, profile_id, issue, body, section, category, severity, status,
              keywords_json, occurrences_json, helpful_count, harmful_count,
              neutral_count, used_count, active, human_locked, source,
              root_cause, evidence_refs_json, affected_agent_identity_ids_json,
              affected_workflow_node_ids_json, affected_task_ids_json,
              affected_span_ids_json, proposal_ids_json, signature,
              recurrence_count, auto_fix_attempts, autonomy_blocked,
              created_at, updated_at, rank
            )
            VALUES (?, 'profile_news_research_001', ?, ?, ?, ?, ?, ?, '[]', '[]',
                    0, 0, 0, 0, 0, 0, 'analysis', ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    0, 0, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              issue=excluded.issue, body=excluded.body, section=excluded.section,
              category=excluded.category, severity=excluded.severity,
              status=excluded.status, root_cause=excluded.root_cause,
              evidence_refs_json=excluded.evidence_refs_json,
              affected_span_ids_json=excluded.affected_span_ids_json,
              proposal_ids_json=excluded.proposal_ids_json,
              recurrence_count=excluded.recurrence_count,
              rank=excluded.rank,
              updated_at=excluded.updated_at
            """,
            (
                issue["id"],
                issue["issue"],
                issue["body"],
                issue["section"],
                issue["category"],
                issue["severity"],
                issue["status"],
                issue["root_cause"],
                _json(
                    [
                        {"entity_type": "span", "entity_id": span_id, "role": "failure"}
                        for span_id in json.loads(issue["affected_span_ids_json"])
                    ]
                ),
                _json(["agent_writer_001"]),
                _json(["node_writer_001"]),
                _json([]),
                issue["affected_span_ids_json"],
                issue["proposal_ids_json"],
                issue["signature"],
                issue["recurrence_count"],
                now,
                now,
                issue["rank"],
            ),
        )


def _seed_showcase_proposals(connection: Any, *, applied_skill_ids: tuple[str, ...]) -> None:
    for proposal in _showcase_proposals():
        connection.execute(
            """
            INSERT INTO learning_proposals (
              id, schema_version, profile_id, producer_json, state, section,
              title, summary, confidence, evidence_refs_json, problem_json,
              insight, proposed_changes_json, gate_expectations_json,
              validation_errors_json, issue_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              state=excluded.state, title=excluded.title, summary=excluded.summary,
              confidence=excluded.confidence, evidence_refs_json=excluded.evidence_refs_json,
              problem_json=excluded.problem_json, insight=excluded.insight,
              proposed_changes_json=excluded.proposed_changes_json,
              gate_expectations_json=excluded.gate_expectations_json,
              issue_id=excluded.issue_id, updated_at=excluded.updated_at
            """,
            (
                proposal["id"],
                "kyoko.learning_proposal.v1",
                "profile_news_research_001",
                _json(proposal["producer"]),
                proposal["state"],
                proposal["section"],
                proposal["title"],
                proposal["summary"],
                proposal["confidence"],
                _json(proposal["evidence_refs"]),
                _json(proposal["problem"]),
                proposal["insight"],
                _json(proposal["proposed_changes"]),
                _json(proposal["gate_expectations"]),
                proposal["issue_id"],
                proposal["created_at"],
                proposal["updated_at"],
            ),
        )
    # The demo-loop proposal can only link to its skill once apply_context has
    # created it; without the loop the skill row does not exist and the FK fails.
    if applied_skill_ids:
        connection.execute(
            "UPDATE learning_proposals SET issue_id = ? WHERE id = ? AND issue_id IS NULL",
            (applied_skill_ids[0], "proposal_context_timeout_001"),
        )


def _showcase_proposals() -> list[dict[str, Any]]:
    producer = {
        "kind": "operator_agent",
        "name": "codex",
        "agent_identity_id": "agent_operator_codex_001",
        "session_id": "codex_demo_showcase",
    }
    return [
        {
            "id": "proposal_citation_grounding_001",
            "issue_id": "issue_citation_grounding_001",
            "state": "pending",
            "section": "context",
            "title": "Require claim-by-claim citation mapping",
            "summary": "Writer should only publish claims that map to retrieved evidence IDs.",
            "confidence": 0.88,
            "producer": producer,
            "evidence_refs": [{"entity_type": "span", "entity_id": "span_showcase_evidence_003", "role": "failure"}],
            "problem": {"issue": "Unsupported claims reached the draft.", "severity": "high"},
            "insight": "Add a citation-map checklist before final handoff.",
            "proposed_changes": [
                {
                    "type": "skillbook_update",
                    "operation": "create",
                    "section": "context",
                    "issue": "Writer cites unsupported claims.",
                    "insight": "Before handoff, map every factual claim to a retrieved evidence id; omit claims without a source.",
                    "keywords": ["citation", "grounding", "claim map"],
                    "occurrence_refs": [{"entity_type": "span", "entity_id": "span_showcase_evidence_003", "role": "failure"}],
                }
            ],
            "gate_expectations": {"requires_replay": True, "requires_human_review": True},
            "created_at": "2026-06-08T15:30:00Z",
            "updated_at": "2026-06-08T15:30:00Z",
        },
        {
            "id": "proposal_handoff_schema_001",
            "issue_id": "issue_handoff_schema_001",
            "state": "pending",
            "section": "harness",
            "title": "Add a handoff schema regression check",
            "summary": "Generate a harness assertion for source_status, confidence, and citation_map.",
            "confidence": 0.79,
            "producer": producer,
            "evidence_refs": [{"entity_type": "span", "entity_id": "span_showcase_evidence_010", "role": "failure"}],
            "problem": {"issue": "Downstream agents receive partial handoffs.", "severity": "medium"},
            "insight": "Make the handoff schema explicit and test it in replay.",
            "proposed_changes": [
                {
                    "type": "harness_patch",
                    "operation": "create",
                    "target_path": "checks/handoff_schema.py",
                    "summary": "Assert required handoff fields before writer/verifier handoff.",
                }
            ],
            "gate_expectations": {"requires_replay": True, "requires_check_level": "L1_repeated"},
            "created_at": "2026-06-08T16:10:00Z",
            "updated_at": "2026-06-08T16:10:00Z",
        },
        {
            "id": "proposal_empty_verifier_rejected_001",
            "issue_id": "issue_empty_llm_output_001",
            "state": "failed",
            "section": "context",
            "title": "Force verifier to always produce a rationale",
            "summary": "Rejected because the analyzer only found one cancelled local run.",
            "confidence": 0.31,
            "producer": producer,
            "evidence_refs": [],
            "problem": {"issue": "Verifier rationale was empty once.", "severity": "low"},
            "insight": "Insufficient recurrence; keep observing.",
            "proposed_changes": [],
            "gate_expectations": {"requires_human_review": True},
            "created_at": "2026-06-08T13:05:00Z",
            "updated_at": "2026-06-08T13:20:00Z",
        },
    ]


def _seed_showcase_checks(connection: Any) -> None:
    specs = [
        ("check_citation_grounding_001", "proposal_citation_grounding_001", "claim map rejects unsupported citations", "L1_repeated"),
        ("check_handoff_schema_001", "proposal_handoff_schema_001", "handoff includes source_status confidence citation_map", "L0_generated"),
    ]
    for check_id, proposal_id, name, trust in specs:
        connection.execute(
            """
            INSERT INTO check_specs (
              id, profile_id, proposal_id, name, check_type, trust_level,
              side_effect_mode, target_json, definition_json, status,
              created_at, updated_at
            )
            VALUES (?, 'profile_news_research_001', ?, ?, 'deterministic_assertion',
                    ?, 'network_mocked', ?, ?, 'active', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, trust_level=excluded.trust_level,
              definition_json=excluded.definition_json, updated_at=excluded.updated_at
            """,
            (
                check_id,
                proposal_id,
                name,
                trust,
                _json({"proposal_id": proposal_id}),
                _json({"assertions": [{"type": "target_status_not_failed"}], "expect": name}),
                "2026-06-08T16:20:00Z",
                "2026-06-08T16:20:00Z",
            ),
        )
    runs = [
        ("replay_citation_grounding_001", "proposal_citation_grounding_001", "check_citation_grounding_001", "passed", "run_showcase_013"),
        ("replay_handoff_schema_001", "proposal_handoff_schema_001", "check_handoff_schema_001", "failed", "run_showcase_010"),
    ]
    for replay_id, proposal_id, check_id, status, source_run_id in runs:
        connection.execute(
            """
            INSERT INTO replay_runs (
              id, profile_id, proposal_id, check_spec_id, source_run_id,
              task_attempt_id, mode, side_effect_mode, status, started_at,
              ended_at, input_ref, output_ref, result_json, artifact_refs_json,
              created_at, updated_at
            )
            VALUES (?, 'profile_news_research_001', ?, ?, ?, NULL, 'dry_run',
                    'network_mocked', ?, ?, ?, NULL, ?, ?, '[]', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status=excluded.status, result_json=excluded.result_json,
              output_ref=excluded.output_ref, updated_at=excluded.updated_at
            """,
            (
                replay_id,
                proposal_id,
                check_id,
                source_run_id,
                status,
                "2026-06-08T16:25:00Z",
                "2026-06-08T16:26:00Z",
                source_run_id,
                _json({"status": status, "demo": True}),
                "2026-06-08T16:25:00Z",
                "2026-06-08T16:26:00Z",
            ),
        )
        connection.execute(
            """
            INSERT INTO check_runs (
              id, profile_id, check_spec_id, proposal_id, replay_run_id,
              status, started_at, ended_at, result_json, artifact_refs_json,
              created_at, updated_at
            )
            VALUES (?, 'profile_news_research_001', ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              status=excluded.status, result_json=excluded.result_json,
              updated_at=excluded.updated_at
            """,
            (
                f"checkrun_{check_id}_demo",
                check_id,
                proposal_id,
                replay_id,
                status,
                "2026-06-08T16:26:00Z",
                "2026-06-08T16:27:00Z",
                _json({"status": status, "summary": "Demo regression evidence"}),
                "2026-06-08T16:26:00Z",
                "2026-06-08T16:27:00Z",
            ),
        )


def _seed_showcase_measurements(connection: Any) -> None:
    run_ids = [f"run_showcase_{i:03d}" for i in range(2, 14)]
    scored = {
        "goal_accuracy": [True, False, False, False, False, False, True, True, False, True, True, True],
        "user_disagreement": [False, True, True, False, False, True, False, False, True, False, False, False],
        "hallucination": [0.08, 0.82, 0.34, 0.21, 0.68, 0.49, 0.09, 0.06, 0.55, 0.05, 0.04, 0.03],
    }
    for definition_id, values in scored.items():
        _upsert_showcase_measurement(
            connection,
            definition_id=definition_id,
            unit_type="run",
            unit_refs=run_ids,
            values=values,
        )

    event_refs = [f"span_showcase_evidence_{i:03d}" for i in range(2, 14)]
    _upsert_showcase_measurement(
        connection,
        definition_id="failed_span",
        unit_type="event",
        unit_refs=event_refs,
        values=[True, True, True, True, True, False, True, False, True, False, False, False],
    )
    _upsert_showcase_measurement(
        connection,
        definition_id="empty_llm_output",
        unit_type="event",
        unit_refs=[f"span_showcase_llm_{i:03d}" for i in range(2, 14)],
        values=[False, False, False, False, False, False, False, False, False, False, False, False],
    )


def _upsert_showcase_measurement(
    connection: Any,
    *,
    definition_id: str,
    unit_type: str,
    unit_refs: list[str],
    values: list[Any],
) -> None:
    run_id = f"evalrun_demo_{definition_id}"
    definition = connection.execute(
        "SELECT * FROM eval_definitions WHERE id = ?", (definition_id,)
    ).fetchone()
    direction = definition["direction"]
    connection.execute("DELETE FROM eval_measure_results WHERE eval_run_id = ?", (run_id,))
    connection.execute(
        """
        INSERT INTO eval_measure_runs (
          id, profile_id, eval_definition_id, kind, definition_snapshot_json,
          corpus_json, unit_type, status, unit_total, unit_scored, unit_skipped,
          aggregate_json, baseline_run_id, started_at, ended_at, created_at, updated_at
        )
        VALUES (?, 'profile_news_research_001', ?, ?, ?, ?, ?, 'complete',
                ?, ?, 0, ?, NULL, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          unit_type=excluded.unit_type, unit_total=excluded.unit_total,
          unit_scored=excluded.unit_scored, aggregate_json=excluded.aggregate_json,
          updated_at=excluded.updated_at
        """,
        (
            run_id,
            definition_id,
            definition["kind"],
            _json(dict(definition)),
            _json({"unit": unit_type, "limit": 50}),
            unit_type,
            len(values),
            len(values),
            _json(_aggregate_demo_values(values, direction)),
            "2026-06-08T17:00:00Z",
            "2026-06-08T17:02:00Z",
            "2026-06-08T17:00:00Z",
            "2026-06-08T17:02:00Z",
        ),
    )
    for idx, value in enumerate(values):
        is_bool = isinstance(value, bool)
        connection.execute(
            """
            INSERT INTO eval_measure_results (
              id, eval_run_id, profile_id, unit_type, unit_ref, status,
              score_numeric, score_bool, reasoning, degraded, detail_json, created_at
            )
            VALUES (?, ?, 'profile_news_research_001', ?, ?, 'scored',
                    ?, ?, ?, 0, ?, ?)
            """,
            (
                f"evalres_demo_{definition_id}_{idx + 1:02d}",
                run_id,
                unit_type,
                unit_refs[idx],
                None if is_bool else float(value),
                int(value) if is_bool else None,
                _demo_reasoning(definition_id, value),
                _json({"demo": True, "score": value}),
                "2026-06-08T17:02:00Z",
            ),
        )


def _seed_showcase_activity(connection: Any) -> None:
    events = [
        ("event_demo_autonomy_001", "skill", "issue_citation_grounding_001", "autonomy_decision", "gate1_allowed", "recurrence threshold met for high-severity grounding issue"),
        ("event_demo_autonomy_002", "learning_proposal", "proposal_citation_grounding_001", "autonomy_gated", "proposal_authored", "context fix drafted from accepted issue"),
        ("event_demo_autonomy_003", "check_run", "checkrun_check_citation_grounding_001_demo", "autonomy_applied", "check_passed", "citation grounding replay passed"),
        ("event_demo_autonomy_004", "skill", "skill_proposal_context_timeout_001_1", "autonomy_decision", "guard_monitor_clean", "no timeout regression since apply"),
    ]
    for event_id, entity_type, entity_id, kind, action, note in events:
        connection.execute(
            """
            INSERT INTO timeline_events (
              id, profile_id, source_id, entity_type, entity_id, kind, at,
              agent_identity_id, payload_ref, metadata_json
            )
            VALUES (?, 'profile_news_research_001', 'source_operator_001',
                    ?, ?, ?, ?, 'agent_operator_codex_001', NULL, ?)
            ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, metadata_json=excluded.metadata_json
            """,
            (event_id, entity_type, entity_id, kind, "2026-06-08T17:30:00Z", _json({"action": action, "note": note})),
        )
    for seq, (direction, method, tool, params, result, duration) in enumerate(
        [
            ("client_to_server", "tools/call", "kyoko.list_issues", '{"status":"open"}', '{"issues":4}', 18.4),
            ("server_to_client", "tools/result", "kyoko.list_issues", "{}", '{"ok":true}', 4.2),
            ("client_to_server", "tools/call", "kyoko.propose_fix", '{"issue_id":"issue_citation_grounding_001"}', '{"proposal_id":"proposal_citation_grounding_001"}', 842.0),
            ("client_to_server", "tools/call", "kyoko.run_replay", '{"check_spec_id":"check_citation_grounding_001"}', '{"status":"passed"}', 1180.0),
        ],
        start=1,
    ):
        connection.execute(
            """
            INSERT INTO mcp_log (
              id, profile_id, session_id, seq, direction, method, tool_name,
              params_preview, params_ref, result_preview, result_ref, is_error,
              error_code, duration_ms, client_id, at, metadata_json
            )
            VALUES (?, 'profile_news_research_001', 'demo-mcp-session', ?, ?, ?, ?,
                    ?, NULL, ?, NULL, 0, NULL, ?, 'codex-demo', ?, '{}')
            ON CONFLICT(id) DO UPDATE SET result_preview=excluded.result_preview,
              duration_ms=excluded.duration_ms
            """,
            (
                f"mcp_demo_{seq:03d}",
                seq,
                direction,
                method,
                tool,
                params,
                result,
                duration,
                f"2026-06-08T17:3{seq}:00Z",
            ),
        )


def _aggregate_demo_values(values: list[Any], direction: str) -> dict[str, Any]:
    if all(isinstance(value, bool) for value in values):
        notable = sum(1 for value in values if (value if direction == "true_is_notable" else not value))
        return {"value": notable / len(values), "numerator": notable, "denominator": len(values)}
    nums = [float(value) for value in values]
    return {
        "mean": round(sum(nums) / len(nums), 3),
        "min": min(nums),
        "max": max(nums),
        "value": round(sum(1 for value in nums if value >= 0.5) / len(nums), 3),
        "numerator": sum(1 for value in nums if value >= 0.5),
        "denominator": len(nums),
    }


def _demo_reasoning(definition_id: str, value: Any) -> str:
    if definition_id == "failed_span":
        return "Span status indicates a failed or errored operation." if value else "Span completed successfully."
    if definition_id == "empty_llm_output":
        return "LLM output was empty." if value else "LLM output contained content."
    if definition_id == "hallucination":
        return "Claim grounding is weak." if float(value) >= 0.5 else "Claims are supported by retrieved evidence."
    if definition_id == "goal_accuracy":
        return "Run met the requested outcome." if value else "Run missed part of the requested outcome."
    return "User pushed back on the answer." if value else "No user disagreement detected."


def _append_once(rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    row_id = row.get("id")
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == row_id:
            rows[index] = row
            return
    rows.append(row)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _load_json_file(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise DemoError(f"demo_json_object_required:{path}")
    return payload


def _require_file(path: Path) -> None:
    if not path.exists():
        raise DemoError(f"demo_file_not_found:{path}")
