from __future__ import annotations

"""Stdlib-only OTLP/protobuf codec for the trace export service.

Kyoko's ingestion path (``kyoko/otlp.py``) consumes OTLP/JSON dicts. Some OTLP
exporters only speak the binary protobuf encoding (``Content-Type:
application/x-protobuf``). This module hand-rolls a protobuf wire decoder using
only the standard library (no ``protobuf`` package) and turns an
``ExportTraceServiceRequest`` message into the exact OTLP/JSON dict shape that
``kyoko/otlp.py`` already understands, so the same normalizer can be reused.

The shape produced by :func:`decode_export_trace_service_request` is::

    {"resourceSpans": [
      {"resource": {"attributes": [{"key": str, "value": <AnyValue>}, ...]},
       "scopeSpans": [
         {"scope": {"name": str, "version": str, "attributes": [...]},
          "spans": [
            {"traceId": <hex>, "spanId": <hex>, "parentSpanId": <hex or "">,
             "name": str, "kind": int,
             "startTimeUnixNano": int, "endTimeUnixNano": int,
             "status": {"code": int, "message": str},
             "attributes": [{"key": str, "value": <AnyValue>}, ...]}]}]}]}

where ``<AnyValue>`` is a dict using exactly one of the keys understood by
``kyoko.otlp._decode_otlp_value``: ``stringValue`` (str), ``boolValue`` (bool),
``intValue`` (int64 as a string, per OTLP/JSON), ``doubleValue`` (float),
``bytesValue`` (hex str), ``arrayValue`` (``{"values": [...]}``) or
``kvlistValue`` (``{"values": [{"key", "value"}...]}``).

The mirror :func:`encode_export_trace_service_request` re-encodes the same dict
shape back to wire bytes; it exists so tests can round-trip
``decode(encode(payload)) == payload``.
"""

import struct
from typing import Any, Optional

__all__ = [
    "OtlpProtobufError",
    "decode_export_trace_service_request",
    "encode_export_trace_service_request",
    "looks_like_protobuf",
]


class OtlpProtobufError(Exception):
    """Raised when OTLP protobuf bytes cannot be decoded into the JSON shape."""


# Wire types (protobuf encoding).
_WT_VARINT = 0
_WT_FIXED64 = 1
_WT_LEN = 2
_WT_FIXED32 = 5


# ---------------------------------------------------------------------------
# Low-level wire decoding
# ---------------------------------------------------------------------------


class _Reader:
    """Sequential reader over a protobuf-encoded byte buffer."""

    __slots__ = ("data", "pos", "end")

    def __init__(self, data: bytes, pos: int = 0, end: Optional[int] = None) -> None:
        self.data = data
        self.pos = pos
        self.end = len(data) if end is None else end

    def at_end(self) -> bool:
        return self.pos >= self.end

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            if self.pos >= self.end:
                raise OtlpProtobufError("truncated varint")
            byte = self.data[self.pos]
            self.pos += 1
            result |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return result
            shift += 7
            if shift > 63:
                raise OtlpProtobufError("varint too long")

    def read_tag(self) -> tuple[int, int]:
        tag = self.read_varint()
        field_number = tag >> 3
        wire_type = tag & 0x07
        if field_number == 0:
            raise OtlpProtobufError("invalid field number 0")
        return field_number, wire_type

    def read_len_delimited(self) -> bytes:
        length = self.read_varint()
        start = self.pos
        end = start + length
        if length < 0 or end > self.end:
            raise OtlpProtobufError("truncated length-delimited field")
        self.pos = end
        return self.data[start:end]

    def read_fixed64(self) -> bytes:
        start = self.pos
        end = start + 8
        if end > self.end:
            raise OtlpProtobufError("truncated fixed64 field")
        self.pos = end
        return self.data[start:end]

    def read_fixed32(self) -> bytes:
        start = self.pos
        end = start + 4
        if end > self.end:
            raise OtlpProtobufError("truncated fixed32 field")
        self.pos = end
        return self.data[start:end]

    def skip(self, wire_type: int) -> None:
        if wire_type == _WT_VARINT:
            self.read_varint()
        elif wire_type == _WT_FIXED64:
            self.read_fixed64()
        elif wire_type == _WT_LEN:
            self.read_len_delimited()
        elif wire_type == _WT_FIXED32:
            self.read_fixed32()
        else:
            raise OtlpProtobufError(f"unsupported wire type {wire_type}")


def _sub_reader(data: bytes) -> _Reader:
    return _Reader(data, 0, len(data))


