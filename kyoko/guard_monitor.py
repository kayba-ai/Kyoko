"""Guard-monitoring + auto-rollback loop (spec 0018) — gate #2's post-hoc validator.

When a fix is applied, ``issues.applied_at`` is watermarked and a deterministic guard
detector is minted (``issue_guard.mint_guard_for_issue``). The measurement plane runs that
detector over new traces; a fire bundles the recurrence back into the *same* issue, bumping
``recurrence_count`` (and re-opening it). This module reads that counter against the apply
watermark and, on a **confirmed** regression (recurrence-since-apply >= the policy's
``regression_threshold`` — never a single fire, mirroring gate #1's "real evidence" rule),
rolls back the applied change and re-opens the issue for a fresh fix. After
``max_auto_fix_attempts`` such cycles the issue is escalated to HITL (``autonomy_blocked``).

This is observation + reaction only; it never authors a proposal. Auto-rollback happens only
in ``autonomous`` mode (in HITL a human owns the apply/rollback decision — the regression is
still surfaced by the guard fire re-opening the issue).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .apply import ApplyError, rollback_applied_change_for_issue
from .autonomy import AutonomyError, get_autonomy_policy, is_autonomous
from .issues import IssueError, get_issue, mark_issue_rolled_back
from .storage import StorageError, connect, initialize_database


class GuardMonitorError(Exception):
    """Raised when the guard monitor cannot run."""


@dataclass(frozen=True)
class GuardMonitorReport:
    profile_id: str
    mode: str
    regression_threshold: int
    actions: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "mode": self.mode,
            "regression_threshold": self.regression_threshold,
            "actions": [dict(action) for action in self.actions],
        }


def monitor_guarded_issues(
    *, db_path: Path, profile_id: Optional[str] = None
) -> GuardMonitorReport:
    initialize_database(db_path)
    try:
        policy = get_autonomy_policy(db_path=db_path, profile_id=profile_id)
    except AutonomyError as exc:
        raise GuardMonitorError(str(exc)) from exc

    selected_profile_id = str(policy["profile_id"])
    regression_threshold = int(policy["regression_threshold"])
    max_attempts = int(policy["max_auto_fix_attempts"])
    auto_rollback = is_autonomous(policy) and bool(policy["auto_rollback_on_regression"])

    actions: list[dict[str, Any]] = []
    for issue_id in _watermarked_issue_ids(db_path, selected_profile_id):
        try:
            issue = get_issue(db_path=db_path, issue_id=issue_id)
        except IssueError:
            continue
        baseline = issue.get("recurrence_count_at_apply")
        if baseline is None:
            continue
        post_apply = int(issue.get("recurrence_count") or 0) - int(baseline)
        if post_apply < regression_threshold:
            continue  # not yet a confirmed regression (n=1 is noise)

        if not auto_rollback:
            actions.append(
                {
                    "issue_id": issue_id,
                    "action": "regression_detected",
                    "post_apply_recurrences": post_apply,
                    "auto_rollback": False,
                }
            )
            continue

        try:
            rollback = rollback_applied_change_for_issue(db_path=db_path, issue_id=issue_id)
        except (ApplyError, StorageError) as exc:
            actions.append(
                {
                    "issue_id": issue_id,
                    "action": "rollback_failed",
                    "post_apply_recurrences": post_apply,
                    "reason": str(exc),
                }
            )
            continue

        attempts_after = int(issue.get("auto_fix_attempts") or 0) + 1
        blocked = rollback.escalate or attempts_after >= max_attempts
        reason = (
            "harness_rollback_escalated"
            if rollback.escalate
            else f"auto_fix_attempts_exhausted:{attempts_after}>={max_attempts}"
        )
        try:
            mark_issue_rolled_back(
                db_path=db_path,
                issue_id=issue_id,
                blocked=blocked,
                reason=reason if blocked else None,
            )
        except (IssueError, StorageError) as exc:
            actions.append(
                {"issue_id": issue_id, "action": "rollback_record_failed", "reason": str(exc)}
            )
            continue

        actions.append(
            {
                "issue_id": issue_id,
                "action": "escalated_to_hitl" if blocked else "rolled_back_reopened",
                "post_apply_recurrences": post_apply,
                "auto_fix_attempts": attempts_after,
                "escalate": rollback.escalate,
                "rolled_back_proposal_ids": list(rollback.rolled_back_proposal_ids),
            }
        )

    return GuardMonitorReport(
        profile_id=selected_profile_id,
        mode=str(policy["mode"]),
        regression_threshold=regression_threshold,
        actions=tuple(actions),
    )


def _watermarked_issue_ids(db_path: Path, profile_id: str) -> tuple[str, ...]:
    """Issues with an applied fix in flight (apply watermark set, not already escalated)."""
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id FROM issues
            WHERE profile_id = ?
              AND applied_at IS NOT NULL
              AND (autonomy_blocked IS NULL OR autonomy_blocked = 0)
            ORDER BY created_at, id
            """,
            (profile_id,),
        ).fetchall()
    return tuple(str(row["id"]) for row in rows)
