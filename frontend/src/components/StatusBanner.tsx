import type { ReactNode } from "react";
import {
  AlertTriangle,
  Archive,
  CheckCircle2,
  Eye,
  Loader2,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Narration, StageKind, Tone } from "@/lib/narrate";
import { cn } from "@/lib/utils";

// Renders a Narration as the page's headline element: an icon, the stage label,
// a plain-English description of what's happening, and what to do next. This is
// the "understand it at a glance" surface that every other detail sits beneath.

const ICONS: Record<StageKind, LucideIcon> = {
  review: Eye,
  drafting: Loader2,
  ready: Sparkles,
  applied: CheckCircle2,
  guarded: ShieldCheck,
  resolved: CheckCircle2,
  dismissed: Archive,
  escalated: AlertTriangle,
  failed: XCircle,
};

const TONE_STYLES: Record<Tone, { border: string; bg: string; iconBg: string; icon: string; label: string }> = {
  primary: { border: "border-primary/30", bg: "bg-primary/5", iconBg: "bg-primary/15", icon: "text-primary", label: "text-primary" },
  ok: { border: "border-ok/30", bg: "bg-ok/5", iconBg: "bg-ok/15", icon: "text-ok", label: "text-ok" },
  warn: { border: "border-warn/30", bg: "bg-warn/5", iconBg: "bg-warn/15", icon: "text-warn", label: "text-warn" },
  danger: { border: "border-danger/30", bg: "bg-danger/5", iconBg: "bg-danger/15", icon: "text-danger", label: "text-danger" },
  neutral: { border: "border-border", bg: "bg-muted/40", iconBg: "bg-muted", icon: "text-muted-foreground", label: "text-muted-foreground" },
};

export function StatusBanner({ narration, actions }: { narration: Narration; actions?: ReactNode }) {
  const Icon = ICONS[narration.kind];
  const s = TONE_STYLES[narration.tone];
  const spin = narration.kind === "drafting";
  return (
    <div className={cn("rounded-xl border p-4", s.border, s.bg)}>
      <div className="flex items-start gap-3.5">
        <div className={cn("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full", s.iconBg)}>
          <Icon className={cn("h-5 w-5", s.icon, spin && "animate-spin")} />
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          <div className={cn("text-label font-semibold uppercase tracking-wide", s.label)}>{narration.stage}</div>
          <p className="text-sm font-medium leading-relaxed text-foreground">{narration.headline}</p>
          {narration.next && <p className="text-sm leading-relaxed text-muted-foreground">{narration.next}</p>}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
    </div>
  );
}

/** Compact one-line version of a narration stage, for list rows. */
export function StageTag({ narration }: { narration: Narration }) {
  const Icon = ICONS[narration.kind];
  const spin = narration.kind === "drafting";
  return (
    <Badge tone={narration.tone}>
      <Icon className={cn("h-3 w-3", spin && "animate-spin")} />
      {narration.stage}
    </Badge>
  );
}
