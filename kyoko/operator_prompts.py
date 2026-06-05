from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .bundled_assets import bundled_asset_path
from .evidence import build_evidence_bundle
from .proposals import DEFAULT_SCHEMA_PATH


BEGIN_PROPOSAL_BLOCK = "BEGIN_KYOKO_LEARNING_PROPOSAL_JSON"
END_PROPOSAL_BLOCK = "END_KYOKO_LEARNING_PROPOSAL_JSON"
BEGIN_ISSUES_BLOCK = "BEGIN_KYOKO_ISSUES_JSON"
END_ISSUES_BLOCK = "END_KYOKO_ISSUES_JSON"
INLINE_EVIDENCE_MAX_CHARS = 60000


@dataclass(frozen=True)
class OperatorPromptReport:
    target: str
    profile_id: str
    evidence_path: Path
    prompt_path: Path
    schema_path: Optional[Path]
    bundle: dict[str, Any]


def write_operator_prompt_artifacts(
    *,
    db_path: Path,
    output_dir: Path,
    target: str = "generic",
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    schema_path: Optional[Path] = None,
    kind: str = "propose",
    issue: Optional[dict[str, Any]] = None,
) -> OperatorPromptReport:
    """Build the evidence bundle + operator-instructions.md for an operator turn.

    ``kind`` selects which contract the operator is asked to satisfy:

    - ``"propose"`` (default — the legacy behavior): return exactly one
      ``LearningProposal`` (``BEGIN_KYOKO_LEARNING_PROPOSAL_JSON`` block). When ``issue``
      is supplied it becomes a *proposal-authoring* turn whose proposal must fix that one
      accepted issue.
    - ``"diagnose"``: return a JSON array of ``kyoko.issue.v1`` issues
      (``BEGIN_KYOKO_ISSUES_JSON`` block) — diagnosis only, no fixes/proposals.

    The returned ``schema_path`` is the issue schema for ``"diagnose"`` and the
    LearningProposal schema otherwise; ``evidence_path``/``prompt_path``/``profile_id``/
    ``bundle`` are always populated."""

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = build_evidence_bundle(
        db_path=db_path,
        profile_id=profile_id,
        run_id=run_id,
        since=since,
        consumer=f"operator_prompt:{target}",
    )
    evidence_path = output_dir / "evidence-bundle.json"
    prompt_path = output_dir / "operator-instructions.md"

    evidence_path.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    if kind == "diagnose":
        resolved_schema_path = resolve_operator_issue_schema_path(schema_path)
        prompt_path.write_text(
            build_diagnosis_prompt(
                bundle=bundle,
                evidence_path=evidence_path,
                target=target,
                schema_path=resolved_schema_path,
            )
        )
    else:
        resolved_schema_path = resolve_operator_schema_path(schema_path)
        if issue is not None:
            prompt_text = build_proposal_authoring_prompt(
                bundle=bundle,
                evidence_path=evidence_path,
                issue=issue,
                target=target,
                schema_path=resolved_schema_path,
            )
        else:
            prompt_text = build_operator_prompt(
                bundle=bundle,
                evidence_path=evidence_path,
                target=target,
                schema_path=resolved_schema_path,
            )
        prompt_path.write_text(prompt_text)

    return OperatorPromptReport(
        target=target,
        profile_id=str(bundle["profile_id"]),
        evidence_path=evidence_path,
        prompt_path=prompt_path,
        schema_path=resolved_schema_path,
        bundle=bundle,
    )


def write_diagnosis_prompt_artifacts(
    *,
    db_path: Path,
    output_dir: Path,
    target: str = "generic",
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    schema_path: Optional[Path] = None,
) -> OperatorPromptReport:
    """Sibling of :func:`write_operator_prompt_artifacts` for the diagnosis turn — the
    operator returns a JSON array of ``kyoko.issue.v1`` issues (no fixes)."""

    return write_operator_prompt_artifacts(
        db_path=db_path,
        output_dir=output_dir,
        target=target,
        profile_id=profile_id,
        run_id=run_id,
        since=since,
        schema_path=schema_path,
        kind="diagnose",
    )


