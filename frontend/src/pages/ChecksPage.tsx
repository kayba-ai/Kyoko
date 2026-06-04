import { useMemo, useState } from "react";
import { FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";
import { ago } from "@/lib/format";
import { cn } from "@/lib/utils";

type Item = Record<string, unknown>;
type TabKey = "specs" | "runs" | "replay";

function str(item: Item, key: string): string | undefined {
  const v = item[key];
  return typeof v === "string" && v ? v : undefined;
}

function itemId(item: Item): string {
  const id = item["id"];
  return typeof id === "string" || typeof id === "number" ? String(id) : "—";
}

/** Prefer status, fall back to mode/result for a single badge label. */
function badgeValue(item: Item): string | undefined {
  return str(item, "status") ?? str(item, "mode") ?? str(item, "result");
}

function Row({ item, selected, onClick }: { item: Item; selected: boolean; onClick: () => void }) {
  const badge = badgeValue(item);
  const created = str(item, "created_at");
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex w-full flex-col items-start gap-1 border-b border-white/[0.05] px-3 py-2 text-left transition-colors",
        selected ? "bg-white/[0.06]" : "hover:bg-white/[0.03]",
      )}
    >
      <div className="flex w-full items-center justify-between gap-2">
        <span className="truncate font-mono text-xs text-foreground">{itemId(item)}</span>
        {badge && <Badge tone={statusTone(badge)}>{badge}</Badge>}
      </div>
      {created && <span className="text-label text-muted-foreground">{ago(created)}</span>}
    </button>
  );
}

const DETAIL_FIELDS: { key: string; label: string }[] = [
  { key: "status", label: "Status" },
  { key: "mode", label: "Mode" },
  { key: "result", label: "Result" },
  { key: "check_spec_id", label: "Check spec" },
  { key: "proposal_id", label: "Proposal" },
  { key: "source_run_id", label: "Source run" },
  { key: "created_at", label: "Created" },
];

function Detail({ item }: { item: Item }) {
  const fields = DETAIL_FIELDS.filter((f) => str(item, f.key) !== undefined);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="truncate font-mono">{itemId(item)}</CardTitle>
      </CardHeader>
      <CardBody>
        {fields.length > 0 && (
          <div className="mb-3 grid grid-cols-2 gap-x-6 gap-y-1.5">
            {fields.map((f) => (
              <div key={f.key} className="flex items-baseline justify-between gap-2">
                <span className="text-xs text-muted-foreground">{f.label}</span>
                <span className="truncate font-mono text-xs text-foreground">{str(item, f.key)}</span>
              </div>
            ))}
          </div>
        )}
        <JsonView data={item} />
      </CardBody>
    </Card>
  );
}

function MasterDetail({ items }: { items: Item[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = useMemo(() => {
    if (items.length === 0) return null;
    const match = items.find((it) => itemId(it) === selectedId);
    return match ?? items[0];
  }, [items, selectedId]);

  if (items.length === 0) return <Empty title="Nothing here yet" />;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,18rem)_1fr]">
      <div className="surface overflow-hidden self-start">
        {items.map((it) => {
          const id = itemId(it);
          return (
            <Row
              key={id}
              item={it}
              selected={selected !== null && id === itemId(selected)}
              onClick={() => setSelectedId(id)}
            />
          );
        })}
      </div>
      {selected && <Detail item={selected} />}
    </div>
  );
}

export function ChecksPage() {
  const { data, error, loading } = useApi(() => api.checks(), []);
  const [tab, setTab] = useState<TabKey>("specs");

  const specs: Item[] = data?.check_specs ?? [];
  const runs: Item[] = data?.check_runs ?? [];
  const replay: Item[] = data?.replay_runs ?? [];
  const allEmpty = specs.length === 0 && runs.length === 0 && replay.length === 0;

  const tabs = [
    { value: "specs", label: `Check specs (${specs.length})` },
    { value: "runs", label: `Check runs (${runs.length})` },
    { value: "replay", label: `Replay runs (${replay.length})` },
  ];

  const active = tab === "specs" ? specs : tab === "runs" ? runs : replay;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Checks &amp; replay</h1>
        {!loading && !error && !allEmpty && (
          <Tabs tabs={tabs} value={tab} onChange={(v) => setTab(v as TabKey)} />
        )}
      </div>
      <div className="flex-1 overflow-auto p-4">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : allEmpty ? (
          <Empty
            title="No checks or replays yet"
            hint="Generate checks from a proposal, then run replay to gather gate evidence."
            icon={<FlaskConical className="h-6 w-6" />}
          />
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground/80">
              Checks produce the evidence that gates autonomy; replay runs re-execute the agent to prove a
              regression fix.
            </p>
            <MasterDetail items={active} />
          </div>
        )}
      </div>
    </div>
  );
}
