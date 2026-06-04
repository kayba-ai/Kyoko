from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .bundled_assets import AssetError, load_bundled_json
from .checks import BEGIN_REPLAY_RESULT_BLOCK, END_REPLAY_RESULT_BLOCK


def main() -> int:
    request_path = os.environ.get("KYOKO_REPLAY_REQUEST_PATH")
    replay_run_id = os.environ.get("KYOKO_REPLAY_RUN_ID")
    if not request_path or not replay_run_id:
        print("KYOKO_REPLAY_REQUEST_PATH and KYOKO_REPLAY_RUN_ID are required", file=sys.stderr)
        return 2

    try:
        request = json.loads(Path(request_path).read_text())
        replay_result = load_bundled_json("replay-results/researcher-fetch-timeout-success.json")
    except (OSError, json.JSONDecodeError, AssetError) as exc:
        print(f"fixture_replay_failed:{exc}", file=sys.stderr)
        return 3

    replay_result["replay"]["replay_run_id"] = replay_run_id
    replay_result["replay"]["note"] = (
        "Bundled Kyoko fixture replay completed request "
        f"{request['replay_run']['id']} with mocked network behavior."
    )

    print("Kyoko fixture replay received one replay request.")
    print(BEGIN_REPLAY_RESULT_BLOCK)
    print(json.dumps(replay_result, sort_keys=True))
    print(END_REPLAY_RESULT_BLOCK)
    print("Kyoko fixture replay finished.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
