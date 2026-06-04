import { useLiveConnection } from "@/hooks/useLiveBus";
import { cn } from "@/lib/utils";

const LABEL: Record<string, string> = {
  open: "Live",
  connecting: "Connecting…",
  closed: "Offline",
};

export function StatusBar() {
  const status = useLiveConnection();
  const dotClass =
    status === "open" ? "bg-ok animate-pulse-dot" : status === "connecting" ? "bg-warn" : "bg-danger";
  return (
    <div className="flex items-center justify-between border-t border-sidebar-border px-5 py-3">
      <div className="flex items-center gap-2">
        <span className={cn("h-2 w-2 rounded-full", dotClass)} />
        <span className="text-xs font-medium text-muted-foreground">{LABEL[status]}</span>
      </div>
      <span className="font-mono text-label uppercase tracking-wide text-muted-foreground/60">SSE</span>
    </div>
  );
}
