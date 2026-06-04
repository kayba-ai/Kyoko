// JudgesPage: LLM-as-judge evaluations — evidence only.
// Read-only measurement plane; applying lives behind the gate in ChecksPage.

import { Scale } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { MeasurePlane } from "@/components/MeasurePlane";
import { humanize } from "@/lib/format";

export function JudgesPage() {
  const defs = useApi(() => api.llmEvals(), []);
  const defRuns = useApi(() => api.llmEvalRuns(), []);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Judges"
        description="LLM-as-judge evaluations — evidence only"
        icon={<Scale className="h-5 w-5" />}
      />
      <div className="flex flex-1 overflow-hidden">
        <MeasurePlane
          defs={defs.data ?? []}
          runs={defRuns.data ?? []}
          loading={defs.loading}
          error={defs.error}
          runsLoading={defRuns.loading}
          runsError={defRuns.error}
          emptyTitle="No judge templates registered"
          emptyHint="LLM-eval judges are registered with kyoko llm-eval register."
          noRunsHint="Run kyoko llm-eval run to produce measurement data."
          listExtraBadges={(d) => (
            <>
              <Badge tone="neutral">{humanize(d.unit_type)}</Badge>
              <Badge tone="neutral">{humanize(d.output_type)}</Badge>
            </>
          )}
          showVars
        />
      </div>
    </div>
  );
}
