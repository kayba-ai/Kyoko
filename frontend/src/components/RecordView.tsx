import { useState } from "react";
import { Badge, statusTone, type BadgeProps } from "@/components/ui/badge";
import { Tabs } from "@/components/ui/tabs";
import { JsonView } from "@/components/JsonView";
import { ago, fmtTime, humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

// A friendly, structured renderer for arbitrary JSON-ish records. Instead of a
// raw JSON tree, it lays scalar fields out in a labeled grid, renders long text
// as paragraphs, primitive arrays as chips, and nested objects/arrays as titled
// inset sections. StructuredDetail wraps it with a Structured ⇄ Raw toggle.

function isComplex(v: unknown): v is object {
  return typeof v === "object" && v !== null;
}

function isLongString(v: unknown): boolean {
  return typeof v === "string" && (v.length > 80 || v.includes("\n"));
}

function isTsKey(key: string): boolean {
  return /(_at|_ts|timestamp)$/i.test(key) || ["at", "timestamp"].includes(key.toLowerCase());
}

const STATUS_KEYS = new Set([
  "status", "state", "result", "mode", "severity", "level", "trust_level",
  "direction", "kind", "role", "entity_type", "check_type", "side_effect_mode",
]);
const ID_KEY = /(^id$|_id$|_ids$|_ref$|_refs$)/i;

function severityTone(v: string): NonNullable<BadgeProps["tone"]> {
  const s = v.toLowerCase();
  if (["high", "critical", "danger", "error", "failed"].includes(s)) return "danger";
  if (["medium", "med", "warn", "warning"].includes(s)) return "warn";
  if (["low", "ok", "passed", "resolved", "active", "succeeded"].includes(s)) return "ok";
  return "neutral";
}

function toneForKey(key: string, v: string): NonNullable<BadgeProps["tone"]> {
  if (["status", "state", "result"].includes(key)) return statusTone(v);
  if (key === "severity") return severityTone(v);
  return "neutral";
}

function looksRatio(key: string): boolean {
  return /(confidence|score|ratio|rate|accuracy|prevalence|value)/i.test(key);
}

function ScalarValue({ keyName, value }: { keyName: string; value: unknown }) {
  if (value === null || value === undefined || value === "")
    return <span className="text-muted-foreground/70">—</span>;
  if (typeof value === "boolean")
    return <Badge tone={value ? "ok" : "neutral"}>{value ? "Yes" : "No"}</Badge>;
  if (typeof value === "number") {
    if (looksRatio(keyName) && value >= 0 && value <= 1)
      return <span className="font-mono tabular-nums">{Math.round(value * 100)}%</span>;
    return <span className="font-mono tabular-nums">{String(value)}</span>;
  }
  const s = String(value);
  if (isTsKey(keyName)) return <span title={fmtTime(s)}>{ago(s)}</span>;
  if (STATUS_KEYS.has(keyName)) return <Badge tone={toneForKey(keyName, s)}>{humanize(s)}</Badge>;
  if (ID_KEY.test(keyName)) return <span className="break-all font-mono text-xs">{s}</span>;
  return <span className="break-words">{s}</span>;
}

function FieldCell({ keyName, value }: { keyName: string; value: unknown }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <span className="text-xs font-medium text-muted-foreground">{humanize(keyName)}</span>
      <span className="min-w-0 text-sm text-foreground">
        <ScalarValue keyName={keyName} value={value} />
      </span>
    </div>
  );
}

function SectionShell({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground">{title}</span>
        {count !== undefined && <span className="text-xs text-muted-foreground/60">{count}</span>}
      </div>
      {children}
    </div>
  );
}

function ComplexSection({ keyName, value, depth }: { keyName: string; value: unknown; depth: number }) {
  const title = humanize(keyName);

  if (Array.isArray(value)) {
    if (value.length === 0)
      return (
        <SectionShell title={title} count={0}>
          <span className="text-sm text-muted-foreground/70">None</span>
        </SectionShell>
      );
    const allPrimitive = value.every((v) => !isComplex(v));
    if (allPrimitive)
      return (
        <SectionShell title={title} count={value.length}>
          <div className="flex flex-wrap gap-1.5">
            {value.map((v, i) => (
              <Badge key={i} tone="neutral" className="font-mono">
                {String(v)}
              </Badge>
            ))}
          </div>
        </SectionShell>
      );
    return (
      <SectionShell title={title} count={value.length}>
        <div className="space-y-2">
          {value.map((v, i) => (
            <div key={i} className="rounded-lg border border-border bg-muted/40 p-3">
              {isComplex(v) ? (
                <ObjectView obj={v as Record<string, unknown>} depth={depth + 1} />
              ) : (
                <ScalarValue keyName="" value={v} />
              )}
            </div>
          ))}
        </div>
      </SectionShell>
    );
  }

  return (
    <SectionShell title={title}>
      <div className="rounded-lg border border-border bg-muted/40 p-3">
        <ObjectView obj={value as Record<string, unknown>} depth={depth + 1} />
      </div>
    </SectionShell>
  );
}

function ObjectView({ obj, depth }: { obj: Record<string, unknown>; depth: number }) {
  const entries = Object.entries(obj);
  const scalars = entries.filter(([, v]) => !isComplex(v) && !isLongString(v));
  const longs = entries.filter(([, v]) => isLongString(v));
  const complex = entries.filter(([, v]) => isComplex(v));

  return (
    <div className="space-y-4">
      {scalars.length > 0 && (
        <div className="grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          {scalars.map(([k, v]) => (
            <FieldCell key={k} keyName={k} value={v} />
          ))}
        </div>
      )}
      {longs.map(([k, v]) => (
        <div key={k} className="space-y-1">
          <span className="text-xs font-medium text-muted-foreground">{humanize(k)}</span>
          <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-foreground">{String(v)}</p>
        </div>
      ))}
      {complex.map(([k, v]) => (
        <ComplexSection key={k} keyName={k} value={v} depth={depth} />
      ))}
    </div>
  );
}

/** Structured render of an arbitrary record (object/array/primitive). */
export function RecordView({ data, className }: { data: unknown; className?: string }) {
  let body: React.ReactNode;
  if (isComplex(data) && !Array.isArray(data)) {
    body = <ObjectView obj={data as Record<string, unknown>} depth={0} />;
  } else if (Array.isArray(data)) {
    body = <ComplexSection keyName="items" value={data} depth={0} />;
  } else {
    body = <ScalarValue keyName="" value={data} />;
  }
  return <div className={className}>{body}</div>;
}

/** RecordView with a Structured ⇄ Raw JSON toggle. */
export function StructuredDetail({
  data,
  className,
  defaultView = "structured",
}: {
  data: unknown;
  className?: string;
  defaultView?: "structured" | "raw";
}) {
  const [view, setView] = useState<"structured" | "raw">(defaultView);
  return (
    <div className={className}>
      <div className="mb-3 flex justify-end">
        <Tabs
          variant="segment"
          value={view}
          onChange={(v) => setView(v as "structured" | "raw")}
          tabs={[
            { value: "structured", label: "Structured" },
            { value: "raw", label: "Raw JSON" },
          ]}
        />
      </div>
      {view === "structured" ? (
        <RecordView data={data} />
      ) : (
        <div className={cn("rounded-lg border border-border bg-muted/60 p-3")}>
          <JsonView data={data} />
        </div>
      )}
    </div>
  );
}
