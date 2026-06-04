import * as React from "react";
import { cn } from "@/lib/utils";

export interface TabDef {
  value: string;
  label: React.ReactNode;
}

/**
 * Segmented tab control. `variant="segment"` (default) renders a muted track
 * with a raised white active pill; `variant="line"` renders an underline.
 */
export function Tabs({
  tabs,
  value,
  onChange,
  className,
  variant = "segment",
}: {
  tabs: TabDef[];
  value: string;
  onChange: (v: string) => void;
  className?: string;
  variant?: "segment" | "line";
}) {
  if (variant === "line") {
    return (
      <div className={cn("flex items-center gap-4 border-b border-border", className)}>
        {tabs.map((t) => (
          <button
            key={t.value}
            onClick={() => onChange(t.value)}
            className={cn(
              "-mb-px border-b-2 px-1 py-2 text-sm font-semibold transition-colors",
              value === t.value
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
    );
  }
  return (
    <div className={cn("inline-flex items-center gap-1 rounded-lg border border-border bg-muted/60 p-1", className)}>
      {tabs.map((t) => (
        <button
          key={t.value}
          onClick={() => onChange(t.value)}
          className={cn(
            "rounded-md px-3 py-1 text-xs font-semibold transition-colors",
            value === t.value
              ? "bg-card text-foreground shadow-xs"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
