import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.evidence import build_evidence_bundle, write_evidence_bundle
from kyoko.redaction import get_redaction_policy
from kyoko.storage import ingest_source_fixture, ingest_source_payload


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


class EvidenceTests(unittest.TestCase):
    def test_build_evidence_bundle_from_fixture(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            bundle = build_evidence_bundle(db_path=db_path)

            self.assertEqual(bundle["schema_version"], "kyoko.evidence_bundle.v1")
            self.assertEqual(bundle["profile_id"], "profile_news_research_001")
            self.assertEqual(bundle["summary"]["failed_spans"], 1)
            self.assertEqual(bundle["spans"][1]["attributes_json"]["error_type"], "timeout")
            self.assertEqual(bundle["handoffs"][0]["id"], "handoff_research_to_writer_001")
            self.assertEqual(
                bundle["eval_capabilities"]["gateable_eval_types"],
                ["deterministic_assertion", "regression_replay"],
            )
            preset_names = {
                preset["name"]
                for preset in bundle["eval_capabilities"]["assertion_presets"]
            }
            self.assertIn("replay_success_shape", preset_names)
            self.assertIn("replay_handoff_present", preset_names)

    def test_write_evidence_bundle(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_path = Path(tmpdir) / "evidence.json"
            ingest_source_fixture(db_path, FIXTURE)

            write_evidence_bundle(db_path=db_path, output_path=output_path)

            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["summary"]["failed_spans"], 1)
            self.assertEqual(payload["tasks"][0]["id"], "task_research_topic_001")

    def test_evidence_bundle_redacts_sensitive_values_and_payload_refs_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            fixture = _fixture_with_secrets()
            ingest_source_payload(
                db_path=db_path,
                fixture=fixture,
                source_label="secret-fixture",
            )

            bundle = build_evidence_bundle(db_path=db_path, consumer="test:evidence")
            encoded = json.dumps(bundle, sort_keys=True)

            self.assertEqual(bundle["redaction"]["policy"]["payload_access"], "redacted")
            self.assertGreaterEqual(bundle["redaction"]["redacted_count"], 5)
            self.assertEqual(bundle["redaction"]["consumer"], "test:evidence")
            self.assertTrue(bundle["redaction"]["redacted"])
            self.assertEqual(bundle["spans"][1]["attributes_json"]["error_type"], "timeout")
            self.assertNotIn("sk-secretsecretsecret", encoded)
            self.assertNotIn("raw-secret-ref", encoded)
            self.assertNotIn("fixture-token-hash", encoded)
            self.assertNotIn("super-secret", encoded)
            self.assertIn("[REDACTED:payload_ref]", encoded)
            self.assertIn("[REDACTED:secret]", encoded)

    def test_redaction_default_policy_is_the_global_redact_on_export_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            policy = get_redaction_policy(db_path=db_path)

            self.assertIsNone(policy["profile_id"])
            self.assertEqual(policy["payload_access"], "redacted")
            self.assertTrue(policy["redact_sensitive_values"])
            self.assertIn("api_key", policy["sensitive_key_patterns"])


def _fixture_with_secrets() -> dict:
    payload = json.loads(FIXTURE.read_text())
    payload["sources"][0]["config_json"] = {
        "api_key": "sk-secretsecretsecret",
        "endpoint": "https://example.test",
    }
    payload["task_attempts"][0]["metadata_json"] = {
        "session_cookie": "cookie-secret",
    }
    payload["runs"][0]["metadata_json"] = {
        "nested": {
            "client_secret": "super-secret",
        }
    }
    payload["spans"][1]["attributes_json"]["authorization"] = "Bearer secret-token-value"
    payload["spans"][1]["raw_ref"] = "raw-secret-ref"
    return payload


if __name__ == "__main__":
    unittest.main()
