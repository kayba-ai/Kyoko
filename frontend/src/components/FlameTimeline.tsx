import { useMemo } from "react";
import type { SpanNode } from "@/lib/types";
import { parseTs, durationMs, fmtDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

interface FlatSpan {
  node: SpanNode;
  depth: number;
  start: number;
  end: number;
}

function flatten(tree: SpanNode[], depth: number, out: FlatSpan[]) {
  for (const node of tree) {
    const start = parseTs(node.started_at);
    const end = parseTs(node.ended_at) ?? start;
    if (start !== null) out.push({ node, depth, start, end: end ?? start });
    flatten(node.children, depth + 1, out);
  }
}

const KIND_BAR: Record<string, string> = {
  llm: "bg-llm/70 border-llm/60",
  tool: "bg-tool/70 border-tool/60",
  other: "bg-muted-foreground/30 border-muted-foreground/40",
};

export function FlameTimeline({
  tree,
  selectedId,
  onSelect,
}: {
  tree: SpanNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { rows, t0, span } = useMemo(() => {
    const flat: FlatSpan[] = [];
    flatten(tree, 0, flat);
    const starts = flat.map((f) => f.start);
    const ends = flat.map((f) => f.end);
    const min = starts.length ? Math.min(...starts) : 0;
    const max = ends.length ? Math.max(...ends) : min + 1;
    return { rows: flat, t0: min, span: Math.max(1, max - min) };
  }, [tree]);

  if (!rows.length) {
    return <div className="p-4 text-xs text-muted-foreground">No timed spans to chart.</div>;
  }

  // Time-axis ticks: 0%, 25%, 50%, 75%, 100% of the trace's total span.
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    pct: f * 100,
    label: f === 0 ? "0s" : fmtDuration(Math.round(span * f)),
  }));

  return (
    <div className="space-y-1 p-2">
      {/* Time axis */}
      <div className="sticky top-0 z-10 mb-1 flex h-5 items-center bg-background/95 px-1 backdrop-blur">
        <div className="relative h-full flex-1">
          {ticks.map((t) => (
            <span
              key={t.pct}
              className="absolute top-1/2 -translate-y-1/2 font-mono text-label text-muted-foreground"
              style={{
                left: `${t.pct}%`,
                transform: t.pct >= 100 ? "translate(-100%, -50%)" : "translate(0, -50%)",
              }}
            >
              {t.label}
            </span>
          ))}
        </div>
      </div>
      {rows.map(({ node, depth, start, end }) => {
        const left = ((start - t0) / span) * 100;
        const width = Math.max(0.6, ((end - start) / span) * 100);
        const kind = node.normalized?.kind ?? "other";
        const failed = ["failed", "errored", "error", "timed_out"].includes((node.status ?? "").toLowerCase());
        const selected = selectedId === node.id;
        const dur = node.duration_ms ?? durationMs(node.started_at, node.ended_at);
        const pctOfTotal = span > 0 ? Math.round(((end - start) / span) * 100) : 0;
        return (
          <div
            key={node.id}
            className={cn(
              "group flex h-6 cursor-pointer items-center rounded-md px-1 transition-colors",
              selected ? "bg-accent" : "hover:bg-muted",
            )}
            onClick={() => onSelect(node.id)}
            title={`${node.name ?? "span"}\n${fmtDuration(dur)} · ${pctOfTotal}% of trace`}
          >
            <div className="relative h-full flex-1" style={{ paddingLeft: depth * 8 }}>
              <div className="relative h-full w-full rounded-md bg-muted/50">
                <div
                  className={cn(
                    "absolute top-1/2 h-2.5 -translate-y-1/2 rounded-md border",
                    failed ? "bg-danger/70 border-danger/60" : KIND_BAR[kind],
                    selected && "ring-1 ring-primary/50",
                  )}
                  style={{ left: `${left}%`, width: `${width}%` }}
                />
                <span
                  className="absolute top-1/2 -translate-y-1/2 truncate pl-1 text-label text-muted-foreground"
                  style={{ left: `${Math.min(left, 85)}%`, maxWidth: "60%" }}
                >
                  {node.name}
                </span>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
