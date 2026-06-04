import { useEffect, useRef, useState } from "react";
import type { LiveEvent, LiveEventKind } from "@/lib/types";
import { api } from "@/lib/api";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Empty } from "@/components/ui/misc";

const KIND_TONE: Record<LiveEventKind, NonNullable<BadgeProps["tone"]>> = {
  token: "neutral",
  tool_start: "tool",
  tool_result: "tool",
  status: "primary",
  message: "llm",
  error: "danger",
  other: "neutral",
};

export function LiveTail({ runId }: { runId: string }) {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [autoscroll, setAutoscroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const seen = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    seen.current = new Set();
    api.liveEvents({ runId, limit: 1000 }).then((evs) => {
      if (cancelled) return;
      for (const e of evs) seen.current.add(e.id);
      setEvents(evs);
    });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  useLiveEvent("live_event", (ev: LiveEvent) => {
    if (!ev || ev.run_id !== runId || seen.current.has(ev.id)) return;
    seen.current.add(ev.id);
    setEvents((prev) => [...prev, ev]);
  });

  useEffect(() => {
    if (autoscroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events, autoscroll]);

  if (!events.length) {
    return (
      <Empty
        title="No live events"
        hint="Token/tool/status events stream here in real time while an agent runs (POST /v1/live)."
      />
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-white/[0.06] px-3 py-1.5">
        <span className="text-label text-muted-foreground">{events.length} events</span>
        <label className="flex items-center gap-1.5 text-label text-muted-foreground">
          <input type="checkbox" checked={autoscroll} onChange={(e) => setAutoscroll(e.target.checked)} />
          follow
        </label>
      </div>
      <div className="flex-1 overflow-auto p-2 font-mono text-xs">
        {events.map((e) => (
          <div key={e.id} className="flex animate-fade-in items-start gap-2 py-0.5">
            <Badge tone={KIND_TONE[e.kind] ?? "neutral"}>{e.kind}</Badge>
            <span className="whitespace-pre-wrap break-all text-foreground/85">
              {e.content_preview}
              {e.content_truncated && <span className="text-warn"> …(truncated)</span>}
            </span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
