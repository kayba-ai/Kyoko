import * as React from "react";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

export interface SelectOption {
  value: string;
  label: React.ReactNode;
}

/** Styled native select. */
export function Select({
  value,
  onChange,
  options,
  disabled,
  id,
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  options: SelectOption[];
  disabled?: boolean;
  id?: string;
  className?: string;
}) {
  return (
    <div className={cn("relative inline-flex", className)}>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "h-9 w-full appearance-none rounded-lg border border-input bg-card pl-3 pr-8 text-sm font-medium text-foreground shadow-xs transition-colors",
          "focus-visible:outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40",
          "disabled:cursor-not-allowed disabled:opacity-50",
        )}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {typeof o.label === "string" ? o.label : o.value}
          </option>
        ))}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
    </div>
  );
}
