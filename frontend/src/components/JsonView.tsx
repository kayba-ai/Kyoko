import * as React from "react";
import { ChevronRight, Check, Copy, ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

// Collapsible JSON tree viewer. Renders strings/numbers/bools inline; objects and
// arrays are expandable. Keeps the first two levels open by default. The optional
// toolbar adds Copy + expand-all / collapse-all controls.

function isCollapsible(v: unknown): v is object {
  return typeof v === "object" && v !== null;
}

function Primitive({ value }: { value: unknown }) {
  if (value === null) return <span className="italic text-muted-foreground">null</span>;
  switch (typeof value) {
    case "string":
      return <span className="break-all text-ok">"{value}"</span>;
    case "number":
      return <span className="text-llm">{String(value)}</span>;
    case "boolean":
      return <span className="text-tool">{String(value)}</span>;
    default:
      return <span className="text-foreground">{String(value)}</span>;
  }
}

// `force` is a tuple [generation, open?] — when generation changes, every node
// resets its open state to the forced value (expand-all / collapse-all).
type Force = { gen: number; open: boolean | null };

function Node({
  name,
  value,
  depth,
  force,
}: {
  name?: string | number;
  value: unknown;
  depth: number;
  force: Force;
}) {
  const collapsible = isCollapsible(value);
  const [open, setOpen] = React.useState(depth < 2);
  // Apply expand-all / collapse-all when the force generation changes.
  React.useEffect(() => {
    if (force.open !== null) setOpen(force.open);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [force.gen]);

  const entries = collapsible
    ? Array.isArray(value)
      ? value.map((v, i) => [i, v] as const)
      : Object.entries(value as Record<string, unknown>)
    : [];
  const isArray = Array.isArray(value);

  return (
    <div className="leading-relaxed">
      <div
        className={cn("flex items-start gap-1 rounded", collapsible && "cursor-pointer hover:bg-muted")}
        onClick={collapsible ? () => setOpen((o) => !o) : undefined}
      >
        {collapsible ? (
          <ChevronRight className={cn("mt-[3px] h-3 w-3 shrink-0 text-muted-foreground transition-transform", open && "rotate-90")} />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        <span className="font-mono text-xs">
          {name !== undefined && <span className="font-medium text-foreground">{name}</span>}
          {name !== undefined && <span className="text-muted-foreground">: </span>}
          {collapsible ? (
            <span className="text-muted-foreground">
              {isArray ? `[${entries.length}]` : `{${entries.length}}`}
            </span>
          ) : (
            <Primitive value={value} />
          )}
        </span>
      </div>
      {collapsible && open && (
        <div className="ml-3 border-l border-border pl-2">
          {entries.map(([k, v]) => (
            <Node key={String(k)} name={k} value={v} depth={depth + 1} force={force} />
          ))}
        </div>
      )}
    </div>
  );
}

export function JsonView({
  data,
  className,
  toolbar = false,
}: {
  data: unknown;
  className?: string;
  /** Show a Copy + expand-all / collapse-all toolbar above the tree. */
  toolbar?: boolean;
}) {
  const [force, setForce] = React.useState<Force>({ gen: 0, open: null });
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // clipboard unavailable — ignore
    }
  }

  return (
    <div className={cn("font-mono text-xs", className)}>
      {toolbar && (
        <div className="mb-1.5 flex items-center gap-1">
          <button
            type="button"
            onClick={() => setForce((f) => ({ gen: f.gen + 1, open: true }))}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-label font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="Expand all"
          >
            <ChevronsUpDown className="h-3 w-3" />
            Expand
          </button>
          <button
            type="button"
            onClick={() => setForce((f) => ({ gen: f.gen + 1, open: false }))}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-label font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="Collapse all"
          >
            <ChevronsDownUp className="h-3 w-3" />
            Collapse
          </button>
          <button
            type="button"
            onClick={copy}
            className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-label font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            title="Copy JSON"
          >
            {copied ? <Check className="h-3 w-3 text-ok" /> : <Copy className="h-3 w-3" />}
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}
      <Node value={data} depth={0} force={force} />
    </div>
  );
}
