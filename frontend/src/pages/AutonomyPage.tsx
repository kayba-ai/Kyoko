import { Check, Minus } from "lucide-react";
import { api } from "@/lib/api";
import type { AutonomyPolicy, TimelineEvent } from "@/lib/types";
import { ago } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Spinner, ErrorNote } from "@/components/ui/misc";

// Read-only view of the single profile's autonomy policy + recent autonomy
// timeline. The gate lives server-side — no editors here. SCOPE: context autonomy
// gates on an L1 check (no replay); harness autonomy needs L2 + replay.

function modeTone(mode: string | null | undefined): NonNullable<BadgeProps["tone"]> {
  const m = (mode ?? "").toLowerCase();
  if (["auto", "autonomous"].includes(m)) return "ok";
  if (m === "propose") return "warn";
  return "neutral";
}

function ModeRow({ label, mode }: { label: string; mode: string | null | undefined }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Badge tone={modeTone(mode)}>{mode ?? "—"}</Badge>
    </div>
  );
}

function PermRow({ label, on }: { label: string; on: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      {on ? (
        <Check className="h-3.5 w-3.5 text-ok" />
      ) : (
        <Minus className="h-3.5 w-3.5 text-muted-foreground/50" />
      )}
    </div>
  );
}

function PathChips({ paths }: { paths: string[] }) {
  if (!paths || paths.length === 0) {
    return <div className="text-xs text-muted-foreground/60">None</div>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {paths.map((p) => (
        <span
          key={p}
          className="rounded border border-white/10 bg-white/[0.03] px-1.5 py-0.5 font-mono text-label text-muted-foreground"
        >
          {p}
        </span>
      ))}
    </div>
  );
}

function PolicyView({ policy }: { policy: AutonomyPolicy }) {
  const perms: Array<[string, boolean]> = [
    ["Repo patch", policy.allow_repo_patch],
    ["Check write", policy.allow_check_write],
    ["Skillbook write", policy.allow_skillbook_write],
    ["Profile config write", policy.allow_profile_config_write],
    ["Replay server patch", policy.allow_replay_server_patch],
  ];

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Modes</CardTitle>
        </CardHeader>
        <CardBody className="space-y-2">
          <ModeRow label="Context" mode={policy.context_mode} />
          <ModeRow label="Harness" mode={policy.harness_mode} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Write permissions</CardTitle>
        </CardHeader>
        <CardBody className="space-y-2">
          {perms.map(([label, on]) => (
            <PermRow key={label} label={label} on={on} />
          ))}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Worktree policy</CardTitle>
        </CardHeader>
        <CardBody>
          <Badge tone="neutral">{policy.dirty_worktree_policy ?? "—"}</Badge>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Allowed paths</CardTitle>
        </CardHeader>
        <CardBody>
          <PathChips paths={policy.allowed_paths} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Protected paths</CardTitle>
        </CardHeader>
        <CardBody>
          <PathChips paths={policy.protected_paths} />
        </CardBody>
      </Card>
    </div>
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
          <div className="p-3 text-xs text-muted-foreground/60">No autonomy activity recorded yet.</div>
        ) : (
          events.map((e) => {
            const entity = eventEntity(e);
            const summary = eventSummary(e);
            return (
              <div
                key={e.id}
                className="flex items-center gap-2 border-b border-white/[0.04] px-3 py-2 last:border-b-0"
              >
                <Badge tone="neutral">{e.kind}</Badge>
                {entity && <span className="font-mono text-xs text-foreground/80">{entity}</span>}
                {summary && <span className="truncate text-xs text-muted-foreground">{summary}</span>}
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
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Autonomy</h1>
      </div>
      <div className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : (
          <div className="space-y-4">
            <p className="text-xs text-muted-foreground/80">
              Context autonomy needs an L1 check (no replay); harness autonomy needs L2 + replay.
            </p>
            {policyState.data && <PolicyView policy={policyState.data} />}
            <ActivityCard events={eventsState.data ?? []} />
          </div>
        )}
      </div>
    </div>
  );
}
