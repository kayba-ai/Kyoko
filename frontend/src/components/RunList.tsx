import type { RunSummary } from "@/lib/types";
import { ago, durationMs, fmtDuration } from "@/lib/format";
import { Badge, statusTone } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function RunList({
  runs,
  selectedId,
  onSelect,
}: {
  runs: RunSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex flex-col">
      {runs.map((run) => {
        const selected = run.id === selectedId;
        const dur = durationMs(run.started_at, run.ended_at);
        return (
          <button
            key={run.id}
            onClick={() => onSelect(run.id)}
            className={cn(
              "flex flex-col gap-1 border-b border-white/[0.04] px-3 py-2.5 text-left transition-colors",
              selected ? "bg-primary/10" : "hover:bg-white/[0.03]",
            )}
          >
            <div className="flex items-center gap-2">
              <Badge tone={statusTone(run.status)}>{run.status ?? "—"}</Badge>
              {run.agent_name && <span className="truncate text-xs font-medium text-foreground/90">{run.agent_name}</span>}
              <span className="ml-auto shrink-0 text-label text-muted-foreground/60">{ago(run.ended_at ?? run.started_at)}</span>
            </div>
            {run.summary && <div className="line-clamp-2 text-xs text-muted-foreground">{run.summary}</div>}
            <div className="flex items-center gap-2 text-label text-muted-foreground/60">
              <span>{run.span_count} spans</span>
              {run.failed_span_count > 0 && <span className="text-danger">{run.failed_span_count} failed</span>}
              {run.handoff_count > 0 && <span>{run.handoff_count} handoffs</span>}
              <span className="ml-auto font-mono">{fmtDuration(dur)}</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
