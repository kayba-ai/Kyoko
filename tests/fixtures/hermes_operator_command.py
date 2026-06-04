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
    if len(sys.argv) != 3 or sys.argv[1] != "-z":
        print("expected Hermes one-shot shape: hermes -z <prompt>", file=sys.stderr)
        return 2
    inline_prompt = sys.argv[2]
    if "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" not in inline_prompt:
        print("Kyoko prompt was not passed through -z", file=sys.stderr)
        return 3
    stdin_prompt = sys.stdin.read()
    if inline_prompt != stdin_prompt:
        print("stdin prompt and -z prompt differ", file=sys.stderr)
        return 4
    evidence_path = os.environ.get("KYOKO_EVIDENCE_PATH")
    if not evidence_path:
        print("KYOKO_EVIDENCE_PATH is required", file=sys.stderr)
        return 5

    bundle = json.loads(Path(evidence_path).read_text())
    proposal = mock_learning_proposal(bundle)
    proposal["id"] = proposal["id"].replace("proposal_mock_", "proposal_hermes_")
    proposal["producer"]["kind"] = "operator_agent"
    proposal["producer"]["name"] = "hermes"
    proposal["producer"]["session_id"] = "hermes_one_shot_session"

    print("Hermes one-shot operator completed analysis.")
    print(BEGIN_PROPOSAL_BLOCK)
    print(json.dumps(proposal, sort_keys=True))
    print(END_PROPOSAL_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
