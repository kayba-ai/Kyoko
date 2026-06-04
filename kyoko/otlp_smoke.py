from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .otlp import OtlpIngestReport, OtlpNormalizeError, ingest_otlp_json
from .storage import StorageError, get_database_status, initialize_database, status_to_json


DEFAULT_OPENTELEMETRY_PROFILE_ID = "profile_opentelemetry_sdk_smoke"
DEFAULT_OPENTELEMETRY_PROFILE_NAME = "OpenTelemetry SDK Smoke"
DEFAULT_OPENTELEMETRY_SOURCE_KIND = "otlp_http"
DEFAULT_OPENTELEMETRY_SOURCE_NAME = "OpenTelemetry Python SDK"


class OtlpSmokeError(Exception):
    """Raised when the OpenTelemetry SDK smoke cannot complete."""


@dataclass(frozen=True)
class OpenTelemetrySdkSmokeReport:
    python_executable: Path
    opentelemetry_sdk_version: str
    db_path: Path
    output_dir: Path
    workspace_root: Path
    script_path: Path
    otlp_payload_path: Path
    normalized_path: Path
    stdout_path: Path
    stderr_path: Path
    exit_code: int
    ingest: OtlpIngestReport
    status: dict[str, Any]
    opentelemetry_sdk_invoked: bool
    passed: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "opentelemetry_python_smoke",
            "python_executable": str(self.python_executable),
            "opentelemetry_sdk_version": self.opentelemetry_sdk_version,
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "workspace_root": str(self.workspace_root),
            "script_path": str(self.script_path),
            "otlp_payload_path": str(self.otlp_payload_path),
            "normalized_path": str(self.normalized_path),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "exit_code": self.exit_code,
            "profile_id": self.ingest.profile_id,
            "run_ids": list(self.ingest.run_ids),
            "span_ids": list(self.ingest.span_ids),
            "ingested_counts": self.ingest.ingested_counts,
            "status": self.status,
            "opentelemetry_sdk_invoked": self.opentelemetry_sdk_invoked,
            "external_model_invoked": False,
            "live_operator_invoked": False,
            "passed": self.passed,
        }


