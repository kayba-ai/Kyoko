import { useEffect, useState } from "react";
import { RotateCw, Users } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
    <div className="flex h-full flex-col gap-4 p-4">
      {/* Run header band */}
      <div className="surface shrink-0 px-4 py-3.5">
        <div className="flex items-center gap-2">
          <Badge tone={statusTone(outline.run.status)}>{outline.run.status ?? "—"}</Badge>
          <span className="truncate font-mono text-xs text-muted-foreground">{outline.run.id}</span>
          <Button variant="ghost" size="sm" onClick={reload} className="ml-auto">
            <RotateCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
        {outline.run.summary && <div className="mt-2 text-sm text-foreground">{outline.run.summary}</div>}
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>
            <span className="font-semibold text-foreground">{s.spans}</span> spans
          </span>
          {s.failed_spans > 0 && (
            <span className="font-medium text-danger">{s.failed_spans} failed</span>
          )}
          <span>
            <span className="font-semibold text-foreground">{s.handoffs}</span> handoffs
          </span>
          <span>
            <span className="font-semibold text-foreground">{s.live_events}</span> live events
          </span>
          <span>
            <span className="font-semibold text-foreground">{s.annotations}</span> annotations
          </span>
        </div>
        {outline.subagents.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border/70 pt-3">
            <Users className="h-3.5 w-3.5 text-muted-foreground" />
            {outline.subagents.map((sa) => (
              <span
                key={sa.root_span_id}
                className="rounded-md border border-border bg-muted/60 px-2 py-0.5 text-label font-medium text-muted-foreground"
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
      <div className="surface flex min-h-0 flex-1 overflow-hidden">
        <div className="flex min-w-0 flex-1 flex-col border-r border-border">
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
            <Tabs
              variant="segment"
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
          <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
            <Tabs
              variant="segment"
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
