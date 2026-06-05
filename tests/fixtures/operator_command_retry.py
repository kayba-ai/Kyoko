#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kyoko.analyze import mock_issues_from_bundle
from kyoko.operator_prompts import BEGIN_ISSUES_BLOCK, END_ISSUES_BLOCK


def main() -> int:
    attempt = int(os.environ.get("KYOKO_OPERATOR_ATTEMPT", "1"))
    stdin_prompt = sys.stdin.read()
    if attempt == 1:
        print("I found the issue, but this is malformed output without the required block.")
        return 0

    if "Retry Correction" not in stdin_prompt:
        print("retry prompt missing correction instructions", file=sys.stderr)
        return 2

    evidence_path = os.environ.get("KYOKO_EVIDENCE_PATH")
    if not evidence_path:
        print("KYOKO_EVIDENCE_PATH is required", file=sys.stderr)
        return 3

    bundle = json.loads(Path(evidence_path).read_text())
    issues = mock_issues_from_bundle(bundle)

    print("Corrected issues after Kyoko retry feedback.")
    print(BEGIN_ISSUES_BLOCK)
    print(json.dumps(issues, sort_keys=True))
    print(END_ISSUES_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
