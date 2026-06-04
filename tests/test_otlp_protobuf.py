import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from kyoko import storage
from kyoko.cli import main
from kyoko.otlp import _extract_spans
from kyoko.otlp_protobuf import (
    OtlpProtobufError,
    decode_export_trace_service_request as dec,
    encode_export_trace_service_request as enc,
    looks_like_protobuf,
)
from tests.test_web import RunningServer


def _full_variant_payload() -> dict:
    """An ExportTraceServiceRequest dict touching every AnyValue variant."""
    attributes = [
        {"key": "s", "value": {"stringValue": "hello"}},
        {"key": "i", "value": {"intValue": "42"}},
        {"key": "b", "value": {"boolValue": True}},
        {"key": "d", "value": {"doubleValue": 3.5}},
        {"key": "by", "value": {"bytesValue": "deadbeef"}},
        {
            "key": "arr",
            "value": {"arrayValue": {"values": [{"stringValue": "a"}, {"intValue": "7"}]}},
        },
        {
            "key": "kv",
            "value": {
                "kvlistValue": {
                    "values": [{"key": "inner", "value": {"boolValue": False}}]
                }
            },
        },
    ]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "svc"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "sc", "version": "1.0", "attributes": []},
                        "spans": [
                            {
                                "traceId": "11223344556677889900aabbccddeeff",
                                "spanId": "aabbccddeeff0011",
                                "parentSpanId": "",
                                "name": "invoke_agent r",
                                "kind": 2,
                                "startTimeUnixNano": 10,
                                "endTimeUnixNano": 20,
                                "status": {"code": 2, "message": "oops"},
                                "attributes": attributes,
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _genai_payload() -> dict:
    """Minimal gen_ai payload used by the ingest integration paths."""
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "pbsvc"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "t", "version": "", "attributes": []},
                        "spans": [
                            {
                                "traceId": "11223344556677889900aabbccddeeff",
                                "spanId": "aabbccddeeff0011",
                                "parentSpanId": "",
                                "name": "invoke_agent r",
                                "kind": 1,
                                "startTimeUnixNano": 1,
                                "endTimeUnixNano": 2,
                                "status": {"code": 1, "message": ""},
                                "attributes": [
                                    {
                                        "key": "gen_ai.operation.name",
                                        "value": {"stringValue": "invoke_agent"},
                                    },
                                    {
                                        "key": "gen_ai.usage.input_tokens",
                                        "value": {"intValue": "42"},
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }


class OtlpProtobufTests(unittest.TestCase):
    def test_round_trip_covers_all_any_value_variants(self) -> None:
        payload = _full_variant_payload()
        # decode(encode(payload)) reproduces the dict exactly across
        # string/int/bool/double/bytes/array/kvlist AnyValue variants.
        self.assertEqual(dec(enc(payload)), payload)

    def test_round_trip_gen_ai_payload(self) -> None:
        payload = _genai_payload()
        self.assertEqual(dec(enc(payload)), payload)

    def test_looks_like_protobuf_true_cases(self) -> None:
        self.assertTrue(looks_like_protobuf("application/x-protobuf"))
        self.assertTrue(looks_like_protobuf("application/protobuf"))
        # A charset parameter must not defeat the media-type match.
        self.assertTrue(looks_like_protobuf("application/x-protobuf; charset=utf-8"))

    def test_looks_like_protobuf_false_cases(self) -> None:
        self.assertFalse(looks_like_protobuf("application/json"))
        self.assertFalse(looks_like_protobuf(None))
        self.assertFalse(looks_like_protobuf(""))

    def test_decoded_dict_flows_through_json_extractor(self) -> None:
        spans = _extract_spans(dec(enc(_genai_payload())))
        self.assertEqual(spans[0]["trace_id"], "11223344556677889900aabbccddeeff")
        self.assertEqual(spans[0]["attributes"]["gen_ai.usage.input_tokens"], 42)

    def test_truncated_bytes_raise(self) -> None:
        with self.assertRaises(OtlpProtobufError):
            dec(b"\x0a\xff")

    def test_empty_input_yields_empty_resource_spans(self) -> None:
        self.assertEqual(dec(b""), {"resourceSpans": []})


class OtlpProtobufWebTests(unittest.TestCase):
    def test_post_protobuf_to_v1_traces(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            storage.initialize_database(db_path)
            body = enc(_genai_payload())
            with RunningServer(db_path) as server:
                request = Request(
                    f"{server.base_url}/v1/traces?profile_id=webpb",
                    data=body,
                    headers={"Content-Type": "application/x-protobuf"},
                    method="POST",
                )
                with urlopen(request, timeout=5) as response:
                    result = json.loads(response.read().decode("utf-8"))
            self.assertEqual(len(result["run_ids"]), 1)

    def test_bad_protobuf_body_returns_400(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            storage.initialize_database(db_path)
            with RunningServer(db_path) as server:
                request = Request(
                    f"{server.base_url}/v1/traces?profile_id=webpb",
                    data=b"\x0a\xff",
                    headers={"Content-Type": "application/x-protobuf"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as ctx:
                    urlopen(request, timeout=5)
                self.assertEqual(ctx.exception.code, 400)


class OtlpProtobufCliTests(unittest.TestCase):
    def test_ingest_otlp_autodetects_protobuf(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            pb_file = Path(tmpdir) / "trace.pb"
            pb_file.write_bytes(enc(_genai_payload()))
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "ingest-otlp",
                        str(pb_file),
                        "--profile-id",
                        "pb",
                        "--db",
                        str(db_path),
                        "--json",
                    ]
                )
            self.assertEqual(exit_code, 0)
            result = json.loads(buffer.getvalue())
            self.assertEqual(len(result["run_ids"]), 1)

    def test_ingest_otlp_with_explicit_protobuf_flag(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            pb_file = Path(tmpdir) / "trace.pb"
            pb_file.write_bytes(enc(_genai_payload()))
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "ingest-otlp",
                        str(pb_file),
                        "--protobuf",
                        "--profile-id",
                        "pb",
                        "--db",
                        str(db_path),
                        "--json",
                    ]
                )
            self.assertEqual(exit_code, 0)
            result = json.loads(buffer.getvalue())
            self.assertEqual(len(result["run_ids"]), 1)


if __name__ == "__main__":
    unittest.main()
