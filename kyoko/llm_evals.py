"""`llm_eval` plane — LLM-as-judge templates scored outside Kyoko's core.

The 10 bundled templates ship as ``kyoko/assets/llm_evals/<id>.json`` (schema
``kyoko.llm_eval.v1``) with a byte-identical ``docs/llm_evals`` mirror. Each is a
pure prompt + output spec; the model call runs **outside** core via the user's
``--command`` (BYO key/CLI), exactly like the check apply-judge — but with a
**distinct** result block so the two wire formats never conflate.

Per unit: resolve bindings → render → redact → invoke command (stdin + env) →
parse ``BEGIN_KYOKO_LLM_EVAL_RESULT_JSON {score, reasoning} END`` → validate
against the template output spec → record a result row. Missing var → skipped.
``--prepare-only`` writes per-unit requests + a handoff and stops. Evidence only.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .evals_measure import (
    EvalMeasureError,
    aggregate_boolean,
    aggregate_numeric,
    complete_measure_run,
    create_measure_run,
    fail_measure_run,
    get_eval_definition,
    list_eval_definitions,
    record_measure_result,
    resolve_corpus,
    set_eval_definition_status,
    upsert_eval_definition,
)
from .live import LiveBus
from .metric_bindings import resolve_bindings
from .redaction import get_redaction_policy, redact_evidence_bundle

BEGIN_BLOCK = "BEGIN_KYOKO_LLM_EVAL_RESULT_JSON"
END_BLOCK = "END_KYOKO_LLM_EVAL_RESULT_JSON"
REQUEST_SCHEMA = "kyoko.llm_eval_request.v1"
_ASSETS_DIR = Path(__file__).resolve().parent / "assets" / "llm_evals"
_DEFAULT_TIMEOUT_SECONDS = 120
_NOTABLE_WHEN_TRUE = {"true_is_notable"}
_NOTABLE_WHEN_FALSE = {"false_is_notable"}

# Safety cap on each bound variable before it enters a judge prompt. Long traces
# (whole-conversation context for grounding metrics) are head/tail elided rather than
# allowed to blow up the model's context window. ~12k tokens at ~4 chars/token.
_MAX_VALUE_CHARS = 48000
_TRUNCATION_MARKER = "\n…[truncated for length]…\n"


class LlmEvalError(Exception):
    """Raised for invalid llm_eval input or a failed judge invocation."""


# --------------------------------------------------------------------------
# catalog (bundled assets -> definitions)
# --------------------------------------------------------------------------
def _load_asset(path: Path) -> dict[str, Any]:
    asset = json.loads(path.read_text(encoding="utf-8"))
    if asset.get("schema_version") != "kyoko.llm_eval.v1":
        raise LlmEvalError(f"bad_llm_eval_schema:{path.name}")
    return asset


def seed_bundled_llm_evals(*, db_path: Path, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    """Upsert every bundled llm_eval template. Idempotent (keyed by id)."""
    seeded: list[dict[str, Any]] = []
    if not _ASSETS_DIR.is_dir():
        return seeded
    for asset_path in sorted(_ASSETS_DIR.glob("*.json")):
        asset = _load_asset(asset_path)
        output = asset.get("output") or {}
        seeded.append(
            upsert_eval_definition(
                db_path=db_path,
                definition_id=asset["id"],
                kind="llm",
                name=asset["name"],
                version=int(asset.get("version", 1)),
                unit_type=asset["unit"],
                output_type=output.get("type", "numeric"),
                direction=asset["direction"],
                source="bundled",
                partner=asset.get("partner"),
                prompt=asset["prompt"],
                vars=asset.get("vars"),
                bindings=asset.get("bindings"),
                output=output,
                severity_bands=asset.get("severity_bands"),
                profile_id=profile_id,
            )
        )
    return seeded


def list_llm_evals(*, db_path: Path, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    seed_bundled_llm_evals(db_path=db_path, profile_id=profile_id)
    return list_eval_definitions(db_path=db_path, kind="llm", profile_id=profile_id)


def get_llm_eval(*, db_path: Path, llm_eval_id: str, profile_id: Optional[str] = None) -> dict[str, Any]:
    seed_bundled_llm_evals(db_path=db_path, profile_id=profile_id)
    definition = get_eval_definition(db_path=db_path, definition_id=llm_eval_id)
    if definition["kind"] != "llm":
        raise LlmEvalError(f"not_an_llm_eval:{llm_eval_id}")
    return definition


def set_llm_eval_status(
    *, db_path: Path, llm_eval_id: str, status: str, profile_id: Optional[str] = None
) -> dict[str, Any]:
    """Activate ("active") or deactivate ("archived") a judge template. Evidence
    only — a judge's status gates nothing in the autonomy plane; it just controls
    whether the user considers this measurement in play."""
    # Validates kind == "llm" and seeds bundled rows so the id resolves.
    get_llm_eval(db_path=db_path, llm_eval_id=llm_eval_id, profile_id=profile_id)
    return set_eval_definition_status(
        db_path=db_path, definition_id=llm_eval_id, status=status, profile_id=profile_id
    )


# --------------------------------------------------------------------------
# prompt rendering + result parsing + score validation
# --------------------------------------------------------------------------
def render_prompt(prompt: str, values: dict[str, str]) -> str:
    def _sub(match: "re.Match[str]") -> str:
        name = match.group(1)
        return values.get(name, match.group(0))

    return re.sub(r"{{\s*([a-zA-Z0-9_]+)\s*}}", _sub, prompt)


def _parse_result_block(stdout: str) -> dict[str, Any]:
    if stdout.count(BEGIN_BLOCK) != 1 or stdout.count(END_BLOCK) != 1:
        raise LlmEvalError("llm_eval_result_block_missing")
    start = stdout.index(BEGIN_BLOCK) + len(BEGIN_BLOCK)
    end = stdout.index(END_BLOCK)
    try:
        return json.loads(stdout[start:end].strip())
    except json.JSONDecodeError as exc:
        raise LlmEvalError(f"llm_eval_result_block_invalid:{exc}") from exc


def _parse_result_block_tolerant(stdout: str) -> dict[str, Any]:
    """Parse a judge result from free-form agent-CLI stdout.

    Unlike :func:`_parse_result_block` (the strict BYO ``--command`` contract), an agent
    CLI may wrap the block in chatter or echo the prompt (which itself names the markers).
    Prefer the LAST well-formed ``BEGIN..END`` block; fall back to the last bare JSON
    object mentioning ``"score"``.
    """
    begin = stdout.rfind(BEGIN_BLOCK)
    if begin != -1:
        start = begin + len(BEGIN_BLOCK)
        end = stdout.find(END_BLOCK, start)
        if end != -1:
            try:
                return json.loads(stdout[start:end].strip())
            except json.JSONDecodeError:
                pass
    for candidate in reversed(re.findall(r"\{[^{}]*\"score\"[^{}]*\}", stdout)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise LlmEvalError("llm_eval_result_block_missing")


def _truncate_text(text: str, budget: int) -> tuple[str, bool]:
    if len(text) <= budget:
        return text, False
    head = (budget * 2) // 3
    tail = max(0, budget - head - len(_TRUNCATION_MARKER))
    return text[:head] + _TRUNCATION_MARKER + (text[-tail:] if tail else ""), True


def _truncate_values(
    values: dict[str, str], budget: int = _MAX_VALUE_CHARS
) -> tuple[dict[str, str], list[str]]:
    """Head/tail elide each bound var past ``budget`` chars. Returns the capped values
    and the names of any var that was truncated (so callers can flag it, never silently)."""
    out: dict[str, str] = {}
    truncated: list[str] = []
    for key, value in values.items():
        text = value if isinstance(value, str) else str(value)
        new_text, was_truncated = _truncate_text(text, budget)
        out[key] = new_text
        if was_truncated:
            truncated.append(key)
    return out, truncated


def _coerce_numeric(score: Any, output: dict[str, Any]) -> float:
    try:
        value = float(score)
    except (TypeError, ValueError) as exc:
        raise LlmEvalError(f"llm_eval_score_not_numeric:{score!r}") from exc
    rng = output.get("range") or [0, 1]
    lo, hi = float(rng[0]), float(rng[1])
    if not (lo <= value <= hi):
        raise LlmEvalError(f"llm_eval_score_out_of_range:{value}:[{lo},{hi}]")
    return value


def _coerce_bool(score: Any) -> bool:
    if isinstance(score, bool):
        return score
    if isinstance(score, (int, float)):
        return bool(score)
    if isinstance(score, str):
        token = score.strip().lower()
        if token in {"true", "yes", "1"}:
            return True
        if token in {"false", "no", "0"}:
            return False
    raise LlmEvalError(f"llm_eval_score_not_boolean:{score!r}")


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------
@dataclass
class LlmEvalRunReport:
    llm_eval_id: str
    persisted: bool
    prepared_only: bool
    eval_run_id: Optional[str]
    aggregate: Optional[dict[str, Any]]
    results: list[dict[str, Any]]
    corpus_resolution: dict[str, Any]
    status: str
    raised_issue_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "llm_eval_id": self.llm_eval_id,
            "persisted": self.persisted,
            "prepared_only": self.prepared_only,
            "eval_run_id": self.eval_run_id,
            "aggregate": self.aggregate,
            "results": self.results,
            "corpus_resolution": self.corpus_resolution,
            "status": self.status,
            "raised_issue_id": self.raised_issue_id,
        }


def _build_request(definition: dict[str, Any], unit_ref: str, values: dict[str, str], policy: dict[str, Any]) -> dict[str, Any]:
    rendered = render_prompt(definition["prompt"], values)
    bundle = {"vars": values, "rendered_prompt": rendered}
    redacted = redact_evidence_bundle(bundle, policy).payload
    return {
        "schema_version": REQUEST_SCHEMA,
        "llm_eval_id": definition["id"],
        "unit_type": definition["unit_type"],
        "unit_ref": unit_ref,
        "output": definition.get("output") or {"type": definition["output_type"]},
        "prompt": redacted.get("rendered_prompt"),
        "vars": redacted.get("vars"),
        "result_block": {"begin": BEGIN_BLOCK, "end": END_BLOCK},
    }


def _invoke_judge(
    command: Sequence[str], request: dict[str, Any], timeout_seconds: int
) -> dict[str, Any]:
    env = os.environ.copy()
    env["KYOKO_LLM_EVAL_ID"] = str(request["llm_eval_id"])
    env["KYOKO_LLM_EVAL_UNIT_REF"] = str(request["unit_ref"])
    env["KYOKO_LLM_EVAL_RESULT_BLOCK_BEGIN"] = BEGIN_BLOCK
    env["KYOKO_LLM_EVAL_RESULT_BLOCK_END"] = END_BLOCK
    try:
        completed = subprocess.run(
            list(command),
            input=json.dumps(request, sort_keys=True),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        raise LlmEvalError(f"llm_eval_command_not_found:{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise LlmEvalError(f"llm_eval_command_timeout:{timeout_seconds}") from exc
    if completed.returncode != 0:
        raise LlmEvalError(f"llm_eval_command_failed:{completed.returncode}")
    return _parse_result_block(completed.stdout)


def _judge_format_instruction(output: dict[str, Any]) -> str:
    """The output-format directive appended to a prompt when judging via an agent CLI.

    The BYO ``--command`` wrapper is trusted to emit the result block itself; an agent CLI
    (claude/codex/hermes/openclaw) is a general assistant and must be told the exact wire
    format, since the bundled template prompts carry only the scoring rubric."""
    if output.get("type") == "numeric":
        rng = output.get("range") or [0, 1]
        score_hint = f"a number from {rng[0]} to {rng[1]}"
    else:
        score_hint = "either true or false (a JSON boolean, unquoted)"
    return (
        "\n\n---\n"
        "When you have decided, output your judgment as a single block and nothing after "
        "it — no markdown fences — in EXACTLY this format:\n"
        f"{BEGIN_BLOCK}\n"
        '{"score": <' + score_hint + '>, "reasoning": "<one short sentence>"}\n'
        f"{END_BLOCK}"
    )


def _expand_judge_command(
    command: Sequence[str], prompt_text: str, prompt_path: Path
) -> tuple[list[str], bool]:
    """Substitute ``{prompt}``/``{prompt_path}`` placeholders (mirrors the operator-adapter
    convention in ``analyze.expand_operator_command``). Returns the expanded argv and
    whether any placeholder was present — if none, the prompt is delivered on stdin."""
    used = False
    expanded: list[str] = []
    for part in command:
        value = str(part)
        if "{prompt_path}" in value or "{prompt}" in value:
            used = True
        value = value.replace("{prompt_path}", str(prompt_path)).replace("{prompt}", prompt_text)
        expanded.append(value)
    return expanded, used


def _invoke_judge_operator(
    command: Sequence[str],
    operator_kind: Optional[str],
    request: dict[str, Any],
    output: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run a registered operator adapter (any backend CLI) as the judge.

    The rendered+redacted prompt (plus an explicit output-format directive) is delivered
    via a ``{prompt_path}`` temp file / ``{prompt}`` arg, or on stdin when the adapter
    command names no placeholder. The result block is parsed tolerantly from stdout."""
    prompt_text = str(request.get("prompt") or "") + _judge_format_instruction(output)
    env = os.environ.copy()
    env["KYOKO_LLM_EVAL_ID"] = str(request["llm_eval_id"])
    env["KYOKO_LLM_EVAL_UNIT_REF"] = str(request["unit_ref"])
    env["KYOKO_LLM_EVAL_RESULT_BLOCK_BEGIN"] = BEGIN_BLOCK
    env["KYOKO_LLM_EVAL_RESULT_BLOCK_END"] = END_BLOCK
    if operator_kind:
        env["KYOKO_OPERATOR_TARGET"] = operator_kind
    with tempfile.TemporaryDirectory(prefix="kyoko-judge-") as tmp:
        prompt_path = Path(tmp) / "judge_prompt.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        expanded, used_placeholder = _expand_judge_command(command, prompt_text, prompt_path)
        try:
            completed = subprocess.run(
                expanded,
                input=None if used_placeholder else prompt_text,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env,
            )
        except FileNotFoundError as exc:
            raise LlmEvalError(f"llm_eval_command_not_found:{expanded[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            raise LlmEvalError(f"llm_eval_command_timeout:{timeout_seconds}") from exc
    if completed.returncode != 0:
        raise LlmEvalError(f"llm_eval_command_failed:{completed.returncode}")
    return _parse_result_block_tolerant(completed.stdout)


def run_llm_eval(
    *,
    db_path: Path,
    llm_eval_id: str,
    corpus: dict[str, Any],
    command: Optional[Sequence[str]] = None,
    operator_adapter_id: Optional[str] = None,
    persist: bool = False,
    prepare_only: bool = False,
    raise_issues: bool = False,
    issue_threshold: Optional[float] = None,
    output_dir: Optional[Path] = None,
    profile_id: Optional[str] = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    bus: Optional[LiveBus] = None,
) -> LlmEvalRunReport:
    definition = get_llm_eval(db_path=db_path, llm_eval_id=llm_eval_id, profile_id=profile_id)
    if not prepare_only and not command and not operator_adapter_id:
        raise LlmEvalError("llm_eval_command_required")
    # Resolve a registered operator adapter (claude/codex/hermes/openclaw/generic) into a
    # runnable argv + kind once, up front — this is the backend-agnostic judge path.
    operator_command: Optional[list[str]] = None
    operator_kind: Optional[str] = None
    if operator_adapter_id and not prepare_only:
        from .operator_adapters import get_operator_adapter_command

        operator_command, operator_kind = get_operator_adapter_command(
            db_path=db_path, adapter_id=operator_adapter_id
        )
    if raise_issues and issue_threshold is None:
        raise LlmEvalError("raise_issues_requires_threshold")
    if raise_issues and not prepare_only:
        persist = True  # an Issue references a persisted run
    unit_type = definition["unit_type"]
    output = definition.get("output") or {"type": definition["output_type"]}
    direction = definition["direction"]
    bindings = definition.get("bindings") or {}
    resolution = resolve_corpus(
        db_path=db_path, corpus=corpus, profile_id=profile_id, default_unit=unit_type
    )
    policy = get_redaction_policy(db_path=db_path, profile_id=profile_id)

    eval_run_id: Optional[str] = None
    if persist and not prepare_only:
        eval_run_id = create_measure_run(
            db_path=db_path, definition=definition, corpus=corpus, profile_id=profile_id
        )

    results: list[dict[str, Any]] = []
    numeric_scores: list[float] = []
    notable = 0
    scored = 0
    skipped = 0
    total_units = len(resolution.unit_refs)

    def _emit_progress(last_value: Optional[float] = None) -> None:
        if bus is not None:
            bus.publish(
                "live_event",
                {
                    "kind": "eval_progress",
                    "eval_run_id": eval_run_id,
                    "llm_eval_id": llm_eval_id,
                    "scored": scored,
                    "skipped": skipped,
                    "total": total_units,
                    "last_value": last_value,
                },
            )

    if prepare_only and output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    for unit_ref in resolution.unit_refs:
        resolution_b = resolve_bindings(
            db_path=db_path,
            unit_type=unit_type,
            unit_ref=unit_ref,
            bindings=bindings,
            profile_id=profile_id,
        )
        if resolution_b.missing:
            skipped += 1
            detail = {"reason": f"missing_var:{resolution_b.missing[0]}", "missing": resolution_b.missing}
            results.append({"unit_ref": unit_ref, "status": "skipped", "detail": detail})
            if eval_run_id:
                record_measure_result(
                    db_path=db_path, eval_run_id=eval_run_id, unit_type=unit_type,
                    unit_ref=unit_ref, status="skipped", detail=detail, profile_id=profile_id,
                )
            _emit_progress()
            continue

        values, truncated_vars = _truncate_values(resolution_b.values)
        request = _build_request(definition, unit_ref, values, policy)

        if prepare_only:
            if output_dir is not None:
                (output_dir / f"{unit_ref}.json").write_text(
                    json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
            results.append({"unit_ref": unit_ref, "status": "prepared", "degraded": resolution_b.degraded})
            continue

        if operator_command is not None:
            block = _invoke_judge_operator(
                operator_command, operator_kind, request, output, timeout_seconds
            )
        else:
            block = _invoke_judge(command, request, timeout_seconds)
        reasoning_red = redact_evidence_bundle(
            {"reasoning": str(block.get("reasoning", ""))}, policy
        ).payload.get("reasoning")

        if output["type"] == "numeric":
            value = _coerce_numeric(block.get("score"), output)
            numeric_scores.append(value)
            scored += 1
            row = {"unit_ref": unit_ref, "status": "scored", "score_numeric": value,
                   "reasoning": reasoning_red, "degraded": resolution_b.degraded}
            if eval_run_id:
                record_measure_result(
                    db_path=db_path, eval_run_id=eval_run_id, unit_type=unit_type,
                    unit_ref=unit_ref, status="scored", score_numeric=value,
                    reasoning=reasoning_red, degraded=resolution_b.degraded,
                    detail={"raw": block}, profile_id=profile_id,
                )
        else:
            value_b = _coerce_bool(block.get("score"))
            is_notable = (value_b and direction in _NOTABLE_WHEN_TRUE) or (
                not value_b and direction in _NOTABLE_WHEN_FALSE
            )
            if is_notable:
                notable += 1
            scored += 1
            row = {"unit_ref": unit_ref, "status": "scored", "score_bool": value_b,
                   "notable": is_notable, "reasoning": reasoning_red, "degraded": resolution_b.degraded}
            if eval_run_id:
                record_measure_result(
                    db_path=db_path, eval_run_id=eval_run_id, unit_type=unit_type,
                    unit_ref=unit_ref, status="scored", score_bool=value_b,
                    reasoning=reasoning_red, degraded=resolution_b.degraded,
                    detail={"raw": block, "notable": is_notable}, profile_id=profile_id,
                )
        if truncated_vars:
            row["truncated"] = truncated_vars
        results.append(row)
        _emit_progress(last_value=row.get("score_numeric"))

    if prepare_only:
        if output_dir is not None:
            (output_dir / "handoff.json").write_text(
                json.dumps(
                    {"llm_eval_id": llm_eval_id, "unit_type": unit_type,
                     "prepared": [r["unit_ref"] for r in results if r["status"] == "prepared"],
                     "result_block": {"begin": BEGIN_BLOCK, "end": END_BLOCK}},
                    indent=2, sort_keys=True,
                ) + "\n",
                encoding="utf-8",
            )
        return LlmEvalRunReport(
            llm_eval_id=llm_eval_id, persisted=False, prepared_only=True, eval_run_id=None,
            aggregate=None, results=results, corpus_resolution=resolution.to_json(),
            status="prepared",
        )

    if output["type"] == "numeric":
        aggregate = aggregate_numeric(numeric_scores, skipped=skipped)
    else:
        aggregate = aggregate_boolean(notable, scored)
    if eval_run_id:
        complete_measure_run(db_path=db_path, eval_run_id=eval_run_id, aggregate=aggregate)
    if bus is not None:
        bus.publish(
            "live_event",
            {"kind": "eval_complete", "eval_run_id": eval_run_id,
             "llm_eval_id": llm_eval_id, "aggregate": aggregate},
        )

    raised_issue_id: Optional[str] = None
    if raise_issues and eval_run_id is not None:
        from .eval_issues import problem_value, raise_issue_for_run

        scored_rows = [r for r in results if r["status"] == "scored"]
        if output["type"] == "numeric":
            scored_rows.sort(
                key=lambda r: problem_value(r.get("score_numeric") or 0.0, direction), reverse=True
            )
            worst = [r["unit_ref"] for r in scored_rows][:5]
        else:
            worst = [r["unit_ref"] for r in scored_rows if r.get("notable")][:5]
        issue = raise_issue_for_run(
            db_path=db_path,
            definition=definition,
            eval_run_id=eval_run_id,
            aggregate=aggregate,
            worst_unit_refs=worst,
            threshold=float(issue_threshold),
            profile_id=profile_id,
        )
        raised_issue_id = issue["id"] if issue else None

    return LlmEvalRunReport(
        llm_eval_id=llm_eval_id, persisted=bool(eval_run_id), prepared_only=False,
        eval_run_id=eval_run_id, aggregate=aggregate, results=results,
        corpus_resolution=resolution.to_json(), status="complete",
        raised_issue_id=raised_issue_id,
    )
