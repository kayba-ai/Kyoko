import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ChevronDown, ChevronRight, RotateCw, Users } from "lucide-react";
import type { RunOutline, Score } from "@/lib/types";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { ago, durationMs, fmtCost, fmtDuration, fmtTime, fmtTokens } from "@/lib/format";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";
import { SpanTree } from "@/components/SpanTree";
import { FlameTimeline } from "@/components/FlameTimeline";
import { PayloadViewer } from "@/components/PayloadViewer";
import { LiveTail } from "@/components/LiveTail";
import { SpanDetail, SpanDetailEmpty, findSpan } from "@/components/SpanDetail";
import { ScoreList } from "@/components/ScoreList";
import { cn } from "@/lib/utils";

type NavView = "tree" | "timeline";
type HeaderPanel = "none" | "metadata" | "io";

function HeaderStat({ label, value, tone }: { label: string; value: ReactNode; tone?: "danger" }) {
  return (
    <div className="flex flex-col">
      <span className="text-label uppercase tracking-wide text-muted-foreground/70">{label}</span>
      <span className={cn("font-mono text-sm font-semibold", tone === "danger" ? "text-danger" : "text-foreground")}>
        {value}
      </span>
    </div>
  );
}

function TraceScores({ scores }: { scores: Score[] }) {
  if (!scores.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {scores.map((s) => {
        const label =
          s.score_bool !== null
            ? s.score_bool
              ? "true"
              : "false"
            : s.score_numeric !== null
              ? String(s.score_numeric)
              : s.status;
        const tone = s.score_bool === false || s.status === "error" ? "danger" : s.score_bool === true ? "ok" : "primary";
        return (
          <Badge key={s.id} tone={tone} className="normal-case" title={s.reasoning ?? undefined}>
            {(s.name || s.kind || "score") + ": " + label}
          </Badge>
        );
      })}
    </div>
  );
}

function Header({
  outline,
  meta,
  traceScores,
  metrics,
  externalId,
  onRefresh,
}: {
  outline: RunOutline;
  meta: Record<string, unknown> | undefined;
  traceScores: Score[];
  metrics: RunOutline["metrics"];
  externalId: string | null | undefined;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const [panel, setPanel] = useState<HeaderPanel>("none");
  const run = outline.run;
  const s = outline.summary;
  const dur = metrics?.total_duration_ms ?? durationMs(run.started_at, run.ended_at);
  const totalTok = metrics?.total_tokens ?? null;
  const hasMeta = meta && Object.keys(meta).length > 0;

  return (
    <div className="surface shrink-0 px-4 py-3.5">
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={() => navigate("/traces")} className="-ml-1.5">
          <ArrowLeft className="h-3.5 w-3.5" />
          Traces
        </Button>
        <Badge tone={statusTone(run.status)}>{run.status ?? "—"}</Badge>
        <span className="truncate font-mono text-xs text-muted-foreground">{run.id}</span>
        <Button variant="ghost" size="sm" onClick={onRefresh} className="ml-auto">
          <RotateCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {run.summary && <div className="mt-2 text-sm text-foreground">{run.summary}</div>}

      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4 lg:grid-cols-6">
        <HeaderStat label="Started" value={<span title={fmtTime(run.started_at)}>{ago(run.started_at)}</span>} />
        <HeaderStat label="Duration" value={fmtDuration(dur)} />
        <HeaderStat label="Tokens" value={fmtTokens(totalTok)} />
        <HeaderStat label="Cost" value={fmtCost(metrics?.cost_usd)} />
        <HeaderStat label="Spans" value={String(s.spans)} />
        <HeaderStat
          label="Failed"
          value={s.failed_spans > 0 ? String(s.failed_spans) : "—"}
          tone={s.failed_spans > 0 ? "danger" : undefined}
        />
      </div>

      {totalTok !== null && (
        <div className="mt-1.5 font-mono text-label text-muted-foreground">
          {fmtTokens(metrics?.input_tokens)} in · {fmtTokens(metrics?.output_tokens)} out
          {metrics?.llm_spans != null && <> · {metrics.llm_spans} llm</>}
          {metrics?.tool_spans != null && <> · {metrics.tool_spans} tool</>}
          {s.handoffs > 0 && <> · {s.handoffs} handoffs</>}
        </div>
      )}

      {traceScores.length > 0 && <div className="mt-3">
        <TraceScores scores={traceScores} />
      </div>}

      {outline.subagents.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border/70 pt-3">
          <Users className="h-3.5 w-3.5 text-muted-foreground" />
          {outline.subagents.map((sa) => (
            <span
              key={sa.root_span_id}
              className="rounded-md border border-border bg-muted/60 px-2 py-0.5 text-label font-medium text-muted-foreground"
              title={`trigger: ${sa.trigger}`}
            >
              {sa.name || "subagent"}
              {sa.model ? ` · ${sa.model}` : ""} · {sa.llm_count}🧠 {sa.tool_count}🔧
            </span>
          ))}
        </div>
      )}

      {/* Expandable detail toggles */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border/70 pt-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setPanel((p) => (p === "io" ? "none" : "io"))}
        >
          {panel === "io" ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          Input / Output
        </Button>
        {hasMeta && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setPanel((p) => (p === "metadata" ? "none" : "metadata"))}
          >
            {panel === "metadata" ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            Metadata
          </Button>
        )}
        {externalId && (
          <span className="ml-auto font-mono text-label text-muted-foreground">ext: {externalId}</span>
        )}
      </div>

      {panel === "io" && (
        <div className="mt-2 h-72 overflow-hidden rounded-lg border border-border">
          <PayloadViewer runId={run.id} />
        </div>
      )}
      {panel === "metadata" && hasMeta && (
        <div className="surface-muted mt-2 max-h-72 overflow-auto p-3">
          <JsonView data={meta} toolbar />
        </div>
      )}
    </div>
  );
}

