// EvaluationPage: surfaces the measurement plane — evidence-only eval detectors
// (Python) and llm_eval judges. Read-only; applying lives behind the gate in
// ChecksPage. Two sub-areas in one page via tabs.

import { useState } from "react";
import { BarChart2 } from "lucide-react";
import { api } from "@/lib/api";
import type { EvalDefinition, MeasureRun } from "@/lib/types";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

// ---- Severity coloring based on direction-oriented "problem level" ----------

type ScoreTone = "ok" | "warn" | "danger" | "neutral";

/**
 * Map an aggregate numeric value to a severity tone.
 * For higher_is_better: low score = danger, mid = warn, high = ok.
 * For lower_is_better: high score = danger, mid = warn, low = ok.
 */
function scoreTone(value: number | null | undefined, direction: string): ScoreTone {
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

function fmtAggregate(run: MeasureRun): string {
  const agg = run.aggregate;
  if (!agg) return "—";
  const v = agg.value;
  if (v === null || v === undefined) return "—";
  // If it looks like a 0-1 ratio, show as %; otherwise show fixed.
  if (v >= 0 && v <= 1) return `${Math.round(v * 100)}%`;
  return String(typeof v === "number" ? v.toFixed(2) : v);
}

function directionLabel(d: string): string {
  return d === "lower_is_better" ? "↓ lower" : "↑ higher";
}

// ---- Detector (Python eval) section ----------------------------------------

function DetectorTable({
  defs,
  runs,
  loading,
  error,
  runsLoading,
  runsError,
}: {
  defs: EvalDefinition[];
  runs: MeasureRun[];
  loading: boolean;
  error: Error | null;
  runsLoading: boolean;
  runsError: Error | null;
}) {
  const [selectedDef, setSelectedDef] = useState<string | null>(null);

  if (loading || runsLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (error) return <ErrorNote error={error} />;
  if (runsError) return <ErrorNote error={runsError} />;

  if (defs.length === 0) {
    return (
      <Empty
        title="No detectors registered"
        hint="Detectors are Python eval definitions registered with kyoko eval register."
        icon={<BarChart2 className="h-5 w-5" />}
      />
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
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
      {/* Detector list */}
      <div className="surface overflow-hidden self-start">
        {defs.map((def) => {
          const run = latestRunByDef.get(def.id);
          const agg = run ? fmtAggregate(run) : null;
          const tone = run ? scoreTone(run.aggregate?.value, def.direction) : "neutral";
          const isActive = def.id === active;
          return (
            <button
              key={def.id}
              onClick={() => setSelectedDef(def.id)}
              className={cn(
                "flex w-full flex-col items-start gap-1 border-b border-white/[0.05] px-3 py-2 text-left transition-colors",
                isActive ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
              )}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <span className="truncate text-sm font-medium text-foreground">{def.name}</span>
                {agg && (
                  <Badge tone={tone} className="shrink-0">
                    {agg}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <Badge tone="neutral">{def.source}</Badge>
                <span className="text-label text-muted-foreground">{directionLabel(def.direction)}</span>
                {run && (
                  <span className="ml-auto text-label text-muted-foreground/70">{ago(run.created_at)}</span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Detail panel */}
      {detailDef && (
        <div className="flex flex-col gap-3">
          <Card>
            <CardHeader>
              <CardTitle>{detailDef.name}</CardTitle>
              <div className="flex items-center gap-1.5">
                <Badge tone={statusTone(detailDef.status)}>{detailDef.status}</Badge>
                <Badge tone="neutral">{detailDef.output_type}</Badge>
              </div>
            </CardHeader>
            <CardBody>
              <div className="mb-2 grid grid-cols-2 gap-x-6 gap-y-1.5">
                {[
                  { label: "ID", value: detailDef.id },
                  { label: "Version", value: detailDef.version },
                  { label: "Source", value: detailDef.source },
                  { label: "Unit type", value: detailDef.unit_type },
                  { label: "Direction", value: directionLabel(detailDef.direction) },
                  ...(detailDef.partner ? [{ label: "Partner", value: detailDef.partner }] : []),
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-baseline justify-between gap-2">
                    <span className="text-xs text-muted-foreground">{label}</span>
                    <span className="truncate font-mono text-xs text-foreground">{value}</span>
                  </div>
                ))}
              </div>
              {detailDef.problem_statement && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground/80">
                  {detailDef.problem_statement}
                </p>
              )}
            </CardBody>
          </Card>

          {detailRuns.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Recent runs</CardTitle>
                <span className="text-xs text-muted-foreground">{detailRuns.length} total</span>
              </CardHeader>
              <CardBody className="p-0">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.05] text-left">
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Run</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Status</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Score</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Scored / Total</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailRuns.map((run) => {
                      const agg = fmtAggregate(run);
                      const tone = scoreTone(run.aggregate?.value, detailDef.direction);
                      return (
                        <tr
                          key={run.id}
                          className="border-b border-white/[0.04] last:border-0 hover:bg-white/[0.02]"
                        >
                          <td className="px-3 py-1.5 font-mono text-foreground/80">
                            {run.id.slice(0, 12)}…
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge tone={tone}>{agg}</Badge>
                          </td>
                          <td className="px-3 py-1.5 tabular-nums text-muted-foreground">
                            {run.unit_scored} / {run.unit_total}
                          </td>
                          <td className="px-3 py-1.5 text-muted-foreground">{ago(run.created_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}

          {detailRuns.length === 0 && (
            <Empty title="No runs yet" hint="Run kyoko eval run to produce measurement data." />
          )}
        </div>
      )}
    </div>
  );
}

// ---- Judge (LLM eval) section -----------------------------------------------

function JudgeTable({
  defs,
  runs,
  loading,
  error,
  runsLoading,
  runsError,
}: {
  defs: EvalDefinition[];
  runs: MeasureRun[];
  loading: boolean;
  error: Error | null;
  runsLoading: boolean;
  runsError: Error | null;
}) {
  const [selectedDef, setSelectedDef] = useState<string | null>(null);

  if (loading || runsLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (error) return <ErrorNote error={error} />;
  if (runsError) return <ErrorNote error={runsError} />;

  if (defs.length === 0) {
    return (
      <Empty
        title="No judge templates registered"
        hint="LLM-eval judges are registered with kyoko llm-eval register."
        icon={<BarChart2 className="h-5 w-5" />}
      />
    );
  }

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
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
      {/* Judge list */}
      <div className="surface overflow-hidden self-start">
        {defs.map((def) => {
          const run = latestRunByDef.get(def.id);
          const agg = run ? fmtAggregate(run) : null;
          const tone = run ? scoreTone(run.aggregate?.value, def.direction) : "neutral";
          const isActive = def.id === active;
          return (
            <button
              key={def.id}
              onClick={() => setSelectedDef(def.id)}
              className={cn(
                "flex w-full flex-col items-start gap-1 border-b border-white/[0.05] px-3 py-2 text-left transition-colors",
                isActive ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
              )}
            >
              <div className="flex w-full items-center justify-between gap-2">
                <span className="truncate text-sm font-medium text-foreground">{def.name}</span>
                {agg && (
                  <Badge tone={tone} className="shrink-0">
                    {agg}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <Badge tone="neutral">{def.unit_type}</Badge>
                <Badge tone="neutral">{def.output_type}</Badge>
                <span className="text-label text-muted-foreground">{directionLabel(def.direction)}</span>
                {def.partner && (
                  <span className="text-label text-muted-foreground/70">via {def.partner}</span>
                )}
                {run && (
                  <span className="ml-auto text-label text-muted-foreground/70">{ago(run.created_at)}</span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {/* Detail panel */}
      {detailDef && (
        <div className="flex flex-col gap-3">
          <Card>
            <CardHeader>
              <CardTitle>{detailDef.name}</CardTitle>
              <div className="flex items-center gap-1.5">
                <Badge tone={statusTone(detailDef.status)}>{detailDef.status}</Badge>
                <Badge tone="neutral">{detailDef.output_type}</Badge>
              </div>
            </CardHeader>
            <CardBody>
              <div className="mb-2 grid grid-cols-2 gap-x-6 gap-y-1.5">
                {[
                  { label: "ID", value: detailDef.id },
                  { label: "Version", value: detailDef.version },
                  { label: "Unit type", value: detailDef.unit_type },
                  { label: "Direction", value: directionLabel(detailDef.direction) },
                  ...(detailDef.partner ? [{ label: "Partner", value: detailDef.partner }] : []),
                  ...(detailDef.vars && detailDef.vars.length > 0
                    ? [{ label: "Vars", value: detailDef.vars.join(", ") }]
                    : []),
                ].map(({ label, value }) => (
                  <div key={label} className="flex items-baseline justify-between gap-2">
                    <span className="text-xs text-muted-foreground">{label}</span>
                    <span className="truncate font-mono text-xs text-foreground">{value}</span>
                  </div>
                ))}
              </div>
              {detailDef.problem_statement && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground/80">
                  {detailDef.problem_statement}
                </p>
              )}
            </CardBody>
          </Card>

          {detailRuns.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Recent runs</CardTitle>
                <span className="text-xs text-muted-foreground">{detailRuns.length} total</span>
              </CardHeader>
              <CardBody className="p-0">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-white/[0.05] text-left">
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Run</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Status</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Score</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Scored / Total</th>
                      <th className="px-3 py-1.5 font-medium text-muted-foreground">Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detailRuns.map((run) => {
                      const agg = fmtAggregate(run);
                      const tone = scoreTone(run.aggregate?.value, detailDef.direction);
                      return (
                        <tr
                          key={run.id}
                          className="border-b border-white/[0.04] last:border-0 hover:bg-white/[0.02]"
                        >
                          <td className="px-3 py-1.5 font-mono text-foreground/80">
                            {run.id.slice(0, 12)}…
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                          </td>
                          <td className="px-3 py-1.5">
                            <Badge tone={tone}>{agg}</Badge>
                          </td>
                          <td className="px-3 py-1.5 tabular-nums text-muted-foreground">
                            {run.unit_scored} / {run.unit_total}
                          </td>
                          <td className="px-3 py-1.5 text-muted-foreground">{ago(run.created_at)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </CardBody>
            </Card>
          )}

          {detailRuns.length === 0 && (
            <Empty title="No runs yet" hint="Run kyoko llm-eval run to produce measurement data." />
          )}
        </div>
      )}
    </div>
  );
}

// ---- Page ------------------------------------------------------------------

type TabKey = "detectors" | "judges";

export function EvaluationPage() {
  const [tab, setTab] = useState<TabKey>("detectors");

  const defs = useApi(() => api.evals(), []);
  const defRuns = useApi(() => api.evalRuns(), []);
  const llmDefs = useApi(() => api.llmEvals(), []);
  const llmDefRuns = useApi(() => api.llmEvalRuns(), []);

  const detectorCount = defs.data?.length ?? 0;
  const judgeCount = llmDefs.data?.length ?? 0;

  const tabs = [
    { value: "detectors", label: `Evals — detectors (${detectorCount})` },
    { value: "judges", label: `LLM-evals — judges (${judgeCount})` },
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Evaluation</h1>
        <Tabs tabs={tabs} value={tab} onChange={(v) => setTab(v as TabKey)} />
      </div>

      <div className="flex-1 overflow-auto p-4">
        <div className="mb-3 text-xs text-muted-foreground/80">
          {tab === "detectors"
            ? "Evidence-only measurement plane. Detectors are Python eval functions that score agent runs without mutating anything — results are used as gate evidence."
            : "LLM-judge templates assess quality dimensions (instruction following, tool accuracy, verbosity, …) using a model as a grader. Results feed the same gate evidence pipeline."}
        </div>

        {tab === "detectors" ? (
          <DetectorTable
            defs={defs.data ?? []}
            runs={defRuns.data ?? []}
            loading={defs.loading}
            error={defs.error}
            runsLoading={defRuns.loading}
            runsError={defRuns.error}
          />
        ) : (
          <JudgeTable
            defs={llmDefs.data ?? []}
            runs={llmDefRuns.data ?? []}
            loading={llmDefs.loading}
            error={llmDefs.error}
            runsLoading={llmDefRuns.loading}
            runsError={llmDefRuns.error}
          />
        )}
      </div>
    </div>
  );
}
