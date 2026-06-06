import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Check,
  CheckCheck,
  CircleDot,
  FileSearch,
  Lightbulb,
  Loader2,
  Lock,
  MessageSquare,
  Repeat,
  RotateCcw,
  Search,
  Shield,
  ShieldCheck,
  Stethoscope,
  Tag,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { AcceptIssueResult, AutonomyPolicy, Issue, IssueStatus, Skill } from "@/lib/types";
import { ago, fmtTime, humanize } from "@/lib/format";
import { narrateIssue, sectionPhrase, severityPhrase } from "@/lib/narrate";
import { useApi } from "@/hooks/useApi";
import { useLiveEvent } from "@/hooks/useLiveBus";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { Disclosure } from "@/components/ui/disclosure";
import { Input, Textarea } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { Spinner, Empty, ErrorNote } from "@/components/ui/misc";
import { PageHeader } from "@/components/ui/page-header";
import { StatusBanner, StageTag } from "@/components/StatusBanner";
import { StructuredDetail } from "@/components/RecordView";
import { cn } from "@/lib/utils";

// Issues are first-class EVIDENCE. This page is a REVIEW QUEUE: you accept (resolve)
// or reject (dismiss) each tracked problem, leave a review comment, and see the
// skillbook deliverable the issue feeds into. Review is bookkeeping on the evidence
// record — it never changes agent behavior, mutates a skillbook/harness/repo, or
// bypasses the check/replay gate.

type StatusFilter = "open" | "accepted" | "resolved" | "dismissed" | "all";

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: "open", label: "Pending" },
  { value: "accepted", label: "Accepted" },
  { value: "resolved", label: "Resolved" },
  { value: "dismissed", label: "Rejected" },
  { value: "all", label: "All" },
];

// Statuses where the issue is still in the triage/diagnosis stage and can be
// accepted at gate #1. "accepted" and beyond are already past the gate.
const ACCEPTABLE_STATUSES = new Set<string>(["open", "prioritized", "diagnosed"]);

// Bucket any lifecycle status into the four review-queue filters. Gate #1 splits
// the queue: pre-accept (triage) → Pending; accepted/proposed (gate #1 done, a fix
// is being authored / awaiting gate-#2 approval on Proposals) → Accepted; the
// applied/resolved end-states → Resolved; dismissed → Rejected.
function bucket(status: string): "open" | "accepted" | "resolved" | "dismissed" {
  if (status === "resolved" || status === "applied" || status === "guarded") return "resolved";
  if (status === "accepted" || status === "proposed") return "accepted";
  if (status === "dismissed") return "dismissed";
  return "open";
}

function matchesQuery(issue: Issue, q: string): boolean {
  if (!q) return true;
  const haystack = [issue.title, issue.body, issue.section, issue.id, issue.category, issue.severity]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(q);
}

// ---- Review actions (accept at gate #1 / approve+apply at gate #2 / reject) --
//
// Gate #1 lives here (triage): "Accept" (POST /api/issues/accept) authors a proposal
// for the issue; Reject/Reopen are plain status bookkeeping. Gate #2 (review + apply the
// authored fix) lives on the Proposals page — once a fix is authored this surfaces a
// deep-link there rather than an apply control, so each tab owns exactly one gate.

// The issue has cleared gate #1 and a fix is authored / being authored.
const ACCEPTED_STATUSES = new Set<string>(["accepted", "proposed"]);

function firstProposalId(issue: Issue, accepted: AcceptIssueResult | null): string | null {
  return accepted?.propose?.proposal_id ?? issue.proposal_ids?.[0] ?? null;
}

// Deep-link to a specific authored proposal on the Proposals (gate #2) page.
function proposalLink(proposalId: string | null): string {
  return proposalId ? `/proposals?id=${encodeURIComponent(proposalId)}` : "/proposals";
}