def write_proposal_prompt_artifacts(
    *,
    db_path: Path,
    output_dir: Path,
    issue: dict[str, Any],
    target: str = "generic",
    profile_id: Optional[str] = None,
    run_id: Optional[str] = None,
    since: Optional[str] = None,
    schema_path: Optional[Path] = None,
) -> OperatorPromptReport:
    """Sibling of :func:`write_operator_prompt_artifacts` for the proposal-authoring turn —
    given one accepted ``issue``, the operator returns exactly one ``LearningProposal``
    that fixes it."""

    return write_operator_prompt_artifacts(
        db_path=db_path,
        output_dir=output_dir,
        target=target,
        profile_id=profile_id,
        run_id=run_id,
        since=since,
        schema_path=schema_path,
        kind="propose",
        issue=issue,
    )


def build_operator_prompt(
    *,
    bundle: dict[str, Any],
    evidence_path: Path,
    target: str = "generic",
    schema_path: Optional[Path] = None,
) -> str:
    summary = bundle.get("summary", {})
    capabilities = bundle.get("check_capabilities") if isinstance(bundle.get("check_capabilities"), dict) else {}
    redaction = bundle.get("redaction") if isinstance(bundle.get("redaction"), dict) else {}
    redaction_policy = redaction.get("policy") if isinstance(redaction.get("policy"), dict) else {}
    payload_access = redaction_policy.get("payload_access", "unknown")
    redact_sensitive_values = redaction_policy.get("redact_sensitive_values", "unknown")
    profile_id = str(bundle.get("profile_id") or "")
    schema_display = str(schema_path) if schema_path is not None else "docs/schemas/learning-proposal.schema.json"
    target_note = _target_note(target)
    skeleton = _proposal_skeleton(profile_id)
    inline_evidence = _inline_evidence_json(bundle=bundle, evidence_path=evidence_path)

    return "\n".join(
        [
            "# Kyoko Operator Task",
            "",
            f"Target operator: `{target}`",
            f"Evidence bundle: `{evidence_path}`",
            f"LearningProposal schema: `{schema_display}`",
            "",
            "You are acting as Kyoko's analysis operator. Read the evidence bundle, identify one concrete agent failure or improvement opportunity, and return one strict LearningProposal JSON object.",
            "",
            target_note,
            "",
            "## Hard Constraints",
            "",
            "- Return exactly one proposal block on stdout.",
            "- Cite only evidence IDs that exist in the evidence bundle.",
            "- Do not apply proposals, patch files, mutate the skillbook, or change autonomy policy.",
            "- Prefer a `context` proposal when a prompt/skillbook fix is enough.",
            "- Use `harness` only when the proposed change is an check, test, replay adapter, tool wrapper, or repository patch.",
            "- Keep generated checks at `L0_generated`; Kyoko promotes trust only after replay/check evidence.",
            "- If evidence is insufficient, propose the smallest useful context skill and mark confidence conservatively.",
            "- Your `confidence` field is only an operator signal; Kyoko computes its own confidence from evidence coverage, check/replay results, duplicate history, and validation state.",
            "",
            "## Check Capabilities",
            "",
            *_check_capability_lines(capabilities),
            "",
            "## Evidence Privacy And Audit",
            "",
            f"- Payload access mode: `{payload_access}`",
            f"- Sensitive-value redaction: `{redact_sensitive_values}`",
            f"- Redacted field count: {redaction.get('redacted_count', 0)}",
            "- Treat redacted refs and secret placeholders as intentional privacy controls, not missing evidence.",
            "",
            "## Evidence Summary",
            "",
            f"- Profile: `{profile_id}`",
            f"- Runs: {summary.get('runs', 0)}",
            f"- Spans: {summary.get('spans', 0)}",
            f"- Failed spans: {summary.get('failed_spans', 0)}",
            f"- Tasks: {summary.get('tasks', 0)}",
            f"- Handoffs: {summary.get('handoffs', 0)}",
            f"- Existing proposals: {len(bundle.get('learning_proposals', [])) if isinstance(bundle.get('learning_proposals'), list) else 0}",
            f"- Existing skills: {summary.get('skills', 0)}",
            f"- Check specs: {summary.get('check_specs', 0)}",
            f"- Replay runs: {summary.get('replay_runs', 0)}",
            "",
            "## Evidence Bundle JSON",
            "",
            "The inline JSON below is the evidence to cite from. If it is marked as truncated, read the full evidence bundle path above.",
            "",
            "```json",
            inline_evidence,
            "```",
            "",
            "## Required Stdout",
            "",
            "```text",
            BEGIN_PROPOSAL_BLOCK,
            json.dumps(skeleton, indent=2, sort_keys=True),
            END_PROPOSAL_BLOCK,
            "```",
            "",
            "The JSON above is a shape guide, not the answer. Replace every placeholder with evidence-backed content.",
            "",
        ]
    )


