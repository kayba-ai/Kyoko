// MeasureTable: full-width overview of every measurement definition (judges or
// detectors) with its baseline, latest score, change-since-baseline, and a trend
// sparkline — Langfuse's "all evaluators at a glance" information architecture,
// rendered in Kyoko's kayba-hosted visual language. Each row expands in place to
// show config + the full run history (no persistent sidebar). Evidence-only.

import { Fragment, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, BarChart2, ChevronRight, Minus } from "lucide-react";
import type { EvalDefinition, MeasureRun } from "@/lib/types";
import { Badge, statusTone, type BadgeProps } from "@/components/ui/badge";
import { Card, CardBody } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { ago, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

// ---- Score helpers ----------------------------------------------------------

type ScoreTone = "ok" | "warn" | "danger" | "neutral";

const TONE_TEXT: Record<ScoreTone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
  neutral: "text-muted-foreground",
};

/** Map an aggregate value to a severity tone, honoring the metric's direction. */
export function scoreTone(value: number | null | undefined, direction: string): ScoreTone {
  if (value === null || value === undefined) return "neutral";
  const v = Number(value);
  if (!Number.isFinite(v)) return "neutral";
  if (direction === "lower_is_better") {
    if (v >= 0.7) return "danger";
    if (v >= 0.4) return "warn";
    return "ok";
  }
  if (v >= 0.7) return "ok";
  if (v >= 0.4) return "warn";
  return "danger";
}

