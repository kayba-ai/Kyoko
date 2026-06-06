# Kyoko

Kyoko is a local repair loop for AI agent workflows. It turns agent traces into
diagnosed issues, proposed fixes, deterministic checks, replay evidence, and
policy-gated context or harness updates.

Kyoko is designed for one developer working on one local agent workflow. The
runtime is a Python CLI, a loopback-only dashboard/API, a SQLite database, a
content-addressed blob store, and optional local integrations for agent CLIs,
MCP clients, telemetry sources, and replay servers.

## What it does

Kyoko gives agent developers a repeatable path from "this run failed" to "this
fix is supported by evidence":

```text
telemetry -> issue -> proposal -> check -> replay -> gated apply
```

- Records or imports agent runs, spans, handoffs, live events, and payload
  previews.
- Surfaces first-class issues with resolved evidence.
- Accepts operator-agent or user-authored `LearningProposal` fixes.
- Generates check specs and runs bounded replay to prove before/after behavior.
- Applies context skills or harness patches only through explicit gates,
  autonomy policy, and human locks.
- Serves a local dashboard and MCP server for coding-agent workflows.

## Install

Kyoko requires Python 3.12 or newer. The recommended CLI install is isolated:

```bash
pipx install kyoko
```

Other supported install paths:

```bash
uv tool install kyoko
python3 -m pip install kyoko
python3 -m pip install .      # from a checkout
```

Until the package is published to PyPI, install from a local checkout:

```bash
python3 -m pip install .
```

See [docs/INSTALL.md](docs/INSTALL.md) for installer details, upgrades, and
source builds.

## Quick Start

Run the self-contained demo against a throwaway database:

```bash
kyoko demo --db /tmp/kyoko-demo.db --json
kyoko serve --db /tmp/kyoko-demo.db
```

Then open `http://127.0.0.1:8765`.

Bootstrap Kyoko inside a real local agent project:

```bash
kyoko project-bootstrap \
  --project-dir . \
  --profile-name my-agent \
  --source-framework generic-python \
  --replay-framework generic-python \
  --mcp-target codex

kyoko doctor --db .kyoko/kyoko.db --safe-smokes --json
kyoko serve --db .kyoko/kyoko.db
```

`project-bootstrap` creates `.kyoko/kyoko.db`, source/replay scaffolds, an MCP
config, operator adapter presets, and `.kyoko/NEXT_STEPS.md`.

## Documentation

- [Install](docs/INSTALL.md): package, source, and one-line installer paths.
- [Quickstart](docs/QUICKSTART.md): demo and project bootstrap flows.
- [Architecture](docs/ARCHITECTURE.md): runtime components and safety gates.
- [Integrations](docs/INTEGRATIONS.md): telemetry, replay, operators, MCP, and
  SDKs.
- [CLI Reference](docs/CLI.md): command groups and common workflows.
- [Security](docs/SECURITY.md): local-first data, loopback serving, redaction,
  and write boundaries.
- [Development](docs/DEVELOPMENT.md): tests, frontend builds, release smoke,
  and contract artifacts.
- [Scope](docs/SCOPE.md): what Kyoko v0 is and is not.

Reference contracts live under `docs/specs`, `docs/schemas`, and
`docs/fixtures`. They are part of the test and release surface, not marketing
docs.

## Repository Layout

```text
kyoko/              Python package, CLI, dashboard/API, bundled assets
frontend/           React/Vite dashboard source
sdk/typescript/     Dependency-free TypeScript telemetry SDK
examples/           Source and replay hook examples
scripts/            Installer, fixture replay helpers, artifact validation
tests/              Python unittest suite and CLI contract tests
docs/               User docs plus reference specs, schemas, and fixtures
```

## Local Development

```bash
python3 -m pip install -e .
python3 scripts/validate_gate_artifacts.py
python3 -m unittest discover -s tests
python3 -m kyoko doctor --safe-smokes --json
```

Build the dashboard bundle that ships inside the Python package:

```bash
cd frontend
npm install
npm run build
```

Run release packaging smoke:

```bash
python3 -m kyoko release-smoke --artifact both --install-deps --json
```

## Status

Kyoko is pre-1.0 software. The local runtime, dashboard, bundled demo, doctor
checks, source/replay scaffolds, MCP server, operator adapters, checks, replay,
and conservative autonomy gates are implemented. Hosted/team features, cloud
workers, multi-tenant auth, and provider-backed automation are outside v0 scope.

## License

Apache-2.0. See [LICENSE](LICENSE).
