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
  // Trace-level metrics (added with the Traces explorer; may be absent on older
  // payloads, so treat as optional and render "—" when null/undefined).
  duration_ms?: number | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  llm_span_count?: number | null;
  cost_usd?: number | null;
}

export type NormalizedKind = "llm" | "tool" | "other";

export interface ChatMessage {
  role: string;
  content: unknown;
}

export interface NormalizedParams {
  temperature?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
  frequency_penalty?: number | null;
  presence_penalty?: number | null;
  response_model?: string | null;
  finish_reasons?: unknown;
  response_id?: string | null;
  [k: string]: unknown;
}

export interface NormalizedSpan {
  kind: NormalizedKind;
  adapter: string;
  model?: string;
  system?: string | null;
  messages?: ChatMessage[];
  output_text?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  params?: NormalizedParams;
  tool_name?: string | null;
  args?: unknown;
  result?: unknown;
  is_error?: boolean;
  // Adapters attach extra fields; keep open.
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
  duration_ms?: number | null;
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

export interface TraceMetrics {
  total_duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  llm_spans: number | null;
  tool_spans: number | null;
  cost_usd: number | null;
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
  metrics?: TraceMetrics;
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

export interface RunPayload {
  run_id: string;
  target: "input" | "output";
  available: boolean;
  media_type?: string;
  size_bytes?: number;
  path_applied?: string | null;
  offset?: number;
  truncated?: boolean;
  content?: string;
}

export interface Score {
  id: string;
  eval_run_id: string;
  name: string | null;
  kind: string | null;
  unit_type: string;
  status: string;
  score_numeric: number | null;
  score_bool: boolean | null;
  reasoning: string | null;
}

export interface RunScores {
  trace: Score[];
  by_span: { [span_id: string]: Score[] };
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
  // The originating Issue this proposal addresses (Issue-as-spine), when known.
  issue_id?: string | null;
  created_at: string;
  profile_id: string;
}

export type IssueSection = "context" | "harness";
export type IssueSeverity = "low" | "medium" | "high";
// Expanded lifecycle: an Issue is the spine of the optimization loop and moves
// through prioritized → diagnosed → accepted → proposed → applied → resolved,
// can be guarded (a regression check now protects the fix), or dismissed. The
// original "open"|"resolved"|"dismissed" remain valid. "accepted" is the gate-#1
// approval point: analysis only surfaces a diagnosis, and proposal authoring
// happens in a separate, autonomy-gated step.
export type IssueStatus =
  | "open"
  | "prioritized"
  | "diagnosed"
  | "accepted"
  | "proposed"
  | "applied"
  | "resolved"
  | "guarded"
  | "dismissed";

// Where an Issue came from.
export type IssueSource = "analysis" | "eval" | "llm_eval" | "manual";

export interface Issue {
  id: string;
  profile_id: string;
  title: string;
  body: string | null;
  section: IssueSection | null;
  category: string | null;
  severity: IssueSeverity | null;
  status: IssueStatus;
  // Priority rank assigned during prioritization (lower = more important); null
  // until prioritized.
  rank?: number | null;
  // Diagnosed root cause, when known.
  root_cause?: string | null;
  // Provenance of the issue.
  source?: IssueSource | null;
  // The evaluator/guard that now protects a resolved fix, when guarded.
  evaluator_id?: string | null;
  // Dedup fingerprint for this failure; the deterministic dedup net folds
  // recurrences of the same failure into one issue. Rarely worth surfacing.
  signature?: string | null;
  // How many times this failure has been surfaced across time (≥1). >1 means a
  // recurring failure folded into this issue.
  recurrence_count?: number | null;
  // When this issue was accepted at gate #1 (iso), null until accepted.
  accepted_at?: string | null;
  // When the fix for this issue was applied (iso), null until applied.
  applied_at?: string | null;
  // The recurrence_count snapshotted at apply time; post-apply recurrences are
  // `recurrence_count - recurrence_count_at_apply` and feed the regression guard.
  recurrence_count_at_apply?: number | null;
  // How many auto-fix cycles the guard monitor has spent on this issue.
  auto_fix_attempts?: number | null;
  // Set when autonomy has been blocked for this issue (escalated to HITL) after
  // exhausting max_auto_fix_attempts; carries a human-readable reason.
  autonomy_blocked?: boolean | null;
  autonomy_blocked_reason?: string | null;
  evidence_refs: Record<string, unknown>[];
  affected_agent_identity_ids: string[];
  affected_workflow_node_ids: string[];
  affected_task_ids: string[];
  affected_span_ids: string[];
  proposal_ids: string[];
  review_comment?: string | null;
  created_at: string;
  updated_at: string | null;
}

// A guard installed by `improve` so a resolved Issue cannot silently regress.
// Surfaced in the improve --json response (POST /api/improve `guards`).
export interface GuardReport {
  issue_id: string;
  evaluator_id: string;
  evaluator_kind: string;
  deterministic: boolean;
  affected_span_names: string[];
}

// Result of accepting an issue at gate #1 (POST /api/issues/accept).
//
// Two shapes, by `status`:
//  - "proposed":  the in-process mock author ran synchronously; `propose` carries the
//                 authored proposal context (`proposal_id`), `job_id` is null.
//  - "authoring": a real operator (e.g. codex) is authoring the proposal on the background
//                 runner; `propose` is null and `job_id` identifies the run. The proposal
//                 arrives later over the `analysis_run` SSE channel — refetch on completion.
export interface AcceptIssueResult {
  issue: Issue;
  propose: { proposal_id?: string | null; [k: string]: unknown } | null;
  job_id?: string | null;
  operator?: string;
  status?: "proposed" | "authoring";
}

// Issue-centric analysis report (POST /api/analyze). Analysis surfaces Issues
// only (diagnosis); proposal authoring is a separate, autonomy-gated step, so
// there is NO proposal_id here.
export interface AnalyzeReport {
  operator: string;
  profile_id: string;
  issue_ids: string[];
  new_issue_ids: string[];
  bundled_issue_ids: string[];
  evidence_path?: string | null;
  prompt_path?: string | null;
  persisted?: boolean;
  operator_run_id?: string | null;
  raw_output_path?: string | null;
  attempts?: number;
  [k: string]: unknown;
}

// One per-issue gate-#1 outcome from an improve run. `action`:
// proposed → a proposal was authored; awaiting_acceptance → mode is `propose`,
// issue awaits human acceptance; diagnosed_only → mode is `off`, no authoring.
export interface Gate1Outcome {
  issue_id: string;
  section: string;
  mode: string;
  action: "proposed" | "awaiting_acceptance" | "diagnosed_only";
}

// Report from an improve run (POST /api/improve). Keeps `proposal_id` (the first
// authored proposal, or null) for back-compat and adds the issue-centric fields.
export interface ImproveReport {
  proposal_id?: string | null;
  proposal_ids?: string[];
  gate1_outcomes?: Gate1Outcome[];
  guards?: GuardReport[];
  analyze?: AnalyzeReport | null;
  [k: string]: unknown;
}

export type AutonomyMode = "hitl" | "autonomous";

export interface AutonomyPolicy {
  profile_id: string;
  // Two-mode autonomy (spec 0018): `hitl` = human accepts/approves every change;
  // `autonomous` = Kyoko auto-applies a fix once it has recurred enough times.
  mode: AutonomyMode;
  // How many times a failure must recur before autonomous mode authors+applies a fix.
  recurrence_threshold: number;
  // Post-apply recurrences (count - count_at_apply) that trip the regression guard.
  regression_threshold: number;
  // In autonomous mode, auto-revert an applied fix once it regresses past the threshold.
  auto_rollback_on_regression: boolean;
  // How many auto-fix cycles the guard monitor will attempt before escalating to HITL.
  max_auto_fix_attempts: number;
  allow_repo_patch: boolean;
  dirty_worktree_policy: string;
  allowed_paths: string[];
  protected_paths: string[];
  updated_at?: string;
  [k: string]: unknown;
}

/** A skillbook entry — the deliverable that issues/proposals feed into. */
export interface Skill {
  id: string;
  profile_id: string;
  proposal_id: string | null;
  section: string;
  issue: string;
  insight: string;
  keywords: string[];
  occurrences: unknown[];
  helpful_count: number;
  harmful_count: number;
  neutral_count: number;
  active: boolean | number;
  human_locked: boolean | number;
  source_run_id: string | null;
  created_at: string;
  updated_at: string;
  [k: string]: unknown;
}

/** Fields the loopback dashboard may update via POST /api/policy. Paths are
 *  intentionally not editable here (CLI/storage only). */
export interface PolicyUpdate {
  mode?: AutonomyMode;
  recurrence_threshold?: number;
  regression_threshold?: number;
  auto_rollback_on_regression?: boolean;
  max_auto_fix_attempts?: number;
  allow_repo_patch?: boolean;
  dirty_worktree_policy?: string;
}

/** Result of applying a proposal at HITL gate #2 (POST /api/proposals/apply). */
export interface ApplyProposalResult {
  proposal_id: string;
  profile_id: string;
  section: string;
  state: string;
  applied_skill_ids: string[];
  applied_context_rule_ids: string[];
  patch_transaction_ids: string[];
  [k: string]: unknown;
}

/** One guard-monitor action from POST /api/guard-monitor. Shape is permissive
 *  since the server may attach extra detail. */
export interface GuardMonitorAction {
  issue_id?: string;
  action?: string;
  reason?: string;
  [k: string]: unknown;
}

/** Report from the guard monitor (POST /api/guard-monitor). */
export interface GuardMonitorReport {
  profile_id: string;
  mode: AutonomyMode;
  regression_threshold: number;
  actions: GuardMonitorAction[];
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

// ---- Analysis plane (operator/import analyzers, schedules, runs) -------------

export type AnalyzerKind = "ace" | "codex" | "claude" | "openclaw" | "hermes";

export interface Analyzer {
  analyzer: AnalyzerKind;
  installed: boolean;
  command: string;
  adapter_registered: boolean;
  schedulable: boolean;
}

export interface AnalyzersBundle {
  analyzers: Analyzer[];
  schedulable: string[];
}

export type AnalysisRunStatus = "running" | "succeeded" | "failed";

export interface AnalysisRun {
  id: string;
  status: AnalysisRunStatus;
  operator_label: string | null;
  operator_kind: string | null;
  started_at: string | null;
  ended_at: string | null;
  proposal_id: string | null;
  error: string | null;
  schedule_id: string | null;
  analyzed_since: string | null;
}

export interface AnalysisSchedule {
  id: string;
  analyzer_kind: string;
  adapter_id: string | null;
  source_kind: string | null;
  source_path: string | null;
  refresh_import: boolean;
  interval_hours: number;
  at_time: string | null;
  enabled: boolean;
  run_autonomy: boolean;
  watermark: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  last_operator_run_id: string | null;
  last_error: string | null;
}

export type AnalysisRunScope = "all" | "new" | "run";

export interface RunAnalysisBody {
  analyzer: AnalyzerKind;
  adapter_id?: string;
  scope: AnalysisRunScope;
  run_id?: string;
  since?: string;
  refresh_import?: boolean;
  source_kind?: string;
  source_path?: string;
  run_autonomy?: boolean;
  ace_command?: string[];
  operator_command?: string[];
  timeout_seconds?: number;
  max_retries?: number;
  profile_id?: string;
}

export interface RunAnalysisResult {
  job_id: string;
  analyzer: string;
  status: string;
}

export interface CreateScheduleBody {
  analyzer: "openclaw" | "hermes";
  source_path?: string;
  adapter_id?: string;
  interval_hours?: number;
  at_time?: string;
  refresh_import?: boolean;
  enabled?: boolean;
  run_autonomy?: boolean;
}

export interface UpdateScheduleBody {
  id: string;
  enabled?: boolean;
  interval_hours?: number;
  at_time?: string;
  refresh_import?: boolean;
  run_autonomy?: boolean;
  source_path?: string;
  adapter_id?: string;
}

// SSE `analysis_run` event payload (live progress for run analysis + schedules).
export type AnalysisRunPhase =
  | "running"
  | "importing"
  | "analyzing"
  | "skipped"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface AnalysisRunEvent {
  job_id: string;
  schedule_id: string | null;
  analyzer: string;
  scope: string;
  status: AnalysisRunPhase;
  proposal_ids?: string[];
  operator_run_id?: string;
  error?: string;
  reason?: string;
  at: string;
}
