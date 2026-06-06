# CLI Reference

The CLI command is `kyoko`. Most commands support `--json`; use that output for
automation and agent workflows.

## First Run

```bash
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko doctor --json
kyoko doctor --safe-smokes --json
kyoko project-bootstrap --project-dir . --profile-name my-agent --json
kyoko serve --db .kyoko/kyoko.db
```

## Ingest And Inspect

```bash
kyoko ingest --db .kyoko/kyoko.db source-events.json --json
kyoko ingest-otlp --db .kyoko/kyoko.db otlp.json --json
kyoko runs --db .kyoko/kyoko.db --json
kyoko run-detail --db .kyoko/kyoko.db <run-id> --json
kyoko current-run --db .kyoko/kyoko.db --json
kyoko run-outline --db .kyoko/kyoko.db <run-id> --json
kyoko search-run --db .kyoko/kyoko.db <run-id> "timeout" --json
kyoko span-context --db .kyoko/kyoko.db <span-id> --json
kyoko span-payload --db .kyoko/kyoko.db <span-id> output --json
```

## Issues And Proposals

```bash
kyoko issues --db .kyoko/kyoko.db --json
kyoko issue-detail --db .kyoko/kyoko.db <issue-id> --json
kyoko issue-create --db .kyoko/kyoko.db --title "Timeout" --evidence-ref span:<span-id> --json
kyoko accept-issue --db .kyoko/kyoko.db <issue-id> --operator mock --json
kyoko propose --db .kyoko/kyoko.db proposal.json --json
kyoko proposals --db .kyoko/kyoko.db --json
kyoko proposal-detail --db .kyoko/kyoko.db <proposal-id> --json
```

## Checks, Replay, And Apply

```bash
kyoko generate-checks --db .kyoko/kyoko.db <proposal-id> --json
kyoko checks --db .kyoko/kyoko.db --json
kyoko run-check --db .kyoko/kyoko.db <check-id> --json
kyoko replay --db .kyoko/kyoko.db <check-id> --json
kyoko replay-detail --db .kyoko/kyoko.db <replay-run-id> --json
kyoko policy --db .kyoko/kyoko.db --json
kyoko run-autonomy --db .kyoko/kyoko.db --json
kyoko apply-proposal --db .kyoko/kyoko.db <proposal-id> --json
```

## Improvement Loop

```bash
kyoko improve \
  --db .kyoko/kyoko.db \
  --operator codex \
  --replay-adapter my-agent_replay \
  --json
```

Other starts:

```bash
kyoko improve --db .kyoko/kyoko.db --proposal-id <proposal-id> --replay-adapter my-agent_replay --json
kyoko improve --db .kyoko/kyoko.db --operator command --command "codex exec ..." --replay-adapter my-agent_replay --json
kyoko improve --db .kyoko/kyoko.db --source-candidate-id <candidate-id> --operator codex --replay-adapter my-agent_replay --json
```

## Operators, Replay Adapters, And MCP

```bash
kyoko operator-adapter-bootstrap --db .kyoko/kyoko.db --json
kyoko operator-adapters --db .kyoko/kyoko.db --json
kyoko operator-adapter-run --db .kyoko/kyoko.db codex --json
kyoko operator-smoke --db .kyoko/kyoko.db --prepare-only --all-presets --json

kyoko replay-adapter-register --db .kyoko/kyoko.db my-agent_replay --server-url http://127.0.0.1:61200 --json
kyoko replay-adapters --db .kyoko/kyoko.db --json
kyoko replay-server-start --db .kyoko/kyoko.db my-agent_replay --json
kyoko replay-server-status --db .kyoko/kyoko.db my-agent_replay --json
kyoko replay-server-stop --db .kyoko/kyoko.db my-agent_replay --json

kyoko mcp serve --db .kyoko/kyoko.db
kyoko mcp install-plan --db .kyoko/kyoko.db --target codex --json
```

## Maintenance

```bash
kyoko status --db .kyoko/kyoko.db --json
kyoko dashboard-metrics --db .kyoko/kyoko.db --json
kyoko storage-report --db .kyoko/kyoko.db --json
kyoko wal-checkpoint --db .kyoko/kyoko.db --json
kyoko prune --db .kyoko/kyoko.db --dry-run --json
kyoko prune-retention --db .kyoko/kyoko.db --older-than-days 30 --dry-run --json
```

## Development And Release

```bash
kyoko validate-gates
kyoko bundled-assets --json
kyoko release-smoke --artifact both --install-deps --json
kyoko dashboard-smoke --output-dir .kyoko/smoke/dashboard --json
```
