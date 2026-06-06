# Install

Kyoko installs as a Python CLI named `kyoko`.

## Requirements

- Python 3.12 or newer.
- `jsonschema` is the only required runtime dependency.
- Optional integrations are installed separately by the user: agent CLIs,
  framework runtimes, browser smoke tooling, OpenTelemetry, or ACE compatibility.

## Recommended Install

Use `pipx` for a global, isolated CLI:

```bash
pipx install kyoko
```

Upgrade and uninstall:

```bash
pipx upgrade kyoko
pipx uninstall kyoko
```

If you use `uv`:

```bash
uv tool install kyoko
uv tool upgrade kyoko
```

Plain `pip` also works, but it is less isolated:

```bash
python3 -m pip install --user kyoko
```

## Install From This Checkout

Until the package is published to PyPI, install from the repository root:

```bash
python3 -m pip install .
```

For editable development:

```bash
python3 -m pip install -e .
```

Then verify the command:

```bash
kyoko --version
kyoko doctor --json
```

## One-Line Installer

The repository includes `scripts/install.sh` for users who want a convenience
installer:

```bash
curl -fsSL https://raw.githubusercontent.com/kayba-ai/kyoko/main/scripts/install.sh | bash
```

The script:

- verifies that a Python executable is present,
- prefers `pipx`,
- falls back to `uv tool install`,
- then falls back to `python3 -m pip install --user`,
- installs the local checkout when run from inside the repository.

Overrides:

```bash
KYOKO_INSTALL_METHOD=pipx ./scripts/install.sh
KYOKO_INSTALL_SPEC=. ./scripts/install.sh
KYOKO_INSTALL_SPEC=kyoko==0.1.0 ./scripts/install.sh
```

As with any `curl | bash` installer, inspect the script first if you do not
already trust the source:

```bash
curl -fsSL https://raw.githubusercontent.com/kayba-ai/kyoko/main/scripts/install.sh -o install.sh
less install.sh
bash install.sh
```

## Data Location

The default database is:

```text
~/.kyoko/kyoko.db
```

Payload blobs live next to the selected database under `blobs/`. A project
bootstrap uses a project-local database at `.kyoko/kyoko.db`.

Kyoko does not start a background service during install. The dashboard/API only
runs when you start it:

```bash
kyoko serve
```
