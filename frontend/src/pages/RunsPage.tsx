import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ListTree, Search } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { RunList } from "@/components/RunList";
import { RunDetail } from "@/components/RunDetail";

export function RunsPage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const { data: runs, error, loading, reload } = useApi(() => api.runs(), []);
  const [filter, setFilter] = useState("");

  // Live: a run_upsert means a run was created/updated by ingest — refresh the list.
  useLiveEvent("run_upsert", () => reload());

  // Default-select the most recent run when none is in the URL.
  useEffect(() => {
    if (!runId && runs && runs.length > 0) {
      navigate(`/runs/${runs[0].id}`, { replace: true });
    }
  }, [runId, runs, navigate]);

  const filtered = useMemo(() => {
    if (!runs) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return runs;
    return runs.filter((r) =>
      [r.id, r.agent_name, r.summary, r.status, r.external_id].some((v) => v && v.toLowerCase().includes(q)),
    );
  }, [runs, filter]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Runs"
        description="Inspect agent runs — spans, payloads, timeline, and live events."
        icon={<ListTree className="h-5 w-5" />}
      />
      <div className="flex flex-1 overflow-hidden">
        <div className="flex w-80 shrink-0 flex-col border-r border-border bg-background">
          <div className="shrink-0 border-b border-border px-3 py-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter runs…"
                className="h-9 pl-8 pr-12"
              />
              <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-label font-medium text-muted-foreground">
                {filtered.length}
              </span>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading && !runs ? (
              <div className="flex justify-center py-10">
                <Spinner />
              </div>
            ) : error ? (
              <ErrorNote error={error} />
            ) : filtered.length === 0 ? (
              <Empty title="No runs" hint="Ingest traces via POST /v1/traces or run `kyoko demo`." />
            ) : (
              <RunList runs={filtered} selectedId={runId ?? null} onSelect={(id) => navigate(`/runs/${id}`)} />
            )}
          </div>
        </div>
        <div className="min-w-0 flex-1 overflow-y-auto bg-background">
          {runId ? (
            <RunDetail runId={runId} />
          ) : (
            <Empty title="Select a run" hint="Choose a run from the list to inspect its spans, payloads, and live events." />
          )}
        </div>
      </div>
    </div>
  );
}
