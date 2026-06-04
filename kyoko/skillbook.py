from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from .apply import list_context_delivery_rules, list_skills
from .storage import connect


ACE_SKILLBOOK_SCHEMA_VERSION = "2"


def export_skillbook(
    db_path: Path,
    *,
    section: str = "all",
    include_inactive: bool = False,
    profile_id: Optional[str] = None,
) -> dict[str, Any]:
    skills = _filtered_skills(
        db_path,
        section=section,
        include_inactive=include_inactive,
        profile_id=profile_id,
    )
    return _skillbook_payload(skills)


def render_skillbook_prompt(
    db_path: Path,
    *,
    section: str = "context",
    include_inactive: bool = False,
    target_entity_type: Optional[str] = None,
    target_entity_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    include_delivery_rules: bool = True,
) -> str:
    skills = _filtered_skills(
        db_path,
        section=section,
        include_inactive=include_inactive,
        profile_id=profile_id,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
    )
    skillbook = _skillbook_payload(skills)
    parts: list[str] = []

    for section_name in ("context", "harness"):
        skill_ids = skillbook["sections"].get(section_name, [])
        if not skill_ids:
            continue
        parts.append(f"## {section_name}")
        for skill_id in skill_ids:
            skill = skillbook["skills"][skill_id]
            parts.append(f"- [{skill['id']}]")
            parts.append(f"  Keywords: {', '.join(skill['keywords'])}")
            parts.append(f"  Issue: {skill['issue']}")
            insight = skill.get("insight")
            if insight:
                parts.append(f"  Insight: {insight}")
            parts.append("")

    if include_delivery_rules and section in {"all", "context"}:
        rules = _filtered_delivery_rules(
            db_path,
            include_inactive=include_inactive,
            profile_id=profile_id,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
        )
        if rules:
            parts.append("## context_delivery_rules")
            for rule in rules:
                target = rule.get("target", {})
                rule_body = rule.get("rule", {})
                parts.append(f"- [{rule['id']}]")
                parts.append(
                    "  Target: "
                    f"{target.get('entity_type', 'unknown')}:{target.get('entity_id', 'unknown')}"
                )
                delivery_mode = rule_body.get("mode") or rule_body.get("delivery_mode")
                if isinstance(delivery_mode, str) and delivery_mode:
                    parts.append(f"  Mode: {delivery_mode}")
                parts.append(f"  Rule: {json.dumps(rule_body, sort_keys=True)}")
                parts.append("")

    return "\n".join(parts).rstrip()


