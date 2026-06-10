import { useState } from "react";
import { Check, Copy, Radio } from "lucide-react";
import { cn } from "@/lib/utils";

// Shown on the dashboard's empty states. Mirrors the "waiting for your agent"
// onboarding moment: instead of telling the user which endpoint to POST to, it
// hands them one command to run inside their coding agent, which wires the
// telemetry for them. See the bundled `kyoko-instrument` skill.

const SKILL_COMMAND = "/kyoko-instrument";
const SUPPORTED_AGENTS = ["Claude Code", "Cursor", "Codex", "Windsurf", "Cline"];

function CopyPill({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable; the command is still visible to type */
    }
  };
  return (
    <button
      type="button"
      onClick={copy}
      title="Copy command"
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2",
        "font-mono text-sm font-semibold text-foreground shadow-xs transition-colors hover:bg-accent",
      )}
    >
      {SKILL_COMMAND}
      {copied ? (
        <Check className="h-3.5 w-3.5 text-ok" />
      ) : (
        <Copy className="h-3.5 w-3.5 text-muted-foreground" />
      )}
    </button>
  );
}

export function InstrumentCTA({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex h-full min-h-32 flex-col items-center justify-center gap-4 p-10 text-center",
        className,
      )}
    >
      <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-muted text-muted-foreground/70">
        <Radio className="h-6 w-6" />
      </div>
      <div>
        <div className="text-sm font-semibold text-foreground">Waiting for your agent…</div>
        <div className="mx-auto mt-1 max-w-sm text-xs text-muted-foreground">
          Open your coding agent in your repo and run this. It wires your agent's telemetry
          into Kyoko, so the next run shows up here.
        </div>
      </div>

      <CopyPill text={SKILL_COMMAND} />

      <div className="flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground/80">
        {SUPPORTED_AGENTS.map((agent, i) => (
          <span key={agent} className="flex items-center gap-2">
            {i > 0 && <span className="text-muted-foreground/40">·</span>}
            {agent}
          </span>
        ))}
      </div>

      <div className="mt-1 max-w-sm text-[11px] leading-relaxed text-muted-foreground/70">
        Don't have the command yet? Run{" "}
        <code className="rounded bg-muted px-1 py-0.5 font-mono">kyoko install-skill</code> once.
        Just exploring? Run{" "}
        <code className="rounded bg-muted px-1 py-0.5 font-mono">kyoko demo</code> for sample data.
      </div>
    </div>
  );
}
