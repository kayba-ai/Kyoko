import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { CheckCheck, CircleDot, GitPullRequestArrow, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/types";
import { ago } from "@/lib/format";
import { narrateProposal, sectionPhrase } from "@/lib/narrate";
import { useApi } from "@/hooks/useApi";
import { Button } from "@/components/ui/button";
import { Disclosure } from "@/components/ui/disclosure";
import { Spinner, Empty, ErrorNote } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBanner, StageTag } from "@/components/StatusBanner";
import { StructuredDetail } from "@/components/RecordView";
import { cn } from "@/lib/utils";

// Learning proposals are Kyoko's gated change suggestions (context/skill/harness
// edits). This is the gate-#2 surface: a pending proposal authored from an accepted
// issue is reviewed here and applied via "Approve & apply" (POST /api/proposals/apply).
// Applying still runs server-side behind the autonomy policy + human locks — the button
// is the human approval, not a bypass. The display leads with plain English (what this
// change does, what to do next); the numbers and raw record sit behind a toggle.

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

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </section>
  );
}

function ProposalDetail({
  id,
  version,
  applying,
  applyError,
  onApply,
}: {
  id: string;
  version: number;
  applying: boolean;
  applyError: string | null;
  onApply: () => void;
}) {
  const { data, error, loading } = useApi<Record<string, unknown>>(() => api.proposalDetail(id), [id, version]);

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
  const section = (data.section as string | undefined) ?? null;
  const issueId = (data.issue_id as string | undefined) ?? null;
  const summary = (data.summary as string | undefined) ?? null;
  const sectionDescription = (data.section_description as string | undefined) ?? null;
  const kyokoConfidence = data.kyoko_confidence as number | null | undefined;
  const operatorConfidence = data.operator_confidence as number | null | undefined;
  const confidence = data.confidence as number | null | undefined;
  const hasConfidence =
    pct(kyokoConfidence) !== null || pct(operatorConfidence) !== null || pct(confidence) !== null;

  const narration = narrateProposal({ state, section });

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      {/* What this proposal is, with the human-readable basics underneath. */}
      <div className="space-y-2">
        <h2 className="text-xl font-bold tracking-tight text-foreground">{title}</h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {section && <span>Changes {sectionPhrase(section)}</span>}
          {issueId && (
            <span className="inline-flex items-center gap-1" title={`Origin issue: ${issueId}`}>
              <CircleDot className="h-3 w-3" />
              Fixes a tracked issue
            </span>
          )}
        </div>
        {sectionDescription && <p className="text-sm text-muted-foreground">{sectionDescription}</p>}
      </div>

      {/* What's happening + the one action that matters: approve to apply. */}
      <StatusBanner
        narration={narration}
        actions={
          state === "pending" ? (
            <Button variant="default" disabled={applying} onClick={onApply}>
              {applying ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCheck className="h-3.5 w-3.5" />
              )}
              Approve &amp; apply
            </Button>
          ) : undefined
        }
      />
      {applyError && (
        <span className="block text-xs text-danger" role="alert">
          {applyError}
        </span>
      )}

      {/* The change, in the operator's own words. */}
      {summary && (
        <Section label="What it changes">
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{summary}</p>
        </Section>
      )}

      {/* Confidence numbers and the complete record, tucked away. */}
      <Disclosure summary="Confidence & full proposal">
        <div className="space-y-5">
          {hasConfidence && (
            <div className="space-y-3.5">
              <ConfidenceRow label="Kyoko" value={kyokoConfidence} />
              <ConfidenceRow label="Operator" value={operatorConfidence} />
              <ConfidenceRow label="Overall" value={confidence} />
            </div>
          )}
          <StructuredDetail data={data} />
        </div>
      </Disclosure>
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

  // Gate #2 apply lives at the page level so each proposal in the list (the review queue)
  // gets its own button, plus the detail's. Tracks the in-flight id and per-id error.
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [applyErrors, setApplyErrors] = useState<Record<string, string>>({});

  async function apply(id: string) {
    setApplyingId(id);
    setApplyErrors((m) => {
      const next = { ...m };
      delete next[id];
      return next;
    });
    try {
      await api.applyProposal(id);
      setVersion((v) => v + 1);
      reload();
    } catch (e) {
      setApplyErrors((m) => ({ ...m, [id]: e instanceof Error ? e.message : String(e) }));
    } finally {
      setApplyingId(null);
    }
  }

  function select(id: string) {
    setSelected(id);
    if (linkedId) setSearchParams({}, { replace: true });
  }

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Proposals"
        description="Review and approve the fixes Kyoko has drafted from accepted issues."
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
              title="No drafted fixes yet"
              hint="Accept an issue on the Issues tab and Kyoko will draft a fix here for you to approve."
              icon={<GitPullRequestArrow className="h-6 w-6" />}
            />
          </div>
        ) : (
          <>
            <div className="w-80 shrink-0 space-y-1.5 overflow-y-auto border-r border-border p-3">
              {data.map((p) => {
                const narration = narrateProposal({ state: p.state, section: p.section });
                const active = p.id === selected;
                const pending = p.state === "pending";
                const applyError = applyErrors[p.id];
                return (
                  <div
                    key={p.id}
                    onClick={() => select(p.id)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        select(p.id);
                      }
                    }}
                    className={cn(
                      "w-full cursor-pointer rounded-lg border p-3 text-left transition-colors",
                      active ? "border-primary/40 bg-accent" : "border-transparent hover:bg-accent",
                    )}
                  >
                    <div className="mb-1.5 truncate text-sm font-medium text-foreground">{p.title}</div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <StageTag narration={narration} />
                      {p.issue_id && (
                        <span
                          className="inline-flex items-center gap-1 text-label text-muted-foreground"
                          title={`Origin issue: ${p.issue_id}`}
                        >
                          <CircleDot className="h-3 w-3" />
                          Fix
                        </span>
                      )}
                      <span className="ml-auto text-xs text-muted-foreground">{ago(p.created_at)}</span>
                    </div>
                    {pending && (
                      <div className="mt-2.5">
                        <Button
                          variant="default"
                          size="sm"
                          className="w-full"
                          disabled={applyingId === p.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            apply(p.id);
                          }}
                        >
                          {applyingId === p.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <CheckCheck className="h-3.5 w-3.5" />
                          )}
                          Approve &amp; apply
                        </Button>
                        {applyError && (
                          <span className="mt-1 block text-label text-danger" role="alert">
                            {applyError}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div className="min-w-0 flex-1 overflow-y-auto p-6">
              {selected ? (
                <ProposalDetail
                  id={selected}
                  version={version}
                  applying={applyingId === selected}
                  applyError={applyErrors[selected] ?? null}
                  onApply={() => apply(selected)}
                />
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
