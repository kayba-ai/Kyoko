# Examples

Local hooks and adapter examples for wiring existing agent workflows into
Kyoko. Each file is intentionally small: copy the pattern, adapt it to your
framework, then smoke it before registering it.

## Source Hooks

Source hooks convert a real agent run into Kyoko source events.

| Example | What it demonstrates |
| --- | --- |
| [`source-hooks/generic-python`](../docs/INTEGRATIONS.md#generated-source-adapter) | Generate a generic Python adapter with `kyoko source-adapter-template`. |
| [`source-hooks/ai_sdk_source_hook.mjs`](source-hooks/ai_sdk_source_hook.mjs) | TypeScript AI SDK-style source hook. |
| [`source-hooks/langgraph_source_hook.py`](source-hooks/langgraph_source_hook.py) | LangGraph-style Python source hook. |
| [`source-hooks/pydantic_ai_source_hook.py`](source-hooks/pydantic_ai_source_hook.py) | Pydantic AI-style Python source hook. |
| [`source-hooks/openai_agents_source_hook.py`](source-hooks/openai_agents_source_hook.py) | OpenAI Agents-style Python source hook. |
| [`source-hooks/crewai_source_hook.py`](source-hooks/crewai_source_hook.py) | CrewAI-style Python source hook. |
| [`source-hooks/hermes_source_hook.py`](source-hooks/hermes_source_hook.py) | Hermes source hook. |
| [`source-hooks/openclaw_source_hook.py`](source-hooks/openclaw_source_hook.py) | OpenClaw source hook. |

Smoke a source adapter before using it:

```bash
kyoko integration-smoke source .kyoko/scripts/source_adapter.py \
  --hook examples/source-hooks/langgraph_source_hook.py:collect \
  --json
```

## Replay Hooks

Replay hooks let Kyoko run checks against controlled before/after
behavior.

| Example | What it demonstrates |
| --- | --- |
| [`replay-hooks/generic-python`](../docs/INTEGRATIONS.md#replay) | Generate a generic Python replay server with `kyoko replay-server-template`. |
| [`replay-hooks/ai_sdk_replay_hook.mjs`](replay-hooks/ai_sdk_replay_hook.mjs) | TypeScript AI SDK-style replay hook. |
| [`replay-hooks/langgraph_replay_hook.py`](replay-hooks/langgraph_replay_hook.py) | LangGraph-style Python replay hook. |
| [`replay-hooks/pydantic_ai_replay_hook.py`](replay-hooks/pydantic_ai_replay_hook.py) | Pydantic AI-style Python replay hook. |
| [`replay-hooks/openai_agents_replay_hook.py`](replay-hooks/openai_agents_replay_hook.py) | OpenAI Agents-style Python replay hook. |
| [`replay-hooks/crewai_replay_hook.py`](replay-hooks/crewai_replay_hook.py) | CrewAI-style Python replay hook. |
| [`replay-hooks/hermes_replay_hook.py`](replay-hooks/hermes_replay_hook.py) | Hermes replay hook. |
| [`replay-hooks/openclaw_replay_hook.py`](replay-hooks/openclaw_replay_hook.py) | OpenClaw replay hook. |

Smoke a replay server before registering it:

```bash
kyoko integration-smoke replay-server \
  --command "python3 .kyoko/scripts/replay_server.py --port 61200" \
  --server-url http://127.0.0.1:61200 \
  --hook examples/replay-hooks/langgraph_replay_hook.py:replay \
  --run-replay \
  --json
```

If `61200` is already in use, choose another local port and update both the
server command and `--server-url`.

## ACE Hook

[`ace-hooks/claude_skillbook_mutator.py`](ace-hooks/claude_skillbook_mutator.py)
shows an ACE-compatible skillbook mutation flow.

## Generate New Hooks

Use templates instead of starting from a blank file:

```bash
kyoko source-adapter-template .kyoko/scripts/source_adapter.py \
  --framework generic-python \
  --profile-name my-agent

kyoko replay-server-template .kyoko/scripts/replay_server.py \
  --framework generic-python \
  --profile-name my-agent \
  --json
```

Supported framework labels are listed in [docs/INTEGRATIONS.md](../docs/INTEGRATIONS.md).