function aggValue(run: MeasureRun | undefined): number | null {
  const v = run?.aggregate?.value;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** A run aggregate (0–1 → "%", else fixed). */
function fmtScore(v: number | null): string {
  if (v === null) return "—";
  if (v >= 0 && v <= 1) return `${Math.round(v * 100)}%`;
  return v.toFixed(2);
}

function fmtDelta(delta: number, ratio: boolean): string {
  const sign = delta > 0 ? "+" : "";
  if (ratio) return `${sign}${Math.round(delta * 100)}%`;
  return `${sign}${delta.toFixed(2)}`;
}

export function directionLabel(d: string): string {
  return d === "lower_is_better" ? "↓ lower is better" : "↑ higher is better";
}

// ---- Per-definition rollup (baseline → latest, trend series) ----------------

type DefStats = {
  series: number[]; // chronological aggregate values (oldest → newest)
  baseline: number | null; // earliest scored run
  latest: number | null; // most recent scored run
  delta: number | null; // latest − baseline
  improved: boolean;
  worsened: boolean;
  ratio: boolean; // values look like 0–1 ratios
  runCount: number;
  lastRun: MeasureRun | undefined;
  latestStatus: string | null;
};

function rollup(def: EvalDefinition, runs: MeasureRun[]): DefStats {
  const chrono = [...runs].sort((a, b) => (a.created_at < b.created_at ? -1 : 1));
  const series = chrono.map(aggValue).filter((v): v is number => v !== null);
  const baseline = series.length ? series[0] : null;
  const latest = series.length ? series[series.length - 1] : null;
  const delta = baseline !== null && latest !== null ? latest - baseline : null;
  const ratio =
    baseline !== null && latest !== null && baseline >= 0 && baseline <= 1 && latest >= 0 && latest <= 1;
  const better = def.direction === "lower_is_better";
  const improved = delta !== null && delta !== 0 && (better ? delta < 0 : delta > 0);
  const worsened = delta !== null && delta !== 0 && (better ? delta > 0 : delta < 0);
  const lastRun = chrono.length ? chrono[chrono.length - 1] : undefined;
  return {
    series,
    baseline,
    latest,
    delta,
    improved,
    worsened,
    ratio,
    runCount: chrono.length,
    lastRun,
    latestStatus: lastRun?.status ?? null,
  };
}

// ---- Trend sparkline --------------------------------------------------------

/** A compact inline trend of a definition's scores, with a dashed baseline ref. */
function Sparkline({ values, tone }: { values: number[]; tone: ScoreTone }) {
  const w = 108;
  const h = 30;
  const pad = 3;
  if (values.length === 0) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  if (values.length === 1) {
    return (
      <svg width={w} height={h} className={TONE_TEXT[tone]} aria-hidden>
        <circle cx={w / 2} cy={h / 2} r={3} fill="currentColor" />
      </svg>
    );
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const x = (i: number) => pad + (i / (values.length - 1)) * (w - 2 * pad);
  const y = (v: number) => h - pad - ((v - min) / range) * (h - 2 * pad);
  const points = values.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const baseY = y(values[0]);
  const last = values.length - 1;
  return (
    <svg width={w} height={h} className={TONE_TEXT[tone]} aria-hidden>
      <line
        x1={pad}
        y1={baseY}
        x2={w - pad}
        y2={baseY}
        stroke="currentColor"
        strokeWidth={1}
        strokeDasharray="3 3"
        opacity={0.3}
      />
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinejoin="round" />
      <circle cx={x(last)} cy={y(values[last])} r={2.5} fill="currentColor" />
    </svg>
  );
}

function ChangeCell({ stats, direction }: { stats: DefStats; direction: string }) {
  if (stats.delta === null) {
    return <span className="text-xs text-muted-foreground">{stats.runCount <= 1 ? "First run" : "—"}</span>;
  }
  const tone: ScoreTone = stats.improved ? "ok" : stats.worsened ? "danger" : "neutral";
  const Icon = stats.improved ? ArrowUp : stats.worsened ? ArrowDown : Minus;
  return (
    <span
      className={cn("inline-flex items-center gap-1 text-sm font-medium tabular-nums", TONE_TEXT[tone])}
      title={`vs baseline ${fmtScore(stats.baseline)} · ${directionLabel(direction)}`}
    >
      <Icon className="h-3.5 w-3.5" />
      {fmtDelta(stats.delta, stats.ratio)}
    </span>
  );
}

// ---- Expanded detail (config + run history) ---------------------------------

function MetaField({ label, value, mono = false }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span className={cn("truncate text-sm text-foreground", mono && "font-mono text-xs")}>{value}</span>
    </div>
  );
}

function ExpandedDetail({
  def,
  runs,
  showVars,
  noRunsHint,
}: {
  def: EvalDefinition;
  runs: MeasureRun[];
  showVars: boolean;
  noRunsHint: string;
}) {
  const chrono = [...runs].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)); // newest first
  return (
    <div className="grid grid-cols-1 gap-5 bg-muted/30 p-5 lg:grid-cols-[minmax(0,18rem)_1fr]">
      <div className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-x-6 gap-y-3">
          <MetaField label="ID" value={def.id} mono />
          <MetaField label="Version" value={def.version} mono />
          <MetaField label="Source" value={humanize(def.source)} />
          <MetaField label="Unit type" value={humanize(def.unit_type)} />
          <MetaField label="Direction" value={directionLabel(def.direction)} />
          {def.partner && <MetaField label="Partner" value={def.partner} />}
        </div>
        {showVars && def.vars && def.vars.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">Vars</span>
            <div className="flex flex-wrap gap-1.5">
              {def.vars.map((v) => (
                <Badge key={v} tone="neutral" className="font-mono">
                  {v}
                </Badge>
              ))}
            </div>
          </div>
        )}
        {def.problem_statement && (
          <p className="rounded-lg border border-border bg-card p-3 text-sm leading-relaxed text-muted-foreground">
            {def.problem_statement}
          </p>
        )}
      </div>

      <div className="min-w-0">
        <div className="mb-2 text-xs font-medium text-muted-foreground">Run history ({chrono.length})</div>
        {chrono.length === 0 ? (
          <Empty title="No runs yet" hint={noRunsHint} />
        ) : (
          <div className="overflow-hidden rounded-lg border border-border bg-card">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs font-medium text-muted-foreground">
                  <th className="px-3 py-2">Run</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2 text-right">Scored / total</th>
                  <th className="px-3 py-2 text-right">Created</th>
                </tr>
              </thead>
              <tbody>
                {chrono.map((run) => {
                  const v = aggValue(run);
                  return (
                    <tr key={run.id} className="border-b border-border/60 last:border-0 hover:bg-muted/50">
                      <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{run.id.slice(0, 14)}…</td>
                      <td className="px-3 py-2">
                        <Badge tone={statusTone(run.status)}>{humanize(run.status)}</Badge>
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className={cn("font-mono tabular-nums", TONE_TEXT[scoreTone(v, def.direction)])}>
                          {fmtScore(v)}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono text-xs tabular-nums text-muted-foreground">
                        {run.unit_scored} / {run.unit_total}
                      </td>
                      <td className="px-3 py-2 text-right text-xs text-muted-foreground">{ago(run.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ---- MeasureTable -----------------------------------------------------------

const TH = "px-4 py-2.5 text-left text-xs font-medium text-muted-foreground";

export function MeasureTable({
  defs,
  runs,
  loading,
  error,
  runsLoading,
  runsError,
  emptyTitle,
  emptyHint,
  typeBadges,
  showVars = false,
  noRunsHint = "Run the measurement to produce data.",
  onToggleActive,
}: {
  defs: EvalDefinition[];
  runs: MeasureRun[];
  loading: boolean;
  error: Error | null;
  runsLoading: boolean;
  runsError: Error | null;
  emptyTitle: string;
  emptyHint: string;
  /** Type/source badges shown under each definition's name. */
  typeBadges: (def: EvalDefinition) => ReactNode;
  showVars?: boolean;
  noRunsHint?: string;
  /** When provided, each row gets an active/inactive toggle (status: active ↔
   *  archived). Evidence-only config — toggling gates nothing. */
  onToggleActive?: (def: EvalDefinition, active: boolean) => Promise<unknown> | void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [pendingToggle, setPendingToggle] = useState<string | null>(null);

  async function handleToggle(def: EvalDefinition, active: boolean) {
    if (!onToggleActive) return;
    setPendingToggle(def.id);
    try {
      await onToggleActive(def, active);
    } finally {
      setPendingToggle(null);
    }
  }

  if (loading || runsLoading) {
    return (
      <div className="flex h-40 flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (error || runsError) {
    return (
      <div className="flex-1 p-6">
        <ErrorNote error={(error ?? runsError)!} />
      </div>
    );
  }
  if (defs.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Empty title={emptyTitle} hint={emptyHint} icon={<BarChart2 className="h-5 w-5" />} />
      </div>
    );
  }

  const runsByDef = new Map<string, MeasureRun[]>();
  for (const r of runs) {
    const list = runsByDef.get(r.eval_definition_id);
    if (list) list.push(r);
    else runsByDef.set(r.eval_definition_id, [r]);
  }

  // Order: most recently active definitions first.
  const ordered = [...defs].sort((a, b) => {
    const la = runsByDef.get(a.id)?.reduce((m, r) => (r.created_at > m ? r.created_at : m), "") ?? "";
    const lb = runsByDef.get(b.id)?.reduce((m, r) => (r.created_at > m ? r.created_at : m), "") ?? "";
    return la < lb ? 1 : la > lb ? -1 : a.name.localeCompare(b.name);
  });

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <Card className="overflow-hidden">
        <CardBody className="p-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className={TH}>Judge</th>
                <th className={TH}>Status</th>
                <th className={cn(TH, "text-right")}>Latest</th>
                <th className={cn(TH, "text-right")}>Baseline</th>
                <th className={cn(TH, "text-right")}>Change</th>
                <th className={TH}>Trend</th>
                <th className={cn(TH, "text-right")}>Runs</th>
                <th className={cn(TH, "text-right")}>Last run</th>
                {onToggleActive && <th className={cn(TH, "text-center")}>Active</th>}
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {ordered.map((def) => {
                const defRuns = runsByDef.get(def.id) ?? [];
                const stats = rollup(def, defRuns);
                const isOpen = expanded === def.id;
                const latestTone = scoreTone(stats.latest, def.direction);
                return (
                  <Fragment key={def.id}>
                    <tr
                      onClick={() => setExpanded(isOpen ? null : def.id)}
                      className={cn(
                        "cursor-pointer border-b border-border/60 transition-colors hover:bg-muted/50",
                        isOpen && "bg-muted/50",
                        onToggleActive && def.status !== "active" && "opacity-55",
                      )}
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium text-foreground">{def.name}</div>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">{typeBadges(def)}</div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={statusTone(def.status) as BadgeProps["tone"]}>{humanize(def.status)}</Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <span className={cn("text-base font-semibold tabular-nums", TONE_TEXT[latestTone])}>
                          {fmtScore(stats.latest)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs tabular-nums text-muted-foreground">
                        {fmtScore(stats.baseline)}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <ChangeCell stats={stats} direction={def.direction} />
                      </td>
                      <td className="px-4 py-3">
                        <Sparkline values={stats.series} tone={latestTone} />
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-muted-foreground">{stats.runCount}</td>
                      <td className="px-4 py-3 text-right text-xs text-muted-foreground">
                        {stats.lastRun ? ago(stats.lastRun.created_at) : "—"}
                      </td>
                      {onToggleActive && (
                        <td
                          className="px-4 py-3 text-center"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Switch
                            checked={def.status === "active"}
                            disabled={pendingToggle === def.id}
                            onCheckedChange={(next) => handleToggle(def, next)}
                          />
                        </td>
                      )}
                      <td className="px-2 text-muted-foreground">
                        <ChevronRight className={cn("h-4 w-4 transition-transform", isOpen && "rotate-90")} />
                      </td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <td colSpan={onToggleActive ? 10 : 9} className="border-b border-border/60 p-0">
                          <ExpandedDetail def={def} runs={defRuns} showVars={showVars} noRunsHint={noRunsHint} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </CardBody>
      </Card>
    </div>
  );
}
