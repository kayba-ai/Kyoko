"""Example KYOKO_SOURCE_HOOK for Hermes-style profile/task workflows.

This example is dependency-free. In a real Hermes app, replace
sample_hermes_events() with Hermes task, profile, queue, and run data from the
local board/session source, then keep the same conversion into Kyoko queues,
tasks, task attempts, spans, handoffs, and timeline events.
"""

from __future__ import annotations

from typing import Any


def collect(context: dict[str, Any]) -> dict[str, Any]:
    events = sample_hermes_events()
    task_event = events[0]
    timeout_event = events[-1]
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    researcher_agent_id = context["agent_id"]
    writer_agent_id = "agent_hermes_writer"
    researcher_node_id = "node_hermes_researcher"
    writer_node_id = "node_hermes_writer"
    queue_id = "queue_hermes_news_board"
    task_id = "task_hermes_research_topic_001"
    attempt_id = "attempt_hermes_research_topic_001"
    run_id = "run_hermes_news_example_001"
    root_span_id = "span_hermes_research_root_001"
    tool_span_id = "span_hermes_fetch_source_timeout_001"
    handoff_id = "handoff_hermes_research_to_writer_001"

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": "hermes-source-hook-example",
        "description": "Example Hermes-style source hook output for Kyoko.",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": task_event["created_at"],
            "updated_at": timeout_event["ended_at"],
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": "Hermes source hook example",
                "status": "active",
                "adapter_version": "kyoko.example.hermes_source_hook.v0",
                "config_json": {"example": True, "board": "news"},
                "capabilities_json": {"tasks": True, "handoffs": True, "runs": True},
                "last_seen_at": timeout_event["ended_at"],
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=researcher_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name=context["agent_name"],
                role="source research",
                workspace_path=context["root_path"],
            ),
            _agent(
                agent_id=writer_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name="writer",
                role="article drafting",
                workspace_path=context["root_path"],
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=researcher_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=researcher_agent_id,
                name="Hermes researcher profile",
            ),
            _node(
                node_id=writer_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=writer_agent_id,
                name="Hermes writer profile",
            ),
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "hermes-board-news",
                "name": "news",
                "kind": "hermes_board",
                "metadata_json": {"board": "news"},
            }
        ],
        "tasks": [
            {
                "id": task_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "queue_id": queue_id,
                "external_id": task_event["task_external_id"],
                "title": "Research source coverage for an AI infrastructure story",
                "body_ref": None,
                "body_payload": {
                    "content": task_event["body"],
                    "media_type": "text/plain",
                    "kind": "task_body",
                },
                "status": "done",
                "assignee_agent_identity_id": researcher_agent_id,
                "created_by_agent_identity_id": writer_agent_id,
                "priority": "normal",
                "workspace_kind": "repo",
                "workspace_path": context["root_path"],
                "created_at": task_event["created_at"],
                "started_at": task_event["started_at"],
                "completed_at": timeout_event["ended_at"],
                "metadata_json": {"hermes.status": "done", "source_status": "incomplete"},
            }
        ],
        "task_attempts": [
            {
                "id": attempt_id,
                "task_id": task_id,
                "run_id": run_id,
                "agent_identity_id": researcher_agent_id,
                "status": "done",
                "outcome": "completed_with_incomplete_source",
                "claim_token_hash": "hermes-example-claim",
                "worker_pid": 12345,
                "started_at": task_event["started_at"],
                "ended_at": timeout_event["ended_at"],
                "last_heartbeat_at": "2026-01-01T00:00:09Z",
                "summary_ref": None,
                "summary_payload": {
                    "content": "Research completed, but one source fetch timed out and was not retried.",
                    "media_type": "text/plain",
                    "kind": "task_attempt_summary",
                },
                "metadata_json": {"worker_profile": "researcher"},
                "error_ref": None,
            }
        ],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": task_event["run_external_id"],
                "root_span_id": root_span_id,
                "agent_identity_id": researcher_agent_id,
                "task_attempt_id": attempt_id,
                "status": "succeeded",
                "started_at": task_event["started_at"],
                "ended_at": timeout_event["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": task_event["body"],
                    "media_type": "text/plain",
                    "kind": "run_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"source_status": "incomplete", "timed_out_span": tool_span_id},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "run_output",
                },
                "summary": "Hermes example finished with an incomplete source after a timeout.",
                "metadata_json": {"profile": "researcher"},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "hermes-research-root",
                "parent_span_id": None,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "agent",
                "name": "research topic",
                "status": "succeeded",
                "started_at": task_event["started_at"],
                "ended_at": timeout_event["ended_at"],
                "input_ref": None,
                "input_payload": {"content": task_event["body"], "media_type": "text/plain", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {
                    "content": "Research summary produced with one missing source.",
                    "media_type": "text/plain",
                    "kind": "span_output",
                },
                "usage_json": {},
                "attributes_json": {"hermes.profile": "researcher"},
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "hermes-fetch-source",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": timeout_event["started_at"],
                "ended_at": timeout_event["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": timeout_event["tool_args"],
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": timeout_event["error"],
                    "media_type": "text/plain",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {"error.type": "timeout", "retry_count": 0},
                "raw_ref": None,
                "raw_payload": {
                    "content": {"events": events},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "raw_trace",
                    "metadata": {"source": "sample_hermes_events"},
                },
            },
        ],
        "handoffs": [
            {
                "id": handoff_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "from_agent_identity_id": researcher_agent_id,
                "to_agent_identity_id": writer_agent_id,
                "from_workflow_node_id": researcher_node_id,
                "to_workflow_node_id": writer_node_id,
                "from_task_id": task_id,
                "to_task_id": None,
                "run_id": run_id,
                "span_id": None,
                "kind": "agent_handoff",
                "reason_ref": None,
                "reason_payload": {
                    "content": "Researcher handed incomplete source status back to writer.",
                    "media_type": "text/plain",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": {"source_status": "incomplete", "task_id": task_id},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_payload",
                },
                "created_at": timeout_event["ended_at"],
                "metadata_json": {"source_status": "incomplete"},
            }
        ],
        "timeline_events": [
            {
                "id": "event_hermes_fetch_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "tool_timeout",
                "at": timeout_event["ended_at"],
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {"content": timeout_event["error"], "media_type": "text/plain", "kind": "error_quote"},
                "metadata_json": {"error_type": "timeout"},
            },
            {
                "id": "event_hermes_handoff_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "handoff",
                "entity_id": handoff_id,
                "kind": "handoff_created",
                "at": timeout_event["ended_at"],
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {
                    "content": "Writer received incomplete source status.",
                    "media_type": "text/plain",
                    "kind": "timeline_note",
                },
                "metadata_json": {"source_status": "incomplete"},
            },
        ],
    }


