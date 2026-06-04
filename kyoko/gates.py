from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ENTITY_COLLECTIONS = {
    "profile": "profile",
    "source": "sources",
    "agent_identity": "agent_identities",
    "workflow_node": "workflow_nodes",
    "run": "runs",
    "span": "spans",
    "queue": "queues",
    "task": "tasks",
    "task_attempt": "task_attempts",
    "handoff": "handoffs",
    "timeline_event": "timeline_events",
}


@dataclass(frozen=True)
class GateArtifactPaths:
    schema: Path
    source_fixture: Path
    replay_fixture: Path
    valid_proposal: Path
    hermes_operator_proposal: Path
    openclaw_operator_proposal: Path
    valid_harness_proposal: Path
    valid_generated_file_harness_proposal: Path
    invalid_proposal: Path
    bundled_schema: Path
    bundled_source_fixture: Path
    bundled_replay_fixture: Path
    bundled_valid_proposal: Path
    bundled_hermes_operator_proposal: Path
    bundled_openclaw_operator_proposal: Path
    bundled_valid_harness_proposal: Path
    bundled_valid_generated_file_harness_proposal: Path
    bundled_invalid_proposal: Path

    @classmethod
    def from_root(cls, root: Path) -> "GateArtifactPaths":
        return cls(
            schema=root / "docs/schemas/learning-proposal.schema.json",
            source_fixture=root / "docs/fixtures/source-events/hermes-news-research-minimal.json",
            replay_fixture=root
            / "docs/fixtures/replay-results/researcher-fetch-timeout-success.json",
            valid_proposal=root / "docs/fixtures/learning-proposals/valid-context-proposal.json",
            hermes_operator_proposal=root
            / "docs/fixtures/learning-proposals/hermes-one-shot-proposal.json",
            openclaw_operator_proposal=root
            / "docs/fixtures/learning-proposals/openclaw-local-operator-proposal.json",
            valid_harness_proposal=root
            / "docs/fixtures/learning-proposals/valid-harness-proposal.json",
            valid_generated_file_harness_proposal=root
            / "docs/fixtures/learning-proposals/valid-harness-generated-file-proposal.json",
            invalid_proposal=root
            / "docs/fixtures/learning-proposals/invalid-hallucinated-span.json",
            bundled_schema=root / "kyoko/assets/schemas/learning-proposal.schema.json",
            bundled_source_fixture=root
            / "kyoko/assets/source-events/hermes-news-research-minimal.json",
            bundled_replay_fixture=root
            / "kyoko/assets/replay-results/researcher-fetch-timeout-success.json",
            bundled_valid_proposal=root
            / "kyoko/assets/learning-proposals/valid-context-proposal.json",
            bundled_hermes_operator_proposal=root
            / "kyoko/assets/learning-proposals/hermes-one-shot-proposal.json",
            bundled_openclaw_operator_proposal=root
            / "kyoko/assets/learning-proposals/openclaw-local-operator-proposal.json",
            bundled_valid_harness_proposal=root
            / "kyoko/assets/learning-proposals/valid-harness-proposal.json",
            bundled_valid_generated_file_harness_proposal=root
            / "kyoko/assets/learning-proposals/valid-harness-generated-file-proposal.json",
            bundled_invalid_proposal=root
            / "kyoko/assets/learning-proposals/invalid-hallucinated-span.json",
        )


@dataclass(frozen=True)
class ValidationReport:
    messages: tuple[str, ...]


class ValidationError(Exception):
    """Raised when a gate artifact fails validation."""


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise ValidationError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path}: invalid JSON: {exc}") from exc


def collect_ids(source_fixture: dict[str, Any]) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {entity_type: set() for entity_type in ENTITY_COLLECTIONS}

    profile = source_fixture.get("profile")
    if isinstance(profile, dict) and isinstance(profile.get("id"), str):
        ids["profile"].add(profile["id"])
    else:
        raise ValidationError("source fixture profile is missing string id")

    for entity_type, collection_name in ENTITY_COLLECTIONS.items():
        if collection_name == "profile":
            continue
        collection = source_fixture.get(collection_name, [])
        if not isinstance(collection, list):
            raise ValidationError(f"{collection_name} must be a list")
        for row in collection:
            if not isinstance(row, dict):
                raise ValidationError(f"{collection_name} contains a non-object row")
            row_id = row.get("id")
            if not isinstance(row_id, str):
                raise ValidationError(f"{collection_name} row is missing string id")
            if row_id in ids[entity_type]:
                raise ValidationError(f"{collection_name} has duplicate id {row_id}")
            ids[entity_type].add(row_id)

    return ids


