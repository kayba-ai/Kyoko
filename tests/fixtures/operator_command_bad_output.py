#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kyoko.analyze import BEGIN_PROPOSAL_BLOCK, END_PROPOSAL_BLOCK, mock_learning_proposal


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "partial-json"
    evidence_path = os.environ.get("KYOKO_EVIDENCE_PATH")
    if not evidence_path:
        print("KYOKO_EVIDENCE_PATH is required", file=sys.stderr)
        return 2

    print(f"fixture bad operator mode={mode}")
    print(BEGIN_PROPOSAL_BLOCK)
    if mode == "partial-json":
        print('{"schema_version":"kyoko.learning_proposal.v1","id":"proposal_bad_partial"')
    else:
        bundle = json.loads(Path(evidence_path).read_text())
        proposal = mock_learning_proposal(bundle)
        proposal["producer"]["name"] = "fixture-bad-command"
        proposal["producer"]["session_id"] = f"fixture_bad_{mode}"
        if mode == "hallucinated-evidence":
            proposal["id"] = "proposal_bad_hallucinated_evidence_001"
            proposal["evidence_refs"][0]["entity_id"] = "span_does_not_exist_001"
        elif mode == "unsupported-change":
            proposal["id"] = "proposal_bad_unsupported_change_001"
            proposal["proposed_changes"] = [
                {
                    "type": "rewrite_agent_runtime",
                    "operation": "replace",
                    "target": "agent.py",
                }
            ]
        else:
            print(END_PROPOSAL_BLOCK)
            print(f"unknown bad-output mode: {mode}", file=sys.stderr)
            return 3
        print(json.dumps(proposal, sort_keys=True))
    print(END_PROPOSAL_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
