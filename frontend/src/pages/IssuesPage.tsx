import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CircleDot,
  FileSearch,
  Lightbulb,
  Loader2,
  MessageSquare,
  RotateCcw,
  Search,
  Shield,
  Stethoscope,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Issue, IssueStatus, Skill } from "@/lib/types";
import { ago, fmtTime, humanize } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, Empty, ErrorNote } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { StructuredDetail } from "@/components/RecordView";
import { cn } from "@/lib/utils";

// Issues are first-class EVIDENCE. This page is a REVIEW QUEUE: you accept (resolve)
// or reject (dismiss) each tracked problem, leave a review comment, and see the
// skillbook deliverable the issue feeds into. Review is bookkeeping on the evidence
// record — it never changes agent behavior, mutates a skillbook/harness/repo, or
// bypasses the check/replay gate.

type StatusFilter = "open" | "resolved" | "dismissed" | "all";

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "open", label: "Pending" },
  { value: "resolved", label: "Accepted" },
  { value: "dismissed", label: "Rejected" },
  { value: "all", label: "All" },
];

// Bucket any lifecycle status into the three review-queue filters.
function bucket(status: string): "open" | "resolved" | "dismissed" {
  if (status === "resolved" || status === "applied" || status === "guarded") return "resolved";
  if (status === "dismissed") return "dismissed";
  return "open";
}

// Review-queue decision bucket: resolved/applied/guarded → Accepted,
// dismissed → Rejected, everything in-flight → Pending.
function decision(status: string): { label: string; tone: NonNullable<BadgeProps["tone"]> } {
  if (status === "resolved" || status === "applied" || status === "guarded")
    return { label: "Accepted", tone: "ok" };
  if (status === "dismissed") return { label: "Rejected", tone: "danger" };
  return { label: "Pending", tone: "warn" };
}

// Precise lifecycle badge for every status in the Issue spine. Returns null for
// plain "open" (the decision badge already reads "Pending" there).
function lifecycle(status: string): { label: string; tone: NonNullable<BadgeProps["tone"]> } | null {
  switch (status) {
    case "prioritized":
      return { label: "Prioritized", tone: "warn" };
    case "diagnosed":
      return { label: "Diagnosed", tone: "warn" };
    case "proposed":
      return { label: "Proposed", tone: "primary" };
    case "applied":
      return { label: "Applied", tone: "ok" };
    case "resolved":
      return { label: "Resolved", tone: "ok" };
    case "guarded":
      return { label: "Guarded", tone: "primary" };
    case "dismissed":
      return { label: "Dismissed", tone: "danger" };
    default:
      return null;
  }
}

function severityTone(severity: string | null | undefined): NonNullable<BadgeProps["tone"]> {
  if (severity === "high") return "danger";
  if (severity === "medium") return "warn";
  return "neutral";
}

function matchesQuery(issue: Issue, q: string): boolean {
  if (!q) return true;
  const haystack = [issue.title, issue.body, issue.section, issue.id, issue.category, issue.severity]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

// ---- Review actions (accept / reject / reopen) ------------------------------

function ReviewActions({
  issue,
  onReviewed,
  size = "default",
}: {
  issue: Issue;
  onReviewed: () => void;
  size?: "sm" | "default";
}) {
  const [pending, setPending] = useState<IssueStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);

  async function review(next: IssueStatus) {
    setPending(next);
    setError(null);
    try {
      await api.updateIssueStatus(issue.id, next);
      onReviewed();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setPending(null);
    }
  }

  const busy = pending !== null;

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        {issue.status === "open" ? (
          <>
            <Button variant="default" size={size} disabled={busy} onClick={() => review("resolved")}>
              {pending === "resolved" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Check className="h-3.5 w-3.5" />
              )}
              Accept
            </Button>
            <Button variant="outline" size={size} disabled={busy} onClick={() => review("dismissed")}>
              {pending === "dismissed" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <X className="h-3.5 w-3.5" />
              )}
              Reject
            </Button>
          </>
        ) : (
          <Button variant="outline" size={size} disabled={busy} onClick={() => review("open")}>
            {pending === "open" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            Reopen
          </Button>
        )}
      </div>
      {error && (
        <span className="text-xs text-danger" role="alert">
          {error.message}
        </span>
      )}
    </div>
  );
}

// ---- Review comment ---------------------------------------------------------

