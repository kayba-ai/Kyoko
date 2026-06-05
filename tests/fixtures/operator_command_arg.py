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
    if len(sys.argv) < 6:
        print("expected prompt, profile, evidence path, prompt path, and schema path args", file=sys.stderr)
        return 2

    prompt_text = sys.argv[1]
    profile_id = sys.argv[2]
    evidence_path = Path(sys.argv[3])
    prompt_path = Path(sys.argv[4])
    schema_path = Path(sys.argv[5])

    if "Kyoko Diagnosis Task" not in prompt_text or "span_fetch_timeout_001" not in prompt_text:
        print("operator prompt was not expanded into argv", file=sys.stderr)
        return 3
    if profile_id != os.environ.get("KYOKO_PROFILE_ID"):
        print("profile placeholder did not match environment", file=sys.stderr)
        return 4
    if not evidence_path.exists() or not prompt_path.exists() or not schema_path.exists():
        print("artifact path placeholder missing", file=sys.stderr)
        return 5

    bundle = json.loads(evidence_path.read_text())
    issues = mock_issues_from_bundle(bundle)

    print("ARG_PROFILE=" + profile_id)
    print(BEGIN_ISSUES_BLOCK)
    print(json.dumps(issues, sort_keys=True))
    print(END_ISSUES_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
