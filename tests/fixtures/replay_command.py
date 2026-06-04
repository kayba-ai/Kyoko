#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kyoko.checks import BEGIN_REPLAY_RESULT_BLOCK, END_REPLAY_RESULT_BLOCK


def main() -> int:
    request_path = os.environ.get("KYOKO_REPLAY_REQUEST_PATH")
    replay_run_id = os.environ.get("KYOKO_REPLAY_RUN_ID")
    if not request_path or not replay_run_id:
        print("KYOKO_REPLAY_REQUEST_PATH and KYOKO_REPLAY_RUN_ID are required", file=sys.stderr)
        return 2

    request = json.loads(Path(request_path).read_text())
    fixture_path = ROOT / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json"
    replay_result = json.loads(fixture_path.read_text())
    replay_result["replay"]["replay_run_id"] = replay_run_id
    replay_result["replay"]["note"] = (
        "Fixture replay command completed request "
        f"{request['replay_run']['id']} with mocked network behavior."
    )

    print("Replay command received Kyoko request and produced one replay result.")
    print(BEGIN_REPLAY_RESULT_BLOCK)
    print(json.dumps(replay_result, sort_keys=True))
    print(END_REPLAY_RESULT_BLOCK)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
