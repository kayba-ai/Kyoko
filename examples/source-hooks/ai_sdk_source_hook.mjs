/*
Example KYOKO_SOURCE_HOOK for AI SDK / TypeScript projects.

This file is dependency-free on purpose. In a real AI SDK app, replace
sampleAiSdkEvents() with the telemetry/events you collect around generateText,
streamText, tool calls, and final responses, then keep the same conversion into
Kyoko runs and spans.
*/

export async function collect(context) {
  const events = sampleAiSdkEvents();
  const runId = "run_ai_sdk_news_example_001";
  const rootSpanId = "span_ai_sdk_generate_text_001";
  const toolSpanId = "span_ai_sdk_tool_search_news_001";
  const nodeId = "node_" + slug(context.agent_name);
  const generated = events.find((event) => event.kind === "generate_text");
  const toolCall = events.find((event) => event.kind === "tool_call");
  const toolResult = events.find((event) => event.kind === "tool_result");
  const failed = events.some((event) => event.status === "failed");

  return {
    runs: [
      {
        id: runId,
        profile_id: context.profile_id,
        source_id: context.source_id,
        external_id: generated.request_id,
        root_span_id: rootSpanId,
        agent_identity_id: context.agent_id,
        task_attempt_id: null,
        status: failed ? "failed" : "succeeded",
        started_at: generated.started_at,
        ended_at: toolResult.ended_at,
        input_ref: "prompt://ai-sdk/news-research/topic",
        output_ref: failed ? "error://ai-sdk/search-timeout" : "output://ai-sdk/news-summary",
        summary: failed
          ? "AI SDK example failed because searchNews timed out."
          : "AI SDK example completed.",
        metadata_json: {
          framework: "ai-sdk",
          function_id: generated.function_id,
          model: generated.model
        }
      }
    ],
    spans: [
      {
        id: rootSpanId,
        run_id: runId,
        source_id: context.source_id,
        external_id: generated.request_id,
        parent_span_id: null,
        workflow_node_id: nodeId,
        agent_identity_id: context.agent_id,
        kind: "llm",
        name: "generateText: news research",
        status: failed ? "failed" : "succeeded",
        started_at: generated.started_at,
        ended_at: toolResult.ended_at,
        input_ref: "prompt://ai-sdk/news-research/topic",
        output_ref: failed ? "error://ai-sdk/search-timeout" : "output://ai-sdk/news-summary",
        usage_json: {
          input_tokens: generated.input_tokens,
          output_tokens: generated.output_tokens,
          total_tokens: generated.input_tokens + generated.output_tokens
        },
        attributes_json: {
          "gen_ai.operation.name": "generate_text",
          "gen_ai.request.model": generated.model,
          "ai.telemetry.function_id": generated.function_id,
          "ai.sdk.provider": generated.provider
        },
        raw_ref: null
      },
      {
        id: toolSpanId,
        run_id: runId,
        source_id: context.source_id,
        external_id: toolCall.tool_call_id,
        parent_span_id: rootSpanId,
        workflow_node_id: nodeId,
        agent_identity_id: context.agent_id,
        kind: "tool",
        name: "tool: searchNews",
        status: toolResult.status === "failed" ? "failed" : "succeeded",
        started_at: toolCall.started_at,
        ended_at: toolResult.ended_at,
        input_ref: "input://ai-sdk/search-news",
        output_ref: toolResult.status === "failed"
          ? "error://ai-sdk/search-news-timeout"
          : "output://ai-sdk/search-news",
        usage_json: {},
        attributes_json: {
          "gen_ai.operation.name": "execute_tool",
          "gen_ai.tool.name": toolCall.tool_name,
          "ai.toolCallId": toolCall.tool_call_id,
          "error.type": toolResult.status === "failed" ? toolResult.error_type : null
        },
        raw_ref: null
      }
    ],
    timeline_events: toolResult.status === "failed"
      ? [
          {
            id: "event_ai_sdk_search_timeout_001",
            profile_id: context.profile_id,
            source_id: context.source_id,
            entity_type: "span",
            entity_id: toolSpanId,
            kind: "span_failed",
            at: toolResult.ended_at,
            agent_identity_id: context.agent_id,
            payload_ref: "error://ai-sdk/search-news-timeout",
            metadata_json: {
              error_type: toolResult.error_type,
              tool_name: toolCall.tool_name
            }
          }
        ]
      : []
  };
}

function sampleAiSdkEvents() {
  return [
    {
      kind: "generate_text",
      request_id: "ai-sdk-request-001",
      function_id: "news-research",
      provider: "openai",
      model: "gpt-4.1-mini",
      input_tokens: 164,
      output_tokens: 47,
      started_at: "2026-01-01T00:00:00Z"
    },
    {
      kind: "tool_call",
      tool_call_id: "tool-call-search-news-001",
      tool_name: "searchNews",
      started_at: "2026-01-01T00:00:04Z"
    },
    {
      kind: "tool_result",
      tool_call_id: "tool-call-search-news-001",
      status: "failed",
      error_type: "timeout",
      ended_at: "2026-01-01T00:00:10Z"
    }
  ];
}

function slug(value) {
  const cleaned = String(value)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return cleaned || "agent";
}
