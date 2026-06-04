import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-label font-medium uppercase tracking-wide leading-none border",
  {
    variants: {
      tone: {
        neutral: "border-white/10 text-muted-foreground bg-white/[0.03]",
        llm: "border-llm/30 text-llm bg-llm/10",
        tool: "border-tool/30 text-tool bg-tool/10",
        ok: "border-ok/30 text-ok bg-ok/10",
        warn: "border-warn/30 text-warn bg-warn/10",
        danger: "border-danger/40 text-danger bg-danger/10",
        primary: "border-primary/30 text-primary bg-primary/10",
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