export function TraceDetailPage() {
  const { traceId, spanId } = useParams();
  const navigate = useNavigate();
  const runId = traceId ?? "";

  const { data: outline, error, loading, reload } = useApi(() => api.runOutline(runId), [runId]);
  const { data: scoresData } = useApi(() => api.runScores(runId), [runId]);
  const { data: runs } = useApi(() => api.runs(), []);

  const [nav, setNav] = useState<NavView>("tree");
  const [rightTab, setRightTab] = useState<"span" | "live" | "scores">("span");

  const summary = useMemo(() => (runs ?? []).find((r) => r.id === runId), [runs, runId]);
  const metadata = (summary?.metadata as Record<string, unknown> | undefined) ?? {};

  const selectedSpan = useMemo(
    () => (outline && spanId ? findSpan(outline.span_tree, spanId) : null),
    [outline, spanId],
  );
  const spanScores = spanId ? scoresData?.by_span?.[spanId] ?? [] : [];

  // Reset right tab to span detail when selecting a span.
  useEffect(() => {
    if (spanId) setRightTab("span");
  }, [spanId]);

  function selectSpan(id: string) {
    navigate(`/traces/${runId}/span/${id}`);
  }

  if (loading && !outline) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (error) return <ErrorNote error={error} />;
  if (!outline) return null;

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      <Header
        outline={outline}
        meta={metadata}
        traceScores={scoresData?.trace ?? []}
        metrics={outline.metrics}
        externalId={summary?.external_id}
        onRefresh={reload}
      />

      <div className="surface flex min-h-0 flex-1 overflow-hidden">
        {/* Left: observation panel */}
        <div className="flex min-w-0 flex-1 flex-col border-r border-border">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
            <Tabs
              variant="segment"
              tabs={[
                { value: "tree", label: "Tree" },
                { value: "timeline", label: "Timeline" },
              ]}
              value={nav}
              onChange={(v) => setNav(v as NavView)}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {outline.span_tree.length === 0 ? (
              <Empty title="No spans" hint="This trace has no captured spans." />
            ) : nav === "tree" ? (
              <SpanTree tree={outline.span_tree} selectedId={spanId ?? null} onSelect={selectSpan} />
            ) : (
              <FlameTimeline tree={outline.span_tree} selectedId={spanId ?? null} onSelect={selectSpan} />
            )}
          </div>
        </div>

        {/* Right: span detail / live / trace scores */}
        <div className="flex w-[46%] min-w-0 flex-col">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
            <Tabs
              variant="segment"
              tabs={[
                { value: "span", label: "Span" },
                { value: "scores", label: "Trace scores" },
                { value: "live", label: "Live" },
              ]}
              value={rightTab}
              onChange={(v) => setRightTab(v as "span" | "live" | "scores")}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {rightTab === "span" ? (
              selectedSpan ? (
                <SpanDetail runId={runId} span={selectedSpan} scores={spanScores} />
              ) : (
                <SpanDetailEmpty />
              )
            ) : rightTab === "scores" ? (
              <div className="h-full overflow-auto">
                <ScoreList scores={scoresData?.trace ?? []} emptyText="No trace-level scores yet." />
              </div>
            ) : (
              <LiveTail runId={runId} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
