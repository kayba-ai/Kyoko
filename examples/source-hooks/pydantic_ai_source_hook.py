"""Example KYOKO_SOURCE_HOOK for Pydantic AI style agent runs.

This example is dependency-free. In a real Pydantic AI app, replace
sample_pydantic_ai_events() with events from your run wrapper, Logfire export,
or OpenTelemetry export, then keep the same conversion into Kyoko runs, spans,
and timeline events.
"""

from __future__ import annotations

from typing import Any


def collect(context: dict[str, Any]) -> dict[str, Any]:
    events = sample_pydantic_ai_events()
    prompt = events[0]
    tool_call = events[1]
    tool_result = events[2]
    now = prompt["started_at"]
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    agent_id = context["agent_id"]
    node_id = "node_pydantic_ai_research_agent"
    run_id = "run_pydantic_ai_news_example_001"
    root_span_id = "span_pydantic_ai_agent_run_001"
    tool_span_id = "span_pydantic_ai_tool_fetch_001"

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": "pydantic-ai-source-hook-example",
        "description": "Example Pydantic AI style hook output for Kyoko.",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": now,
            "updated_at": tool_result["ended_at"],
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": "Pydantic AI source hook example",
                "status": "active",
                "adapter_version": "kyoko.example.pydantic_ai_source_hook.v0",
                "config_json": {"example": True},
                "capabilities_json": {"runs": True, "spans": True},
                "last_seen_at": tool_result["ended_at"],
            }
        ],
        "agent_identities": [
            {
                "id": agent_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-news-agent",
                "name": context["agent_name"],
                "kind": "framework_node",
                "role": "research agent",
                "model": prompt["model"],
                "workspace_path": context["root_path"],
                "metadata_json": {"framework": "pydantic-ai"},
            }
        ],
        "workflow_nodes": [
            {
                "id": node_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": "pydantic-ai-news-agent",
                "agent_identity_id": agent_id,
                "kind": "agent",
                "name": "Pydantic AI news agent",
                "metadata_json": {"framework": "pydantic-ai"},
            }
        ],
        "queues": [],
        "tasks": [],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": prompt["run_id"],
                "root_span_id": root_span_id,
                "agent_identity_id": agent_id,
                "task_attempt_id": None,
                "status": "failed",
                "started_at": prompt["started_at"],
                "ended_at": tool_result["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": prompt["prompt"],
                    "media_type": "text/plain",
                    "kind": "agent_prompt",
                },
                "output_ref": None,
                "output_payload": {
                    "content": {"error": tool_result["error"], "tool": tool_call["tool_name"]},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "agent_error",
                },
                "summary": "Pydantic AI example failed when fetch_source timed out.",
                "metadata_json": {"run_id": prompt["run_id"], "model": prompt["model"]},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": prompt["run_id"],
                "parent_span_id": None,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "llm",
                "name": "agent.run",
                "status": "failed",
                "started_at": prompt["started_at"],
                "ended_at": tool_result["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": prompt["prompt"],
                    "media_type": "text/plain",
                    "kind": "span_input",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "Tool fetch_source timed out before final response.",
                    "media_type": "text/plain",
                    "kind": "span_output",
                },
                "usage_json": {"input_tokens": prompt["input_tokens"], "output_tokens": 0},
                "attributes_json": {
                    "gen_ai.operation.name": "agent_run",
                    "gen_ai.request.model": prompt["model"],
                },
                "raw_ref": None,
                "raw_payload": {
                    "content": {"events": events},
                    "encoding": "json",
                    "kind": "raw_trace",
                    "media_type": "application/json",
                    "metadata": {"source": "sample_pydantic_ai_events"},
                },
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": tool_call["tool_call_id"],
                "parent_span_id": root_span_id,
                "workflow_node_id": node_id,
                "agent_identity_id": agent_id,
                "kind": "tool",
                "name": tool_call["tool_name"],
                "status": "failed",
                "started_at": tool_call["started_at"],
                "ended_at": tool_result["ended_at"],
                "input_ref": None,
                "input_payload": {
                    "content": tool_call["args"],
                    "encoding": "json",
                    "kind": "tool_args",
                    "media_type": "application/json",
                },
                "output_ref": None,
                "output_payload": {
                    "content": tool_result["error"],
                    "media_type": "text/plain",
                    "kind": "tool_error",
                },
                "usage_json": {},
                "attributes_json": {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": tool_call["tool_name"],
                    "error.type": tool_result["error_type"],
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [],
        "timeline_events": [
            {
                "id": "event_pydantic_ai_fetch_timeout_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "span_failed",
                "at": tool_result["ended_at"],
                "agent_identity_id": agent_id,
                "payload_ref": None,
                "payload": {
                    "content": tool_result["error"],
                    "media_type": "text/plain",
                    "kind": "error_quote",
                },
                "metadata_json": {"error_type": tool_result["error_type"]},
            }
        ],
    }


def sample_pydantic_ai_events() -> list[dict[str, Any]]:
    return [
        {
            "kind": "agent_run",
            "run_id": "pydantic-ai-run-001",
            "model": "openai:gpt-4.1-mini",
            "prompt": "Research current AI infrastructure news and cite sources.",
            "input_tokens": 128,
            "started_at": "2026-01-01T00:00:00Z",
        },
        {
            "kind": "tool_call",
            "tool_call_id": "pydantic-ai-tool-call-001",
            "tool_name": "fetch_source",
            "args": {"url": "https://example.test/news", "timeout_seconds": 3},
            "started_at": "2026-01-01T00:00:04Z",
        },
        {
            "kind": "tool_result",
            "tool_call_id": "pydantic-ai-tool-call-001",
            "status": "failed",
            "error_type": "timeout",
            "error": "fetch_source timed out after 3 seconds",
            "ended_at": "2026-01-01T00:00:08Z",
        },
    ]
