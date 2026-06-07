# Architecture

Kyoko is a local-first self-improvement loop for AI agent workflows. It
is built around one product invariant: behavior changes must be backed by an
issue, a proposal, check/replay evidence, policy evaluation, and human-lock
enforcement.

```text
source telemetry
  -> normalized runs and spans
  -> issues and evidence
  -> LearningProposal
  -> generated checks
  -> bounded replay
  -> gated context or harness apply
```

## Runtime Map

| Component | Role |
| --- | --- |
| `kyoko/cli.py` | Argparse CLI, command dispatch, and JSON automation surface. |
| `kyoko/web.py` | Loopback dashboard, JSON API, and Server-Sent Events stream. |
| `kyoko/storage.py` | SQLite schema, migrations, canonical ingest, and status reporting. |
| `kyoko/assets/` | Bundled schemas, fixtures, demo data, detectors, evals, and dashboard bundle. |
| `frontend/` | React/Vite dashboard source committed into `kyoko/assets/web` after build. |
| `kyoko/sdk.py` | Python telemetry recorder and local HTTP client. |
| `sdk/typescript/` | Dependency-free TypeScript telemetry SDK. |
| `examples/` | Source and replay hook examples for real integrations. |

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
`.kyoko/kyoko.db` inside the selected project. Payload blobs live next to the
selected database under `blobs/`.

## Evidence And Repair

An issue is an evidence-backed statement about observed behavior. A proposal is
a proposed behavior change linked to that evidence. A check is a deterministic
or judge-backed assertion Kyoko can run against replay output. A replay
run is a bounded attempt to reproduce the workflow under an explicit side-effect
mode.

Only the final apply step changes behavior:

- Context writes update Kyoko-managed skills or delivery rules.
- Harness writes create reviewable patch transactions against an explicit
  workspace root.
- Operator output and native tool output become proposals first.

## Gate Boundary

Every behavior-changing path flows through the same gate:

1. Validate the proposal against the schema.
2. Resolve evidence references.
3. Generate or select checks.
4. Run replay and checks.
5. Evaluate the autonomy policy.
6. Enforce human locks.
7. Apply context or harness changes only if the gate allows it.

The dashboard, CLI, MCP tools, and `kyoko improve` use the same
underlying functions. There should be no direct apply shortcut outside this
gate.

## Dashboard And API

`kyoko serve` starts a local HTTP server. By default it binds to
`127.0.0.1:8765`. If the React bundle is present, the server serves the built
dashboard from `kyoko/assets/web`; otherwise it falls back to a small inline
dashboard.

The API mirrors CLI workflows. Live updates use Server-Sent Events rather than
WebSockets.

## MCP

Kyoko exposes a stdio MCP server for coding agents:

```bash
kyoko mcp serve --db .kyoko/kyoko.db
```

MCP tools expose read, inspection, proposal, check/replay, and improve
workflows. They do not expose unchecked direct writes.

## Release Surface

The release surface includes more than Python modules:

- `README.md` and the top-level docs,
- `docs/specs`, `docs/schemas`, and `docs/fixtures`,
- bundled JSON and Python assets under `kyoko/assets`,
- the built dashboard under `kyoko/assets/web`,
- CLI `--json` contracts validated by golden fixtures.

Run `python3 scripts/validate_gate_artifacts.py` when any contract artifact or
bundled asset changes.
