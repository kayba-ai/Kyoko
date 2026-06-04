#!/usr/bin/env python3
"""Bundled out-of-process runner for `eval` (Python detector) measurements.

Kyoko's `serve` process is long-lived, so detectors run here in a **subprocess**
(spawned by ``kyoko.eval_detectors``) rather than in-process. This file is a
bundled asset with **no kyoko imports** — it only reads its inputs from the
environment and prints a single result block on stdout.

Inputs (env):
- ``KYOKO_EVAL_DETECTOR_PATH`` — path to the user/bundled detector ``.py``.
- ``KYOKO_EVAL_TRACES_DIR`` — directory of ``<unit_id>.json`` trace files.

Output (stdout): one block
``BEGIN_KYOKO_EVAL_RESULT_JSON {"numerator","denominator","events":[{event_id,has_problem}]} END_KYOKO_EVAL_RESULT_JSON``
On failure it prints ``{"error": "..."}`` inside the same block and exits 1.

Detector contract (mirrors the kayba-hosted ``/run-eval`` detector contract so
detectors are portable both ways):
- Define ``detect``; if absent and exactly one user function is defined, fall
  back to it.
- Signature dispatch: a first positional param named one of
  {traces_folder, folder, path, dir, directory, traces_dir} → folder mode
  ``detect(traces_dir)``; zero params → ``detect()``; otherwise per-trace mode
  ``detect(trace_data, trace_id)`` called once per file and aggregated.
- Return shapes: ``(numerator, denominator, events)`` tuple, or a flat list of
  ``{event_id, has_problem}`` dicts (→ den = len, num = count(not has_problem)).
"""

import inspect
import json
import os
import sys

BEGIN_BLOCK = "BEGIN_KYOKO_EVAL_RESULT_JSON"
END_BLOCK = "END_KYOKO_EVAL_RESULT_JSON"
_FOLDER_NAMES = {"traces_folder", "folder", "path", "dir", "directory", "traces_dir"}


def _emit(payload):
    sys.stdout.write(f"\n{BEGIN_BLOCK}\n")
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write(f"\n{END_BLOCK}\n")
    sys.stdout.flush()


def _normalize_event(event):
    """Coerce a detector event into {event_id, has_problem}.

    Dict events carry their own has_problem (default True). A bare event id
    string is treated as a flagged (has_problem=True) unit, matching the
    convention that a tuple-shape detector lists the events it flagged.
    """
    if isinstance(event, dict):
        return {
            "event_id": str(event.get("event_id", "")),
            "has_problem": bool(event.get("has_problem", True)),
        }
    return {"event_id": str(event), "has_problem": True}


def _finalize(result):
    """Normalize any dispatch result into (numerator, denominator, events)."""
    if isinstance(result, (list, tuple)) and (
        len(result) >= 2
        and isinstance(result[0], (int, float))
        and isinstance(result[1], (int, float))
    ):
        num = int(result[0])
        den = int(result[1])
        raw_events = result[2] if len(result) >= 3 and isinstance(result[2], list) else []
        events = [_normalize_event(e) for e in raw_events]
        return num, den, events
    if isinstance(result, list):
        # Kyoko reports the *problem prevalence* (count of flagged events), so a
        # detector's stored value and direction orient the same way as a boolean
        # llm_eval. (kayba-hosted's framework counts non-problems instead; the
        # detect() contract and per-event has_problem are unchanged either way.)
        events = [_normalize_event(e) for e in result]
        den = len(events)
        num = sum(1 for e in events if e["has_problem"])
        return num, den, events
    raise ValueError(f"detector returned unsupported result shape: {type(result).__name__}")


def _required_positional_params(fn):
    sig = inspect.signature(fn)
    return [
        p
        for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]


def _discover_detect(namespace):
    if "detect" in namespace and inspect.isfunction(namespace["detect"]):
        return namespace["detect"]
    user_fns = {k: v for k, v in namespace.items() if inspect.isfunction(v)}
    if len(user_fns) == 1:
        return next(iter(user_fns.values()))
    found = ", ".join(sorted(user_fns)) if user_fns else "none"
    raise ValueError(f"detector must define detect(); found functions: {found}")


def _run():
    detector_path = os.environ.get("KYOKO_EVAL_DETECTOR_PATH")
    traces_dir = os.environ.get("KYOKO_EVAL_TRACES_DIR")
    if not detector_path or not os.path.isfile(detector_path):
        raise ValueError(f"detector path not found: {detector_path!r}")
    if not traces_dir or not os.path.isdir(traces_dir):
        raise ValueError(f"traces dir not found: {traces_dir!r}")

    with open(detector_path, "r", encoding="utf-8") as fh:
        detector_code = fh.read()
    namespace = {}
    exec(compile(detector_code, detector_path, "exec"), namespace)
    detect_fn = _discover_detect(namespace)
    params = _required_positional_params(detect_fn)
    wants_folder = len(params) >= 1 and params[0].name.lower() in _FOLDER_NAMES

    if len(params) == 0:
        result = detect_fn()
    elif wants_folder:
        result = detect_fn(traces_dir)
    else:
        # Per-trace: call once per file with (trace_data, trace_id, ...) and
        # aggregate. Folder-named params get the dir; the first non-folder param
        # gets the parsed trace; remaining non-folder params get the trace id.
        all_events = []
        total_num = 0
        total_den = 0
        saw_tuple = False
        trace_files = sorted(f for f in os.listdir(traces_dir) if f.endswith(".json"))
        for fname in trace_files:
            with open(os.path.join(traces_dir, fname), encoding="utf-8") as fh:
                file_data = json.load(fh)
            trace_id = os.path.splitext(fname)[0]
            file_args = []
            data_passed = False
            for p in params:
                if p.name.lower() in _FOLDER_NAMES:
                    file_args.append(traces_dir)
                elif not data_passed:
                    file_args.append(file_data)
                    data_passed = True
                else:
                    file_args.append(trace_id)
            file_result = detect_fn(*file_args)
            if isinstance(file_result, (list, tuple)) and (
                len(file_result) >= 2
                and isinstance(file_result[0], (int, float))
                and isinstance(file_result[1], (int, float))
            ):
                saw_tuple = True
                total_num += int(file_result[0])
                total_den += int(file_result[1])
                if len(file_result) >= 3 and isinstance(file_result[2], list):
                    all_events.extend(file_result[2])
            elif isinstance(file_result, list):
                all_events.extend(file_result)
        if saw_tuple:
            result = (total_num, total_den, all_events)
        else:
            result = all_events

    numerator, denominator, events = _finalize(result)
    _emit({"numerator": numerator, "denominator": denominator, "events": events})


def main():
    try:
        _run()
    except Exception as exc:  # noqa: BLE001 — report any detector failure cleanly
        _emit({"error": f"{type(exc).__name__}: {exc}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