function CommentEditor({ issue, onSaved }: { issue: Issue; onSaved: () => void }) {
  const initial = issue.review_comment ?? "";
  const [text, setText] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const dirty = text.trim() !== initial.trim();

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api.updateIssueComment(issue.id, text.trim());
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-2">
      <Textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Leave a review comment…"
        className="min-h-[72px]"
      />
      <div className="flex items-center justify-between gap-2">
        {error ? (
          <span className="text-xs text-danger">{error.message}</span>
        ) : (
          <span className="text-xs text-muted-foreground">
            {dirty ? "Unsaved comment" : initial ? "Saved" : "No comment yet"}
          </span>
        )}
        <Button size="sm" variant="secondary" disabled={!dirty || saving} onClick={save}>
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <MessageSquare className="h-3.5 w-3.5" />}
          Save comment
        </Button>
      </div>
    </div>
  );
}

// ---- Detail sections --------------------------------------------------------

function Section({
  label,
  icon,
  children,
}: {
  label: string;
  icon?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        {icon}
        {label}
      </div>
      {children}
    </section>
  );
}

function EntityChips({ items }: { items: { entity_id: string; found: boolean }[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item.entity_id}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-muted/60 px-2 py-1 font-mono text-xs text-foreground"
        >
          {item.entity_id}
          {!item.found && <Badge tone="warn">Missing</Badge>}
        </span>
      ))}
    </div>
  );
}

