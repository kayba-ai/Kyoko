"""`eval` plane — deterministic Python detectors over a trace corpus.

A detector is a single ``.py`` defining ``detect(...)`` (kayba-hosted-compatible
contract; see :mod:`kyoko.assets.eval_runner`). Kyoko stores the detector body in
the content-addressed blob store, registers it as an ``eval_definitions`` row
(``kind=python``), and runs it **out-of-process** over a corpus of exported run
traces. The result is **evidence only** — it never writes a ``check_run``,
mutates a skill, or edits a harness file.

Bundled example detectors live in ``kyoko/assets/detectors/*.py`` (with a
byte-identical ``docs/detectors`` mirror) and are seeded as ``source=bundled``
definitions on first use.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .blobs import put_blob
from .evals_measure import (
    EvalMeasureError,
    aggregate_boolean,
    complete_measure_run,
    create_measure_run,
    fail_measure_run,
    get_eval_definition,
    list_eval_definitions,
    record_measure_result,
    resolve_corpus,
    upsert_eval_definition,
)
from .span_normalize import normalize_span
from .storage import connect, initialize_database

BEGIN_BLOCK = "BEGIN_KYOKO_EVAL_RESULT_JSON"
END_BLOCK = "END_KYOKO_EVAL_RESULT_JSON"
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
RUNNER_PATH = _ASSETS_DIR / "eval_runner.py"
BUNDLED_DETECTORS_DIR = _ASSETS_DIR / "detectors"
_DEFAULT_TIMEOUT_SECONDS = 120


class DetectorError(Exception):
    """Raised for invalid detector input or a failed detector run."""


def parse_corpus(value: Optional[str]) -> dict[str, Any]:
    """Parse a ``--corpus`` argument: a path to a JSON file or inline JSON.

    ``None`` defaults to the whole-profile event corpus ``{"unit": "event"}``.
    """
    if value is None:
        return {"unit": "event"}
    candidate = Path(value)
    text = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DetectorError(f"invalid_corpus:{exc}") from exc
    if not isinstance(data, dict):
        raise DetectorError("corpus_must_be_object")
    return data


# --------------------------------------------------------------------------
# detector metadata (parsed, not executed)
# --------------------------------------------------------------------------
@dataclass
class DetectorMetadata:
    id: str
    name: str
    problem_statement: Optional[str]
    direction: str
    output_type: str
    unit_type: str
    version: int


_VALID_DIRECTIONS = ("lower_is_better", "higher_is_better", "true_is_notable", "false_is_notable")


def _extract_metadata(code: str, *, default_id: str) -> DetectorMetadata:
    """Read a detector's metadata via AST (no execution).

    A detector may declare a top-level ``DETECTOR = {...}`` literal with any of
    ``id``/``name``/``problem_statement``/``direction``/``output_type``/
    ``unit_type``/``version``. Missing fields fall back to safe defaults; the
    module docstring is the default ``problem_statement``.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise DetectorError(f"detector_syntax_error:{exc}") from exc

    has_function = any(isinstance(node, ast.FunctionDef) for node in tree.body)
    if not has_function:
        raise DetectorError("detector_defines_no_function")

    meta: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "DETECTOR" in targets:
                try:
                    value = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    value = None
                if isinstance(value, dict):
                    meta = value
                break

    docstring = ast.get_docstring(tree)
    direction = str(meta.get("direction", "true_is_notable"))
    if direction not in _VALID_DIRECTIONS:
        raise DetectorError(f"invalid_direction:{direction}")
    output_type = str(meta.get("output_type", "boolean"))
    unit_type = str(meta.get("unit_type", "event"))
    version = meta.get("version", 1)
    return DetectorMetadata(
        id=str(meta.get("id", default_id)),
        name=str(meta.get("name", default_id)),
        problem_statement=meta.get("problem_statement", docstring),
        direction=direction,
        output_type=output_type,
        unit_type=unit_type,
        version=int(version) if isinstance(version, int) else 1,
    )


# --------------------------------------------------------------------------
# registration + seeding
# --------------------------------------------------------------------------
def register_detector(
    *,
    db_path: Path,
    path: Path,
    source: str = "user",
    profile_id: Optional[str] = None,
) -> dict[str, Any]:
    """Register a detector ``.py``: store its body as a blob, upsert a definition."""
    path = Path(path)
    if not path.is_file():
        raise DetectorError(f"detector_file_not_found:{path}")
    code = path.read_text(encoding="utf-8")
    default_id = f"detector_{path.stem.replace('-', '_')}"
    meta = _extract_metadata(code, default_id=default_id)

    blob = put_blob(
        db_path=db_path,
        data=code.encode("utf-8"),
        kind="detector",
        media_type="text/x-python",
        profile_id=profile_id,
        redaction_mode="raw",
        metadata={"detector_id": meta.id, "source": source},
    )
    return upsert_eval_definition(
        db_path=db_path,
        definition_id=meta.id,
        kind="python",
        name=meta.name,
        version=meta.version,
        unit_type=meta.unit_type,
        output_type=meta.output_type,
        direction=meta.direction,
        source=source,
        problem_statement=meta.problem_statement,
        detector_ref=blob.blob_id,
        profile_id=profile_id,
    )


