from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .storage import StorageError, connect, initialize_database, utc_now


@dataclass(frozen=True)
class ApplyReport:
    proposal_id: str
    profile_id: str
    applied_skill_ids: tuple[str, ...]
    applied_context_rule_ids: tuple[str, ...]
    state: str

    def to_json(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "profile_id": self.profile_id,
            "applied_skill_ids": list(self.applied_skill_ids),
            "applied_context_rule_ids": list(self.applied_context_rule_ids),
            "state": self.state,
        }


@dataclass(frozen=True)
class SkillLockReport:
    skill_id: str
    profile_id: str
    human_locked: bool
    reason: Optional[str] = None
    actor_agent_identity_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "profile_id": self.profile_id,
            "human_locked": self.human_locked,
            "reason": self.reason,
            "actor_agent_identity_id": self.actor_agent_identity_id,
        }


@dataclass(frozen=True)
class ContextDeliveryRuleLockReport:
    rule_id: str
    profile_id: str
    human_locked: bool
    reason: Optional[str] = None
    actor_agent_identity_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "profile_id": self.profile_id,
            "human_locked": self.human_locked,
            "reason": self.reason,
            "actor_agent_identity_id": self.actor_agent_identity_id,
        }


@dataclass(frozen=True)
class SkillRevisionRollbackReport:
    revision_id: str
    rollback_revision_id: str
    skill_id: str
    profile_id: str
    status: str

    def to_json(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "rollback_revision_id": self.rollback_revision_id,
            "skill_id": self.skill_id,
            "profile_id": self.profile_id,
            "status": self.status,
        }


@dataclass(frozen=True)
class ContextDeliveryRuleRevisionRollbackReport:
    revision_id: str
    rollback_revision_id: str
    rule_id: str
    profile_id: str
    status: str

    def to_json(self) -> dict[str, Any]:
        return {
            "revision_id": self.revision_id,
            "rollback_revision_id": self.rollback_revision_id,
            "rule_id": self.rule_id,
            "profile_id": self.profile_id,
            "status": self.status,
        }


class ApplyError(Exception):
    """Raised when a proposal cannot be applied."""


def apply_context_proposal(
    *,
    db_path: Path,
    proposal_id: str,
    allowed_states: tuple[str, ...] = ("pending",),
) -> ApplyReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        proposal = _get_proposal(connection, proposal_id)
        profile_id = str(proposal["profile_id"])
        _ensure_kyoko_source(connection, profile_id)
        _validate_apply_allowed(connection, proposal, allowed_states=allowed_states)

        now = utc_now()
        producer = _json_loads(proposal["producer_json"], {})
        agent_identity_id = producer.get("agent_identity_id") if isinstance(producer, dict) else None

        _insert_timeline_event(
            connection,
            event_id=f"event_{proposal_id}_apply_started",
            profile_id=profile_id,
            entity_type="learning_proposal",
            entity_id=proposal_id,
            kind="proposal_apply_started",
            at=now,
            agent_identity_id=agent_identity_id if isinstance(agent_identity_id, str) else None,
            metadata={"section": proposal["section"]},
        )

        applied_skill_ids = _apply_skillbook_updates(connection, proposal, now)
        applied_context_rule_ids = _apply_context_delivery_rules(connection, proposal, now)

        connection.execute(
            "UPDATE learning_proposals SET state = ?, updated_at = ? WHERE id = ?",
            ("applied", now, proposal_id),
        )

        _insert_timeline_event(
            connection,
            event_id=f"event_{proposal_id}_applied",
            profile_id=profile_id,
            entity_type="learning_proposal",
            entity_id=proposal_id,
            kind="proposal_applied",
            at=now,
            agent_identity_id=agent_identity_id if isinstance(agent_identity_id, str) else None,
            metadata={
                "skill_ids": list(applied_skill_ids),
                "context_delivery_rule_ids": list(applied_context_rule_ids),
            },
        )

    return ApplyReport(
        proposal_id=proposal_id,
        profile_id=profile_id,
        applied_skill_ids=tuple(applied_skill_ids),
        applied_context_rule_ids=tuple(applied_context_rule_ids),
        state="applied",
    )


@dataclass(frozen=True)
class IssueRollbackReport:
    """Result of reverting the applied fix for one issue (spec 0018 guard monitor)."""

    issue_id: str
    rolled_back_proposal_ids: tuple[str, ...]
    rolled_back_skill_revision_ids: tuple[str, ...]
    rolled_back_rule_revision_ids: tuple[str, ...]
    escalate: bool
    reason: str

    def to_json(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "rolled_back_proposal_ids": list(self.rolled_back_proposal_ids),
            "rolled_back_skill_revision_ids": list(self.rolled_back_skill_revision_ids),
            "rolled_back_rule_revision_ids": list(self.rolled_back_rule_revision_ids),
            "escalate": self.escalate,
            "reason": self.reason,
        }


