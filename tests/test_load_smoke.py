from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.load_smoke import LoadSmokeError, run_load_smoke


class LoadSmokeTests(unittest.TestCase):
    def test_run_load_smoke_measures_concurrent_dashboard_reads(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            report = run_load_smoke(
                db_path=db_path,
                run_count=6,
                spans_per_run=3,
                read_workers=2,
                read_iterations=2,
                expired_blob_count=2,
            )
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertEqual(payload["profile_id"], "profile_load_smoke")
            self.assertEqual(payload["status"]["counts"]["runs"], 6)
            self.assertEqual(payload["status"]["counts"]["spans"], 18)
            self.assertEqual(payload["status"]["counts"]["payload_blobs"], 2)
            self.assertEqual(payload["parameters"]["sample_run_id"], "run_load_0005")
            self.assertEqual(payload["errors"], [])
            self.assertGreaterEqual(payload["total_read_operations"], 2 * 2 * 10)
            self.assertGreater(payload["latency_ms"]["p95"], 0)
            self.assertIn("evidence_summary", payload["operation_latency_ms"])
            self.assertEqual(len(payload["retention_dry_run"]["pruned_blobs"]), 2)
            self.assertEqual(payload["wal_checkpoint"]["mode"], "PASSIVE")

    def test_run_load_smoke_can_reuse_existing_seeded_database(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            run_load_smoke(
                db_path=db_path,
                run_count=3,
                spans_per_run=2,
                read_workers=1,
                read_iterations=1,
                expired_blob_count=1,
            )

            report = run_load_smoke(
                db_path=db_path,
                profile_id="profile_load_smoke",
                seed=False,
                run_count=1,
                spans_per_run=1,
                read_workers=1,
                read_iterations=1,
                expired_blob_count=0,
            )

            self.assertTrue(report.passed)
            self.assertFalse(report.seeded)
            self.assertEqual(report.status["counts"]["runs"], 3)

    def test_run_load_smoke_rejects_invalid_sizes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(LoadSmokeError, "run_count_must_be_positive"):
                run_load_smoke(
                    db_path=Path(tmpdir) / "kyoko.db",
                    run_count=0,
                )


if __name__ == "__main__":
    unittest.main()
