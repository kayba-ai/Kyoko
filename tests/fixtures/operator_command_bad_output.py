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
    mode = sys.argv[1] if len(sys.argv) > 1 else "partial-json"
    evidence_path = os.environ.get("KYOKO_EVIDENCE_PATH")
    if not evidence_path:
        print("KYOKO_EVIDENCE_PATH is required", file=sys.stderr)
        return 2

    print(f"fixture bad operator mode={mode}")
    print(BEGIN_ISSUES_BLOCK)
    if mode == "partial-json":
        # Malformed JSON array — fails issues-block extraction (invalid_output).
        print('[{"schema_version":"kyoko.issue.v1","title":"partial"')
    else:
        bundle = json.loads(Path(evidence_path).read_text())
        issues = mock_issues_from_bundle(bundle)
        issue = issues[0]
        if mode == "hallucinated-evidence":
            # References a span that does not exist — referential-integrity failure.
            issue["evidence_refs"][0]["entity_id"] = "span_does_not_exist_001"
            issue["affected_span_ids"] = ["span_does_not_exist_001"]
        elif mode == "missing-root-cause":
            # Schema/enum failure — issue is missing a required diagnosis.
            issue.pop("root_cause", None)
        else:
            print(END_ISSUES_BLOCK)
            print(f"unknown bad-output mode: {mode}", file=sys.stderr)
            return 3
        print(json.dumps([issue], sort_keys=True))
    print(END_ISSUES_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
