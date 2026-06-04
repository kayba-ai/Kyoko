/**
 * KyokoRecorder + run/span handles, mirroring the Python SDK
 * (kyoko/sdk.py: KyokoRecorder, RunHandle, SpanHandle).
 *
 * A recorder accumulates runs and spans in memory and renders them to the
 * `kyoko.source_events.v1` fixture via {@link KyokoRecorder.toSourceEvents}.
 * Pass that fixture to {@link KyokoClient.ingest} to persist it into Kyoko.
 */

import { newId, slug, shortId, utcNow } from "./ids.js";
import type {
  JsonValue,
  RunPayload,
  RunStatus,
  SourceEvents,
  SpanPayload,
  SpanStatus,
  TimelineEventPayload,
} from "./types.js";

export interface RecorderOptions {
  profileId: string;
  profileName: string;
  rootPath: string;
  sourceId?: string;
  sourceKind?: string;
  sourceName?: string;
  agentId?: string;
  agentName?: string;
  agentKind?: string;
  agentRole?: string | null;
  model?: string | null;
  adapterVersion?: string;
}

export interface SpanOptions {
  kind?: string;
  externalId?: string | null;
  inputRef?: string | null;
  workflowNodeId?: string | null;
  agentIdentityId?: string | null;
  usage?: Record<string, JsonValue>;
  attributes?: Record<string, JsonValue>;
  rawRef?: string | null;
}

export interface RunOptions {
  externalId?: string | null;
  inputRef?: string | null;
  metadata?: Record<string, JsonValue>;
}

/** A recording span. Mirrors `SpanHandle`. Call {@link SpanHandle.finish} or {@link SpanHandle.fail}. */
export class SpanHandle {
  status: SpanStatus = "running";
  endedAt: string | null = null;
  outputRef: string | null;

  constructor(
    private readonly recorder: KyokoRecorder,
    private readonly run: RunHandle,
    readonly spanId: string,
    private readonly name: string,
    private readonly kind: string,
    private readonly parentSpanId: string | null,
    private readonly workflowNodeId: string | null,
    private readonly agentIdentityId: string | null,
    private readonly startedAt: string,
    private readonly externalId: string | null,
    private readonly inputRef: string | null,
    private readonly usage: Record<string, JsonValue>,
    readonly attributes: Record<string, JsonValue>,
    private readonly rawRef: string | null,
  ) {
    this.outputRef = null;
  }

  /** Open a child span; the new span becomes the parent for further nesting. */
  span(name: string, options: SpanOptions = {}): SpanHandle {
    return this.run.span(name, { ...options, parentSpanId: this.spanId });
  }

  finish(status: SpanStatus = "succeeded", outputRef?: string | null): void {
    if (this.endedAt !== null) return;
    this.status = status;
    this.endedAt = utcNow();
    if (outputRef !== undefined && outputRef !== null) this.outputRef = outputRef;
    this.recorder._pushSpan(this.toPayload());
    this.run._popSpan(this.spanId);
  }

  fail(error: unknown, outputRef?: string | null): void {
    if (this.endedAt !== null) return;
    this.status = "failed";
    this.endedAt = utcNow();
    if (outputRef !== undefined && outputRef !== null) this.outputRef = outputRef;
    setDefault(this.attributes, "error_type", errorName(error));
    setDefault(this.attributes, "error_message", errorMessage(error));
    setDefault(this.attributes, "traceback", errorStack(error));
    this.recorder._pushSpan(this.toPayload());
    this.run._popSpan(this.spanId);
  }

  private toPayload(): SpanPayload {
    return {
      id: this.spanId,
      run_id: this.run.runId,
      source_id: this.recorder.sourceId,
      external_id: this.externalId,
      parent_span_id: this.parentSpanId,
      workflow_node_id: this.workflowNodeId,
      agent_identity_id: this.agentIdentityId,
      kind: this.kind,
      name: this.name,
      status: this.status,
      started_at: this.startedAt,
      ended_at: this.endedAt,
      input_ref: this.inputRef,
      output_ref: this.outputRef,
      usage_json: this.usage,
      attributes_json: this.attributes,
      raw_ref: this.rawRef,
    };
  }
}

/** A recording run. Mirrors `RunHandle`. */
export class RunHandle {
  status: RunStatus = "running";
  endedAt: string | null = null;
  outputRef: string | null = null;
  summary: string | null = null;
  rootSpanId: string | null = null;

  private readonly spanStack: string[] = [];
  private rootSpan: SpanHandle | null = null;

  constructor(
    private readonly recorder: KyokoRecorder,
    readonly runId: string,
    private readonly name: string,
    private readonly startedAt: string,
    private readonly agentIdentityId: string,
    private readonly workflowNodeId: string,
    private readonly externalId: string | null,
    private readonly inputRef: string | null,
    private readonly metadata: Record<string, JsonValue>,
  ) {}

