# Integrations

Kyoko is useful when it can observe a workflow, replay it safely, and
hand evidence to a local developer or operator agent. Integrations are local
SDK calls, generated scaffolds, imports, or commands. Kyoko does not
require a hosted service.

## Compatibility

| Area | Supported paths |
| --- | --- |
| Source telemetry | Python SDK, TypeScript SDK, generated source adapters, OTLP/GenAI JSON, Hermes import, OpenClaw import |
| Replay | External replay commands, managed HTTP replay servers, generated replay scaffolds |
| Operator agents | Codex, Claude, generic command adapters, local presets |
| Agent clients | Dashboard, JSON CLI, stdio MCP server |
| Framework scaffolds | `generic-python`, `generic-typescript`, `langgraph-python`, `pydantic-ai-python`, `openai-agents-python`, `crewai-python`, `hermes-python`, `openclaw-python`, `ai-sdk-typescript` |

Example hooks live in [../examples](../examples).

## Source Telemetry

For trace files supplied by a user or external observability tool, prefer OTLP or
GenAI trace exports:

```bash
kyoko ingest-otlp --db .kyoko/kyoko.db otlp.json --profile-id my-agent --json
```

Kyoko normalizes those uploads into its canonical source-event envelope before
storing them. Source-event JSON is an adapter/SDK output format, not the format
end users are expected to already have.

### Python SDK

```python
from kyoko import KyokoClient, KyokoRecorder

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

KyokoClient().ingest(recorder.to_source_events())
```

### TypeScript SDK

The dependency-free TypeScript SDK is under [../sdk/typescript](../sdk/typescript).
It uses the same source-event format as the Python SDK and defaults to
`http://127.0.0.1:8765`.

### Generated Source Adapter

```bash
kyoko source-adapter-template .kyoko/scripts/source_adapter.py \
  --framework generic-python \
  --profile-name my-agent \
  --json
```

Smoke it before relying on it:

```bash
kyoko integration-smoke source .kyoko/scripts/source_adapter.py \
  --hook path/to/source_hook.py:collect \
  --json
```

If the smoke reports `source_hook_required`, the generated adapter is present
but no collector hook has been wired in yet.

### OTLP, Hermes, And OpenClaw

```bash
kyoko discover-sources --db .kyoko/kyoko.db --root-path . --json
kyoko import-hermes-kanban --db .kyoko/kyoko.db ~/.hermes/kanban.db --board default --json
kyoko import-openclaw-sessions --db .kyoko/kyoko.db ~/.openclaw/agents/main/sessions --agent-id main --json
```

## Replay

Generate a replay server scaffold:

```bash
kyoko replay-server-template .kyoko/scripts/replay_server.py \
  --framework generic-python \
  --profile-name my-agent \
  --json
```

Smoke it:

```bash
kyoko integration-smoke replay-server \
  --command "python3 .kyoko/scripts/replay_server.py --port 61200" \
  --server-url http://127.0.0.1:61200 \
  --hook path/to/replay_hook.py:replay \
  --run-replay \
  --json
```

Register it:

```bash
kyoko replay-adapter-register --db .kyoko/kyoko.db my-agent_replay \
  --name "My Agent replay" \
  --command "python3 .kyoko/scripts/replay_server.py --port 61200" \
  --server-url http://127.0.0.1:61200 \
  --mode dry_run \
  --side-effect-mode network_mocked \
  --json
```

If `61200` is busy, choose another local port and update both the server
command and `--server-url`. HTTP replay server URLs are loopback-only unless
`--allow-remote-server` is supplied.

## Operator Agents

Operator agents author proposals from evidence. Register safe local presets
when the matching CLIs are installed:

```bash
kyoko operator-adapter-bootstrap --db .kyoko/kyoko.db --json
kyoko operator-adapters --db .kyoko/kyoko.db --json
```

Run a prepare-only smoke before invoking a live operator:

```bash
kyoko operator-smoke --db .kyoko/kyoko.db --prepare-only --all-presets --json
```

Operator output becomes a validated proposal. It does not directly mutate
context, skills, checks, or workspace files.

## MCP

Generate an install plan:

```bash
kyoko mcp install-plan --db .kyoko/kyoko.db --target codex --json
```

Run the server:

```bash
kyoko mcp serve --db .kyoko/kyoko.db
```

MCP tools expose inspection, proposal, check/replay, and improve workflows.
They do not expose unchecked direct writes.
