import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  CircleDot,
  FlaskConical,
  GitPullRequestArrow,
  LayoutDashboard,
  ScanSearch,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Issue, IssueSeverity } from "@/lib/types";
import { isUnresolvedIssue } from "@/lib/issues";
import { useApi } from "@/hooks/useApi";
import { ago, fmtPercent, humanize } from "@/lib/format";
import { Card, CardBody } from "@/components/ui/card";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner, ErrorNote, Empty } from "@/components/ui/misc";
import { cn } from "@/lib/utils";

// The Overview is an OUTCOME dashboard, not a trace browser: it leads with how
// often the agent is failing and which failure category dominates, then surfaces
// the open issues and where the improvement loop stands. Individual traces live on
// the Traces tab — here we only quantify and rank failure, never list raw spans.

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

// Failure rate is the headline — colour it by how bad it is, not by a flat palette.
function rateTone(rate: number | null): "ok" | "warn" | "danger" {
  if (rate === null || rate <= 0) return "ok";
  if (rate < 5) return "warn";
  return "danger";
}

const TONE_TEXT: Record<string, string> = {
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
  neutral: "text-foreground",
};

const SEVERITY_RANK: Record<IssueSeverity, number> = { high: 3, medium: 2, low: 1 };

function severityTone(sev: IssueSeverity | null | undefined): NonNullable<BadgeProps["tone"]> {
  if (sev === "high") return "danger";
  if (sev === "medium") return "warn";
  return "neutral";
}

/** A small inline metric, used in the hero band and the loop-status strip. */
function MiniStat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  return (
    <div className="min-w-0">
      <div className="truncate text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 text-2xl font-semibold tabular-nums", TONE_TEXT[tone])}>{value}</div>
    </div>
  );
}

type CategoryBucket = {
  key: string;
  label: string;
  total: number;
  high: number;
  medium: number;
  low: number;
  topRank: number;
};

// Group open issues into failure categories (category → falls back to section →
// "Uncategorized"), tracking the severity mix so the bar can show composition and
// the list can rank by "most painful" rather than raw count.
function bucketByCategory(issues: Issue[]): CategoryBucket[] {
  const map = new Map<string, CategoryBucket>();
  for (const issue of issues) {
    const raw = issue.category || issue.section || "uncategorized";
    const key = raw.toLowerCase();
    let bucket = map.get(key);
    if (!bucket) {
      bucket = { key, label: humanize(raw), total: 0, high: 0, medium: 0, low: 0, topRank: 0 };
      map.set(key, bucket);
    }
    bucket.total += 1;
    const sev = (issue.severity ?? "low") as IssueSeverity;
    if (sev === "high") bucket.high += 1;
    else if (sev === "medium") bucket.medium += 1;
    else bucket.low += 1;
    bucket.topRank = Math.max(bucket.topRank, SEVERITY_RANK[sev] ?? 1);
  }
  // Most important first: weight by severity then volume.
  return [...map.values()].sort(
    (a, b) =>
      b.high * 100 + b.medium * 10 + b.low - (a.high * 100 + a.medium * 10 + a.low) || b.total - a.total,
  );
}

function CategoryBar({ bucket, max }: { bucket: CategoryBucket; max: number }) {
  const width = (n: number) => `${max > 0 ? (n / max) * 100 : 0}%`;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate text-sm font-medium text-foreground">{bucket.label}</span>
        <span className="shrink-0 text-sm tabular-nums text-muted-foreground">{bucket.total}</span>
      </div>
      <div className="flex h-2 w-full overflow-hidden rounded-full bg-muted">
        {bucket.high > 0 && <div className="h-full bg-danger" style={{ width: width(bucket.high) }} />}
        {bucket.medium > 0 && <div className="h-full bg-warn" style={{ width: width(bucket.medium) }} />}
        {bucket.low > 0 && <div className="h-full bg-muted-foreground/40" style={{ width: width(bucket.low) }} />}
      </div>
    </div>
  );
}

/** One stage of the optimisation pipeline: Analyse → Issues → Proposals → Evals.
 *  Each tile links to its page and shows the live count at that stage. */