def apply_proposal(
    *,
    db_path: Path,
    proposal_id: str,
    harness_workspace_root: Optional[Path] = None,
) -> dict[str, Any]:
    """HITL gate #2: a human approves and applies one pending proposal. The act of calling
    this IS the approval, so it bypasses the autonomous-mode gate (but repo writes are still
    subject to the ``allow_repo_patch`` fence, enforced inside the harness apply path)."""

    initialize_database(db_path)
    with connect(db_path) as connection:
        proposal = _get_proposal(connection, proposal_id)
        section = str(proposal["section"])
        profile_id = str(proposal["profile_id"])
        state = str(proposal["state"])

    if state != "pending":
        raise ApplyError(f"proposal_state_not_applyable:{state}")

    if section == "context":
        report = apply_context_proposal(db_path=db_path, proposal_id=proposal_id)
        return {
            "proposal_id": proposal_id,
            "profile_id": profile_id,
            "section": "context",
            "state": "applied",
            "applied_skill_ids": list(report.applied_skill_ids),
            "applied_context_rule_ids": list(report.applied_context_rule_ids),
            "patch_transaction_ids": [],
        }

    if section == "harness":
        from .harness import (
            HarnessError,
            apply_patch_transaction,
            prepare_harness_proposal,
        )

        root = harness_workspace_root or _profile_root_path(db_path, profile_id)
        if root is None:
            raise ApplyError("harness_workspace_root_required")
        try:
            prepared = prepare_harness_proposal(db_path=db_path, proposal_id=proposal_id)
            applied_patch_ids: list[str] = []
            for patch_transaction_id in prepared.patch_transaction_ids:
                apply_patch_transaction(
                    db_path=db_path,
                    patch_transaction_id=patch_transaction_id,
                    workspace_root=Path(root),
                )
                applied_patch_ids.append(patch_transaction_id)
        except HarnessError as exc:
            raise ApplyError(str(exc)) from exc
        _set_proposal_state(db_path, proposal_id, "applied")
        return {
            "proposal_id": proposal_id,
            "profile_id": profile_id,
            "section": "harness",
            "state": "applied",
            "applied_skill_ids": [],
            "applied_context_rule_ids": [],
            "patch_transaction_ids": applied_patch_ids,
        }

    raise ApplyError(f"unsupported_apply_section:{section}")


def rollback_applied_change_for_issue(*, db_path: Path, issue_id: str) -> IssueRollbackReport:
    """Revert the applied fix(es) for one issue (spec 0018 guard monitor, on regression).

    Traverses ``issue -> learning_proposals.issue_id -> revisions.proposal_id`` and reuses
    the existing per-revision rollbacks. Context (skill + delivery-rule) revisions are
    reverted in place. Harness/repo patches are NOT auto-reverted (a diverged worktree makes
    that unsafe — spec 0018 Decision #6): they set ``escalate`` so the caller hands the issue
    to a human instead."""

    initialize_database(db_path)
    with connect(db_path) as connection:
        proposal_rows = connection.execute(
            """
            SELECT id, section FROM learning_proposals
            WHERE issue_id = ? AND state = 'applied'
            ORDER BY updated_at DESC, id DESC
            """,
            (issue_id,),
        ).fetchall()
        proposals = [(str(row["id"]), str(row["section"])) for row in proposal_rows]
        skill_revs: dict[str, list[str]] = {}
        rule_revs: dict[str, list[str]] = {}
        for proposal_id, section in proposals:
            if section != "context":
                continue
            skill_revs[proposal_id] = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM skill_revisions WHERE proposal_id = ? AND operation != 'rollback' "
                    "ORDER BY created_at DESC, id DESC",
                    (proposal_id,),
                ).fetchall()
            ]
            rule_revs[proposal_id] = [
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM context_delivery_rule_revisions WHERE proposal_id = ? "
                    "AND operation != 'rollback' ORDER BY created_at DESC, id DESC",
                    (proposal_id,),
                ).fetchall()
            ]

    rolled_back_skill_ids: list[str] = []
    rolled_back_rule_ids: list[str] = []
    reverted_proposal_ids: list[str] = []
    reasons: list[str] = []
    escalate = False

    for proposal_id, section in proposals:
        if section != "context":
            escalate = True
            reasons.append(f"harness_proposal_escalated:{proposal_id}")
            continue
        clean = True
        for revision_id in rule_revs.get(proposal_id, []):
            try:
                report = rollback_context_delivery_rule_revision(db_path=db_path, revision_id=revision_id)
                rolled_back_rule_ids.append(report.rollback_revision_id)
            except (ApplyError, StorageError) as exc:
                clean = False
                reasons.append(f"rule_rollback_skipped:{revision_id}:{exc}")
        for revision_id in skill_revs.get(proposal_id, []):
            try:
                report = rollback_skill_revision(db_path=db_path, revision_id=revision_id)
                rolled_back_skill_ids.append(report.rollback_revision_id)
            except (ApplyError, StorageError) as exc:
                clean = False
                reasons.append(f"skill_rollback_skipped:{revision_id}:{exc}")
        if clean:
            _set_proposal_state(db_path, proposal_id, "rolled_back")
            reverted_proposal_ids.append(proposal_id)
        else:
            escalate = True

    return IssueRollbackReport(
        issue_id=issue_id,
        rolled_back_proposal_ids=tuple(reverted_proposal_ids),
        rolled_back_skill_revision_ids=tuple(rolled_back_skill_ids),
        rolled_back_rule_revision_ids=tuple(rolled_back_rule_ids),
        escalate=escalate,
        reason="; ".join(reasons) if reasons else "rolled_back",
    )


