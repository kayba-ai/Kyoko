import { useMemo, useState } from "react";
import { FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { StructuredDetail } from "@/components/RecordView";
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
        "flex w-full flex-col items-start gap-1 border-b border-border/60 px-3 py-2.5 text-left transition-colors last:border-b-0",
        selected ? "bg-accent border-l-2 border-l-primary" : "hover:bg-accent",
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

function Detail({ item }: { item: Item }) {
  const badge = badgeValue(item);
  return (
    <Card>
      <CardHeader className="flex items-center justify-between gap-3">
        <CardTitle className="truncate font-mono">{itemId(item)}</CardTitle>
        {badge && <Badge tone={statusTone(badge)}>{badge}</Badge>}
      </CardHeader>
      <CardBody>
        <StructuredDetail data={item} />
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
    <div className="flex flex-1 overflow-hidden">
      <div className="w-72 shrink-0 overflow-y-auto border-r border-border">
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
      <div className="flex-1 overflow-y-auto p-6">{selected && <Detail item={selected} />}</div>
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
      <PageHeader
        title="Checks & replay"
        description="Evidence that gates autonomy"
        icon={<FlaskConical className="h-5 w-5" />}
      >
        {!loading && !error && !allEmpty && (
          <Tabs tabs={tabs} value={tab} onChange={(v) => setTab(v as TabKey)} variant="segment" />
        )}
      </PageHeader>
      {loading ? (
        <div className="flex flex-1 items-center justify-center">
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
        <div className="flex flex-1 flex-col overflow-hidden">
          <div className="shrink-0 p-6 pb-0">
            <div className="rounded-lg border border-border bg-muted/50 p-3 text-sm text-muted-foreground">
              Checks produce the evidence that gates autonomy; replay runs re-execute the agent to prove a
              regression fix.
            </div>
          </div>
          <div className="flex flex-1 overflow-hidden pt-4">
            <MasterDetail items={active} />
          </div>
        </div>
      )}
    </div>
  );
}
