"""Example KYOKO_REPLAY_HOOK for OpenAI Agents SDK style workflows.

This example is dependency-free. In a real OpenAI Agents app, replace
run_openai_agents_replay() with an agent run using mocked tools and handoffs,
then keep the same return shape: output_run_id, target_map, and Kyoko
source_events for the replay output run.
"""

from __future__ import annotations

from typing import Any


def replay(request: dict[str, Any]) -> dict[str, Any]:
    output_run_id = "run_openai_agents_replay_001"
    source_id = "source_openai_agents_replay_example"
    root_span_id = "span_openai_agents_replay_root_001"
    handoff_span_id = "span_openai_agents_replay_handoff_001"
    retry_span_id = "span_fetch_retry_success_001"
    return {
        "status": "passed",
        "output_run_id": output_run_id,
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {"span_fetch_timeout_001": retry_span_id},
        "source_events": _source_events(
            output_run_id=output_run_id,
            source_id=source_id,
            root_span_id=root_span_id,
            handoff_span_id=handoff_span_id,
            retry_span_id=retry_span_id,
            replay_of_run_id=request.get("source_run_id") or "run_research_topic_001",
        ),
        "note": "OpenAI Agents example replay retried the transient source fetch after handoff.",
    }


def _source_events(
    *,
    output_run_id: str,
    source_id: str,
    root_span_id: str,
    handoff_span_id: str,
    retry_span_id: str,
    replay_of_run_id: str,
) -> dict[str, Any]:
    return {
        "fixture_version": "kyoko.source_events.v1",
        "profile": {
            "id": "profile_news_research_001",
            "name": "News Research Workflow",
            "root_path": "/tmp/kyoko-fixtures/news-research",
            "status": "active",
            "created_at": "2026-05-31T12:05:00Z",
            "updated_at": "2026-05-31T12:08:00Z",
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": "profile_news_research_001",
                "kind": "openai-agents-python",
                "display_name": "OpenAI Agents replay hook example",
                "status": "active",
                "adapter_version": "kyoko.example.openai_agents_replay_hook.v0",
                "config_json": {"example": True},
                "capabilities_json": {"trace": True, "replay": True},
                "last_seen_at": "2026-05-31T12:08:00Z",
            }
        ],
        "runs": [
            {
                "id": output_run_id,
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "external_id": "openai-agents-replay-trace-001",
                "root_span_id": root_span_id,
                "agent_identity_id": "agent_researcher_001",
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": "2026-05-31T12:05:00Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://openai-agents/replay/news-topic",
                "output_ref": "output://openai-agents/replay/news-topic",
                "summary": "Replay completed after researcher retry recovered the missing source.",
                "metadata_json": {"replay_of_run_id": replay_of_run_id},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-root",
                "parent_span_id": None,
                "workflow_node_id": "node_researcher_001",
                "agent_identity_id": "agent_researcher_001",
                "kind": "agent",
                "name": "researcher_agent replay",
                "status": "succeeded",
                "started_at": "2026-05-31T12:05:00Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://openai-agents/replay/news-topic",
                "output_ref": "output://openai-agents/replay/news-topic",
                "usage_json": {"input_tokens": 144, "output_tokens": 72},
                "attributes_json": {
                    "replay_of_run_id": replay_of_run_id,
                    "openai_agents.agent.name": "researcher",
                },
                "raw_ref": None,
            },
            {
                "id": handoff_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "openai-agents-replay-handoff",
                "parent_span_id": root_span_id,
                "workflow_node_id": "node_writer_001",
                "agent_identity_id": "agent_writer_001",
                "kind": "handoff",
                "name": "handoff_to_writer",
                "status": "succeeded",
                "started_at": "2026-05-31T12:07:45Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://openai-agents/replay/handoff",
                "output_ref": "output://openai-agents/replay/handoff",
                "usage_json": {},
                "attributes_json": {"openai_agents.handoff.to": "writer"},
                "raw_ref": None,
            },
            {
                "id": retry_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "openai-agents-fetch-source-retry",
                "parent_span_id": root_span_id,
                "workflow_node_id": "node_researcher_001",
                "agent_identity_id": "agent_researcher_001",
                "kind": "tool",
                "name": "web_search",
                "status": "succeeded",
                "started_at": "2026-05-31T12:06:00Z",
                "ended_at": "2026-05-31T12:06:45Z",
                "input_ref": "input://openai-agents/replay/web-search",
                "output_ref": "output://openai-agents/replay/web-search",
                "usage_json": {},
                "attributes_json": {
                    "replay_of_span_id": "span_fetch_timeout_001",
                    "first_attempt": "timeout",
                    "retry_count": 1,
                    "source_status": "complete",
                    "gen_ai.operation.name": "execute_tool",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_openai_agents_replay_research_to_writer_001",
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "from_agent_identity_id": "agent_researcher_001",
                "to_agent_identity_id": "agent_writer_001",
                "from_workflow_node_id": "node_researcher_001",
                "to_workflow_node_id": "node_writer_001",
                "from_task_id": "task_research_topic_001",
                "to_task_id": None,
                "run_id": output_run_id,
                "span_id": handoff_span_id,
                "kind": "agent_handoff",
                "reason_ref": "reason://openai-agents/replay/fetch-recovered",
                "payload_ref": "payload://openai-agents/replay/source-complete",
                "created_at": "2026-05-31T12:08:00Z",
                "metadata_json": {
                    "source_status": "complete",
                    "replay_of_handoff_id": "handoff_research_to_writer_001",
                },
            }
        ],
        "timeline_events": [
            {
                "id": "event_openai_agents_replay_fetch_retry_success_001",
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": retry_span_id,
                "kind": "tool_retry_succeeded",
                "at": "2026-05-31T12:06:45Z",
                "agent_identity_id": "agent_researcher_001",
                "payload_ref": "output://openai-agents/replay/web-search",
                "metadata_json": {"replay_of_span_id": "span_fetch_timeout_001"},
            }
        ],
    }
