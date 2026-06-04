from __future__ import annotations

from typing import Any


TERMS: dict[str, dict[str, str]] = {
    "issue": {
        "label": "Issue",
        "description": "A specific observed failure or weakness backed by trace, task, eval, or replay evidence.",
    },
    "insight": {
        "label": "Insight",
        "description": "The reusable lesson or change Kyoko proposes from the issue evidence.",
    },
    "context": {
        "label": "Context fix",
        "description": "A change to agent-facing skillbook context or context delivery.",
    },
    "harness": {
        "label": "Harness fix",
        "description": "A change to eval, replay, instrumentation, or repository harness files.",
    },
}


def learning_terms() -> dict[str, dict[str, str]]:
    return {key: dict(value) for key, value in TERMS.items()}


def section_label(section: Any) -> str:
    if isinstance(section, str):
        term = TERMS.get(section)
        if term is not None:
            return term["label"]
        if section:
            return section.replace("_", " ").title()
    return "Unknown fix"


def section_description(section: Any) -> str:
    if isinstance(section, str):
        term = TERMS.get(section)
        if term is not None:
            return term["description"]
    return "A proposal whose write plane is not recognized by this Kyoko version."
