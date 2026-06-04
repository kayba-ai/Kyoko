import type { Score } from "@/lib/types";
import { Badge, type BadgeProps } from "@/components/ui/badge";

// Renders measurement-plane scores (numeric or boolean) attached to a trace or
// span, with the judge/detector reasoning when present. Observation-only.

function scoreValue(s: Score): { label: string; tone: NonNullable<BadgeProps["tone"]> } {
  if (s.score_bool !== null) {
    return s.score_bool ? { label: "true", tone: "ok" } : { label: "false", tone: "danger" };
  }
  if (s.score_numeric !== null) {
    const v = s.score_numeric;
    const label = Number.isInteger(v) ? String(v) : v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
    return { label, tone: "primary" };
  }
  if (s.status === "skipped") return { label: "skipped", tone: "neutral" };
  if (s.status === "error") return { label: "error", tone: "danger" };
  return { label: "—", tone: "neutral" };
}

export function ScoreList({ scores, emptyText }: { scores: Score[]; emptyText: string }) {
  if (!scores.length) {
    return <div className="p-4 text-center text-xs text-muted-foreground">{emptyText}</div>;
  }
  return (
    <div className="space-y-2 p-3">
      {scores.map((s) => {
        const v = scoreValue(s);
        return (
          <div key={s.id} className="rounded-lg border border-border bg-muted/40 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="truncate text-xs font-semibold text-foreground">{s.name || s.kind || "score"}</span>
              {s.unit_type && (
                <span className="text-label text-muted-foreground">{s.unit_type}</span>
              )}
              <Badge tone={v.tone} className="ml-auto font-mono normal-case">
                {v.label}
              </Badge>
            </div>
            {s.reasoning && (
              <div className="mt-1.5 whitespace-pre-wrap break-words text-xs text-muted-foreground">{s.reasoning}</div>
            )}
          </div>
        );
      })}
    </div>
  );
}