function SkillDeliverable({ skill }: { skill: Skill }) {
  return (
    <div className="rounded-xl border border-primary/25 bg-primary/5 p-4">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-primary">
        <Lightbulb className="h-3.5 w-3.5" />
        Skillbook deliverable
      </div>
      <p className="text-sm font-medium leading-relaxed text-foreground">{skill.insight}</p>
      {skill.issue && <p className="mt-1 text-xs text-muted-foreground">{skill.issue}</p>}
      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <Badge tone="primary">{humanize(skill.section)}</Badge>
        {(skill.active === true || skill.active === 1) && <Badge tone="ok">Active</Badge>}
        {(skill.human_locked === true || skill.human_locked === 1) && <Badge tone="neutral">Locked</Badge>}
        {skill.keywords?.slice(0, 6).map((k) => (
          <Badge key={k} tone="neutral" className="font-mono normal-case tracking-normal">
            {k}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function IssueDetail({
  id,
  version,
  skillsByProposal,
  onReviewed,
}: {
  id: string;
  version: number;
  skillsByProposal: Map<string, Skill[]>;
  onReviewed: () => void;
}) {
  const { data, error, loading } = useApi<Record<string, unknown>>(() => api.issueDetail(id), [id, version]);

  if (loading)
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Empty title="Issue not found" />;

  const issue = (data.issue as Issue | undefined) ?? null;
  if (!issue) return <Empty title="Issue not found" />;

  const dec = decision(issue.status);
  const life = lifecycle(issue.status);
  const sectionDescription = (data.section_description as string | undefined) ?? null;
  const affected = (data.affected as Record<string, { entity_id: string; found: boolean }[]>) ?? {};
  const linkedProposals =
    (data.linked_proposals as { proposal: { id: string; title?: string; state?: string } }[]) ?? [];
  const evidenceRefs = Array.isArray(issue.evidence_refs) ? issue.evidence_refs : [];

  const deliveredSkills = (issue.proposal_ids ?? []).flatMap((pid) => skillsByProposal.get(pid) ?? []);

  const sourceGroups: { title: string; items: { entity_id: string; found: boolean }[] }[] = [
    { title: "Agents", items: affected.agent_identities ?? [] },
    { title: "Workflow nodes", items: affected.workflow_nodes ?? [] },
    { title: "Tasks", items: affected.tasks ?? [] },
    { title: "Spans", items: affected.spans ?? [] },
  ].filter((g) => g.items.length > 0);

  return (
    <div className="mx-auto max-w-3xl space-y-6 pb-4">
      {/* Decision header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Badge tone={dec.tone}>{dec.label}</Badge>
          {life && <Badge tone={life.tone}>{life.label}</Badge>}
          {typeof issue.rank === "number" && (
            <Badge tone="neutral" className="tabular-nums">{`Rank ${issue.rank}`}</Badge>
          )}
          {issue.severity && <Badge tone={severityTone(issue.severity)}>{humanize(issue.severity)}</Badge>}
          {issue.section && <Badge tone="neutral">{humanize(issue.section)}</Badge>}
          {issue.category && <Badge tone="neutral">{humanize(issue.category)}</Badge>}
          {issue.source && <Badge tone="neutral">{humanize(issue.source)}</Badge>}
          {issue.evaluator_id && (
            <Badge tone="primary" title={`Guarded by ${issue.evaluator_id}`}>
              <Shield className="h-3 w-3" />
              {`Guard: ${issue.evaluator_id}`}
            </Badge>
          )}
        </div>
        <div className="shrink-0">
          <ReviewActions issue={issue} onReviewed={onReviewed} />
        </div>
      </div>

      {/* Statement */}
      <div className="space-y-1.5">
        <h2 className="text-2xl font-bold leading-snug tracking-tight text-foreground">{issue.title}</h2>
        {sectionDescription && <p className="text-sm text-muted-foreground">{sectionDescription}</p>}
      </div>

      {/* Skillbook deliverable(s) */}
      {deliveredSkills.length > 0 && (
        <div className="space-y-2">
          {deliveredSkills.map((s) => (
            <SkillDeliverable key={s.id} skill={s} />
          ))}
        </div>
      )}

      {/* Root cause (diagnosis) */}
      {issue.root_cause && (
        <Section label="Root cause" icon={<Stethoscope className="h-3.5 w-3.5" />}>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{issue.root_cause}</p>
        </Section>
      )}

      {/* Justification */}
      <Section label="Justification">
        {issue.body ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{issue.body}</p>
        ) : (
          <p className="text-sm text-muted-foreground/70">No description provided.</p>
        )}
      </Section>

      {/* Evidence */}
      {(evidenceRefs.length > 0 || (affected.spans?.length ?? 0) > 0) && (
        <Section label="Evidence" icon={<FileSearch className="h-3.5 w-3.5" />}>
          <div className="space-y-2">
            {evidenceRefs.length > 0 && (
              <div className="rounded-lg border border-border bg-muted/40 p-3">
                <StructuredDetail data={evidenceRefs} />
              </div>
            )}
            {(affected.spans?.length ?? 0) > 0 && <EntityChips items={affected.spans ?? []} />}
          </div>
        </Section>
      )}

      {/* Sources */}
      {(sourceGroups.length > 0 || linkedProposals.length > 0) && (
        <Section label="Sources">
          <div className="space-y-3">
            {sourceGroups.map((g) => (
              <div key={g.title} className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">{g.title}</div>
                <EntityChips items={g.items} />
              </div>
            ))}
            {linkedProposals.length > 0 && (
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">Linked proposals</div>
                <div className="space-y-1.5">
                  {linkedProposals.map((entry) => (
                    <div
                      key={entry.proposal.id}
                      className="flex items-center gap-2 rounded-lg border border-border bg-muted/60 px-3 py-2"
                    >
                      {entry.proposal.state && (
                        <Badge tone="neutral">{humanize(entry.proposal.state)}</Badge>
                      )}
                      <span className="truncate text-sm text-foreground">
                        {entry.proposal.title ?? entry.proposal.id}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </Section>
      )}

      {/* Review comment */}
      <Section label="Review comment" icon={<MessageSquare className="h-3.5 w-3.5" />}>
        <CommentEditor key={issue.id} issue={issue} onSaved={onReviewed} />
      </Section>

      {/* Metadata */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border/60 pt-3 text-xs text-muted-foreground">
        <span>
          Created <span title={fmtTime(issue.created_at)}>{ago(issue.created_at)}</span>
        </span>
        {issue.updated_at && (
          <span>
            Updated <span title={fmtTime(issue.updated_at)}>{ago(issue.updated_at)}</span>
          </span>
        )}
        <span className="font-mono">{issue.id}</span>
      </div>

      {/* Full record */}
      <Card>
        <CardBody>
          <StructuredDetail data={data} defaultView="raw" />
        </CardBody>
      </Card>

      <p className="text-xs text-muted-foreground/70">
        Reviewing updates this evidence record only — it never changes agent behavior or bypasses the check/replay
        gate.
      </p>
    </div>
  );
}

// ---- Review card (left list) ------------------------------------------------

function ReviewCard({
  issue,
  active,
  onSelect,
  onReviewed,
}: {
  issue: Issue;
  active: boolean;
  onSelect: () => void;
  onReviewed: () => void;
}) {
  const dec = decision(issue.status);
  const life = lifecycle(issue.status);
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "group w-full cursor-pointer rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        active ? "border-primary/40 bg-accent shadow-xs" : "border-border bg-card hover:bg-accent/60",
      )}
    >
      <div className="mb-2 line-clamp-2 text-sm font-semibold leading-snug text-foreground">{issue.title}</div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={dec.tone}>{dec.label}</Badge>
        {life && <Badge tone={life.tone}>{life.label}</Badge>}
        {issue.severity && <Badge tone={severityTone(issue.severity)}>{humanize(issue.severity)}</Badge>}
        {issue.section && <Badge tone="neutral">{humanize(issue.section)}</Badge>}
        {issue.evaluator_id && (
          <Badge tone="primary" title={`Guarded by ${issue.evaluator_id}`}>
            <Shield className="h-3 w-3" />
            Guard
          </Badge>
        )}
        <span className="ml-auto text-label text-muted-foreground">{ago(issue.created_at)}</span>
      </div>
      {issue.status === "open" && (
        <div className="mt-2.5" onClick={(e) => e.stopPropagation()} role="presentation">
          <ReviewActions issue={issue} onReviewed={onReviewed} size="sm" />
        </div>
      )}
    </div>
  );
}

// ---- Page -------------------------------------------------------------------

export function IssuesPage() {
  const { data, error, loading, reload } = useApi<Issue[]>(() => api.issues(), []);
  const skillsState = useApi<Skill[]>(() => api.skills(), []);
  const [selected, setSelected] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("open");
  const [query, setQuery] = useState("");
  // Bumped after a successful review so the open detail re-fetches and the list/
  // counts stay in sync.
  const [version, setVersion] = useState(0);

  const issues = data ?? [];

  const skillsByProposal = useMemo(() => {
    const map = new Map<string, Skill[]>();
    for (const s of skillsState.data ?? []) {
      if (!s.proposal_id) continue;
      const arr = map.get(s.proposal_id) ?? [];
      arr.push(s);
      map.set(s.proposal_id, arr);
    }
    return map;
  }, [skillsState.data]);

  const counts = useMemo(() => {
    const c = { open: 0, resolved: 0, dismissed: 0, all: issues.length };
    for (const i of issues) c[bucket(i.status)] += 1;
    return c;
  }, [issues]);

  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => issues.filter((i) => (statusFilter === "all" || bucket(i.status) === statusFilter) && matchesQuery(i, q)),
    [issues, statusFilter, q],
  );

  useEffect(() => {
    if (filtered.length === 0) {
      if (selected !== null) setSelected(null);
      return;
    }
    if (selected === null || !filtered.some((i) => i.id === selected)) {
      setSelected(filtered[0].id);
    }
  }, [filtered, selected]);

  function onReviewed() {
    setVersion((v) => v + 1);
    reload();
  }

  const tabs = STATUS_FILTERS.map((f) => ({ value: f.value, label: `${f.label} (${counts[f.value]})` }));

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Review"
        description="Accept, reject, and comment on tracked issues — and see the skillbook they deliver into."
        icon={<CircleDot className="h-5 w-5" />}
        actions={
          data ? <span className="text-sm text-muted-foreground tabular-nums">{counts.all} total</span> : undefined
        }
      >
        <Tabs variant="segment" value={statusFilter} onChange={(v) => setStatusFilter(v as StatusFilter)} tabs={tabs} />
      </PageHeader>

      <div className="flex flex-1 overflow-hidden">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <div className="flex-1 overflow-y-auto">
            <ErrorNote error={error} />
          </div>
        ) : issues.length === 0 ? (
          <div className="flex-1">
            <Empty
              title="No issues yet"
              hint="Issues are evidence: tracked problems with category/severity, linked proposals, and the skills they deliver."
              icon={<CircleDot className="h-6 w-6" />}
            />
          </div>
        ) : (
          <>
            <div className="flex w-[22rem] shrink-0 flex-col border-r border-border">
              <div className="space-y-2 border-b border-border p-3">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Filter by title, body, section, id…"
                    className="pl-8"
                  />
                </div>
                <div className="px-0.5 text-xs text-muted-foreground tabular-nums">
                  {filtered.length} {filtered.length === 1 ? "issue" : "issues"}
                </div>
              </div>

              <div className="flex-1 space-y-2 overflow-y-auto p-3">
                {filtered.length === 0 ? (
                  <Empty
                    title="Nothing here"
                    hint={q ? "No issues match your filter." : "No issues in this state."}
                  />
                ) : (
                  filtered.map((issue) => (
                    <ReviewCard
                      key={issue.id}
                      issue={issue}
                      active={issue.id === selected}
                      onSelect={() => setSelected(issue.id)}
                      onReviewed={onReviewed}
                    />
                  ))
                )}
              </div>
            </div>

            <div className="min-w-0 flex-1 overflow-y-auto p-6">
              {selected ? (
                <IssueDetail
                  id={selected}
                  version={version}
                  skillsByProposal={skillsByProposal}
                  onReviewed={onReviewed}
                />
              ) : (
                <Empty title="Select an issue to review" />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
