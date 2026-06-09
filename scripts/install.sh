#!/usr/bin/env bash
#
# Kyoko local installer.
#
# Kyoko is a local, single-user, single-machine tool. This script
# installs the `kyoko` console command (entry point: kyoko.cli:main) on
# your machine. It does NOT start any service, open any port, or phone home;
# after install you run `kyoko serve` yourself.
#
# Usage:
#   # From a published release (once Kyoko is on PyPI):
#   curl -fsSL https://raw.githubusercontent.com/kayba-ai/kyoko/main/scripts/install.sh | bash
#
#   # From a local checkout of this repo (installs the working tree):
#   ./scripts/install.sh
#
# Install-method preference order:
#   1. pipx   (isolated, recommended)
#   2. uv     (uv tool install / uvx)
#   3. pip    (pip install --user)
#
# Environment overrides:
#   KYOKO_INSTALL_SPEC   Package spec to install (default: "kyoko", or "." inside the repo).
#   KYOKO_INSTALL_METHOD Force one of: pipx | uv | pip (default: auto-detect).
#   KYOKO_PYTHON         Python executable to use (default: first compatible python3.13/python3.12/python3/python).
#
set -euo pipefail

readonly MIN_PY_MAJOR=3
readonly MIN_PY_MINOR=12

log()  { printf '\033[1;36m[kyoko]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[kyoko] warning:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[kyoko] error:\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------------------
# Locate Python and verify it is >= 3.12.
# ---------------------------------------------------------------------------
PYTHON=""
PYTHON_VERSION=""
python_version() {
  "$1" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "0.0"
}

python_is_compatible() {
  local version="$1"
  local major="${version%%.*}"
  local minor="${version##*.}"
  [ "$major" -gt "$MIN_PY_MAJOR" ] || {
    [ "$major" -eq "$MIN_PY_MAJOR" ] && [ "$minor" -ge "$MIN_PY_MINOR" ]
  }
}

detect_python() {
  local candidate
  local version

  if [ -n "${KYOKO_PYTHON:-}" ]; then
    have "$KYOKO_PYTHON" || die "KYOKO_PYTHON='${KYOKO_PYTHON}' was not found on PATH."
    PYTHON="$(command -v "$KYOKO_PYTHON")"
    PYTHON_VERSION="$(python_version "$PYTHON")"
    python_is_compatible "$PYTHON_VERSION" || die "Detected Python ${PYTHON_VERSION} at ${PYTHON}; Kyoko requires Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}."
    log "Using Python ${PYTHON_VERSION} (${PYTHON})."
    return
  fi

  for candidate in python3.13 python3.12 python3 python; do
    if have "$candidate"; then
      version="$(python_version "$candidate")"
      if python_is_compatible "$version"; then
        PYTHON="$(command -v "$candidate")"
        PYTHON_VERSION="$version"
        log "Using Python ${PYTHON_VERSION} (${PYTHON})."
        return
      fi
    fi
  done

  die "Could not find Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR} on PATH. Install Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ first, or set KYOKO_PYTHON=/path/to/python."
}

# ---------------------------------------------------------------------------
# Decide what to install. Inside the repo checkout we install the working tree
# (".") so contributors get their local changes; otherwise the published spec.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

INSTALL_SPEC="${KYOKO_INSTALL_SPEC:-}"
if [ -z "$INSTALL_SPEC" ]; then
  if [ -f "${REPO_ROOT}/setup.cfg" ] && grep -q '^name = kyoko' "${REPO_ROOT}/setup.cfg" 2>/dev/null; then
    INSTALL_SPEC="${REPO_ROOT}"
    log "Detected local Kyoko checkout; installing the working tree."
  else
    INSTALL_SPEC="kyoko"
    log "Installing the published 'kyoko' package."
  fi
fi

# ---------------------------------------------------------------------------
# Pick an install method.
# ---------------------------------------------------------------------------
choose_method() {
  if [ -n "${KYOKO_INSTALL_METHOD:-}" ]; then
    printf '%s' "$KYOKO_INSTALL_METHOD"
    return
  fi
  if have pipx; then
    printf 'pipx'
  elif have uv; then
    printf 'uv'
  else
    printf 'pip'
  fi
}

install_with_pipx() {
  log "Installing with pipx: pipx install --python '${PYTHON}' '${INSTALL_SPEC}'"
  pipx install --force --python "${PYTHON}" "${INSTALL_SPEC}"
}

install_with_uv() {
  # `uv tool install` is the persistent equivalent of pipx install.
  log "Installing with uv: uv tool install '${INSTALL_SPEC}'"
  uv tool install --force "${INSTALL_SPEC}"
}

install_with_pip() {
  log "Installing with pip: ${PYTHON} -m pip install --user '${INSTALL_SPEC}'"
  "$PYTHON" -m pip install --user --upgrade "${INSTALL_SPEC}"
}

main() {
  detect_python

  local method
  method="$(choose_method)"

  case "$method" in
    pipx)
      have pipx || die "KYOKO_INSTALL_METHOD=pipx but pipx is not installed."
      install_with_pipx
      ;;
    uv)
      have uv || die "KYOKO_INSTALL_METHOD=uv but uv is not installed."
      install_with_uv
      ;;
    pip)
      install_with_pip
      ;;
    *)
      die "Unknown install method '${method}'. Use pipx, uv, or pip."
      ;;
  esac

  # ------------------------------------------------------------------------
  # Confirm the command resolves and print the next step.
  # ------------------------------------------------------------------------
  if have kyoko; then
    log "Installed. 'kyoko' resolves at: $(command -v kyoko)"
  else
    warn "'kyoko' is installed but not on your current PATH."
    case "$method" in
      pipx) warn "Run 'pipx ensurepath' and open a new shell." ;;
      uv)   warn "Run 'uv tool update-shell' (or add uv's bin dir to PATH) and open a new shell." ;;
      pip)  warn "Add your Python user-base bin dir to PATH: $("$PYTHON" -m site --user-base 2>/dev/null)/bin" ;;
    esac
  fi

  cat <<'EOF'

  Next steps
  ----------
    1. Start the local dashboard + API (loopback only):

         kyoko serve

       Then open http://127.0.0.1:8765 in your browser.

    2. Try the bundled end-to-end demo against a throwaway DB:

         kyoko demo --db /tmp/kyoko-demo.db --json

    3. Check first-run readiness:

         kyoko doctor --json

  Kyoko stores everything locally under ~/.kyoko. Nothing leaves your machine.
EOF
}

main "$@"
