import { useEffect, useState } from "react";
import { Bot, Wrench, Circle } from "lucide-react";
import type { Score, SpanNode } from "@/lib/types";
import { durationMs, fmtDuration, fmtTokens } from "@/lib/format";
import { Badge, statusTone } from "@/components/ui/badge";
import { Tabs } from "@/components/ui/tabs";
import { Empty } from "@/components/ui/misc";
import { PayloadViewer } from "@/components/PayloadViewer";
import { ChatMessages } from "@/components/ChatMessages";
import { ScoreList } from "@/components/ScoreList";
import { Annotations } from "@/components/Annotations";

type DetailTab = "messages" | "input" | "output" | "scores" | "annotations";

function kindIcon(kind: string) {
  if (kind === "llm") return <Bot className="h-4 w-4 text-llm" />;
  if (kind === "tool") return <Wrench className="h-4 w-4 text-tool" />;
  return <Circle className="h-3 w-3 text-muted-foreground" />;
}

/** Find a span by id anywhere in the tree. */
export function findSpan(tree: SpanNode[], id: string): SpanNode | null {
  for (const node of tree) {
    if (node.id === id) return node;
    const hit = findSpan(node.children, id);
    if (hit) return hit;
  }
  return null;
}

function ParamChip({ label, value }: { label: string; value: unknown }) {
  if (value === null || value === undefined || value === "") return null;
  const text = Array.isArray(value) ? value.join(", ") : String(value);
  if (!text) return null;
  return (
    <span className="rounded border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-label text-muted-foreground">
      {label}: <span className="text-foreground">{text}</span>
    </span>
  );
}

export function SpanDetail({
  runId,
  span,
  scores,
}: {
  runId: string;
  span: SpanNode;
  scores: Score[];
}) {
  const [tab, setTab] = useState<DetailTab>("messages");
  const n = span.normalized ?? { kind: "other", adapter: "" };

  // Reset to the most useful tab when switching spans.
  useEffect(() => {
    setTab("messages");
  }, [span.id]);

  const dur = span.duration_ms ?? durationMs(span.started_at, span.ended_at);
  const usage = span.usage ?? {};
  const inTok = (n.input_tokens as number | null | undefined) ?? (usage.input_tokens as number | undefined) ?? null;
  const outTok = (n.output_tokens as number | null | undefined) ?? (usage.output_tokens as number | undefined) ?? null;
  const totalTok = inTok !== null || outTok !== null ? (inTok ?? 0) + (outTok ?? 0) : null;
  const model = n.model || span.model;
  const params = n.params ?? {};

  const tabs = [
    { value: "messages", label: "Messages" },
    { value: "input", label: "Input" },
    { value: "output", label: "Output" },
    { value: "scores", label: "Scores" },
    { value: "annotations", label: "Annotations" },
  ];

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="shrink-0 space-y-2 border-b border-border px-3 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="flex h-5 w-5 items-center justify-center">{kindIcon(n.kind)}</span>
          <span className="truncate font-mono text-sm font-semibold text-foreground">
            {span.name || <span className="italic text-muted-foreground">unnamed span</span>}
          </span>
          {span.status && <Badge tone={statusTone(span.status)}>{span.status}</Badge>}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-label text-muted-foreground">
          {model && (
            <span className="rounded border border-llm/25 bg-llm/10 px-1.5 py-0.5 font-mono text-llm">{model}</span>
          )}
          <span className="font-mono">{fmtDuration(dur)}</span>
          {totalTok !== null && (
            <span title="input · output · total" className="font-mono">
              {fmtTokens(inTok)} in · {fmtTokens(outTok)} out · {fmtTokens(totalTok)} tok
            </span>
          )}
        </div>
        {n.kind === "llm" && (
          <div className="flex flex-wrap items-center gap-1.5">
            <ParamChip label="temp" value={params.temperature} />
            <ParamChip label="top_p" value={params.top_p} />
            <ParamChip label="max_tokens" value={params.max_tokens} />
            <ParamChip label="freq_pen" value={params.frequency_penalty} />
            <ParamChip label="pres_pen" value={params.presence_penalty} />
            <ParamChip label="finish" value={params.finish_reasons} />
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="shrink-0 border-b border-border px-3 py-2">
        <Tabs variant="segment" tabs={tabs} value={tab} onChange={(v) => setTab(v as DetailTab)} />
      </div>

      {/* Body */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "messages" ? (
          <div className="h-full overflow-auto">
            <ChatMessages node={span} />
          </div>
        ) : tab === "input" ? (
          <PayloadViewer key={`${span.id}-in`} spanId={span.id} initialTarget="input" />
        ) : tab === "output" ? (
          <PayloadViewer key={`${span.id}-out`} spanId={span.id} initialTarget="output" />
        ) : tab === "scores" ? (
          <div className="h-full overflow-auto">
            <ScoreList scores={scores} emptyText="No scores yet for this span." />
          </div>
        ) : (
          <Annotations runId={runId} spanId={span.id} />
        )}
      </div>
    </div>
  );
}

export function SpanDetailEmpty() {
  return (
    <Empty
      title="Select a span"
      hint="Pick a span in the tree or timeline to inspect its messages, payloads, and scores."
    />
  );
}
