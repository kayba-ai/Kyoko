# 0004 - Dashboard Metrics Contract

Status: implemented
Date: 2026-06-01

## Purpose

Kyoko dashboard metrics are product-loop metrics, not observability analytics.
They should help a developer answer whether the local improvement loop is
moving:

1. Did any run fail?
2. Did Kyoko create a scoped issue/proposal?
3. Are check gates generated and passing?
4. Did replay produce a verified before/after result?
5. Did autonomy apply, gate, prepare, or roll back anything?

## API

`GET /api/dashboard-metrics`

Optional query:

- `profile_id`: scope metrics to one workflow profile. If omitted, Kyoko uses
  the first local profile by creation order.

Equivalent local/operator surfaces:

- `kyoko dashboard-metrics --json`
- `kyoko_get_dashboard_metrics` MCP tool

Response shape:

```json
{
  "profile_id": "profile_news_research_001",
  "profile_name": "News Research",
  "scope": "profile",
  "cards": [
    {"id": "issues", "label": "Issues", "value": 1, "detail": "1 context, 0 harness"},
    {"id": "proposal_status", "label": "Proposal Status", "value": 1, "detail": "proposed 1"},
    {"id": "checks", "label": "Check Pass/Fail", "value": "0/0", "detail": "0 specs, latest none"},
    {"id": "replay", "label": "Replay Result", "value": "0/0", "detail": "0 runs, latest none"},
    {"id": "autonomy", "label": "Autonomy Actions", "value": 0, "detail": "no actions yet"},
    {"id": "before_after", "label": "Before/After", "value": "pending", "detail": "run_id -> replay_id"}
  ],
  "runs": {},
  "issues": {},
  "checks": {},
  "replay": {},
  "autonomy": {},
  "before_after": {}
}
```

## Included Metrics

- Runs: total runs, failed runs, failed spans, latest run, latest failed run.
- Issues/proposals: total, active, by state, by section.
- Checks: specs, runs, pass/fail counts, latest status.
- Replay: runs, pass/fail counts, latest status, latest passed replay.
- Autonomy: autonomy timeline event count and action counts.
- Before/after: latest failed run, latest passed replay, output run, and whether
  replay improvement is verified.

## Excluded Metrics

The v0 dashboard must not expand into full observability analytics:

- no latency histograms,
- no token-cost analytics,
- no production SLO/SLA dashboards,
- no multi-tenant/team comparison,
- no arbitrary trace-query dashboard builder.

Those may be future integrations, but they are outside the single-player local
optimization loop.
