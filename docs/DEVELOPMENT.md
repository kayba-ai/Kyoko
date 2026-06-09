# Development

Python 3.12 is the baseline. CI also runs Python 3.13.

## Setup

```bash
python3 -m pip install -e .
python3 -m pip install setuptools wheel
kyoko --version
kyoko doctor --json
```

## Test Gates

Run the normal local gates:

```bash
python3 scripts/validate_gate_artifacts.py
python3 -m unittest discover -s tests
kyoko doctor --safe-smokes --json
```

Use a single test while working:

```bash
python3 -m unittest tests.test_cli
python3 -m unittest tests.test_web.WebTests.test_demo_endpoint_runs_first_run_loop
```

## Dashboard Bundle

The dashboard source lives in `frontend/`. The built bundle is committed under
`kyoko/assets/web/` so installed packages can serve the dashboard without a Node
toolchain.

Build:

```bash
cd frontend
npm install
npm run build
```

Develop against a running API:

```bash
kyoko serve --db /tmp/kyoko.db
cd frontend
npm run dev
```

The Vite dev server proxies API requests to `kyoko serve`.

## Contract Artifacts

Kyoko has contract tests for public JSON shapes and bundled assets:

- `docs/fixtures/cli-json/*.golden.json`
- `docs/schemas/*.json`
- `docs/specs/*.md`
- `docs/detectors/*.py`
- `docs/llm_evals/*.json`
- `kyoko/assets/**`

If you change CLI `--json` output, update the matching golden and any relevant
spec. If you change source/proposal/replay fixtures, keep the runtime bundled
copy in `kyoko/assets` synchronized with the docs copy.

Validate drift:

```bash
python3 scripts/validate_gate_artifacts.py
kyoko validate-gates
```

## Documentation

Keep GitHub-facing docs practical:

- Root `README.md`: product overview, demo, install, project bootstrap,
  integrations, and doc map.
- `docs/README.md`: docs navigation and reference index.
- `docs/GETTING_STARTED.md`: demo, project bootstrap, telemetry, inspection,
  and the repair loop.
- `docs/INSTALL.md`: install paths, verification, data location, and setup fixes.
- `docs/INTEGRATIONS.md`: source, replay, operator, MCP, and SDK wiring.
- `docs/CLI.md`: grouped command reference.
- `docs/SECURITY.md`: local data, auth, redaction, replay, and write boundaries.
- `docs/ARCHITECTURE.md`: runtime components, data model, and gate boundaries.
- `docs/SCOPE.md`: v0 product boundary and non-goals.

Keep long-lived behavior contracts under `docs/specs`, `docs/schemas`, and
`docs/fixtures`.

## Release Smoke

Run a package install smoke before publishing:

```bash
kyoko release-smoke --artifact both --install-deps --json
```

For dashboard packaging:

```bash
kyoko release-smoke --artifact wheel --dashboard-smoke --json
```

## Repo Hygiene

- Keep generated local state under `.kyoko/`, `build/`, `dist/`, or other
  ignored paths.
- Do not commit `__pycache__`, virtualenvs, test databases, or `node_modules`.
- Keep public docs concise and command-backed.
- Preserve the safety gate when adding CLI, API, dashboard, or MCP workflows.
