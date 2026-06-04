/*
Example KYOKO_REPLAY_HOOK for AI SDK / TypeScript projects.

This file is dependency-free on purpose. In a real AI SDK app, replace
runAiSdkReplay() with generateText/streamText under mocked tools, then keep the
same return shape: output_run_id, target_map, and Kyoko source_events for the
replay output run.
*/

export async function replay(request) {
  const outputRunId = "run_ai_sdk_replay_001";
  const sourceId = "source_ai_sdk_replay_example";
  const rootSpanId = "span_ai_sdk_replay_root_001";
  const retrySpanId = "span_fetch_retry_success_001";
  return {
    status: "passed",
    output_run_id: outputRunId,
    actual_side_effect_mode: request.side_effect_mode,
    target_map: {
      span_fetch_timeout_001: retrySpanId
    },
    source_events: sourceEvents({
      outputRunId,
      sourceId,
      rootSpanId,
      retrySpanId,
      replayOfRunId: request.source_run_id || "run_research_topic_001"
    }),
    note: "AI SDK example replay retried the transient source fetch under mocked tool behavior."
  };
}

function sourceEvents({ outputRunId, sourceId, rootSpanId, retrySpanId, replayOfRunId }) {
  return {
    fixture_version: "kyoko.source_events.v1",
    profile: {
      id: "profile_news_research_001",
      name: "News Research Workflow",
      root_path: "/tmp/kyoko-fixtures/news-research",
      status: "active",
      created_at: "2026-05-31T12:05:00Z",
      updated_at: "2026-05-31T12:08:00Z"
    },
    sources: [
      {
        id: sourceId,
        profile_id: "profile_news_research_001",
        kind: "ai-sdk-typescript",
        display_name: "AI SDK replay hook example",
        status: "active",
        adapter_version: "kyoko.example.ai_sdk_replay_hook.v0",
        config_json: { example: true },
        capabilities_json: { trace: true, replay: true },
        last_seen_at: "2026-05-31T12:08:00Z"
      }
    ],
    runs: [
      {
        id: outputRunId,
        profile_id: "profile_news_research_001",
        source_id: sourceId,
        external_id: "ai-sdk-replay-request-001",
        root_span_id: rootSpanId,
        agent_identity_id: "agent_researcher_001",
        task_attempt_id: null,
        status: "succeeded",
        started_at: "2026-05-31T12:05:00Z",
        ended_at: "2026-05-31T12:08:00Z",
        input_ref: "input://ai-sdk/replay/news-topic",
        output_ref: "output://ai-sdk/replay/news-topic",
        summary: "Replay completed after retrying the transient source fetch timeout.",
        metadata_json: { replay_of_run_id: replayOfRunId }
      }
    ],
    spans: [
      {
        id: rootSpanId,
        run_id: outputRunId,
        source_id: sourceId,
        external_id: "ai-sdk-replay-root",
        parent_span_id: null,
        workflow_node_id: "node_researcher_001",
        agent_identity_id: "agent_researcher_001",
        kind: "llm",
        name: "generateText: replay news research",
        status: "succeeded",
        started_at: "2026-05-31T12:05:00Z",
        ended_at: "2026-05-31T12:08:00Z",
        input_ref: "input://ai-sdk/replay/news-topic",
        output_ref: "output://ai-sdk/replay/news-topic",
        usage_json: { input_tokens: 164, output_tokens: 64, total_tokens: 228 },
        attributes_json: {
          replay_of_run_id: replayOfRunId,
          "gen_ai.operation.name": "generate_text"
        },
        raw_ref: null
      },
      {
        id: retrySpanId,
        run_id: outputRunId,
        source_id: sourceId,
        external_id: "ai-sdk-tool-search-news-retry",
        parent_span_id: rootSpanId,
        workflow_node_id: "node_researcher_001",
        agent_identity_id: "agent_researcher_001",
        kind: "tool",
        name: "tool: searchNews",
        status: "succeeded",
        started_at: "2026-05-31T12:06:00Z",
        ended_at: "2026-05-31T12:06:45Z",
        input_ref: "input://ai-sdk/replay/search-news",
        output_ref: "output://ai-sdk/replay/search-news",
        usage_json: {},
        attributes_json: {
          replay_of_span_id: "span_fetch_timeout_001",
          first_attempt: "timeout",
          retry_count: 1,
          source_status: "complete",
          "gen_ai.operation.name": "execute_tool"
        },
        raw_ref: null
      }
    ],
    handoffs: [
      {
        id: "handoff_ai_sdk_replay_research_to_writer_001",
        profile_id: "profile_news_research_001",
        source_id: sourceId,
        from_agent_identity_id: "agent_researcher_001",
        to_agent_identity_id: "agent_writer_001",
        from_workflow_node_id: "node_researcher_001",
        to_workflow_node_id: "node_writer_001",
        from_task_id: "task_research_topic_001",
        to_task_id: null,
        run_id: outputRunId,
        span_id: null,
        kind: "agent_handoff",
        reason_ref: "reason://ai-sdk/replay/fetch-recovered",
        payload_ref: "payload://ai-sdk/replay/source-complete",
        created_at: "2026-05-31T12:08:00Z",
        metadata_json: {
          source_status: "complete",
          replay_of_handoff_id: "handoff_research_to_writer_001"
        }
      }
    ],
    timeline_events: [
      {
        id: "event_ai_sdk_replay_fetch_retry_success_001",
        profile_id: "profile_news_research_001",
        source_id: sourceId,
        entity_type: "span",
        entity_id: retrySpanId,
        kind: "tool_retry_succeeded",
        at: "2026-05-31T12:06:45Z",
        agent_identity_id: "agent_researcher_001",
        payload_ref: "output://ai-sdk/replay/search-news",
        metadata_json: { replay_of_span_id: "span_fetch_timeout_001" }
      }
    ]
  };
}
