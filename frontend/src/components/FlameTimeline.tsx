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
  llm: "bg-llm/70 border-llm",
  tool: "bg-tool/70 border-tool",
  other: "bg-white/20 border-white/30",
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

  return (
    <div className="space-y-1 p-2">
      {rows.map(({ node, depth, start, end }) => {
        const left = ((start - t0) / span) * 100;
        const width = Math.max(0.6, ((end - start) / span) * 100);
        const kind = node.normalized?.kind ?? "other";
        const failed = ["failed", "errored", "error", "timed_out"].includes((node.status ?? "").toLowerCase());
        const selected = selectedId === node.id;
        return (
          <div
            key={node.id}
            className={cn("group flex h-5 cursor-pointer items-center rounded", selected && "bg-primary/10")}
            onClick={() => onSelect(node.id)}
            title={`${node.name ?? "span"} · ${fmtDuration(durationMs(node.started_at, node.ended_at))}`}
          >
            <div className="relative h-full flex-1" style={{ paddingLeft: depth * 8 }}>
              <div className="relative h-full w-full">
                <div
                  className={cn(
                    "absolute top-1/2 h-2.5 -translate-y-1/2 rounded-sm border",
                    failed ? "bg-danger/70 border-danger" : KIND_BAR[kind],
                    selected && "ring-1 ring-primary",
                  )}
                  style={{ left: `${left}%`, width: `${width}%` }}
                />
                <span
                  className="absolute top-1/2 -translate-y-1/2 truncate pl-1 text-label text-foreground/70"
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
