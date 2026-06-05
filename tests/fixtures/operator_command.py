#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kyoko.analyze import (
    BEGIN_PROPOSAL_BLOCK,
    END_PROPOSAL_BLOCK,
    mock_issues_from_bundle,
    mock_learning_proposal,
)
from kyoko.operator_prompts import (
    BEGIN_ISSUES_BLOCK,
    END_ISSUES_BLOCK,
)


def main() -> int:
    evidence_path = os.environ.get("KYOKO_EVIDENCE_PATH")
    if not evidence_path:
        print("KYOKO_EVIDENCE_PATH is required", file=sys.stderr)
        return 2
    prompt_path = os.environ.get("KYOKO_OPERATOR_PROMPT_PATH")
    if not prompt_path or not Path(prompt_path).exists():
        print("KYOKO_OPERATOR_PROMPT_PATH is required", file=sys.stderr)
        return 3
    stdin_prompt = sys.stdin.read()

    bundle = json.loads(Path(evidence_path).read_text())

    # Detect intent: the diagnosis turn advertises the issues block (in the prompt and via
    # KYOKO_ISSUES_BLOCK_BEGIN); the proposal-authoring turn advertises the proposal block.
    wants_issues = (
        BEGIN_ISSUES_BLOCK in stdin_prompt
        or os.environ.get("KYOKO_ISSUES_BLOCK_BEGIN") is not None
    ) and "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" not in stdin_prompt

    if wants_issues:
        issues = mock_issues_from_bundle(bundle)
        print("Operator analyzed the evidence bundle and diagnosed one issue.")
        print(f"Prompt path: {prompt_path}")
        print(BEGIN_ISSUES_BLOCK)
        print(json.dumps(issues, sort_keys=True))
        print(END_ISSUES_BLOCK)
        print("Done.")
        return 0

    if "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON" not in stdin_prompt:
        print("operator prompt was not passed on stdin", file=sys.stderr)
        return 4

    proposal = mock_learning_proposal(bundle)
    proposal["id"] = proposal["id"].replace("proposal_mock_", "proposal_command_")
    proposal["producer"]["name"] = "fixture-command"
    proposal["producer"]["session_id"] = "fixture_command_session"

    print("Operator analyzed the evidence bundle and prepared one proposal.")
    print(f"Prompt path: {prompt_path}")
    print(BEGIN_PROPOSAL_BLOCK)
    print(json.dumps(proposal, sort_keys=True))
    print(END_PROPOSAL_BLOCK)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
