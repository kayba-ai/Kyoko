// Thin fetch wrapper over Kyoko's loopback JSON API. No auth (SCOPE Decision 2:
// loopback-only, no tokens). Mutating POSTs always send `application/json` — the
// server's CSRF content-type guard requires it.

import type {
  AnalysisRun,
  AnalysisSchedule,
  AnalyzersBundle,
  Annotation,
  AnnotationKind,
  AutonomyPolicy,
  Comparison,
  CreateScheduleBody,
  DashboardMetrics,
  ChecksBundle,
  RunAnalysisBody,
  RunAnalysisResult,
  UpdateScheduleBody,
  EvalDefinition,
  EvalDetailBundle,
  EvalRunDetailBundle,
  EvalRunsBundle,
  EvalsBundle,
  Issue,
  IssueSection,
  IssueSeverity,
  IssueStatus,
  LlmEvalDetailBundle,
  LlmEvalRunDetailBundle,
  LlmEvalRunsBundle,
  LlmEvalsBundle,
  LiveEvent,
  McpLogEntry,
  PolicyUpdate,
  Proposal,
  RunOutline,
  RunPayload,
  RunScores,
  RunSummary,
  Skill,
  SpanPayload,
  TimelineEvent,
} from "./types";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function parse<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    if (body && typeof body === "object" && "error" in body) {
      msg = String((body as Record<string, unknown>).error);
    }
    throw new ApiError(res.status, msg, body);
  }
  return body as T;
}

export async function getJson<T>(path: string, params?: Record<string, unknown>): Promise<T> {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === "") continue;
      url.searchParams.set(k, String(v));
    }
  }
  const res = await fetch(url.toString(), { headers: { Accept: "application/json" } });
  return parse<T>(res);
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  return parse<T>(res);
}

// ---- Typed endpoint helpers (the surface the dashboard uses) -----------------

