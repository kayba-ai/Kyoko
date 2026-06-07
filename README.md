# Kyoko

[![CI](https://github.com/kayba-ai/kyoko/actions/workflows/ci.yml/badge.svg)](https://github.com/kayba-ai/kyoko/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

## A Self-Improvement Loop For AI Agents

Kyoko turns a failed agent run into an evidence-backed issue, a proposed
fix, replay/check evidence, and a gated apply decision.

![Kyoko dashboard overview](docs/assets/kyoko-dashboard-overview.png)

```text
trace -> issue -> proposal -> check -> replay -> gated apply
```

Kyoko is local-first: SQLite database, local blob store, loopback
dashboard/API, JSON CLI, optional MCP server, and opt-in integrations for
source telemetry, operator agents, and replay.

## Quick Demo

Kyoko requires Python 3.12 or newer. From this checkout:

```bash
python3 -m pip install .
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko serve --db /tmp/kyoko-demo.db
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

The demo uses bundled fixture data, so it does not require a live model,
framework adapter, or replay server.

## Install

Current source install:

```bash
git clone https://github.com/kayba-ai/kyoko.git
cd kyoko
python3 -m pip install .
```

After the package is published, use an isolated CLI install:

```bash
pipx install kyoko
```

See [docs/INSTALL.md](docs/INSTALL.md) for `uv`, editable installs, the
installer script, upgrades, and common setup fixes.

## Use It In A Project

Run this from the root of an agent project:

```bash
kyoko project-bootstrap \
  --project-dir . \
  --profile-name my-agent \
  --source-framework generic-python \
  --replay-framework generic-python \
  --mcp-target codex
```

Then check readiness and start the dashboard:

```bash
kyoko doctor --db .kyoko/kyoko.db --safe-smokes --json
kyoko serve --db .kyoko/kyoko.db
```

`project-bootstrap` writes `.kyoko/kyoko.db`, source/replay scaffolds, MCP
config, operator presets, and `.kyoko/NEXT_STEPS.md`.

## What Kyoko Does

- Records or imports local agent traces from SDKs, generated adapters, OTLP,
  Hermes, or OpenClaw.
- Turns observed behavior into first-class issues with local evidence.
- Converts user or operator fixes into validated `LearningProposal` records.
- Generates checks and runs bounded replay before applying changes.
- Applies context or harness changes only through policy gates and human locks.
- Exposes the loop through a dashboard, JSON CLI, and local MCP server.

## Integrations

| Area | Supported paths |
| --- | --- |
| Source telemetry | Python SDK, TypeScript SDK, generated source adapters, OTLP/GenAI JSON, Hermes import, OpenClaw import |
| Replay | External replay commands, managed HTTP replay servers, generated replay scaffolds |
| Operator agents | Codex, Claude, generic command adapters, local presets |
| Agent clients | Dashboard, JSON CLI, stdio MCP server |
| Framework scaffolds | Generic Python/TypeScript, LangGraph, Pydantic AI, OpenAI Agents, CrewAI, Hermes, OpenClaw, AI SDK |

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) and
[examples/README.md](examples/README.md).

## Documentation

- [Getting Started](docs/GETTING_STARTED.md): demo, project bootstrap,
  telemetry, inspection, and the repair loop.
- [Install](docs/INSTALL.md): install paths, verification, data location, and
  common setup fixes.
- [Integrations](docs/INTEGRATIONS.md): source adapters, replay adapters,
  operator agents, MCP, and SDKs.
- [CLI Reference](docs/CLI.md): grouped command reference.
- [Security](docs/SECURITY.md): local data, loopback serving, tokens,
  redaction, and write boundaries.
- [Development](docs/DEVELOPMENT.md): tests, dashboard bundle, release smoke,
  and contract artifacts.

Specs, schemas, fixtures, and design decisions live under `docs/` as reference
contracts.

## Repository Layout

```text
kyoko/              Python import package, CLI runtime, dashboard/API, bundled assets
frontend/           React/Vite dashboard source
sdk/typescript/     Dependency-free TypeScript telemetry SDK
examples/           Source and replay hook examples
scripts/            Installer, release smoke, fixture and artifact helpers
tests/              Python unittest suite and CLI contract tests
docs/               User docs plus specs, schemas, fixtures, and decisions
```

## Status

Kyoko is pre-1.0 software. The published distribution, primary CLI, Python
import namespace, and project data directory all use the `kyoko` name.

Implemented: local runtime, dashboard, demo, doctor checks, SDKs,
source/replay scaffolds, MCP server, operator adapters, checks, replay, and
conservative autonomy gates.

Outside v0: hosted observability, team workspaces, cloud workers, multi-tenant
auth, billing, and unchecked autonomous repository writes.

## License

Apache-2.0. See [LICENSE](LICENSE).
