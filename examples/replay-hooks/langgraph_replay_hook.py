"""Example KYOKO_REPLAY_HOOK for LangGraph-style Python workflows.

This example is dependency-free. In a real LangGraph app, replace
run_langgraph_replay() with a graph invocation that runs under mocked or
sandboxed tools, then keep the same return shape: output_run_id, target_map,
and Kyoko source_events for the replay output run.
"""

from __future__ import annotations

from typing import Any


def replay(request: dict[str, Any]) -> dict[str, Any]:
    output_run_id = "run_langgraph_replay_001"
    source_id = "source_langgraph_replay_example"
    root_span_id = "span_langgraph_replay_root_001"
    retry_span_id = "span_fetch_retry_success_001"
    return {
        "status": "passed",
        "output_run_id": output_run_id,
        "actual_side_effect_mode": request["side_effect_mode"],
        "target_map": {
            "span_fetch_timeout_001": retry_span_id,
        },
        "source_events": _source_events(
            output_run_id=output_run_id,
            source_id=source_id,
            root_span_id=root_span_id,
            retry_span_id=retry_span_id,
            replay_of_run_id=request.get("source_run_id") or "run_research_topic_001",
            framework="langgraph-python",
        ),
        "note": "LangGraph example replay retried the transient source fetch under mocked network behavior.",
    }


def _source_events(
    *,
    output_run_id: str,
    source_id: str,
    root_span_id: str,
    retry_span_id: str,
    replay_of_run_id: str,
    framework: str,
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
                "kind": framework,
                "display_name": "LangGraph replay hook example",
                "status": "active",
                "adapter_version": "kyoko.example.langgraph_replay_hook.v0",
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
                "external_id": "langgraph-replay-thread-001",
                "root_span_id": root_span_id,
                "agent_identity_id": "agent_researcher_001",
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": "2026-05-31T12:05:00Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://langgraph/replay/news-topic",
                "output_ref": "output://langgraph/replay/news-topic",
                "summary": "Replay completed after retrying the transient source fetch timeout.",
                "metadata_json": {"replay_of_run_id": replay_of_run_id},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "langgraph-replay-root",
                "parent_span_id": None,
                "workflow_node_id": "node_researcher_001",
                "agent_identity_id": "agent_researcher_001",
                "kind": "agent",
                "name": "research topic replay",
                "status": "succeeded",
                "started_at": "2026-05-31T12:05:00Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://langgraph/replay/news-topic",
                "output_ref": "output://langgraph/replay/news-topic",
                "usage_json": {},
                "attributes_json": {"replay_of_run_id": replay_of_run_id},
                "raw_ref": None,
            },
            {
                "id": retry_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "langgraph-fetch-source-retry",
                "parent_span_id": root_span_id,
                "workflow_node_id": "node_researcher_001",
                "agent_identity_id": "agent_researcher_001",
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": "2026-05-31T12:06:00Z",
                "ended_at": "2026-05-31T12:06:45Z",
                "input_ref": "input://langgraph/replay/fetch-source",
                "output_ref": "output://langgraph/replay/fetch-source",
                "usage_json": {},
                "attributes_json": {
                    "replay_of_span_id": "span_fetch_timeout_001",
                    "first_attempt": "timeout",
                    "retry_count": 1,
                    "source_status": "complete",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_langgraph_replay_research_to_writer_001",
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "from_agent_identity_id": "agent_researcher_001",
                "to_agent_identity_id": "agent_writer_001",
                "from_workflow_node_id": "node_researcher_001",
                "to_workflow_node_id": "node_writer_001",
                "from_task_id": "task_research_topic_001",
                "to_task_id": None,
                "run_id": output_run_id,
                "span_id": None,
                "kind": "agent_handoff",
                "reason_ref": "reason://langgraph/replay/fetch-recovered",
                "payload_ref": "payload://langgraph/replay/source-complete",
                "created_at": "2026-05-31T12:08:00Z",
                "metadata_json": {
                    "source_status": "complete",
                    "replay_of_handoff_id": "handoff_research_to_writer_001",
                },
            }
        ],
        "timeline_events": [
            {
                "id": "event_langgraph_replay_fetch_retry_success_001",
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": retry_span_id,
                "kind": "tool_retry_succeeded",
                "at": "2026-05-31T12:06:45Z",
                "agent_identity_id": "agent_researcher_001",
                "payload_ref": "output://langgraph/replay/fetch-source",
                "metadata_json": {"replay_of_span_id": "span_fetch_timeout_001"},
            }
        ],
    }
