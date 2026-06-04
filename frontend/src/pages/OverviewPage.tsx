import { Activity } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
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

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="surface px-3 py-2.5">
      <div className="text-label uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-1 text-md font-semibold tabular-nums text-foreground">{value}</div>
    </div>
  );
}

const HEADLINE: { key: string; label: string }[] = [
  { key: "runs", label: "Runs" },
  { key: "spans", label: "Spans" },
  { key: "eval_runs", label: "Eval runs" },
  { key: "replay_runs", label: "Replay runs" },
  { key: "learning_proposals", label: "Proposals" },
  { key: "annotations", label: "Annotations" },
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
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Overview</h1>
      </div>
      <div className="flex-1 overflow-auto p-4">
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
          <div className="flex flex-col gap-4">
            {headline.length > 0 && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
                {headline.map((h) => (
                  <StatTile key={h.key} label={h.label} value={counts[h.key]} />
                ))}
              </div>
            )}

            {isNonEmptyObject(cards) && (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
                {Object.entries(cards).map(([k, v]) => (
                  <StatTile key={k} label={humanize(k)} value={cardValue(v)} />
                ))}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <SubCard title="Runs" data={metrics.data?.runs} />
              <SubCard title="Evals" data={metrics.data?.evals} />
              <SubCard title="Replay" data={metrics.data?.replay} />
              <SubCard title="Autonomy" data={metrics.data?.autonomy} />
            </div>

            {Object.keys(counts).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Database</CardTitle>
                </CardHeader>
                <CardBody>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3 lg:grid-cols-4">
                    {Object.entries(counts).map(([k, v]) => (
                      <div key={k} className="flex items-baseline justify-between gap-2">
                        <span className="truncate text-xs text-muted-foreground">{humanize(k)}</span>
                        <span className="font-mono text-xs tabular-nums text-foreground">{v}</span>
                      </div>
                    ))}
                  </div>
                </CardBody>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
