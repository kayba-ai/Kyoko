# Getting Started

This guide takes you from the bundled demo to the first useful commands in a
real agent project.

## Run The Demo

```bash
pipx install kyoko
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko serve --db /tmp/kyoko-demo.db
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

The demo runs the full loop against bundled fixture data:

```text
trace -> issue -> proposal -> check -> replay -> gated apply
```

It does not require a live model, framework adapter, or replay server.

## Bootstrap A Project

Run this from the root of an agent project:

```bash
kyoko project-bootstrap \
  --project-dir . \
  --profile-name my-agent \
  --source-framework generic-python \
  --replay-framework generic-python \
  --mcp-target codex
```

Bootstrap creates:

```text
.kyoko/kyoko.db
.kyoko/config/mcp.json
.kyoko/scripts/
.kyoko/NEXT_STEPS.md
```

Then run:

```bash
kyoko doctor --db .kyoko/kyoko.db --safe-smokes --json
kyoko serve --db .kyoko/kyoko.db
```

## Add Telemetry

### Easiest: delegate the setup to your coding agent

Connect Kyoko as an MCP server for the coding agent you are using:

```bash
kyoko mcp install-plan --db .kyoko/kyoko.db --target codex --json
kyoko mcp install-plan --db .kyoko/kyoko.db --target claude --json
```

Run the `shell_command` printed by the matching plan. For another MCP client,
write the generic config and point that client at it:

```bash
kyoko mcp install --db .kyoko/kyoko.db --target generic --output .kyoko/config/mcp.json --json
```

Then paste this task into the agent:

```text
Use Kyoko to finish setup for this project. Read .kyoko/NEXT_STEPS.md, inspect
the agent entry point and framework, and keep changes scoped. First run
`kyoko doctor --db .kyoko/kyoko.db --json`. Then discover or import existing
trace data if available. If no useful traces exist, add the smallest telemetry
hook using the Python SDK, TypeScript SDK, generated source adapter, OTLP export,
or an existing framework callback. Record one real or smoke run, ingest it into
.kyoko/kyoko.db, and verify it with `kyoko runs --db .kyoko/kyoko.db --json`.
Do not add secrets or run live operator/model actions unless I ask.
```

The agent can use Kyoko MCP tools when available, and can always fall back to
the generated `.kyoko/NEXT_STEPS.md` commands. This makes the flow portable
across Codex, Claude Code, Cursor, generic MCP clients, and agents that can only
run shell commands.

### By hand: the Python SDK

Record a run and write it to a file. This needs **no running server** — ingest
writes straight to the database:

```python
from kyoko import KyokoRecorder

recorder = KyokoRecorder(
    profile_id="my-agent",
    profile_name="My Agent",
    root_path=".",
    agent_name="researcher",
)

with recorder.run("research task") as run:
    with run.span("search", kind="tool") as span:
        span.finish(status="succeeded", output_ref="output://search-results")
    run.finish(status="succeeded", summary="Collected search results.")

recorder.write_json("kyoko-run.json")
```

```bash
kyoko ingest --db .kyoko/kyoko.db kyoko-run.json --json
```

To push runs to a live dashboard instead, start `kyoko serve --db
.kyoko/kyoko.db` and call `KyokoClient().ingest(recorder.to_source_events())`.
The client is best-effort: if the server is not running it warns and drops the
telemetry rather than raising into your agent (pass `strict=True` to raise).
Either way, ingest and `kyoko serve` must use the **same `--db` path** for runs
to appear.

Other source paths are covered in [Integrations](INTEGRATIONS.md): TypeScript
SDK, generated source adapters, OTLP/GenAI JSON, Hermes, and OpenClaw.

## Inspect A Run

```bash
kyoko runs --db .kyoko/kyoko.db --json
kyoko current-run --db .kyoko/kyoko.db --json
kyoko run-outline --db .kyoko/kyoko.db <run-id> --json
kyoko search-run --db .kyoko/kyoko.db <run-id> "timeout" --json
kyoko span-payload --db .kyoko/kyoko.db <span-id> --target output --json
```

## Move From Issue To Repair

Issues are evidence records; creating one does not change agent behavior:

```bash
kyoko issues --db .kyoko/kyoko.db --json
kyoko issue-detail --db .kyoko/kyoko.db <issue-id> --json
kyoko issue-create --db .kyoko/kyoko.db "Search timeout" \
  --body "Search span timed out; inspect span:<span-id>." \
  --json
```

Proposals are candidate behavior changes:

```bash
kyoko accept-issue --db .kyoko/kyoko.db <issue-id> --operator mock --json
kyoko proposals --db .kyoko/kyoko.db --json
kyoko proposal-detail --db .kyoko/kyoko.db <proposal-id> --json
```

Checks and replay provide evidence before apply:

```bash
kyoko generate-checks --db .kyoko/kyoko.db <proposal-id> --json
kyoko replay --db .kyoko/kyoko.db <check-spec-id> --json
kyoko run-autonomy --db .kyoko/kyoko.db --json
```

`run-autonomy` evaluates the proposal, check/replay results, policy, and human
locks. It only applies changes the gate allows.

## Run The Full Loop

After registering an operator and replay adapter:

```bash
kyoko improve \
  --db .kyoko/kyoko.db \
  --operator codex \
  --replay-adapter my-agent_replay \
  --json
```

`improve` is orchestration, not a shortcut. It still creates proposals,
generates checks, runs replay, evaluates policy, and honors human locks.

## Connect A Coding Agent

Generate an MCP install plan:

```bash
kyoko mcp install-plan --db .kyoko/kyoko.db --target codex --json
```

Run the local MCP server:

```bash
kyoko mcp serve --db .kyoko/kyoko.db
```

MCP tools expose inspection, proposal, check/replay, and improve workflows.
They do not expose unchecked direct writes.
