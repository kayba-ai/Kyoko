// DetectorsPage: deterministic Python eval detectors — evidence only.
// Read-only measurement plane; applying lives behind the gate in ChecksPage.

import { ScanSearch } from "lucide-react";
import { api } from "@/lib/api";
import { useApi } from "@/hooks/useApi";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { MeasurePlane } from "@/components/MeasurePlane";

export function DetectorsPage() {
  const defs = useApi(() => api.evals(), []);
  const defRuns = useApi(() => api.evalRuns(), []);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Detectors"
        description="Deterministic Python eval detectors — evidence only"
        icon={<ScanSearch className="h-5 w-5" />}
      />
      <div className="flex flex-1 overflow-hidden">
        <MeasurePlane
          defs={defs.data ?? []}
          runs={defRuns.data ?? []}
          loading={defs.loading}
          error={defs.error}
          runsLoading={defRuns.loading}
          runsError={defRuns.error}
          emptyTitle="No detectors registered"
          emptyHint="Detectors are Python eval definitions registered with kyoko eval register."
          noRunsHint="Run kyoko eval run to produce measurement data."
          listExtraBadges={(d) => <Badge tone="neutral">{d.source}</Badge>}
        />
      </div>
    </div>
  );
}
