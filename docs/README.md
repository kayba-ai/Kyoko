# Kyoko Documentation

Kyoko is a local repair loop for AI agents: it analyses real runs, files
issues, drafts fixes, and proves them with replay and evals before anything
ships. Start with the product docs. Use the reference material only when you are
changing behavior or validating a release.

## Product Docs

| Guide | Purpose |
| --- | --- |
| [Getting Started](GETTING_STARTED.md) | Demo, project bootstrap, telemetry, inspection, and the repair loop. |
| [Install](INSTALL.md) | Install paths, verification, data location, and setup fixes. |
| [Integrations](INTEGRATIONS.md) | Source adapters, replay adapters, operator agents, MCP, and SDKs. |
| [CLI Reference](CLI.md) | Common command groups and JSON automation surface. |
| [Security](SECURITY.md) | Local data, loopback serving, tokens, redaction, replay, and write boundaries. |
| [Development](DEVELOPMENT.md) | Tests, dashboard bundle, release smoke, and contract artifacts. |

## Reference

| Reference | Purpose |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Runtime components, data model, and gate boundaries. |
| [Scope](SCOPE.md) | v0 product boundary and non-goals. |
| `specs/` | Design and command-contract specs. |
| `schemas/` | JSON Schemas used by validators and fixtures. |
| `fixtures/` | Golden CLI outputs, source events, replay results, proposals, and migration fixtures. |
| `decisions/` | Short decisions that explain product boundaries. |

When a CLI `--json` shape, schema, fixture, or gate behavior changes, update the
matching reference artifact and run:

```bash
python3 scripts/validate_gate_artifacts.py
python3 -m unittest discover -s tests
```