function FlowStage({
  step,
  to,
  icon,
  label,
  value,
  detail,
  tone = "neutral",
}: {
  step: number;
  to: string;
  icon: ReactNode;
  label: string;
  value: ReactNode;
  detail: string;
  tone?: "neutral" | "ok" | "warn" | "danger";
}) {
  return (
    <Link
      to={to}
      className="group flex flex-1 flex-col rounded-xl border border-border bg-card p-4 shadow-xs transition-colors hover:border-primary/40 hover:bg-accent"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary [&>svg]:h-4 [&>svg]:w-4">
            {icon}
          </div>
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {step}. {label}
          </span>
        </div>
        <ArrowRight className="h-4 w-4 text-muted-foreground/40 transition-transform group-hover:translate-x-0.5 group-hover:text-foreground" />
      </div>
      <div className={cn("mt-3 text-2xl font-semibold tabular-nums", TONE_TEXT[tone])}>{value}</div>
      <div className="truncate text-xs text-muted-foreground">{detail}</div>
    </Link>
  );
}

export function OverviewPage() {
  const metrics = useApi(() => api.dashboardMetrics(), []);
  // Fetch the full issue set and derive "unresolved" client-side via the shared
  // bucket logic — every failure that has not been resolved or dismissed,
  // including accepted/proposed (a fix authored but not yet applied is NOT a
  // resolution). The old literal status="open" filter dropped those.
  const openIssues = useApi(() => api.issues(), []);

  const loading = (metrics.loading && !metrics.data) || (openIssues.loading && !openIssues.data);
  const error = metrics.error ?? openIssues.error;

  const m = (metrics.data ?? {}) as Record<string, unknown>;
  const runs = (m.runs ?? {}) as Record<string, unknown>;
  const evals = (m.evals ?? {}) as Record<string, unknown>;
  const proposalCounts = (m.issues ?? {}) as Record<string, unknown>; // learning_proposals counts

  const totalRuns = num(runs.total);

  // Failure is dictated by the eval/measurement plane, never by a status flag on
  // a trace — traces carry no verdict. The rate is failing evaluated runs over all
  // evaluated runs; null (→ "not measured yet") until evals have actually run.
  const evaluatedRuns = num(evals.evaluated_runs);
  const failedRuns = num(evals.failed_runs);
  const measureRuns = num(evals.measure_runs);
  const evalDefinitions = num(evals.definitions);
  const hasEvals = evaluatedRuns > 0;
  const failRate = hasEvals ? (failedRuns / evaluatedRuns) * 100 : null;
  const tone = rateTone(failRate);

  const issues = (openIssues.data ?? []).filter(isUnresolvedIssue);
  const highCount = issues.filter((i) => i.severity === "high").length;
  const mediumCount = issues.filter((i) => i.severity === "medium").length;
  const lowCount = issues.length - highCount - mediumCount;
  const buckets = bucketByCategory(issues);
  const maxBucket = buckets.reduce((mx, b) => Math.max(mx, b.total), 0);
  const topCategory = buckets[0];

  const topIssues = [...issues]
    .sort(
      (a, b) =>
        (SEVERITY_RANK[(b.severity ?? "low") as IssueSeverity] ?? 1) -
          (SEVERITY_RANK[(a.severity ?? "low") as IssueSeverity] ?? 1) ||
        Date.parse(b.created_at) - Date.parse(a.created_at),
    )
    .slice(0, 6);

  const pendingProposals = num(proposalCounts.active);

  const stages: {
    step: number;
    to: string;
    icon: ReactNode;
    label: string;
    value: string;
    detail: string;
    tone?: "neutral" | "ok" | "warn" | "danger";
  }[] = [
    {
      step: 1,
      to: "/analysis",
      icon: <ScanSearch />,
      label: "Analyse",
      value: totalRuns.toLocaleString(),
      detail: totalRuns > 0 ? "traces available" : "no traces yet",
    },
    {
      step: 2,
      to: "/issues",
      icon: <CircleDot />,
      label: "Issues",
      value: issues.length.toLocaleString(),
      detail: issues.length > 0 ? "open to review" : "none open",
      tone: issues.length > 0 ? "warn" : "neutral",
    },
    {
      step: 3,
      to: "/proposals",
      icon: <GitPullRequestArrow />,
      label: "Proposals",
      value: pendingProposals.toLocaleString(),
      detail: pendingProposals > 0 ? "pending approval" : "none pending",
      tone: pendingProposals > 0 ? "warn" : "neutral",
    },
    {
      step: 4,
      to: "/detectors",
      icon: <FlaskConical />,
      label: "Evals",
      value: (hasEvals ? evaluatedRuns : measureRuns).toLocaleString(),
      detail: hasEvals ? "runs scored" : `${evalDefinitions} configured · none run`,
      tone: hasEvals ? (failedRuns > 0 ? "warn" : "ok") : "neutral",
    },
  ];

  const nothingYet = totalRuns === 0 && issues.length === 0 && !metrics.data;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Overview"
        description="How often the agent fails — measured by evals, not trace flags — and where failures concentrate."
        icon={<LayoutDashboard className="h-5 w-5" />}
      />
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <ErrorNote error={error} />
        ) : nothingYet ? (
          <Empty
            title="No telemetry yet"
            hint="Ingest agent runs to see your failure rate, top failure categories, and open issues."
            icon={<LayoutDashboard className="h-6 w-6" />}
          />
        ) : (
          <div className="flex flex-col gap-6">
            {/* The optimisation pipeline: Analyse → Issues → Proposals → Evals.
                Each stage links onward and shows its live count. */}
            <div>
              <div className="mb-3 flex flex-col gap-1">
                <div className="text-xs font-medium text-muted-foreground">Optimisation pipeline</div>
                <div className="text-xs text-muted-foreground">
                  Overview fills in as Kyoko analyses traces, surfaces issues, proposes fixes, and runs evals.
                </div>
              </div>
              <div className="flex flex-col gap-3 lg:flex-row lg:items-stretch">
                {stages.map((s, i) => (
                  <Fragment key={s.label}>
                    <FlowStage
                      step={s.step}
                      to={s.to}
                      icon={s.icon}
                      label={s.label}
                      value={s.value}
                      detail={s.detail}
                      tone={s.tone}
                    />
                    {i < stages.length - 1 && (
                      <div className="flex items-center justify-center text-muted-foreground/40">
                        <ArrowRight className="hidden h-5 w-5 lg:block" />
                      </div>
                    )}
                  </Fragment>
                ))}
              </div>
            </div>

            {/* Hero: the eval-driven failure rate gets the prominence. */}
            <Card>
              <CardBody className="flex flex-col gap-6 p-6 lg:flex-row lg:items-center lg:justify-between">
                <div className="flex items-start gap-4">
                  <div
                    className={cn(
                      "flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl",
                      !hasEvals
                        ? "bg-muted text-muted-foreground"
                        : tone === "danger"
                          ? "bg-danger/10 text-danger"
                          : tone === "warn"
                            ? "bg-warn/10 text-warn"
                            : "bg-ok/10 text-ok",
                    )}
                  >
                    {!hasEvals ? (
                      <FlaskConical className="h-6 w-6" />
                    ) : tone === "ok" ? (
                      <CheckCircle2 className="h-6 w-6" />
                    ) : (
                      <AlertTriangle className="h-6 w-6" />
                    )}
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground">
                      Run failure rate <span className="text-muted-foreground/60">· by evals</span>
                    </div>
                    {hasEvals ? (
                      <>
                        <div className={cn("text-5xl font-semibold tabular-nums tracking-tight", TONE_TEXT[tone])}>
                          {fmtPercent(failRate)}
                        </div>
                        <div className="mt-1 text-sm text-muted-foreground">
                          {failedRuns.toLocaleString()} of {evaluatedRuns.toLocaleString()} evaluated runs failed their
                          evals
                        </div>
                      </>
                    ) : (
                      <>
                        <div className="text-3xl font-semibold tracking-tight text-foreground">
                          Not measured yet - start analysing your agents' behaviour
                        </div>
                        <div className="mt-1 max-w-md text-sm text-muted-foreground">
                          A trace isn't a pass or fail on its own — run evaluations to measure how often the agent
                          fails.{" "}
                          <Link to="/detectors" className="font-medium text-primary hover:underline">
                            Run evals →
                          </Link>
                        </div>
                      </>
                    )}
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-6 border-t border-border/70 pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                  <MiniStat label="Evaluated runs" value={evaluatedRuns.toLocaleString()} />
                  <MiniStat label="Open issues" value={issues.length.toLocaleString()} tone={issues.length > 0 ? "warn" : "neutral"} />
                  <MiniStat label="High severity" value={highCount.toLocaleString()} tone={highCount > 0 ? "danger" : "neutral"} />
                </div>
              </CardBody>
            </Card>

            {/* Failure breakdown: top categories (the "most important" one leads). */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <Card className="lg:col-span-2">
                <CardBody className="flex flex-col gap-4 p-5">
                  <div className="flex items-baseline justify-between gap-3">
                    <div>
                      <div className="text-md font-semibold text-foreground">Top failure categories</div>
                      <div className="text-xs text-muted-foreground">
                        Open issues grouped by category, ranked by severity.
                      </div>
                    </div>
                    {topCategory && (
                      <Badge tone={topCategory.high > 0 ? "danger" : topCategory.medium > 0 ? "warn" : "neutral"}>
                        Top: {topCategory.label}
                      </Badge>
                    )}
                  </div>
                  {buckets.length === 0 ? (
                    <div className="py-6 text-center text-sm text-muted-foreground">
                      No open issues to categorize.{" "}
                      <Link to="/analysis" className="font-medium text-primary hover:underline">
                        Start analysis.
                      </Link>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-3.5">
                      {buckets.slice(0, 6).map((b) => (
                        <CategoryBar key={b.key} bucket={b} max={maxBucket} />
                      ))}
                    </div>
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardBody className="flex flex-col gap-4 p-5">
                  <div className="text-md font-semibold text-foreground">By severity</div>
                  <div className="flex flex-col gap-3">
                    <SeverityRow label="High" count={highCount} total={issues.length} tone="danger" />
                    <SeverityRow label="Medium" count={mediumCount} total={issues.length} tone="warn" />
                    <SeverityRow label="Low" count={lowCount} total={issues.length} tone="neutral" />
                  </div>
                  <Link
                    to="/issues"
                    className="mt-auto inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                  >
                    Review all issues <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </CardBody>
              </Card>
            </div>

            {/* Prominence of the actual failures: the open-issue queue. */}
            <Card>
              <CardBody className="p-0">
                <div className="flex items-center justify-between border-b border-border/70 px-5 py-3">
                  <div className="text-md font-semibold text-foreground">Open issues</div>
                  <Link to="/issues" className="text-sm font-medium text-primary hover:underline">
                    View all
                  </Link>
                </div>
                {topIssues.length === 0 ? (
                  <div className="px-5 py-8 text-center text-sm text-muted-foreground">
                    No open issues yet.{" "}
                    <Link to="/analysis" className="font-medium text-primary hover:underline">
                      Start analysis to surface recurring failures.
                    </Link>
                  </div>
                ) : (
                  <ul className="divide-y divide-border/60">
                    {topIssues.map((issue) => (
                      <li key={issue.id} className="flex items-center gap-3 px-5 py-3">
                        <Badge tone={severityTone(issue.severity)} className="shrink-0">
                          {humanize(issue.severity ?? "low")}
                        </Badge>
                        <span className="min-w-0 flex-1 truncate text-sm text-foreground">{issue.title}</span>
                        {(issue.category || issue.section) && (
                          <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
                            {humanize(issue.category || issue.section || "")}
                          </span>
                        )}
                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                          {ago(issue.created_at)}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}

function SeverityRow({
  label,
  count,
  total,
  tone,
}: {
  label: string;
  count: number;
  total: number;
  tone: "danger" | "warn" | "neutral";
}) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  const bar = tone === "danger" ? "bg-danger" : tone === "warn" ? "bg-warn" : "bg-muted-foreground/40";
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm text-foreground">{label}</span>
        <span className="text-sm tabular-nums text-muted-foreground">{count}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
        <div className={cn("h-full rounded-full", bar)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
