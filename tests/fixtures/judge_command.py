#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    request_path = os.environ.get("KYOKO_JUDGE_REQUEST_PATH")
    if not request_path:
        print("KYOKO_JUDGE_REQUEST_PATH missing", file=sys.stderr)
        return 2
    request = json.loads(Path(request_path).read_text())
    eval_spec_id = request["eval_spec"]["id"]
    target = request["target"]
    result = {
        "schema_version": "kyoko.judge_result.v1",
        "judgment": {
            "verdict": "passed",
            "judge": "fixture_external_judge",
            "score": 0.93,
            "reasoning": f"Target {target['entity_type']}:{target['entity_id']} satisfies the rubric.",
            "evidence_refs": [
                {
                    "entity_type": target["entity_type"],
                    "entity_id": target["entity_id"],
                    "role": "judged_target",
                }
            ],
        },
        "metadata": {
            "eval_spec_id": eval_spec_id,
            "saw_redacted_request": request.get("redaction", {}).get("redacted") is True,
        },
    }
    print(os.environ["KYOKO_JUDGE_RESULT_BLOCK_BEGIN"])
    print(json.dumps(result, sort_keys=True))
    print(os.environ["KYOKO_JUDGE_RESULT_BLOCK_END"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
