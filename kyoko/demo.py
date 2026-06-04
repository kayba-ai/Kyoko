from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .apply import ApplyError, apply_context_proposal, list_skills
from .bundled_assets import AssetError, load_bundled_json
from .checks import CheckError, generate_checks_for_proposal
from .proposals import ProposalError, list_learning_proposals, submit_learning_proposal_payload
from .replay_adapters import ReplayAdapterError, register_replay_adapter, run_registered_replay_adapter
from .storage import (
    StorageError,
    get_database_status,
    ingest_source_fixture,
    ingest_source_payload,
    initialize_database,
    status_to_json,
)


DEMO_ADAPTER_ID = "fixture_replay"
DEMO_PROPOSAL_ID = "proposal_context_timeout_001"


class DemoError(Exception):
    """Raised when the bundled first-run demo cannot complete."""


@dataclass(frozen=True)
class DemoReport:
    db_path: Path
    profile_id: str
    proposal_id: str
    proposal_created: bool
    check_spec_ids: tuple[str, ...]
    check_spec_created_ids: tuple[str, ...]
    check_spec_existing_ids: tuple[str, ...]
    adapter_id: str
    output_dir: Path
    replay_run_id: Optional[str]
    check_run_id: Optional[str]
    check_status: Optional[str]
    promoted_trust_level: Optional[str]
    applied_skill_ids: tuple[str, ...]
    status: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "profile_id": self.profile_id,
            "proposal_id": self.proposal_id,
            "proposal_created": self.proposal_created,
            "check_spec_ids": list(self.check_spec_ids),
            "check_spec_created_ids": list(self.check_spec_created_ids),
            "check_spec_existing_ids": list(self.check_spec_existing_ids),
            "adapter_id": self.adapter_id,
            "output_dir": str(self.output_dir),
            "replay_run_id": self.replay_run_id,
            "check_run_id": self.check_run_id,
            "check_status": self.check_status,
            "promoted_trust_level": self.promoted_trust_level,
            "applied_skill_ids": list(self.applied_skill_ids),
            "status": self.status,
        }


def run_demo_setup(
    *,
    db_path: Path,
    output_dir: Optional[Path] = None,
    run_loop: bool = True,
    apply_context: bool = True,
    root: Optional[Path] = None,
) -> DemoReport:
    """Run the bundled local demo loop against a Kyoko SQLite database."""

    selected_output_dir = output_dir or db_path.parent / ".kyoko" / "demo-replay"

    try:
        source_payload = _demo_source_payload(root)
        proposal_payload = _demo_proposal_payload(root)
    except AssetError as exc:
        raise DemoError(str(exc)) from exc

    try:
        initialize_database(db_path)
        ingest_report = _ingest_demo_source(
            db_path=db_path,
            source_payload=source_payload,
            root=root,
        )
        proposal_created = _ensure_demo_proposal(
            db_path=db_path,
            proposal=proposal_payload,
        )
        check_report = generate_checks_for_proposal(
            db_path=db_path,
            proposal_id=DEMO_PROPOSAL_ID,
        )
        check_spec_ids = tuple(check_report.check_spec_ids + check_report.existing_check_spec_ids)
        if not check_spec_ids:
            raise DemoError(f"demo_check_not_available:{DEMO_PROPOSAL_ID}")

        register_replay_adapter(
            db_path=db_path,
            adapter_id=DEMO_ADAPTER_ID,
            name="Fixture replay",
            command=[sys.executable, "-m", "kyoko.fixture_replay"],
            profile_id=ingest_report.profile_id,
            output_dir=selected_output_dir,
            default_mode="dry_run",
            default_side_effect_mode="network_mocked",
            timeout_seconds=120,
            enabled=True,
            metadata={"demo": True, "fixture": "hermes-news-research-minimal"},
        )

        replay_run_id = None
        check_run_id = None
        check_status = None
        promoted_trust_level = None
        if run_loop:
            replay_report = run_registered_replay_adapter(
                db_path=db_path,
                adapter_id=DEMO_ADAPTER_ID,
                check_spec_id=check_spec_ids[0],
                run_check_after=True,
            )
            replay_run_id = replay_report.replay_run_id
            if replay_report.check_run is None:
                raise DemoError(f"demo_check_not_run:{check_spec_ids[0]}")
            check_run_id = replay_report.check_run.check_run_id
            check_status = replay_report.check_run.status
            promoted_trust_level = replay_report.check_run.promoted_trust_level

        applied_skill_ids: tuple[str, ...] = ()
        if apply_context:
            if not run_loop:
                raise DemoError("demo_apply_requires_run_loop")
            if check_status != "passed":
                raise DemoError(f"demo_apply_requires_passing_check:{check_status}")
            applied_skill_ids = _ensure_demo_skill_applied(db_path)

        database_status = status_to_json(get_database_status(db_path))
    except (ApplyError, CheckError, ProposalError, ReplayAdapterError, StorageError) as exc:
        raise DemoError(str(exc)) from exc

    return DemoReport(
        db_path=db_path,
        profile_id=ingest_report.profile_id,
        proposal_id=DEMO_PROPOSAL_ID,
        proposal_created=proposal_created,
        check_spec_ids=check_spec_ids,
        check_spec_created_ids=tuple(check_report.check_spec_ids),
        check_spec_existing_ids=tuple(check_report.existing_check_spec_ids),
        adapter_id=DEMO_ADAPTER_ID,
        output_dir=selected_output_dir,
        replay_run_id=replay_run_id,
        check_run_id=check_run_id,
        check_status=check_status,
        promoted_trust_level=promoted_trust_level,
        applied_skill_ids=applied_skill_ids,
        status=database_status,
    )


