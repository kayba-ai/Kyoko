"""Optional, dependency-free helper for Kyoko's normalized ingest event envelope.

The *event envelope* is the canonical source-event shape Kyoko accepts at
``kyoko ingest`` / ``POST /api/ingest`` (and that ``kyoko ingest-otlp`` and the SDK
recorder normalize into). It is documented in ``docs/specs/0013-event-envelope.md``
and constrained by ``docs/schemas/event-envelope.schema.json``.

This module is intentionally outside the ingest hot path: ``kyoko.storage`` performs
its own per-column checks at upsert time. ``validate_envelope`` is a convenience for
adapter authors, tests, and tooling that want to fail fast against the written
contract before calling ingest.

Stdlib-only except for a lazy ``import jsonschema`` (already a Kyoko runtime
dependency), imported only inside ``validate_envelope`` so importing this module
never pulls it in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

__all__ = [
    "ENVELOPE_FIXTURE_VERSIONS",
    "ENVELOPE_COLLECTIONS",
    "INLINE_PAYLOAD_SIBLINGS",
    "EventEnvelope",
    "default_schema_path",
    "load_schema",
    "validate_envelope",
]

# Both spellings are accepted in the wild: the OTLP normalizer and offline
# importers emit ``kyoko.source_events.v1``; the original hand-authored Hermes
# fixture uses ``kyoko.source_fixture.v1``. Ingest ignores the field entirely.
ENVELOPE_FIXTURE_VERSIONS = (
    "kyoko.source_events.v1",
    "kyoko.source_fixture.v1",
)

# Top-level entity collections, in dependency order. Mirrors
# ``kyoko.storage.FIXTURE_COLLECTIONS`` plus the entities materialized ahead of
# them (``profile`` is a single object, not a collection).
ENVELOPE_COLLECTIONS = (
    "sources",
    "agent_identities",
    "workflow_nodes",
    "queues",
    "tasks",
    "task_attempts",
    "runs",
    "spans",
    "handoffs",
    "timeline_events",
)

# ``<collection>: {<ref_field>: <inline_payload_field>}`` — an entity may carry the
# inline payload sibling OR the pre-registered blob ref, never both. Mirrors
# ``kyoko.storage.INLINE_PAYLOAD_FIELDS``.
INLINE_PAYLOAD_SIBLINGS: dict[str, dict[str, str]] = {
    "tasks": {"body_ref": "body_payload"},
    "task_attempts": {"summary_ref": "summary_payload", "error_ref": "error_payload"},
    "runs": {"input_ref": "input_payload", "output_ref": "output_payload"},
    "spans": {
        "input_ref": "input_payload",
        "output_ref": "output_payload",
        "raw_ref": "raw_payload",
    },
    "handoffs": {"reason_ref": "reason_payload", "payload_ref": "payload"},
    "timeline_events": {"payload_ref": "payload"},
}


@dataclass(frozen=True)
class EventEnvelope:
    """Pure-documentation view of the envelope's top-level shape.

    This is a read-only convenience wrapper. It does not normalize, mutate, or
    persist anything; ``kyoko.storage.ingest_source_payload`` is the only writer.
    """

    profile: dict[str, Any]
    fixture_version: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    agent_identities: list[dict[str, Any]] = field(default_factory=list)
    workflow_nodes: list[dict[str, Any]] = field(default_factory=list)
    queues: list[dict[str, Any]] = field(default_factory=list)
    tasks: list[dict[str, Any]] = field(default_factory=list)
    task_attempts: list[dict[str, Any]] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)
    spans: list[dict[str, Any]] = field(default_factory=list)
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    timeline_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> "EventEnvelope":
        if not isinstance(obj, dict):
            raise TypeError("event envelope must be a JSON object")
        profile = obj.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("event envelope is missing a profile object")
        kwargs: dict[str, Any] = {
            "profile": profile,
            "fixture_version": obj.get("fixture_version"),
            "name": obj.get("name"),
            "description": obj.get("description"),
        }
        for collection in ENVELOPE_COLLECTIONS:
            value = obj.get(collection, [])
            kwargs[collection] = list(value) if isinstance(value, list) else []
        return cls(**kwargs)


def default_schema_path() -> Optional[Path]:
    """Locate the checked-in envelope JSON Schema, or ``None`` if absent.

    Prefers the bundled copy under ``kyoko/assets/schemas`` (when shipped), then
    falls back to the authoring copy under ``docs/schemas``.
    """

    candidates = [
        Path(__file__).resolve().parent / "assets" / "schemas" / "event-envelope.schema.json",
        Path(__file__).resolve().parent.parent / "docs" / "schemas" / "event-envelope.schema.json",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_schema(schema_path: Optional[Path] = None) -> dict[str, Any]:
    path = schema_path or default_schema_path()
    if path is None:
        raise FileNotFoundError("event-envelope.schema.json not found")
    return json.loads(Path(path).read_text())


def validate_envelope(obj: Any, *, schema_path: Optional[Path] = None) -> list[str]:
    """Validate ``obj`` against the event-envelope schema.

    Returns a list of human-readable error strings; an empty list means the
    envelope conforms to the written contract. Never raises on a malformed
    envelope — only on genuinely unusable inputs (missing/invalid schema file).

    ``jsonschema`` is imported lazily so that importing this module stays
    dependency-free.
    """

    import jsonschema  # lazy: already a Kyoko runtime dependency

    schema = load_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    for error in sorted(validator.iter_errors(obj), key=lambda e: list(e.path)):
        location = "/".join(str(part) for part in error.path) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors
