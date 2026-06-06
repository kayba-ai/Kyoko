# Security

Kyoko is a local, single-user tool. It is not a hosted observability platform
and does not implement team auth, RBAC, tenant isolation, billing, or cloud
workers.

## Local Data

By default Kyoko stores data under:

```text
~/.kyoko/kyoko.db
~/.kyoko/blobs/
```

Project bootstrap stores data under:

```text
.kyoko/kyoko.db
.kyoko/blobs/
```

Nothing is sent to a hosted Kyoko service. External commands only run when the
user invokes an integration that shells out to a local CLI, framework runtime,
operator, judge, or replay server.

## Dashboard Binding

`kyoko serve` binds to `127.0.0.1:8765` by default:

```bash
kyoko serve --db .kyoko/kyoko.db
```

If you bind to a non-loopback host, Kyoko requires an auth token. You can pass
one explicitly:

```bash
kyoko serve --host 0.0.0.0 --auth-token "$KYOKO_AUTH_TOKEN"
```

The server accepts the token through a bearer header, `X-Kyoko-Token`, a
`token` query parameter, or the strict same-site cookie it sets after a valid
tokenized dashboard load.

## Redaction

Kyoko stores payloads locally so it can resolve evidence and replay behavior.
Surfaces that export or serve evidence should use redacted previews by default:

- CLI/API summaries,
- MCP tools,
- operator prompts,
- evidence bundles,
- dashboard payload views.

Large payloads belong in the blob store, not hot SQLite rows.

## Write Boundaries

Behavior-changing writes are gated. Operator output and ACE/native output become
validated proposals first; they do not directly mutate context, skills, or a
workspace.

Kyoko applies changes only after proposal validation, evidence resolution,
check/replay evidence, autonomy-policy evaluation, and human-lock enforcement.
Harness changes require an explicit workspace root and are represented as patch
transactions.

## Replay Boundaries

HTTP replay server URLs are loopback-only by default. Use
`--allow-remote-server` only when you have deliberately chosen a remote replay
endpoint and understand its side effects.

Replay modes and side-effect modes are recorded in adapter config and run
metadata so the trust boundary is visible in JSON output.

## MCP Boundary

The MCP server is a local stdio process. It exposes inspection, proposal,
check/replay, and improve workflows, but direct behavior-changing writes still
flow through Kyoko's gate.
