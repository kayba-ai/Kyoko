from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.blobs import (
    list_payload_blobs,
    prune_payload_blobs,
    put_blob,
    retained_until_for_days,
    storage_report,
)
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


class BlobTests(unittest.TestCase):
    def test_put_blob_registers_content_addressed_payload(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            ingest_source_fixture(db_path, FIXTURE)

            report = put_blob(
                db_path=db_path,
                data=b'{"token":"redacted"}',
                kind="operator_output",
                media_type="application/json",
                profile_id="profile_news_research_001",
                metadata={"source": "test"},
            )
            rows = list_payload_blobs(db_path)
            status = get_database_status(db_path)
            store_report = storage_report(db_path)

            self.assertTrue(report.path.exists())
            self.assertTrue(report.created)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], report.blob_id)
            self.assertEqual(rows[0]["profile_id"], "profile_news_research_001")
            self.assertEqual(rows[0]["metadata"], {"source": "test"})
            self.assertEqual(rows[0]["preview"], "[REDACTED:blob_preview]")
            self.assertEqual(status.counts["payload_blobs"], 1)
            self.assertEqual(store_report.registered_blobs, 1)
            self.assertEqual(store_report.registered_blob_bytes, report.size_bytes)
            self.assertEqual(store_report.missing_blobs, ())

    def test_unredacted_blob_preview_is_explicit_opt_in(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"

            report = put_blob(
                db_path=db_path,
                data=b"debug payload",
                kind="debug_payload",
                media_type="text/plain",
                redaction_mode="unredacted",
            )
            rows = list_payload_blobs(db_path)

            self.assertEqual(rows[0]["id"], report.blob_id)
            self.assertEqual(rows[0]["redaction_mode"], "unredacted")
            self.assertEqual(rows[0]["preview"], "debug payload")

    def test_storage_report_finds_orphan_and_missing_blob_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            report = put_blob(db_path=db_path, data=b"payload", media_type="text/plain")
            report.path.unlink()
            orphan = db_path.parent / "blobs" / "orphan.txt"
            orphan.parent.mkdir(parents=True, exist_ok=True)
            orphan.write_text("orphan")

            store_report = storage_report(db_path)

            self.assertEqual(store_report.missing_blobs[0]["blob_id"], report.blob_id)
            self.assertEqual(store_report.orphan_files[0]["path"], str(orphan))

    def test_prune_blobs_dry_run_and_apply(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            now = datetime(2026, 6, 1, tzinfo=timezone.utc)
            retained_until = retained_until_for_days(0, now=now - timedelta(days=1))
            report = put_blob(
                db_path=db_path,
                data=b"expired payload",
                media_type="text/plain",
                retained_until=retained_until,
            )

            dry_run = prune_payload_blobs(db_path, dry_run=True, now=now)
            self.assertEqual(len(dry_run.pruned_blobs), 1)
            self.assertTrue(report.path.exists())
            self.assertEqual(len(list_payload_blobs(db_path)), 1)

            applied = prune_payload_blobs(db_path, dry_run=False, now=now)
            self.assertEqual(len(applied.pruned_blobs), 1)
            self.assertFalse(report.path.exists())
            self.assertEqual(list_payload_blobs(db_path), [])


if __name__ == "__main__":
    unittest.main()