def _set_proposal_state(db_path: Path, proposal_id: str, state: str) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "UPDATE learning_proposals SET state = ?, updated_at = ? WHERE id = ?",
            (state, utc_now(), proposal_id),
        )


def _profile_root_path(db_path: Path, profile_id: str) -> Optional[Path]:
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT root_path FROM profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    if row is None:
        return None
    root_path = row["root_path"]
    if not isinstance(root_path, str) or not root_path:
        return None
    return Path(root_path).expanduser()


def list_skills(db_path: Path, *, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    where_sql = "WHERE profile_id = ?" if profile_id is not None else ""
    params = [profile_id] if profile_id is not None else []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT id, profile_id, proposal_id, section, issue, insight,
                       keywords_json, occurrences_json, helpful_count,
                       harmful_count, neutral_count, active, human_locked,
                       human_lock_reason, source_run_id, created_at, updated_at
                FROM skills
                {where_sql}
                ORDER BY created_at DESC, id ASC
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    skills = []
    for row in rows:
        payload = dict(row)
        payload["keywords"] = _json_loads(payload.pop("keywords_json"), [])
        payload["occurrences"] = _json_loads(payload.pop("occurrences_json"), [])
        payload["active"] = bool(payload["active"])
        payload["human_locked"] = bool(payload["human_locked"])
        skills.append(payload)
    return skills


def list_context_delivery_rules(
    db_path: Path,
    *,
    profile_id: Optional[str] = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    where = []
    params: list[Any] = []
    if profile_id is not None:
        where.append("profile_id = ?")
        params.append(profile_id)
    if active_only:
        where.append("active = 1")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT id, profile_id, proposal_id, target_json, rule_json,
                       active, human_locked, human_lock_reason, created_at, updated_at
                FROM context_delivery_rules
                {where_sql}
                ORDER BY created_at DESC, id ASC
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    rules = []
    for row in rows:
        payload = dict(row)
        payload["target"] = _json_loads(payload.pop("target_json"), {})
        payload["rule"] = _json_loads(payload.pop("rule_json"), {})
        payload["active"] = bool(payload["active"])
        payload["human_locked"] = bool(payload["human_locked"])
        rules.append(payload)
    return rules


def list_skill_revisions(
    db_path: Path,
    *,
    skill_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    where_sql = "WHERE skill_id = ?" if skill_id is not None else ""
    params = [skill_id] if skill_id is not None else []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT id, skill_id, profile_id, proposal_id, operation,
                       before_json, after_json, created_at
                FROM skill_revisions
                {where_sql}
                ORDER BY rowid DESC
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    revisions = []
    for row in rows:
        payload = dict(row)
        payload["before"] = _json_loads(payload.pop("before_json"), None)
        payload["after"] = _json_loads(payload.pop("after_json"), {})
        revisions.append(payload)
    return revisions


def list_context_delivery_rule_revisions(
    db_path: Path,
    *,
    rule_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []

    where_sql = "WHERE rule_id = ?" if rule_id is not None else ""
    params = [rule_id] if rule_id is not None else []
    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                f"""
                SELECT id, rule_id, profile_id, proposal_id, operation,
                       before_json, after_json, created_at
                FROM context_delivery_rule_revisions
                {where_sql}
                ORDER BY rowid DESC
                """,
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    revisions = []
    for row in rows:
        payload = dict(row)
        payload["before"] = _json_loads(payload.pop("before_json"), None)
        payload["after"] = _json_loads(payload.pop("after_json"), {})
        revisions.append(payload)
    return revisions


def rollback_skill_revision(*, db_path: Path, revision_id: str) -> SkillRevisionRollbackReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT rowid, * FROM skill_revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ApplyError(f"skill_revision_not_found:{revision_id}")
        skill_id = str(row["skill_id"])
        latest = connection.execute(
            "SELECT id FROM skill_revisions WHERE skill_id = ? ORDER BY rowid DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        if latest is None or latest["id"] != revision_id:
            raise ApplyError(f"skill_revision_not_latest:{revision_id}")

        skill = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if skill is None:
            raise ApplyError(f"skill_not_found:{skill_id}")
        if int(skill["human_locked"]) == 1:
            raise ApplyError(f"human_locked_skill:{skill_id}")

        profile_id = str(row["profile_id"])
        now = utc_now()
        _ensure_kyoko_source(connection, profile_id)
        current = _skill_snapshot(skill)
        if str(row["operation"]) == "create":
            connection.execute(
                "UPDATE skills SET active = ?, updated_at = ? WHERE id = ?",
                (0, now, skill_id),
            )
        else:
            before = _json_loads(row["before_json"], None)
            if not isinstance(before, dict):
                raise ApplyError(f"skill_revision_before_missing:{revision_id}")
            _restore_skill_snapshot(connection, before, now=now)
        restored = _skill_snapshot(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        rollback_revision_id = _record_skill_revision(
            connection,
            skill_id=skill_id,
            profile_id=profile_id,
            proposal_id=str(row["proposal_id"]),
            operation="rollback",
            before=current,
            after=restored,
            now=now,
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{skill_id}_rollback_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
            entity_type="skill",
            entity_id=skill_id,
            kind="skill_revision_rolled_back",
            at=now,
            agent_identity_id=None,
            metadata={
                "revision_id": revision_id,
                "rollback_revision_id": rollback_revision_id,
                "operation": row["operation"],
            },
        )
        return SkillRevisionRollbackReport(
            revision_id=revision_id,
            rollback_revision_id=rollback_revision_id,
            skill_id=skill_id,
            profile_id=profile_id,
            status="rolled_back",
        )


def rollback_context_delivery_rule_revision(
    *,
    db_path: Path,
    revision_id: str,
) -> ContextDeliveryRuleRevisionRollbackReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT rowid, * FROM context_delivery_rule_revisions WHERE id = ?",
            (revision_id,),
        ).fetchone()
        if row is None:
            raise ApplyError(f"context_delivery_rule_revision_not_found:{revision_id}")
        rule_id = str(row["rule_id"])
        latest = connection.execute(
            "SELECT id FROM context_delivery_rule_revisions WHERE rule_id = ? ORDER BY rowid DESC LIMIT 1",
            (rule_id,),
        ).fetchone()
        if latest is None or latest["id"] != revision_id:
            raise ApplyError(f"context_delivery_rule_revision_not_latest:{revision_id}")

        rule = connection.execute("SELECT * FROM context_delivery_rules WHERE id = ?", (rule_id,)).fetchone()
        if rule is None:
            raise ApplyError(f"context_delivery_rule_not_found:{rule_id}")
        if int(rule["human_locked"]) == 1:
            raise ApplyError(f"human_locked_context_delivery_rule:{rule_id}")

        profile_id = str(row["profile_id"])
        now = utc_now()
        _ensure_kyoko_source(connection, profile_id)
        current = _context_delivery_rule_snapshot(rule)
        if str(row["operation"]) == "create":
            connection.execute(
                "UPDATE context_delivery_rules SET active = ?, updated_at = ? WHERE id = ?",
                (0, now, rule_id),
            )
        else:
            before = _json_loads(row["before_json"], None)
            if not isinstance(before, dict):
                raise ApplyError(f"context_delivery_rule_revision_before_missing:{revision_id}")
            _restore_context_delivery_rule_snapshot(connection, before, now=now)
        restored = _context_delivery_rule_snapshot(
            connection.execute("SELECT * FROM context_delivery_rules WHERE id = ?", (rule_id,)).fetchone()
        )
        rollback_revision_id = _record_context_delivery_rule_revision(
            connection,
            rule_id=rule_id,
            profile_id=profile_id,
            proposal_id=row["proposal_id"] if isinstance(row["proposal_id"], str) else None,
            operation="rollback",
            before=current,
            after=restored,
            now=now,
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{rule_id}_rollback_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
            entity_type="context_delivery_rule",
            entity_id=rule_id,
            kind="context_delivery_rule_revision_rolled_back",
            at=now,
            agent_identity_id=None,
            metadata={
                "revision_id": revision_id,
                "rollback_revision_id": rollback_revision_id,
                "operation": row["operation"],
            },
        )
        return ContextDeliveryRuleRevisionRollbackReport(
            revision_id=revision_id,
            rollback_revision_id=rollback_revision_id,
            rule_id=rule_id,
            profile_id=profile_id,
            status="rolled_back",
        )


def set_skill_lock(
    *,
    db_path: Path,
    skill_id: str,
    locked: bool,
    reason: Optional[str] = None,
    actor_agent_identity_id: Optional[str] = None,
) -> SkillLockReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute("SELECT id, profile_id FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if row is None:
            raise ApplyError(f"skill_not_found:{skill_id}")
        profile_id = str(row["profile_id"])
        clean_actor_agent_identity_id = _validate_actor_agent_identity_id(
            connection,
            profile_id,
            actor_agent_identity_id,
        )
        clean_reason = _clean_lock_reason(reason)
        now = utc_now()
        connection.execute(
            "UPDATE skills SET human_locked = ?, human_lock_reason = ?, updated_at = ? WHERE id = ?",
            (1 if locked else 0, clean_reason, now, skill_id),
        )
        return SkillLockReport(
            skill_id=skill_id,
            profile_id=profile_id,
            human_locked=locked,
            reason=clean_reason,
            actor_agent_identity_id=clean_actor_agent_identity_id,
        )


def set_context_delivery_rule_lock(
    *,
    db_path: Path,
    rule_id: str,
    locked: bool,
    reason: Optional[str] = None,
    actor_agent_identity_id: Optional[str] = None,
) -> ContextDeliveryRuleLockReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT id, profile_id FROM context_delivery_rules WHERE id = ?",
            (rule_id,),
        ).fetchone()
        if row is None:
            raise ApplyError(f"context_delivery_rule_not_found:{rule_id}")
        profile_id = str(row["profile_id"])
        clean_actor_agent_identity_id = _validate_actor_agent_identity_id(
            connection,
            profile_id,
            actor_agent_identity_id,
        )
        clean_reason = _clean_lock_reason(reason)
        now = utc_now()
        connection.execute(
            """
            UPDATE context_delivery_rules
            SET human_locked = ?, human_lock_reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (1 if locked else 0, clean_reason, now, rule_id),
        )
        return ContextDeliveryRuleLockReport(
            rule_id=rule_id,
            profile_id=profile_id,
            human_locked=locked,
            reason=clean_reason,
            actor_agent_identity_id=clean_actor_agent_identity_id,
        )


def _get_proposal(connection: sqlite3.Connection, proposal_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("learning_proposals table is missing") from exc

    if row is None:
        raise ApplyError(f"proposal_not_found:{proposal_id}")
    return row


def _validate_apply_allowed(
    connection: sqlite3.Connection,
    proposal: sqlite3.Row,
    *,
    allowed_states: tuple[str, ...],
) -> None:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    state = str(proposal["state"])
    section = str(proposal["section"])

    if state not in set(allowed_states):
        raise ApplyError(f"proposal_state_not_applyable:{state}")
    if section != "context":
        raise ApplyError(f"unsupported_apply_section:{section}")

    # v31 (spec 0018): the gate decision (autonomous auto-apply vs HITL human-approve) is
    # made by the caller; this low-level apply only validates the change payload. Context
    # writes have no separate capability fence (only repo patches do, enforced in harness).
    changes = _json_loads(proposal["proposed_changes_json"], [])
    if not isinstance(changes, list):
        raise ApplyError("invalid_proposed_changes")

    skill_updates = [change for change in changes if isinstance(change, dict) and change.get("type") == "skillbook_update"]
    delivery_rules = [
        change for change in changes if isinstance(change, dict) and change.get("type") == "context_delivery_rule"
    ]
    if not skill_updates and not delivery_rules:
        raise ApplyError("no_context_apply_changes")

    for change in changes:
        if not isinstance(change, dict):
            raise ApplyError("invalid_change")
        change_type = change.get("type")
        if change_type not in {"skillbook_update", "context_delivery_rule", "check_spec"}:
            raise ApplyError(f"unsupported_context_apply_change:{change_type}")
        if change_type == "skillbook_update" and change.get("section") != "context":
            raise ApplyError("skillbook_update_section_mismatch")
        if change_type == "context_delivery_rule":
            if change.get("operation") not in {"create", "update", "deactivate"}:
                raise ApplyError(f"unsupported_context_delivery_rule_operation:{change.get('operation')}")
            if not isinstance(change.get("target"), dict):
                raise ApplyError("context_delivery_rule_target_required")
            if not isinstance(change.get("rule"), dict):
                raise ApplyError("context_delivery_rule_body_required")

    if _has_applied_skill_for_proposal(connection, proposal_id) or _has_applied_context_rule_for_proposal(
        connection,
        proposal_id,
    ):
        raise ApplyError(f"proposal_already_applied:{proposal_id}")


def _apply_skillbook_updates(
    connection: sqlite3.Connection,
    proposal: sqlite3.Row,
    now: str,
) -> list[str]:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    changes = _json_loads(proposal["proposed_changes_json"], [])
    applied_skill_ids: list[str] = []

    for index, change in enumerate(changes, start=1):
        if not isinstance(change, dict) or change.get("type") != "skillbook_update":
            continue

        operation = change.get("operation")
        if operation not in {"create", "update", "deactivate", "link_occurrence"}:
            raise ApplyError(f"unsupported_skillbook_operation:{operation}")

        skill_id = change.get("skill_id")
        if not isinstance(skill_id, str):
            skill_id = f"skill_{proposal_id}_{index}"

        existing = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if existing is not None and int(existing["human_locked"]) == 1:
            raise ApplyError(f"human_locked_skill:{skill_id}")

        if operation == "create":
            if existing is not None:
                raise ApplyError(f"skill_already_exists:{skill_id}")

            occurrences = change.get("occurrence_refs", [])
            source_run_id = _first_source_run_id(connection, occurrences)
            connection.execute(
                """
                INSERT INTO skills (
                  id,
                  profile_id,
                  proposal_id,
                  section,
                  issue,
                  insight,
                  keywords_json,
                  occurrences_json,
                  helpful_count,
                  harmful_count,
                  neutral_count,
                  active,
                  human_locked,
                  source_run_id,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    skill_id,
                    profile_id,
                    proposal_id,
                    change["section"],
                    change["issue"],
                    change["insight"],
                    _json_dumps(change.get("keywords", [])),
                    _json_dumps(occurrences),
                    0,
                    0,
                    0,
                    1,
                    0,
                    source_run_id,
                    now,
                    now,
                ),
            )
            after = _skill_snapshot(
                connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
            )
            _record_skill_revision(
                connection,
                skill_id=skill_id,
                profile_id=profile_id,
                proposal_id=proposal_id,
                operation="create",
                before=None,
                after=after,
                now=now,
            )
            applied_skill_ids.append(skill_id)
            continue

        if existing is None:
            raise ApplyError(f"skill_not_found:{skill_id}")

        before = _skill_snapshot(existing)
        if operation == "update":
            occurrences = change.get("occurrence_refs", [])
            source_run_id = _first_source_run_id(connection, occurrences) or before.get("source_run_id")
            connection.execute(
                """
                UPDATE skills
                SET proposal_id = ?,
                    section = ?,
                    issue = ?,
                    insight = ?,
                    keywords_json = ?,
                    occurrences_json = ?,
                    source_run_id = ?,
                    active = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    proposal_id,
                    change["section"],
                    change["issue"],
                    change["insight"],
                    _json_dumps(change.get("keywords", [])),
                    _json_dumps(occurrences),
                    source_run_id,
                    now,
                    skill_id,
                ),
            )
        elif operation == "deactivate":
            connection.execute(
                """
                UPDATE skills
                SET proposal_id = ?,
                    active = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (proposal_id, now, skill_id),
            )
        else:
            occurrences = _merge_occurrences(
                _json_loads(existing["occurrences_json"], []),
                change.get("occurrence_refs", []),
            )
            source_run_id = before.get("source_run_id") or _first_source_run_id(connection, occurrences)
            connection.execute(
                """
                UPDATE skills
                SET proposal_id = ?,
                    occurrences_json = ?,
                    source_run_id = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    proposal_id,
                    _json_dumps(occurrences),
                    source_run_id,
                    now,
                    skill_id,
                ),
            )

        after = _skill_snapshot(connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone())
        _record_skill_revision(
            connection,
            skill_id=skill_id,
            profile_id=profile_id,
            proposal_id=proposal_id,
            operation=str(operation),
            before=before,
            after=after,
            now=now,
        )
        applied_skill_ids.append(skill_id)

    return applied_skill_ids


def _apply_context_delivery_rules(
    connection: sqlite3.Connection,
    proposal: sqlite3.Row,
    now: str,
) -> list[str]:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    changes = _json_loads(proposal["proposed_changes_json"], [])
    applied_rule_ids: list[str] = []

    for index, change in enumerate(changes, start=1):
        if not isinstance(change, dict) or change.get("type") != "context_delivery_rule":
            continue

        operation = change.get("operation")
        target = change.get("target")
        rule = change.get("rule")
        if operation not in {"create", "update", "deactivate"}:
            raise ApplyError(f"unsupported_context_delivery_rule_operation:{operation}")
        if not isinstance(target, dict):
            raise ApplyError("context_delivery_rule_target_required")
        if not isinstance(rule, dict):
            raise ApplyError("context_delivery_rule_body_required")

        rule_id = _context_delivery_rule_id(rule, proposal_id=proposal_id, index=index)
        existing = connection.execute(
            "SELECT * FROM context_delivery_rules WHERE id = ?",
            (rule_id,),
        ).fetchone()

        if existing is not None and int(existing["human_locked"]) == 1:
            raise ApplyError(f"human_locked_context_delivery_rule:{rule_id}")

        if operation == "create":
            if existing is not None:
                raise ApplyError(f"context_delivery_rule_already_exists:{rule_id}")
            connection.execute(
                """
                INSERT INTO context_delivery_rules (
                  id,
                  profile_id,
                  proposal_id,
                  target_json,
                  rule_json,
                  active,
                  human_locked,
                  created_at,
                  updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    profile_id,
                    proposal_id,
                    _json_dumps(target),
                    _json_dumps(rule),
                    1,
                    0,
                    now,
                    now,
                ),
            )
        else:
            if existing is None:
                raise ApplyError(f"context_delivery_rule_not_found:{rule_id}")
            before = _context_delivery_rule_snapshot(existing)
            connection.execute(
                """
                UPDATE context_delivery_rules
                SET proposal_id = ?,
                    target_json = ?,
                    rule_json = ?,
                    active = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    proposal_id,
                    _json_dumps(target),
                    _json_dumps(rule),
                    0 if operation == "deactivate" else 1,
                    now,
                    rule_id,
                ),
            )

        after = _context_delivery_rule_snapshot(
            connection.execute("SELECT * FROM context_delivery_rules WHERE id = ?", (rule_id,)).fetchone()
        )
        _record_context_delivery_rule_revision(
            connection,
            rule_id=rule_id,
            profile_id=profile_id,
            proposal_id=proposal_id,
            operation=str(operation),
            before=None if operation == "create" else before,
            after=after,
            now=now,
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{rule_id}_{operation}_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
            entity_type="context_delivery_rule",
            entity_id=rule_id,
            kind="context_delivery_rule_applied",
            at=now,
            agent_identity_id=None,
            metadata={
                "operation": operation,
                "proposal_id": proposal_id,
                "active": operation != "deactivate",
            },
        )
        applied_rule_ids.append(rule_id)

    return applied_rule_ids


def _get_policy(connection: sqlite3.Connection, profile_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM autonomy_policies WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise ApplyError(f"autonomy_policy_not_found:{profile_id}")
    return row


def _validate_actor_agent_identity_id(
    connection: sqlite3.Connection,
    profile_id: str,
    actor_agent_identity_id: Optional[str],
) -> Optional[str]:
    if actor_agent_identity_id is None:
        return None
    clean_actor_agent_identity_id = actor_agent_identity_id.strip()
    if not clean_actor_agent_identity_id:
        return None
    row = connection.execute(
        """
        SELECT id
        FROM agent_identities
        WHERE id = ? AND profile_id = ?
        """,
        (clean_actor_agent_identity_id, profile_id),
    ).fetchone()
    if row is None:
        raise ApplyError(f"actor_agent_identity_not_found:{clean_actor_agent_identity_id}")
    return clean_actor_agent_identity_id


def _clean_lock_reason(reason: Optional[str]) -> Optional[str]:
    return reason.strip() if isinstance(reason, str) and reason.strip() else None


def _ensure_kyoko_source(connection: sqlite3.Connection, profile_id: str) -> None:
    now = utc_now()
    source_id = f"source_kyoko_{profile_id}"
    connection.execute(
        """
        INSERT OR IGNORE INTO sources (
          id,
          profile_id,
          kind,
          display_name,
          status,
          adapter_version,
          config_json,
          capabilities_json,
          last_seen_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_id,
            profile_id,
            "kyoko_sdk",
            "Kyoko",
            "active",
            "kyoko.core.v0",
            "{}",
            _json_dumps({"proposal_apply": True}),
            now,
        ),
    )


def _insert_timeline_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    profile_id: str,
    entity_type: str,
    entity_id: str,
    kind: str,
    at: str,
    agent_identity_id: Optional[str],
    metadata: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO timeline_events (
          id,
          profile_id,
          source_id,
          entity_type,
          entity_id,
          kind,
          at,
          agent_identity_id,
          payload_ref,
          metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            profile_id,
            f"source_kyoko_{profile_id}",
            entity_type,
            entity_id,
            kind,
            at,
            agent_identity_id,
            None,
            _json_dumps(metadata),
        ),
    )


def _first_source_run_id(connection: sqlite3.Connection, occurrences: Any) -> Optional[str]:
    if not isinstance(occurrences, list):
        return None
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        entity_type = occurrence.get("entity_type")
        entity_id = occurrence.get("entity_id")
        if not isinstance(entity_id, str):
            continue
        if entity_type == "run":
            return entity_id
        if entity_type == "span":
            row = connection.execute("SELECT run_id FROM spans WHERE id = ?", (entity_id,)).fetchone()
            if row is not None:
                return str(row["run_id"])
        if entity_type == "task_attempt":
            row = connection.execute(
                "SELECT run_id FROM task_attempts WHERE id = ?",
                (entity_id,),
            ).fetchone()
            if row is not None and row["run_id"] is not None:
                return str(row["run_id"])
    return None


def _skill_snapshot(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        raise ApplyError("skill_snapshot_missing")
    return {
        "id": str(row["id"]),
        "profile_id": str(row["profile_id"]),
        "proposal_id": row["proposal_id"],
        "section": str(row["section"]),
        "issue": str(row["issue"]),
        "insight": str(row["insight"]),
        "keywords": _json_loads(row["keywords_json"], []),
        "occurrences": _json_loads(row["occurrences_json"], []),
        "helpful_count": int(row["helpful_count"]),
        "harmful_count": int(row["harmful_count"]),
        "neutral_count": int(row["neutral_count"]),
        "active": bool(row["active"]),
        "human_locked": bool(row["human_locked"]),
        "human_lock_reason": row["human_lock_reason"],
        "source_run_id": row["source_run_id"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _record_skill_revision(
    connection: sqlite3.Connection,
    *,
    skill_id: str,
    profile_id: str,
    proposal_id: str,
    operation: str,
    before: Optional[dict[str, Any]],
    after: dict[str, Any],
    now: str,
) -> str:
    revision_id = f"skill_revision_{proposal_id}_{skill_id}_{uuid.uuid4().hex[:8]}"
    connection.execute(
        """
        INSERT INTO skill_revisions (
          id,
          skill_id,
          profile_id,
          proposal_id,
          operation,
          before_json,
          after_json,
          created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            skill_id,
            profile_id,
            proposal_id,
            operation,
            _json_dumps(before) if before is not None else None,
            _json_dumps(after),
            now,
        ),
    )
    return revision_id


def _restore_skill_snapshot(connection: sqlite3.Connection, snapshot: dict[str, Any], *, now: str) -> None:
    connection.execute(
        """
        UPDATE skills
        SET proposal_id = ?,
            section = ?,
            issue = ?,
            insight = ?,
            keywords_json = ?,
            occurrences_json = ?,
            helpful_count = ?,
            harmful_count = ?,
            neutral_count = ?,
            active = ?,
            human_locked = ?,
            human_lock_reason = ?,
            source_run_id = ?,
            created_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            snapshot.get("proposal_id"),
            snapshot["section"],
            snapshot["issue"],
            snapshot["insight"],
            _json_dumps(snapshot.get("keywords", [])),
            _json_dumps(snapshot.get("occurrences", [])),
            int(snapshot.get("helpful_count", 0)),
            int(snapshot.get("harmful_count", 0)),
            int(snapshot.get("neutral_count", 0)),
            1 if snapshot.get("active", False) else 0,
            1 if snapshot.get("human_locked", False) else 0,
            snapshot.get("human_lock_reason"),
            snapshot.get("source_run_id"),
            snapshot["created_at"],
            now,
            snapshot["id"],
        ),
    )


def _context_delivery_rule_snapshot(row: Optional[sqlite3.Row]) -> dict[str, Any]:
    if row is None:
        raise ApplyError("context_delivery_rule_snapshot_missing")
    return {
        "id": str(row["id"]),
        "profile_id": str(row["profile_id"]),
        "proposal_id": row["proposal_id"],
        "target": _json_loads(row["target_json"], {}),
        "rule": _json_loads(row["rule_json"], {}),
        "active": bool(row["active"]),
        "human_locked": bool(row["human_locked"]),
        "human_lock_reason": row["human_lock_reason"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _record_context_delivery_rule_revision(
    connection: sqlite3.Connection,
    *,
    rule_id: str,
    profile_id: str,
    proposal_id: Optional[str],
    operation: str,
    before: Optional[dict[str, Any]],
    after: dict[str, Any],
    now: str,
) -> str:
    revision_proposal_id = proposal_id or "manual"
    revision_id = f"context_delivery_rule_revision_{revision_proposal_id}_{rule_id}_{uuid.uuid4().hex[:8]}"
    connection.execute(
        """
        INSERT INTO context_delivery_rule_revisions (
          id,
          rule_id,
          profile_id,
          proposal_id,
          operation,
          before_json,
          after_json,
          created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            rule_id,
            profile_id,
            proposal_id,
            operation,
            _json_dumps(before) if before is not None else None,
            _json_dumps(after),
            now,
        ),
    )
    return revision_id


def _restore_context_delivery_rule_snapshot(
    connection: sqlite3.Connection,
    snapshot: dict[str, Any],
    *,
    now: str,
) -> None:
    connection.execute(
        """
        UPDATE context_delivery_rules
        SET proposal_id = ?,
            target_json = ?,
            rule_json = ?,
            active = ?,
            human_locked = ?,
            human_lock_reason = ?,
            created_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            snapshot.get("proposal_id"),
            _json_dumps(snapshot.get("target", {})),
            _json_dumps(snapshot.get("rule", {})),
            1 if snapshot.get("active", False) else 0,
            1 if snapshot.get("human_locked", False) else 0,
            snapshot.get("human_lock_reason"),
            snapshot["created_at"],
            now,
            snapshot["id"],
        ),
    )


def _merge_occurrences(existing: Any, incoming: Any) -> list[dict[str, Any]]:
    merged = [item for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
    seen = {_json_dumps(item) for item in merged}
    if not isinstance(incoming, list):
        return merged
    for occurrence in incoming:
        if not isinstance(occurrence, dict):
            continue
        key = _json_dumps(occurrence)
        if key in seen:
            continue
        merged.append(occurrence)
        seen.add(key)
    return merged


def _has_applied_skill_for_proposal(connection: sqlite3.Connection, proposal_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM skills WHERE proposal_id = ? LIMIT 1",
        (proposal_id,),
    ).fetchone()
    if row is not None:
        return True
    revision = connection.execute(
        "SELECT 1 FROM skill_revisions WHERE proposal_id = ? LIMIT 1",
        (proposal_id,),
    ).fetchone()
    return revision is not None


def _has_applied_context_rule_for_proposal(connection: sqlite3.Connection, proposal_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM context_delivery_rules WHERE proposal_id = ? LIMIT 1",
        (proposal_id,),
    ).fetchone()
    if row is not None:
        return True
    revision = connection.execute(
        "SELECT 1 FROM context_delivery_rule_revisions WHERE proposal_id = ? LIMIT 1",
        (proposal_id,),
    ).fetchone()
    return revision is not None


def _context_delivery_rule_id(rule: dict[str, Any], *, proposal_id: str, index: int) -> str:
    rule_id = rule.get("id")
    if isinstance(rule_id, str) and rule_id:
        return rule_id
    return f"context_rule_{proposal_id}_{index}"


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
