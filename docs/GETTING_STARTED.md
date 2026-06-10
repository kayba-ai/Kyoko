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
kyoko project-bootstrap
```

Bootstrap creates:

```text
.kyoko/kyoko.db
.kyoko/config/mcp.json
.kyoko/scripts/
.kyoko/NEXT_STEPS.md
```

Every `kyoko` command run inside the project finds `.kyoko/kyoko.db`
automatically, so the commands below need no `--db` flag. Bootstrap defaults
can be tuned with `--profile-name`, `--source-framework`, `--replay-framework`,
and `--mcp-target` (see `kyoko project-bootstrap --help`).

Then start the dashboard:

```bash
kyoko serve
```

`kyoko doctor --safe-smokes --json` checks environment readiness against a
temporary database; pass `--db .kyoko/kyoko.db` to check the project one.

## Add Telemetry

### Easiest: delegate the setup to your coding agent

Install the bundled instrumentation skill:

```bash
kyoko install-skill   # then run /kyoko-instrument in your coding agent
```

The skill lands in `.claude/skills/` and `.agents/skills/`, where Claude Code
and Codex pick it up automatically; `kyoko install-skill --print` prints the
same playbook to paste into Cursor or other agents. It finds your agent's
entry point, records one real run, and verifies it shows up in Kyoko.

Alternatively, connect Kyoko as an MCP server for your coding agent:

```bash
kyoko mcp install-plan --target codex --json
```

Use `--target claude` for Claude Code. Run the printed `shell_command`, then
paste this task into the agent:

```text
Use Kyoko to finish setup. Read .kyoko/NEXT_STEPS.md, wire the smallest
telemetry hook or import existing traces, record one run, and verify it with
`kyoko runs --json`. Do not add secrets or run live operator/model actions
unless I ask.
```

The agent can use Kyoko MCP tools when available, and can always fall back to
the generated `.kyoko/NEXT_STEPS.md` commands. For other MCP clients, write a
generic config and point the client at it:

```bash
kyoko mcp install --target generic --output .kyoko/config/mcp.json --json
```

### By hand: the Python SDK

Record a run and write it to a file. This needs **no running server** — ingest
writes straight to the database. Reuse the profile bootstrap created (default
`profile_kyoko_agent`; see `.kyoko/NEXT_STEPS.md`) so the run shows up in
`kyoko runs` and the dashboard without extra flags:

```python
from kyoko import KyokoRecorder

recorder = KyokoRecorder(
    profile_id="profile_kyoko_agent",
    profile_name="kyoko-agent",
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
kyoko ingest kyoko-run.json --json
```

To push runs to a live dashboard instead, start `kyoko serve` and call
`KyokoClient().ingest(recorder.to_source_events())`. The client is
best-effort: if the server is not running it warns and drops the telemetry
rather than raising into your agent (pass `strict=True` to raise). Either way,
ingest and `kyoko serve` must use the **same database**; inside a bootstrapped
project both default to `.kyoko/kyoko.db`.

Other source paths are covered in [Integrations](INTEGRATIONS.md): TypeScript
SDK, generated source adapters, OTLP/GenAI JSON, Hermes, and OpenClaw.

## Inspect A Run

```bash
kyoko runs --json
kyoko current-run --json
kyoko run-outline <run-id> --json
kyoko search-run <run-id> "timeout" --json
kyoko span-payload <span-id> --target output --json
```

## Move From Issue To Repair

Issues are evidence records; creating one does not change agent behavior:

```bash
kyoko issues --json
kyoko issue-detail <issue-id> --json
kyoko issue-create "Search timeout" \
  --body "Search span timed out; inspect span:<span-id>." \
  --json
```

Proposals are candidate behavior changes:

```bash
kyoko accept-issue <issue-id> --operator mock --json
kyoko proposals --json
kyoko proposal-detail <proposal-id> --json
```

Checks and replay provide evidence before apply:

```bash
kyoko generate-checks <proposal-id> --json
kyoko replay <check-spec-id> --json
kyoko run-autonomy --json
```

`run-autonomy` evaluates the proposal, check/replay results, policy, and human
locks. It only applies changes the gate allows.

## Run The Full Loop

After registering an operator and replay adapter:

```bash
kyoko improve \
  --operator codex \
  --replay-adapter my-agent_replay \
  --json
```

`improve` is orchestration, not a shortcut. It still creates proposals,
generates checks, runs replay, evaluates policy, and honors human locks.

## Connect A Coding Agent

Generate an MCP install plan:

```bash
kyoko mcp install-plan --target codex --json
```

Run the local MCP server:

```bash
kyoko mcp serve
```

MCP tools expose inspection, proposal, check/replay, and improve workflows.
They do not expose unchecked direct writes.