def resolve_operator_schema_path(schema_path: Optional[Path]) -> Optional[Path]:
    if schema_path is None:
        default_path = Path.cwd() / DEFAULT_SCHEMA_PATH
        if default_path.exists():
            return default_path.resolve()
        bundled = bundled_asset_path("schemas/learning-proposal.schema.json")
        return bundled if bundled.exists() else None

    if schema_path.exists():
        return schema_path.resolve()

    if schema_path == DEFAULT_SCHEMA_PATH:
        default_path = Path.cwd() / DEFAULT_SCHEMA_PATH
        if default_path.exists():
            return default_path.resolve()
        bundled = bundled_asset_path("schemas/learning-proposal.schema.json")
        return bundled if bundled.exists() else schema_path

    return schema_path


def resolve_operator_issue_schema_path(schema_path: Optional[Path]) -> Optional[Path]:
    """Resolve the kyoko.issue.v1 schema path for the diagnosis turn. Mirrors
    :func:`resolve_operator_schema_path` but never substitutes the LearningProposal
    schema: a caller-supplied LearningProposal default path is ignored in favor of the
    issue schema."""

    default_docs = Path("docs/schemas/issue.schema.json")
    if schema_path is not None and schema_path.exists() and schema_path != DEFAULT_SCHEMA_PATH:
        return schema_path.resolve()
    local = Path.cwd() / default_docs
    if local.exists():
        return local.resolve()
    bundled = bundled_asset_path("schemas/issue.schema.json")
    return bundled if bundled.exists() else None


