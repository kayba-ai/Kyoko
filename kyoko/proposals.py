from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .bundled_assets import AssetError, load_bundled_json
from .confidence import assess_proposal_confidence
from .gates import load_json, proposal_evidence_refs
from .issues import create_issue, link_proposal_to_issue
from .storage import StorageError, connect, initialize_database
from .vocabulary import section_description, section_label


DEFAULT_SCHEMA_PATH = Path("docs/schemas/learning-proposal.schema.json")


# Collapsed proposal state machine: 3 user-facing states + 1 internal ("failed").
# Legacy producers/fixtures may still emit any of the old 10 states; normalize them
# through this mapping so stored state is always one of the canonical four.
PROPOSAL_STATES = ("pending", "applied", "rolled_back", "failed")

_LEGACY_STATE_MAP = {
    # pending ← any not-yet-acted-on working state
    "draft": "pending",
    "proposed": "pending",
    "gated": "pending",
    "approved": "pending",
    "applying": "pending",
    "pending": "pending",
    # applied (terminal success)
    "applied": "applied",
    # rolled_back ← supersession / harness rollback
    "superseded": "rolled_back",
    "rolled_back": "rolled_back",
    # failed (internal terminal) ← any error/rejection; detail kept in reason/error
    "failed": "failed",
    "invalid": "failed",
    "rejected": "failed",
}


def normalize_proposal_state(state: Any) -> str:
    """Map any (possibly legacy) state string onto the collapsed 4-state model."""
    if not isinstance(state, str) or not state:
        return "pending"
    return _LEGACY_STATE_MAP.get(state, "pending")


ENTITY_TABLES = {
    "profile": "profiles",
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
    "proposal": "learning_proposals",
    "learning_proposal": "learning_proposals",
    "issue": "issues",
    "skill": "skills",
    "context_delivery_rule": "context_delivery_rules",
    "check_run": "check_runs",
    "replay_run": "replay_runs",
    "patch_transaction": "patch_transactions",
}


@dataclass(frozen=True)
class ProposalValidationResult:
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ProposalSubmitReport:
    proposal_id: str
    profile_id: str
    state: str
    section: str
    title: str


class ProposalError(Exception):
    """Raised when a proposal cannot be validated or persisted."""


