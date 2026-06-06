# CLAUDE.md

This file gives coding agents the repo-specific context needed to work on
Kyoko without re-learning the project from scratch.

## Product Shape

Kyoko is a local repair loop for AI agent workflows:

```text
telemetry -> issue -> proposal -> check -> replay -> gated apply
```

It is a single-user, local-first tool. The shipped runtime is a Python CLI,
loopback dashboard/API, SQLite database, blob store, bundled dashboard assets,
MCP server, telemetry SDKs, source/replay scaffolds, and conservative autonomy
gate.

Read these first when the task touches product behavior:

- `README.md` for the public overview.
- `docs/SCOPE.md` for v0 boundaries and non-goals.
- `docs/ARCHITECTURE.md` for the runtime model and safety boundary.
- `docs/DEVELOPMENT.md` for tests, dashboard builds, and release smoke.
- `docs/specs/` and `docs/fixtures/` for contract-level behavior.

## Current Names

The current package, module, and CLI are still named `kyoko`. Do not rename the
package, command, import path, docs, or release metadata unless the user
explicitly asks for that change.

## Commands

```bash
# Local editable install
python3 -m pip install -e .

# Validate specs, schemas, fixtures, and bundled asset mirrors
python3 scripts/validate_gate_artifacts.py
python3 -m kyoko validate-gates

# Full Python test suite
python3 -m unittest discover -s tests

# First-run/safe local smoke
python3 -m kyoko doctor --safe-smokes --json

# Package install smoke
python3 -m kyoko release-smoke --artifact both --install-deps --json
```

There is no separate lint/format config. Match surrounding style.

## Frontend

The dashboard source lives in `frontend/`. Vite builds into `kyoko/assets/web/`
so the Python package can serve the dashboard after installation.

```bash
cd frontend
npm install
npm run build
```

For frontend development:

```bash
python3 -m kyoko serve --db /tmp/kyoko.db
cd frontend
npm run dev
```

The dev server proxies API requests to `kyoko serve`. Push updates use
Server-Sent Events, not WebSockets.

## Architecture Map

- `kyoko/cli.py`: argparse front door and command dispatch.
- `kyoko/web.py`: dashboard/API server and SSE stream.
- `kyoko/storage.py`: SQLite schema, migrations, and canonical ingest.
- `kyoko/sdk.py`: dependency-free Python recorder/client.
- `kyoko/project_bootstrap.py`: project-local `.kyoko/` bootstrap.
- `kyoko/demo.py`: bundled first-run demo.
- `kyoko/doctor.py`: readiness and safe smoke checks.
- `kyoko/analyze.py`, `kyoko/issues.py`, `kyoko/proposals.py`: diagnosis,
  first-class issues, and proposal creation.
- `kyoko/checks.py`, `kyoko/replay_adapters.py`, `kyoko/replay_servers.py`:
  check and replay gate.
- `kyoko/improve.py`, `kyoko/autonomy_runner.py`, `kyoko/apply.py`,
  `kyoko/harness.py`: improvement loop and gated writes.
- `kyoko/eval_detectors.py`, `kyoko/llm_evals.py`, `kyoko/evals_measure.py`:
  evidence-only measurement plane.
- `kyoko/mcp.py`: stdio MCP server and install-plan helpers.
- `kyoko/assets/**`: packaged schemas, fixtures, detectors, LLM eval templates,
  and built dashboard.

## Safety Invariants

Every behavior-changing path must flow through the proposal/check/replay gate.
Do not add shortcuts in CLI, API, dashboard, or MCP code.

Preserve these rules:

- Operator, ACE, import, and MCP outputs become validated proposals first.
- Context or harness writes happen only after gate evaluation.
- Human locks block later writes to the same protected target.
- Harness writes require an explicit workspace root and patch transaction.
- Replay server URLs are loopback-only unless `--allow-remote-server` is set.
- External model/provider/framework calls are opt-in and never part of the
  default safe smoke path.
- Evidence exported to prompts, MCP, API summaries, or bundles is redacted by
  default.

## Contract Artifacts

Many CLI commands have frozen `--json` contracts under
`docs/fixtures/cli-json/`. If output shape changes, update the relevant golden
and the matching spec in `docs/specs/0005-cli-json-contracts.md`.

Source/proposal/replay fixtures have authoring copies in `docs/fixtures/` and
runtime copies in `kyoko/assets/`. Keep mirrors synchronized and run:

```bash
python3 scripts/validate_gate_artifacts.py
```

Bundled detectors and LLM eval templates also mirror between `docs/` and
`kyoko/assets/`.

## Dependencies

The Python runtime currently keeps required dependencies minimal
(`jsonschema`). Optional integrations belong in extras or lazy imports. The
frontend is a normal Node/Vite/React project and may use frontend dependencies
when they earn their keep.

## Repo Hygiene

Do not commit local state, build caches, `__pycache__`, virtualenvs,
`node_modules`, or `.kyoko/` runtime data. Keep user-facing docs concise and
put stable contracts under `docs/specs`, `docs/schemas`, and `docs/fixtures`.
