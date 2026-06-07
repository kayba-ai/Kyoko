# Install

Kyoko installs as a Python CLI named `kyoko`. It requires Python
3.12 or newer.

## From This Repository

Current GitHub-user install:

```bash
git clone https://github.com/kayba-ai/kyoko.git
cd kyoko
python3 -m pip install .
kyoko --version
```

Editable development install:

```bash
python3 -m pip install -e .
```

Verify:

```bash
kyoko doctor --json
kyoko demo --db /tmp/kyoko-demo.db --json
```

## Published Package

After the package is published, use an isolated CLI installer:

```bash
pipx install kyoko
```

Upgrade or uninstall:

```bash
pipx upgrade kyoko
pipx uninstall kyoko
```

Other supported published-package paths:

```bash
uv tool install kyoko
python3 -m pip install --user kyoko
```

## Installer Script

From a checkout:

```bash
./scripts/install.sh
```

After publishing, the same installer can be fetched remotely:

```bash
curl -fsSL https://raw.githubusercontent.com/kayba-ai/kyoko/main/scripts/install.sh | bash
```

The script checks Python, prefers `pipx`, falls back to `uv`, then falls back
to `python3 -m pip install --user`. It installs the working tree when run from
inside the repository.

As with any `curl | bash` installer, inspect it first if you do not already
trust the source:

```bash
curl -fsSL https://raw.githubusercontent.com/kayba-ai/kyoko/main/scripts/install.sh -o install.sh
less install.sh
bash install.sh
```

## Data Location

Default data:

```text
~/.kyoko/kyoko.db
~/.kyoko/blobs/
```

Project bootstrap data:

```text
.kyoko/kyoko.db
.kyoko/blobs/
```

Kyoko does not start a background service during install. The
dashboard/API runs only when you start it:

```bash
kyoko serve
```

## Common Setup Fixes

`kyoko` not found after install:

```bash
pipx ensurepath
uv tool update-shell
python3 -m site --user-base
```

Python too old:

```bash
python3.12 -m pip install .
python3.12 -m kyoko doctor --json
```

Dashboard port busy:

```bash
kyoko serve --db .kyoko/kyoko.db --port 8766
```

Non-loopback dashboard bind:

```bash
kyoko serve --host 0.0.0.0 --auth-token "$KYOKO_AUTH_TOKEN"
```