def originate_issue_for_proposal(
    *,
    db_path: Path,
    proposal: dict[str, Any],
    source: str = "analysis",
    profile_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create the originating :class:`Issue` for ``proposal`` and stamp
    ``proposal["issue_id"]`` in place. This is the single chokepoint that enforces the
    issue-centric spine — every production proposal producer routes through here so a
    proposal can never exist without an issue. The issue is created already
    ``diagnosed`` (analysis both surfaces and diagnoses), carrying the proposal's
    ``insight`` as its root cause and the proposal's section/evidence.

    Returns the stored issue record. The caller submits the proposal, then calls
    :func:`kyoko.issues.link_proposal_to_issue` to backlink and advance to ``proposed``.
    """

    problem = proposal.get("problem") if isinstance(proposal.get("problem"), dict) else {}
    raw_title = problem.get("issue") or proposal.get("title") or "Surfaced agent failure"
    title = str(raw_title).strip()[:500] or "Surfaced agent failure"
    section = proposal.get("section") if proposal.get("section") in ("context", "harness") else None
    evidence_refs = proposal.get("evidence_refs") if isinstance(proposal.get("evidence_refs"), list) else []
    root_cause = proposal.get("insight") if isinstance(proposal.get("insight"), str) else None
    if not root_cause:
        rc = problem.get("root_cause") if isinstance(problem, dict) else None
        root_cause = rc if isinstance(rc, str) and rc.strip() else None
    body = proposal.get("summary") if isinstance(proposal.get("summary"), str) else None
    severity = _issue_severity_from_problem(problem)

    span_ids: list[str] = []
    target = problem.get("target") if isinstance(problem, dict) else None
    if (
        isinstance(target, dict)
        and target.get("entity_type") == "span"
        and isinstance(target.get("entity_id"), str)
    ):
        span_ids = [target["entity_id"]]

    issue = create_issue(
        db_path=db_path,
        title=title,
        body=body,
        section=section,
        category="analysis",
        severity=severity,
        status="diagnosed" if root_cause else "open",
        evidence_refs=evidence_refs,
        affected_span_ids=span_ids,
        source=source,
        root_cause=root_cause,
        profile_id=profile_id or proposal.get("profile_id"),
    )
    proposal["issue_id"] = issue["id"]
    return issue


def _issue_severity_from_problem(problem: dict[str, Any]) -> Optional[str]:
    """Map a proposal problem severity (info|low|medium|high|critical) onto the issue
    severity scale (low|medium|high)."""
    mapping = {
        "info": "low",
        "low": "low",
        "medium": "medium",
        "high": "high",
        "critical": "high",
    }
    raw = problem.get("severity") if isinstance(problem, dict) else None
    return mapping.get(raw) if isinstance(raw, str) else None


def submit_learning_proposal(
    *,
    db_path: Path,
    proposal_path: Path,
    schema_path: Optional[Path] = None,
    require_jsonschema: bool = False,
) -> ProposalSubmitReport:
    initialize_database(db_path)
    proposal = load_json(proposal_path)
    if not isinstance(proposal, dict):
        raise ProposalError(f"{proposal_path}: proposal must be a JSON object")
    return submit_learning_proposal_payload(
        db_path=db_path,
        proposal=proposal,
        schema_path=schema_path,
        require_jsonschema=require_jsonschema,
    )


def submit_learning_proposal_payload(
    *,
    db_path: Path,
    proposal: dict[str, Any],
    schema_path: Optional[Path] = None,
    require_jsonschema: bool = False,
) -> ProposalSubmitReport:
    initialize_database(db_path)
    proposal["state"] = normalize_proposal_state(proposal.get("state"))
    with connect(db_path) as connection:
        result = validate_learning_proposal(
            connection=connection,
            proposal=proposal,
            schema_path=schema_path,
            require_jsonschema=require_jsonschema,
        )
        if not result.ok:
            raise ProposalError("; ".join(result.errors))
        _insert_learning_proposal(connection, proposal)

    return ProposalSubmitReport(
        proposal_id=str(proposal["id"]),
        profile_id=str(proposal["profile_id"]),
        state=str(proposal["state"]),
        section=str(proposal["section"]),
        title=str(proposal["title"]),
    )


def validate_learning_proposal(
    *,
    connection: sqlite3.Connection,
    proposal: dict[str, Any],
    schema_path: Optional[Path] = None,
    require_jsonschema: bool = False,
) -> ProposalValidationResult:
    errors: list[str] = []

    errors.extend(_schema_errors(proposal, schema_path, require_jsonschema=require_jsonschema))
    if errors:
        return ProposalValidationResult(errors=tuple(errors))

    profile_id = _string_field(proposal, "profile_id")
    if not profile_id:
        errors.append("profile_id is required")
    elif not _row_exists(connection, "profiles", profile_id):
        errors.append(f"profile_not_found:{profile_id}")

    proposal_id = _string_field(proposal, "id")
    if proposal_id and _row_exists(connection, "learning_proposals", proposal_id):
        errors.append(f"proposal_already_exists:{proposal_id}")

    # The issue-centric spine: every proposal originates from an Issue. The field is
    # schema-optional (so legacy static fixtures validate) but referentially checked
    # when present; all production producers stamp it via originate_issue_for_proposal.
    issue_id = _string_field(proposal, "issue_id")
    if issue_id and not _row_exists(connection, "issues", issue_id):
        errors.append(f"issue_not_found:{issue_id}")

    producer = proposal.get("producer")
    if isinstance(producer, dict):
        agent_identity_id = producer.get("agent_identity_id")
        if isinstance(agent_identity_id, str) and not _row_exists(
            connection,
            "agent_identities",
            agent_identity_id,
        ):
            errors.append(f"producer_agent_not_found:{agent_identity_id}")

    problem = proposal.get("problem")
    if isinstance(problem, dict):
        target = problem.get("target")
        if isinstance(target, dict):
            missing = _missing_target_ref(connection, target)
            if missing:
                errors.append(missing)

    for ref in proposal_evidence_refs(proposal):
        missing = _missing_evidence_ref(connection, ref)
        if missing:
            errors.append(missing)

    section = proposal.get("section")
    for change in proposal.get("proposed_changes", []):
        if not isinstance(change, dict):
            continue
        change_type = change.get("type")
        if change_type == "skillbook_update" and change.get("section") != section:
            errors.append("change_section_mismatch:skillbook_update")
        if change_type == "harness_patch" and section != "harness":
            errors.append("change_section_mismatch:harness_patch")
        if change_type == "context_delivery_rule" and section != "context":
            errors.append("change_section_mismatch:context_delivery_rule")
        if change_type == "context_delivery_rule":
            target = change.get("target")
            if isinstance(target, dict):
                missing = _missing_target_ref(connection, target)
                if missing:
                    errors.append(f"change_{missing}")

    return ProposalValidationResult(errors=tuple(errors))


def list_learning_proposals(db_path: Path, *, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    with connect(db_path) as connection:
        try:
            where_sql = "WHERE profile_id = ?" if profile_id else ""
            params = (profile_id,) if profile_id else ()
            rows = connection.execute(
                f"""
                SELECT *
                FROM learning_proposals
                {where_sql}
                ORDER BY created_at DESC, id ASC
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

        proposals = []
        for row in rows:
            proposal = _decode_proposal_row(row)
            assessment = assess_proposal_confidence(connection=connection, proposal=proposal)
            proposals.append(
                {
                    "id": proposal["id"],
                    "profile_id": proposal["profile_id"],
                    "issue_id": proposal.get("issue_id"),
                    "state": proposal["state"],
                    "section": proposal["section"],
                    "section_label": section_label(proposal["section"]),
                    "section_description": section_description(proposal["section"]),
                    "title": proposal["title"],
                    "summary": proposal["summary"],
                    "confidence": proposal["confidence"],
                    "operator_confidence": assessment["operator_confidence"],
                    "kyoko_confidence": assessment["kyoko_confidence"],
                    "confidence_level": assessment["level"],
                    "confidence_delta": assessment["confidence_delta"],
                    "created_at": proposal["created_at"],
                }
            )

    return proposals


def _schema_errors(
    proposal: dict[str, Any],
    schema_path: Optional[Path],
    *,
    require_jsonschema: bool,
) -> list[str]:
    try:
        schema = _load_schema(schema_path)
    except Exception as exc:
        return [f"schema_load_failed:{exc}"]
    if schema is None:
        if require_jsonschema:
            return ["schema_not_found"]
        return []

    try:
        import jsonschema
    except ImportError:
        if require_jsonschema:
            return ["jsonschema_not_installed"]
        return []

    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"schema_error:{list(error.path)}:{error.message}"
        for error in sorted(validator.iter_errors(proposal), key=lambda err: list(err.path))
    ]


