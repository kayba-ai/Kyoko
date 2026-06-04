import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-label font-semibold uppercase tracking-wide leading-none [&>svg]:size-3",
  {
    variants: {
      tone: {
        neutral: "border-border text-muted-foreground bg-muted/60",
        llm: "border-llm/25 text-llm bg-llm/10",
        tool: "border-tool/25 text-tool bg-tool/10",
        ok: "border-ok/25 text-ok bg-ok/10",
        warn: "border-warn/30 text-warn bg-warn/10",
        danger: "border-danger/30 text-danger bg-danger/10",
        primary: "border-primary/25 text-primary bg-primary/10",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

/** Map a run/span status string to a badge tone. */
export function statusTone(status: string | null | undefined): NonNullable<BadgeProps["tone"]> {
  const s = (status ?? "").toLowerCase();
  if (["succeeded", "passed", "ok", "complete", "completed", "applied"].includes(s)) return "ok";
  if (["failed", "errored", "error", "timed_out", "rejected", "invalid"].includes(s)) return "danger";
  if (["running", "in_progress", "pending", "proposed", "draft"].includes(s)) return "warn";
  return "neutral";
}
