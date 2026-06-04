// TypeScript shapes for Kyoko's JSON API. These mirror the Python contract in
// kyoko/web.py, inspection.py, live.py, mcp_log.py, annotations.py. The `/api/*`
// JSON is the integration boundary — keep these in sync when the server changes.

export interface RunSummary {
  id: string;
  profile_id: string;
  status: string | null;
  summary: string | null;
  agent_identity_id: string | null;
  agent_name: string | null;
  agent_kind: string | null;
  external_id: string | null;
  started_at: string | null;
  ended_at: string | null;
  span_count: number;
  failed_span_count: number;
  handoff_count: number;
  root_span_id: string | null;
  source_id: string | null;
  input_ref: string | null;
  output_ref: string | null;
  task_attempt_id: string | null;
  metadata: Record<string, unknown>;
}

export type NormalizedKind = "llm" | "tool" | "other";

export interface NormalizedSpan {
  kind: NormalizedKind;
  adapter: string;
  model?: string;
  // Adapters attach extra fields (messages, tool name, args, etc.); keep open.
  [k: string]: unknown;
}

export interface SpanNode {
  id: string;
  parent_span_id: string | null;
  name: string | null;
  kind: string | null;
  status: string | null;
  started_at: string | null;
  ended_at: string | null;
  agent_identity_id: string | null;
  model: string | null;
  usage: Record<string, unknown>;
  normalized: NormalizedSpan;
  input_preview?: string | null;
  output_preview?: string | null;
  children: SpanNode[];
}

export interface SubAgent {
  root_span_id: string;
  name: string | null;
  span_ids: string[];
  llm_count: number;
  tool_count: number;
  started_at: string | null;
  ended_at: string | null;
  model: string | null;
  trigger: string;
}

export interface RunOutline {
  run: {
    id: string;
    status: string | null;
    started_at: string | null;
    ended_at: string | null;
    summary: string | null;
  };
  span_tree: SpanNode[];
  subagents: SubAgent[];
  summary: {
    spans: number;
    failed_spans: number;
    handoffs: number;
    live_events: number;
    annotations: number;
    subagents: number;
  };
}

export interface SpanPayload {
  span_id: string;
  target: "input" | "output";
  available: boolean;
  media_type?: string;
  size_bytes?: number;
  path_applied?: string | null;
  offset?: number;
  truncated?: boolean;
  content?: string;
}

export type LiveEventKind =
  | "token"
  | "tool_start"
  | "tool_result"
  | "status"
  | "message"
  | "error"
  | "other";

export interface LiveEvent {
  id: string;
  profile_id: string;
  source_id: string | null;
  run_id: string | null;
  span_id: string | null;
  seq: number;
  kind: LiveEventKind;
  content_preview: string | null;
  content_ref: string | null;
  content_truncated: boolean;
  at: string;
  metadata: Record<string, unknown>;
}

export type McpDirection = "request" | "response" | "notification";

export interface McpLogEntry {
  id: string;
  profile_id: string | null;
  session_id: string;
  seq: number;
  direction: McpDirection;
  method: string | null;
  tool_name: string | null;
  params_preview: string | null;
  params_ref: string | null;
  result_preview: string | null;
  result_ref: string | null;
  is_error: boolean;
  error_code: number | null;
  duration_ms: number | null;
  client_id: string | null;
  at: string;
  metadata: Record<string, unknown>;
}

export type AnnotationKind = "issue" | "good" | "note";

export interface Annotation {
  id: string;
  profile_id: string;
  run_id: string | null;
  span_id: string | null;
  kind: AnnotationKind;
  note: string | null;
  source: string;
  created_at: string;
  updated_at: string | null;
  metadata: Record<string, unknown>;
}

export interface Proposal {
  id: string;
  title: string;
  summary: string | null;
  section: string;
  section_label?: string;
  section_description?: string;
  state: string;
  confidence: number | null;
  confidence_level?: string;
  confidence_delta?: number | null;
  kyoko_confidence?: number | null;
  operator_confidence?: number | null;
  created_at: string;
  profile_id: string;
}

export type IssueSection = "context" | "harness";
export type IssueSeverity = "low" | "medium" | "high";
export type IssueStatus = "open" | "resolved" | "dismissed";

