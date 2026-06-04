import { useState } from "react";
import { ChevronRight, Bot, Wrench, Circle, AlertTriangle } from "lucide-react";
import type { SpanNode } from "@/lib/types";
import { durationMs, fmtDuration } from "@/lib/format";
import { cn } from "@/lib/utils";

/** duration_ms when the server provides it, else derive from timestamps. */
function spanDuration(node: SpanNode): number | null {
  return node.duration_ms ?? durationMs(node.started_at, node.ended_at);
}

/** Combined in+out token count for an llm span, or null when unknown/zero. */
function spanTokens(node: SpanNode): number | null {
  const n = node.normalized ?? {};
  const usage = node.usage ?? {};
  const inTok = (n.input_tokens as number | null | undefined) ?? (usage.input_tokens as number | undefined);
  const outTok = (n.output_tokens as number | null | undefined) ?? (usage.output_tokens as number | undefined);
  const total = (inTok ?? 0) + (outTok ?? 0);
  return total > 0 ? total : null;
}

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
  const dur = spanDuration(node);
  const tokens = kind === "llm" ? spanTokens(node) : null;
  const selected = selectedId === node.id;

  return (
    <div>
      <div
        className={cn(
          "group flex cursor-pointer items-center gap-1.5 rounded-md border-l-2 py-[4px] pr-2 text-xs transition-colors",
          selected
            ? "border-primary bg-accent"
            : "border-transparent hover:bg-muted",
          failed && !selected && "border-danger/40",
        )}
        style={{ paddingLeft: depth * 14 + 4 }}
        onClick={() => onSelect(node.id)}
      >
        <button
          className={cn(
            "flex h-4 w-4 shrink-0 items-center justify-center rounded text-muted-foreground hover:text-foreground",
            !hasChildren && "invisible",
          )}
          onClick={(e) => {
            e.stopPropagation();
            setOpen((o) => !o);
          }}
        >
          <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} />
        </button>
        <span className="flex h-4 w-4 shrink-0 items-center justify-center">{kindIcon(kind)}</span>
        <span className={cn("truncate font-mono", failed ? "font-medium text-danger" : "text-foreground")}>
          {node.name || <span className="italic text-muted-foreground">unnamed</span>}
        </span>
        {failed && <AlertTriangle className="h-3 w-3 shrink-0 text-danger" />}
        {node.model && (
          <span className="shrink-0 truncate rounded border border-llm/25 bg-llm/10 px-1 font-mono text-label text-llm">
            {node.model}
          </span>
        )}
        {tokens !== null && (
          <span
            className="shrink-0 rounded border border-border bg-muted/60 px-1 font-mono text-label text-muted-foreground"
            title="input + output tokens"
          >
            {tokens.toLocaleString()} tok
          </span>
        )}
        <span className="ml-auto shrink-0 font-mono text-label text-muted-foreground">{fmtDuration(dur)}</span>
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
