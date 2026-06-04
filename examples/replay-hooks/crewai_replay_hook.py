"""Example KYOKO_REPLAY_HOOK for CrewAI style crews and tasks.

This example is dependency-free. In a real CrewAI app, replace
run_crewai_replay() with a crew kickoff using mocked or sandboxed tools, then
keep the same return shape: output_run_id, target_map, and Kyoko source_events
for the replay output run.
"""

from __future__ import annotations

from typing import Any


def replay(request: dict[str, Any]) -> dict[str, Any]:
    output_run_id = "run_crewai_replay_001"
    source_id = "source_crewai_replay_example"
    root_span_id = "span_crewai_replay_root_001"
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
            retry_span_id=retry_span_id,
            replay_of_run_id=request.get("source_run_id") or "run_research_topic_001",
        ),
        "note": "CrewAI example replay retried fetch_source with mocked tool behavior before the writer task ran.",
    }


def _source_events(
    *,
    output_run_id: str,
    source_id: str,
    root_span_id: str,
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
                "kind": "crewai-python",
                "display_name": "CrewAI replay hook example",
                "status": "active",
                "adapter_version": "kyoko.example.crewai_replay_hook.v0",
                "config_json": {"example": True},
                "capabilities_json": {"trace": True, "replay": True, "tasks": True},
                "last_seen_at": "2026-05-31T12:08:00Z",
            }
        ],
        "runs": [
            {
                "id": output_run_id,
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "external_id": "crewai-replay-run-001",
                "root_span_id": root_span_id,
                "agent_identity_id": "agent_researcher_001",
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": "2026-05-31T12:05:00Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://crewai/replay/news-topic",
                "output_ref": "output://crewai/replay/news-topic",
                "summary": "Replay completed after retrying the transient source fetch timeout.",
                "metadata_json": {"replay_of_run_id": replay_of_run_id, "crewai.process": "sequential"},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "crewai-replay-root",
                "parent_span_id": None,
                "workflow_node_id": "node_researcher_001",
                "agent_identity_id": "agent_researcher_001",
                "kind": "agent",
                "name": "crew.kickoff replay",
                "status": "succeeded",
                "started_at": "2026-05-31T12:05:00Z",
                "ended_at": "2026-05-31T12:08:00Z",
                "input_ref": "input://crewai/replay/news-topic",
                "output_ref": "output://crewai/replay/news-topic",
                "usage_json": {},
                "attributes_json": {"replay_of_run_id": replay_of_run_id, "crewai.crew": "news research crew"},
                "raw_ref": None,
            },
            {
                "id": retry_span_id,
                "run_id": output_run_id,
                "source_id": source_id,
                "external_id": "crewai-fetch-source-retry",
                "parent_span_id": root_span_id,
                "workflow_node_id": "node_researcher_001",
                "agent_identity_id": "agent_researcher_001",
                "kind": "tool",
                "name": "fetch_source",
                "status": "succeeded",
                "started_at": "2026-05-31T12:06:00Z",
                "ended_at": "2026-05-31T12:06:45Z",
                "input_ref": "input://crewai/replay/fetch-source",
                "output_ref": "output://crewai/replay/fetch-source",
                "usage_json": {},
                "attributes_json": {
                    "replay_of_span_id": "span_fetch_timeout_001",
                    "first_attempt": "timeout",
                    "retry_count": 1,
                    "source_status": "complete",
                    "crewai.task": "research current AI infrastructure news",
                },
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": "handoff_crewai_replay_research_to_writer_001",
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
                "reason_ref": "reason://crewai/replay/fetch-recovered",
                "payload_ref": "payload://crewai/replay/source-complete",
                "created_at": "2026-05-31T12:08:00Z",
                "metadata_json": {
                    "source_status": "complete",
                    "replay_of_handoff_id": "handoff_research_to_writer_001",
                },
            }
        ],
        "timeline_events": [
            {
                "id": "event_crewai_replay_fetch_retry_success_001",
                "profile_id": "profile_news_research_001",
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": retry_span_id,
                "kind": "tool_retry_succeeded",
                "at": "2026-05-31T12:06:45Z",
                "agent_identity_id": "agent_researcher_001",
                "payload_ref": "output://crewai/replay/fetch-source",
                "metadata_json": {"replay_of_span_id": "span_fetch_timeout_001"},
            }
        ],
    }
