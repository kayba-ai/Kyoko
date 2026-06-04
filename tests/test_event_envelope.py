"""Tests for the normalized ingest event-envelope contract (Q20 / spec 0013)."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from kyoko import event_envelope
from kyoko.event_envelope import EventEnvelope, validate_envelope

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "docs" / "fixtures" / "source-events"
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "event-envelope.schema.json"
HERMES_FIXTURE = FIXTURE_DIR / "hermes-news-research-minimal.json"
OTLP_FIXTURE = FIXTURE_DIR / "otlp-genai-minimal.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


class SchemaSanityTests(unittest.TestCase):
    def test_schema_is_valid_draft_2020_12(self) -> None:
        import jsonschema

        schema = _load(SCHEMA_PATH)
        self.assertEqual(
            schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        # Raises if the schema itself is malformed.
        jsonschema.Draft202012Validator.check_schema(schema)


class FixtureValidationTests(unittest.TestCase):
    def test_hermes_fixture_validates_clean(self) -> None:
        errors = validate_envelope(_load(HERMES_FIXTURE), schema_path=SCHEMA_PATH)
        self.assertEqual(errors, [], msg=f"unexpected errors: {errors}")

    def test_normalized_otlp_validates_clean(self) -> None:
        # The raw OTLP fixture is an *input* format, not an envelope. The contract
        # is that the OTLP normalizer's output conforms to the envelope schema.
        from kyoko.otlp import normalize_otlp_json

        envelope = normalize_otlp_json(
            _load(OTLP_FIXTURE),
            profile_id="profile_otlp_test",
            profile_name="otlp test",
            root_path=".",
        )
        errors = validate_envelope(envelope, schema_path=SCHEMA_PATH)
        self.assertEqual(errors, [], msg=f"unexpected errors: {errors}")

    def test_default_schema_path_resolves_and_validates(self) -> None:
        # Exercise validate_envelope with no explicit schema_path (default lookup).
        self.assertIsNotNone(event_envelope.default_schema_path())
        errors = validate_envelope(_load(HERMES_FIXTURE))
        self.assertEqual(errors, [])


class MalformedEnvelopeTests(unittest.TestCase):
    def test_missing_profile_reports_error(self) -> None:
        errors = validate_envelope({"sources": []}, schema_path=SCHEMA_PATH)
        self.assertTrue(errors)
        self.assertTrue(any("profile" in e for e in errors), msg=errors)

    def test_bad_span_kind_reports_error(self) -> None:
        envelope = copy.deepcopy(_load(HERMES_FIXTURE))
        envelope["spans"][0]["kind"] = "not_a_real_kind"
        errors = validate_envelope(envelope, schema_path=SCHEMA_PATH)
        self.assertTrue(errors)
        self.assertTrue(any("spans" in e for e in errors), msg=errors)

    def test_inline_payload_and_ref_conflict_reports_error(self) -> None:
        # Providing both the *_ref and the inline payload sibling is ambiguous
        # provenance; storage rejects it and so must the schema.
        envelope = copy.deepcopy(_load(HERMES_FIXTURE))
        run = envelope["runs"][0]
        run["input_ref"] = "blob_run_input_001"
        run["input_payload"] = "inline conflicting payload"
        errors = validate_envelope(envelope, schema_path=SCHEMA_PATH)
        self.assertTrue(errors)
        self.assertTrue(any("runs" in e for e in errors), msg=errors)

    def test_wrong_top_level_type_reports_error(self) -> None:
        errors = validate_envelope(["not", "an", "object"], schema_path=SCHEMA_PATH)
        self.assertTrue(errors)

    def test_bad_fixture_version_reports_error(self) -> None:
        envelope = copy.deepcopy(_load(HERMES_FIXTURE))
        envelope["fixture_version"] = "kyoko.something_else.v9"
        errors = validate_envelope(envelope, schema_path=SCHEMA_PATH)
        self.assertTrue(errors)
        self.assertTrue(any("fixture_version" in e for e in errors), msg=errors)


class EventEnvelopeDataclassTests(unittest.TestCase):
    def test_from_obj_populates_collections(self) -> None:
        envelope = EventEnvelope.from_obj(_load(HERMES_FIXTURE))
        self.assertEqual(envelope.profile["id"], "profile_news_research_001")
        self.assertEqual(envelope.fixture_version, "kyoko.source_fixture.v1")
        self.assertEqual(len(envelope.spans), 2)
        self.assertEqual(len(envelope.handoffs), 1)
        self.assertEqual(len(envelope.timeline_events), 2)

    def test_from_obj_requires_profile(self) -> None:
        with self.assertRaises(ValueError):
            EventEnvelope.from_obj({"sources": []})


if __name__ == "__main__":
    unittest.main()
