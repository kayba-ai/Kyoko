"""Example KYOKO_SOURCE_HOOK for LangGraph-style Python workflows.

This example is dependency-free. In a real LangGraph app, replace
sample_langgraph_events() with events from your graph invocation, callbacks, or
trace export, then keep the same conversion into Kyoko workflow nodes, spans,
handoffs, and timeline events.
"""

from __future__ import annotations

from typing import Any


def collect(context: dict[str, Any]) -> dict[str, Any]:
    events = sample_langgraph_events()
    now = "2026-01-01T00:00:00Z"
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    planner_agent_id = context["agent_id"]
    researcher_agent_id = "agent_langgraph_researcher"
    planner_node_id = "node_langgraph_planner"
    researcher_node_id = "node_langgraph_researcher"
    run_id = "run_langgraph_news_example_001"
    root_span_id = "span_langgraph_plan_001"
    tool_span_id = "span_langgraph_fetch_sources_001"

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": "langgraph-source-hook-example",
        "description": "Example LangGraph-style hook output for Kyoko.",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": now,
            "updated_at": events[-1]["ended_at"],
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": "LangGraph source hook example",
                "status": "active",
                "adapter_version": "kyoko.example.langgraph_source_hook.v0",
                "config_json": {"example": True},
                "capabilities_json": {"runs": True, "spans": True, "handoffs": True},
                "last_seen_at": events[-1]["ended_at"],
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=planner_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name=context["agent_name"],
                role="planner",
                workspace_path=context["root_path"],
            ),
            _agent(
                agent_id=researcher_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name="researcher",
                role="researcher",
                workspace_path=context["root_path"],
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=planner_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=planner_agent_id,
                name="plan_topic",
            ),
            _node(
                node_id=researcher_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=researcher_agent_id,
                name="fetch_sources",
            ),
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "langgraph-thread-001",
                "root_span_id": root_span_id,
                "agent_identity_id": planner_agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": events[0]["started_at"],
                "ended_at": events[-1]["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": "Research current AI infrastructure news and cite sources.",
                    "media_type": "text/plain",
                    "kind": "agent_prompt",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"error": "fetch_sources timed out", "node": "fetch_sources"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "agent_error",
                },
                "summary": "LangGraph example failed when fetch_sources timed out.",
                "metadata_json": {"thread_id": "langgraph-thread-001"},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": events[0]["span_id"],
                "parent_span_id": None,
                "workflow_node_id": planner_node_id,
                "agent_identity_id": planner_agent_id,
                "kind": "agent",
                "name": "plan_topic",
                "status": "succeeded",
                "started_at": events[0]["started_at"],
                "ended_at": events[0]["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": "Research current AI infrastructure news and cite sources.",
                    "media_type": "text/plain",
                    "kind": "span_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"next": "fetch_sources", "topic": "AI infrastructure news"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "span_output",
                },
                "usage_json": {},
                "attributes_json": {"langgraph.node": "plan_topic"},
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": events[1]["span_id"],
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "fetch_sources",
                "status": "failed",
                "started_at": events[1]["started_at"],
                "ended_at": events[1]["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": {"topic": "AI infrastructure news", "source_count": 3},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "fetch_sources timed out after 7 seconds",
                    "media_type": "text/plain",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {
                    "langgraph.node": "fetch_sources",
                    "error.type": "timeout",
                },
                "raw_ref": None,
                "raw_payload": {
                    "content": {"events": events},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "raw_trace",
                    "metadata": {"source": "sample_langgraph_events"},
                },
            },
        ],
        "handoffs": [
            {
                "id": "handoff_langgraph_plan_to_research_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "run_id": run_id,
                "from_agent_identity_id": planner_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": planner_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": None,
                "to_task_id": None,
                "kind": "graph_edge",
                "span_id": tool_span_id,
                "reason_ref": None,
                "reason_payload": {
                    "content": {"edge": "plan_topic -> fetch_sources", "reason": "source lookup"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": "fetch_sources accepted the planned topic before timing out",
                    "media_type": "text/plain",
                    "kind": "handoff_payload",
                },
                "created_at": events[1]["started_at"],
                "metadata_json": {"edge": "plan_topic -> fetch_sources"},
            }
        ],
        "timeline_events": [
            {
                "id": "event_langgraph_fetch_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "span_failed",
                "at": events[1]["ended_at"],
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {
                    "content": "fetch_sources timed out after 7 seconds",
                    "media_type": "text/plain",
                    "kind": "timeline_error",
                },
                "metadata_json": {"error_type": "timeout"},
            }
        ],
    }


def sample_langgraph_events() -> list[dict[str, str]]:
    return [
        {
            "span_id": "langgraph-span-plan-001",
            "started_at": "2026-01-01T00:00:00Z",
            "ended_at": "2026-01-01T00:00:02Z",
        },
        {
            "span_id": "langgraph-span-fetch-001",
            "started_at": "2026-01-01T00:00:02Z",
            "ended_at": "2026-01-01T00:00:09Z",
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
        "model": None,
        "workspace_path": workspace_path,
        "metadata_json": {"framework": "langgraph"},
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
        "kind": "framework_node",
        "name": name,
        "metadata_json": {"framework": "langgraph"},
    }
