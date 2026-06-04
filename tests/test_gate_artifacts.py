import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from kyoko.gates import (
    GateArtifactPaths,
    ValidationError,
    collect_ids,
    load_json,
    missing_evidence_refs,
    validate_gate_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]


class GateArtifactTests(unittest.TestCase):
    def test_gate_artifacts_validate(self) -> None:
        report = validate_gate_artifacts(root=ROOT)

        self.assertIn("semantic: valid proposal evidence refs resolve", report.messages)
        self.assertIn("semantic: Hermes operator proposal evidence refs resolve", report.messages)
        self.assertIn("semantic: OpenClaw operator proposal evidence refs resolve", report.messages)
        self.assertIn("semantic: valid harness proposal evidence refs resolve", report.messages)
        self.assertIn(
            "semantic: valid generated-file harness proposal evidence refs resolve",
            report.messages,
        )
        self.assertIn(
            "semantic: invalid proposal fails for expected hallucinated span",
            report.messages,
        )
        self.assertIn("bundled: runtime schema mirrors docs schema", report.messages)
        self.assertIn(
            "bundled: runtime source fixture mirrors docs source fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime proposal fixture mirrors docs proposal fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime harness proposal fixture mirrors docs proposal fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime generated-file harness proposal fixture mirrors docs proposal fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime Hermes operator proposal fixture mirrors docs proposal fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime OpenClaw operator proposal fixture mirrors docs proposal fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime invalid proposal fixture mirrors docs proposal fixture",
            report.messages,
        )
        self.assertIn(
            "bundled: runtime replay fixture mirrors docs replay fixture",
            report.messages,
        )

    def test_valid_context_proposal_refs_resolve(self) -> None:
        paths = GateArtifactPaths.from_root(ROOT)
        ids = collect_ids(load_json(paths.source_fixture))
        proposal = load_json(paths.valid_proposal)

        self.assertEqual(missing_evidence_refs(proposal, ids), [])

    def test_bundled_asset_drift_fails_validation(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            tmp_root = Path(tmpdir_name)
            shutil.copytree(ROOT / "docs", tmp_root / "docs")
            shutil.copytree(ROOT / "kyoko" / "assets", tmp_root / "kyoko" / "assets")

            bundled_source = (
                tmp_root
                / "kyoko/assets/source-events/hermes-news-research-minimal.json"
            )
            payload = json.loads(bundled_source.read_text())
            payload["profile"]["name"] = "Drifted fixture"
            bundled_source.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                ValidationError,
                "bundled asset does not mirror",
            ):
                validate_gate_artifacts(root=tmp_root)

    def test_hermes_operator_proposal_refs_resolve(self) -> None:
        paths = GateArtifactPaths.from_root(ROOT)
        ids = collect_ids(load_json(paths.source_fixture))
        proposal = load_json(paths.hermes_operator_proposal)

        self.assertEqual(missing_evidence_refs(proposal, ids), [])

    def test_openclaw_operator_proposal_refs_resolve(self) -> None:
        paths = GateArtifactPaths.from_root(ROOT)
        ids = collect_ids(load_json(paths.source_fixture))
        proposal = load_json(paths.openclaw_operator_proposal)

        self.assertEqual(missing_evidence_refs(proposal, ids), [])

    def test_valid_harness_proposal_refs_resolve(self) -> None:
        paths = GateArtifactPaths.from_root(ROOT)
        ids = collect_ids(load_json(paths.source_fixture))
        proposal = load_json(paths.valid_harness_proposal)

        self.assertEqual(missing_evidence_refs(proposal, ids), [])

    def test_valid_generated_file_harness_proposal_refs_resolve(self) -> None:
        paths = GateArtifactPaths.from_root(ROOT)
        ids = collect_ids(load_json(paths.source_fixture))
        proposal = load_json(paths.valid_generated_file_harness_proposal)

        self.assertEqual(missing_evidence_refs(proposal, ids), [])

    def test_invalid_fixture_has_expected_missing_span(self) -> None:
        paths = GateArtifactPaths.from_root(ROOT)
        ids = collect_ids(load_json(paths.source_fixture))
        proposal = load_json(paths.invalid_proposal)

        self.assertEqual(
            missing_evidence_refs(proposal, ids),
            ["span:span_does_not_exist_999", "span:span_does_not_exist_999"],
        )


if __name__ == "__main__":
    unittest.main()