def _decode_string(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:  # pragma: no cover - defensive
        raise OtlpProtobufError("invalid UTF-8 in string field") from exc


def _bytes_to_hex(data: bytes) -> str:
    return data.hex()


def _fixed64_to_uint(data: bytes) -> int:
    return struct.unpack("<Q", data)[0]


def _fixed64_to_double(data: bytes) -> float:
    return struct.unpack("<d", data)[0]


# ---------------------------------------------------------------------------
# Message decoders -> OTLP/JSON dict shape
# ---------------------------------------------------------------------------


def _decode_any_value(data: bytes) -> dict[str, Any]:
    """Decode an AnyValue (oneof) into the single-key JSON dict shape."""
    reader = _sub_reader(data)
    result: Optional[dict[str, Any]] = None
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # string_value
            result = {"stringValue": _decode_string(reader.read_len_delimited())}
        elif field == 2 and wire_type == _WT_VARINT:  # bool_value
            result = {"boolValue": bool(reader.read_varint())}
        elif field == 3 and wire_type == _WT_VARINT:  # int_value (int64)
            result = {"intValue": str(_to_signed64(reader.read_varint()))}
        elif field == 4 and wire_type == _WT_FIXED64:  # double_value
            result = {"doubleValue": _fixed64_to_double(reader.read_fixed64())}
        elif field == 5 and wire_type == _WT_LEN:  # array_value
            result = {"arrayValue": _decode_array_value(reader.read_len_delimited())}
        elif field == 6 and wire_type == _WT_LEN:  # kvlist_value
            result = {"kvlistValue": _decode_kvlist_value(reader.read_len_delimited())}
        elif field == 7 and wire_type == _WT_LEN:  # bytes_value
            result = {"bytesValue": _bytes_to_hex(reader.read_len_delimited())}
        else:
            reader.skip(wire_type)
    if result is None:
        # An AnyValue with no set field: default to an empty string per proto3.
        return {"stringValue": ""}
    return result


def _decode_array_value(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    values: list[Any] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # repeated AnyValue values
            values.append(_decode_any_value(reader.read_len_delimited()))
        else:
            reader.skip(wire_type)
    return {"values": values}


def _decode_kvlist_value(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    values: list[Any] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # repeated KeyValue values
            values.append(_decode_key_value(reader.read_len_delimited()))
        else:
            reader.skip(wire_type)
    return {"values": values}


def _decode_key_value(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    key = ""
    value: dict[str, Any] = {"stringValue": ""}
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # key
            key = _decode_string(reader.read_len_delimited())
        elif field == 2 and wire_type == _WT_LEN:  # value (AnyValue)
            value = _decode_any_value(reader.read_len_delimited())
        else:
            reader.skip(wire_type)
    return {"key": key, "value": value}


def _decode_attributes(reader: _Reader, wire_type: int, into: list[dict[str, Any]]) -> None:
    if wire_type != _WT_LEN:
        reader.skip(wire_type)
        return
    into.append(_decode_key_value(reader.read_len_delimited()))


def _decode_resource(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    attributes: list[dict[str, Any]] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1:  # attributes
            _decode_attributes(reader, wire_type, attributes)
        else:
            reader.skip(wire_type)
    return {"attributes": attributes}


def _decode_scope(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    name = ""
    version = ""
    attributes: list[dict[str, Any]] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # name
            name = _decode_string(reader.read_len_delimited())
        elif field == 2 and wire_type == _WT_LEN:  # version
            version = _decode_string(reader.read_len_delimited())
        elif field == 3:  # attributes
            _decode_attributes(reader, wire_type, attributes)
        else:
            reader.skip(wire_type)
    return {"name": name, "version": version, "attributes": attributes}


def _decode_status(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    message = ""
    code = 0
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 2 and wire_type == _WT_LEN:  # message
            message = _decode_string(reader.read_len_delimited())
        elif field == 3 and wire_type == _WT_VARINT:  # code
            code = reader.read_varint()
        else:
            reader.skip(wire_type)
    return {"code": code, "message": message}


def _decode_span(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    trace_id = ""
    span_id = ""
    parent_span_id = ""
    name = ""
    kind = 0
    start_time = 0
    end_time = 0
    status = {"code": 0, "message": ""}
    attributes: list[dict[str, Any]] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # trace_id
            trace_id = _bytes_to_hex(reader.read_len_delimited())
        elif field == 2 and wire_type == _WT_LEN:  # span_id
            span_id = _bytes_to_hex(reader.read_len_delimited())
        elif field == 4 and wire_type == _WT_LEN:  # parent_span_id
            parent_span_id = _bytes_to_hex(reader.read_len_delimited())
        elif field == 5 and wire_type == _WT_LEN:  # name
            name = _decode_string(reader.read_len_delimited())
        elif field == 6 and wire_type == _WT_VARINT:  # kind
            kind = reader.read_varint()
        elif field == 7 and wire_type == _WT_FIXED64:  # start_time_unix_nano
            start_time = _fixed64_to_uint(reader.read_fixed64())
        elif field == 8 and wire_type == _WT_FIXED64:  # end_time_unix_nano
            end_time = _fixed64_to_uint(reader.read_fixed64())
        elif field == 9:  # attributes
            _decode_attributes(reader, wire_type, attributes)
        elif field == 15 and wire_type == _WT_LEN:  # status
            status = _decode_status(reader.read_len_delimited())
        else:
            reader.skip(wire_type)
    return {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": start_time,
        "endTimeUnixNano": end_time,
        "status": status,
        "attributes": attributes,
    }


def _decode_scope_spans(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    scope: Optional[dict[str, Any]] = None
    spans: list[dict[str, Any]] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # scope
            scope = _decode_scope(reader.read_len_delimited())
        elif field == 2 and wire_type == _WT_LEN:  # spans
            spans.append(_decode_span(reader.read_len_delimited()))
        else:
            reader.skip(wire_type)
    if scope is None:
        scope = {"name": "", "version": "", "attributes": []}
    return {"scope": scope, "spans": spans}


def _decode_resource_spans(data: bytes) -> dict[str, Any]:
    reader = _sub_reader(data)
    resource: Optional[dict[str, Any]] = None
    scope_spans: list[dict[str, Any]] = []
    while not reader.at_end():
        field, wire_type = reader.read_tag()
        if field == 1 and wire_type == _WT_LEN:  # resource
            resource = _decode_resource(reader.read_len_delimited())
        elif field == 2 and wire_type == _WT_LEN:  # scope_spans
            scope_spans.append(_decode_scope_spans(reader.read_len_delimited()))
        else:
            reader.skip(wire_type)
    if resource is None:
        resource = {"attributes": []}
    return {"resource": resource, "scopeSpans": scope_spans}


def decode_export_trace_service_request(data: bytes) -> dict[str, Any]:
    """Decode binary OTLP ``ExportTraceServiceRequest`` into the OTLP/JSON dict.

    Raises :class:`OtlpProtobufError` on truncated or malformed input.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise OtlpProtobufError("input must be bytes")
    reader = _Reader(bytes(data))
    resource_spans: list[dict[str, Any]] = []
    try:
        while not reader.at_end():
            field, wire_type = reader.read_tag()
            if field == 1 and wire_type == _WT_LEN:  # resource_spans
                resource_spans.append(_decode_resource_spans(reader.read_len_delimited()))
            else:
                reader.skip(wire_type)
    except OtlpProtobufError:
        raise
    except (struct.error, IndexError, ValueError) as exc:
        raise OtlpProtobufError(f"malformed OTLP protobuf: {exc}") from exc
    return {"resourceSpans": resource_spans}


def _to_signed64(value: int) -> int:
    """Interpret an unsigned 64-bit varint as a two's-complement int64."""
    value &= (1 << 64) - 1
    if value >= 1 << 63:
        value -= 1 << 64
    return value


# ---------------------------------------------------------------------------
# Wire encoding (mirror, used for round-trip testing)
# ---------------------------------------------------------------------------


def _encode_varint(value: int) -> bytes:
    if value < 0:
        value &= (1 << 64) - 1
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _encode_tag(field_number: int, wire_type: int) -> bytes:
    return _encode_varint((field_number << 3) | wire_type)


def _encode_len_field(field_number: int, payload: bytes) -> bytes:
    return _encode_tag(field_number, _WT_LEN) + _encode_varint(len(payload)) + payload


def _encode_string_field(field_number: int, value: str) -> bytes:
    return _encode_len_field(field_number, value.encode("utf-8"))


def _encode_varint_field(field_number: int, value: int) -> bytes:
    return _encode_tag(field_number, _WT_VARINT) + _encode_varint(value)


def _encode_fixed64_uint_field(field_number: int, value: int) -> bytes:
    return _encode_tag(field_number, _WT_FIXED64) + struct.pack("<Q", value & ((1 << 64) - 1))


def _encode_fixed64_double_field(field_number: int, value: float) -> bytes:
    return _encode_tag(field_number, _WT_FIXED64) + struct.pack("<d", value)


def _hex_to_bytes(value: str) -> bytes:
    if not value:
        return b""
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise OtlpProtobufError(f"invalid hex string: {value!r}") from exc


def _encode_any_value(value: dict[str, Any]) -> bytes:
    if "stringValue" in value:
        return _encode_string_field(1, str(value["stringValue"]))
    if "boolValue" in value:
        return _encode_varint_field(2, 1 if value["boolValue"] else 0)
    if "intValue" in value:
        return _encode_varint_field(3, int(value["intValue"]))
    if "doubleValue" in value:
        return _encode_fixed64_double_field(4, float(value["doubleValue"]))
    if "arrayValue" in value:
        return _encode_len_field(5, _encode_array_value(value["arrayValue"]))
    if "kvlistValue" in value:
        return _encode_len_field(6, _encode_kvlist_value(value["kvlistValue"]))
    if "bytesValue" in value:
        return _encode_len_field(7, _hex_to_bytes(str(value["bytesValue"])))
    raise OtlpProtobufError(f"unsupported AnyValue: {value!r}")


def _encode_array_value(value: dict[str, Any]) -> bytes:
    out = bytearray()
    for item in value.get("values", []):
        out += _encode_len_field(1, _encode_any_value(item))
    return bytes(out)


def _encode_kvlist_value(value: dict[str, Any]) -> bytes:
    out = bytearray()
    for item in value.get("values", []):
        out += _encode_len_field(1, _encode_key_value(item))
    return bytes(out)


def _encode_key_value(kv: dict[str, Any]) -> bytes:
    out = bytearray()
    out += _encode_string_field(1, str(kv.get("key", "")))
    out += _encode_len_field(2, _encode_any_value(kv.get("value") or {"stringValue": ""}))
    return bytes(out)


def _encode_attributes(field_number: int, attributes: list[dict[str, Any]]) -> bytes:
    out = bytearray()
    for kv in attributes or []:
        out += _encode_len_field(field_number, _encode_key_value(kv))
    return bytes(out)


def _encode_resource(resource: dict[str, Any]) -> bytes:
    return _encode_attributes(1, resource.get("attributes", []))


def _encode_scope(scope: dict[str, Any]) -> bytes:
    out = bytearray()
    out += _encode_string_field(1, str(scope.get("name", "")))
    out += _encode_string_field(2, str(scope.get("version", "")))
    out += _encode_attributes(3, scope.get("attributes", []))
    return bytes(out)


def _encode_status(status: dict[str, Any]) -> bytes:
    out = bytearray()
    out += _encode_string_field(2, str(status.get("message", "")))
    out += _encode_varint_field(3, int(status.get("code", 0)))
    return bytes(out)


def _encode_span(span: dict[str, Any]) -> bytes:
    out = bytearray()
    out += _encode_len_field(1, _hex_to_bytes(str(span.get("traceId", ""))))
    out += _encode_len_field(2, _hex_to_bytes(str(span.get("spanId", ""))))
    out += _encode_len_field(4, _hex_to_bytes(str(span.get("parentSpanId", "") or "")))
    out += _encode_string_field(5, str(span.get("name", "")))
    out += _encode_varint_field(6, int(span.get("kind", 0)))
    out += _encode_fixed64_uint_field(7, int(span.get("startTimeUnixNano", 0)))
    out += _encode_fixed64_uint_field(8, int(span.get("endTimeUnixNano", 0)))
    out += _encode_attributes(9, span.get("attributes", []))
    out += _encode_len_field(15, _encode_status(span.get("status") or {"code": 0, "message": ""}))
    return bytes(out)


def _encode_scope_spans(scope_spans: dict[str, Any]) -> bytes:
    out = bytearray()
    out += _encode_len_field(1, _encode_scope(scope_spans.get("scope") or {}))
    for span in scope_spans.get("spans", []):
        out += _encode_len_field(2, _encode_span(span))
    return bytes(out)


def _encode_resource_spans(resource_spans: dict[str, Any]) -> bytes:
    out = bytearray()
    out += _encode_len_field(1, _encode_resource(resource_spans.get("resource") or {"attributes": []}))
    for scope_spans in resource_spans.get("scopeSpans", []):
        out += _encode_len_field(2, _encode_scope_spans(scope_spans))
    return bytes(out)


def encode_export_trace_service_request(payload: dict[str, Any]) -> bytes:
    """Encode the OTLP/JSON dict shape back into wire bytes (test helper)."""
    if not isinstance(payload, dict):
        raise OtlpProtobufError("payload must be a dict")
    out = bytearray()
    for resource_spans in payload.get("resourceSpans", []):
        out += _encode_len_field(1, _encode_resource_spans(resource_spans))
    return bytes(out)


# ---------------------------------------------------------------------------
# Content-type sniffing
# ---------------------------------------------------------------------------


def looks_like_protobuf(content_type: Optional[str]) -> bool:
    """Return True when ``content_type``'s media type is an OTLP protobuf type."""
    if not content_type:
        return False
    media_type = content_type.split(";", 1)[0].strip().lower()
    return media_type in {"application/x-protobuf", "application/protobuf"}
