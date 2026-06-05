import * as React from "react";
import { Link } from "react-router-dom";
import {
  CalendarClock,
  Layers,
  Loader2,
  Play,
  Plus,
  Sparkles,
  Trash2,
  Wrench,
} from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  Analyzer,
  AnalyzerKind,
  AnalysisRun,
  AnalysisRunEvent,
  AnalysisRunScope,
  AnalysisSchedule,
  ConsolidationReport,
} from "@/lib/types";
import { ago } from "@/lib/format";
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

const PHASE_TONE: Record<string, NonNullable<BadgeProps["tone"]>> = {
  running: "warn",
  importing: "warn",
  analyzing: "warn",
  skipped: "neutral",
  succeeded: "ok",
  failed: "danger",
};

function phaseTone(status: string | null | undefined): NonNullable<BadgeProps["tone"]> {
  return PHASE_TONE[(status ?? "").toLowerCase()] ?? statusTone(status);
}

function errMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

// ---- Run analysis now -------------------------------------------------------

function RunAnalysisCard({
  analyzers,
  onBootstrapped,
  onLaunched,
}: {
  analyzers: Analyzer[];
  onBootstrapped: () => void;
  onLaunched: () => void;
}) {
  const [analyzer, setAnalyzer] = React.useState<AnalyzerKind>(
    () => analyzers.find((a) => a.installed)?.analyzer ?? "ace",
  );
  const [scope, setScope] = React.useState<AnalysisRunScope>("all");
  const [aceCommand, setAceCommand] = React.useState("ace run");
  const [busy, setBusy] = React.useState(false);
  const [bootstrapping, setBootstrapping] = React.useState<AnalyzerKind | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [phase, setPhase] = React.useState<AnalysisRunEvent | null>(null);

  // Live progress for the job we just launched.
  useLiveEvent("analysis_run", (ev: AnalysisRunEvent) => {
    if (jobId && ev.job_id === jobId) setPhase(ev);
  });

  const selected = analyzers.find((a) => a.analyzer === analyzer) ?? null;
  const needsBootstrap = Boolean(selected && selected.installed && !selected.adapter_registered);
  const canRun =
    Boolean(selected && selected.installed) &&
    !needsBootstrap &&
    !busy &&
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
    setBusy(true);
    setError(null);
    setPhase(null);
    setJobId(null);
    try {
      const body = {
        analyzer,
        scope,
        ...(analyzer === "ace"
          ? { ace_command: aceCommand.trim().split(/\s+/).filter(Boolean) }
          : {}),
      };
      const res = await api.runAnalysis(body);
      setJobId(res.job_id);
      onLaunched();
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
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

        {jobId && phase && (
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/50 px-3 py-2 text-xs">
            <Badge tone={phaseTone(phase.status)}>{phase.status}</Badge>
            <span className="text-muted-foreground">
              {ANALYZER_LABELS[(phase.analyzer as AnalyzerKind) ?? analyzer] ?? phase.analyzer}
              {phase.proposal_ids && phase.proposal_ids.length > 0
                ? ` · ${phase.proposal_ids.length} proposal${phase.proposal_ids.length === 1 ? "" : "s"}`
                : ""}
              {phase.reason ? ` · ${phase.reason}` : ""}
              {phase.error ? ` · ${phase.error}` : ""}
            </span>
            <span className="ml-auto font-mono text-muted-foreground/70">
              {ago(phase.at)}
            </span>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 pt-1">
          <p className="text-xs text-muted-foreground/70">
            Proposed changes still pass the check/replay gate and your autonomy policy.
          </p>
          <Button onClick={run} disabled={!canRun}>
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Run analysis
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>Schedules</CardTitle>
        <Badge tone="neutral">OpenClaw · Hermes</Badge>
      </CardHeader>
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

// ---- Skillbook consolidation ------------------------------------------------
//
// A deterministic merge/dedup pass over the skillbook. It authors proposals for
// the duplicate groups it finds; those still pass the autonomy gate. Modest by
// design — one button plus the resulting report.

function ConsolidateCard() {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [report, setReport] = React.useState<ConsolidationReport | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.consolidateSkillbook();
      setReport(res);
    } catch (e) {
      setError(errMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Consolidate skillbook</CardTitle>
        <Badge tone="neutral">Deterministic dedup</Badge>
      </CardHeader>
      <CardBody className="space-y-4">
        <p className="text-xs text-muted-foreground">
          Merge and de-duplicate skillbook entries. Authored proposals still pass the check/replay gate and your
          autonomy policy.
        </p>

        {error && (
          <div className="rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>
        )}

        {report && (
          <div className="space-y-2 rounded-lg border border-border bg-muted/50 px-3 py-2.5 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={report.duplicate_group_count > 0 ? "warn" : "ok"}>
                {report.duplicate_group_count} duplicate group{report.duplicate_group_count === 1 ? "" : "s"}
              </Badge>
              <Badge tone="neutral">
                {report.proposal_ids.length} proposal{report.proposal_ids.length === 1 ? "" : "s"}
              </Badge>
              {report.applied_proposal_ids.length > 0 && (
                <Badge tone="ok">{report.applied_proposal_ids.length} applied</Badge>
              )}
              {report.proposal_ids.length > 0 && (
                <Link to="/proposals" className="ml-auto font-medium text-primary hover:underline">
                  View proposals
                </Link>
              )}
            </div>
            {report.notes.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4 text-muted-foreground">
                {report.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex items-center justify-end pt-1">
          <Button onClick={run} disabled={busy}>
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Layers className="h-3.5 w-3.5" />}
            Consolidate
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

// ---- Page -------------------------------------------------------------------

const TERMINAL_PHASES = new Set(["succeeded", "failed", "skipped"]);

export function AnalysisPage() {
  const analyzersState = useApi(() => api.listAnalyzers(), []);
  const runsState = useApi<AnalysisRun[]>(() => api.listAnalysisRuns(), []);
  const schedulesState = useApi<AnalysisSchedule[]>(() => api.listSchedules(), []);

  // When any analysis reaches a terminal phase, refresh runs (and schedules, in
  // case a scheduled job just updated its last_run/next_run).
  useLiveEvent("analysis_run", (ev: AnalysisRunEvent) => {
    if (TERMINAL_PHASES.has((ev.status ?? "").toLowerCase())) {
      runsState.reload();
      if (ev.schedule_id) schedulesState.reload();
    }
  });

  const analyzers = analyzersState.data?.analyzers ?? [];

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Analysis"
        description="Run an analyzer over your traces to surface diagnosed issues; proposal authoring is gated separately."
        icon={<Sparkles className="h-5 w-5" />}
      />
      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {analyzersState.loading ? (
          <div className="flex items-center justify-center py-10">
            <Spinner />
          </div>
        ) : analyzersState.error ? (
          <ErrorNote error={analyzersState.error} />
        ) : (
          <RunAnalysisCard
            analyzers={analyzers}
            onBootstrapped={() => analyzersState.reload()}
            onLaunched={() => runsState.reload()}
          />
        )}

        <ConsolidateCard />

        <SchedulesCard
          schedules={schedulesState.data ?? []}
          loading={schedulesState.loading}
          error={schedulesState.error}
          onChanged={() => schedulesState.reload()}
        />

        <RunsCard
          runs={runsState.data ?? []}
          loading={runsState.loading}
          error={runsState.error}
        />
      </div>
    </div>
  );
}
