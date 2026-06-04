import { useEffect, useState } from "react";
import { CircleDot } from "lucide-react";
import { api } from "@/lib/api";
import type { Issue } from "@/lib/types";
import { ago } from "@/lib/format";
import { useApi } from "@/hooks/useApi";
import { Badge, statusTone } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Spinner, Empty, ErrorNote } from "@/components/ui/misc";
import { JsonView } from "@/components/JsonView";
import { cn } from "@/lib/utils";

// Issues are first-class EVIDENCE (read/propose side): a tracked problem with a
// category/severity, links to affected canonical entities, and optional backlinks to the
// proposals that address it. This dashboard only VIEWS them — creating or resolving an
// issue never changes agent behavior or bypasses the check/replay gate.

function severityTone(severity: string | null | undefined): "danger" | "warn" | "neutral" {
  if (severity === "high") return "danger";
  if (severity === "medium") return "warn";
  return "neutral";
}

function IssueBadges({ issue }: { issue: Issue }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Badge tone={statusTone(issue.status)}>{issue.status}</Badge>
      {issue.severity && <Badge tone={severityTone(issue.severity)}>{issue.severity}</Badge>}
      {issue.section && <Badge tone="neutral">{issue.section}</Badge>}
    </div>
  );
}

function AffectedList({ title, items }: { title: string; items: { entity_id: string; found: boolean }[] }) {
  if (!items.length) return null;
  return (
    <div className="space-y-1">
      <div className="text-xs font-medium text-muted-foreground">{title}</div>
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.entity_id} className="flex items-center gap-2 font-mono text-xs text-foreground/85">
            <span>{item.entity_id}</span>
            {!item.found && <Badge tone="warn">missing</Badge>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function IssueDetail({ id }: { id: string }) {
  const { data, error, loading } = useApi<Record<string, unknown>>(() => api.issueDetail(id), [id]);

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

  const sectionDescription = (data.section_description as string | undefined) ?? null;
  const affected = (data.affected as Record<string, { entity_id: string; found: boolean }[]>) ?? {};
  const linkedProposals = (data.linked_proposals as { proposal: { id: string; title?: string; state?: string } }[]) ?? [];
  const hasAffected =
    (affected.agent_identities?.length ?? 0) +
      (affected.workflow_nodes?.length ?? 0) +
      (affected.tasks?.length ?? 0) +
      (affected.spans?.length ?? 0) >
    0;

  return (
    <div className="space-y-3 p-4">
      <div className="space-y-2">
        <h2 className="text-md font-semibold text-foreground">{issue.title}</h2>
        <IssueBadges issue={issue} />
        {issue.category && <p className="text-xs text-muted-foreground/80">Category: {issue.category}</p>}
        {sectionDescription && <p className="text-xs text-muted-foreground/80">{sectionDescription}</p>}
      </div>

      {issue.body && (
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/85">{issue.body}</p>
      )}

      {hasAffected && (
        <Card>
          <CardHeader>
            <CardTitle>Affected entities</CardTitle>
          </CardHeader>
          <CardBody className="space-y-3">
            <AffectedList title="Agents" items={affected.agent_identities ?? []} />
            <AffectedList title="Workflow nodes" items={affected.workflow_nodes ?? []} />
            <AffectedList title="Tasks" items={affected.tasks ?? []} />
            <AffectedList title="Spans" items={affected.spans ?? []} />
          </CardBody>
        </Card>
      )}

      {linkedProposals.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Linked proposals</CardTitle>
          </CardHeader>
          <CardBody className="space-y-1.5">
            {linkedProposals.map((entry) => (
              <div key={entry.proposal.id} className="flex items-center gap-2">
                {entry.proposal.state && <Badge tone={statusTone(entry.proposal.state)}>{entry.proposal.state}</Badge>}
                <span className="text-sm text-foreground/85">{entry.proposal.title ?? entry.proposal.id}</span>
              </div>
            ))}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Full issue</CardTitle>
        </CardHeader>
        <CardBody>
          <JsonView data={data} />
        </CardBody>
      </Card>
    </div>
  );
}

export function IssuesPage() {
  const { data, error, loading } = useApi<Issue[]>(() => api.issues(), []);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (data && data.length > 0 && selected === null) {
      setSelected(data[0].id);
    }
  }, [data, selected]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
        <h1 className="text-md font-semibold">Issues</h1>
        {data && <span className="text-xs text-muted-foreground">{data.length} total</span>}
      </div>
      <div className="flex min-h-0 flex-1">
        {loading ? (
          <div className="flex flex-1 items-center justify-center">
            <Spinner />
          </div>
        ) : error ? (
          <div className="flex-1 overflow-auto">
            <ErrorNote error={error} />
          </div>
        ) : !data || data.length === 0 ? (
          <div className="flex-1">
            <Empty
              title="No issues yet"
              hint="Issues are evidence: tracked problems with category/severity and links to affected entities and proposals."
              icon={<CircleDot className="h-6 w-6" />}
            />
          </div>
        ) : (
          <>
            <div className="w-80 shrink-0 overflow-auto border-r border-white/[0.06] p-2">
              <div className="space-y-1.5">
                {data.map((issue) => {
                  const active = issue.id === selected;
                  return (
                    <button
                      key={issue.id}
                      onClick={() => setSelected(issue.id)}
                      className={cn(
                        "w-full rounded-md border p-2.5 text-left transition-colors",
                        active
                          ? "border-primary/30 bg-white/[0.05]"
                          : "border-white/[0.06] hover:bg-white/[0.03]",
                      )}
                    >
                      <div className="mb-1.5 text-sm font-medium text-foreground/90">{issue.title}</div>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <IssueBadges issue={issue} />
                        <span className="ml-auto text-label text-muted-foreground/70">{ago(issue.created_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="min-w-0 flex-1 overflow-auto">
              {selected ? <IssueDetail id={selected} /> : <Empty title="Select an issue" />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
