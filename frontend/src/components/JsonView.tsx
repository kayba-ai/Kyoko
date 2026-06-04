import * as React from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// Collapsible JSON tree viewer. Renders strings/numbers/bools inline; objects and
// arrays are expandable. Keeps the first two levels open by default.

function isCollapsible(v: unknown): v is object {
  return typeof v === "object" && v !== null;
}

function Primitive({ value }: { value: unknown }) {
  if (value === null) return <span className="text-muted-foreground/60">null</span>;
  switch (typeof value) {
    case "string":
      return <span className="text-ok/90 break-all">"{value}"</span>;
    case "number":
      return <span className="text-llm">{String(value)}</span>;
    case "boolean":
      return <span className="text-tool">{String(value)}</span>;
    default:
      return <span>{String(value)}</span>;
  }
}

function Node({ name, value, depth }: { name?: string | number; value: unknown; depth: number }) {
  const [open, setOpen] = React.useState(depth < 2);
  const collapsible = isCollapsible(value);
  const entries = collapsible
    ? Array.isArray(value)
      ? value.map((v, i) => [i, v] as const)
      : Object.entries(value as Record<string, unknown>)
    : [];
  const isArray = Array.isArray(value);

  return (
    <div className="leading-relaxed">
      <div
        className={cn("flex items-start gap-1", collapsible && "cursor-pointer hover:bg-white/[0.03] rounded")}
        onClick={collapsible ? () => setOpen((o) => !o) : undefined}
      >
        {collapsible ? (
          <ChevronRight className={cn("mt-[3px] h-3 w-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span className="font-mono text-xs">
          {name !== undefined && <span className="text-primary/80">{name}</span>}
          {name !== undefined && <span className="text-muted-foreground/60">: </span>}
          {collapsible ? (
            <span className="text-muted-foreground/60">
              {isArray ? `[${entries.length}]` : `{${entries.length}}`}
            </span>
          ) : (
            <Primitive value={value} />
          )}
        </span>
      </div>
      {collapsible && open && (
        <div className="ml-3 border-l border-white/[0.06] pl-2">
          {entries.map(([k, v]) => (
            <Node key={String(k)} name={k} value={v} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export function JsonView({ data, className }: { data: unknown; className?: string }) {
  return (
    <div className={cn("font-mono text-xs", className)}>
      <Node value={data} depth={0} />
    </div>
  );
}
