import { useEffect, useState } from "react";
import { CircleDot, GitPullRequestArrow } from "lucide-react";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";
import { ago, humanize } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Spinner, Empty, ErrorNote } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { StructuredDetail } from "@/components/RecordView";
import { cn } from "@/lib/utils";

// Learning proposals are Kyoko's gated change suggestions (context/skill/harness
// edits). This dashboard only VIEWS them — applying happens server-side behind the
// check/replay gate and the profile autonomy policy. No apply controls here.

function pct(v: number | null | undefined): string | null {
  if (v === null || v === undefined) return null;
  return `${Math.round(v * 100)}%`;
}

function ratio(v: number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  return Math.max(0, Math.min(1, v));
}

function ConfidenceRow({ label, value }: { label: string; value: number | null | undefined }) {
  const p = pct(value);
  const r = ratio(value);
  if (p === null || r === null) return null;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="font-mono text-sm font-semibold tabular-nums text-foreground">{p}</span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.round(r * 100)}%` }} />
      </div>
    </div>
  );
}

function ProposalDetail({ id }: { id: string }) {
  const { data, error, loading } = useApi<Record<string, unknown>>(() => api.proposalDetail(id), [id]);

  if (loading)
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Empty title="Proposal not found" />;

  const title = String(data.title ?? id);
  const state = (data.state as string | undefined) ?? null;
  const issueId = (data.issue_id as string | undefined) ?? null;
  const sectionLabel = (data.section_label as string | undefined) ?? (data.section as string | undefined) ?? null;
  const summary = (data.summary as string | undefined) ?? null;
  const sectionDescription = (data.section_description as string | undefined) ?? null;
  const kyokoConfidence = data.kyoko_confidence as number | null | undefined;
  const operatorConfidence = data.operator_confidence as number | null | undefined;
  const confidence = data.confidence as number | null | undefined;
  const hasConfidence =
    pct(kyokoConfidence) !== null || pct(operatorConfidence) !== null || pct(confidence) !== null;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="space-y-2.5">
        <h2 className="text-xl font-bold tracking-tight text-foreground">{title}</h2>
        <div className="flex flex-wrap items-center gap-1.5">
          {state && <Badge tone={statusTone(state)}>{humanize(state)}</Badge>}
          {sectionLabel && <Badge tone="neutral">{sectionLabel}</Badge>}
        </div>
        {issueId && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <CircleDot className="h-3.5 w-3.5" />
            <span>Origin issue:</span>
            <span className="font-mono text-foreground">{issueId}</span>
          </div>
        )}
        {sectionDescription && <p className="text-sm text-muted-foreground">{sectionDescription}</p>}
      </div>

      {summary && (
        <Card>
          <CardHeader>
            <CardTitle>Summary</CardTitle>
          </CardHeader>
          <CardBody>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{summary}</p>
          </CardBody>
        </Card>
      )}

      {hasConfidence && (
        <Card>
          <CardHeader>
            <CardTitle>Confidence</CardTitle>
          </CardHeader>
          <CardBody className="space-y-3.5">
            <ConfidenceRow label="Kyoko" value={kyokoConfidence} />
            <ConfidenceRow label="Operator" value={operatorConfidence} />
            <ConfidenceRow label="Overall" value={confidence} />
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Full proposal</CardTitle>
        </CardHeader>
        <CardBody>
          <StructuredDetail data={data} />
        </CardBody>
      </Card>
    </div>
  );
}

export function ProposalsPage() {
  const { data, error, loading } = useApi<Proposal[]>(() => api.proposals(), []);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (data && data.length > 0 && selected === null) {
      setSelected(data[0].id);
    }
  }, [data, selected]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Proposals"
        description="Gated context, skill, and harness change suggestions — view only."
        icon={<GitPullRequestArrow className="h-5 w-5" />}
        actions={
          data ? (
            <span className="text-sm text-muted-foreground tabular-nums">{data.length} total</span>
          ) : undefined
        }
      />
      <div className="flex flex-1 overflow-hidden">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <div className="flex-1 overflow-y-auto">
            <ErrorNote error={error} />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="flex-1">
            <Empty
              title="No learning proposals yet"
              hint="Proposals come from operator, ACE, and import runs once they surface a gated change."
              icon={<GitPullRequestArrow className="h-6 w-6" />}
            />
          </div>
        ) : (
          <>
            <div className="w-80 shrink-0 space-y-1.5 overflow-y-auto border-r border-border p-3">
              {data.map((p) => {
                const sectionLabel = p.section_label ?? p.section;
                const conf = pct(p.confidence);
                const active = p.id === selected;
                return (
                  <button
                    key={p.id}
                    onClick={() => setSelected(p.id)}
                    className={cn(
                      "w-full rounded-lg border p-3 text-left transition-colors",
                      active
                        ? "border-primary/40 bg-accent"
                        : "border-transparent hover:bg-accent",
                    )}
                  >
                    <div className="mb-1.5 truncate text-sm font-medium text-foreground">{p.title}</div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge tone={statusTone(p.state)}>{humanize(p.state)}</Badge>
                      {sectionLabel && <Badge tone="neutral">{sectionLabel}</Badge>}
                      {p.issue_id && (
                        <span
                          className="inline-flex items-center gap-1 text-label text-muted-foreground"
                          title={`Origin issue: ${p.issue_id}`}
                        >
                          <CircleDot className="h-3 w-3" />
                          Issue
                        </span>
                      )}
                      {conf && (
                        <span className="font-mono text-label tabular-nums text-muted-foreground">{conf}</span>
                      )}
                      <span className="ml-auto text-xs text-muted-foreground">{ago(p.created_at)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
            <div className="min-w-0 flex-1 overflow-y-auto p-6">
              {selected ? <ProposalDetail id={selected} /> : <Empty title="Select a proposal" />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
