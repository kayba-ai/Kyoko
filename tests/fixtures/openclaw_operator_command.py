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
    expected_prefix = ["agent", "--agent", "main", "--local", "--message"]
    if len(sys.argv) != 9 or sys.argv[1:6] != expected_prefix or sys.argv[7:9] != ["--timeout", "120"]:
        print(
            "expected OpenClaw local shape: "
            "openclaw agent --agent main --local --message <prompt> --timeout 120",
            file=sys.stderr,
        )
        return 2
    inline_prompt = sys.argv[6]
    if "BEGIN_KYOKO_ISSUES_JSON" not in inline_prompt:
        print("Kyoko prompt was not passed through --message", file=sys.stderr)
        return 3
    stdin_prompt = sys.stdin.read()
    if inline_prompt != stdin_prompt:
        print("stdin prompt and --message prompt differ", file=sys.stderr)
        return 4
    evidence_path = os.environ.get("KYOKO_EVIDENCE_PATH")
    if not evidence_path:
        print("KYOKO_EVIDENCE_PATH is required", file=sys.stderr)
        return 5

    bundle = json.loads(Path(evidence_path).read_text())
    issues = mock_issues_from_bundle(bundle)

    print("OpenClaw local operator completed diagnosis.")
    print(BEGIN_ISSUES_BLOCK)
    print(json.dumps(issues, sort_keys=True))
    print(END_ISSUES_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
