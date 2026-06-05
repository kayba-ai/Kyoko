import * as React from "react";
import { AlertTriangle, Loader2, RotateCcw, Save, ShieldCheck, UserCheck, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { AutonomyMode, AutonomyPolicy, PolicyUpdate, TimelineEvent } from "@/lib/types";
import { ago, humanize } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Spinner, ErrorNote } from "@/components/ui/misc";
import { cn } from "@/lib/utils";

// Editable view of the single profile's two-mode autonomy policy (spec 0018) +
// recent autonomy timeline. The policy is owner configuration (not learned
// content), so the loopback dashboard may edit it directly via POST /api/policy.
//
// Two modes:
//   • HITL       — every change waits for a human accept (gate #1) + approve (gate #2).
//   • Autonomous — Kyoko authors+applies a fix once a failure recurs enough times,
//                  and (optionally) auto-rolls-back regressions.
//
// Allowed/protected paths are intentionally read-only here (CLI/storage only).

const WORKTREE_OPTIONS = [
  { value: "block", label: "Block on dirty worktree" },
  { value: "allow_touched_only", label: "Allow touched paths only" },
  { value: "allow", label: "Allow always" },
];

interface Draft {
  mode: AutonomyMode;
  recurrence_threshold: number;
  regression_threshold: number;
  auto_rollback_on_regression: boolean;
  max_auto_fix_attempts: number;
  allow_repo_patch: boolean;
  dirty_worktree_policy: string;
}

const EDITABLE_KEYS = Object.keys({
  mode: 0,
  recurrence_threshold: 0,
  regression_threshold: 0,
  auto_rollback_on_regression: 0,
  max_auto_fix_attempts: 0,
  allow_repo_patch: 0,
  dirty_worktree_policy: 0,
} satisfies Record<keyof Draft, unknown>) as (keyof Draft)[];

function toMode(v: unknown): AutonomyMode {
  return v === "autonomous" ? "autonomous" : "hitl";
}

function toInt(v: unknown, fallback: number): number {
  const n = Number(v);
  return Number.isFinite(n) ? Math.trunc(n) : fallback;
}

function draftFromPolicy(p: AutonomyPolicy): Draft {
  return {
    mode: toMode(p.mode),
    recurrence_threshold: toInt(p.recurrence_threshold, 3),
    regression_threshold: toInt(p.regression_threshold, 2),
    auto_rollback_on_regression: Boolean(p.auto_rollback_on_regression),
    max_auto_fix_attempts: toInt(p.max_auto_fix_attempts, 1),
    allow_repo_patch: Boolean(p.allow_repo_patch),
    dirty_worktree_policy: String(p.dirty_worktree_policy ?? "block"),
  };
}

function diff(base: Draft, draft: Draft): PolicyUpdate {
  const out: PolicyUpdate = {};
  for (const key of EDITABLE_KEYS) {
    if (base[key] !== draft[key]) {
      // Each key maps to the same-named PolicyUpdate field.
      (out as Record<string, unknown>)[key] = draft[key];
    }
  }
  return out;
}

