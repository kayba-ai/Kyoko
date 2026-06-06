import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCheck, CircleDot, GitPullRequestArrow, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";
import { ago, humanize } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Spinner, Empty, ErrorNote } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { StructuredDetail } from "@/components/RecordView";
import { cn } from "@/lib/utils";

// Learning proposals are Kyoko's gated change suggestions (context/skill/harness
// edits). This is the gate-#2 surface: a pending proposal authored from an accepted
// issue is reviewed here and applied via "Approve & apply" (POST /api/proposals/apply).
// Applying still runs server-side behind the autonomy policy + human locks — the button
// is the human approval, not a bypass.

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

function ProposalDetail({
  id,
  version,
  onApplied,
}: {
  id: string;
  version: number;
  onApplied: () => void;
}) {
  const { data, error, loading } = useApi<Record<string, unknown>>(() => api.proposalDetail(id), [id, version]);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<Error | null>(null);

  async function apply() {
    setApplying(true);
    setApplyError(null);
    try {
      await api.applyProposal(id);
      onApplied();
    } catch (e) {
      setApplyError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setApplying(false);
    }
  }

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

      {/* Gate #2 — review the authored fix above, then approve to apply it. */}
      {state === "pending" && (
        <div className="flex flex-col gap-2 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-foreground">
              <span className="font-semibold">Ready to apply.</span>{" "}
              <span className="text-muted-foreground">
                Approving writes this change through the autonomy gate.
              </span>
            </div>
            <Button variant="default" disabled={applying} onClick={apply}>
              {applying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCheck className="h-3.5 w-3.5" />}
              Approve &amp; apply
            </Button>
          </div>
          {applyError && (
            <span className="text-xs text-danger" role="alert">
              {applyError.message}
            </span>
          )}
        </div>
      )}

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
  const { data, error, loading, reload } = useApi<Proposal[]>(() => api.proposals(), []);
  const [selected, setSelected] = useState<string | null>(null);
  // Bumped after an apply so the open detail re-fetches (state → applied, button hides).
  const [version, setVersion] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();

  // Deep-link from an accepted issue's "Review fix →" link: ?id=<proposal> selects it.
  const linkedId = searchParams.get("id");
  useEffect(() => {
    if (linkedId) {
      setSelected(linkedId);
    } else if (data && data.length > 0 && selected === null) {
      setSelected(data[0].id);
    }
  }, [linkedId, data, selected]);

  function onApplied() {
    setVersion((v) => v + 1);
    reload();
  }

  function select(id: string) {
    setSelected(id);
    if (linkedId) setSearchParams({}, { replace: true });
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Proposals"
        description="Review and approve gated context, skill, and harness fixes authored from accepted issues."
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
                    onClick={() => select(p.id)}
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
              {selected ? (
                <ProposalDetail id={selected} version={version} onApplied={onApplied} />
              ) : (
                <Empty title="Select a proposal" />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
