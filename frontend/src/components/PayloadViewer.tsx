import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import type { RunPayload, SpanPayload } from "@/lib/types";
import { fmtBytes, tryParseJson } from "@/lib/format";
import { Tabs } from "@/components/ui/tabs";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";

// Reads an input/output payload from /api/span-payload or /api/run-payload (already
// redacted + sliceable server-side). Lets the user toggle input/output, apply a
// dotted path (e.g. messages.0.content), switch Pretty ⇄ Raw, copy, and highlight
// a search term. Pass exactly one of `spanId` / `runId`.

function highlight(text: string, term: string) {
  const q = term.trim();
  if (!q) return text;
  const parts: (string | JSX.Element)[] = [];
  const lower = text.toLowerCase();
  const ql = q.toLowerCase();
  let i = 0;
  let key = 0;
  while (i < text.length) {
    const idx = lower.indexOf(ql, i);
    if (idx === -1) {
      parts.push(text.slice(i));
      break;
    }
    if (idx > i) parts.push(text.slice(i, idx));
    parts.push(
      <mark key={key++} className="rounded-sm bg-warn/30 text-foreground">
        {text.slice(idx, idx + q.length)}
      </mark>,
    );
    i = idx + q.length;
  }
  return parts;
}

export function PayloadViewer({
  spanId,
  runId,
  searchTerm = "",
  initialTarget = "input",
}: {
  spanId?: string;
  runId?: string;
  searchTerm?: string;
  initialTarget?: "input" | "output";
}) {
  const [target, setTarget] = useState<"input" | "output">(initialTarget);
  const [path, setPath] = useState("");
  const [appliedPath, setAppliedPath] = useState("");
  const [view, setView] = useState<"pretty" | "raw">("pretty");
  const [copied, setCopied] = useState(false);

  const key = spanId ?? runId ?? "";
  const { data, error, loading } = useApi<SpanPayload | RunPayload>(() => {
    const opts = { target, path: appliedPath || undefined, maxChars: 20000 };
    return spanId ? api.spanPayload(spanId, opts) : api.runPayload(runId!, opts);
  }, [key, target, appliedPath]);

  const parsed = data?.available ? tryParseJson(data.content) : null;
  const isJson = parsed !== null && typeof parsed === "object";

  async function copy() {
    if (!data?.content) return;
    try {
      await navigator.clipboard.writeText(data.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2.5">
        <Tabs
          variant="segment"
          tabs={[
            { value: "input", label: "Input" },
            { value: "output", label: "Output" },
          ]}
          value={target}
          onChange={(v) => setTarget(v as "input" | "output")}
        />
        <form
          className="flex flex-1 items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            setAppliedPath(path.trim());
          }}
        >
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="path e.g. messages.0.content"
            className="h-7 font-mono text-xs"
          />
        </form>
        {isJson && (
          <Tabs
            variant="segment"
            tabs={[
              { value: "pretty", label: "Pretty" },
              { value: "raw", label: "Raw" },
            ]}
            value={view}
            onChange={(v) => setView(v as "pretty" | "raw")}
          />
        )}
        <button
          type="button"
          onClick={copy}
          disabled={!data?.available}
          className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-card px-2 text-label font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-50"
          title="Copy payload"
        >
          {copied ? <Check className="h-3 w-3 text-ok" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
        {data?.available && data.media_type && (
          <Badge tone="neutral">{data.media_type.replace("application/", "")}</Badge>
        )}
        {data?.available && data.size_bytes !== undefined && (
          <Badge tone="neutral" className="font-mono normal-case">{fmtBytes(data.size_bytes)}</Badge>
        )}
      </div>
      <div className="flex-1 overflow-auto p-3">
        {loading && !data ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : !data?.available ? (
          <Empty title={`No ${target} payload`} hint="No captured payload for the selected side." />
        ) : isJson && view === "pretty" ? (
          <div className="surface-muted p-3">
            <JsonView data={parsed} toolbar />
          </div>
        ) : (
          <pre className="whitespace-pre-wrap break-all rounded-lg border border-border bg-muted/60 p-3 font-mono text-xs text-foreground">
            {searchTerm ? highlight(data.content ?? "", searchTerm) : data.content}
          </pre>
        )}
        {data?.truncated && (
          <div className="mt-2">
            <Badge tone="warn">payload truncated</Badge>
          </div>
        )}
      </div>
    </div>
  );
}