def seed_bundled_detectors(*, db_path: Path, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Upsert every bundled detector. Idempotent (keyed by detector id)."""
    seeded: list[dict[str, Any]] = []
    if not BUNDLED_DETECTORS_DIR.is_dir():
        return seeded
    for detector_path in sorted(BUNDLED_DETECTORS_DIR.glob("*.py")):
        if detector_path.name == "__init__.py":
            continue
        seeded.append(
            register_detector(
                db_path=db_path, path=detector_path, source="bundled", profile_id=profile_id
            )
        )
    return seeded


def list_detectors(*, db_path: Path, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    seed_bundled_detectors(db_path=db_path, profile_id=profile_id)
    return list_eval_definitions(db_path=db_path, kind="python", profile_id=profile_id)


def get_detector(*, db_path: Path, detector_id: str, profile_id: Optional[str] = None) -> dict[str, Any]:
    seed_bundled_detectors(db_path=db_path, profile_id=profile_id)
    definition = get_eval_definition(db_path=db_path, definition_id=detector_id)
    if definition["kind"] != "python":
        raise DetectorError(f"not_a_detector:{detector_id}")
    return definition


# --------------------------------------------------------------------------
# corpus export (real local trace data; redaction applies to stored outputs)
# --------------------------------------------------------------------------
def _load_payload(connection: Any, ref: Optional[str]) -> Any:
    if not ref:
        return None
    row = connection.execute(
        "SELECT path, media_type FROM payload_blobs WHERE id = ?", (ref,)
    ).fetchone()
    if row is None:
        return None
    try:
        data = Path(row["path"]).read_bytes()
    except OSError:
        return None
    if (row["media_type"] or "").startswith("application/json"):
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return data.decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def export_run_trace(*, db_path: Path, run_id: str) -> dict[str, Any]:
    """Export a run to a detector-facing trace dict (run + spans + content)."""
    initialize_database(db_path)
    with connect(db_path) as connection:
        run = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            raise DetectorError(f"run_not_found:{run_id}")
        span_rows = connection.execute(
            "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at, id", (run_id,)
        ).fetchall()
        spans: list[dict[str, Any]] = []
        for span in span_rows:
            try:
                attributes = json.loads(span["attributes_json"] or "{}")
            except (ValueError, TypeError):
                attributes = {}
            input_payload = _load_payload(connection, span["input_ref"])
            output_payload = _load_payload(connection, span["output_ref"])
            normalized = normalize_span(
                name=span["name"],
                kind=span["kind"],
                attributes=attributes if isinstance(attributes, dict) else {},
                input_payload=input_payload,
                output_payload=output_payload,
            )
            spans.append(
                {
                    "id": span["id"],
                    "parent_span_id": span["parent_span_id"],
                    "kind": span["kind"],
                    "name": span["name"],
                    "status": span["status"],
                    "started_at": span["started_at"],
                    "ended_at": span["ended_at"],
                    "attributes": attributes,
                    "input": input_payload,
                    "output": output_payload,
                    "normalized": normalized,
                }
            )
        return {
            "run": {
                "id": run["id"],
                "source_id": run["source_id"],
                "status": run["status"],
                "started_at": run["started_at"],
                "ended_at": run["ended_at"],
                "summary": run["summary"],
            },
            "spans": spans,
        }


# --------------------------------------------------------------------------
# running a detector
# --------------------------------------------------------------------------
def _materialize_detector(connection: Any, detector_ref: str, dest_dir: Path) -> Path:
    row = connection.execute(
        "SELECT path FROM payload_blobs WHERE id = ?", (detector_ref,)
    ).fetchone()
    if row is None:
        raise DetectorError(f"detector_blob_missing:{detector_ref}")
    code = Path(row["path"]).read_bytes()
    dest = dest_dir / "detector.py"
    dest.write_bytes(code)
    return dest


def _parse_result_block(stdout: str) -> dict[str, Any]:
    start = stdout.find(BEGIN_BLOCK)
    end = stdout.find(END_BLOCK)
    if start == -1 or end == -1 or end < start:
        raise DetectorError("detector_result_block_missing")
    payload = stdout[start + len(BEGIN_BLOCK) : end].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise DetectorError(f"detector_result_block_invalid:{exc}") from exc


@dataclass
class DetectorRunReport:
    detector_id: str
    persisted: bool
    eval_run_id: Optional[str]
    aggregate: dict[str, Any]
    events: list[dict[str, Any]]
    corpus_resolution: dict[str, Any]
    status: str

    def to_json(self) -> dict[str, Any]:
        return {
            "detector_id": self.detector_id,
            "persisted": self.persisted,
            "eval_run_id": self.eval_run_id,
            "aggregate": self.aggregate,
            "events": self.events,
            "corpus_resolution": self.corpus_resolution,
            "status": self.status,
        }


def run_detector(
    *,
    db_path: Path,
    detector_id: str,
    corpus: dict[str, Any],
    persist: bool = False,
    profile_id: Optional[str] = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    python_executable: Optional[str] = None,
) -> DetectorRunReport:
    """Run a detector over a corpus and return numerator/denominator + events.

    The corpus resolves to run ids (``event``/``run`` units); each run is exported
    to ``<tmp>/<run_id>.json`` and the bundled runner execs the detector once
    (folder mode) or per-trace. With ``persist=True`` the result is recorded as an
    ``eval_measure_runs`` row plus per-event ``eval_measure_results``.
    """
    definition = get_detector(db_path=db_path, detector_id=detector_id, profile_id=profile_id)
    resolution = resolve_corpus(
        db_path=db_path, corpus=corpus, profile_id=profile_id, default_unit="event"
    )

    with tempfile.TemporaryDirectory(prefix="kyoko_eval_") as tmp:
        tmp_path = Path(tmp)
        traces_dir = tmp_path / "traces"
        traces_dir.mkdir()
        for run_id in resolution.unit_refs:
            trace = export_run_trace(db_path=db_path, run_id=run_id)
            (traces_dir / f"{run_id}.json").write_text(
                json.dumps(trace, sort_keys=True), encoding="utf-8"
            )

        with connect(db_path) as connection:
            detector_path = _materialize_detector(connection, definition["detector_ref"], tmp_path)

        env = dict(os.environ)
        env["KYOKO_EVAL_DETECTOR_PATH"] = str(detector_path)
        env["KYOKO_EVAL_TRACES_DIR"] = str(traces_dir)
        try:
            proc = subprocess.run(
                [python_executable or sys.executable, str(RUNNER_PATH)],
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise DetectorError(f"detector_timeout:{timeout_seconds}s") from exc

        block = _parse_result_block(proc.stdout)

    if "error" in block:
        report = _persist_failure(
            db_path, definition, corpus, resolution, block, persist, profile_id
        )
        return report

    numerator = int(block.get("numerator", 0))
    denominator = int(block.get("denominator", 0))
    events = [
        {"event_id": str(e.get("event_id", "")), "has_problem": bool(e.get("has_problem", True))}
        for e in block.get("events", [])
        if isinstance(e, dict)
    ]
    aggregate = aggregate_boolean(numerator, denominator)

    eval_run_id: Optional[str] = None
    if persist:
        eval_run_id = create_measure_run(
            db_path=db_path, definition=definition, corpus=corpus, profile_id=profile_id
        )
        for event in events:
            record_measure_result(
                db_path=db_path,
                eval_run_id=eval_run_id,
                unit_type="event",
                unit_ref=event["event_id"],
                status="scored",
                score_bool=event["has_problem"],
                detail=event,
                profile_id=profile_id,
            )
        complete_measure_run(db_path=db_path, eval_run_id=eval_run_id, aggregate=aggregate)

    return DetectorRunReport(
        detector_id=detector_id,
        persisted=persist,
        eval_run_id=eval_run_id,
        aggregate=aggregate,
        events=events,
        corpus_resolution=resolution.to_json(),
        status="complete",
    )


def _persist_failure(
    db_path: Path,
    definition: dict[str, Any],
    corpus: dict[str, Any],
    resolution: Any,
    block: dict[str, Any],
    persist: bool,
    profile_id: Optional[str],
) -> DetectorRunReport:
    eval_run_id: Optional[str] = None
    if persist:
        eval_run_id = create_measure_run(
            db_path=db_path, definition=definition, corpus=corpus, profile_id=profile_id
        )
        fail_measure_run(db_path=db_path, eval_run_id=eval_run_id, detail=block["error"])
    raise DetectorError(f"detector_run_failed:{block['error']}")
