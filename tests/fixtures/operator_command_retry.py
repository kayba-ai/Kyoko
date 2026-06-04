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
    proposal = mock_learning_proposal(bundle)
    proposal["id"] = proposal["id"].replace("proposal_mock_", "proposal_retry_")
    proposal["producer"]["name"] = "fixture-retry-command"
    proposal["producer"]["session_id"] = "fixture_retry_command_session"

    print("Corrected proposal after Kyoko retry feedback.")
    print(BEGIN_PROPOSAL_BLOCK)
    print(json.dumps(proposal, sort_keys=True))
    print(END_PROPOSAL_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
