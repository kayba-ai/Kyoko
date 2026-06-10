# CLI Reference

The CLI command is `kyoko`. Most commands support `--json`; use JSON output
for automation, MCP-facing workflows, tests, and coding agents.

Use `kyoko <command> --help` for full arguments. The groups below cover
the commands most users reach for first.

`--db` defaults to the nearest `.kyoko/kyoko.db` above the current directory
(falling back to `~/.kyoko/kyoko.db`), so inside a bootstrapped project the
flag can be omitted. The snippets below keep it explicit for copy-paste use
from anywhere.

## First Run

```bash
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko serve --db /tmp/kyoko-demo.db
kyoko doctor --json
kyoko doctor --safe-smokes --json
```

Bootstrap inside a project (flags such as `--profile-name` and `--mcp-target`
are optional; see `kyoko project-bootstrap --help` for defaults):

```bash
kyoko project-bootstrap
```

## Ingest And Inspect Runs

```bash
kyoko discover-sources --db .kyoko/kyoko.db --root-path . --json
kyoko ingest-otlp --db .kyoko/kyoko.db otlp.json --profile-id my-agent --json
kyoko runs --db .kyoko/kyoko.db --json
kyoko current-run --db .kyoko/kyoko.db --json
kyoko run-detail --db .kyoko/kyoko.db <run-id> --json
kyoko run-outline --db .kyoko/kyoko.db <run-id> --json
kyoko search-run --db .kyoko/kyoko.db <run-id> "timeout" --json
kyoko span-context --db .kyoko/kyoko.db <span-id> --json
kyoko span-payload --db .kyoko/kyoko.db <span-id> --target output --json
```

Use `ingest-otlp` for user-facing trace uploads. Kyoko normalizes OTLP/GenAI
exports into its canonical source-event envelope before storing them.

`kyoko ingest` is the adapter/SDK boundary for already-normalized Kyoko
source-event JSON produced by Kyoko SDKs, generated source adapters, and
offline importers:

```bash
kyoko ingest --db .kyoko/kyoko.db source-events.json --json
```

## Issues And Proposals

```bash
kyoko issues --db .kyoko/kyoko.db --json
kyoko issue-detail --db .kyoko/kyoko.db <issue-id> --json
kyoko issue-create --db .kyoko/kyoko.db "Search timeout" \
  --body "Search span timed out; inspect span:<span-id>." \
  --json
kyoko issue-status --db .kyoko/kyoko.db <issue-id> resolved --json
kyoko accept-issue --db .kyoko/kyoko.db <issue-id> --operator mock --json
kyoko propose --db .kyoko/kyoko.db proposal.json --json
kyoko proposals --db .kyoko/kyoko.db --json
kyoko proposal-detail --db .kyoko/kyoko.db <proposal-id> --json
```

## Checks, Replay, And Apply

```bash
kyoko generate-checks --db .kyoko/kyoko.db <proposal-id> --json
kyoko checks --db .kyoko/kyoko.db --json
kyoko check-detail --db .kyoko/kyoko.db <check-id> --json
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

## Integrations

Generate source and replay scaffolds:

```bash
kyoko source-adapter-template .kyoko/scripts/source_adapter.py \
  --framework generic-python \
  --profile-name my-agent \
  --json

kyoko replay-server-template .kyoko/scripts/replay_server.py \
  --framework generic-python \
  --profile-name my-agent \
  --json
```

Smoke generated integrations:

```bash
kyoko integration-smoke source .kyoko/scripts/source_adapter.py \
  --hook path/to/source_hook.py:collect \
  --json

kyoko integration-smoke replay-server \
  --command "python3 .kyoko/scripts/replay_server.py --port 61200" \
  --server-url http://127.0.0.1:61200 \
  --hook path/to/replay_hook.py:replay \
  --run-replay \
  --json
```

Register and run adapters:

```bash
kyoko operator-adapter-bootstrap --db .kyoko/kyoko.db --json
kyoko operator-adapters --db .kyoko/kyoko.db --json
kyoko operator-adapter-run --db .kyoko/kyoko.db codex --json

kyoko replay-adapter-register --db .kyoko/kyoko.db my-agent_replay \
  --name "My Agent replay" \
  --server-url http://127.0.0.1:61200 \
  --json
kyoko replay-adapters --db .kyoko/kyoko.db --json
kyoko replay-server-start --db .kyoko/kyoko.db my-agent_replay --json
kyoko replay-server-status --db .kyoko/kyoko.db my-agent_replay --json
kyoko replay-server-stop --db .kyoko/kyoko.db my-agent_replay --json
```

## MCP

```bash
kyoko mcp config --db .kyoko/kyoko.db --target codex --json
kyoko mcp install-plan --db .kyoko/kyoko.db --target codex --json
kyoko mcp install --db .kyoko/kyoko.db --target generic --output .kyoko/config/mcp.json --json
kyoko mcp serve --db .kyoko/kyoko.db
```

## Maintenance

```bash
kyoko status --db .kyoko/kyoko.db --json
kyoko dashboard-metrics --db .kyoko/kyoko.db --json
kyoko storage-report --db .kyoko/kyoko.db --json
kyoko wal-checkpoint --db .kyoko/kyoko.db --json
# prune and prune-retention default to a dry run; pass --apply to delete.
kyoko prune --db .kyoko/kyoko.db --json
kyoko prune-retention --db .kyoko/kyoko.db --trace-older-than-days 30 --json
```

## Development And Release

```bash
kyoko validate-gates
kyoko bundled-assets --json
kyoko dashboard-smoke --output-dir .kyoko/smoke/dashboard --json
kyoko release-smoke --artifact both --install-deps --json
```