def build_diagnosis_prompt(
    *,
    bundle: dict[str, Any],
    evidence_path: Path,
    target: str = "generic",
    schema_path: Optional[Path] = None,
) -> str:
    """Diagnosis turn: instruct the operator to read the evidence and return a JSON array
    of ``kyoko.issue.v1`` issues — diagnosis only, no fixes/proposals/skillbook edits."""

    summary = bundle.get("summary", {})
    redaction = bundle.get("redaction") if isinstance(bundle.get("redaction"), dict) else {}
    redaction_policy = redaction.get("policy") if isinstance(redaction.get("policy"), dict) else {}
    payload_access = redaction_policy.get("payload_access", "unknown")
    redact_sensitive_values = redaction_policy.get("redact_sensitive_values", "unknown")
    profile_id = str(bundle.get("profile_id") or "")
    schema_display = str(schema_path) if schema_path is not None else "docs/schemas/issue.schema.json"
    target_note = _target_note(target)
    skeleton = [_issue_skeleton()]
    inline_evidence = _inline_evidence_json(bundle=bundle, evidence_path=evidence_path)

    return "\n".join(
        [
            "# Kyoko Diagnosis Task",
            "",
            f"Target operator: `{target}`",
            f"Evidence bundle: `{evidence_path}`",
            f"Issue schema: `{schema_display}`",
            "",
            "You are acting as Kyoko's analysis operator. Read the evidence bundle, identify one or more concrete agent failures, and return a JSON array of strict `kyoko.issue.v1` issues.",
            "",
            "This is a **diagnosis-only** turn. Do NOT propose fixes, do NOT author a LearningProposal, and do NOT edit the skillbook. A proposal is authored in a separate step after a human (or autonomous policy) accepts an issue.",
            "",
            target_note,
            "",
            "## Hard Constraints",
            "",
            "- Return exactly one issues block on stdout containing a JSON array (one or more issues).",
            "- Cite only evidence IDs that exist in the evidence bundle.",
            "- Each issue's `root_cause` is the diagnosis; do not include any fix, patch, or skill text.",
            "- Set `section` to `context` when a prompt/skillbook fix would address it, or `harness` when it needs a check, test, replay adapter, tool wrapper, or repository patch.",
            "- If evidence is insufficient for a concrete failure, return an empty array `[]`.",
            "",
            "## Evidence Privacy And Audit",
            "",
            f"- Payload access mode: `{payload_access}`",
            f"- Sensitive-value redaction: `{redact_sensitive_values}`",
            f"- Redacted field count: {redaction.get('redacted_count', 0)}",
            "- Treat redacted refs and secret placeholders as intentional privacy controls, not missing evidence.",
            "",
            "## Evidence Summary",
            "",
            f"- Profile: `{profile_id}`",
            f"- Runs: {summary.get('runs', 0)}",
            f"- Spans: {summary.get('spans', 0)}",
            f"- Failed spans: {summary.get('failed_spans', 0)}",
            f"- Tasks: {summary.get('tasks', 0)}",
            f"- Handoffs: {summary.get('handoffs', 0)}",
            "",
            "## Evidence Bundle JSON",
            "",
            "The inline JSON below is the evidence to cite from. If it is marked as truncated, read the full evidence bundle path above.",
            "",
            "```json",
            inline_evidence,
            "```",
            "",
            "## Required Stdout",
            "",
            "```text",
            BEGIN_ISSUES_BLOCK,
            json.dumps(skeleton, indent=2, sort_keys=True),
            END_ISSUES_BLOCK,
            "```",
            "",
            "The JSON above is a shape guide, not the answer. Replace every placeholder with evidence-backed content, and emit one array element per distinct failure.",
            "",
        ]
    )


