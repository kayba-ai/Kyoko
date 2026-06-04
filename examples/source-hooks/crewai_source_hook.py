"""Example KYOKO_SOURCE_HOOK for CrewAI style crews and tasks.

This example is dependency-free. In a real CrewAI app, replace
sample_crewai_events() with task, agent, tool, and delegation events from your
crew kickoff, then keep the same conversion into Kyoko tasks, spans, handoffs,
and timeline events.
"""

from __future__ import annotations

from typing import Any, Optional


def collect(context: dict[str, Any]) -> dict[str, Any]:
    events = sample_crewai_events()
    kickoff = events[0]
    tool_result = events[-1]
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    manager_agent_id = context["agent_id"]
    researcher_agent_id = "agent_crewai_researcher"
    manager_node_id = "node_crewai_manager"
    researcher_node_id = "node_crewai_researcher"
    queue_id = "queue_crewai_news_crew"
    research_task_id = "task_crewai_research_topic_001"
    writing_task_id = "task_crewai_write_brief_001"
    attempt_id = "attempt_crewai_research_topic_001"
    run_id = "run_crewai_news_example_001"
    root_span_id = "span_crewai_kickoff_001"
    delegation_span_id = "span_crewai_delegate_research_001"
    tool_span_id = "span_crewai_fetch_source_timeout_001"

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": "crewai-source-hook-example",
        "description": "Example CrewAI crew/task hook output for Kyoko.",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": kickoff["started_at"],
            "updated_at": tool_result["ended_at"],
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": "CrewAI source hook example",
                "status": "active",
                "adapter_version": "kyoko.example.crewai_source_hook.v0",
                "config_json": {"example": True},
                "capabilities_json": {"runs": True, "spans": True, "tasks": True},
                "last_seen_at": tool_result["ended_at"],
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=manager_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name=context["agent_name"],
                role="crew manager",
                workspace_path=context["root_path"],
            ),
            _agent(
                agent_id=researcher_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name="researcher",
                role="source researcher",
                workspace_path=context["root_path"],
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=manager_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=manager_agent_id,
                name="news_crew_manager",
            ),
            _node(
                node_id=researcher_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=researcher_agent_id,
                name="research_task_agent",
            ),
        ],
        "queues": [
            {
                "id": queue_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "crewai-news-crew",
                "name": "news research crew",
                "kind": "crewai_crew",
                "metadata_json": {"process": "sequential"},
            }
        ],
        "tasks": [
            _task(
                task_id=research_task_id,
                profile_id=profile_id,
                source_id=source_id,
                queue_id=queue_id,
                title="Research current AI infrastructure news",
                assignee_agent_id=researcher_agent_id,
                created_by_agent_id=manager_agent_id,
                workspace_path=context["root_path"],
                started_at="2026-01-01T00:00:02Z",
                completed_at="2026-01-01T00:00:11Z",
                status="failed",
            ),
            _task(
                task_id=writing_task_id,
                profile_id=profile_id,
                source_id=source_id,
                queue_id=queue_id,
                title="Draft sourced news brief",
                assignee_agent_id=manager_agent_id,
                created_by_agent_id=manager_agent_id,
                workspace_path=context["root_path"],
                started_at=None,
                completed_at=None,
                status="blocked",
            ),
        ],
        "task_attempts": [
            {
                "id": attempt_id,
                "task_id": research_task_id,
                "run_id": run_id,
                "agent_identity_id": researcher_agent_id,
                "status": "failed",
                "outcome": "source_fetch_timeout",
                "claim_token_hash": "crewai-example-claim",
                "worker_pid": None,
                "started_at": "2026-01-01T00:00:02Z",
                "ended_at": tool_result["ended_at"],
                "last_heartbeat_at": "2026-01-01T00:00:10Z",
                "summary_ref": None,
                "summary_payload": {
                    "content": "Research task failed because fetch_source timed out.",
                    "media_type": "text/plain",
                    "kind": "task_attempt_summary",
                },
                "metadata_json": {"task": "research"},
                "error_ref": None,
                "error_payload": {
                    "content": tool_result["error"],
                    "media_type": "text/plain",
                    "kind": "task_attempt_error",
                },
            }
        ],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": kickoff["crew_run_id"],
                "root_span_id": root_span_id,
                "agent_identity_id": manager_agent_id,
                "task_attempt_id": attempt_id,
                "status": "failed",
                "started_at": kickoff["started_at"],
                "ended_at": tool_result["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": kickoff["goal"],
                    "media_type": "text/plain",
                    "kind": "crew_goal",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"blocked_task": writing_task_id, "error": tool_result["error"]},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "crew_error",
                },
                "summary": "CrewAI example blocked the writing task after source fetch timeout.",
                "metadata_json": {"crew_run_id": kickoff["crew_run_id"]},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-kickoff-span",
                "parent_span_id": None,
                "workflow_node_id": manager_node_id,
                "agent_identity_id": manager_agent_id,
                "kind": "agent",
                "name": "crew.kickoff",
                "status": "succeeded",
                "started_at": kickoff["started_at"],
                "ended_at": "2026-01-01T00:00:02Z",
                "input_ref": None,
                "input_payload": {"content": kickoff["goal"], "media_type": "text/plain", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {
                    "content": {"next_task": research_task_id},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "span_output",
                },
                "usage_json": {},
                "attributes_json": {"crewai.crew": "news research crew"},
                "raw_ref": None,
            },
            {
                "id": delegation_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-delegate-research",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "handoff",
                "name": "delegate_research_task",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:02Z",
                "ended_at": "2026-01-01T00:00:03Z",
                "input_ref": None,
                "input_payload": {
                    "content": {"from": "manager", "to": "researcher", "task_id": research_task_id},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_input",
                },
                "output_ref": None,
                "output_payload": {"content": "researcher accepted task", "media_type": "text/plain", "kind": "handoff_output"},
                "usage_json": {},
                "attributes_json": {"crewai.task": research_task_id},
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "crewai-fetch-source-tool",
                "parent_span_id": delegation_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_source",
                "status": "failed",
                "started_at": "2026-01-01T00:00:03Z",
                "ended_at": tool_result["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": "AI infrastructure news", "timeout_seconds": 5},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": tool_result["error"],
                    "media_type": "text/plain",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {"error.type": tool_result["error_type"], "crewai.task": research_task_id},
                "raw_ref": None,
                "raw_payload": {
                    "content": {"events": events},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "raw_trace",
                    "metadata": {"source": "sample_crewai_events"},
                },
            },
        ],
        "handoffs": [
            {
                "id": "handoff_crewai_manager_to_researcher_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "from_agent_identity_id": manager_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": manager_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": writing_task_id,
                "to_task_id": research_task_id,
                "run_id": run_id,
                "span_id": delegation_span_id,
                "kind": "task_delegation",
                "reason_ref": None,
                "reason_payload": {"content": "Crew manager delegated source lookup.", "media_type": "text/plain", "kind": "handoff_reason"},
                "payload_ref": None,
                "payload": {
                    "content": {"crew": "news research crew", "task": research_task_id},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_payload",
                },
                "created_at": "2026-01-01T00:00:02Z",
                "metadata_json": {"crewai.process": "sequential"},
            }
        ],
        "timeline_events": [
            {
                "id": "event_crewai_task_delegated_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "handoff",
                "entity_id": "handoff_crewai_manager_to_researcher_001",
                "kind": "task_delegated",
                "at": "2026-01-01T00:00:02Z",
                "agent_identity_id": manager_agent_id,
                "payload_ref": None,
                "payload": {"content": "Research task delegated to researcher.", "media_type": "text/plain", "kind": "timeline_note"},
                "metadata_json": {"task_id": research_task_id},
            },
            {
                "id": "event_crewai_fetch_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "span_failed",
                "at": tool_result["ended_at"],
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {"content": tool_result["error"], "media_type": "text/plain", "kind": "error_quote"},
                "metadata_json": {"error_type": tool_result["error_type"]},
            },
        ],
    }