def sample_hermes_events() -> list[dict[str, Any]]:
    return [
        {
            "kind": "task_started",
            "task_external_id": "hermes-task-001",
            "run_external_id": "hermes-run-001",
            "body": "Find source coverage for a breaking AI infrastructure story.",
            "created_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:02Z",
        },
        {
            "kind": "tool_timeout",
            "tool_args": {"url": "https://example.test/news", "timeout_seconds": 4},
            "error": "fetch_source timed out after 4 seconds",
            "started_at": "2026-01-01T00:00:04Z",
            "ended_at": "2026-01-01T00:00:10Z",
        },
    ]


def _agent(
    *,
    agent_id: str,
    profile_id: str,
    source_id: str,
    name: str,
    role: str,
    workspace_path: str,
) -> dict[str, Any]:
    return {
        "id": agent_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": f"hermes-profile-{name}",
        "name": name,
        "kind": "hermes_profile",
        "role": role,
        "model": "unknown",
        "workspace_path": workspace_path,
        "metadata_json": {"framework": "hermes"},
    }


def _node(
    *,
    node_id: str,
    profile_id: str,
    source_id: str,
    agent_id: str,
    name: str,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "external_id": node_id,
        "agent_identity_id": agent_id,
        "kind": "agent",
        "name": name,
        "metadata_json": {"framework": "hermes"},
    }