def run_opentelemetry_sdk_smoke(
    *,
    db_path: Path,
    python_executable: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    timeout_seconds: int = 30,
) -> OpenTelemetrySdkSmokeReport:
    if timeout_seconds <= 0:
        raise OtlpSmokeError("timeout_seconds_must_be_positive")

    selected_python = _resolve_python_executable(python_executable)
    selected_output_dir = (
        output_dir if output_dir is not None else Path(tempfile.mkdtemp(prefix="kyoko-otlp-sdk-smoke-"))
    ).resolve()
    selected_output_dir.mkdir(parents=True, exist_ok=True)
    workspace_root = selected_output_dir / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    script_path = selected_output_dir / "opentelemetry_sdk_smoke.py"
    otlp_payload_path = selected_output_dir / "otlp-payload.json"
    normalized_path = selected_output_dir / "normalized-source-events.json"
    stdout_path = selected_output_dir / "opentelemetry-sdk.stdout.txt"
    stderr_path = selected_output_dir / "opentelemetry-sdk.stderr.txt"

    try:
        sdk_version = _opentelemetry_sdk_version(
            python_executable=selected_python,
            cwd=selected_output_dir,
            timeout_seconds=timeout_seconds,
        )
        initialize_database(db_path)
        script_path.write_text(OPENTELEMETRY_SDK_SMOKE_SCRIPT, encoding="utf-8")
        completed = subprocess.run(
            [
                str(selected_python),
                str(script_path),
                "--output",
                str(otlp_payload_path),
                "--workspace-root",
                str(workspace_root),
                "--sdk-version",
                sdk_version,
            ],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(selected_output_dir),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise OtlpSmokeError(f"opentelemetry_sdk_smoke_timeout:{timeout_seconds}") from exc
    except OSError as exc:
        raise OtlpSmokeError(f"opentelemetry_sdk_smoke_failed_to_start:{exc}") from exc

    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise OtlpSmokeError(f"opentelemetry_sdk_smoke_failed:{completed.returncode}:{stderr_path}")
    if not otlp_payload_path.exists():
        raise OtlpSmokeError(f"opentelemetry_sdk_payload_missing:{otlp_payload_path}")

    try:
        ingest = ingest_otlp_json(
            db_path=db_path,
            payload_path=otlp_payload_path,
            profile_id=DEFAULT_OPENTELEMETRY_PROFILE_ID,
            profile_name=DEFAULT_OPENTELEMETRY_PROFILE_NAME,
            root_path=str(workspace_root),
            source_kind=DEFAULT_OPENTELEMETRY_SOURCE_KIND,
            source_name=DEFAULT_OPENTELEMETRY_SOURCE_NAME,
            output_path=normalized_path,
        )
    except (OtlpNormalizeError, StorageError) as exc:
        raise OtlpSmokeError(str(exc)) from exc

    payload = _load_json(otlp_payload_path)
    invoked = _payload_marks_opentelemetry_sdk(payload)
    status = status_to_json(get_database_status(db_path))
    passed = (
        invoked
        and completed.returncode == 0
        and len(ingest.run_ids) == 1
        and len(ingest.span_ids) >= 2
        and status["counts"].get("runs", 0) >= 1
        and status["counts"].get("spans", 0) >= 2
        and status["counts"].get("timeline_events", 0) >= 1
    )
    return OpenTelemetrySdkSmokeReport(
        python_executable=selected_python,
        opentelemetry_sdk_version=sdk_version,
        db_path=db_path,
        output_dir=selected_output_dir,
        workspace_root=workspace_root,
        script_path=script_path,
        otlp_payload_path=otlp_payload_path,
        normalized_path=normalized_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        exit_code=completed.returncode,
        ingest=ingest,
        status=status,
        opentelemetry_sdk_invoked=invoked,
        passed=passed,
    )


def _resolve_python_executable(python_executable: Optional[Path]) -> Path:
    selected = python_executable if python_executable is not None else Path(sys.executable)
    if selected.exists():
        return selected
    resolved = shutil.which(str(selected))
    if resolved is not None:
        return Path(resolved)
    raise OtlpSmokeError(f"python_executable_not_found:{selected}")


def _opentelemetry_sdk_version(
    *,
    python_executable: Path,
    cwd: Path,
    timeout_seconds: int,
) -> str:
    code = (
        "import importlib.metadata as metadata\n"
        "import opentelemetry.sdk.trace\n"
        "try:\n"
        "    version = metadata.version('opentelemetry-sdk')\n"
        "except metadata.PackageNotFoundError:\n"
        "    version = getattr(opentelemetry.sdk.trace, '__version__', 'unknown')\n"
        "print(version)\n"
    )
    try:
        completed = subprocess.run(
            [str(python_executable), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise OtlpSmokeError("opentelemetry_sdk_package_check_timeout") from exc
    except OSError as exc:
        raise OtlpSmokeError(f"opentelemetry_sdk_package_check_failed_to_start:{exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or str(completed.returncode)
        raise OtlpSmokeError(f"opentelemetry_sdk_not_importable:{detail}")
    version = completed.stdout.strip()
    if not version:
        raise OtlpSmokeError("opentelemetry_sdk_version_missing")
    return version


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OtlpSmokeError(f"opentelemetry_sdk_payload_invalid_json:{path}") from exc
    if not isinstance(payload, dict):
        raise OtlpSmokeError("opentelemetry_sdk_payload_must_be_object")
    return payload


def _payload_marks_opentelemetry_sdk(payload: dict[str, Any]) -> bool:
    for resource_span in payload.get("resourceSpans", []):
        if not isinstance(resource_span, dict):
            continue
        resource = resource_span.get("resource")
        if not isinstance(resource, dict):
            continue
        attrs = _attrs(resource.get("attributes", []))
        if (
            attrs.get("telemetry.sdk.name") == "opentelemetry"
            and attrs.get("kyoko.smoke.opentelemetry_sdk_invoked") is True
        ):
            return True
    return False


def _attrs(items: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if not isinstance(items, list):
        return values
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, dict):
            values[key] = _value(value)
    return values


def _value(value: dict[str, Any]) -> Any:
    for field in ("stringValue", "boolValue", "intValue", "doubleValue"):
        if field in value:
            return value[field]
    return None


OPENTELEMETRY_SDK_SMOKE_SCRIPT = r'''
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import SpanKind, Status, StatusCode


class JsonSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.spans: list[Any] = []

    def export(self, spans: list[Any]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Kyoko OpenTelemetry SDK smoke")
    parser.add_argument("--output", required=True)
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--sdk-version", required=True)
    args = parser.parse_args()

    resource = Resource.create(
        {
            "service.name": "kyoko-opentelemetry-sdk-smoke",
            "service.namespace": "profile_opentelemetry_sdk_smoke",
            "telemetry.sdk.name": "opentelemetry",
            "kyoko.profile.id": "profile_opentelemetry_sdk_smoke",
            "kyoko.profile.name": "OpenTelemetry SDK Smoke",
            "kyoko.root_path": args.workspace_root,
            "kyoko.smoke.opentelemetry_sdk_invoked": True,
            "kyoko.smoke.opentelemetry_sdk_version": args.sdk_version,
        }
    )
    exporter = JsonSpanExporter()
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("kyoko.opentelemetry_sdk_smoke")

    with tracer.start_as_current_span(
        "invoke_agent researcher",
        kind=SpanKind.INTERNAL,
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "researcher",
            "gen_ai.request.model": "local-test-model",
            "kyoko.smoke.opentelemetry_sdk_invoked": True,
        },
    ):
        with tracer.start_as_current_span(
            "execute_tool fetch_source",
            kind=SpanKind.INTERNAL,
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "fetch_source",
                "error.type": "timeout",
                "kyoko.smoke.opentelemetry_sdk_invoked": True,
            },
        ) as span:
            span.set_status(Status(StatusCode.ERROR, "source timed out"))

    provider.force_flush()
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": attributes_to_otlp(resource.attributes)},
                "scopeSpans": [
                    {
                        "scope": {"name": "kyoko.opentelemetry_sdk_smoke"},
                        "spans": [span_to_otlp(span) for span in exporter.spans],
                    }
                ],
            }
        ]
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"opentelemetry_sdk_invoked": True, "span_count": len(exporter.spans)}, sort_keys=True))
    return 0


def span_to_otlp(span: Any) -> dict[str, Any]:
    parent_span_id = None
    parent = getattr(span, "parent", None)
    if parent is not None:
        parent_span_id = _span_id(parent.span_id)
    payload = {
        "traceId": _trace_id(span.context.trace_id),
        "spanId": _span_id(span.context.span_id),
        "name": span.name,
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": str(span.start_time),
        "endTimeUnixNano": str(span.end_time),
        "attributes": attributes_to_otlp(span.attributes),
        "status": {
            "code": status_code_name(span.status.status_code),
            "message": getattr(span.status, "description", None) or "",
        },
    }
    if parent_span_id:
        payload["parentSpanId"] = parent_span_id
    return payload


def attributes_to_otlp(attributes: Any) -> list[dict[str, Any]]:
    return [
        {"key": str(key), "value": value_to_otlp(value)}
        for key, value in sorted(dict(attributes or {}).items())
    ]


def value_to_otlp(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    return {"stringValue": str(value)}


def status_code_name(status_code: Any) -> str:
    name = getattr(status_code, "name", str(status_code))
    return {
        "OK": "STATUS_CODE_OK",
        "ERROR": "STATUS_CODE_ERROR",
        "UNSET": "STATUS_CODE_UNSET",
    }.get(name, name)


def _trace_id(value: int) -> str:
    return f"{int(value):032x}"


def _span_id(value: int) -> str:
    return f"{int(value):016x}"


if __name__ == "__main__":
    raise SystemExit(main())
'''.lstrip()
