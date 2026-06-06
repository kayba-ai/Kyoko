# Integrations

Kyoko is useful when it can observe a workflow, replay it safely, and hand the
evidence to a local operator or developer. Integrations are local commands,
SDKs, or generated scaffolds; Kyoko does not require a hosted service.

## Telemetry Sources

Supported source paths:

- Python SDK: `kyoko/sdk.py`.
- TypeScript SDK: `sdk/typescript`.
- Generated source adapters:

  ```bash
  kyoko source-adapter-template .kyoko/scripts/source_adapter.py \
    --framework generic-python \
    --profile-name my-agent
  ```

- OTLP/GenAI JSON:

  ```bash
  kyoko ingest-otlp --db .kyoko/kyoko.db otlp.json --json
  ```

- Local Hermes and OpenClaw imports:

  ```bash
  kyoko discover-sources --db .kyoko/kyoko.db --root-path . --json
  kyoko import-hermes-kanban --db .kyoko/kyoko.db ~/.hermes/kanban.db --board default --json
  kyoko import-openclaw-sessions --db .kyoko/kyoko.db ~/.openclaw/agents/main/sessions --agent-id main --json
  ```

Framework scaffold labels include `generic-python`, `generic-typescript`,
`langgraph-python`, `pydantic-ai-python`, `openai-agents-python`,
`crewai-python`, `hermes-python`, `openclaw-python`, and `ai-sdk-typescript`.

## Replay

Replay adapters run a check against controlled before/after behavior. Kyoko
supports external replay commands and HTTP replay servers.

Generate a replay server scaffold:

```bash
kyoko replay-server-template .kyoko/scripts/replay_server.py \
  --framework generic-python \
  --profile-name my-agent \
  --json
```

Smoke it before registering it:

```bash
kyoko integration-smoke replay-server \
  --command "python3 .kyoko/scripts/replay_server.py --port 61200" \
  --server-url http://127.0.0.1:61200 \
  --run-replay \
  --json
```

Register a managed replay server:

```bash
kyoko replay-adapter-register --db .kyoko/kyoko.db my-agent_replay \
  --name "My Agent replay" \
  --command "python3 .kyoko/scripts/replay_server.py --port 61200" \
  --server-url http://127.0.0.1:61200 \
  --mode dry_run \
  --side-effect-mode network_mocked \
  --json
```

Replay server URLs are loopback-only unless `--allow-remote-server` is supplied.

## Operator Agents

Operator agents author proposals from evidence. Kyoko can register common local
CLI presets when they are installed:

```bash
kyoko operator-adapter-bootstrap --db .kyoko/kyoko.db --json
kyoko operator-adapters --db .kyoko/kyoko.db --json
```

Run a prepare-only smoke before invoking a live operator:

```bash
kyoko operator-smoke --db .kyoko/kyoko.db --prepare-only --all-presets --json
```

## MCP Clients

Generate or install MCP config for local clients:

```bash
kyoko mcp config --db .kyoko/kyoko.db --target codex --json
kyoko mcp install-plan --db .kyoko/kyoko.db --target codex --json
kyoko mcp install --db .kyoko/kyoko.db --target generic --output .kyoko/config/mcp.json --json
```

For verified clients, isolated install smokes are available:

```bash
kyoko mcp install-smoke --db .kyoko/kyoko.db --all-targets --json
```

## SDKs

The Python SDK ships with the package:

```python
from kyoko import KyokoClient, KyokoRecorder
```

The TypeScript SDK is under `sdk/typescript`. It is dependency-free at runtime
and uses the same source-event format as the Python SDK.
