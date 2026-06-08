# Contributing to Kyoko

Thanks for your interest in Kyoko. It is an early, local-first project, so
contributions of any size are welcome: bug reports, doc fixes, and pull
requests.

## Before you start

- For anything beyond a small fix, open an issue first so we can agree on the
  approach before you write code.
- By contributing you agree your work is licensed under the project's
  [Apache-2.0 license](LICENSE).

## Development setup

Kyoko requires **Python 3.12 or newer**. From a checkout:

```bash
python3 -m pip install -e .
kyoko --version
kyoko doctor --json
```

The full development workflow (dashboard build, release smoke, contract
artifacts) lives in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Before you open a pull request

Run the local gates and make sure they pass:

```bash
python3 scripts/validate_gate_artifacts.py     # schemas, fixtures, asset mirrors
python3 -m unittest discover -s tests          # Python test suite
kyoko doctor --safe-smokes --json              # safe local smoke
```

If you change the dashboard under `frontend/`, rebuild the committed bundle so
installed packages keep serving the latest UI:

```bash
cd frontend
npm install
npm run build
```

If you change a CLI `--json` shape, a schema, or a fixture, update the matching
reference artifact under `docs/` and re-run `validate_gate_artifacts.py`. Keep
the `docs/` authoring copies and the `kyoko/assets/` runtime copies in sync.

## Pull request expectations

- Branch off `main` and keep each PR focused on one change.
- Match the surrounding code and docs style; there is no separate lint/format
  config.
- Preserve the safety gate: every behavior-changing path must flow through the
  proposal / check / replay / policy / locks gate. Do not add apply shortcuts in
  CLI, API, dashboard, or MCP code.
- Update the relevant docs when behavior changes.

## Reporting bugs

Open a [bug report](https://github.com/kayba-ai/kyoko/issues/new) and include
your Kyoko version, Python version, OS, and `kyoko doctor --json` output.

## Reporting security issues

Do **not** open a public issue for vulnerabilities. Follow
[SECURITY.md](SECURITY.md) instead.
