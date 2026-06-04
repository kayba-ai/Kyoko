import { useEffect, useMemo, useState } from "react";
import { ChevronRight, Radio } from "lucide-react";
import { api } from "@/lib/api";
import type { McpLogEntry } from "@/lib/types";
import { useApi } from "@/hooks/useApi";
import { useLiveConnection, useLiveEvent } from "@/hooks/useLiveBus";
import { ago, fmtDuration, tryParseJson } from "@/lib/format";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";
import { cn } from "@/lib/utils";

function directionTone(entry: McpLogEntry): NonNullable<BadgeProps["tone"]> {
  if (entry.direction === "request") return "primary";
  if (entry.direction === "response") return entry.is_error ? "danger" : "ok";
  return "neutral";
}

function Preview({ label, text }: { label: string; text: string | null }) {
  if (!text) return null;
  const parsed = tryParseJson(text);
  return (
    <div className="flex flex-col gap-1">
      <div className="text-label uppercase tracking-wide text-muted-foreground">{label}</div>
      {parsed !== null && typeof parsed === "object" ? (
        <JsonView data={parsed} />
      ) : (
        <pre className="whitespace-pre-wrap break-all font-mono text-xs text-foreground/90">{text}</pre>
      )}
    </div>
  );
}

function LogRow({ entry }: { entry: McpLogEntry }) {
  const [open, setOpen] = useState(false);
  const hasBody = Boolean(entry.params_preview || entry.result_preview || entry.is_error);

  return (
    <div className="surface overflow-hidden">
      <button
        type="button"
        onClick={() => hasBody && setOpen((o) => !o)}
        className={cn(
          "flex w-full items-center gap-2 px-3 py-2 text-left",
          hasBody && "cursor-pointer hover:bg-white/[0.02]",
        )}
      >
        <ChevronRight
          className={cn(
            "h-3 w-3 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-90",
            !hasBody && "opacity-0",
          )}
        />
        <Badge tone={directionTone(entry)}>{entry.direction}</Badge>
        <span className="truncate font-mono text-xs text-foreground">{entry.method ?? "—"}</span>
        {entry.tool_name && <Badge tone="tool">{entry.tool_name}</Badge>}
        {entry.is_error && entry.error_code !== null && (
          <Badge tone="danger">err {entry.error_code}</Badge>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
          {entry.client_id && <span className="truncate max-w-32">{entry.client_id}</span>}
          {entry.duration_ms !== null && (
            <span className="font-mono tabular-nums">{fmtDuration(entry.duration_ms)}</span>
          )}
          <span className="tabular-nums">{ago(entry.at)}</span>
        </div>
      </button>
      {open && hasBody && (
        <div className="flex flex-col gap-3 border-t border-white/[0.06] px-3 py-2.5">
          <Preview label="Params" text={entry.params_preview} />
          <Preview label="Result" text={entry.result_preview} />
        </div>
      )}
    </div>
  );
}

export function McpLogPage() {
  const initial = useApi(() => api.mcpLog({ limit: 200 }), []);
  const connection = useLiveConnection();
  const [entries, setEntries] = useState<McpLogEntry[]>([]);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (initial.data) setEntries(initial.data);
  }, [initial.data]);

  useLiveEvent("mcp_log", (entry: McpLogEntry) => {
    if (!entry || typeof entry.id !== "string") return;
    setEntries((prev) => (prev.some((e) => e.id === entry.id) ? prev : [entry, ...prev]));
  });

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(
      (e) =>
        (e.method ?? "").toLowerCase().includes(q) || (e.tool_name ?? "").toLowerCase().includes(q),
    );
  }, [entries, filter]);

  const live = connection === "open";

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Agent ↔ Kyoko</h1>
        <div className="flex items-center gap-3">
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter by tool or method…"
            className="h-7 w-56"
          />
          <span className="text-xs text-muted-foreground tabular-nums">{filtered.length}</span>
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                live ? "bg-ok animate-pulse-dot" : "bg-muted-foreground/40",
              )}
            />
            {live ? "Live" : "Offline"}
          </span>
        </div>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {initial.loading && !initial.data ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : initial.error ? (
          <ErrorNote error={initial.error} />
        ) : filtered.length === 0 ? (
          <Empty
            title={filter ? "No matching MCP traffic" : "No MCP traffic yet"}
            hint={
              filter
                ? "Try a different tool or method substring."
                : "JSON-RPC traffic appears here when a coding agent talks to Kyoko's MCP server (KYOKO_MCP_LOG=1, on by default)."
            }
            icon={<Radio className="h-6 w-6" />}
          />
        ) : (
          <div className="flex flex-col gap-1.5">
            {filtered.map((entry) => (
              <LogRow key={entry.id} entry={entry} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
