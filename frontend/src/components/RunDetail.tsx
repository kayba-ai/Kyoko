import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { SpanTree } from "./SpanTree";
import { FlameTimeline } from "./FlameTimeline";
import { PayloadViewer } from "./PayloadViewer";
import { LiveTail } from "./LiveTail";
import { Annotations } from "./Annotations";

type NavView = "tree" | "timeline";
type InspectView = "payload" | "live" | "annotations";

export function RunDetail({ runId }: { runId: string }) {
  const { data: outline, error, loading, reload } = useApi(() => api.runOutline(runId), [runId]);
  const [nav, setNav] = useState<NavView>("tree");
  const [inspect, setInspect] = useState<InspectView>("payload");
  const [selectedSpan, setSelectedSpan] = useState<string | null>(null);

  useEffect(() => {
    setSelectedSpan(null);
  }, [runId]);

  function selectSpan(id: string) {
    setSelectedSpan(id);
    setInspect("payload");
  }

  if (loading && !outline) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (error) return <ErrorNote error={error} />;
  if (!outline) return null;

  const s = outline.summary;

  return (
    <div className="flex h-full flex-col">
      {/* Run header */}
      <div className="shrink-0 border-b border-white/[0.06] px-4 py-3">
        <div className="flex items-center gap-2">
          <Badge tone={statusTone(outline.run.status)}>{outline.run.status ?? "—"}</Badge>
          <span className="font-mono text-xs text-muted-foreground">{outline.run.id}</span>
          <button onClick={reload} className="ml-auto text-label text-muted-foreground hover:text-foreground">
            refresh
          </button>
        </div>
        {outline.run.summary && <div className="mt-1.5 text-sm text-foreground/85">{outline.run.summary}</div>}
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-label text-muted-foreground/70">
          <span>{s.spans} spans</span>
          {s.failed_spans > 0 && <span className="text-danger">{s.failed_spans} failed</span>}
          <span>{s.handoffs} handoffs</span>
          <span>{s.live_events} live events</span>
          <span>{s.annotations} annotations</span>
        </div>
        {outline.subagents.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Users className="h-3.5 w-3.5 text-muted-foreground/60" />
            {outline.subagents.map((sa) => (
              <span
                key={sa.root_span_id}
                className="rounded border border-white/10 bg-white/[0.03] px-1.5 py-0.5 text-label text-muted-foreground"
                title={`trigger: ${sa.trigger}`}
              >
                {sa.name || "subagent"}
                {sa.model ? ` · ${sa.model}` : ""} · {sa.llm_count}🧠 {sa.tool_count}🔧
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Split: navigator | inspector */}
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col border-r border-white/[0.06]">
          <div className="flex shrink-0 items-center gap-2 border-b border-white/[0.06] px-3 py-1.5">
            <Tabs
              tabs={[
                { value: "tree", label: "Span tree" },
                { value: "timeline", label: "Timeline" },
              ]}
              value={nav}
              onChange={(v) => setNav(v as NavView)}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-auto">
            {outline.span_tree.length === 0 ? (
              <Empty title="No spans" hint="This run has no captured spans." />
            ) : nav === "tree" ? (
              <SpanTree tree={outline.span_tree} selectedId={selectedSpan} onSelect={selectSpan} />
            ) : (
              <FlameTimeline tree={outline.span_tree} selectedId={selectedSpan} onSelect={selectSpan} />
            )}
          </div>
        </div>

        <div className="flex w-[44%] min-w-0 flex-col">
          <div className="flex shrink-0 items-center gap-2 border-b border-white/[0.06] px-3 py-1.5">
            <Tabs
              tabs={[
                { value: "payload", label: "Payload" },
                { value: "live", label: "Live" },
                { value: "annotations", label: "Annotations" },
              ]}
              value={inspect}
              onChange={(v) => setInspect(v as InspectView)}
            />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {inspect === "payload" ? (
              selectedSpan ? (
                <PayloadViewer spanId={selectedSpan} />
              ) : (
                <Empty title="Select a span" hint="Pick a span in the tree or timeline to inspect its redacted payload." />
              )
            ) : inspect === "live" ? (
              <LiveTail runId={runId} />
            ) : (
              <Annotations runId={runId} spanId={selectedSpan ?? undefined} />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