  /** Open the root agent span. Call once before adding child spans. */
  start(): this {
    if (this.rootSpan !== null) return this;
    this.rootSpanId = newId("span", this.name);
    const root = new SpanHandle(
      this.recorder,
      this,
      this.rootSpanId,
      this.name,
      "agent",
      null,
      this.workflowNodeId,
      this.agentIdentityId,
      this.startedAt,
      this.externalId,
      this.inputRef,
      {},
      {},
      null,
    );
    this.spanStack.push(this.rootSpanId);
    this.rootSpan = root;
    return this;
  }

  /** Open a child span under the current span (or the root if none is open). */
  span(name: string, options: SpanOptions & { parentSpanId?: string } = {}): SpanHandle {
    const parentSpanId =
      options.parentSpanId ??
      (this.spanStack.length > 0 ? this.spanStack[this.spanStack.length - 1] : this.rootSpanId);
    const span = new SpanHandle(
      this.recorder,
      this,
      newId("span", name),
      name,
      options.kind ?? "tool",
      parentSpanId,
      options.workflowNodeId ?? this.workflowNodeId,
      options.agentIdentityId ?? this.agentIdentityId,
      utcNow(),
      options.externalId ?? null,
      options.inputRef ?? null,
      options.usage ?? {},
      options.attributes ?? {},
      options.rawRef ?? null,
    );
    this.spanStack.push(span.spanId);
    return span;
  }

  finish(status: RunStatus = "succeeded", options: { outputRef?: string | null; summary?: string | null } = {}): void {
    if (this.endedAt !== null) return;
    this.status = status;
    this.endedAt = utcNow();
    if (options.outputRef !== undefined && options.outputRef !== null) this.outputRef = options.outputRef;
    if (options.summary !== undefined && options.summary !== null) this.summary = options.summary;
    this.finishRootSpan(status as SpanStatus);
    this.recorder._pushRun(this.toPayload());
    this.recorder._popActiveRun(this.runId);
  }

  fail(error: unknown, outputRef?: string | null): void {
    if (this.endedAt !== null) return;
    this.status = "failed";
    this.endedAt = utcNow();
    if (outputRef !== undefined && outputRef !== null) this.outputRef = outputRef;
    setDefault(this.metadata, "error_type", errorName(error));
    setDefault(this.metadata, "error_message", errorMessage(error));
    if (this.rootSpan) {
      setDefault(this.rootSpan.attributes, "error_type", errorName(error));
      setDefault(this.rootSpan.attributes, "error_message", errorMessage(error));
    }
    this.finishRootSpan("failed");
    this.recorder._pushRun(this.toPayload());
    this.recorder._popActiveRun(this.runId);
  }

  /** @internal */
  _popSpan(spanId: string): void {
    if (this.spanStack.length > 0 && this.spanStack[this.spanStack.length - 1] === spanId) {
      this.spanStack.pop();
    }
  }

  private finishRootSpan(status: SpanStatus): void {
    if (this.rootSpan && this.rootSpan.endedAt === null) {
      this.rootSpan.finish(status, this.outputRef);
    }
  }

  private toPayload(): RunPayload {
    return {
      id: this.runId,
      profile_id: this.recorder.profileId,
      source_id: this.recorder.sourceId,
      external_id: this.externalId,
      root_span_id: this.rootSpanId,
      agent_identity_id: this.agentIdentityId,
      task_attempt_id: null,
      status: this.status,
      started_at: this.startedAt,
      ended_at: this.endedAt,
      input_ref: this.inputRef,
      output_ref: this.outputRef,
      summary: this.summary,
      metadata_json: this.metadata,
    };
  }
}

/** In-memory recorder mirroring the Python `KyokoRecorder`. */
export class KyokoRecorder {
  readonly profileId: string;
  readonly profileName: string;
  readonly rootPath: string;
  readonly sourceId: string;
  readonly sourceKind: string;
  readonly sourceName: string;
  readonly agentId: string;
  readonly agentName: string;
  readonly agentKind: string;
  readonly agentRole: string | null;
  readonly model: string | null;
  readonly adapterVersion: string;
  readonly createdAt: string;
  readonly updatedAt: string;

  private readonly workflowNodeId: string;
  private readonly runs: RunPayload[] = [];
  private readonly spans: SpanPayload[] = [];
  private readonly activeRuns: string[] = [];

  constructor(options: RecorderOptions) {
    const now = utcNow();
    this.profileId = options.profileId;
    this.profileName = options.profileName;
    this.rootPath = options.rootPath;
    this.sourceKind = options.sourceKind ?? "kyoko_sdk";
    this.sourceName = options.sourceName ?? "Kyoko SDK";
    this.sourceId = options.sourceId ?? `source_${slug(this.sourceKind)}_${shortId()}`;
    this.agentName = options.agentName ?? "agent";
    this.agentKind = options.agentKind ?? "agent";
    this.agentRole = options.agentRole ?? null;
    this.agentId = options.agentId ?? `agent_${slug(this.agentName)}_${shortId()}`;
    this.model = options.model ?? null;
    this.adapterVersion = options.adapterVersion ?? "kyoko.typescript_sdk.v0";
    this.createdAt = now;
    this.updatedAt = now;
    this.workflowNodeId = `node_${slug(this.agentName)}_${shortId()}`;
  }