def proposal_evidence_refs(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    top_level_refs = proposal.get("evidence_refs", [])
    if isinstance(top_level_refs, list):
        refs.extend(ref for ref in top_level_refs if isinstance(ref, dict))

    proposed_changes = proposal.get("proposed_changes", [])
    if not isinstance(proposed_changes, list):
        return refs

    for change in proposed_changes:
        if not isinstance(change, dict):
            continue
        occurrence_refs = change.get("occurrence_refs", [])
        if isinstance(occurrence_refs, list):
            refs.extend(ref for ref in occurrence_refs if isinstance(ref, dict))

    return refs


def missing_evidence_refs(proposal: dict[str, Any], ids: dict[str, set[str]]) -> list[str]:
    missing: list[str] = []

    for ref in proposal_evidence_refs(proposal):
        entity_type = ref.get("entity_type")
        entity_id = ref.get("entity_id")
        if not isinstance(entity_type, str) or not isinstance(entity_id, str):
            missing.append(f"{entity_type}:{entity_id}")
            continue
        if entity_type not in ids:
            # Types such as blob, issue, eval_run, replay_run, and patch_transaction
            # are valid evidence targets but are not included in this source fixture.
            continue
        if entity_id not in ids[entity_type]:
            missing.append(f"{entity_type}:{entity_id}")

    return missing


def validate_json_schema_if_available(
    schema: dict[str, Any],
    proposal_paths: list[Path],
    *,
    require_jsonschema: bool = False,
) -> str:
    try:
        import jsonschema
    except ImportError as exc:
        if require_jsonschema:
            raise ValidationError("jsonschema is required for strict schema validation") from exc
        return "schema: skipped JSON Schema validation because jsonschema is not installed"

    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    for path in proposal_paths:
        proposal = load_json(path)
        proposal_errors = sorted(validator.iter_errors(proposal), key=lambda err: list(err.path))
        errors.extend(f"{path}: {list(error.path)}: {error.message}" for error in proposal_errors)

    if errors:
        raise ValidationError("\n".join(errors))
    return "schema: proposal fixtures conform to learning-proposal.schema.json"


def validate_gate_artifacts(
    *,
    root: Path,
    require_jsonschema: bool = False,
) -> ValidationReport:
    paths = GateArtifactPaths.from_root(root.resolve())

    schema = load_json(paths.schema)
    source_fixture = load_json(paths.source_fixture)
    replay_fixture = load_json(paths.replay_fixture)
    valid_proposal = load_json(paths.valid_proposal)
    hermes_operator_proposal = load_json(paths.hermes_operator_proposal)
    openclaw_operator_proposal = load_json(paths.openclaw_operator_proposal)
    valid_harness_proposal = load_json(paths.valid_harness_proposal)
    valid_generated_file_harness_proposal = load_json(paths.valid_generated_file_harness_proposal)
    invalid_proposal = load_json(paths.invalid_proposal)

    messages = [
        validate_json_schema_if_available(
            schema,
            [
                paths.valid_proposal,
                paths.hermes_operator_proposal,
                paths.openclaw_operator_proposal,
                paths.valid_harness_proposal,
                paths.valid_generated_file_harness_proposal,
                paths.invalid_proposal,
            ],
            require_jsonschema=require_jsonschema,
        )
    ]

    ids = collect_ids(source_fixture)

    valid_missing = missing_evidence_refs(valid_proposal, ids)
    if valid_missing:
        raise ValidationError(
            f"{paths.valid_proposal}: expected no missing evidence refs, got {valid_missing}"
        )

    hermes_operator_missing = missing_evidence_refs(hermes_operator_proposal, ids)
    if hermes_operator_missing:
        raise ValidationError(
            f"{paths.hermes_operator_proposal}: expected no missing evidence refs, "
            f"got {hermes_operator_missing}"
        )

    openclaw_operator_missing = missing_evidence_refs(openclaw_operator_proposal, ids)
    if openclaw_operator_missing:
        raise ValidationError(
            f"{paths.openclaw_operator_proposal}: expected no missing evidence refs, "
            f"got {openclaw_operator_missing}"
        )

    valid_harness_missing = missing_evidence_refs(valid_harness_proposal, ids)
    if valid_harness_missing:
        raise ValidationError(
            f"{paths.valid_harness_proposal}: expected no missing evidence refs, "
            f"got {valid_harness_missing}"
        )

    valid_generated_file_missing = missing_evidence_refs(valid_generated_file_harness_proposal, ids)
    if valid_generated_file_missing:
        raise ValidationError(
            f"{paths.valid_generated_file_harness_proposal}: expected no missing evidence refs, "
            f"got {valid_generated_file_missing}"
        )

    invalid_missing = missing_evidence_refs(invalid_proposal, ids)
    expected_missing = ["span:span_does_not_exist_999", "span:span_does_not_exist_999"]
    if invalid_missing != expected_missing:
        raise ValidationError(
            f"{paths.invalid_proposal}: expected missing refs {expected_missing}, "
            f"got {invalid_missing}"
        )

    messages.append("semantic: valid proposal evidence refs resolve")
    messages.append("semantic: Hermes operator proposal evidence refs resolve")
    messages.append("semantic: OpenClaw operator proposal evidence refs resolve")
    messages.append("semantic: valid harness proposal evidence refs resolve")
    messages.append("semantic: valid generated-file harness proposal evidence refs resolve")
    messages.append("semantic: invalid proposal fails for expected hallucinated span")
    messages.append(_validate_replay_fixture(source_fixture, replay_fixture, paths.replay_fixture))
    messages.extend(_validate_bundled_asset_mirrors(paths))
    return ValidationReport(messages=tuple(messages))


def _validate_bundled_asset_mirrors(paths: GateArtifactPaths) -> tuple[str, ...]:
    pairs = (
        (
            paths.schema,
            paths.bundled_schema,
            "bundled: runtime schema mirrors docs schema",
        ),
        (
            paths.source_fixture,
            paths.bundled_source_fixture,
            "bundled: runtime source fixture mirrors docs source fixture",
        ),
        (
            paths.valid_proposal,
            paths.bundled_valid_proposal,
            "bundled: runtime proposal fixture mirrors docs proposal fixture",
        ),
        (
            paths.hermes_operator_proposal,
            paths.bundled_hermes_operator_proposal,
            "bundled: runtime Hermes operator proposal fixture mirrors docs proposal fixture",
        ),
        (
            paths.openclaw_operator_proposal,
            paths.bundled_openclaw_operator_proposal,
            "bundled: runtime OpenClaw operator proposal fixture mirrors docs proposal fixture",
        ),
        (
            paths.valid_harness_proposal,
            paths.bundled_valid_harness_proposal,
            "bundled: runtime harness proposal fixture mirrors docs proposal fixture",
        ),
        (
            paths.valid_generated_file_harness_proposal,
            paths.bundled_valid_generated_file_harness_proposal,
            "bundled: runtime generated-file harness proposal fixture mirrors docs proposal fixture",
        ),
        (
            paths.invalid_proposal,
            paths.bundled_invalid_proposal,
            "bundled: runtime invalid proposal fixture mirrors docs proposal fixture",
        ),
        (
            paths.replay_fixture,
            paths.bundled_replay_fixture,
            "bundled: runtime replay fixture mirrors docs replay fixture",
        ),
    )
    messages: list[str] = []
    for docs_path, bundled_path, message in pairs:
        docs_payload = load_json(docs_path)
        bundled_payload = load_json(bundled_path)
        if bundled_payload != docs_payload:
            raise ValidationError(
                f"{bundled_path}: bundled asset does not mirror {docs_path}"
            )
        messages.append(message)
    return tuple(messages)


def _validate_replay_fixture(
    source_fixture: dict[str, Any],
    replay_fixture: dict[str, Any],
    replay_fixture_path: Path,
) -> str:
    source_ids = collect_ids(source_fixture)
    replay_ids = collect_ids(replay_fixture)

    source_profile_id = next(iter(source_ids["profile"]))
    replay_profile_id = next(iter(replay_ids["profile"]))
    if replay_profile_id != source_profile_id:
        raise ValidationError(
            f"{replay_fixture_path}: profile mismatch {replay_profile_id} != {source_profile_id}"
        )

    replay = replay_fixture.get("replay")
    if not isinstance(replay, dict):
        raise ValidationError(f"{replay_fixture_path}: missing replay object")
    output_run_id = replay.get("output_run_id")
    if not isinstance(output_run_id, str) or output_run_id not in replay_ids["run"]:
        raise ValidationError(f"{replay_fixture_path}: replay output_run_id does not resolve")

    target_map = replay.get("target_map")
    if not isinstance(target_map, dict) or not target_map:
        raise ValidationError(f"{replay_fixture_path}: replay target_map is required")

    source_spans = {span["id"]: span for span in source_fixture.get("spans", []) if isinstance(span, dict)}
    replay_spans = {span["id"]: span for span in replay_fixture.get("spans", []) if isinstance(span, dict)}
    for source_span_id, replay_span_id in target_map.items():
        if source_span_id not in source_ids["span"]:
            raise ValidationError(f"{replay_fixture_path}: source span {source_span_id} does not resolve")
        if replay_span_id not in replay_ids["span"]:
            raise ValidationError(f"{replay_fixture_path}: replay span {replay_span_id} does not resolve")
        if source_spans[source_span_id].get("status") not in {"failed", "timed_out"}:
            raise ValidationError(f"{replay_fixture_path}: source span {source_span_id} is not a failure")
        if replay_spans[replay_span_id].get("status") in {"failed", "timed_out", "cancelled"}:
            raise ValidationError(f"{replay_fixture_path}: replay span {replay_span_id} is not successful")

    return "semantic: replay fixture maps failed source span to successful replay span"