def write_skillbook_export(
    db_path: Path,
    *,
    output_path: Path,
    output_format: str,
    section: str = "all",
    include_inactive: bool = False,
    profile_id: Optional[str] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        payload = export_skillbook(
            db_path,
            section=section,
            include_inactive=include_inactive,
            profile_id=profile_id,
        )
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return
    if output_format == "prompt":
        output_path.write_text(
            render_skillbook_prompt(
                db_path,
                section=section,
                include_inactive=include_inactive,
                profile_id=profile_id,
            )
            + "\n"
        )
        return
    raise ValueError(f"unsupported export format: {output_format}")


def _filtered_skills(
    db_path: Path,
    *,
    section: str,
    include_inactive: bool,
    profile_id: Optional[str] = None,
    target_entity_type: Optional[str] = None,
    target_entity_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    if section not in {"all", "context", "harness"}:
        raise ValueError(f"unsupported section: {section}")

    selected_profile_id = _resolve_profile_id(
        db_path,
        profile_id=profile_id,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
    )
    target_requested = bool(target_entity_type and target_entity_id)
    if target_requested and selected_profile_id is None:
        return []
    delivery_rules = []
    if section in {"all", "context"} and target_requested:
        delivery_rules = _filtered_delivery_rules(
            db_path,
            include_inactive=include_inactive,
            profile_id=selected_profile_id,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
        )

    skills = list_skills(db_path, profile_id=selected_profile_id)
    filtered = []
    for skill in skills:
        if not include_inactive and not skill.get("active", False):
            continue
        if section != "all" and skill.get("section") != section:
            continue
        filtered.append(skill)
    if delivery_rules:
        filtered = _apply_delivery_rule_filters(filtered, delivery_rules)
    return sorted(filtered, key=lambda item: (item.get("section", ""), item.get("id", "")))


def _filtered_delivery_rules(
    db_path: Path,
    *,
    include_inactive: bool,
    profile_id: Optional[str],
    target_entity_type: Optional[str],
    target_entity_id: Optional[str],
) -> list[dict[str, Any]]:
    selected_profile_id = _resolve_profile_id(
        db_path,
        profile_id=profile_id,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
    )
    if target_entity_type and target_entity_id and selected_profile_id is None:
        return []
    rules = list_context_delivery_rules(db_path, profile_id=selected_profile_id)
    filtered = []
    for rule in rules:
        if not include_inactive and not rule.get("active", False):
            continue
        target = rule.get("target", {})
        if target_entity_type and target_entity_id and not _rule_matches_target(
            target,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
        ):
            continue
        filtered.append(rule)
    return sorted(filtered, key=lambda item: str(item.get("id", "")))


def _resolve_profile_id(
    db_path: Path,
    *,
    profile_id: Optional[str],
    target_entity_type: Optional[str],
    target_entity_id: Optional[str],
) -> Optional[str]:
    if profile_id:
        return profile_id
    if target_entity_type == "profile" and target_entity_id:
        return target_entity_id
    if not target_entity_type or not target_entity_id or not db_path.exists():
        return None

    table = {
        "agent_identity": "agent_identities",
        "workflow_node": "workflow_nodes",
        "queue": "queues",
        "task": "tasks",
        "run": "runs",
    }.get(target_entity_type)
    try:
        with connect(db_path) as connection:
            if table is not None:
                row = connection.execute(
                    f"SELECT profile_id FROM {table} WHERE id = ?",
                    (target_entity_id,),
                ).fetchone()
                return str(row["profile_id"]) if row is not None else None
            if target_entity_type == "span":
                row = connection.execute(
                    """
                    SELECT runs.profile_id AS profile_id
                    FROM spans
                    JOIN runs ON runs.id = spans.run_id
                    WHERE spans.id = ?
                    """,
                    (target_entity_id,),
                ).fetchone()
                return str(row["profile_id"]) if row is not None else None
    except sqlite3.OperationalError:
        return None
    return None


def _rule_matches_target(
    target: dict[str, Any],
    *,
    target_entity_type: str,
    target_entity_id: str,
) -> bool:
    entity_type = target.get("entity_type")
    entity_id = target.get("entity_id")
    if entity_type == target_entity_type and entity_id == target_entity_id:
        return True
    return entity_type == "profile"


def _apply_delivery_rule_filters(
    skills: list[dict[str, Any]],
    rules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    include_skill_ids: set[str] = set()
    include_keywords: set[str] = set()
    exclude_skill_ids: set[str] = set()
    exclude_keywords: set[str] = set()
    max_skills: Optional[int] = None

    for rule in rules:
        body = rule.get("rule", {})
        if not isinstance(body, dict):
            continue
        include_skill_ids.update(_string_set(body.get("include_skill_ids")))
        include_keywords.update(_string_set(body.get("include_keywords")))
        exclude_skill_ids.update(_string_set(body.get("exclude_skill_ids")))
        exclude_keywords.update(_string_set(body.get("exclude_keywords")))
        raw_max = body.get("max_skills")
        if isinstance(raw_max, int) and raw_max > 0:
            max_skills = raw_max if max_skills is None else min(max_skills, raw_max)

    has_include_filters = bool(include_skill_ids or include_keywords)
    selected = []
    for skill in skills:
        skill_id = str(skill.get("id", ""))
        skill_keywords = {str(keyword) for keyword in skill.get("keywords", [])}
        if skill_id in exclude_skill_ids or skill_keywords.intersection(exclude_keywords):
            continue
        if has_include_filters and skill_id not in include_skill_ids and not skill_keywords.intersection(
            include_keywords
        ):
            continue
        selected.append(skill)

    if max_skills is not None:
        return selected[:max_skills]
    return selected


def _string_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item}


def _skillbook_payload(skills: list[dict[str, Any]]) -> dict[str, Any]:
    skills_by_id = {}
    sections = {"context": [], "harness": []}

    for skill in skills:
        skill_payload = _ace_skill(skill)
        skills_by_id[skill_payload["id"]] = skill_payload
        sections.setdefault(skill_payload["section"], []).append(skill_payload["id"])

    return {
        "schema_version": ACE_SKILLBOOK_SCHEMA_VERSION,
        "skills": skills_by_id,
        "sections": {key: value for key, value in sections.items() if value},
        "next_id": 0,
        "similarity_decisions": {},
    }


def _ace_skill(skill: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": skill["id"],
        "section": skill["section"],
        "keywords": list(skill.get("keywords", [])),
        "issue": skill["issue"],
        "insight": skill.get("insight"),
        "occurrences": [
            _ace_occurrence(
                occurrence,
                source_run_id=skill.get("source_run_id"),
                issue=skill["issue"],
                insight=skill.get("insight"),
            )
            for occurrence in skill.get("occurrences", [])
        ],
        "active": bool(skill.get("active", True)),
        "used_count": 0,
        "helpful_count": int(skill.get("helpful_count", 0)),
        "harmful_count": int(skill.get("harmful_count", 0)),
        "neutral_count": int(skill.get("neutral_count", 0)),
        "created_at": skill["created_at"],
        "updated_at": skill["updated_at"],
    }


def _ace_occurrence(
    occurrence: dict[str, Any],
    *,
    source_run_id: Optional[str],
    issue: str,
    insight: Optional[str],
) -> dict[str, Any]:
    entity_type = str(occurrence.get("entity_type", "unknown"))
    entity_id = str(occurrence.get("entity_id", source_run_id or "unknown"))
    trace_id = source_run_id or entity_id
    return {
        "trace_uid": f"kyoko:{trace_id}",
        "source_system": "kyoko",
        "trace_id": trace_id,
        "display_name": f"{entity_type}:{entity_id}",
        "relation": str(occurrence.get("role", "source")),
        "operation_type": "ADD",
        "error_identification": issue,
        "learning_text": insight or issue,
    }
