import * as React from "react";
import { AlertTriangle, Loader2, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import type { AutonomyPolicy, PolicyUpdate, TimelineEvent } from "@/lib/types";
import { ago } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Spinner, ErrorNote } from "@/components/ui/misc";

// Editable view of the single profile's autonomy policy + recent autonomy
// timeline. The policy is owner configuration (not learned content), so the
// loopback dashboard may edit it directly via POST /api/policy. SCOPE: context
// autonomy gates on an L1 check (no replay); harness autonomy needs L2 + replay.
// Allowed/protected paths are intentionally read-only here (CLI/storage only).

const MODE_OPTIONS = [
  { value: "off", label: "Off" },
  { value: "propose", label: "Propose" },
  { value: "autonomous", label: "Autonomous" },
];
const WORKTREE_OPTIONS = [
  { value: "block", label: "Block on dirty worktree" },
  { value: "allow_touched_only", label: "Allow touched paths only" },
  { value: "allow", label: "Allow always" },
];
const CHECK_LEVEL_OPTIONS = [
  { value: "L0_generated", label: "L0 · Generated" },
  { value: "L1_repeated", label: "L1 · Repeated" },
  { value: "L2_regression", label: "L2 · Regression" },
  { value: "L3_human_approved", label: "L3 · Human-approved" },
];

const MODE_HINT: Record<string, string> = {
  off: "Kyoko makes no changes of this kind.",
  propose: "Kyoko drafts changes as proposals for you to review and apply.",
  autonomous: "Kyoko applies changes automatically once the gate passes.",
};

interface Draft {
  context_mode: string;
  harness_mode: string;
  allow_repo_patch: boolean;
  allow_check_write: boolean;
  allow_skillbook_write: boolean;
  allow_profile_config_write: boolean;
  allow_replay_server_patch: boolean;
  dirty_worktree_policy: string;
  required_check_level_context: string;
  required_check_level_harness: string;
  rollback_on_regression: boolean;
}

const EDITABLE_KEYS = Object.keys({
  context_mode: 0,
  harness_mode: 0,
  allow_repo_patch: 0,
  allow_check_write: 0,
  allow_skillbook_write: 0,
  allow_profile_config_write: 0,
  allow_replay_server_patch: 0,
  dirty_worktree_policy: 0,
  required_check_level_context: 0,
  required_check_level_harness: 0,
  rollback_on_regression: 0,
} satisfies Record<keyof Draft, unknown>) as (keyof Draft)[];

function draftFromPolicy(p: AutonomyPolicy): Draft {
  return {
    context_mode: String(p.context_mode ?? "off"),
    harness_mode: String(p.harness_mode ?? "off"),
    allow_repo_patch: Boolean(p.allow_repo_patch),
    allow_check_write: Boolean(p.allow_check_write),
    allow_skillbook_write: Boolean(p.allow_skillbook_write),
    allow_profile_config_write: Boolean(p.allow_profile_config_write),
    allow_replay_server_patch: Boolean(p.allow_replay_server_patch),
    dirty_worktree_policy: String(p.dirty_worktree_policy ?? "block"),
    required_check_level_context: String(p.required_check_level_context ?? "L1_repeated"),
    required_check_level_harness: String(p.required_check_level_harness ?? "L2_regression"),
    rollback_on_regression: Boolean(p.rollback_on_regression),
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

  const harnessRisky = draft.harness_mode === "autonomous" && draft.allow_repo_patch;

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

  const perms: Array<{ key: keyof Draft; label: string; hint: string }> = [
    { key: "allow_repo_patch", label: "Repo patch", hint: "Write generated code/prompt patches into the repo (harness)." },
    { key: "allow_check_write", label: "Check write", hint: "Write Kyoko check specs." },
    { key: "allow_skillbook_write", label: "Skillbook write", hint: "Write skills and context-delivery rules." },
    { key: "allow_profile_config_write", label: "Profile config write", hint: "Write profile configuration." },
    { key: "allow_replay_server_patch", label: "Replay server patch", hint: "Patch the replay server target." },
  ];

  return (
    <>
      {/* Modes */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Context autonomy</CardTitle>
            <Badge tone="neutral">L1 · no replay</Badge>
          </CardHeader>
          <CardBody className="space-y-2">
            <Select
              value={draft.context_mode}
              onChange={(v) => set("context_mode", v)}
              options={MODE_OPTIONS}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground">{MODE_HINT[draft.context_mode]}</p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Harness autonomy</CardTitle>
            <Badge tone="warn">L2 · replay</Badge>
          </CardHeader>
          <CardBody className="space-y-2">
            <Select
              value={draft.harness_mode}
              onChange={(v) => set("harness_mode", v)}
              options={MODE_OPTIONS}
              className="w-full"
            />
            <p className="text-xs text-muted-foreground">{MODE_HINT[draft.harness_mode]}</p>
          </CardBody>
        </Card>
      </div>

      {/* Write permissions */}
      <Card>
        <CardHeader>
          <CardTitle>Write permissions</CardTitle>
        </CardHeader>
        <CardBody className="py-1">
          {perms.map((p) => (
            <FieldRow
              key={p.key}
              label={p.label}
              hint={p.hint}
              control={
                <Switch
                  checked={draft[p.key] as boolean}
                  onCheckedChange={(v) => set(p.key, v as Draft[typeof p.key])}
                />
              }
            />
          ))}
          {harnessRisky && (
            <div className="mt-2 flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Harness autonomy is <strong>autonomous</strong> with <strong>repo patch</strong> on — Kyoko can write
                code into the repo once the L2 gate passes. A clean/allowed worktree and rollback preimage still apply.
              </span>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Guardrails */}
      <Card>
        <CardHeader>
          <CardTitle>Guardrails</CardTitle>
        </CardHeader>
        <CardBody className="py-1">
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
          <FieldRow
            label="Required check level — context"
            hint="Minimum check trust before context changes apply."
            control={
              <Select
                value={draft.required_check_level_context}
                onChange={(v) => set("required_check_level_context", v)}
                options={CHECK_LEVEL_OPTIONS}
                className="w-56"
              />
            }
          />
          <FieldRow
            label="Required check level — harness"
            hint="Minimum check trust before harness changes apply."
            control={
              <Select
                value={draft.required_check_level_harness}
                onChange={(v) => set("required_check_level_harness", v)}
                options={CHECK_LEVEL_OPTIONS}
                className="w-56"
              />
            }
          />
          <FieldRow
            label="Rollback on regression"
            hint="Revert autonomous harness writes if replay regresses."
            control={
              <Switch
                checked={draft.rollback_on_regression}
                onCheckedChange={(v) => set("rollback_on_regression", v)}
              />
            }
          />
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
                <Badge tone="neutral">{e.kind}</Badge>
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

export function AutonomyPage() {
  const policyState = useApi<AutonomyPolicy>(() => api.policy(), []);
  const eventsState = useApi<TimelineEvent[]>(() => api.autonomyEvents(50), []);

  const loading = policyState.loading || eventsState.loading;
  const error = policyState.error ?? eventsState.error;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Autonomy"
        description="Configure what Kyoko is allowed to change, and review recent activity"
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
              Context autonomy needs an L1 check (no replay); harness autonomy needs L2 + replay. Changes here take
              effect immediately and apply to your single local workflow.
            </div>
            {policyState.data && (
              <PolicyEditor policy={policyState.data} onSaved={() => policyState.reload()} />
            )}
            <ActivityCard events={eventsState.data ?? []} />
          </>
        )}
      </div>
    </div>
  );
}
