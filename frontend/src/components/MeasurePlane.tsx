// MeasurePlane: shared master-detail for the measurement plane (evidence-only).
// Used by DetectorsPage (Python eval detectors) and JudgesPage (llm_eval judges).
// Renders the left list + right detail; pages own their own PageHeader.

import { useState } from "react";
import { BarChart2 } from "lucide-react";
import type { EvalDefinition, MeasureRun } from "@/lib/types";
import { Badge, statusTone } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { ago, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

// ---- Severity coloring based on direction-oriented "problem level" ----------

type ScoreTone = "ok" | "warn" | "danger" | "neutral";

/**
 * Map an aggregate numeric value to a severity tone.
 * For higher_is_better: low score = danger, mid = warn, high = ok.
 * For lower_is_better: high score = danger, mid = warn, low = ok.
 */
export function scoreTone(value: number | null | undefined, direction: string): ScoreTone {
  if (value === null || value === undefined) return "neutral";
  const v = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(v)) return "neutral";
  if (direction === "lower_is_better") {
    if (v >= 0.7) return "danger";
    if (v >= 0.4) return "warn";
    return "ok";
  }
  // higher_is_better (default)
  if (v >= 0.7) return "ok";
  if (v >= 0.4) return "warn";
  return "danger";
}

export function fmtAggregate(run: MeasureRun): string {
  const agg = run.aggregate;
  if (!agg) return "—";
  const v = agg.value;
  if (v === null || v === undefined) return "—";
  // If it looks like a 0-1 ratio, show as %; otherwise show fixed.
  if (v >= 0 && v <= 1) return `${Math.round(v * 100)}%`;
  return String(typeof v === "number" ? v.toFixed(2) : v);
}

export function directionArrow(d: string): string {
  return d === "lower_is_better" ? "↓" : "↑";
}

export function directionLabel(d: string): string {
  return d === "lower_is_better" ? "↓ lower is better" : "↑ higher is better";
}

// ---- Shared building blocks -------------------------------------------------

/** Labeled key/value cell used inside the metadata grid. */
function MetaField({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium text-muted-foreground">{label}</span>
      <span
        className={cn(
          "truncate text-sm text-foreground",
          mono && "font-mono text-xs",
        )}
      >
        {value}
      </span>
    </div>
  );
}

