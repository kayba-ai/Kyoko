import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ListTree, Search } from "lucide-react";
import type { RunSummary } from "@/lib/types";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { ago, durationMs, fmtCost, fmtDuration, fmtTime, fmtTokens, humanize } from "@/lib/format";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { PageHeader } from "@/components/ui/page-header";
import { Badge, statusTone } from "@/components/ui/badge";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { InstrumentCTA } from "@/components/InstrumentCTA";
import { Table, THead, TBody, TR, TD, SortableTH, type SortDir } from "@/components/ui/table";
import { cn } from "@/lib/utils";

type SortKey = "time" | "duration" | "tokens";

function rowDuration(r: RunSummary): number | null {
  return r.duration_ms ?? durationMs(r.started_at, r.ended_at);
}
function rowTokens(r: RunSummary): number | null {
  return r.total_tokens ?? null;
}
function rowTime(r: RunSummary): number {
  return Date.parse(r.started_at ?? r.ended_at ?? "") || 0;
}

export function TracesPage() {
  const navigate = useNavigate();
  const { data: runs, error, loading, reload } = useApi(() => api.runs(), []);
  const [filter, setFilter] = useState("");
  const [status, setStatus] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("time");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Live: a run_upsert means a run was created/updated by ingest — refresh the list.
  useLiveEvent("run_upsert", () => reload());

  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    for (const r of runs ?? []) if (r.status) set.add(r.status);
    return [{ value: "", label: "All statuses" }, ...[...set].sort().map((s) => ({ value: s, label: s }))];
  }, [runs]);

  const rows = useMemo(() => {
    let list = runs ?? [];
    const q = filter.trim().toLowerCase();
    if (q) {
      list = list.filter((r) =>
        [r.id, r.agent_name, r.summary, r.external_id].some((v) => v && v.toLowerCase().includes(q)),
      );
    }
    if (status) list = list.filter((r) => r.status === status);

    const cmp = (a: RunSummary, b: RunSummary): number => {
      let av: number, bv: number;
      if (sortKey === "duration") {
        av = rowDuration(a) ?? -1;
        bv = rowDuration(b) ?? -1;
      } else if (sortKey === "tokens") {
        av = rowTokens(a) ?? -1;
        bv = rowTokens(b) ?? -1;
      } else {
        av = rowTime(a);
        bv = rowTime(b);
      }
      return av - bv;
    };
    const sorted = [...list].sort(cmp);
    if (sortDir === "desc") sorted.reverse();
    return sorted;
  }, [runs, filter, status, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "time" ? "desc" : "desc");
    }
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Traces"
        description="Every agent run as a trace — spans, payloads, tokens, cost, and scores."
        icon={<ListTree className="h-5 w-5" />}
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="Search id, agent, summary, external id…"
              className="h-9 pl-8"
            />
          </div>
          <Select value={status} onChange={setStatus} options={statusOptions} className="w-44" />
          <span className="ml-auto text-label font-medium text-muted-foreground">{rows.length} traces</span>
        </div>
      </PageHeader>

      <div className="min-h-0 flex-1 overflow-auto">
        {loading && !runs ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : rows.length === 0 ? (
          (runs ?? []).length === 0 ? (
            <InstrumentCTA />
          ) : (
            <Empty title="No matching traces" hint="No runs match the current search or status filter." />
          )
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <SortableTH
                  label="Time"
                  active={sortKey === "time"}
                  dir={sortDir}
                  onSort={() => toggleSort("time")}
                  className="w-28"
                />
                <SortableTH label="Name / agent" active={false} dir={sortDir} onSort={() => {}} className="cursor-default" />
                <SortableTH label="Status" active={false} dir={sortDir} onSort={() => {}} className="w-28 cursor-default" />
                <SortableTH
                  label="Duration"
                  active={sortKey === "duration"}
                  dir={sortDir}
                  onSort={() => toggleSort("duration")}
                  align="right"
                  className="w-24"
                />
                <SortableTH label="Spans" active={false} dir={sortDir} onSort={() => {}} align="right" className="w-24 cursor-default" />
                <SortableTH
                  label="Tokens"
                  active={sortKey === "tokens"}
                  dir={sortDir}
                  onSort={() => toggleSort("tokens")}
                  align="right"
                  className="w-24"
                />
                <SortableTH label="Cost" active={false} dir={sortDir} onSort={() => {}} align="right" className="w-20 cursor-default" />
              </TR>
            </THead>
            <TBody>
              {rows.map((r) => {
                const dur = rowDuration(r);
                const total = rowTokens(r);
                return (
                  <TR
                    key={r.id}
                    className="cursor-pointer hover:bg-muted"
                    onClick={() => navigate(`/traces/${r.id}`)}
                  >
                    <TD className="text-xs text-muted-foreground" title={fmtTime(r.started_at ?? r.ended_at)}>
                      {ago(r.started_at ?? r.ended_at)}
                    </TD>
                    <TD>
                      <div className="flex min-w-0 flex-col">
                        <span className="truncate text-sm font-semibold text-foreground">
                          {r.agent_name || <span className="font-mono text-xs text-muted-foreground">{r.id}</span>}
                        </span>
                        {r.summary && <span className="truncate text-xs text-muted-foreground">{r.summary}</span>}
                      </div>
                    </TD>
                    <TD>
                      <Badge tone={statusTone(r.status)}>{r.status ? humanize(r.status) : "—"}</Badge>
                    </TD>
                    <TD className="text-right font-mono text-xs text-muted-foreground">{fmtDuration(dur)}</TD>
                    <TD className="text-right font-mono text-xs">
                      <span className="text-foreground">{r.span_count}</span>
                      {r.failed_span_count > 0 && (
                        <span className="ml-1 font-medium text-danger">/{r.failed_span_count}✕</span>
                      )}
                    </TD>
                    <TD
                      className={cn("text-right font-mono text-xs", total ? "text-foreground" : "text-muted-foreground")}
                      title={
                        total
                          ? `in ${fmtTokens(r.input_tokens)} · out ${fmtTokens(r.output_tokens)}`
                          : undefined
                      }
                    >
                      {fmtTokens(total)}
                    </TD>
                    <TD
                      className={cn(
                        "text-right font-mono text-xs",
                        r.cost_usd != null ? "text-foreground" : "text-muted-foreground",
                      )}
                    >
                      {fmtCost(r.cost_usd)}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </div>
    </div>
  );
}
