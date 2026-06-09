/**
 * Canonical payload shapes mirrored from the Kyoko Python SDK (kyoko/sdk.py)
 * and the server ingest routes in kyoko/web.py. These intentionally match the
 * `kyoko.source_events.v1` fixture format that `POST /api/ingest` accepts, and
 * the live-event shape that `POST /v1/live` accepts.
 *
 * Field names are snake_case on purpose: the wire format is the same JSON the
 * Python core produces, so the keys must match exactly.
 */

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export type RunStatus = "running" | "succeeded" | "failed";
export type SpanStatus = "running" | "succeeded" | "failed";

/** A single span row in the canonical model. */
export interface SpanPayload {
  id: string;
  run_id: string;
  source_id: string;
  external_id: string | null;
  parent_span_id: string | null;
  workflow_node_id: string | null;
  agent_identity_id: string | null;
  kind: string;
  name: string;
  status: SpanStatus;
  started_at: string;
  ended_at: string | null;
  input_ref: string | null;
  output_ref: string | null;
  usage_json: Record<string, JsonValue>;
  attributes_json: Record<string, JsonValue>;
  raw_ref: string | null;
}

/** A single run row in the canonical model. */
export interface RunPayload {
  id: string;
  profile_id: string;
  source_id: string;
  external_id: string | null;
  root_span_id: string | null;
  agent_identity_id: string;
  task_attempt_id: string | null;
  status: RunStatus;
  started_at: string;
  ended_at: string | null;
  input_ref: string | null;
  output_ref: string | null;
  summary: string | null;
  metadata_json: Record<string, JsonValue>;
}

export interface TimelineEventPayload {
  id: string;
  profile_id: string;
  source_id: string;
  entity_type: string;
  entity_id: string;
  kind: string;
  at: string;
  agent_identity_id: string | null;
  payload_ref: string | null;
  metadata_json: Record<string, JsonValue>;
}

/**
 * The `kyoko.source_events.v1` fixture, identical to what
 * `KyokoRecorder.to_source_events()` produces in the Python SDK. This is the
 * object posted (as-is) to `POST /api/ingest`.
 */
export interface SourceEvents {
  fixture_version: "kyoko.source_events.v1";
  name: string;
  description: string;
  profile: {
    id: string;
    name: string;
    root_path: string;
    status: string;
    created_at: string;
    updated_at: string;
  };
  sources: Array<Record<string, JsonValue>>;
  agent_identities: Array<Record<string, JsonValue>>;
  workflow_nodes: Array<Record<string, JsonValue>>;
  queues: Array<Record<string, JsonValue>>;
  tasks: Array<Record<string, JsonValue>>;
  task_attempts: Array<Record<string, JsonValue>>;
  runs: RunPayload[];
  spans: SpanPayload[];
  handoffs: Array<Record<string, JsonValue>>;
  timeline_events: TimelineEventPayload[];
}

/** A live (push) event, mirroring kyoko/live.py ingest_live_events. */
export interface LiveEvent {
  kind?: string;
  profile_id?: string | null;
  run_id?: string | null;
  span_id?: string | null;
  source_id?: string | null;
  content?: JsonValue;
  metadata?: Record<string, JsonValue> | null;
  at?: string | null;
}

/** Server response from `POST /api/ingest`. */
export interface IngestResponse {
  profile_id?: string;
  ingested_counts?: Record<string, number>;
  /** True on a successful POST; false when a best-effort ingest found no server. */
  delivered?: boolean;
  /** Set when a best-effort ingest could not reach a running Kyoko server. */
  unreachable?: boolean;
  detail?: string;
}

/** Server response from `POST /v1/live`. */
export interface LiveIngestResponse {
  ingested_count: number;
  events: Array<Record<string, JsonValue>>;
}
