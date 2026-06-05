#!/usr/bin/env python3
"""Operator-style mock judge for tests (mimics an agent CLI, no model).

Unlike ``llm_eval_judge.py`` (the BYO ``--command`` contract that reads the request
JSON on stdin), this reads the rendered PROMPT delivered the way an operator adapter
delivers it — a ``{prompt_path}`` file given as argv[1], else on stdin — then echoes it
back (so the instruction text, which itself names the result-block markers, appears in
stdout) before emitting its own result block. That exercises the tolerant parser's
"prefer the last well-formed block" behaviour. Score override via ``MOCK_SCORE``.
"""
import os
import sys

if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    prompt = open(sys.argv[1], encoding="utf-8").read()
else:
    prompt = sys.stdin.read()

score = os.environ.get("MOCK_SCORE", "0.3")
begin = os.environ["KYOKO_LLM_EVAL_RESULT_BLOCK_BEGIN"]
end = os.environ["KYOKO_LLM_EVAL_RESULT_BLOCK_END"]
unit = os.environ.get("KYOKO_LLM_EVAL_UNIT_REF", "?")

print("Let me restate the task before judging:\n" + prompt)
print("Now my judgment:")
print(begin)
print('{"score": %s, "reasoning": "operator mock for %s"}' % (score, unit))
print(end)
