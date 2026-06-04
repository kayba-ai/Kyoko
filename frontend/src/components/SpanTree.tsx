import { useState } from "react";
import { ChevronRight, Bot, Wrench, Circle, AlertTriangle } from "lucide-react";
import type { SpanNode } from "@/lib/types";
import { durationMs, fmtDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

const FAILED = new Set(["failed", "errored", "error", "timed_out"]);

function kindIcon(kind: string) {
  if (kind === "llm") return <Bot className="h-3.5 w-3.5 text-llm" />;
  if (kind === "tool") return <Wrench className="h-3.5 w-3.5 text-tool" />;
  return <Circle className="h-2.5 w-2.5 text-muted-foreground" />;
}

function Row({
  node,
  depth,
  selectedId,
  onSelect,
}: {
  node: SpanNode;
  depth: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  const kind = node.normalized?.kind ?? "other";
  const failed = FAILED.has((node.status ?? "").toLowerCase());
  const dur = durationMs(node.started_at, node.ended_at);
  const selected = selectedId === node.id;

  return (
    <div>
      <div
        className={cn(
          "group flex cursor-pointer items-center gap-1 rounded py-[3px] pr-2 text-xs",
          selected ? "bg-primary/15" : "hover:bg-white/[0.04]",
        )}
        style={{ paddingLeft: depth * 14 + 4 }}
        onClick={() => onSelect(node.id)}
      >
        <button
          className={cn("flex h-4 w-4 shrink-0 items-center justify-center", !hasChildren && "invisible")}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((o) => !o);
          }}
        >
          <ChevronRight className={cn("h-3 w-3 text-muted-foreground transition-transform", open && "rotate-90")} />
        </button>
        <span className="flex h-4 w-4 shrink-0 items-center justify-center">{kindIcon(kind)}</span>
        <span className={cn("truncate", failed ? "text-danger" : "text-foreground/90")}>
          {node.name || <span className="text-muted-foreground italic">unnamed</span>}
        </span>
        {failed && <AlertTriangle className="h-3 w-3 shrink-0 text-danger" />}
        {node.model && <span className="shrink-0 truncate font-mono text-label text-muted-foreground/70">{node.model}</span>}
        <span className="ml-auto shrink-0 font-mono text-label text-muted-foreground/60">{fmtDuration(dur)}</span>
      </div>
      {hasChildren && open && (
        <div>
          {node.children.map((child) => (
            <Row key={child.id} node={child} depth={depth + 1} selectedId={selectedId} onSelect={onSelect} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SpanTree({
  tree,
  selectedId,
  onSelect,
}: {
  tree: SpanNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="py-1">
      {tree.map((node) => (
        <Row key={node.id} node={node} depth={0} selectedId={selectedId} onSelect={onSelect} />
      ))}
    </div>
  );
}