  /** Create a run handle. Call `.start()` on it to open the root span. */
  run(name: string, options: RunOptions = {}): RunHandle {
    const handle = new RunHandle(
      this,
      newId("run", name),
      name,
      utcNow(),
      this.agentId,
      this.workflowNodeId,
      options.externalId ?? null,
      options.inputRef ?? null,
      options.metadata ?? {},
    );
    this.activeRuns.push(handle.runId);
    return handle;
  }

  /** Render the accumulated runs/spans into a `kyoko.source_events.v1` fixture. */
  toSourceEvents(): SourceEvents {
    return {
      fixture_version: "kyoko.source_events.v1",
      name: `${this.profileId}-sdk-events`,
      description: "Source events recorded with the Kyoko TypeScript SDK.",
      profile: {
        id: this.profileId,
        name: this.profileName,
        root_path: this.rootPath,
        status: "active",
        created_at: this.createdAt,
        updated_at: this.updatedAt,
      },
      sources: [
        {
          id: this.sourceId,
          profile_id: this.profileId,
          kind: this.sourceKind,
          display_name: this.sourceName,
          status: "active",
          adapter_version: this.adapterVersion,
          config_json: {},
          capabilities_json: { runs: true, spans: true },
          last_seen_at: utcNow(),
        },
      ],
      agent_identities: [
        {
          id: this.agentId,
          profile_id: this.profileId,
          source_id: this.sourceId,
          external_id: this.agentName,
          name: this.agentName,
          kind: this.agentKind,
          role: this.agentRole,
          model: this.model,
          workspace_path: this.rootPath,
          metadata_json: {},
        },
      ],
      workflow_nodes: [
        {
          id: this.workflowNodeId,
          profile_id: this.profileId,
          source_id: this.sourceId,
          external_id: this.agentName,
          agent_identity_id: this.agentId,
          kind: "agent",
          name: this.agentName,
          metadata_json: {},
        },
      ],
      queues: [],
      tasks: [],
      task_attempts: [],
      runs: [...this.runs],
      spans: this.orderedSpans(),
      handoffs: [],
      timeline_events: this.timelineEvents(),
    };
  }

  /** @internal */
  _pushRun(run: RunPayload): void {
    this.runs.push(run);
  }

  /** @internal */
  _pushSpan(span: SpanPayload): void {
    this.spans.push(span);
  }

  /** @internal */
  _popActiveRun(runId: string): void {
    if (this.activeRuns.length > 0 && this.activeRuns[this.activeRuns.length - 1] === runId) {
      this.activeRuns.pop();
    }
  }

  private timelineEvents(): TimelineEventPayload[] {
    const events: TimelineEventPayload[] = [];
    for (const span of this.spans) {
      if (span.status !== "failed") continue;
      events.push({
        id: `event_${span.id}_failed`,
        profile_id: this.profileId,
        source_id: this.sourceId,
        entity_type: "span",
        entity_id: span.id,
        kind: "span_failed",
        at: span.ended_at ?? utcNow(),
        agent_identity_id: span.agent_identity_id,
        payload_ref: span.output_ref,
        metadata_json: span.attributes_json,
      });
    }
    return events;
  }

  /** Topologically order spans parents-before-children, matching `_ordered_spans`. */
  private orderedSpans(): SpanPayload[] {
    const remaining = new Map<string, SpanPayload>();
    for (const span of this.spans) remaining.set(span.id, span);
    const ordered: SpanPayload[] = [];
    const emitted = new Set<string>();
    while (remaining.size > 0) {
      let progressed = false;
      for (const [spanId, span] of [...remaining.entries()]) {
        const parentId = span.parent_span_id;
        if (parentId === null || emitted.has(parentId) || !remaining.has(parentId)) {
          ordered.push(span);
          emitted.add(spanId);
          remaining.delete(spanId);
          progressed = true;
        }
      }
      if (!progressed) {
        for (const span of remaining.values()) ordered.push(span);
        break;
      }
    }
    return ordered;
  }
}

function setDefault(target: Record<string, JsonValue>, key: string, value: JsonValue): void {
  if (!(key in target)) target[key] = value;
}

function errorName(error: unknown): string {
  if (error instanceof Error) return error.name;
  return typeof error;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function errorStack(error: unknown): string {
  if (error instanceof Error && typeof error.stack === "string") return error.stack;
  return errorMessage(error);
}
