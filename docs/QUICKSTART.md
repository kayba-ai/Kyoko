# Quickstart

This guide shows the two first-run paths: a self-contained demo and a real local
project bootstrap.

## Run The Demo

The demo proves the complete repair loop without requiring a live model,
framework adapter, or replay server:

```bash
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko serve --db /tmp/kyoko-demo.db
```

Open:

```text
http://127.0.0.1:8765
```

The demo ingests bundled source events, creates an issue/proposal, generates a
check, runs mocked replay, verifies the improvement, and applies a context
skill through the gate.

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

This creates:

```text
.kyoko/kyoko.db
.kyoko/config/mcp.json
.kyoko/scripts/
.kyoko/NEXT_STEPS.md
```

Then run the local readiness smoke:

```bash
kyoko doctor --db .kyoko/kyoko.db --safe-smokes --json
```

Start the dashboard:

```bash
kyoko serve --db .kyoko/kyoko.db
```

## Bring In Telemetry

Use one of these paths:

- The Python SDK in `kyoko/sdk.py`.
- The TypeScript SDK in `sdk/typescript`.
- Generated source adapters from `kyoko source-adapter-template`.
- Local imports from Hermes or OpenClaw.
- OTLP/GenAI JSON through `kyoko ingest-otlp`.

Minimal Python SDK example:

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
        span.finish("succeeded", output_ref="output://search-results")
    run.finish("succeeded", summary="Collected search results.")

KyokoClient().ingest(recorder.to_source_events())
```

## Run The Repair Loop

Kyoko can start from a human-authored proposal, a registered operator adapter,
or a source candidate:

```bash
kyoko improve \
  --db .kyoko/kyoko.db \
  --operator codex \
  --replay-adapter my-agent_replay \
  --json
```

`improve` does not bypass safety. It still writes proposals first, generates
checks, runs replay, evaluates the gate, honors human locks, and applies only
what the autonomy policy allows.
