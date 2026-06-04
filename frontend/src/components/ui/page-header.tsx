import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Consistent page header used at the top of every page. Renders a title,
 * optional description, and a right-aligned actions slot, on a sticky bar that
 * sits above the page's scrollable content.
 */
export function PageHeader({
  title,
  description,
  icon,
  actions,
  children,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  /** Optional extra row (filters, tabs) rendered below the title row. */
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-10 shrink-0 border-b border-border bg-background/80 px-6 py-4 backdrop-blur",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          {icon && (
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
              {icon}
            </div>
          )}
          <div className="min-w-0">
            <h1 className="truncate text-xl font-bold tracking-tight text-foreground">{title}</h1>
            {description && (
              <p className="mt-0.5 truncate text-sm text-muted-foreground">{description}</p>
            )}
          </div>
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      {children && <div className="mt-3">{children}</div>}
    </header>
  );
}