function FieldRow({
  label,
  hint,
  control,
}: {
  label: string;
  hint?: string;
  control: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-border/60 last:border-b-0">
      <div className="min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        {hint && <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

function NumberInput({
  value,
  min = 1,
  onChange,
}: {
  value: number;
  min?: number;
  onChange: (v: number) => void;
}) {
  return (
    <Input
      type="number"
      min={min}
      step={1}
      value={String(value)}
      onChange={(e) => {
        const n = Number(e.target.value);
        if (Number.isFinite(n)) onChange(Math.max(min, Math.trunc(n)));
      }}
      className="w-24 text-right tabular-nums"
    />
  );
}

function PathChips({ paths, tone = "neutral" }: { paths: string[]; tone?: NonNullable<BadgeProps["tone"]> }) {
  if (!paths || paths.length === 0) {
    return <div className="text-sm text-muted-foreground/70">None</div>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {paths.map((p) => (
        <Badge key={p} tone={tone} className="font-mono normal-case tracking-normal">
          {p}
        </Badge>
      ))}
    </div>
  );
}

// ---- Mode toggle (HITL / Autonomous) ----------------------------------------

function ModeToggle({ mode, onChange }: { mode: AutonomyMode; onChange: (m: AutonomyMode) => void }) {
  const options: { value: AutonomyMode; label: string; icon: React.ReactNode; hint: string }[] = [
    {
      value: "hitl",
      label: "Human-in-the-loop",
      icon: <UserCheck className="h-4 w-4" />,
      hint: "You accept each issue and approve each fix. Kyoko writes nothing on its own.",
    },
    {
      value: "autonomous",
      label: "Autonomous",
      icon: <Zap className="h-4 w-4" />,
      hint: "Kyoko authors and applies a fix once a failure recurs past the threshold.",
    },
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {options.map((o) => {
        const active = mode === o.value;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={cn(
              "flex flex-col gap-1.5 rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
              active ? "border-primary/50 bg-accent shadow-xs" : "border-border bg-card hover:bg-accent/60",
            )}
            aria-pressed={active}
          >
            <div className="flex items-center gap-2">
              <span className={cn("inline-flex", active ? "text-primary" : "text-muted-foreground")}>{o.icon}</span>
              <span className="text-sm font-semibold text-foreground">{o.label}</span>
              {active && <Badge tone="primary" className="ml-auto">Active</Badge>}
            </div>
            <p className="text-xs text-muted-foreground">{o.hint}</p>
          </button>
        );
      })}
    </div>
  );
}

function PolicyEditor({ policy, onSaved }: { policy: AutonomyPolicy; onSaved: () => void }) {
  const base = React.useMemo(() => draftFromPolicy(policy), [policy]);
  const [draft, setDraft] = React.useState<Draft>(base);
  const [saving, setSaving] = React.useState(false);
  const [saveError, setSaveError] = React.useState<Error | null>(null);

  // Resync when a fresh policy arrives (after save/reload).
  React.useEffect(() => {
    setDraft(base);
    setSaveError(null);
  }, [base]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const changes = diff(base, draft);
  const dirty = Object.keys(changes).length > 0;

  const autonomous = draft.mode === "autonomous";
  const repoRisky = autonomous && draft.allow_repo_patch;

  async function save() {
    setSaving(true);
    setSaveError(null);
    try {
      await api.updatePolicy(changes);
      onSaved();
    } catch (e) {
      setSaveError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {/* Mode */}
      <Card>
        <CardHeader>
          <CardTitle>Mode</CardTitle>
          <Badge tone={autonomous ? "ok" : "neutral"}>{autonomous ? "Autonomous" : "HITL"}</Badge>
        </CardHeader>
        <CardBody>
          <ModeToggle mode={draft.mode} onChange={(m) => set("mode", m)} />
        </CardBody>
      </Card>

      {/* Thresholds */}
      <Card>
        <CardHeader>
          <CardTitle>Thresholds</CardTitle>
        </CardHeader>
        <CardBody className="py-1">
          <FieldRow
            label="Recurrence threshold"
            hint="In autonomous mode, how many times a failure must recur before Kyoko authors and applies a fix."
            control={
              <NumberInput value={draft.recurrence_threshold} onChange={(v) => set("recurrence_threshold", v)} />
            }
          />
          <FieldRow
            label="Regression threshold"
            hint="Post-apply recurrences of the same failure that trip the regression guard."
            control={
              <NumberInput value={draft.regression_threshold} onChange={(v) => set("regression_threshold", v)} />
            }
          />
          <FieldRow
            label="Max auto-fix attempts"
            hint="How many auto-fix cycles the guard monitor runs before escalating an issue to HITL."
            control={
              <NumberInput value={draft.max_auto_fix_attempts} onChange={(v) => set("max_auto_fix_attempts", v)} />
            }
          />
        </CardBody>
      </Card>

      {/* Guardrails */}
      <Card>
        <CardHeader>
          <CardTitle>Guardrails</CardTitle>
        </CardHeader>
        <CardBody className="py-1">
          <FieldRow
            label="Auto-rollback on regression"
            hint="In autonomous mode, revert an applied fix automatically once it regresses past the threshold."
            control={
              <Switch
                checked={draft.auto_rollback_on_regression}
                onCheckedChange={(v) => set("auto_rollback_on_regression", v)}
              />
            }
          />
          <FieldRow
            label="Repo patch"
            hint="Allow Kyoko to write generated code/prompt patches into the repo (harness changes)."
            control={
              <Switch checked={draft.allow_repo_patch} onCheckedChange={(v) => set("allow_repo_patch", v)} />
            }
          />
          <FieldRow
            label="Dirty worktree policy"
            hint="How harness apply behaves when the git worktree is dirty."
            control={
              <Select
                value={draft.dirty_worktree_policy}
                onChange={(v) => set("dirty_worktree_policy", v)}
                options={WORKTREE_OPTIONS}
                className="w-56"
              />
            }
          />
          {repoRisky && (
            <div className="mt-2 flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Autonomous mode with <strong>repo patch</strong> on — Kyoko can write code into the repo once a failure
                recurs past the threshold. A clean/allowed worktree and rollback preimage still apply.
              </span>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Paths (read-only) */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Allowed paths</CardTitle>
            <Badge tone="neutral">Read-only</Badge>
          </CardHeader>
          <CardBody>
            <PathChips paths={policy.allowed_paths} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Protected paths</CardTitle>
            <Badge tone="neutral">Read-only</Badge>
          </CardHeader>
          <CardBody>
            <PathChips paths={policy.protected_paths} tone="warn" />
          </CardBody>
        </Card>
      </div>
      <p className="-mt-2 text-xs text-muted-foreground/70">
        Path globs are managed from the CLI (<span className="font-mono">kyoko policy-set</span>), not the dashboard.
      </p>

      {saveError && <ErrorNote error={saveError} />}

      {/* Action bar */}
      <div className="sticky bottom-0 -mx-6 mt-2 flex items-center justify-between gap-3 border-t border-border bg-background/85 px-6 py-3 backdrop-blur">
        <div className="text-xs text-muted-foreground">
          {dirty ? (
            <span className="font-medium text-foreground">
              {Object.keys(changes).length} unsaved change{Object.keys(changes).length === 1 ? "" : "s"}
            </span>
          ) : policy.updated_at ? (
            <>Last updated {ago(policy.updated_at)}</>
          ) : (
            "No unsaved changes"
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={!dirty || saving}
            onClick={() => setDraft(base)}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </Button>
          <Button size="sm" disabled={!dirty || saving} onClick={save}>
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            Save changes
          </Button>
        </div>
      </div>
    </>
  );
}

function eventTime(e: TimelineEvent): string | null | undefined {
  return e.created_at ?? e.at;
}

function eventSummary(e: TimelineEvent): string | null {
  return e.summary ?? e.detail ?? null;
}

function eventEntity(e: TimelineEvent): string | null {
  if (e.entity_type && e.entity_id) return `${e.entity_type}:${e.entity_id}`;
  return e.entity_type ?? e.entity_id ?? null;
}

function ActivityCard({ events }: { events: TimelineEvent[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent autonomy activity</CardTitle>
      </CardHeader>
      <CardBody className="space-y-0 p-0">
        {events.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground/70">No autonomy activity recorded yet.</div>
        ) : (
          events.map((e) => {
            const entity = eventEntity(e);
            const summary = eventSummary(e);
            return (
              <div
                key={e.id}
                className="flex items-center gap-2.5 border-b border-border/60 px-4 py-2.5 transition-colors hover:bg-accent last:border-b-0"
              >
                <Badge tone="neutral">{humanize(e.kind)}</Badge>
                {entity && <span className="font-mono text-xs text-foreground">{entity}</span>}
                {summary && <span className="truncate text-sm text-muted-foreground">{summary}</span>}
                <span className="ml-auto shrink-0 text-label text-muted-foreground/70">
                  {ago(eventTime(e))}
                </span>
              </div>
            );
          })
        )}
      </CardBody>
    </Card>
  );
}

function GuardMonitorButton({ onRan }: { onRan: () => void }) {
  const [running, setRunning] = React.useState(false);
  const [result, setResult] = React.useState<string | null>(null);
  const [error, setError] = React.useState<Error | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const report = await api.guardMonitor();
      const n = report.actions?.length ?? 0;
      setResult(n === 0 ? "No regressions found." : `${n} guard action${n === 1 ? "" : "s"} taken.`);
      onRan();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="secondary" size="sm" disabled={running} onClick={run}>
        {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
        Run guard monitor
      </Button>
      {result && <span className="text-xs text-muted-foreground">{result}</span>}
      {error && (
        <span className="text-xs text-danger" role="alert">
          {error.message}
        </span>
      )}
    </div>
  );
}

export function AutonomyPage() {
  const policyState = useApi<AutonomyPolicy>(() => api.policy(), []);
  const eventsState = useApi<TimelineEvent[]>(() => api.autonomyEvents(50), []);

  const loading = policyState.loading || eventsState.loading;
  const error = policyState.error ?? eventsState.error;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Autonomy"
        description="Choose human-in-the-loop or autonomous, set thresholds, and review recent activity"
        icon={<ShieldCheck className="h-5 w-5" />}
      />
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : (
          <>
            <div className="rounded-lg border border-border bg-muted/50 p-3 text-sm text-muted-foreground">
              In <strong>HITL</strong> you accept each issue and approve each fix. In <strong>autonomous</strong> mode
              Kyoko authors+applies a fix once a failure recurs past the recurrence threshold, then the guard monitor
              watches for regressions. Changes here take effect immediately for your single local workflow.
            </div>
            {policyState.data && (
              <PolicyEditor policy={policyState.data} onSaved={() => policyState.reload()} />
            )}
            <Card>
              <CardHeader>
                <CardTitle>Guard monitor</CardTitle>
              </CardHeader>
              <CardBody className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Checks applied fixes for post-apply regressions. In autonomous mode (with auto-rollback) it reverts a
                  regressed fix and, after max auto-fix attempts, escalates the issue back to HITL.
                </p>
                <GuardMonitorButton onRan={() => eventsState.reload()} />
              </CardBody>
            </Card>
            <ActivityCard events={eventsState.data ?? []} />
          </>
        )}
      </div>
    </div>
  );
}
