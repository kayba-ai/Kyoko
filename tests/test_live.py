import io
import json
import queue
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.request import Request, urlopen

from kyoko import live
from kyoko.cli import main
from kyoko.storage import ingest_source_fixture
from tests.test_web import RunningServer

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"


def _seed(db_path: Path) -> str:
    report = ingest_source_fixture(db_path, FIXTURE)
    return report.profile_id


class LiveBusTests(unittest.TestCase):
    def test_publish_delivers_to_subscribers(self) -> None:
        bus = live.LiveBus()
        sub = bus.subscribe()
        bus.publish(live.EVENT_LIVE, {"hello": "world"})
        message = sub.get_nowait()
        self.assertEqual(message["event"], live.EVENT_LIVE)
        self.assertEqual(message["data"], {"hello": "world"})

    def test_unsubscribe_stops_delivery(self) -> None:
        bus = live.LiveBus()
        sub = bus.subscribe()
        bus.unsubscribe(sub)
        bus.publish(live.EVENT_LIVE, {"x": 1})
        with self.assertRaises(queue.Empty):
            sub.get_nowait()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_overflow_drops_oldest(self) -> None:
        bus = live.LiveBus(max_queue=2)
        sub = bus.subscribe()
        for index in range(5):
            bus.publish(live.EVENT_LIVE, {"i": index})
        drained = []
        while True:
            try:
                drained.append(sub.get_nowait()["data"]["i"])
            except queue.Empty:
                break
        # Bounded queue keeps only the most recent two events.
        self.assertEqual(drained, [3, 4])


class LiveIngestTests(unittest.TestCase):
    def test_ingest_assigns_monotonic_seq_per_run(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id = _seed(db_path)
            first = live.ingest_live_event(
                db_path=db_path, kind="token", run_id="run_a", content="a", profile_id=profile_id
            )
            second = live.ingest_live_event(
                db_path=db_path, kind="token", run_id="run_a", content="b", profile_id=profile_id
            )
            other = live.ingest_live_event(
                db_path=db_path, kind="token", run_id="run_b", content="c", profile_id=profile_id
            )
            self.assertEqual((first["seq"], second["seq"]), (1, 2))
            self.assertEqual(other["seq"], 1)

    def test_ingest_redacts_sensitive_values(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id = _seed(db_path)
            record = live.ingest_live_event(
                db_path=db_path,
                kind="tool_start",
                run_id="run_a",
                content={"api_key": "SECRET", "q": "news"},
                profile_id=profile_id,
            )
            self.assertIn("[REDACTED", record["content_preview"])
            self.assertNotIn("SECRET", record["content_preview"])

    def test_ingest_truncates_oversized_content(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id = _seed(db_path)
            record = live.ingest_live_event(
                db_path=db_path,
                kind="message",
                run_id="run_a",
                content="x" * (live.PREVIEW_MAX_CHARS + 100),
                profile_id=profile_id,
            )
            self.assertTrue(record["content_truncated"])
            self.assertEqual(len(record["content_preview"]), live.PREVIEW_MAX_CHARS)

    def test_unknown_kind_coerced_to_other(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id = _seed(db_path)
            record = live.ingest_live_event(
                db_path=db_path, kind="bogus", run_id="run_a", content="x", profile_id=profile_id
            )
            self.assertEqual(record["kind"], "other")

    def test_missing_profile_raises(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            with self.assertRaises(live.LiveError):
                live.ingest_live_event(db_path=db_path, kind="token", run_id="r", content="x")

    def test_list_filters_by_kind_and_after_seq(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id = _seed(db_path)
            live.ingest_live_events(
                db_path=db_path,
                profile_id=profile_id,
                events=[
                    {"kind": "token", "run_id": "run_a", "content": "a"},
                    {"kind": "tool_start", "run_id": "run_a", "content": "b"},
                    {"kind": "token", "run_id": "run_a", "content": "c"},
                ],
            )
            tokens = live.list_live_events(db_path=db_path, run_id="run_a", kinds=["token"])
            self.assertEqual([e["kind"] for e in tokens], ["token", "token"])
            after = live.list_live_events(db_path=db_path, run_id="run_a", after_seq=1)
            self.assertEqual([e["seq"] for e in after], [2, 3])


class LiveCliTests(unittest.TestCase):
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(argv)
        return code, buffer.getvalue()

    def test_ingest_live_and_live_tail_roundtrip(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            profile_id = _seed(db_path)
            payload = Path(tmpdir) / "events.json"
            payload.write_text(
                json.dumps(
                    {
                        "events": [
                            {"kind": "token", "run_id": "run_a", "content": "Hello "},
                            {"kind": "token", "run_id": "run_a", "content": "world"},
                        ]
                    }
                )
            )
            code, out = self._run(
                ["ingest-live", "--db", str(db_path), str(payload), "--profile-id", profile_id, "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["ingested_count"], 2)

            code, out = self._run(["live-tail", "run_a", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)
            events = json.loads(out)["events"]
            self.assertEqual([e["content_preview"] for e in events], ["Hello ", "world"])

    def test_live_tail_text_output_when_empty(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            code, out = self._run(["live-tail", "missing_run", "--db", str(db_path)])
            self.assertEqual(code, 0)
            self.assertIn("(no live events)", out)


class LiveWebTests(unittest.TestCase):
    def test_post_live_and_query(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            with RunningServer(db_path) as server:
                posted = server.post_json(
                    "/v1/live", {"kind": "token", "run_id": "run_a", "content": "Hi"}
                )
                self.assertEqual(posted["ingested_count"], 1)
                listed = server.get_json("/api/live-events?run_id=run_a")
                self.assertEqual([e["kind"] for e in listed["events"]], ["token"])

    def test_post_live_rejects_non_list_events(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            with RunningServer(db_path) as server:
                from urllib.error import HTTPError

                request = Request(
                    f"{server.base_url}/v1/live",
                    data=json.dumps({"events": "nope"}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(request, timeout=5)
                self.assertEqual(ctx.exception.code, 400)

    def test_sse_stream_receives_live_event(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _seed(db_path)
            with RunningServer(db_path) as server:
                seen: list[str] = []

                def reader() -> None:
                    request = Request(f"{server.base_url}/api/events/stream")
                    with urlopen(request, timeout=5) as response:
                        deadline = time.time() + 3
                        while time.time() < deadline:
                            chunk = response.read(64)
                            if not chunk:
                                break
                            seen.append(chunk.decode("utf-8", "replace"))
                            if any("event: live_event" in part for part in seen):
                                break

                thread = Thread(target=reader, daemon=True)
                thread.start()
                time.sleep(0.4)
                server.post_json("/v1/live", {"kind": "token", "run_id": "run_a", "content": "Hi"})
                thread.join(timeout=4)

                joined = "".join(seen)
                self.assertIn(": connected", joined)
                self.assertIn("event: live_event", joined)


if __name__ == "__main__":
    unittest.main()
