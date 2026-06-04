import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.otlp import ingest_otlp_json, ingest_otlp_payload, normalize_otlp_json
from kyoko.otlp_smoke import run_opentelemetry_sdk_smoke
from kyoko.storage import get_database_status


ROOT = Path(__file__).resolve().parents[1]
OTLP_FIXTURE = ROOT / "docs/fixtures/source-events/otlp-genai-minimal.json"


class OtlpTests(unittest.TestCase):
    def test_normalize_otlp_genai_spans_to_canonical_source_events(self) -> None:
        payload = json.loads(OTLP_FIXTURE.read_text())

        normalized = normalize_otlp_json(
            payload,
            profile_id="profile_otlp_news_001",
            profile_name="OTLP News",
            root_path="/tmp/kyoko-otlp",
            source_kind="pydantic_ai",
            source_name="Pydantic AI OTel",
        )

        self.assertEqual(normalized["profile"]["id"], "profile_otlp_news_001")
        self.assertEqual(normalized["sources"][0]["kind"], "pydantic_ai")
        self.assertEqual(len(normalized["agent_identities"]), 1)
        self.assertEqual(len(normalized["runs"]), 1)
        self.assertEqual(len(normalized["spans"]), 2)
        self.assertEqual(normalized["spans"][0]["kind"], "agent")
        self.assertEqual(normalized["spans"][1]["kind"], "tool")
        self.assertEqual(normalized["spans"][1]["status"], "failed")
        self.assertEqual(normalized["spans"][1]["attributes_json"]["error.type"], "timeout")
        self.assertEqual(normalized["timeline_events"][0]["kind"], "span_failed")

    def test_ingest_otlp_json_persists_normalized_trace(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            normalized_path = Path(tmpdir) / "normalized.json"

            report = ingest_otlp_json(
                db_path=db_path,
                payload_path=OTLP_FIXTURE,
                profile_id="profile_otlp_news_001",
                profile_name="OTLP News",
                root_path=tmpdir,
                source_kind="otlp_http",
                source_name="OTLP JSON",
                output_path=normalized_path,
            )
            status = get_database_status(db_path)
            normalized = json.loads(normalized_path.read_text())

            self.assertEqual(report.profile_id, "profile_otlp_news_001")
            self.assertEqual(len(report.run_ids), 1)
            self.assertEqual(len(report.span_ids), 2)
            self.assertTrue(normalized_path.exists())
            self.assertEqual(normalized["spans"][1]["status"], "failed")
            self.assertEqual(status.counts["profiles"], 1)
            self.assertEqual(status.counts["sources"], 1)
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 2)
            self.assertEqual(status.counts["timeline_events"], 1)

    def test_ingest_otlp_payload_infers_profile_from_service_name(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            payload = json.loads(OTLP_FIXTURE.read_text())

            report = ingest_otlp_payload(
                db_path=db_path,
                payload=payload,
                source_label="POST /v1/traces",
            )
            status = get_database_status(db_path)

            self.assertEqual(report.profile_id, "profile_otlp_news_research_agent")
            self.assertEqual(status.counts["runs"], 1)
            self.assertEqual(status.counts["spans"], 2)

    def test_flat_spans_shape_is_supported(self) -> None:
        payload = {
            "spans": [
                {
                    "trace_id": "trace-1",
                    "span_id": "span-root",
                    "name": "invoke_agent planner",
                    "started_at": "2026-10-01T09:00:00Z",
                    "ended_at": "2026-10-01T09:01:00Z",
                    "attributes": {
                        "gen_ai.operation.name": "invoke_agent",
                        "gen_ai.agent.name": "planner",
                    },
                }
            ]
        }

        normalized = normalize_otlp_json(
            payload,
            profile_id="profile_flat_001",
        )

        self.assertEqual(normalized["spans"][0]["kind"], "agent")
        self.assertEqual(normalized["runs"][0]["status"], "succeeded")

    def test_opentelemetry_sdk_smoke_runs_sdk_and_ingests_otlp(self) -> None:
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "opentelemetry-smoke"
            _write_fake_opentelemetry_package(output_dir)

            report = run_opentelemetry_sdk_smoke(
                db_path=root / "kyoko.db",
                output_dir=output_dir,
                python_executable=Path(sys.executable),
                timeout_seconds=10,
            )
            normalized = json.loads(report.normalized_path.read_text(encoding="utf-8"))

            self.assertTrue(report.passed)
            self.assertEqual(report.opentelemetry_sdk_version, "9.9.0")
            self.assertTrue(report.opentelemetry_sdk_invoked)
            self.assertEqual(report.ingest.profile_id, "profile_opentelemetry_sdk_smoke")
            self.assertEqual(len(report.ingest.run_ids), 1)
            self.assertEqual(len(report.ingest.span_ids), 2)
            self.assertEqual(report.ingest.ingested_counts["timeline_events"], 1)
            self.assertTrue(report.otlp_payload_path.exists())
            self.assertTrue(report.normalized_path.exists())
            self.assertEqual(normalized["spans"][1]["kind"], "tool")
            self.assertEqual(normalized["spans"][1]["status"], "failed")


def _write_fake_opentelemetry_package(root: Path) -> None:
    package_root = root / "opentelemetry"
    (package_root / "sdk" / "resources").mkdir(parents=True, exist_ok=True)
    (package_root / "sdk" / "trace" / "export").mkdir(parents=True, exist_ok=True)
    (package_root / "trace").mkdir(parents=True, exist_ok=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "sdk" / "__init__.py").write_text("", encoding="utf-8")
    (package_root / "sdk" / "resources" / "__init__.py").write_text(
        """
class Resource:
    def __init__(self, attributes):
        self.attributes = dict(attributes or {})

    @classmethod
    def create(cls, attributes):
        return cls(attributes)
""".lstrip(),
        encoding="utf-8",
    )
    (package_root / "trace" / "__init__.py").write_text(
        """
class _EnumValue:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return self.name


class SpanKind:
    INTERNAL = _EnumValue("INTERNAL")


class StatusCode:
    OK = _EnumValue("OK")
    ERROR = _EnumValue("ERROR")
    UNSET = _EnumValue("UNSET")


class Status:
    def __init__(self, status_code=StatusCode.UNSET, description=""):
        self.status_code = status_code
        self.description = description


_provider = None


def set_tracer_provider(provider):
    global _provider
    _provider = provider


def get_tracer(name):
    if _provider is None:
        raise RuntimeError("fake tracer provider not set")
    return _provider.get_tracer(name)
""".lstrip(),
        encoding="utf-8",
    )
    (package_root / "sdk" / "trace" / "export" / "__init__.py").write_text(
        """
class SpanExportResult:
    SUCCESS = "SUCCESS"


class SpanExporter:
    def export(self, spans):
        raise NotImplementedError

    def shutdown(self):
        return None


class SimpleSpanProcessor:
    def __init__(self, exporter):
        self.exporter = exporter

    def on_end(self, span):
        self.exporter.export([span])

    def force_flush(self):
        return True
""".lstrip(),
        encoding="utf-8",
    )
    (package_root / "sdk" / "trace" / "__init__.py").write_text(
        """
from opentelemetry.trace import Status, StatusCode

__version__ = "9.9.0"
_active_spans = []
_span_counter = 0


class SpanContext:
    def __init__(self, trace_id, span_id):
        self.trace_id = trace_id
        self.span_id = span_id


class FakeSpan:
    def __init__(self, provider, name, kind=None, attributes=None):
        global _span_counter
        _span_counter += 1
        parent = _active_spans[-1] if _active_spans else None
        trace_id = parent.context.trace_id if parent is not None else 0x1234
        self.context = SpanContext(trace_id, _span_counter)
        self.parent = parent.context if parent is not None else None
        self.name = name
        self.kind = kind
        self.attributes = dict(attributes or {})
        self.status = Status(StatusCode.UNSET, "")
        self.start_time = 1700000000000000000 + (_span_counter * 1000)
        self.end_time = self.start_time
        self._provider = provider

    def set_status(self, status):
        self.status = status


class _SpanManager:
    def __init__(self, span):
        self.span = span

    def __enter__(self):
        _active_spans.append(self.span)
        return self.span

    def __exit__(self, exc_type, exc, tb):
        if exc_type is not None:
            self.span.set_status(Status(StatusCode.ERROR, str(exc)))
        self.span.end_time = self.span.start_time + 500
        _active_spans.pop()
        for processor in self.span._provider._processors:
            processor.on_end(self.span)
        return False


class Tracer:
    def __init__(self, provider):
        self.provider = provider

    def start_as_current_span(self, name, kind=None, attributes=None):
        return _SpanManager(FakeSpan(self.provider, name, kind=kind, attributes=attributes))


class TracerProvider:
    def __init__(self, resource=None):
        self.resource = resource
        self._processors = []

    def add_span_processor(self, processor):
        self._processors.append(processor)

    def get_tracer(self, name):
        return Tracer(self)

    def force_flush(self):
        for processor in self._processors:
            force_flush = getattr(processor, "force_flush", None)
            if force_flush:
                force_flush()
        return True
""".lstrip(),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
