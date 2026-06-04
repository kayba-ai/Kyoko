#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


BEGIN = "BEGIN_KYOKO_ACE_SKILL_JSON"
END = "END_KYOKO_ACE_SKILL_JSON"


def main() -> int:
    after_path = Path(_required_env("KYOKO_ACE_AFTER_PATH"))
    before_path = Path(os.environ.get("KYOKO_ACE_BEFORE_PATH", after_path))
    payload = json.loads(after_path.read_text(encoding="utf-8"))
    prompt = _prompt(before_path=before_path, after_path=after_path)
    completed = subprocess.run(
        [
            "claude",
            "--print",
            "--input-format",
            "text",
            "--output-format",
            "text",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "Read",
            "--no-session-persistence",
        ],
        input=prompt,
        text=True,
        capture_output=True,
        check=False,
        timeout=180,
    )
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    if completed.returncode != 0:
        return completed.returncode

    skill = _parse_skill(completed.stdout)
    skill_id = "context-claude-provider-live-001"
    payload.setdefault("skills", {})[skill_id] = {
        "id": skill_id,
        "section": "context",
        "keywords": skill["keywords"],
        "issue": skill["issue"],
        "insight": skill["insight"],
        "occurrences": [],
        "active": True,
    }
    sections = payload.setdefault("sections", {})
    context_ids = sections.setdefault("context", [])
    if skill_id not in context_ids:
        context_ids.append(skill_id)
    after_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote provider-backed ACE skill {skill_id} to {after_path}")
    return 0


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} missing")
    return value


def _prompt(*, before_path: Path, after_path: Path) -> str:
    return "\n".join(
        [
            "You are a provider-backed ACE-compatible Skillbook mutator for a Kyoko smoke test.",
            "Read the cloned Skillbook context and propose exactly one context skill.",
            "Return exactly one delimited JSON block and no extra commentary.",
            f"Use delimiters {BEGIN} and {END}.",
            "JSON shape: {\"issue\": string, \"insight\": string, \"keywords\": [string, ...]}.",
            "The skill should address transient fetch/source timeouts before handoff.",
            f"Before Skillbook path: {before_path}",
            f"After Skillbook path to be written by this wrapper: {after_path}",
        ]
    )


def _parse_skill(text: str) -> dict[str, object]:
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end <= start:
        raise SystemExit("claude_skill_json_block_missing")
    raw = text[start + len(BEGIN) : end].strip()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise SystemExit("claude_skill_json_not_object")
    issue = payload.get("issue")
    insight = payload.get("insight")
    keywords = payload.get("keywords")
    if not isinstance(issue, str) or not issue.strip():
        raise SystemExit("claude_skill_issue_missing")
    if not isinstance(insight, str) or not insight.strip():
        raise SystemExit("claude_skill_insight_missing")
    if not isinstance(keywords, list) or not all(isinstance(item, str) and item.strip() for item in keywords):
        raise SystemExit("claude_skill_keywords_invalid")
    return {
        "issue": issue.strip(),
        "insight": insight.strip(),
        "keywords": [item.strip() for item in keywords],
    }


if __name__ == "__main__":
    raise SystemExit(main())
