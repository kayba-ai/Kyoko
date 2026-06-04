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
    if len(sys.argv) < 6:
        print("expected prompt, profile, evidence path, prompt path, and schema path args", file=sys.stderr)
        return 2

    prompt_text = sys.argv[1]
    profile_id = sys.argv[2]
    evidence_path = Path(sys.argv[3])
    prompt_path = Path(sys.argv[4])
    schema_path = Path(sys.argv[5])

    if "Kyoko Operator Task" not in prompt_text or "span_fetch_timeout_001" not in prompt_text:
        print("operator prompt was not expanded into argv", file=sys.stderr)
        return 3
    if profile_id != os.environ.get("KYOKO_PROFILE_ID"):
        print("profile placeholder did not match environment", file=sys.stderr)
        return 4
    if not evidence_path.exists() or not prompt_path.exists() or not schema_path.exists():
        print("artifact path placeholder missing", file=sys.stderr)
        return 5

    bundle = json.loads(evidence_path.read_text())
    proposal = mock_learning_proposal(bundle)
    proposal["id"] = proposal["id"].replace("proposal_mock_", "proposal_arg_")
    proposal["producer"]["name"] = "fixture-arg-command"
    proposal["producer"]["session_id"] = "fixture_arg_command_session"

    print("ARG_PROFILE=" + profile_id)
    print(BEGIN_PROPOSAL_BLOCK)
    print(json.dumps(proposal, sort_keys=True))
    print(END_PROPOSAL_BLOCK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