def build_proposal_authoring_prompt(
    *,
    bundle: dict[str, Any],
    evidence_path: Path,
    issue: dict[str, Any],
    target: str = "generic",
    schema_path: Optional[Path] = None,
) -> str:
    """Proposal-authoring turn: given ONE accepted issue, instruct the operator to return
    exactly one ``LearningProposal`` whose ``proposed_changes`` fix THIS issue."""

    profile_id = str(bundle.get("profile_id") or "")
    capabilities = bundle.get("check_capabilities") if isinstance(bundle.get("check_capabilities"), dict) else {}
    schema_display = str(schema_path) if schema_path is not None else "docs/schemas/learning-proposal.schema.json"
    target_note = _target_note(target)
    skeleton = _proposal_skeleton(profile_id)
    inline_evidence = _inline_evidence_json(bundle=bundle, evidence_path=evidence_path)

    issue_id = str(issue.get("id") or "")
    issue_title = str(issue.get("title") or "")
    issue_section = str(issue.get("section") or "context")
    issue_root_cause = str(issue.get("root_cause") or "")
    issue_body = str(issue.get("body") or "")
    issue_evidence = issue.get("evidence_refs") if isinstance(issue.get("evidence_refs"), list) else []

    return "\n".join(
        [
            "# Kyoko Proposal Authoring Task",
            "",
            f"Target operator: `{target}`",
            f"Evidence bundle: `{evidence_path}`",
            f"LearningProposal schema: `{schema_display}`",
            "",
            "You are acting as Kyoko's analysis operator. An Issue has already been diagnosed and accepted for a fix. Author exactly one strict LearningProposal whose `proposed_changes` fix THIS issue.",
            "",
            target_note,
            "",
            "## Accepted Issue",
            "",
            f"- Issue id: `{issue_id}` (Kyoko injects `issue_id` for you — do not invent or change it)",
            f"- Title: {issue_title}",
            f"- Section: `{issue_section}` (your proposal's `section` must match this)",
            f"- Root cause: {issue_root_cause}",
            *([f"- Body: {issue_body}"] if issue_body else []),
            "- Issue evidence refs:",
            *[f"  - `{ref.get('entity_type')}:{ref.get('entity_id')}`" for ref in issue_evidence if isinstance(ref, dict)],
            "",
            "## Hard Constraints",
            "",
            "- Return exactly one proposal block on stdout.",
            "- The proposal must fix the accepted issue above and nothing else.",
            f"- Set `section` to `{issue_section}` to match the accepted issue.",
            "- Cite only evidence IDs that exist in the evidence bundle (reuse the issue's evidence where it applies).",
            "- Do not set `issue_id` yourself; Kyoko injects it from the accepted issue.",
            "- Do not apply proposals, patch files, mutate the skillbook, or change autonomy policy.",
            "- Keep generated checks at `L0_generated`; Kyoko promotes trust only after replay/check evidence.",
            "",
            "## Check Capabilities",
            "",
            *_check_capability_lines(capabilities),
            "",
            "## Evidence Bundle JSON",
            "",
            "The inline JSON below is the evidence to cite from. If it is marked as truncated, read the full evidence bundle path above.",
            "",
            "```json",
            inline_evidence,
            "```",
            "",
            "## Required Stdout",
            "",
            "```text",
            BEGIN_PROPOSAL_BLOCK,
            json.dumps(skeleton, indent=2, sort_keys=True),
            END_PROPOSAL_BLOCK,
            "```",
            "",
            "The JSON above is a shape guide, not the answer. Replace every placeholder with evidence-backed content that fixes the accepted issue.",
            "",
        ]
    )


def _issue_skeleton() -> dict[str, Any]:
    return {
        "schema_version": "kyoko.issue.v1",
        "title": "Short evidence-backed failure title",
        "section": "context",
        "root_cause": "Evidence-backed diagnosis of why the agent failed.",
        "severity": "medium",
        "evidence_refs": [
            {
                "entity_type": "span",
                "entity_id": "replace_with_existing_span_id",
                "role": "failure",
                "note": "Why this evidence supports the diagnosis.",
            }
        ],
        "keywords": ["replace", "with", "specific", "terms"],
        "affected_span_ids": ["replace_with_existing_span_id"],
        "affected_agent_identity_ids": ["replace_with_existing_agent_identity_id"],
    }


def _check_capability_lines(capabilities: dict[str, Any]) -> list[str]:
    gateable = capabilities.get("gateable_check_types") if isinstance(capabilities.get("gateable_check_types"), list) else []
    executable = capabilities.get("executable_check_types") if isinstance(capabilities.get("executable_check_types"), list) else []
    replay = capabilities.get("replay") if isinstance(capabilities.get("replay"), dict) else {}
    safe_modes = replay.get("safe_side_effect_modes") if isinstance(replay.get("safe_side_effect_modes"), list) else []
    presets = capabilities.get("assertion_presets") if isinstance(capabilities.get("assertion_presets"), list) else []
    preset_names = [preset.get("name") for preset in presets if isinstance(preset, dict) and isinstance(preset.get("name"), str)]
    deterministic = capabilities.get("deterministic_assertions") if isinstance(capabilities.get("deterministic_assertions"), list) else []
    assertion_names = [
        assertion.get("name")
        for assertion in deterministic
        if isinstance(assertion, dict) and isinstance(assertion.get("name"), str)
    ]
    return [
        f"- Executable check types: `{_joined(executable)}`",
        f"- Check types that can gate autonomy: `{_joined(gateable)}`",
        "- `judge` and `smoke_run` are informational only; do not rely on them as sole autonomy gates.",
        f"- Safe replay side-effect modes: `{_joined(safe_modes)}`",
        f"- Deterministic assertions: `{_joined(assertion_names)}`",
        f"- Assertion presets: `{_joined(preset_names)}`",
        "- Prefer deterministic assertions or assertion presets tied to cited failure evidence.",
    ]