def sample_crewai_events() -> list[dict[str, Any]]:
    return [
        {
            "kind": "crew_kickoff",
            "crew_run_id": "crewai-run-001",
            "goal": "Research current AI infrastructure news and draft a sourced brief.",
            "started_at": "2026-01-01T00:00:00Z",
        },
        {
            "kind": "tool_result",
            "tool": "fetch_source",
            "status": "failed",
            "error_type": "timeout",
            "error": "fetch_source timed out after 5 seconds",
            "ended_at": "2026-01-01T00:00:11Z",
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
        "external_id": name,
        "name": name,
        "kind": "framework_node",
        "role": role,
        "model": "unknown",
        "workspace_path": workspace_path,
        "metadata_json": {"framework": "crewai"},
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
        "external_id": name,
        "agent_identity_id": agent_id,
        "kind": "agent",
        "name": name,
        "metadata_json": {"framework": "crewai"},
    }


def _task(
    *,
    task_id: str,
    profile_id: str,
    source_id: str,
    queue_id: str,
    title: str,
    assignee_agent_id: str,
    created_by_agent_id: str,
    workspace_path: str,
    started_at: Optional[str],
    completed_at: Optional[str],
    status: str,
) -> dict[str, Any]:
    return {
        "id": task_id,
        "profile_id": profile_id,
        "source_id": source_id,
        "queue_id": queue_id,
        "external_id": task_id.replace("task_", "crewai-task-"),
        "title": title,
        "body_ref": None,
        "body_payload": {"content": title, "media_type": "text/plain", "kind": "task_body"},
        "status": status,
        "assignee_agent_identity_id": assignee_agent_id,
        "created_by_agent_identity_id": created_by_agent_id,
        "priority": "normal",
        "workspace_kind": "repo",
        "workspace_path": workspace_path,
        "created_at": "2026-01-01T00:00:00Z",
        "started_at": started_at,
        "completed_at": completed_at,
        "metadata_json": {"framework": "crewai"},
    }
