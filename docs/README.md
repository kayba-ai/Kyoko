# Kyoko Documentation

Kyoko is a local repair loop for AI agent workflows. These docs are organized
for a release-ready repository: start with the short user guides, then drop into
reference contracts only when you are changing behavior.

## Start Here

- [Install](INSTALL.md): supported install paths and source builds.
- [Quickstart](QUICKSTART.md): run the demo, bootstrap a project, and open the
  dashboard.
- [Architecture](ARCHITECTURE.md): how telemetry, issues, proposals, checks,
  replay, and gated apply fit together.
- [Integrations](INTEGRATIONS.md): SDKs, source adapters, replay servers,
  operator agents, MCP, and framework scaffolds.
- [CLI Reference](CLI.md): command groups and common workflows.
- [Security](SECURITY.md): local data, dashboard binding, tokens, redaction, and
  write boundaries.
- [Development](DEVELOPMENT.md): tests, dashboard builds, release smoke, and
  contract artifacts.
- [Scope](SCOPE.md): v0 boundaries and non-goals.

## Reference Contracts

The following directories are not prose docs. They are part of the test and
release surface:

- `docs/specs/`: design and command-contract specs.
- `docs/schemas/`: JSON Schemas used by validators and fixtures.
- `docs/fixtures/`: golden CLI outputs, source events, replay results,
  proposals, and migration fixtures.

When a CLI `--json` shape, schema, fixture, or gate behavior changes, update the
matching reference artifact and run:

```bash
python3 scripts/validate_gate_artifacts.py
python3 -m unittest discover -s tests
```