function ReviewActions({
  issue,
  onReviewed,
  size = "default",
}: {
  issue: Issue;
  onReviewed: () => void;
  size?: "sm" | "default";
}) {
  const [pending, setPending] = useState<"accept" | IssueStatus | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [accepted, setAccepted] = useState<AcceptIssueResult | null>(null);
  // A real operator authors the proposal on the background runner, which can take minutes;
  // hold this until the issue re-fetches with a proposal (driven by the analysis_run SSE
  // event at the page level), then surface the "review on Proposals" link.
  const [authoring, setAuthoring] = useState<string | null>(null);

  const proposalId = firstProposalId(issue, accepted);
  // Gate #1 cleared and a fix exists → point the user at gate #2 on the Proposals page.
  const fixAuthored = ACCEPTED_STATUSES.has(issue.status) && !!proposalId;

  // The operator finished: a proposal now exists on the re-fetched issue → drop the
  // "Authoring…" state so the "review on Proposals" link shows.
  useEffect(() => {
    if (authoring && (issue.proposal_ids?.length ?? 0) > 0) setAuthoring(null);
  }, [authoring, issue.proposal_ids]);

  const canAccept = !authoring && ACCEPTABLE_STATUSES.has(issue.status);
  const busy = pending !== null;

  async function accept() {
    setPending("accept");
    setError(null);
    try {
      const res = await api.acceptIssue(issue.id);
      if (res.status === "authoring") {
        // Async path: a real operator is authoring. The proposal arrives via SSE; show a
        // pending label until the re-fetched issue carries it.
        setAuthoring(res.operator ?? "operator");
      } else {
        setAccepted(res);
      }
      onReviewed();
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setPending(null);
    }
  }

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

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex items-center gap-2">
        {issue.status === "dismissed" ? (
          <Button variant="outline" size={size} disabled={busy} onClick={() => review("open")}>
            {pending === "open" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
            Reopen
          </Button>
        ) : (
          <>
            {canAccept && (
              <>
                <Button variant="default" size={size} disabled={busy} onClick={accept}>
                  {pending === "accept" ? (
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
            )}
            {fixAuthored && (
              <Link to={proposalLink(proposalId)} className={buttonVariants({ variant: "default", size })}>
                <CheckCheck className="h-3.5 w-3.5" />
                Review fix →
              </Link>
            )}
          </>
        )}
        {authoring && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Authoring proposal… ({authoring})
          </span>
        )}
      </div>
      {fixAuthored && (
        <span className="text-right text-xs text-muted-foreground">
          Fix authored — review &amp; approve on Proposals.
        </span>
      )}
      {error && (
        <span className="text-xs text-danger" role="alert">
          {error.message}
        </span>
      )}
    </div>
  );
}

// ---- Autonomy summary (read-only, deep-links to the control) ----------------
//
// The two-mode policy (spec 0018) lives on the Autonomy page; surface it here
// near the accept controls so what "Accept" will do is discoverable from triage.

function AutonomySummary({ issue }: { issue: Issue }) {
  const { data: policy } = useApi<AutonomyPolicy>(() => api.policy(), []);
  if (!policy) return null;
  const mode = policy.mode === "autonomous" ? "autonomous" : "hitl";
  const tone: NonNullable<BadgeProps["tone"]> = mode === "autonomous" ? "ok" : "neutral";
  const threshold = policy.recurrence_threshold ?? 0;
  const seen = issue.recurrence_count ?? 1;
  const hint =
    mode === "autonomous"
      ? threshold > 0 && seen < threshold
        ? `Kyoko auto-fixes once this recurs ${threshold}× (seen ${seen}×).`
        : "Kyoko authors and applies a fix automatically."
      : "You accept the issue, then approve the authored proposal.";
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
      <ShieldCheck className="h-3.5 w-3.5 text-muted-foreground" />
      <span>
        Autonomy: <Badge tone={tone}>{mode === "autonomous" ? "Autonomous" : "HITL"}</Badge>
      </span>
      <span className="text-muted-foreground/80">{hint}</span>
      <Link to="/autonomy" className="ml-auto inline-flex items-center gap-1 text-primary hover:underline">
        Change <ArrowRight className="h-3 w-3" />
      </Link>
    </div>
  );
}

// ---- Recurrence progress toward the autonomous-fix threshold ----------------

