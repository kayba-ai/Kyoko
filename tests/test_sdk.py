import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.request import urlopen

from kyoko.sdk import KyokoClient, KyokoRecorder
from kyoko.storage import get_database_status, ingest_source_payload
from kyoko.web import make_handler


class RunningServer:
    def __init__(self, db_path: Path) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(db_path))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "RunningServer":
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get_json(self, path: str) -> dict:
        with urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))


class SdkTests(unittest.TestCase):
    def test_recorder_builds_ingestable_source_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            recorder = KyokoRecorder(
                profile_id="profile_sdk_001",
                profile_name="SDK Workflow",
                root_path=tmpdir,
                agent_name="researcher",
                model="test-model",
            )

            with recorder.run("research topic", input_ref="blob_input") as run:
                with run.span("fetch_source", kind="tool", attributes={"url": "https://example.com"}):
                    pass
                run.summary = "completed with one tool call"

            payload = recorder.to_source_events()
            report = ingest_source_payload(
                db_path=db_path,
                fixture=payload,
                source_label="sdk-test",
            )
            status = get_database_status(db_path)

            self.assertEqual(report.profile_id, "profile_sdk_001")
            self.assertEqual(len(payload["runs"]), 1)
            self.assertEqual(len(payload["spans"]), 2)
            self.assertEqual(payload["runs"][0]["status"], "succeeded")
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 2)

    def test_recorder_marks_uncaught_span_exception_failed(self) -> None:
        recorder = KyokoRecorder(
            profile_id="profile_sdk_error_001",
            profile_name="SDK Error Workflow",
            root_path="/tmp/kyoko-sdk",
            agent_name="researcher",
        )

        with self.assertRaises(TimeoutError):
            with recorder.run("research topic") as run:
                with run.span("fetch_source", kind="tool"):
                    raise TimeoutError("source timed out")

        payload = recorder.to_source_events()
        failed_spans = [span for span in payload["spans"] if span["status"] == "failed"]

        self.assertEqual(payload["runs"][0]["status"], "failed")
        self.assertGreaterEqual(len(failed_spans), 1)
        self.assertEqual(failed_spans[0]["attributes_json"]["error_type"], "TimeoutError")
        self.assertEqual(payload["timeline_events"][0]["kind"], "span_failed")

    def test_recorder_writes_json_file(self) -> None:
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "source-events.json"
            recorder = KyokoRecorder(
                profile_id="profile_sdk_file_001",
                profile_name="SDK File Workflow",
                root_path=tmpdir,
            )

            with recorder.run("one run"):
                pass
            payload = recorder.write_json(output_path)

            written = json.loads(output_path.read_text())
            self.assertEqual(written["profile"]["id"], "profile_sdk_file_001")
            self.assertEqual(written["runs"][0]["id"], payload["runs"][0]["id"])

    def test_client_posts_source_events_to_local_api(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            recorder = KyokoRecorder(
                profile_id="profile_sdk_http_001",
                profile_name="SDK HTTP Workflow",
                root_path=tmpdir,
            )
            with recorder.run("http run"):
                pass

            with RunningServer(db_path) as server:
                response = KyokoClient(server.base_url).ingest(recorder.to_source_events())
                status = server.get_json("/api/status")

            self.assertEqual(response["profile_id"], "profile_sdk_http_001")
            self.assertTrue(response["delivered"])
            self.assertEqual(status["counts"]["runs"], 1)
            self.assertEqual(status["counts"]["spans"], 1)

    def test_client_ingest_is_best_effort_when_server_down(self) -> None:
        recorder = KyokoRecorder(
            profile_id="profile_sdk_offline_001",
            profile_name="SDK Offline Workflow",
            root_path=".",
        )
        with recorder.run("offline run"):
            pass

        # Port 9 (discard) is reliably not listening for HTTP.
        response = KyokoClient("http://127.0.0.1:9").ingest(recorder.to_source_events())
        self.assertFalse(response["delivered"])
        self.assertTrue(response["unreachable"])

    def test_client_ingest_strict_raises_when_server_down(self) -> None:
        from kyoko.sdk import KyokoSdkError

        recorder = KyokoRecorder(
            profile_id="profile_sdk_strict_001",
            profile_name="SDK Strict Workflow",
            root_path=".",
        )
        with recorder.run("strict run"):
            pass

        with self.assertRaises(KyokoSdkError):
            KyokoClient("http://127.0.0.1:9").ingest(
                recorder.to_source_events(), strict=True
            )


if __name__ == "__main__":
    unittest.main()