export const api = {
  status: () => getJson<Record<string, unknown>>("/api/status"),
  dashboardMetrics: () => getJson<DashboardMetrics>("/api/dashboard-metrics"),

  runs: () => getJson<{ runs: RunSummary[] }>("/api/runs").then((d) => d.runs),
  runDetail: (id: string) => getJson<Record<string, unknown>>("/api/run-detail", { id }),
  currentRun: () => getJson<RunSummary | null>("/api/current-run"),
  runOutline: (runId: string, payloadPreviewChars = 200) =>
    getJson<RunOutline>("/api/run-outline", { run_id: runId, payload_preview_chars: payloadPreviewChars }),
  runSearch: (
    runId: string,
    pattern: string,
    opts: { regex?: boolean; caseSensitive?: boolean; scope?: string; maxMatches?: number } = {},
  ) =>
    getJson<{ run_id: string; matches: any[]; match_count: number; truncated: boolean }>("/api/run-search", {
      run_id: runId,
      pattern,
      regex: opts.regex,
      case_sensitive: opts.caseSensitive,
      scope: opts.scope,
      max_matches: opts.maxMatches,
    }),
  spanContext: (spanId: string) => getJson<Record<string, unknown>>("/api/span-context", { span_id: spanId }),
  spanPayload: (
    spanId: string,
    opts: { target?: "input" | "output"; path?: string; maxChars?: number; offset?: number } = {},
  ) =>
    getJson<SpanPayload>("/api/span-payload", {
      span_id: spanId,
      target: opts.target ?? "input",
      path: opts.path,
      max_chars: opts.maxChars,
      offset: opts.offset,
    }),
  runPayload: (
    runId: string,
    opts: { target?: "input" | "output"; path?: string; maxChars?: number; offset?: number } = {},
  ) =>
    getJson<RunPayload>("/api/run-payload", {
      run_id: runId,
      target: opts.target ?? "input",
      path: opts.path,
      max_chars: opts.maxChars,
      offset: opts.offset,
    }),
  runScores: (runId: string) => getJson<RunScores>("/api/run-scores", { run_id: runId }),

  liveEvents: (opts: { runId?: string; afterSeq?: number; kinds?: string; limit?: number } = {}) =>
    getJson<{ events: LiveEvent[] } | LiveEvent[]>("/api/live-events", {
      run_id: opts.runId,
      after_seq: opts.afterSeq,
      kinds: opts.kinds,
      limit: opts.limit,
    }).then(unwrapList<LiveEvent>("events")),

  mcpLog: (opts: { sessionId?: string; toolName?: string; afterSeq?: number; limit?: number } = {}) =>
    getJson<{ events: McpLogEntry[] }>("/api/mcp-log", {
      session_id: opts.sessionId,
      tool_name: opts.toolName,
      after_seq: opts.afterSeq,
      limit: opts.limit,
    }).then((d) => d.events ?? []),

  annotations: (opts: { runId?: string; spanId?: string } = {}) =>
    getJson<{ annotations: Annotation[] }>("/api/annotations", {
      run_id: opts.runId,
      span_id: opts.spanId,
    }).then((d) => d.annotations ?? []),
  createAnnotation: (body: { kind: AnnotationKind; run_id?: string; span_id?: string; note?: string; source?: string }) =>
    postJson<{ annotation: Annotation }>("/api/annotations", body).then((d) => d.annotation),
  deleteAnnotation: (id: string) => postJson<unknown>("/api/annotations/delete", { id }),

  proposals: () => getJson<{ proposals: Proposal[] }>("/api/proposals").then((d) => d.proposals),
  proposalDetail: (id: string) => getJson<Record<string, unknown>>("/api/proposal-detail", { id }),

  issues: (opts: { status?: IssueStatus; section?: IssueSection } = {}) =>
    getJson<{ issues: Issue[] }>("/api/issues", {
      status: opts.status,
      section: opts.section,
    }).then((d) => d.issues ?? []),
  issueDetail: (id: string) => getJson<Record<string, unknown>>("/api/issue-detail", { id }),
  createIssue: (body: {
    title: string;
    body?: string;
    section?: IssueSection;
    category?: string;
    severity?: IssueSeverity;
    proposal_ids?: string[];
  }) => postJson<{ issue: Issue }>("/api/issues", body).then((d) => d.issue),
  updateIssueStatus: (id: string, status: IssueStatus) =>
    postJson<{ issue: Issue }>("/api/issue-status", { id, status }).then((d) => d.issue),
  updateIssueComment: (id: string, comment: string) =>
    postJson<{ issue: Issue }>("/api/issue-comment", { id, comment }).then((d) => d.issue),

  policy: () => getJson<{ policy: AutonomyPolicy }>("/api/policy").then((d) => d.policy),
  updatePolicy: (body: PolicyUpdate) =>
    postJson<{ policy: AutonomyPolicy }>("/api/policy", body).then((d) => d.policy),
  autonomyEvents: (limit = 50) =>
    getJson<{ autonomy_events?: TimelineEvent[]; events?: TimelineEvent[] }>("/api/autonomy-events", { limit }).then(
      (d) => d.autonomy_events ?? d.events ?? [],
    ),

  checks: () => getJson<ChecksBundle>("/api/checks"),

  skills: () => getJson<{ skills: Skill[] }>("/api/skills").then((d) => d.skills ?? []),

  // ---- Evaluation plane (detectors + judges) --------------------------------
  evals: () => getJson<EvalsBundle>("/api/evals").then((d) => d.detectors ?? []),
  evalDetail: (id: string) => getJson<EvalDetailBundle>("/api/evals/detail", { id }).then((d) => d.detector),
  evalRuns: () => getJson<EvalRunsBundle>("/api/eval-runs").then((d) => d.eval_runs ?? []),
  evalRunDetail: (id: string) =>
    getJson<EvalRunDetailBundle>("/api/eval-runs/detail", { id }),
  evalCompare: (baseline: string, compare: string) =>
    getJson<Comparison>("/api/eval-compare", { baseline, compare }),

  llmEvals: () => getJson<LlmEvalsBundle>("/api/llm-evals").then((d) => d.llm_evals ?? []),
  // Activate/deactivate a judge. Evidence-only config — gates nothing.
  setLlmEvalActive: (id: string, active: boolean) =>
    postJson<{ llm_eval: EvalDefinition }>("/api/llm-evals/status", { id, active }).then((d) => d.llm_eval),
  llmEvalDetail: (id: string) =>
    getJson<LlmEvalDetailBundle>("/api/llm-evals/detail", { id }).then((d) => d.llm_eval),
  llmEvalRuns: () => getJson<LlmEvalRunsBundle>("/api/llm-eval-runs").then((d) => d.eval_runs ?? []),
  llmEvalRunDetail: (id: string) =>
    getJson<LlmEvalRunDetailBundle>("/api/llm-eval-runs/detail", { id }),
  llmEvalCompare: (baseline: string, compare: string) =>
    getJson<Comparison>("/api/llm-eval-compare", { baseline, compare }),

  // ---- Analysis plane (operator/import analyzers, schedules, runs) ----------
  listAnalyzers: () => getJson<AnalyzersBundle>("/api/analysis/analyzers"),
  listAnalysisRuns: () =>
    getJson<{ runs: AnalysisRun[] }>("/api/analysis/runs").then((d) => d.runs ?? []),
  listSchedules: () =>
    getJson<{ schedules: AnalysisSchedule[] }>("/api/analysis/schedules").then((d) => d.schedules ?? []),
  runAnalysis: (body: RunAnalysisBody) =>
    postJson<RunAnalysisResult>("/api/analysis/run", body),
  bootstrapAdapters: (target: "all" | "codex" | "claude" | "openclaw" | "hermes") =>
    postJson<Record<string, unknown>>("/api/operator-adapters/bootstrap", { target }),
  createSchedule: (body: CreateScheduleBody) =>
    postJson<{ schedule: AnalysisSchedule }>("/api/analysis/schedules/create", body).then((d) => d.schedule),
  updateSchedule: (body: UpdateScheduleBody) =>
    postJson<{ schedule: AnalysisSchedule }>("/api/analysis/schedules/update", body).then((d) => d.schedule),
  deleteSchedule: (id: string) =>
    postJson<{ deleted: boolean; id: string }>("/api/analysis/schedules/delete", { id }),
  runSchedule: (id: string) =>
    postJson<{ job_id: string; schedule_id: string; status: string }>("/api/analysis/schedules/run", { id }),

  // Redaction is a fixed global default and retention is a manual prune (SCOPE
  // simplification) — neither has a policy endpoint anymore; Settings shows them
  // statically. Only storage is live.
  storageReport: () => getJson<Record<string, unknown>>("/api/storage-report"),
};

function unwrapList<T>(key: string) {
  return (d: { [k: string]: unknown } | T[]): T[] => {
    if (Array.isArray(d)) return d as T[];
    const v = (d as Record<string, unknown>)[key];
    return Array.isArray(v) ? (v as T[]) : [];
  };
}
