"""Skillbook consolidation — the post-analysis "keep the skillbook live and tracked" turn.

Phase 3 of the issue-centric loop. After analysis surfaces issues and proposals are
authored + gated, the skillbook can accumulate duplicate/near-duplicate skills (the same
learning recorded from two different runs, two analyzers, etc.). This module detects those
duplicate groups **deterministically** (no embeddings, no model, no new dependency) and
proposes consolidation as ordinary gated :class:`~kyoko.proposals.LearningProposal`\\ s.

Design (locked):

- Modeled on ACE's DeduplicationManager but **deterministic-first and gated**. Grouping is
  by an exact, normalized key — never a fuzzy/embedding similarity — to favor precision.
- A MERGE is expressed with the **existing** skillbook apply ops (see
  :func:`kyoko.apply._apply_skillbook_updates`): ``update`` the winner with the union of
  keywords/occurrences + a combined issue/insight, ``deactivate`` each loser, and
  ``link_occurrence`` to move each loser's occurrences onto the winner.
- Consolidation is **evidence/proposal-only**: it NEVER writes skills directly. It submits
  proposals (pending) and, only when asked, runs the SAME autonomy gate as any proposal —
  the gate (not this module) is the only thing that applies a merge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .apply import list_skills
from .autonomy_runner import AutonomyRunError, run_autonomy
from .checks import CheckError, generate_checks_for_proposal
from .proposals import ProposalError, submit_learning_proposal_payload
from .storage import StorageError, connect, initialize_database, utc_now


class SkillbookManagerError(Exception):
    """Raised when skillbook consolidation cannot be performed."""


@dataclass(frozen=True)
class ConsolidationReport:
    profile_id: Optional[str]
    duplicate_group_count: int
    proposal_ids: tuple[str, ...]
    applied_proposal_ids: tuple[str, ...]
    notes: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "duplicate_group_count": self.duplicate_group_count,
            "proposal_ids": list(self.proposal_ids),
            "applied_proposal_ids": list(self.applied_proposal_ids),
            "notes": list(self.notes),
        }


def detect_duplicate_skill_groups(
    db_path: Path,
    *,
    profile_id: Optional[str] = None,
) -> list[list[dict[str, Any]]]:
    """Deterministically group ACTIVE skills that represent the same learning.

    Grouping is run-independent and model-free. Two active skills in the same ``section``
    are grouped when EITHER:

    - they share the same normalized keyword set (lowercased/trimmed, as a ``frozenset``),
      which must be non-empty; OR
    - they share the same normalized ``issue`` text (lowercased/trimmed), non-empty.

    A group is a duplicate group only when it has >=2 active skills. The grouping is
    conservative (strong, exact matches only) and deterministic: skills are ordered by id
    within a group and groups are ordered by their (lowest) member id. Human-locked skills
    are never grouped (a lock blocks later writes; consolidating around one would only
    produce a proposal the gate cannot apply).
    """

    skills = [
        skill
        for skill in list_skills(db_path, profile_id=profile_id)
        if skill.get("active") and not skill.get("human_locked")
    ]
    # Stable, id-ordered input so group membership/order never depends on insertion order.
    skills.sort(key=lambda skill: str(skill.get("id")))

    # Union-find over skills keyed by id, joined on either matching signal.
    parent: dict[str, str] = {str(skill["id"]): str(skill["id"]) for skill in skills}

    def find(node: str) -> str:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        # Keep the smaller id as the representative for deterministic grouping.
        if left_root <= right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    keyword_index: dict[tuple[str, frozenset[str]], str] = {}
    issue_index: dict[tuple[str, str], str] = {}
    for skill in skills:
        skill_id = str(skill["id"])
        section = str(skill.get("section") or "")
        keyword_set = _normalized_keyword_set(skill.get("keywords"))
        if keyword_set:
            key = (section, keyword_set)
            if key in keyword_index:
                union(keyword_index[key], skill_id)
            else:
                keyword_index[key] = skill_id
        issue_text = _normalized_text(skill.get("issue"))
        if issue_text:
            ikey = (section, issue_text)
            if ikey in issue_index:
                union(issue_index[ikey], skill_id)
            else:
                issue_index[ikey] = skill_id

    by_root: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        root = find(str(skill["id"]))
        by_root.setdefault(root, []).append(skill)

    groups: list[list[dict[str, Any]]] = []
    for root in sorted(by_root):
        members = sorted(by_root[root], key=lambda skill: str(skill.get("id")))
        if len(members) >= 2:
            groups.append(members)
    return groups


def build_consolidation_proposal(
    group: Sequence[dict[str, Any]],
    *,
    profile_id: str,
) -> dict[str, Any]:
    """Build ONE valid ``kyoko.learning_proposal.v1`` that merges a duplicate ``group``.

    Winner = max occurrences, tie-break oldest ``created_at`` then smallest id. The proposed
    changes are: ``update`` the winner (union of keywords/occurrences + a combined
    issue/insight), ``deactivate`` each loser, and ``link_occurrence`` moving each loser's
    occurrence_refs onto the winner. ``section`` is the group's section. The id is the
    deterministic ``proposal_consolidate_{winner_id}``.
    """

    members = list(group)
    if len(members) < 2:
        raise SkillbookManagerError("consolidation_group_requires_two_or_more_skills")
    section = str(members[0].get("section") or "context")
    if any(str(skill.get("section") or "context") != section for skill in members):
        raise SkillbookManagerError("consolidation_group_section_mismatch")

    winner = _select_winner(members)
    losers = [skill for skill in members if str(skill["id"]) != str(winner["id"])]

    merged_keywords = _merged_keywords(members)
    merged_occurrences = _merged_occurrences(members)
    if not merged_occurrences:
        # The schema requires occurrence_refs to be non-empty for every skillbook_update;
        # a group with no occurrences anywhere cannot be expressed as a gated merge.
        raise SkillbookManagerError("consolidation_group_has_no_occurrences")

    winner_id = str(winner["id"])
    loser_ids = [str(skill["id"]) for skill in losers]
    issue_text = _combined_issue(members)
    insight_text = _combined_insight(members)

    proposed_changes: list[dict[str, Any]] = [
        {
            "type": "skillbook_update",
            "operation": "update",
            "skill_id": winner_id,
            "section": section,
            "issue": issue_text,
            "insight": insight_text,
            "keywords": merged_keywords,
            "occurrence_refs": merged_occurrences,
        }
    ]
    for skill in losers:
        loser_id = str(skill["id"])
        loser_occurrences = _occurrence_refs(skill.get("occurrences")) or merged_occurrences
        proposed_changes.append(
            {
                "type": "skillbook_update",
                "operation": "deactivate",
                "skill_id": loser_id,
                "section": section,
                "issue": _normalized_or_default(skill.get("issue"), issue_text),
                "insight": _normalized_or_default(skill.get("insight"), insight_text),
                "keywords": _normalized_keyword_list(skill.get("keywords")) or merged_keywords,
                "occurrence_refs": loser_occurrences,
            }
        )
        proposed_changes.append(
            {
                "type": "skillbook_update",
                "operation": "link_occurrence",
                "skill_id": winner_id,
                "section": section,
                "issue": issue_text,
                "insight": insight_text,
                "keywords": merged_keywords,
                "occurrence_refs": loser_occurrences,
            }
        )

    # Top-level evidence_refs drive the gate's fallback deterministic check target. Use a
    # non-failure role so the check resolves to a non-failed entity (winner's source run
    # when available), keeping consolidation gateable without inventing new evidence.
    evidence_refs = _evidence_refs_for(winner, merged_occurrences)

    title = f"Consolidate {len(members)} duplicate {section} skills into {winner_id}"
    summary = (
        f"Merge {len(losers)} duplicate {section} skill(s) "
        f"({', '.join(loser_ids)}) into {winner_id}, keeping the union of "
        f"{len(merged_keywords)} keyword(s) and {len(merged_occurrences)} occurrence(s)."
    )
    return {
        "schema_version": "kyoko.learning_proposal.v1",
        "id": f"proposal_consolidate_{winner_id}",
        "profile_id": profile_id,
        "producer": {
            "kind": "system",
            "name": "kyoko_skillbook_manager",
            "session_id": f"consolidate_{winner_id}",
        },
        "state": "pending",
        "section": section,
        "title": title,
        "summary": summary,
        "confidence": 0.6,
        "evidence_refs": evidence_refs,
        "problem": {
            "issue": (
                f"The {section} skillbook holds {len(members)} skills that record the same "
                "learning, splitting occurrences and keywords across duplicates."
            ),
            "severity": "low",
            "root_cause": (
                "Repeated analyses recorded the same insight as separate skills instead of "
                "linking new occurrences onto an existing skill."
            ),
            "target": {"entity_type": "skill", "entity_id": winner_id},
        },
        "insight": insight_text,
        "proposed_changes": proposed_changes,
        "gate_expectations": {
            "requires_human_review": False,
            # Context-section skillbook edits gate on an L1 deterministic check (no replay).
            "requires_check_level": "L1_repeated",
            "requires_replay": False,
            "allowed_autonomy_section": section,
            "notes": "Deterministic skillbook consolidation; verify the merge target before apply.",
        },
        "created_at": utc_now(),
    }


def run_skillbook_consolidation(
    *,
    db_path: Path,
    output_dir: Optional[Path] = None,
    profile_id: Optional[str] = None,
    operator: str = "mock",
    command: Optional[Sequence[str]] = None,
    schema_path: Optional[Path] = None,
    run_autonomy_after: bool = False,
    harness_workspace_root: Optional[Path] = None,
) -> ConsolidationReport:
    """Detect duplicate skill groups, submit one consolidation proposal per group, and
    (optionally) run the autonomy gate so eligible merges apply.

    The ``mock`` (deterministic) path is the solid, fully-tested one: it groups skills,
    builds + submits one consolidation proposal per group (pending), and — when
    ``run_autonomy_after`` — generates checks and runs the standard gate. The ``command``
    path is a thin operator wrapper (see :func:`write_consolidation_prompt_artifacts`).
    This function NEVER writes skills directly; only the gate applies a merge.
    """

    initialize_database(db_path)
    notes: list[str] = []

    groups = detect_duplicate_skill_groups(db_path, profile_id=profile_id)
    resolved_profile_id = profile_id or _resolve_profile_id(db_path, groups)

    if not groups:
        return ConsolidationReport(
            profile_id=resolved_profile_id,
            duplicate_group_count=0,
            proposal_ids=(),
            applied_proposal_ids=(),
            notes=("no_duplicate_skill_groups",),
        )
    if resolved_profile_id is None:
        raise SkillbookManagerError("profile_id_unresolved")

    if operator == "command":
        proposals = _author_consolidation_via_command(
            db_path=db_path,
            output_dir=output_dir,
            groups=groups,
            profile_id=resolved_profile_id,
            command=command,
            schema_path=schema_path,
            notes=notes,
        )
    elif operator == "mock":
        proposals = [
            build_consolidation_proposal(group, profile_id=resolved_profile_id)
            for group in groups
        ]
    else:
        raise SkillbookManagerError(f"unsupported_consolidation_operator:{operator}")

    proposal_ids: list[str] = []
    for proposal in proposals:
        try:
            report = submit_learning_proposal_payload(
                db_path=db_path,
                proposal=proposal,
                schema_path=schema_path,
            )
        except ProposalError as exc:
            # An already-submitted consolidation proposal (idempotent id) is not fatal.
            if "proposal_already_exists" in str(exc):
                notes.append(f"consolidation_proposal_exists:{proposal.get('id')}")
                proposal_ids.append(str(proposal["id"]))
                continue
            raise SkillbookManagerError(str(exc)) from exc
        proposal_ids.append(report.proposal_id)
        _record_consolidation_operator_run(
            db_path=db_path,
            profile_id=resolved_profile_id,
            proposal_id=report.proposal_id,
            operator=operator,
            command=command,
        )

    applied_proposal_ids: list[str] = []
    if run_autonomy_after:
        for proposal_id in proposal_ids:
            try:
                generate_checks_for_proposal(db_path=db_path, proposal_id=proposal_id)
            except CheckError as exc:
                if not str(exc).startswith("no_check_spec_changes:"):
                    notes.append(f"consolidation_check_generation:{proposal_id}:{exc}")
            except StorageError as exc:
                notes.append(f"consolidation_check_generation:{proposal_id}:{exc}")
        try:
            autonomy = run_autonomy(
                db_path=db_path,
                profile_id=resolved_profile_id,
                harness_workspace_root=harness_workspace_root,
            )
        except (AutonomyRunError, StorageError) as exc:
            raise SkillbookManagerError(str(exc)) from exc
        proposal_id_set = set(proposal_ids)
        for decision in autonomy.decisions:
            if decision.proposal_id in proposal_id_set and decision.state_after == "applied":
                applied_proposal_ids.append(decision.proposal_id)

    return ConsolidationReport(
        profile_id=resolved_profile_id,
        duplicate_group_count=len(groups),
        proposal_ids=tuple(proposal_ids),
        applied_proposal_ids=tuple(applied_proposal_ids),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------------------
# Command-operator path (thin wrapper)
# ---------------------------------------------------------------------------

def _author_consolidation_via_command(
    *,
    db_path: Path,
    output_dir: Optional[Path],
    groups: list[list[dict[str, Any]]],
    profile_id: str,
    command: Optional[Sequence[str]],
    schema_path: Optional[Path],
    notes: list[str],
) -> list[dict[str, Any]]:
    import os
    import subprocess

    from .operator_prompts import (
        BEGIN_PROPOSAL_BLOCK,
        END_PROPOSAL_BLOCK,
        write_consolidation_prompt_artifacts,
    )

    if not command:
        raise SkillbookManagerError("operator_command_required")
    resolved_output_dir = Path(output_dir) if output_dir is not None else _default_output_dir(db_path)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    prompt_report = write_consolidation_prompt_artifacts(
        db_path=db_path,
        output_dir=resolved_output_dir,
        profile_id=profile_id,
        schema_path=schema_path,
    )
    prompt_text = prompt_report.prompt_path.read_text()
    env = os.environ.copy()
    env["KYOKO_EVIDENCE_PATH"] = str(prompt_report.evidence_path)
    env["KYOKO_OPERATOR_PROMPT_PATH"] = str(prompt_report.prompt_path)
    env["KYOKO_PROFILE_ID"] = profile_id
    env["KYOKO_PROPOSAL_BLOCK_BEGIN"] = BEGIN_PROPOSAL_BLOCK
    env["KYOKO_PROPOSAL_BLOCK_END"] = END_PROPOSAL_BLOCK

    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            input=prompt_text,
        )
    except FileNotFoundError as exc:
        raise SkillbookManagerError(f"operator_command_not_found:{command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SkillbookManagerError("operator_timeout:120") from exc
    (resolved_output_dir / "consolidation-output.txt").write_text(completed.stdout)
    if completed.returncode != 0:
        raise SkillbookManagerError(f"operator_failed:{completed.returncode}")

    proposals = _extract_consolidation_proposals(completed.stdout)
    if not proposals:
        notes.append("consolidation_command_returned_no_proposals")
    for proposal in proposals:
        # Never trust the operator for identity.
        proposal["profile_id"] = profile_id
    return proposals


def _extract_consolidation_proposals(output: str) -> list[dict[str, Any]]:
    """Parse one-or-more proposal blocks from operator stdout."""
    import json

    from .operator_prompts import BEGIN_PROPOSAL_BLOCK, END_PROPOSAL_BLOCK

    proposals: list[dict[str, Any]] = []
    cursor = 0
    while True:
        begin = output.find(BEGIN_PROPOSAL_BLOCK, cursor)
        if begin == -1:
            break
        start = begin + len(BEGIN_PROPOSAL_BLOCK)
        end = output.find(END_PROPOSAL_BLOCK, start)
        if end == -1:
            raise SkillbookManagerError("consolidation_proposal_block_unterminated")
        raw = output[start:end].strip()
        try:
            proposal = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SkillbookManagerError(f"consolidation_proposal_json_invalid:{exc}") from exc
        if not isinstance(proposal, dict):
            raise SkillbookManagerError("consolidation_proposal_must_be_object")
        proposals.append(proposal)
        cursor = end + len(END_PROPOSAL_BLOCK)
    return proposals


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _select_winner(members: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(skill: dict[str, Any]) -> tuple[int, str, str]:
        occurrence_count = len(skill.get("occurrences") or [])
        # max occurrences -> tie-break oldest created_at -> smallest id
        return (-occurrence_count, str(skill.get("created_at") or ""), str(skill.get("id")))

    return sorted(members, key=sort_key)[0]


def _merged_keywords(members: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for skill in members:
        for keyword in _normalized_keyword_list(skill.get("keywords")):
            if keyword not in seen:
                seen.add(keyword)
                merged.append(keyword)
    return merged


def _merged_occurrences(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    merged: list[dict[str, Any]] = []
    for skill in members:
        for ref in _occurrence_refs(skill.get("occurrences")):
            key = (ref.get("entity_type"), ref.get("entity_id"), ref.get("role"))
            if key not in seen:
                seen.add(key)
                merged.append(ref)
    return merged


def _occurrence_refs(occurrences: Any) -> list[dict[str, Any]]:
    """Normalize stored skill occurrences into schema-valid evidence_refs (role required)."""
    refs: list[dict[str, Any]] = []
    if not isinstance(occurrences, list):
        return refs
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            continue
        entity_type = occurrence.get("entity_type")
        entity_id = occurrence.get("entity_id")
        if not isinstance(entity_type, str) or not isinstance(entity_id, str):
            continue
        role = occurrence.get("role")
        ref: dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "role": role if role in _EVIDENCE_ROLES else "source",
        }
        refs.append(ref)
    return refs


def _evidence_refs_for(
    winner: dict[str, Any],
    merged_occurrences: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_run_id = winner.get("source_run_id")
    if isinstance(source_run_id, str) and source_run_id:
        return [
            {
                "entity_type": "run",
                "entity_id": source_run_id,
                "role": "source",
                "note": "Winner skill's source run; consolidation verification target.",
            }
        ]
    # Fall back to the merged occurrences (already schema-valid) when no source run exists.
    return [dict(ref) for ref in merged_occurrences]


def _combined_issue(members: list[dict[str, Any]]) -> str:
    for skill in members:
        text = _normalized_text(skill.get("issue"))
        if text:
            return str(skill.get("issue")).strip()
    return "Consolidated duplicate skillbook entries."


def _combined_insight(members: list[dict[str, Any]]) -> str:
    insights: list[str] = []
    seen: set[str] = set()
    for skill in members:
        text = skill.get("insight")
        if isinstance(text, str) and text.strip():
            normalized = _normalized_text(text)
            if normalized and normalized not in seen:
                seen.add(normalized)
                insights.append(text.strip())
    if not insights:
        return "Consolidated guidance from duplicate skillbook entries."
    return " ".join(insights)


def _normalized_or_default(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _normalized_keyword_set(keywords: Any) -> frozenset[str]:
    return frozenset(_normalized_keyword_list(keywords))


def _normalized_keyword_list(keywords: Any) -> list[str]:
    if not isinstance(keywords, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        if not isinstance(keyword, str):
            continue
        value = keyword.strip().lower()
        if value and value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized


def _normalized_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().lower().split())


def _resolve_profile_id(
    db_path: Path,
    groups: list[list[dict[str, Any]]],
) -> Optional[str]:
    for group in groups:
        for skill in group:
            pid = skill.get("profile_id")
            if isinstance(pid, str) and pid:
                return pid
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT id FROM profiles ORDER BY created_at, id LIMIT 1"
        ).fetchone()
    return str(row["id"]) if row is not None else None


def _record_consolidation_operator_run(
    *,
    db_path: Path,
    profile_id: str,
    proposal_id: str,
    operator: str,
    command: Optional[Sequence[str]],
) -> None:
    """Record a lightweight operator_run labeled 'consolidate' for traceability."""
    import json
    import uuid

    now = utc_now()
    operator_run_id = f"oprun_consolidate_{uuid.uuid4().hex[:12]}"
    metadata = {
        "kind": "consolidate",
        "proposal_id": proposal_id,
        "command": list(command) if command is not None else None,
    }
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO operator_runs (
              id,
              profile_id,
              adapter_id,
              operator_label,
              operator_kind,
              status,
              started_at,
              ended_at,
              evidence_ref,
              prompt_ref,
              raw_output_ref,
              proposal_id,
              error,
              metadata_json,
              schedule_id,
              analyzed_since,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operator_run_id,
                profile_id,
                None,
                "consolidate",
                "consolidate" if operator == "mock" else f"consolidate:{operator}",
                "succeeded",
                now,
                now,
                None,
                None,
                None,
                proposal_id,
                None,
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                None,
                None,
                now,
                now,
            ),
        )


def _default_output_dir(db_path: Path) -> Path:
    safe_timestamp = (
        utc_now()
        .replace(":", "")
        .replace("-", "")
        .replace(".", "")
        .replace("+", "")
    )
    return db_path.parent / ".kyoko" / "consolidate-runs" / f"consolidate_{safe_timestamp}"


_EVIDENCE_ROLES = {
    "failure",
    "context",
    "counterexample",
    "verification",
    "regression",
    "source",
}
