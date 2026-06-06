# Architecture

Kyoko is a local-first runtime for repairing AI agent workflows from evidence.
The core product loop is:

```text
telemetry -> issue -> proposal -> check -> replay -> gated apply
```

## Runtime Components

- `kyoko/cli.py`: argparse CLI and command dispatch.
- `kyoko/web.py`: loopback dashboard, JSON API, and Server-Sent Events stream.
- `kyoko/storage.py`: SQLite schema, migrations, and canonical event ingest.
- `kyoko/assets/`: bundled schemas, fixtures, demo data, and built dashboard.
- `frontend/`: React/Vite dashboard source.
- `sdk/typescript/` and `kyoko/sdk.py`: telemetry recorder/client SDKs.
- `examples/`: source and replay hook examples for real integrations.

## Data Model

Kyoko stores normalized local evidence:

- profiles, sources, runs, spans, handoffs, and timeline events,
- live events and MCP logs,
- issues and annotations,
- learning proposals,
- check specs, check runs, replay runs, and judge results,
- context skills, delivery rules, patch transactions, and human locks,
- payload blob metadata.

The default database is `~/.kyoko/kyoko.db`. Project bootstrap creates
`.kyoko/kyoko.db` inside the selected project. Large or sensitive payloads are
kept in the sibling blob store and served through redacted previews by default.

## Evidence And Repair

An issue is an evidence-backed statement about observed behavior. A proposal is
a proposed behavior change linked to evidence. A check is a deterministic or
judge-backed assertion Kyoko can run against replay output. A replay run is a
bounded attempt to reproduce the workflow under controlled side-effect modes.

Only the final apply step changes behavior. Context writes update Kyoko-managed
skills or delivery rules. Harness writes create reviewable patch transactions
against an explicit workspace root.

## Safety Boundary

Every behavior-changing path flows through the same gate:

1. Validate the proposal against the schema.
2. Resolve evidence references.
3. Generate or select checks.
4. Run replay and checks.
5. Evaluate the autonomy policy.
6. Enforce human locks.
7. Apply context or harness changes only if the gate allows it.

The dashboard, CLI, MCP tools, and `kyoko improve` use the same underlying
functions. There should be no direct apply shortcut outside this gate.

## Dashboard And API

`kyoko serve` starts a local HTTP server. By default it binds to
`127.0.0.1:8765`. The React dashboard is built into `kyoko/assets/web`; when the
bundle is missing, the server falls back to a small inline dashboard.

The API mirrors CLI workflows. Push updates use Server-Sent Events rather than
WebSockets.

## MCP

Kyoko exposes a stdio MCP server for coding agents:

```bash
kyoko mcp serve --db .kyoko/kyoko.db
```

MCP tools expose read, inspection, proposal, check, replay, and improve
workflows. They do not expose unchecked direct writes.