def _joined(values: list[Any]) -> str:
    cleaned = [str(value) for value in values if isinstance(value, str) and value]
    return "`, `".join(cleaned) if cleaned else "none"


def _inline_evidence_json(
    *,
    bundle: dict[str, Any],
    evidence_path: Path,
    max_chars: int = INLINE_EVIDENCE_MAX_CHARS,
) -> str:
    encoded = json.dumps(bundle, indent=2, sort_keys=True)
    if len(encoded) <= max_chars:
        return encoded
    return json.dumps(
        {
            "truncated": True,
            "max_chars": max_chars,
            "full_evidence_path": str(evidence_path),
            "prefix": encoded[:max_chars],
        },
        indent=2,
        sort_keys=True,
    )


def _target_note(target: str) -> str:
    notes = {
        "codex": "Codex note: use your normal local subscription/runtime for reasoning, but the only Kyoko output should be the delimited proposal block.",
        "claude": "Claude note: use the local Claude Code session for reasoning, but do not emit markdown instead of the delimited proposal block.",
        "hermes": "Hermes note: treat Hermes profile/task/queue/handoff evidence as source data unless this run is explicitly registered as an operator adapter.",
        "openclaw": "OpenClaw note: treat OpenClaw agent/session/workspace evidence as source data unless this run is explicitly registered as an operator adapter.",
        "generic": "Generic note: if your CLI can read stdin, this prompt is also passed on stdin. The evidence path is provided through `KYOKO_EVIDENCE_PATH`.",
        "mock": "Mock note: deterministic tests may use this prompt only as an operator contract fixture.",
    }
    return notes.get(target, notes["generic"])


def _proposal_skeleton(profile_id: str) -> dict[str, Any]:
    return {
        "schema_version": "kyoko.learning_proposal.v1",
        "id": "proposal_replace_with_stable_id",
        "profile_id": profile_id,
        "producer": {
            "kind": "operator_agent",
            "name": "replace_with_operator_name",
            "session_id": "replace_with_session_id",
        },
        "state": "pending",
        "section": "context",
        "title": "Short evidence-backed title",
        "summary": "One or two sentences explaining the proposed improvement.",
        "confidence": 0.5,
        "evidence_refs": [
            {
                "entity_type": "span",
                "entity_id": "replace_with_existing_span_id",
                "role": "failure",
                "note": "Why this evidence supports the proposal.",
            }
        ],
        "problem": {
            "issue": "Observed issue phrased as a reusable failure pattern.",
            "severity": "medium",
            "root_cause": "Evidence-backed root cause.",
            "target": {
                "entity_type": "agent_identity",
                "entity_id": "replace_with_existing_agent_identity_id",
            },
        },
        "insight": "Reusable operational guidance or harness improvement.",
        "proposed_changes": [
            {
                "type": "skillbook_update",
                "operation": "create",
                "section": "context",
                "issue": "Same reusable issue text.",
                "insight": "Same reusable guidance.",
                "keywords": ["replace", "with", "specific", "terms"],
                "occurrence_refs": [
                    {
                        "entity_type": "span",
                        "entity_id": "replace_with_existing_span_id",
                        "role": "failure",
                    }
                ],
            }
        ],
        "gate_expectations": {
            "requires_human_review": False,
            "requires_check_level": "L1_repeated",
            "requires_replay": False,
            "allowed_autonomy_section": "context",
            "notes": "Explain what Kyoko should verify before apply.",
        },
        "created_at": "replace_with_current_iso8601_utc",
    }