export interface Issue {
  id: string;
  profile_id: string;
  title: string;
  body: string | null;
  section: IssueSection | null;
  category: string | null;
  severity: IssueSeverity | null;
  status: IssueStatus;
  evidence_refs: Record<string, unknown>[];
  affected_agent_identity_ids: string[];
  affected_workflow_node_ids: string[];
  affected_task_ids: string[];
  affected_span_ids: string[];
  proposal_ids: string[];
  created_at: string;
  updated_at: string | null;
}

export interface AutonomyPolicy {
  profile_id: string;
  context_mode: string;
  harness_mode: string;
  allow_repo_patch: boolean;
  allow_check_write: boolean;
  allow_skillbook_write: boolean;
  allow_profile_config_write: boolean;
  allow_replay_server_patch: boolean;
  dirty_worktree_policy: string;
  allowed_paths: string[];
  protected_paths: string[];
  [k: string]: unknown;
}

export interface TimelineEvent {
  id: string;
  kind: string;
  entity_type?: string | null;
  entity_id?: string | null;
  created_at?: string;
  at?: string;
  summary?: string | null;
  detail?: string | null;
  [k: string]: unknown;
}

export interface CheckSpec {
  id: string;
  [k: string]: unknown;
}
export interface CheckRun {
  id: string;
  [k: string]: unknown;
}
export interface ReplayRun {
  id: string;
  [k: string]: unknown;
}

export interface ChecksBundle {
  check_specs: CheckSpec[];
  check_runs: CheckRun[];
  replay_runs: ReplayRun[];
}

export interface DashboardMetrics {
  profile_id?: string;
  profile_name?: string;
  scope?: unknown;
  cards?: Record<string, unknown>;
  runs?: Record<string, unknown>;
  checks?: Record<string, unknown>;
  replay?: Record<string, unknown>;
  autonomy?: Record<string, unknown>;
  issues?: unknown;
  before_after?: unknown;
  [k: string]: unknown;
}

// ---- Evaluation plane (measurement) ----------------------------------------

export type EvalKind = "python" | "llm";
export type EvalOutputType = "numeric" | "boolean";
export type EvalDirection = "higher_is_better" | "lower_is_better";

export interface EvalDefinition {
  id: string;
  kind: EvalKind;
  name: string;
  version: string;
  partner: string | null;
  source: string;
  unit_type: string;
  output_type: EvalOutputType;
  direction: EvalDirection;
  problem_statement: string | null;
  vars?: string[] | null;
  severity_bands?: Record<string, unknown> | null;
  status: string;
}

export interface MeasureAggregate {
  type: string;
  value: number | null;
  numerator?: number;
  denominator?: number;
  scored?: number;
  skipped?: number;
  histogram?: Record<string, unknown>;
}

export interface MeasureRun {
  id: string;
  eval_definition_id: string;
  kind: EvalKind;
  status: string;
  unit_total: number;
  unit_scored: number;
  unit_skipped: number;
  aggregate: MeasureAggregate | null;
  created_at: string;
}

export interface MeasureResult {
  id: string;
  unit_type: string;
  unit_ref: string;
  status: "scored" | "skipped" | "error";
  score_numeric: number | null;
  score_bool: boolean | null;
  reasoning: string | null;
  degraded: boolean;
  detail: Record<string, unknown>;
}

export type ComparisonDirection = "improved" | "regressed" | "unchanged";

export interface Comparison {
  eval_id: string;
  kind: EvalKind;
  baseline: string;
  compare: string;
  baseline_value: number | null;
  compare_value: number | null;
  delta: number | null;
  direction: ComparisonDirection;
  metric_direction: EvalDirection;
}

export interface EvalsBundle {
  detectors: EvalDefinition[];
}

export interface EvalDetailBundle {
  detector: EvalDefinition;
}

export interface EvalRunsBundle {
  eval_runs: MeasureRun[];
}

export interface EvalRunDetailBundle {
  eval_run: MeasureRun;
  results: MeasureResult[];
}

export interface LlmEvalsBundle {
  llm_evals: EvalDefinition[];
}

export interface LlmEvalDetailBundle {
  llm_eval: EvalDefinition;
}

export interface LlmEvalRunsBundle {
  eval_runs: MeasureRun[];
}

export interface LlmEvalRunDetailBundle {
  eval_run: MeasureRun;
  results: MeasureResult[];
}
