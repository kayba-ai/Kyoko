# Kyoko

[![CI](https://github.com/kayba-ai/kyoko/actions/workflows/ci.yml/badge.svg)](https://github.com/kayba-ai/kyoko/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-green.svg)](LICENSE)

**Kyoko is the all-in-one, fully local tool for debugging and improving your AI
agents.**

Point it at **any agent you're building** — instrument it with OpenTelemetry or
the SDKs — or plug straight into CLI agents you already run like Codex, Claude
Code, OpenClaw, and Hermes. Kyoko captures what your agent actually does and
runs a closed repair loop over it: it **analyses** real runs into a living state
reflection of the system, files recurring and generalised failures as
**issues**, drafts concrete **fixes**, and proves them with replay and **evals**
before anything ships. Everything runs on your machine — traces, database, and
dashboard — and any model or external call is opt-in.

Most agent tooling stops at showing you traces; you still have to read them,
guess what went wrong, write the fix, and hope it didn't break something else.
Kyoko closes that gap end to end, in one place.

That state reflection is cumulative: Kyoko keeps learning from traces, issues,
fixes, replays, and evals, so it can surface the problems humans would not
think to measure by hand while still respecting the detectors and judges you
explicitly choose.

![Kyoko dashboard overview](docs/assets/kyoko-dashboard-overview.png)

## The loop

```text
        ┌─────────────────┐          ┌─────────────────┐
        │  ① Analyse      │ ───────▶ │  ② Issues       │
        │  traces in      │          │  recurring      │
        │                 │          │  failures       │
        └─────────────────┘          └─────────────────┘
                 ▲                             │
                 │ measure                     │ accept
                 │                             ▼
        ┌─────────────────┐  ┌──────┐  ┌─────────────────┐
        │  ④ Evals        │ ◀┤ gate ├─ │  ③ Proposals    │
        │  failure rate   │  └──────┘  │  candidate      │
        │                 │   apply    │  fixes          │
        └─────────────────┘            └─────────────────┘

   Gate = checks · replay · policy · locks; a fix applies only if it passes.
   Evals score the result and feed the next analysis — the loop tightens.
```

1. **Analyse** — Kyoko reads your agent's traces *for you*, diagnoses what went
   wrong, and updates a state reflection of how the system behaves over time.
   No manual log-digging.
2. **Issues** — it surfaces the failures to you automatically as first-class,
   evidence-backed issues, grouped by category and severity so you fix the
   pattern, not the symptom — including problems you did not predefine as a
   metric.
3. **Proposals** — each accepted issue becomes a concrete fix (to context/skills
   or the agent's harness), then runs the **gate**: generated checks, bounded
   replay, autonomy policy, and human locks. It applies only if it passes.
4. **Evals** — a measurement plane of deterministic detectors and LLM judges
   scores runs into a failure rate, before vs after. Failure is decided by
   evals, never by a status flag on a trace.

**Run it your way.** The same loop, the same gate — you pick the autonomy level:

- **Human-in-the-loop** — Kyoko surfaces issues and drafts fixes, and you review
  and approve each change before it applies.
- **Fully autonomous** — the policy auto-applies any change that clears replay,
  evals, and human locks, and parks anything that doesn't for you to look at.

Either way, nothing behavior-changing ships without passing the gate.

## Why Kyoko

- **OpenTelemetry-native.** Ingests OTLP/GenAI spans; SDKs and importers for the rest.
- **Plugs into CLI agents.** Codex, Claude Code, OpenClaw, Hermes — operators author fixes, MCP drives the loop.
- **Fully local.** SQLite + loopback UI. Nothing leaves your machine; external calls opt-in.
- **Cumulative analysis.** Builds a state reflection from traces, issues, evals, and fixes, so repeated behavior becomes more accurate fixes over time.
- **Measured, not guessed.** Failure rate from real evals — not status flags.
- **Safe by default.** No change ships without passing the gate. No shortcuts, anywhere.
- **Zero-fuss.** One `kyoko` CLI, near-zero deps, `--json` everywhere. No server, no cloud.

![Kyoko issues review queue](docs/assets/kyoko-dashboard-issues.png)

## Quick demo

Kyoko requires Python 3.12 or newer. From this checkout:

```bash
python3 -m pip install .
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko serve --db /tmp/kyoko-demo.db
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

The demo runs the full loop against bundled fixture data, so it needs no live
model, framework adapter, or replay server.

## Install

```bash
git clone https://github.com/kayba-ai/kyoko.git
cd kyoko
python3 -m pip install .
```

After the package is published, prefer an isolated CLI install:

```bash
pipx install kyoko
```

See [docs/INSTALL.md](docs/INSTALL.md) for `uv`, editable installs, the
installer script, upgrades, and common setup fixes.

## Use it in your project

Run this from the root of an agent project:

```bash
kyoko project-bootstrap \
  --project-dir . \
  --profile-name my-agent \
  --source-framework generic-python \
  --replay-framework generic-python \
  --mcp-target codex
```

`project-bootstrap` writes `.kyoko/kyoko.db`, source/replay scaffolds, MCP
config, operator presets, and `.kyoko/NEXT_STEPS.md`. Then check readiness and
start the dashboard:

```bash
kyoko doctor --db .kyoko/kyoko.db --safe-smokes --json
kyoko serve --db .kyoko/kyoko.db
```

Point telemetry at Kyoko with the Python or TypeScript SDK, a generated
adapter, or an importer — see [Getting Started](docs/GETTING_STARTED.md) for the
end-to-end walkthrough.

## What you get

- **Telemetry in:** Python SDK, TypeScript SDK, generated source adapters,
  OTLP/GenAI JSON, Hermes import, OpenClaw import.
- **Diagnosis:** per-trace and cumulative analysis that folds behavior into a
  state reflection, then turns recurring or generalised weaknesses into
  evidence-backed issues with category, severity, and the spans where they
  happened.
- **Fixes out:** issues become validated `LearningProposal` records — authored
  by you or an operator agent (Codex, Claude, or a generic command).
- **Verification:** generated checks plus bounded replay against external
  commands or managed loopback replay servers.
- **Measurement:** an evidence-only eval plane — deterministic detectors and
  LLM-judge evals — for what you choose to measure, alongside analysis that
  surfaces unmeasured patterns from observed behavior.
- **Surfaces:** a local dashboard, a JSON-everywhere CLI, and a stdio MCP server
  for coding agents — all sharing the same gated apply path.

| Area | Supported paths |
| --- | --- |
| Source telemetry | Python SDK, TypeScript SDK, generated source adapters, OTLP/GenAI JSON, Hermes import, OpenClaw import |
| Replay | External replay commands, managed HTTP replay servers, generated replay scaffolds |
| Operator agents | Codex, Claude, generic command adapters, local presets |
| Agent clients | Dashboard, JSON CLI, stdio MCP server |
| Framework scaffolds | Generic Python/TypeScript, LangGraph, Pydantic AI, OpenAI Agents, CrewAI, Hermes, OpenClaw, AI SDK |

See [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) and
[examples/README.md](examples/README.md).

## How safety works

Every behavior-changing path — operator output, imports, MCP tools, and
`kyoko improve` — flows through one gate:

1. Validate the proposal against its schema.
2. Resolve the evidence it references.
3. Generate or select checks.
4. Run bounded replay and the checks.
5. Evaluate the autonomy policy.
6. Enforce human locks on protected targets.
7. Apply context or harness changes **only** if the gate allows it.

Context writes update Kyoko-managed skills and delivery rules; harness writes
create reviewable patch transactions against an explicit workspace root.
Replay server URLs are loopback-only unless you pass `--allow-remote-server`,
and evidence exported to prompts, MCP, API, or bundles is redacted by default.
See [docs/SECURITY.md](docs/SECURITY.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

- [Getting Started](docs/GETTING_STARTED.md): demo, project bootstrap,
  telemetry, inspection, and the repair loop.
- [Install](docs/INSTALL.md): install paths, verification, data location, and
  common setup fixes.
- [Integrations](docs/INTEGRATIONS.md): source adapters, replay adapters,
  operator agents, MCP, and SDKs.
- [CLI Reference](docs/CLI.md): grouped command reference.
- [Architecture](docs/ARCHITECTURE.md): runtime model, data model, and the gate.
- [Security](docs/SECURITY.md): local data, loopback serving, tokens,
  redaction, and write boundaries.
- [Scope](docs/SCOPE.md): what v0 is and is not.
- [Development](docs/DEVELOPMENT.md): tests, dashboard bundle, release smoke,
  and contract artifacts.

Specs, schemas, fixtures, and design decisions live under `docs/` as reference
contracts.

## Repository layout

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

Kyoko is pre-1.0, single-user, local-first software. The published
distribution, primary CLI, Python import namespace, and project data directory
all use the `kyoko` name.

**Implemented:** local runtime, dashboard, demo, doctor checks, SDKs,
source/replay scaffolds, MCP server, operator adapters, checks, replay, evals,
and conservative autonomy gates.

**Outside v0:** hosted observability, team workspaces, cloud workers,
multi-tenant auth, billing, and unchecked autonomous repository writes.

## License

Apache-2.0. See [LICENSE](LICENSE).
