"""Example KYOKO_SOURCE_HOOK for OpenClaw-style local agent sessions.

This example is dependency-free. In a real OpenClaw app, replace
sample_openclaw_session() with exported session or trajectory rows, then keep
the same conversion into Kyoko agent identities, tasks, spans, handoffs, and
timeline events.
"""

from __future__ import annotations

from typing import Any


def collect(context: dict[str, Any]) -> dict[str, Any]:
    session = sample_openclaw_session()
    profile_id = context["profile_id"]
    source_id = context["source_id"]
    main_agent_id = context["agent_id"]
    reviewer_agent_id = "agent_openclaw_reviewer"
    main_node_id = "node_openclaw_main"
    reviewer_node_id = "node_openclaw_reviewer"
    task_id = "task_openclaw_session_001"
    run_id = "run_openclaw_session_example_001"
    root_span_id = "span_openclaw_user_prompt_001"
    tool_span_id = "span_openclaw_read_file_001"
    handoff_span_id = "span_openclaw_handoff_review_001"
    response_span_id = "span_openclaw_final_response_001"
    handoff_id = "handoff_openclaw_main_to_reviewer_001"

    return {
        "fixture_version": "kyoko.source_events.v1",
        "name": "openclaw-source-hook-example",
        "description": "Example OpenClaw session hook output for Kyoko.",
        "profile": {
            "id": profile_id,
            "name": context["profile_name"],
            "root_path": context["root_path"],
            "status": "active",
            "created_at": session["started_at"],
            "updated_at": session["ended_at"],
        },
        "sources": [
            {
                "id": source_id,
                "profile_id": profile_id,
                "kind": context["framework"],
                "display_name": "OpenClaw source hook example",
                "status": "active",
                "adapter_version": "kyoko.example.openclaw_source_hook.v0",
                "config_json": {"example": True, "agent": "main"},
                "capabilities_json": {"sessions": True, "spans": True, "handoffs": True},
                "last_seen_at": session["ended_at"],
            }
        ],
        "agent_identities": [
            _agent(
                agent_id=main_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name=context["agent_name"],
                role="workspace agent",
                workspace_path=context["root_path"],
            ),
            _agent(
                agent_id=reviewer_agent_id,
                profile_id=profile_id,
                source_id=source_id,
                name="reviewer",
                role="review subagent",
                workspace_path=context["root_path"],
            ),
        ],
        "workflow_nodes": [
            _node(
                node_id=main_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=main_agent_id,
                name="main agent",
            ),
            _node(
                node_id=reviewer_node_id,
                profile_id=profile_id,
                source_id=source_id,
                agent_id=reviewer_agent_id,
                name="reviewer agent",
            ),
        ],
        "queues": [],
        "tasks": [
            {
                "id": task_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "queue_id": None,
                "external_id": session["session_id"],
                "title": "OpenClaw local session",
                "body_ref": None,
                "body_payload": {
                    "content": session["prompt"],
                    "media_type": "text/plain",
                    "kind": "session_prompt",
                },
                "status": "done",
                "assignee_agent_identity_id": main_agent_id,
                "created_by_agent_identity_id": None,
                "priority": "normal",
                "workspace_kind": "repo",
                "workspace_path": context["root_path"],
                "created_at": session["started_at"],
                "started_at": session["started_at"],
                "completed_at": session["ended_at"],
                "metadata_json": {"openclaw.session_id": session["session_id"]},
            }
        ],
        "task_attempts": [],
        "runs": [
            {
                "id": run_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "external_id": session["session_id"],
                "root_span_id": root_span_id,
                "agent_identity_id": main_agent_id,
                "task_attempt_id": None,
                "status": "succeeded",
                "started_at": session["started_at"],
                "ended_at": session["ended_at"],
                "input_ref": None,
                "input_payload": {"content": session["prompt"], "media_type": "text/plain", "kind": "user_prompt"},
                "output_ref": None,
                "output_payload": {
                    "content": session["final_response"],
                    "media_type": "text/plain",
                    "kind": "assistant_response",
                },
                "summary": "OpenClaw example session read workspace state and delegated review.",
                "metadata_json": {"session_id": session["session_id"], "agent": "main"},
            }
        ],
        "spans": [
            {
                "id": root_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openclaw-user-message-001",
                "parent_span_id": None,
                "workflow_node_id": main_node_id,
                "agent_identity_id": main_agent_id,
                "kind": "agent",
                "name": "user_prompt",
                "status": "succeeded",
                "started_at": session["started_at"],
                "ended_at": "2026-01-01T00:00:02Z",
                "input_ref": None,
                "input_payload": {"content": session["prompt"], "media_type": "text/plain", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": "planning workspace inspection", "media_type": "text/plain", "kind": "span_output"},
                "usage_json": {},
                "attributes_json": {"openclaw.agent": "main"},
                "raw_ref": None,
            },
            {
                "id": tool_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openclaw-tool-read-file",
                "parent_span_id": root_span_id,
                "workflow_node_id": main_node_id,
                "agent_identity_id": main_agent_id,
                "kind": "tool",
                "name": "read_file",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:02Z",
                "ended_at": "2026-01-01T00:00:04Z",
                "input_ref": None,
                "input_payload": {
                    "content": {"path": "README.md"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "tool_args",
                },
                "output_ref": None,
                "output_payload": {
                    "content": "README indicates the replay hook still needs wiring.",
                    "media_type": "text/plain",
                    "kind": "tool_result",
                },
                "usage_json": {},
                "attributes_json": {"openclaw.tool": "read_file"},
                "raw_ref": None,
                "raw_payload": {
                    "content": session,
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "raw_session",
                },
            },
            {
                "id": handoff_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openclaw-handoff-review",
                "parent_span_id": tool_span_id,
                "workflow_node_id": reviewer_node_id,
                "agent_identity_id": reviewer_agent_id,
                "kind": "handoff",
                "name": "handoff_to_reviewer",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:04Z",
                "ended_at": "2026-01-01T00:00:05Z",
                "input_ref": None,
                "input_payload": {
                    "content": {"from": "main", "to": "reviewer", "reason": "check replay wiring"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_input",
                },
                "output_ref": None,
                "output_payload": {"content": "review accepted", "media_type": "text/plain", "kind": "handoff_output"},
                "usage_json": {},
                "attributes_json": {"openclaw.handoff.to": "reviewer"},
                "raw_ref": None,
            },
            {
                "id": response_span_id,
                "run_id": run_id,
                "source_id": source_id,
                "external_id": "openclaw-final-response",
                "parent_span_id": handoff_span_id,
                "workflow_node_id": main_node_id,
                "agent_identity_id": main_agent_id,
                "kind": "agent",
                "name": "final_response",
                "status": "succeeded",
                "started_at": "2026-01-01T00:00:05Z",
                "ended_at": session["ended_at"],
                "input_ref": None,
                "input_payload": {"content": "review result", "media_type": "text/plain", "kind": "span_input"},
                "output_ref": None,
                "output_payload": {"content": session["final_response"], "media_type": "text/plain", "kind": "span_output"},
                "usage_json": {"input_tokens": 112, "output_tokens": 48},
                "attributes_json": {"openclaw.agent": "main"},
                "raw_ref": None,
            },
        ],
        "handoffs": [
            {
                "id": handoff_id,
                "profile_id": profile_id,
                "source_id": source_id,
                "from_agent_identity_id": main_agent_id,
                "to_agent_identity_id": reviewer_agent_id,
                "from_workflow_node_id": main_node_id,
                "to_workflow_node_id": reviewer_node_id,
                "from_task_id": task_id,
                "to_task_id": None,
                "run_id": run_id,
                "span_id": handoff_span_id,
                "kind": "agent_handoff",
                "reason_ref": None,
                "reason_payload": {"content": "Main agent requested review.", "media_type": "text/plain", "kind": "handoff_reason"},
                "payload_ref": None,
                "payload": {
                    "content": {"session_id": session["session_id"], "from": "main", "to": "reviewer"},
                    "encoding": "json",
                    "media_type": "application/json",
                    "kind": "handoff_payload",
                },
                "created_at": "2026-01-01T00:00:04Z",
                "metadata_json": {"openclaw.session_id": session["session_id"]},
            }
        ],
        "timeline_events": [
            {
                "id": "event_openclaw_tool_read_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "span",
                "entity_id": tool_span_id,
                "kind": "tool_completed",
                "at": "2026-01-01T00:00:04Z",
                "agent_identity_id": main_agent_id,
                "payload_ref": None,
                "payload": {"content": "read_file completed", "media_type": "text/plain", "kind": "timeline_note"},
                "metadata_json": {"tool": "read_file"},
            },
            {
                "id": "event_openclaw_handoff_001",
                "profile_id": profile_id,
                "source_id": source_id,
                "entity_type": "handoff",
                "entity_id": handoff_id,
                "kind": "handoff_created",
                "at": "2026-01-01T00:00:04Z",
                "agent_identity_id": main_agent_id,
                "payload_ref": None,
                "payload": {"content": "reviewer handoff created", "media_type": "text/plain", "kind": "timeline_note"},
                "metadata_json": {"to": "reviewer"},
            },
        ],
    }


def sample_openclaw_session() -> dict[str, Any]:
    return {
        "session_id": "openclaw-session-001",
        "prompt": "Inspect local replay wiring and summarize what is missing.",
        "final_response": "Replay wiring needs a hook-backed bounded smoke before live gateway replay.",
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:08Z",
    }


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
        "kind": "openclaw_agent",
        "role": role,
        "model": "unknown",
        "workspace_path": workspace_path,
        "metadata_json": {"framework": "openclaw"},
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
        "metadata_json": {"framework": "openclaw"},
    }