def _ensure_demo_proposal(
    *,
    db_path: Path,
    proposal: dict[str, Any],
) -> bool:
    existing = {proposal["id"] for proposal in list_learning_proposals(db_path)}
    if DEMO_PROPOSAL_ID in existing:
        return False

    submit_learning_proposal_payload(
        db_path=db_path,
        proposal=proposal,
        schema_path=None,
    )
    return True


def _ensure_demo_skill_applied(db_path: Path) -> tuple[str, ...]:
    existing = _skill_ids_for_demo_proposal(db_path)
    if existing:
        return existing

    report = apply_context_proposal(db_path=db_path, proposal_id=DEMO_PROPOSAL_ID)
    return tuple(report.applied_skill_ids)


def _skill_ids_for_demo_proposal(db_path: Path) -> tuple[str, ...]:
    skills = list_skills(db_path)
    return tuple(
        str(skill["id"])
        for skill in skills
        if skill.get("proposal_id") == DEMO_PROPOSAL_ID
    )


def _demo_source_payload(root: Optional[Path]) -> dict[str, Any]:
    if root is not None:
        source_fixture = root / "docs/fixtures/source-events/hermes-news-research-minimal.json"
        _require_file(source_fixture)
        return _load_json_file(source_fixture)
    return load_bundled_json("source-events/hermes-news-research-minimal.json")


def _demo_proposal_payload(root: Optional[Path]) -> dict[str, Any]:
    if root is not None:
        proposal_fixture = root / "docs/fixtures/learning-proposals/valid-context-proposal.json"
        _require_file(proposal_fixture)
        return _load_json_file(proposal_fixture)
    return load_bundled_json("learning-proposals/valid-context-proposal.json")


def _ingest_demo_source(
    *,
    db_path: Path,
    source_payload: dict[str, Any],
    root: Optional[Path],
):
    if root is not None:
        source_fixture = root / "docs/fixtures/source-events/hermes-news-research-minimal.json"
        return ingest_source_fixture(db_path, source_fixture)
    return ingest_source_payload(
        db_path=db_path,
        fixture=source_payload,
        source_label="bundled:source-events/hermes-news-research-minimal.json",
    )


def _load_json_file(path: Path) -> dict[str, Any]:
    import json

    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise DemoError(f"demo_json_object_required:{path}")
    return payload


def _require_file(path: Path) -> None:
    if not path.exists():
        raise DemoError(f"demo_file_not_found:{path}")
