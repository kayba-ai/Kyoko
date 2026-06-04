#!/usr/bin/env python3
"""Validate Kyoko pre-build gate artifacts."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kyoko.gates import ValidationError, validate_gate_artifacts  # noqa: E402


def main() -> int:
    try:
        report = validate_gate_artifacts(root=ROOT)
    except ValidationError as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    for message in report.messages:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
