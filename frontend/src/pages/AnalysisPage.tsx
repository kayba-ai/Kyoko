import * as React from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Ban,
  CalendarClock,
  Check,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Loader2,
  Minus,
  Play,
  Plus,
  Sparkles,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  Analyzer,
  AnalyzerKind,
  AnalysisRun,
  AnalysisRunEvent,
  AnalysisRunPhase,
  AnalysisRunScope,
  AnalysisSchedule,
} from "@/lib/types";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useApi } from "@/hooks/useApi";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { Badge, statusTone, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Spinner, ErrorNote } from "@/components/ui/misc";

// Analysis runs an operator/import analyzer (ACE, Codex, Claude, OpenClaw, Hermes)
// over the trace corpus to surface gated learning proposals. The dashboard only
// kicks off analysis and shows progress/results — every proposed change still
// funnels through the check/replay gate and the profile autonomy policy. There is
// no propose-only toggle here: analysis "respects the autonomy policy".

const ANALYZER_LABELS: Record<AnalyzerKind, string> = {
  ace: "ACE",
  codex: "Codex",
  claude: "Claude",
  openclaw: "OpenClaw",
  hermes: "Hermes",
};

const SCOPE_OPTIONS = [
  { value: "all", label: "All traces" },
  { value: "new", label: "New since last" },
];

const DEMO_ANALYZERS: Analyzer[] = [
  { analyzer: "codex", installed: true, command: "codex", adapter_registered: true, schedulable: false },
  { analyzer: "claude", installed: true, command: "claude", adapter_registered: true, schedulable: false },
  { analyzer: "ace", installed: true, command: "ace", adapter_registered: true, schedulable: false },
];
const DEMO_ANALYSIS_ANALYZE_DELAY_MS = 700;
const DEMO_ANALYSIS_COMPLETE_DELAY_MS = 1700;
const DEMO_PROPOSAL_IDS = ["proposal_citation_grounding_001", "proposal_handoff_schema_001"];
const DEMO_ISSUE_COUNT = 2;

const PHASE_TONE: Record<string, NonNullable<BadgeProps["tone"]>> = {
  running: "warn",
  importing: "warn",
  analyzing: "warn",
  skipped: "neutral",
  succeeded: "ok",
  failed: "danger",
  cancelled: "neutral",
};

function phaseTone(status: string | null | undefined): NonNullable<BadgeProps["tone"]> {
  return PHASE_TONE[(status ?? "").toLowerCase()] ?? statusTone(status);
}