/** The shared "Recent runs" table card. */
function RecentRunsCard({
  runs,
  direction,
}: {
  runs: MeasureRun[];
  direction: string;
}) {
  return (
    <Card className="overflow-hidden rounded-xl shadow-sm">
      <CardHeader>
        <CardTitle>Recent runs</CardTitle>
        <span className="text-xs text-muted-foreground">{runs.length} total</span>
      </CardHeader>
      <CardBody className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left">
              <th className="px-4 py-2 text-xs font-medium text-muted-foreground">Run</th>
              <th className="px-4 py-2 text-xs font-medium text-muted-foreground">Status</th>
              <th className="px-4 py-2 text-xs font-medium text-muted-foreground">Score</th>
              <th className="px-4 py-2 text-xs font-medium text-muted-foreground">Scored / Total</th>
              <th className="px-4 py-2 text-xs font-medium text-muted-foreground">Created</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const agg = fmtAggregate(run);
              const tone = scoreTone(run.aggregate?.value, direction);
              return (
                <tr
                  key={run.id}
                  className="border-b border-border/60 transition-colors last:border-0 hover:bg-muted/50"
                >
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                    {run.id.slice(0, 12)}…
                  </td>
                  <td className="px-4 py-2">
                    <Badge tone={statusTone(run.status)}>{humanize(run.status)}</Badge>
                  </td>
                  <td className="px-4 py-2">
                    <Badge tone={tone} className="font-mono">{agg}</Badge>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs tabular-nums text-muted-foreground">
                    {run.unit_scored} / {run.unit_total}
                  </td>
                  <td className="px-4 py-2 text-muted-foreground">{ago(run.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardBody>
    </Card>
  );
}

/** A single selectable row in the left-hand list. */
function ListRow({
  def,
  run,
  extraBadges,
  isActive,
  onSelect,
}: {
  def: EvalDefinition;
  run: MeasureRun | undefined;
  extraBadges: React.ReactNode;
  isActive: boolean;
  onSelect: () => void;
}) {
  const agg = run ? fmtAggregate(run) : null;
  const tone = run ? scoreTone(run.aggregate?.value, def.direction) : "neutral";
  return (
    <button
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col items-start gap-1.5 rounded-lg border px-3 py-2.5 text-left transition-colors",
        isActive
          ? "border-l-2 border-primary/40 bg-accent"
          : "border-transparent hover:bg-accent",
      )}
    >
      <div className="flex w-full items-center justify-between gap-2">
        <span className="truncate text-sm font-medium text-foreground">{def.name}</span>
        {agg && (
          <Badge tone={tone} className="shrink-0 font-mono">
            {agg}
          </Badge>
        )}
      </div>
      <div className="flex w-full items-center gap-1.5">
        {extraBadges}
        <span className="text-xs text-muted-foreground" title={directionLabel(def.direction)}>
          {directionArrow(def.direction)}
        </span>
        {run && (
          <span className="ml-auto text-xs text-muted-foreground">{ago(run.created_at)}</span>
        )}
      </div>
    </button>
  );
}

// ---- MeasurePlane -----------------------------------------------------------

export function MeasurePlane({
  defs,
  runs,
  loading,
  error,
  runsLoading,
  runsError,
  emptyTitle,
  emptyHint,
  listExtraBadges,
  showVars = false,
  noRunsHint = "Run the measurement to produce data.",
}: {
  defs: EvalDefinition[];
  runs: MeasureRun[];
  loading: boolean;
  error: Error | null;
  runsLoading: boolean;
  runsError: Error | null;
  emptyTitle: string;
  emptyHint: string;
  listExtraBadges: (def: EvalDefinition) => React.ReactNode;
  showVars?: boolean;
  noRunsHint?: string;
}) {
  const [selectedDef, setSelectedDef] = useState<string | null>(null);

  if (loading || runsLoading) {
    return (
      <div className="flex h-40 flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (error)
    return (
      <div className="flex-1 p-6">
        <ErrorNote error={error} />
      </div>
    );
  if (runsError)
    return (
      <div className="flex-1 p-6">
        <ErrorNote error={runsError} />
      </div>
    );

  if (defs.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <Empty title={emptyTitle} hint={emptyHint} icon={<BarChart2 className="h-5 w-5" />} />
      </div>
    );
  }

  // Most recent run per eval_definition_id
  const latestRunByDef = new Map<string, MeasureRun>();
  for (const r of runs) {
    const existing = latestRunByDef.get(r.eval_definition_id);
    if (!existing || r.created_at > existing.created_at) {
      latestRunByDef.set(r.eval_definition_id, r);
    }
  }

  const active = selectedDef ?? defs[0]?.id ?? null;
  const detailDef = defs.find((d) => d.id === active) ?? null;
  const detailRuns = runs
    .filter((r) => r.eval_definition_id === active)
    .sort((a, b) => (b.created_at > a.created_at ? 1 : -1));

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Definition list */}
      <div className="w-[22rem] shrink-0 space-y-1.5 overflow-y-auto border-r border-border p-3">
        {defs.map((def) => (
          <ListRow
            key={def.id}
            def={def}
            run={latestRunByDef.get(def.id)}
            isActive={def.id === active}
            onSelect={() => setSelectedDef(def.id)}
            extraBadges={listExtraBadges(def)}
          />
        ))}
      </div>

      {/* Detail panel */}
      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {detailDef && (
          <>
            <Card className="rounded-xl shadow-sm">
              <CardHeader>
                <CardTitle>{detailDef.name}</CardTitle>
                <div className="flex items-center gap-1.5">
                  <Badge tone={statusTone(detailDef.status)}>{humanize(detailDef.status)}</Badge>
                  <Badge tone="neutral">{humanize(detailDef.output_type)}</Badge>
                </div>
              </CardHeader>
              <CardBody>
                <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                  <MetaField label="ID" value={detailDef.id} mono />
                  <MetaField label="Version" value={detailDef.version} mono />
                  {!showVars && <MetaField label="Source" value={detailDef.source} />}
                  <MetaField label="Unit type" value={humanize(detailDef.unit_type)} />
                  <MetaField label="Direction" value={directionLabel(detailDef.direction)} />
                  {detailDef.partner && <MetaField label="Partner" value={detailDef.partner} />}
                </div>
                {showVars && detailDef.vars && detailDef.vars.length > 0 && (
                  <div className="mt-4 flex flex-col gap-1.5">
                    <span className="text-xs font-medium text-muted-foreground">Vars</span>
                    <div className="flex flex-wrap gap-1.5">
                      {detailDef.vars.map((v) => (
                        <Badge key={v} tone="neutral" className="font-mono">
                          {v}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {detailDef.problem_statement && (
                  <p className="mt-4 rounded-lg border border-border bg-muted/60 p-3 text-sm leading-relaxed text-muted-foreground">
                    {detailDef.problem_statement}
                  </p>
                )}
              </CardBody>
            </Card>

            {detailRuns.length > 0 ? (
              <RecentRunsCard runs={detailRuns} direction={detailDef.direction} />
            ) : (
              <Empty title="No runs yet" hint={noRunsHint} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
