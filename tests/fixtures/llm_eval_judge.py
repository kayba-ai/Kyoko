#!/usr/bin/env python3
"""Deterministic mock llm_eval judge for tests (no model).

Reads the kyoko.llm_eval_request.v1 request on stdin and emits a fixed score in
the distinct llm_eval result block. The score can be overridden with env
``MOCK_SCORE`` (numeric) / ``MOCK_BOOL`` (``true``/``false``); otherwise numeric
templates get 0.3 and boolean templates get ``true``.
"""
import json
import os
import sys

req = json.loads(sys.stdin.read())
output_type = (req.get("output") or {}).get("type")
if output_type == "numeric":
    score = float(os.environ.get("MOCK_SCORE", "0.3"))
else:
    score = os.environ.get("MOCK_BOOL", "true").lower() == "true"

print("noise line that should be ignored")
print("BEGIN_KYOKO_LLM_EVAL_RESULT_JSON")
print(json.dumps({"score": score, "reasoning": f"mock reasoning for {req['unit_ref']}"}))
print("END_KYOKO_LLM_EVAL_RESULT_JSON")
