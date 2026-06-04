import type { ReactNode } from "react";
import {
  Activity,
  FlaskConical,
  GitPullRequestArrow,
  LayoutDashboard,
  ListTree,
  MessageSquare,
  RotateCcw,
} from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";

function humanize(key: string): string {
  const s = key.replace(/[_-]+/g, " ").trim();
  if (!s) return key;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function isScalar(v: unknown): v is string | number | boolean {
  return typeof v === "string" || typeof v === "number" || typeof v === "boolean";
}

function cardValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (isScalar(v)) return String(v);
  if (Array.isArray(v)) return String(v.length);
  if (typeof v === "object") return String(Object.keys(v as Record<string, unknown>).length);
  return String(v);
}

function isNonEmptyObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v) && Object.keys(v as object).length > 0;
}

function StatCard({ label, value, icon }: { label: string; value: string | number; icon: ReactNode }) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-3 p-4">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary/10 text-primary [&>svg]:h-5 [&>svg]:w-5">
          {icon}
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm text-muted-foreground">{label}</div>
          <div className="mt-0.5 text-2xl font-bold tabular-nums text-foreground">{value}</div>
        </div>
      </CardBody>
    </Card>
  );
}

const HEADLINE: { key: string; label: string; icon: ReactNode }[] = [
  { key: "runs", label: "Runs", icon: <Activity /> },
  { key: "spans", label: "Spans", icon: <ListTree /> },
  { key: "check_runs", label: "Check runs", icon: <FlaskConical /> },
  { key: "replay_runs", label: "Replay runs", icon: <RotateCcw /> },
  { key: "learning_proposals", label: "Proposals", icon: <GitPullRequestArrow /> },
  { key: "annotations", label: "Annotations", icon: <MessageSquare /> },
];

function SubCard({ title, data }: { title: string; data: unknown }) {
  if (!isNonEmptyObject(data)) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardBody>
        <JsonView data={data} />
      </CardBody>
    </Card>
  );
}

export function OverviewPage() {
  const metrics = useApi(() => api.dashboardMetrics(), []);
  const status = useApi(() => api.status(), []);

  const loading = (metrics.loading && !metrics.data) || (status.loading && !status.data);
  const error = metrics.error ?? status.error;

  const counts: Record<string, number> = {};
  const rawCounts = (status.data?.counts as Record<string, unknown> | undefined) ?? {};
  for (const [k, v] of Object.entries(rawCounts)) {
    if (typeof v === "number") counts[k] = v;
  }

  const headline = HEADLINE.filter((h) => typeof counts[h.key] === "number");
  const cards = metrics.data?.cards;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Overview"
        description="Telemetry, checks, replay, and autonomy at a glance."
        icon={<LayoutDashboard className="h-5 w-5" />}
      />
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : !metrics.data && !status.data ? (
          <Empty
            title="No metrics yet"
            hint="Ingest agent telemetry to populate the dashboard."
            icon={<Activity className="h-6 w-6" />}
          />
        ) : (
          <div className="flex flex-col gap-6">
            {headline.length > 0 && (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
                {headline.map((h) => (
                  <StatCard key={h.key} label={h.label} value={counts[h.key]} icon={h.icon} />
                ))}
              </div>
            )}

            {isNonEmptyObject(cards) && (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
                {Object.entries(cards).map(([k, v]) => (
                  <StatCard
                    key={k}
                    label={humanize(k)}
                    value={cardValue(v)}
                    icon={<Activity />}
                  />
                ))}
              </div>
            )}

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <SubCard title="Runs" data={metrics.data?.runs} />
              <SubCard title="Checks" data={metrics.data?.checks} />
              <SubCard title="Replay" data={metrics.data?.replay} />
              <SubCard title="Autonomy" data={metrics.data?.autonomy} />
            </div>

            {Object.keys(counts).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Database</CardTitle>
                </CardHeader>
                <CardBody className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-border text-xs font-medium text-muted-foreground">
                        <th className="px-4 py-2.5 text-left">Table</th>
                        <th className="px-4 py-2.5 text-right">Rows</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(counts).map(([k, v]) => (
                        <tr
                          key={k}
                          className="border-b border-border/60 last:border-0 hover:bg-muted/50"
                        >
                          <td className="px-4 py-2 text-foreground">{humanize(k)}</td>
                          <td className="px-4 py-2 text-right font-mono tabular-nums text-foreground">
                            {v}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardBody>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
