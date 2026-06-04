from __future__ import annotations

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any


ISSUE = "Fetch timeouts are treated as final failures."
INSIGHT = (
    "Retry transient fetch timeouts once with the same request before treating "
    "the task as a final failure or handing it off."
)
SKILL_ID = "context_legacy_ace_offline_00001"
RUN_ID = "run_research_topic_001"
SPAN_ID = "span_fetch_timeout_001"


def main() -> int:
    try:
        report = run()
    except Exception as exc:  # pragma: no cover - exercised through subprocess callers.
        print(f"legacy ACE offline smoke failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


def run() -> dict[str, Any]:
    after_path = Path(_required_env("KYOKO_ACE_AFTER_PATH"))
    output_dir = Path(os.environ.get("KYOKO_ACE_OUTPUT_DIR", after_path.parent))
    output_dir.mkdir(parents=True, exist_ok=True)

    # ACE >=0.12.0 replaced the legacy Playbook/OfflineAdapter API with the
    # Skillbook v2 API. We exercise the real installed ACE package by loading the
    # Kyoko-exported before/after skillbook, adding a deterministic context skill
    # through ACE's own Skillbook.add_skill, and serializing it back. No model or
    # provider is invoked: the learned issue/insight are fixed inputs and ACE only
    # performs the skill construction, occurrence linkage, and serialization.
    import_output = io.StringIO()
    with redirect_stdout(import_output), redirect_stderr(import_output):
        from ace.core.skillbook import Skillbook

    after = json.loads(after_path.read_text(encoding="utf-8"))
    if not isinstance(after, dict):
        raise ValueError("after skillbook must be a JSON object")

    skillbook = Skillbook.from_dict(after)
    skill = skillbook.add_skill(
        "context",
        ISSUE,
        keywords=["fetch", "timeout", "retry", "native-ace"],
        insight=INSIGHT,
        skill_id=SKILL_ID,
        insight_source={
            "trace_uid": f"kyoko:{RUN_ID}",
            "source_system": "kyoko",
            "trace_id": RUN_ID,
            "display_name": f"span:{SPAN_ID}",
            "relation": "failure",
            "operation_type": "ADD",
            "error_identification": ISSUE,
            "learning_text": INSIGHT,
        },
    )
    after_payload = skillbook.to_dict()
    after_path.write_text(
        json.dumps(after_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    skillbook_path = output_dir / "native-ace-skillbook.json"
    skillbook_path.write_text(skillbook.dumps() + "\n", encoding="utf-8")

    return {
        "kind": "legacy_ace_offline_adapter_command",
        "ace_import_output": import_output.getvalue(),
        "after_path": str(after_path),
        "skillbook_path": str(skillbook_path),
        "skill_id": skill.id,
        "result_count": 1,
        "provider_backed": False,
        "external_model_invoked": False,
    }


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name}_required")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
