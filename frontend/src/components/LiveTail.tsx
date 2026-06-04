import { useEffect, useRef, useState } from "react";
import type { LiveEvent, LiveEventKind } from "@/lib/types";
import { api } from "@/lib/api";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Empty } from "@/components/ui/misc";

const KIND_TONE: Record<LiveEventKind, NonNullable<BadgeProps["tone"]>> = {
  token: "neutral",
  tool_start: "tool",
  tool_result: "tool",
  status: "primary",
  message: "neutral",
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
      <div className="flex shrink-0 items-center justify-between border-b border-border px-3 py-2">
        <Badge tone="neutral" className="normal-case">{events.length} events</Badge>
        <Button
          size="sm"
          variant={autoscroll ? "secondary" : "ghost"}
          onClick={() => setAutoscroll((v) => !v)}
          aria-pressed={autoscroll}
        >
          {autoscroll ? "Following" : "Follow"}
        </Button>
      </div>
      <div className="flex-1 overflow-auto p-2 font-mono text-xs">
        {events.map((e) => (
          <div
            key={e.id}
            className="flex animate-fade-in items-start gap-2 rounded-md px-1.5 py-1 hover:bg-muted"
          >
            <Badge tone={KIND_TONE[e.kind] ?? "neutral"}>{e.kind}</Badge>
            <span className="whitespace-pre-wrap break-all text-foreground">
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