function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function TraceCorpusCard({
  metrics,
  loading,
  error,
}: {
  metrics: Record<string, unknown> | null;
  loading: boolean;
  error: Error | null;
}) {
  const runs = (metrics?.runs ?? {}) as Record<string, unknown>;
  const evals = (metrics?.evals ?? {}) as Record<string, unknown>;
  const totalRuns = num(runs.total);
  const failedSpans = num(runs.failed_spans);
  const evaluatedRuns = num(evals.evaluated_runs);
  const failedRuns = num(evals.failed_runs);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trace corpus</CardTitle>
        <Link to="/traces" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
          View traces <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </CardHeader>
      <CardBody>
        {loading ? (
          <Spinner />
        ) : error ? (
          <ErrorNote error={error} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-4">
            <div>
              <div className="text-2xl font-semibold tabular-nums text-foreground">{totalRuns}</div>
              <div className="text-xs text-muted-foreground">traces available</div>
            </div>
            <div>
              <div className="text-2xl font-semibold tabular-nums text-warn">{failedSpans}</div>
              <div className="text-xs text-muted-foreground">failed spans</div>
            </div>
            <div>
              <div className="text-2xl font-semibold tabular-nums text-foreground">{evaluatedRuns}</div>
              <div className="text-xs text-muted-foreground">runs scored</div>
            </div>
            <div>
              <div className="text-2xl font-semibold tabular-nums text-danger">{failedRuns}</div>
              <div className="text-xs text-muted-foreground">failed by evals</div>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// ---- Run analysis now -------------------------------------------------------

const TERMINAL_RUN_PHASES = new Set(["succeeded", "failed", "skipped", "cancelled"]);

type ActiveRun = {
  jobId: string;
  analyzer: AnalyzerKind;
  scope: AnalysisRunScope;
  startedAtMs: number;
};

type StepState = "pending" | "active" | "done" | "failed" | "skipped";

type CachedDemoAnalysisRun = {
  jobId: string;
  analyzer: AnalyzerKind;
  scope: AnalysisRunScope;
  startedAtMs: number;
  status: AnalysisRunPhase;
  proposalIds: string[];
  updatedAtMs: number;
};

let cachedDemoAnalysisRun: CachedDemoAnalysisRun | null = null;

function readCachedDemoAnalysisRun(): CachedDemoAnalysisRun | null {
  return cachedDemoAnalysisRun;
}

function writeCachedDemoAnalysisRun(run: CachedDemoAnalysisRun) {
  cachedDemoAnalysisRun = run;
}

function fmtElapsed(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}

// Derive the three pipeline nodes (Import → Analyze → Result) from the latest
// phase + the set of phases seen. Import only "happens" for importing analyzers;
// otherwise it shows as skipped once we move past it.
function computeSteps(
  status: AnalysisRunPhase,
  seen: Set<AnalysisRunPhase>,
): { import: StepState; analyze: StepState; result: StepState } {
  const term = TERMINAL_RUN_PHASES.has(status);
  const cancelled = status === "cancelled";
  const importState: StepState =
    status === "importing"
      ? "active"
      : seen.has("importing")
        ? "done"
        : status === "analyzing" || term
          ? "skipped"
          : "pending";
  const analyzeState: StepState = cancelled
    ? "skipped"
    : status === "analyzing" || status === "running"
      ? "active"
      : term
        ? "done"
        : "pending";
  const resultState: StepState =
    status === "failed"
      ? "failed"
      : cancelled
        ? "skipped"
        : status === "succeeded" || status === "skipped"
          ? "done"
          : "pending";
  return { import: importState, analyze: analyzeState, result: resultState };
}

function StepNode({ state, label }: { state: StepState; label: string }) {
  const ring =
    state === "active"
      ? "border-warn bg-warn/10 text-warn"
      : state === "done"
        ? "border-ok bg-ok/10 text-ok"
        : state === "failed"
          ? "border-danger bg-danger/10 text-danger"
          : "border-border bg-muted text-muted-foreground/60";
  return (
    <div className="flex min-w-0 flex-col items-center gap-1.5">
      <div className={cn("flex h-8 w-8 items-center justify-center rounded-full border", ring)}>
        {state === "active" ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : state === "done" ? (
          <Check className="h-4 w-4" />
        ) : state === "failed" ? (
          <X className="h-4 w-4" />
        ) : state === "skipped" ? (
          <Minus className="h-4 w-4" />
        ) : (
          <Circle className="h-2.5 w-2.5 fill-current" />
        )}
      </div>
      <span
        className={cn(
          "text-xs",
          state === "pending" || state === "skipped" ? "text-muted-foreground/60" : "font-medium text-foreground",
        )}
      >
        {label}
      </span>
    </div>
  );
}

function Connector({ filled }: { filled: boolean }) {
  return (
    <div className="mb-5 h-0.5 flex-1 rounded-full bg-border">
      <div className={cn("h-full rounded-full transition-all", filled ? "w-full bg-ok" : "w-0")} />
    </div>
  );
}

function RunProgress({
  run,
  phase,
  seen,
  running,
  nowMs,
  onCancel,
  cancelling,
  issueCount = 0,
}: {
  run: ActiveRun;
  phase: AnalysisRunEvent | null;
  seen: Set<AnalysisRunPhase>;
  running: boolean;
  nowMs: number;
  onCancel: () => void;
  cancelling: boolean;
  issueCount?: number;
}) {
  const status: AnalysisRunPhase = phase?.status ?? "running";
  const steps = computeSteps(status, seen);
  const proposals = phase?.proposal_ids ?? [];
  const elapsed = fmtElapsed(nowMs - run.startedAtMs);

  const headline =
    status === "failed"
      ? "Analysis failed —"
      : status === "cancelled"
        ? "Analysis cancelled —"
        : running
          ? "Analyzing with"
          : "Analysis complete —";

  return (
    <div className="rounded-xl border border-border bg-muted/30 p-4">
      <div className="mb-4 flex items-center gap-2.5">
        {running ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-warn" />
        ) : status === "failed" ? (
          <X className="h-4 w-4 shrink-0 text-danger" />
        ) : status === "cancelled" ? (
          <Ban className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <Check className="h-4 w-4 shrink-0 text-ok" />
        )}
        <span className="text-sm font-medium text-foreground">
          {headline} {ANALYZER_LABELS[run.analyzer]}
        </span>
        <Badge tone={phaseTone(status)} className="ml-1">
          {status}
        </Badge>
        <span className="ml-auto flex items-center gap-3">
          <span className="flex items-center gap-1.5 font-mono text-xs tabular-nums text-muted-foreground">
            <Clock className="h-3.5 w-3.5" />
            {elapsed}
          </span>
          {running && (
            <Button size="sm" variant="outline" onClick={onCancel} disabled={cancelling}>
              {cancelling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Ban className="h-3.5 w-3.5" />}
              {cancelling ? "Cancelling…" : "Cancel"}
            </Button>
          )}
        </span>
      </div>

      <div className="flex items-start">
        <StepNode state={steps.import} label="Import" />
        <Connector filled={steps.import === "done" || steps.import === "skipped"} />
        <StepNode state={steps.analyze} label="Analyze" />
        <Connector filled={steps.analyze === "done"} />
        <StepNode state={steps.result} label="Result" />
      </div>

      <div className="mt-4 border-t border-border/60 pt-3 text-sm">
        {status === "failed" ? (
          <span className="text-danger">{phase?.error ?? "The analyzer reported an error."}</span>
        ) : status === "cancelled" ? (
          <span className="text-muted-foreground">Stopped before it finished — no changes were applied.</span>
        ) : status === "skipped" ? (
          <span className="text-muted-foreground">Skipped{phase?.reason ? ` — ${phase.reason}` : ""}.</span>
        ) : status === "succeeded" ? (
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            {proposals.length > 0 ? (
              <>
                <span className="text-foreground">
                  {issueCount > 0
                    ? `Surfaced ${issueCount} issue${issueCount === 1 ? "" : "s"} and ${proposals.length} proposal${proposals.length === 1 ? "" : "s"}.`
                    : `Surfaced ${proposals.length} proposal${proposals.length === 1 ? "" : "s"} from diagnosed issues.`}
                </span>
                <Link
                  to="/issues"
                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                >
                  Review issues <ArrowRight className="h-3.5 w-3.5" />
                </Link>
                <Link
                  to="/proposals"
                  className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                >
                  Review proposals <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </>
            ) : (
              <span className="text-muted-foreground">
                No new proposals — nothing crossed gate&nbsp;#1 from this run.
              </span>
            )}
          </div>
        ) : (
          <span className="text-muted-foreground">
            {status === "importing"
              ? "Importing fresh traces…"
              : "Working through your traces — this can take a moment."}
          </span>
        )}
      </div>
    </div>
  );
}

function RunAnalysisCard({
  analyzers,
  demoMode = false,
  onBootstrapped,
  onLaunched,
}: {
  analyzers: Analyzer[];
  demoMode?: boolean;
  onBootstrapped: () => void;
  onLaunched: () => void;
}) {
  const [analyzer, setAnalyzer] = React.useState<AnalyzerKind>(
    () => analyzers.find((a) => a.installed)?.analyzer ?? "ace",
  );
  const [scope, setScope] = React.useState<AnalysisRunScope>("all");
  const [aceCommand, setAceCommand] = React.useState("ace run");
  const [submitting, setSubmitting] = React.useState(false);
  const [bootstrapping, setBootstrapping] = React.useState<AnalyzerKind | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [activeRun, setActiveRun] = React.useState<ActiveRun | null>(null);
  const [phase, setPhase] = React.useState<AnalysisRunEvent | null>(null);
  const [seen, setSeen] = React.useState<Set<AnalysisRunPhase>>(() => new Set());
  const [nowMs, setNowMs] = React.useState(() => Date.now());
  const [cancelling, setCancelling] = React.useState(false);
  const demoTimers = React.useRef<number[]>([]);

  // A launched job is "running" until it emits a terminal phase. (Until the very
  // first event arrives, an active run with no terminal phase is still running.)
  const jobRunning =
    activeRun !== null && !(phase !== null && TERMINAL_RUN_PHASES.has(phase.status));
  const running = submitting || jobRunning;

  // Live progress for the job we just launched (handler ref is kept current).
  useLiveEvent("analysis_run", (ev: AnalysisRunEvent) => {
    if (demoMode) return;
    if (activeRun && ev.job_id === activeRun.jobId) {
      setPhase(ev);
      setSeen((prev) => (prev.has(ev.status) ? prev : new Set(prev).add(ev.status)));
      if (TERMINAL_RUN_PHASES.has(ev.status)) setCancelling(false);
    }
  });

  React.useEffect(() => {
    return () => {
      demoTimers.current.forEach((id) => window.clearTimeout(id));
      demoTimers.current = [];
    };
  }, []);

  function clearDemoTimers() {
    demoTimers.current.forEach((id) => window.clearTimeout(id));
    demoTimers.current = [];
  }

  function setDemoPhase({
    jobId,
    status,
    startedAtMs,
    analyzerValue,
    scopeValue,
    proposalIds = [],
  }: {
    jobId: string;
    status: AnalysisRunPhase;
    startedAtMs: number;
    analyzerValue: AnalyzerKind;
    scopeValue: AnalysisRunScope;
    proposalIds?: string[];
  }) {
    const ev: AnalysisRunEvent = {
      job_id: jobId,
      schedule_id: null,
      analyzer: analyzerValue,
      scope: scopeValue,
      status,
      proposal_ids: proposalIds,
      at: new Date().toISOString(),
    };
    setPhase(ev);
    setSeen((prev) => (prev.has(status) ? prev : new Set(prev).add(status)));
    writeCachedDemoAnalysisRun({
      jobId,
      analyzer: analyzerValue,
      scope: scopeValue,
      startedAtMs,
      status,
      proposalIds,
      updatedAtMs: Date.now(),
    });
  }

  function scheduleDemoPhases({
    jobId,
    startedAtMs,
    analyzerValue,
    scopeValue,
  }: {
    jobId: string;
    startedAtMs: number;
    analyzerValue: AnalyzerKind;
    scopeValue: AnalysisRunScope;
  }) {
    clearDemoTimers();
    const elapsed = Date.now() - startedAtMs;
    const complete = () =>
      setDemoPhase({
        jobId,
        status: "succeeded",
        startedAtMs,
        analyzerValue,
        scopeValue,
        proposalIds: DEMO_PROPOSAL_IDS,
      });
    if (elapsed >= DEMO_ANALYSIS_COMPLETE_DELAY_MS) {
      complete();
      return;
    }
    if (elapsed < DEMO_ANALYSIS_ANALYZE_DELAY_MS) {
      demoTimers.current.push(
        window.setTimeout(
          () =>
            setDemoPhase({
              jobId,
              status: "analyzing",
              startedAtMs,
              analyzerValue,
              scopeValue,
            }),
          DEMO_ANALYSIS_ANALYZE_DELAY_MS - elapsed,
        ),
      );
    }
    demoTimers.current.push(window.setTimeout(complete, DEMO_ANALYSIS_COMPLETE_DELAY_MS - elapsed));
  }

  React.useEffect(() => {
    if (!demoMode || activeRun !== null) return;
    const cached = readCachedDemoAnalysisRun();
    if (!cached) return;
    const elapsed = Date.now() - cached.startedAtMs;
    const status =
      cached.status === "succeeded" || elapsed >= DEMO_ANALYSIS_COMPLETE_DELAY_MS
        ? "succeeded"
        : elapsed >= DEMO_ANALYSIS_ANALYZE_DELAY_MS
          ? "analyzing"
          : cached.status;
    setAnalyzer(cached.analyzer);
    setScope(cached.scope);
    setNowMs(Date.now());
    setActiveRun({
      jobId: cached.jobId,
      analyzer: cached.analyzer,
      scope: cached.scope,
      startedAtMs: cached.startedAtMs,
    });
    setSeen(
      new Set<AnalysisRunPhase>(
        status === "succeeded"
          ? ["running", "analyzing", "succeeded"]
          : status === "analyzing"
            ? ["running", "analyzing"]
            : [status],
      ),
    );
    setDemoPhase({
      jobId: cached.jobId,
      status,
      startedAtMs: cached.startedAtMs,
      analyzerValue: cached.analyzer,
      scopeValue: cached.scope,
      proposalIds: status === "succeeded" ? DEMO_PROPOSAL_IDS : [],
    });
    if (status !== "succeeded") {
      scheduleDemoPhases({
        jobId: cached.jobId,
        startedAtMs: cached.startedAtMs,
        analyzerValue: cached.analyzer,
        scopeValue: cached.scope,
      });
    }
  }, [activeRun, demoMode]);

  async function cancel() {
    if (!activeRun) return;
    setCancelling(true);
    try {
      await api.cancelAnalysis(activeRun.jobId);
      // The job emits a terminal "cancelled" phase over SSE, which clears state.
    } catch (e) {
      setError(errMessage(e));
      setCancelling(false);
    }
  }

  // Tick the elapsed timer once a second while a job is in flight.
  React.useEffect(() => {
    if (!running) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const selected = analyzers.find((a) => a.analyzer === analyzer) ?? null;
  const needsBootstrap = Boolean(selected && selected.installed && !selected.adapter_registered);
  const canRun =
    Boolean(selected && selected.installed) &&
    !needsBootstrap &&
    !running &&
    (analyzer !== "ace" || aceCommand.trim().length > 0);

  const analyzerOptions = analyzers.map((a) => ({
    value: a.analyzer,
    label: a.installed
      ? ANALYZER_LABELS[a.analyzer]
      : `${ANALYZER_LABELS[a.analyzer]} (not installed)`,
  }));

  async function bootstrap() {
    const target = analyzer;
    if (!selected || target === "ace") return;
    setBootstrapping(target);
    setError(null);
    try {
      await api.bootstrapAdapters(target);
      onBootstrapped();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBootstrapping(null);
    }
  }

  async function run() {
    setSubmitting(true);
    setError(null);
    setPhase(null);
    setSeen(new Set());
    setActiveRun(null);
    setCancelling(false);
    try {
      if (demoMode) {
        const jobId = `demo-analysis-${Date.now()}`;
        const startedAtMs = Date.now();
        clearDemoTimers();
        setActiveRun({ jobId, analyzer, scope, startedAtMs });
        setDemoPhase({
          jobId,
          status: "running",
          startedAtMs,
          analyzerValue: analyzer,
          scopeValue: scope,
        });
        scheduleDemoPhases({
          jobId,
          startedAtMs,
          analyzerValue: analyzer,
          scopeValue: scope,
        });
        onLaunched();
        return;
      }
      const body = {
        analyzer,
        scope,
        ...(analyzer === "ace"
          ? { ace_command: aceCommand.trim().split(/\s+/).filter(Boolean) }
          : {}),
      };
      const res = await api.runAnalysis(body);
      setActiveRun({ jobId: res.job_id, analyzer, scope, startedAtMs: Date.now() });
      onLaunched();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Run analysis now</CardTitle>
        <Badge tone="neutral">Respects autonomy policy</Badge>
      </CardHeader>
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Analyzer</label>
            <div className="flex items-center gap-2">
              <Select
                value={analyzer}
                onChange={(v) => {
                  setAnalyzer(v as AnalyzerKind);
                  setError(null);
                }}
                options={analyzerOptions}
                className="w-full"
                disabled={running}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Scope</label>
            <Select
              value={scope}
              onChange={(v) => setScope(v as AnalysisRunScope)}
              options={SCOPE_OPTIONS}
              className="w-full"
              disabled={running}
            />
          </div>
        </div>

        {analyzer === "ace" && (
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              ACE command
            </label>
            <Input
              value={aceCommand}
              onChange={(e) => setAceCommand(e.target.value)}
              placeholder="ace run --something"
              className="font-mono"
              disabled={running}
            />
            <p className="text-xs text-muted-foreground/70">
              Required for ACE. Space-separated; runs as the analyzer command.
            </p>
          </div>
        )}

        {selected && !selected.installed && (
          <div className="rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            {ANALYZER_LABELS[analyzer]} isn't installed. Install its command (
            <span className="font-mono">{selected.command}</span>) to enable analysis.
          </div>
        )}

        {needsBootstrap && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            <span>
              {ANALYZER_LABELS[analyzer]} is installed but its operator adapter isn't
              registered yet.
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={bootstrap}
              disabled={bootstrapping === analyzer}
            >
              {bootstrapping === analyzer ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Wrench className="h-3.5 w-3.5" />
              )}
              Register adapter
            </Button>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
            {error}
          </div>
        )}

        {activeRun && (
          <RunProgress
            run={activeRun}
            phase={phase}
            seen={seen}
            running={jobRunning}
            nowMs={nowMs}
            onCancel={cancel}
            cancelling={cancelling}
            issueCount={demoMode ? DEMO_ISSUE_COUNT : 0}
          />
        )}

        <div className="flex items-center justify-between gap-3 pt-1">
          <p className="text-xs text-muted-foreground/70">
            Proposed changes still pass the check/replay gate and your autonomy policy.
          </p>
          <Button onClick={run} disabled={!canRun}>
            {running ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            {running ? "Running…" : activeRun ? "Run again" : "Run analysis"}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

// ---- Schedules --------------------------------------------------------------

function ScheduleRow({
  schedule,
  onChanged,
}: {
  schedule: AnalysisSchedule;
  onChanged: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const cadence =
    schedule.at_time != null
      ? `every ${schedule.interval_hours}h at ${schedule.at_time}`
      : `every ${schedule.interval_hours}h`;

  return (
    <div className="border-b border-border/60 px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="neutral">{ANALYZER_LABELS[schedule.analyzer_kind as AnalyzerKind] ?? schedule.analyzer_kind}</Badge>
        <span className="text-sm text-foreground">{cadence}</span>
        {schedule.last_status && (
          <Badge tone={phaseTone(schedule.last_status)}>{schedule.last_status}</Badge>
        )}
        {schedule.refresh_import && <Badge tone="neutral">refresh import</Badge>}
        <div className="ml-auto flex items-center gap-2">
          <Switch
            checked={schedule.enabled}
            disabled={busy}
            onCheckedChange={(v) => act(() => api.updateSchedule({ id: schedule.id, enabled: v }))}
          />
          <Button
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => act(() => api.runSchedule(schedule.id))}
          >
            <Play className="h-3.5 w-3.5" />
            Run now
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => act(() => api.deleteSchedule(schedule.id))}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
        {schedule.source_path && (
          <span className="font-mono truncate">{schedule.source_path}</span>
        )}
        <span>Last run {schedule.last_run_at ? ago(schedule.last_run_at) : "never"}</span>
        {schedule.next_run_at && <span>Next {ago(schedule.next_run_at)}</span>}
      </div>
      {schedule.last_error && (
        <div className="mt-1.5 truncate text-xs text-danger">{schedule.last_error}</div>
      )}
      {error && <div className="mt-1.5 text-xs text-danger">{error}</div>}
    </div>
  );
}

function NewScheduleForm({ onCreated }: { onCreated: () => void }) {
  const [analyzer, setAnalyzer] = React.useState<"openclaw" | "hermes">("openclaw");
  const [sourcePath, setSourcePath] = React.useState("");
  const [intervalHours, setIntervalHours] = React.useState("24");
  const [atTime, setAtTime] = React.useState("");
  const [refreshImport, setRefreshImport] = React.useState(true);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const interval = Number.parseInt(intervalHours, 10);
      await api.createSchedule({
        analyzer,
        source_path: sourcePath.trim() || undefined,
        interval_hours: Number.isFinite(interval) && interval > 0 ? interval : 24,
        at_time: atTime.trim() || undefined,
        refresh_import: refreshImport,
      });
      setSourcePath("");
      setAtTime("");
      onCreated();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-t border-border/70 p-4">
      <div className="mb-2 text-xs font-medium text-muted-foreground">
        Add schedule
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Analyzer</label>
          <Select
            value={analyzer}
            onChange={(v) => setAnalyzer(v as "openclaw" | "hermes")}
            options={[
              { value: "openclaw", label: "OpenClaw" },
              { value: "hermes", label: "Hermes" },
            ]}
            className="w-full"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Source path</label>
          <Input
            value={sourcePath}
            onChange={(e) => setSourcePath(e.target.value)}
            placeholder="/path/to/source"
            className="font-mono"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">Interval (hours)</label>
          <Input
            type="number"
            min={1}
            value={intervalHours}
            onChange={(e) => setIntervalHours(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-muted-foreground">At time (HH:MM, optional)</label>
          <Input
            value={atTime}
            onChange={(e) => setAtTime(e.target.value)}
            placeholder="03:00"
          />
        </div>
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <Switch checked={refreshImport} onCheckedChange={setRefreshImport} />
          Refresh import before analyzing
        </label>
        <Button onClick={create} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
          Add schedule
        </Button>
      </div>
      {error && <div className="mt-2 text-xs text-danger">{error}</div>}
    </div>
  );
}

function SchedulesCard({
  schedules,
  loading,
  error,
  onChanged,
}: {
  schedules: AnalysisSchedule[];
  loading: boolean;
  error: Error | null;
  onChanged: () => void;
}) {
  const [expanded, setExpanded] = React.useState(false);
  const scheduleCountLabel = loading
    ? "Loading"
    : `${schedules.length.toLocaleString()} configured`;

  return (
    <Card>
      <CardHeader className="border-b-0 p-0">
        <button
          type="button"
          className={cn(
            "flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition-colors hover:bg-accent/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
            expanded ? "rounded-t-lg" : "rounded-lg",
          )}
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            {expanded ? (
              <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
            )}
            <CardTitle>Schedules</CardTitle>
            <Badge tone="neutral">{scheduleCountLabel}</Badge>
          </span>
        </button>
      </CardHeader>
      {expanded && (
        <>
          <CardBody className="p-0">
            {loading ? (
              <div className="flex items-center justify-center p-6">
                <Spinner />
              </div>
            ) : error ? (
              <ErrorNote error={error} />
            ) : schedules.length === 0 ? (
              <div className="px-4 py-5 text-sm text-muted-foreground/70">
                No schedules yet. Add one below to analyze a source on a recurring cadence.
              </div>
            ) : (
              schedules.map((s) => <ScheduleRow key={s.id} schedule={s} onChanged={onChanged} />)
            )}
            <NewScheduleForm onCreated={onChanged} />
          </CardBody>
          <div className="border-t border-border/70 px-4 py-2.5 text-xs text-muted-foreground/70">
            <CalendarClock className="mr-1.5 inline h-3.5 w-3.5 align-text-bottom" />
            Schedules only fire while the dashboard server (<span className="font-mono">kyoko serve</span>) is running.
          </div>
        </>
      )}
    </Card>
  );
}

// ---- Recent analysis runs ---------------------------------------------------

function RunsCard({
  runs,
  loading,
  error,
}: {
  runs: AnalysisRun[];
  loading: boolean;
  error: Error | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent analysis runs</CardTitle>
        {runs.length > 0 && (
          <span className="text-xs text-muted-foreground tabular-nums">{runs.length} total</span>
        )}
      </CardHeader>
      <CardBody className="p-0">
        {loading ? (
          <div className="flex items-center justify-center p-6">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : runs.length === 0 ? (
          <div className="px-4 py-5 text-sm text-muted-foreground/70">No analysis runs yet.</div>
        ) : (
          <div className="divide-y divide-border/60">
            {runs.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
                <Badge tone={phaseTone(r.status)}>{r.status}</Badge>
                <span className="text-sm font-medium text-foreground">
                  {r.operator_label ?? r.operator_kind ?? r.id}
                </span>
                {r.schedule_id && <Badge tone="neutral">scheduled</Badge>}
                {r.proposal_id && (
                  <Link
                    to="/proposals"
                    className="text-xs font-medium text-primary hover:underline"
                  >
                    View proposal
                  </Link>
                )}
                {r.status === "failed" && r.error && (
                  <span className="truncate text-xs text-danger">{r.error}</span>
                )}
                <span className="ml-auto shrink-0 text-label text-muted-foreground/70">
                  {ago(r.started_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

// ---- Page -------------------------------------------------------------------

const TERMINAL_PHASES = new Set(["succeeded", "failed", "skipped"]);

function isDemoMetrics(metrics: Record<string, unknown> | null | undefined): boolean {
  const demo = metrics?.demo as Record<string, unknown> | undefined;
  return demo?.active === true;
}

export function AnalysisPage() {
  const analyzersState = useApi(() => api.listAnalyzers(), []);
  const runsState = useApi<AnalysisRun[]>(() => api.listAnalysisRuns(), []);
  const schedulesState = useApi<AnalysisSchedule[]>(() => api.listSchedules(), []);
  const metricsState = useApi<Record<string, unknown>>(() => api.dashboardMetrics(), []);

  // When any analysis reaches a terminal phase, refresh runs (and schedules, in
  // case a scheduled job just updated its last_run/next_run).
  useLiveEvent("analysis_run", (ev: AnalysisRunEvent) => {
    if (TERMINAL_PHASES.has((ev.status ?? "").toLowerCase())) {
      runsState.reload();
      if (ev.schedule_id) schedulesState.reload();
    }
  });

  const analyzers = analyzersState.data?.analyzers ?? [];
  const demoMode = isDemoMetrics(metricsState.data);
  const analysisAnalyzers = demoMode ? DEMO_ANALYZERS : analyzers;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Analysis"
        description="Run an analyzer over your traces to surface diagnosed issues; proposal authoring is gated separately."
        icon={<Sparkles className="h-5 w-5" />}
      />
      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        <TraceCorpusCard
          metrics={metricsState.data ?? null}
          loading={metricsState.loading}
          error={metricsState.error}
        />

        {!demoMode && analyzersState.loading ? (
          <div className="flex items-center justify-center py-10">
            <Spinner />
          </div>
        ) : !demoMode && analyzersState.error ? (
          <ErrorNote error={analyzersState.error} />
        ) : (
          <RunAnalysisCard
            analyzers={analysisAnalyzers}
            demoMode={demoMode}
            onBootstrapped={() => analyzersState.reload()}
            onLaunched={() => runsState.reload()}
          />
        )}

        {!demoMode && (
          <RunsCard
            runs={runsState.data ?? []}
            loading={runsState.loading}
            error={runsState.error}
          />
        )}

        {!demoMode && (
          <SchedulesCard
            schedules={schedulesState.data ?? []}
            loading={schedulesState.loading}
            error={schedulesState.error}
            onChanged={() => schedulesState.reload()}
          />
        )}
      </div>
    </div>
  );
}
