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
    expected_prefix = ["agent", "--agent", "main", "--local", "--message"]
    if len(sys.argv) != 9 or sys.argv[1:6] != expected_prefix or sys.argv[7:9] != ["--timeout", "120"]:
        print(
            "expected OpenClaw local shape: "
            "openclaw agent --agent main --local --message <prompt> --timeout 120",
            file=sys.stderr,
        )
        return 2
    inline_prompt = sys.argv[6]
    if "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" not in inline_prompt:
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
    proposal = mock_learning_proposal(bundle)
    proposal["id"] = proposal["id"].replace("proposal_mock_", "proposal_openclaw_")
    proposal["producer"]["kind"] = "operator_agent"
    proposal["producer"]["name"] = "openclaw"
    proposal["producer"]["session_id"] = "openclaw_local_main_session"

    print("OpenClaw local operator completed analysis.")
    print(BEGIN_PROPOSAL_BLOCK)
    print(json.dumps(proposal, sort_keys=True))
    print(END_PROPOSAL_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