function RecurrenceProgress({ issue }: { issue: Issue }) {
  const { data: policy } = useApi<AutonomyPolicy>(() => api.policy(), []);
  const threshold = policy?.recurrence_threshold ?? 0;
  const seen = issue.recurrence_count ?? 1;
  if (threshold <= 0) return null;
  const pct = Math.min(100, Math.round((seen / threshold) * 100));
  const ready = seen >= threshold;
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-muted-foreground">Recurrence toward auto-fix</span>
        <span className="tabular-nums text-foreground">
          {seen} / {threshold}
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full transition-all", ready ? "bg-ok" : "bg-primary")}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

// ---- Guard + rollback status (applied fixes) --------------------------------
//
// Once a fix is applied, surface its guard/rollback posture: when it was applied,
// how many recurrences have happened since (the regression-guard signal), and
// whether autonomy has been blocked (escalated). Evidence-only.

function GuardStatus({ issue }: { issue: Issue }) {
  const applied = issue.status === "applied" || issue.status === "resolved" || issue.status === "guarded";
  const hasGuard = !!issue.evaluator_id || applied || issue.applied_at != null;
  if (!hasGuard) return null;

  const seen = issue.recurrence_count ?? 0;
  const atApply = issue.recurrence_count_at_apply ?? null;
  const postApply = atApply != null ? Math.max(0, seen - atApply) : null;

  return (
    <div className="rounded-lg border border-border bg-muted/40 px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <Shield className="h-3.5 w-3.5" />
        Guard &amp; rollback
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
        {issue.applied_at && (
          <span>
            Applied <span title={fmtTime(issue.applied_at)} className="text-foreground">{ago(issue.applied_at)}</span>
          </span>
        )}
        {issue.evaluator_id && (
          <span className="inline-flex items-center gap-1">
            <Badge tone="primary" title={`Guarded by ${issue.evaluator_id}`}>
              <Shield className="h-3 w-3" />
              Guarded
            </Badge>
          </span>
        )}
        {postApply != null && (
          <span className="tabular-nums">
            Post-apply recurrences:{" "}
            <span className={cn(postApply > 0 ? "text-warn" : "text-foreground")}>{postApply}</span>
          </span>
        )}
        {issue.autonomy_blocked ? (
          <Badge tone="danger">
            <Lock className="h-3 w-3" />
            Auto-fix exhausted
          </Badge>
        ) : (
          <Badge tone="ok">No regression detected</Badge>
        )}
      </div>
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

// Tone an evidence ref's role: a "role" naming the fault/cause reads as a problem,
// plain context stays neutral.
function roleTone(role: string | null): NonNullable<BadgeProps["tone"]> {
  const r = (role ?? "").toLowerCase();
  if (["fault", "error", "failure", "cause", "root_cause", "violation", "bug"].includes(r)) return "danger";
  if (["risk", "warning", "concern", "symptom"].includes(r)) return "warn";
  return "neutral";
}

// Evidence refs are the actual proof behind an issue: each carries a plain-English
// `note` (what was seen in that span) plus a reference to the span/entity it came
// from. Render the note as the readable line and the reference as a quiet chip —
// far more useful than dumping the raw JSON.
function EvidenceList({ refs }: { refs: Record<string, unknown>[] }) {
  return (
    <div className="space-y-2">
      {refs.map((ref, i) => {
        const note = typeof ref.note === "string" ? ref.note : null;
        const entityId = typeof ref.entity_id === "string" ? ref.entity_id : null;
        const entityType = typeof ref.entity_type === "string" ? ref.entity_type : null;
        const role = typeof ref.role === "string" ? ref.role : null;
        return (
          <div key={i} className="rounded-lg border border-border bg-muted/40 p-3">
            {note ? (
              <p className="text-sm leading-relaxed text-foreground">{note}</p>
            ) : (
              <p className="text-sm text-muted-foreground/70">Referenced as evidence.</p>
            )}
            {(role || entityId) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5">
                {role && <Badge tone={roleTone(role)}>{humanize(role)}</Badge>}
                {entityId && (
                  <span className="inline-flex items-center gap-1 font-mono text-label text-muted-foreground">
                    {entityType && <span className="opacity-60">{entityType}</span>}
                    {entityId}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
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

  const narration = narrateIssue(issue);
  const sev = severityPhrase(issue.severity);
  const seen = issue.recurrence_count ?? 1;
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

  const hasSources = sourceGroups.length > 0 || linkedProposals.length > 0;
  const hasMore = !!issue.body || hasSources;

  return (
    <div className="mx-auto max-w-3xl space-y-5 pb-4">
      {/* The problem, in one line, with the human-readable basics underneath. */}
      <div className="space-y-2">
        <h2 className="text-2xl font-bold leading-snug tracking-tight text-foreground">{issue.title}</h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
          {issue.category && (
            <Badge tone="primary" title="Issue category">
              <Tag className="h-3 w-3" />
              {humanize(issue.category)}
            </Badge>
          )}
          {sev && (
            <span
              className={cn(
                "font-medium",
                issue.severity === "high" && "text-danger",
                issue.severity === "medium" && "text-warn",
              )}
            >
              {sev}
            </span>
          )}
          {seen > 1 && (
            <span className="inline-flex items-center gap-1">
              <Repeat className="h-3 w-3" />
              Seen {seen} times
            </span>
          )}
          {issue.section && <span>Affects {sectionPhrase(issue.section)}</span>}
        </div>
        {sectionDescription && <p className="text-sm text-muted-foreground">{sectionDescription}</p>}
      </div>

      {/* What's happening, in plain English — plus the one action that matters here. */}
      <StatusBanner narration={narration} actions={<ReviewActions issue={issue} onReviewed={onReviewed} />} />

      {/* How close a recurring problem is to an automatic fix. */}
      {ACCEPTABLE_STATUSES.has(issue.status) && <RecurrenceProgress issue={issue} />}

      {/* What "Accept" will do under the current autonomy setting. */}
      {(ACCEPTABLE_STATUSES.has(issue.status) || ACCEPTED_STATUSES.has(issue.status)) && (
        <AutonomySummary issue={issue} />
      )}

      {/* Why it happens — diagnosis in plain language. */}
      {issue.root_cause && (
        <Section label="Why it happens" icon={<Stethoscope className="h-3.5 w-3.5" />}>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{issue.root_cause}</p>
        </Section>
      )}

      {/* Evidence — the proof, in readable notes rather than raw refs. Kept in
          plain view because it's the thing a reviewer actually weighs. */}
      {evidenceRefs.length > 0 && (
        <Section label={`Evidence (${evidenceRefs.length})`} icon={<FileSearch className="h-3.5 w-3.5" />}>
          <EvidenceList refs={evidenceRefs} />
        </Section>
      )}

      {/* The skillbook entry this issue produced. */}
      {deliveredSkills.length > 0 && (
        <div className="space-y-2">
          {deliveredSkills.map((s) => (
            <SkillDeliverable key={s.id} skill={s} />
          ))}
        </div>
      )}

      {/* Once a fix is live, how it's holding up. */}
      <GuardStatus issue={issue} />

      {/* Your notes */}
      <Section label="Your notes" icon={<MessageSquare className="h-3.5 w-3.5" />}>
        <CommentEditor key={issue.id} issue={issue} onSaved={onReviewed} />
      </Section>

      {/* Secondary detail lives behind a click so the first glance stays clean. */}
      {hasMore && (
        <Disclosure summary="Full description & affected parts">
          <div className="space-y-5">
            {issue.body && (
              <Section label="Full description">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground">{issue.body}</p>
              </Section>
            )}
            {hasSources && (
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
                            {entry.proposal.state && <Badge tone="neutral">{humanize(entry.proposal.state)}</Badge>}
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
          </div>
        </Disclosure>
      )}

      {/* Identifiers & timestamps. */}
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

      {/* The complete raw record, for anyone who wants it. */}
      <Disclosure summary="Full record (raw)">
        <Card>
          <CardBody>
            <StructuredDetail data={data} defaultView="raw" />
          </CardBody>
        </Card>
      </Disclosure>

      <p className="text-xs text-muted-foreground/70">
        Reviewing updates this evidence record only — it never changes agent behavior or bypasses the check/replay
        gate.
      </p>
    </div>
  );
}

// ---- Category facet ---------------------------------------------------------

// A toggleable chip for the free-text issue category. Selecting one narrows the
// list to that domain; selecting it again (or "All") clears the facet.
function CategoryChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium leading-none transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40",
        active
          ? "border-primary/30 bg-primary/10 text-primary"
          : "border-border bg-muted/60 text-muted-foreground hover:bg-accent",
      )}
    >
      {label}
      <span className="tabular-nums opacity-70">{count}</span>
    </button>
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
  const narration = narrateIssue(issue);
  const seen = issue.recurrence_count ?? 1;
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
        <StageTag narration={narration} />
        {issue.category && (
          <Badge tone="neutral" title="Issue category">
            <Tag className="h-3 w-3" />
            {humanize(issue.category)}
          </Badge>
        )}
        {issue.severity === "high" && <Badge tone="danger">High impact</Badge>}
        {seen > 1 && (
          <Badge tone="warn" title="Times this problem has recurred" className="tabular-nums">
            <Repeat className="h-3 w-3" />
            {`${seen}×`}
          </Badge>
        )}
        <span className="ml-auto text-label text-muted-foreground">{ago(issue.created_at)}</span>
      </div>
      {(ACCEPTABLE_STATUSES.has(issue.status) ||
        (ACCEPTED_STATUSES.has(issue.status) && (issue.proposal_ids?.length ?? 0) > 0)) && (
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
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
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
    const c = { open: 0, accepted: 0, resolved: 0, dismissed: 0, all: issues.length };
    for (const i of issues) c[bucket(i.status)] += 1;
    return c;
  }, [issues]);

  const q = query.trim().toLowerCase();
  // Status + text filtered, but BEFORE the category facet — this is the set the
  // category chips are derived from, so every available category stays selectable.
  const statusScoped = useMemo(
    () => issues.filter((i) => (statusFilter === "all" || bucket(i.status) === statusFilter) && matchesQuery(i, q)),
    [issues, statusFilter, q],
  );
  // Distinct free-text categories present in the current view, with counts, sorted.
  const categories = useMemo(() => {
    const m = new Map<string, number>();
    for (const i of statusScoped) if (i.category) m.set(i.category, (m.get(i.category) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [statusScoped]);
  const filtered = useMemo(
    () => statusScoped.filter((i) => !categoryFilter || i.category === categoryFilter),
    [statusScoped, categoryFilter],
  );

  // Drop a category selection that no longer exists in the current status/query scope.
  useEffect(() => {
    if (categoryFilter && !categories.some(([c]) => c === categoryFilter)) setCategoryFilter(null);
  }, [categories, categoryFilter]);

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

  // A background "approve issue" authoring job (real operator) finishes asynchronously and
  // streams its terminal status over the analysis_run channel; reload so the newly authored
  // proposal shows up and "Approve & apply" lights up on the affected issue.
  useLiveEvent("analysis_run", (ev: { status?: string }) => {
    const status = (ev?.status ?? "").toLowerCase();
    if (status === "succeeded" || status === "failed" || status === "cancelled") {
      onReviewed();
    }
  });

  const tabs = STATUS_FILTERS.map((f) => ({ value: f.value, label: `${f.label} (${counts[f.value]})` }));

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Issues"
        description="The spine of the loop — triage, diagnose, and resolve tracked failures; every fix originates here."
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
                    placeholder="Filter by title, body, section, id, category…"
                    className="pl-8"
                  />
                </div>
                {categories.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    <CategoryChip
                      label="All"
                      count={statusScoped.length}
                      active={!categoryFilter}
                      onClick={() => setCategoryFilter(null)}
                    />
                    {categories.map(([cat, n]) => (
                      <CategoryChip
                        key={cat}
                        label={humanize(cat)}
                        count={n}
                        active={categoryFilter === cat}
                        onClick={() => setCategoryFilter((c) => (c === cat ? null : cat))}
                      />
                    ))}
                  </div>
                )}
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