def _load_schema(schema_path: Optional[Path]) -> Optional[dict[str, Any]]:
    if schema_path is None:
        default_schema = Path.cwd() / DEFAULT_SCHEMA_PATH
        if default_schema.exists():
            payload = load_json(default_schema)
            if not isinstance(payload, dict):
                raise ProposalError(f"{default_schema}: schema must be a JSON object")
            return payload
        try:
            return load_bundled_json("schemas/learning-proposal.schema.json")
        except AssetError:
            return None

    if schema_path.exists():
        payload = load_json(schema_path)
        if not isinstance(payload, dict):
            raise ProposalError(f"{schema_path}: schema must be a JSON object")
        return payload

    if schema_path == DEFAULT_SCHEMA_PATH:
        return load_bundled_json("schemas/learning-proposal.schema.json")

    raise ProposalError(f"{schema_path}: schema not found")


def _insert_learning_proposal(connection: sqlite3.Connection, proposal: dict[str, Any]) -> None:
    validation_errors = proposal.get("validation_errors", [])
    if validation_errors is None:
        validation_errors = []

    connection.execute(
        """
        INSERT INTO learning_proposals (
          id,
          schema_version,
          profile_id,
          producer_json,
          state,
          section,
          title,
          summary,
          confidence,
          evidence_refs_json,
          problem_json,
          insight,
          proposed_changes_json,
          gate_expectations_json,
          validation_errors_json,
          issue_id,
          created_at,
          updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            proposal["id"],
            proposal["schema_version"],
            proposal["profile_id"],
            _json_value(proposal["producer"]),
            normalize_proposal_state(proposal.get("state")),
            proposal["section"],
            proposal["title"],
            proposal["summary"],
            proposal["confidence"],
            _json_value(proposal["evidence_refs"]),
            _json_value(proposal["problem"]),
            proposal["insight"],
            _json_value(proposal["proposed_changes"]),
            _json_value(proposal["gate_expectations"]),
            _json_value(validation_errors),
            proposal.get("issue_id"),
            proposal["created_at"],
            proposal.get("updated_at"),
        ),
    )


def _missing_evidence_ref(connection: sqlite3.Connection, ref: dict[str, Any]) -> Optional[str]:
    entity_type = ref.get("entity_type")
    entity_id = ref.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return f"invalid_evidence_ref:{entity_type}:{entity_id}"

    table = ENTITY_TABLES.get(entity_type)
    if table is None:
        # Blob and future check/replay/patch refs may exist outside the current
        # runtime slice. Validate them once those stores exist.
        return None

    if not _row_exists(connection, table, entity_id):
        return f"evidence_ref_not_found:{entity_type}:{entity_id}"
    return None


def _missing_target_ref(connection: sqlite3.Connection, ref: dict[str, Any]) -> Optional[str]:
    entity_type = ref.get("entity_type")
    entity_id = ref.get("entity_id")
    if not isinstance(entity_type, str) or not isinstance(entity_id, str):
        return f"invalid_target_ref:{entity_type}:{entity_id}"

    table = ENTITY_TABLES.get(entity_type)
    if table is None:
        return None

    if not _row_exists(connection, table, entity_id):
        return f"target_ref_not_found:{entity_type}:{entity_id}"
    return None


def _row_exists(connection: sqlite3.Connection, table: str, row_id: str) -> bool:
    try:
        row = connection.execute(f"SELECT 1 FROM {table} WHERE id = ? LIMIT 1", (row_id,)).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError(f"missing table {table}") from exc
    return row is not None


def _string_field(payload: dict[str, Any], field: str) -> Optional[str]:
    value = payload.get(field)
    return value if isinstance(value, str) else None


def _decode_proposal_row(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    for key in [
        "producer_json",
        "evidence_refs_json",
        "problem_json",
        "proposed_changes_json",
        "gate_expectations_json",
        "validation_errors_json",
    ]:
        value = payload.pop(key, None)
        decoded_key = key[: -len("_json")]
        payload[decoded_key] = _json_loads(value, [] if key.endswith("refs_json") or key.endswith("changes_json") or key.endswith("errors_json") else {})
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
