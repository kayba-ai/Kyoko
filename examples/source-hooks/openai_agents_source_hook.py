"""Example KYOKO_SOURCE_HOOK for OpenAI Agents SDK style traces.

This example is dependency-free. In a real OpenAI Agents app, replace
sample_openai_agents_trace() with tracing output from your run, then keep the
same conversion into Kyoko agent identities, workflow nodes, spans, handoffs,
and timeline events.
"""

from __future__ import annotations

from typing import Any


def collect(context: dict[str, Any]) -> dict[str, Any]:
    trace = sample_openai_agents_trace()
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    planner_agent_id = context["agent_id"]
    researcher_agent_id = "agent_openai_agents_researcher"
    planner_node_id = "node_openai_agents_planner"
    researcher_node_id = "node_openai_agents_researcher"
    run_id = "run_openai_agents_news_example_001"
    root_span_id = "span_openai_agents_planner_001"
    handoff_span_id = "span_openai_agents_handoff_001"
    tool_span_id = "span_openai_agents_web_search_001"

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": "openai-agents-source-hook-example",
        "description": "Example OpenAI Agents style hook output for Kyoko.",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": trace["started_at"],
            "updated_at": trace["ended_at"],
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": "OpenAI Agents source hook example",
                "status": "active",
                "adapter_version": "kyoko.example.openai_agents_source_hook.v0",
                "config_json": {"example": True},
                "capabilities_json": {"runs": True, "spans": True, "handoffs": True},
                "last_seen_at": trace["ended_at"],
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=planner_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name=context["agent_name"],
                role="planner",
                model=trace["planner_model"],
                workspace_path=context["root_path"],
            ),
            _agent(
                agent_id=researcher_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name="researcher",
                role="source researcher",
                model=trace["researcher_model"],
                workspace_path=context["root_path"],
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=planner_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=planner_agent_id,
                name="planner_agent",
            ),
            _node(
                node_id=researcher_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=researcher_agent_id,
                name="researcher_agent",
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
                "external_id": trace["trace_id"],
                "root_span_id": root_span_id,
                "agent_identity_id": planner_agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": trace["started_at"],
                "ended_at": trace["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": trace["input"],
                    "media_type": "text/plain",
                    "kind": "agent_prompt",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "Researcher handoff failed because web_search timed out.",
                    "media_type": "text/plain",
                    "kind": "agent_error",
                },
                "summary": "OpenAI Agents example failed after planner handed off to researcher.",
                "metadata_json": {"trace_id": trace["trace_id"]},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "planner-span-001",
                "parent_span_id": None,
                "workflow_node_id": planner_node_id,
                "agent_identity_id": planner_agent_id,
                "kind": "agent",
                "name": "planner_agent",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:00Z",
                "ended_at": "2026-01-01T00:00:03Z",
                "input_ref": None,
                "input_payload": {"content": trace["input"], "media_type": "text/plain", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {
                    "content": {"handoff_to": "researcher", "task": "find current source"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "span_output",
                },
                "usage_json": {"input_tokens": 96, "output_tokens": 32},
                "attributes_json": {
                    "openai_agents.agent.name": "planner",
                    "gen_ai.request.model": trace["planner_model"],
                },
                "raw_ref": None,
            },
            {
                "id": handoff_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "handoff-span-001",
                "parent_span_id": root_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "handoff",
                "name": "handoff_to_researcher",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:03Z",
                "ended_at": "2026-01-01T00:00:04Z",
                "input_ref": None,
                "input_payload": {
                    "content": {"from": "planner", "to": "researcher", "reason": "source lookup"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_input",
                },
                "output_ref": None,
                "output_payload": {"content": "handoff accepted", "media_type": "text/plain", "kind": "handoff_output"},
                "usage_json": {},
                "attributes_json": {"openai_agents.handoff.to": "researcher"},
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "web-search-span-001",
                "parent_span_id": handoff_span_id,
                "workflow_node_id": researcher_node_id,
                "agent_identity_id": researcher_agent_id,
                "kind": "tool",
                "name": "web_search",
                "status": "failed",
                "started_at": "2026-01-01T00:00:04Z",
                "ended_at": "2026-01-01T00:00:10Z",
                "input_ref": None,
                "input_payload": {
                    "content": {"query": "AI infrastructure funding news"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "web_search timed out after 6 seconds",
                    "media_type": "text/plain",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": "web_search",
                    "error.type": "timeout",
                },
                "raw_ref": None,
                "raw_payload": {
                    "content": trace,
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "raw_trace",
                },
            },
        ],
        "handoffs": [
            {
                "id": "handoff_openai_agents_planner_to_researcher_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "run_id": run_id,
                "from_agent_identity_id": planner_agent_id,
                "to_agent_identity_id": researcher_agent_id,
                "from_workflow_node_id": planner_node_id,
                "to_workflow_node_id": researcher_node_id,
                "from_task_id": None,
                "to_task_id": None,
                "kind": "agent_handoff",
                "span_id": handoff_span_id,
                "reason_ref": None,
                "reason_payload": {
                    "content": "Planner delegated source lookup to researcher.",
                    "media_type": "text/plain",
                    "kind": "handoff_reason",
                },
                "payload_ref": None,
                "payload": {
                    "content": {"from": "planner", "to": "researcher", "trace_id": trace["trace_id"]},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_payload",
                },
                "created_at": "2026-01-01T00:00:03Z",
                "metadata_json": {"handoff": "planner -> researcher"},
            }
        ],
        "timeline_events": [
            {
                "id": "event_openai_agents_web_search_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "span_failed",
                "at": "2026-01-01T00:00:10Z",
                "agent_identity_id": researcher_agent_id,
                "payload_ref": None,
                "payload": {
                    "content": "web_search timed out after 6 seconds",
                    "media_type": "text/plain",
                    "kind": "error_quote",
                },
                "metadata_json": {"error_type": "timeout"},
            }
        ],
    }


def sample_openai_agents_trace() -> dict[str, Any]:
    return {
        "trace_id": "openai-agents-trace-001",
        "input": "Plan and research a current AI infrastructure news brief.",
        "planner_model": "gpt-4.1-mini",
        "researcher_model": "gpt-4.1-mini",
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:10Z",
    }


def _agent(
    *,
    agent_id: str,
    profile_id: str,
    source_id: str,
    name: str,
    role: str,
    model: str,
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
        "model": model,
        "workspace_path": workspace_path,
        "metadata_json": {"framework": "openai-agents"},
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
        "metadata_json": {"framework": "openai-agents"},
    }
