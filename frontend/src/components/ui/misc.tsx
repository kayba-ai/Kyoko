import * as React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export function Separator({ className, vertical }: { className?: string; vertical?: boolean }) {
  return (
    <div
      className={cn(vertical ? "w-px self-stretch" : "h-px w-full", "bg-white/[0.07]", className)}
      role="separator"
    />
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("h-4 w-4 animate-spin text-muted-foreground", className)} />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded bg-white/[0.05]", className)} />;
}

export function Empty({ title, hint, icon }: { title: string; hint?: string; icon?: React.ReactNode }) {
  return (
    <div className="flex h-full min-h-32 flex-col items-center justify-center gap-2 p-8 text-center">
      {icon && <div className="text-muted-foreground/50">{icon}</div>}
      <div className="text-sm font-medium text-muted-foreground">{title}</div>
      {hint && <div className="max-w-sm text-xs text-muted-foreground/70">{hint}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: Error }) {
  return (
    <div className="m-3 rounded-md border border-danger/30 bg-danger/10 p-3 text-xs text-danger">
      {error.message}
    </div>
  );
}

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-white/10 bg-white/[0.04] px-1 py-0.5 font-mono text-label text-muted-foreground">
      {children}
    </kbd>
  );
}
