from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .storage import connect, initialize_database


DIRECT_COUNT_TABLES = (
    "sources",
    "agent_identities",
    "workflow_nodes",
    "queues",
    "tasks",
    "runs",
    "handoffs",
    "timeline_events",
    "learning_proposals",
    "skills",
    "context_delivery_rules",
    "eval_specs",
    "eval_runs",
    "replay_runs",
    "replay_adapters",
    "operator_adapters",
    "operator_runs",
    "patch_transactions",
    "harness_target_locks",
    "eval_spec_locks",
    "payload_blobs",
)


def list_profiles(db_path: Path) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        profile_rows = connection.execute(
            """
            SELECT id, name, root_path, status, created_at, updated_at
            FROM profiles
            ORDER BY created_at, id
            """
        ).fetchall()
        profiles: list[dict[str, Any]] = []
        for row in profile_rows:
            profile_id = str(row["id"])
            counts = {
                table: _count(connection, table, profile_id)
                for table in DIRECT_COUNT_TABLES
            }
            counts["spans"] = _count_spans(connection, profile_id)
            counts["task_attempts"] = _count_task_attempts(connection, profile_id)
            counts["failed_runs"] = _count_where(
                connection,
                "runs",
                profile_id,
                "status = ?",
                ("failed",),
            )
            counts["failed_spans"] = _count_failed_spans(connection, profile_id)
            latest_run = _latest_run(connection, profile_id)
            routing = _routing_summary(connection, profile_id, counts)
            routing["suggested_commands"] = _suggested_commands(
                db_path=db_path,
                connection=connection,
                profile_id=profile_id,
                routing=routing,
            )
            profiles.append(
                {
                    "id": profile_id,
                    "name": row["name"],
                    "root_path": row["root_path"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "counts": counts,
                    "storage": {
                        "registered_blob_bytes": _registered_blob_bytes(connection, profile_id),
                    },
                    "agent_identities": _agent_identities(connection, profile_id),
                    "latest_run": latest_run,
                    "routing": routing,
                }
            )
    return profiles


def _count(connection: Any, table: str, profile_id: str) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    return int(row["count"])


def _count_where(
    connection: Any,
    table: str,
    profile_id: str,
    where_sql: str,
    params: tuple[Any, ...],
) -> int:
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM {table} WHERE profile_id = ? AND {where_sql}",
        (profile_id, *params),
    ).fetchone()
    return int(row["count"])


def _count_spans(connection: Any, profile_id: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM spans
        JOIN runs ON runs.id = spans.run_id
        WHERE runs.profile_id = ?
        """,
        (profile_id,),
    ).fetchone()
    return int(row["count"])


def _count_task_attempts(connection: Any, profile_id: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM task_attempts
        JOIN tasks ON tasks.id = task_attempts.task_id
        WHERE tasks.profile_id = ?
        """,
        (profile_id,),
    ).fetchone()
    return int(row["count"])


def _count_failed_spans(connection: Any, profile_id: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS count
        FROM spans
        JOIN runs ON runs.id = spans.run_id
        WHERE runs.profile_id = ? AND spans.status = ?
        """,
        (profile_id, "failed"),
    ).fetchone()
    return int(row["count"])


def _registered_blob_bytes(connection: Any, profile_id: str) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(SUM(size_bytes), 0) AS size_bytes
        FROM payload_blobs
        WHERE profile_id = ?
        """,
        (profile_id,),
    ).fetchone()
    return int(row["size_bytes"])


def _latest_run(connection: Any, profile_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, status, started_at, ended_at, summary
        FROM runs
        WHERE profile_id = ?
        ORDER BY COALESCE(ended_at, started_at) DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "summary": row["summary"],
    }


def _agent_identities(connection: Any, profile_id: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, name, kind, role, source_id, model, workspace_path
        FROM agent_identities
        WHERE profile_id = ?
        ORDER BY kind, name, id
        """,
        (profile_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "role": row["role"],
            "source_id": row["source_id"],
            "model": row["model"],
            "workspace_path": row["workspace_path"],
        }
        for row in rows
    ]


def _routing_summary(connection: Any, profile_id: str, counts: dict[str, int]) -> dict[str, Any]:
    latest_failed_run = _latest_failed_run(connection, profile_id)
    active_proposal = _latest_active_proposal(connection, profile_id)
    if counts["runs"] == 0:
        return {
            "state": "setup_sources",
            "next_action": "ingest",
            "reason": "no_runs",
            "run_id": None,
            "proposal_id": None,
            "eval_spec_id": None,
            "eval_run_id": None,
            "replay_run_id": None,
        }
    if active_proposal is None:
        latest_applied = _latest_proposal_with_state(connection, profile_id, "applied")
        if latest_applied is not None:
            return {
                "state": "loop_complete",
                "next_action": "monitor",
                "reason": "latest_proposal_applied",
                "run_id": latest_failed_run["id"] if latest_failed_run is not None else None,
                "proposal_id": latest_applied["id"],
                "proposal_section": latest_applied["section"],
                "proposal_state": latest_applied["state"],
                "eval_spec_id": None,
                "eval_run_id": None,
                "replay_run_id": None,
            }
        if counts["failed_runs"] > 0 or counts["failed_spans"] > 0:
            return {
                "state": "needs_analysis",
                "next_action": "analyze",
                "reason": "failed_evidence_without_active_proposal",
                "run_id": latest_failed_run["id"] if latest_failed_run is not None else None,
                "proposal_id": None,
                "eval_spec_id": None,
                "eval_run_id": None,
                "replay_run_id": None,
            }
        return {
            "state": "monitor",
            "next_action": "monitor",
            "reason": "no_active_failures",
            "run_id": None,
            "proposal_id": None,
            "eval_spec_id": None,
            "eval_run_id": None,
            "replay_run_id": None,
        }

    proposal_id = str(active_proposal["id"])
    eval_spec = _latest_eval_spec_for_proposal(connection, proposal_id)
    if eval_spec is None:
        return {
            "state": "needs_eval_generation",
            "next_action": "generate_evals",
            "reason": "active_proposal_without_eval_specs",
            "run_id": latest_failed_run["id"] if latest_failed_run is not None else None,
            "proposal_id": proposal_id,
            "proposal_section": active_proposal["section"],
            "proposal_state": active_proposal["state"],
            "eval_spec_id": None,
            "eval_run_id": None,
            "replay_run_id": None,
        }

    passed_eval_run = _latest_eval_run_for_proposal(connection, proposal_id, status="passed")
    latest_eval_run = _latest_eval_run_for_proposal(connection, proposal_id)
    latest_replay_run = _latest_replay_run_for_proposal(connection, proposal_id)
    if passed_eval_run is None:
        return {
            "state": "needs_replay_or_eval",
            "next_action": "run_replay_or_eval",
            "reason": "no_passing_eval_run",
            "run_id": latest_failed_run["id"] if latest_failed_run is not None else None,
            "proposal_id": proposal_id,
            "proposal_section": active_proposal["section"],
            "proposal_state": active_proposal["state"],
            "eval_spec_id": eval_spec["id"],
            "eval_run_id": latest_eval_run["id"] if latest_eval_run is not None else None,
            "eval_run_status": latest_eval_run["status"] if latest_eval_run is not None else "not_run",
            "replay_run_id": latest_replay_run["id"] if latest_replay_run is not None else None,
            "replay_run_status": latest_replay_run["status"] if latest_replay_run is not None else "not_run",
        }

    policy = _policy_for_profile(connection, profile_id)
    section = str(active_proposal["section"])
    mode = str(policy.get(f"{section}_mode", "propose"))
    routing = {
        "state": "ready_for_autonomy",
        "next_action": "run_autonomy" if mode == "autonomous" else "review_proposal",
        "reason": "passing_eval_available",
        "run_id": latest_failed_run["id"] if latest_failed_run is not None else None,
        "proposal_id": proposal_id,
        "proposal_section": section,
        "proposal_state": active_proposal["state"],
        "autonomy_mode": mode,
        "eval_spec_id": eval_spec["id"],
        "eval_run_id": passed_eval_run["id"],
        "eval_run_status": passed_eval_run["status"],
        "replay_run_id": latest_replay_run["id"] if latest_replay_run is not None else None,
        "replay_run_status": latest_replay_run["status"] if latest_replay_run is not None else "not_run",
    }
    if section == "harness":
        routing["harness_repo_patch_allowed"] = bool(policy.get("allow_repo_patch", False))
        if mode == "autonomous":
            routing.update(_harness_workspace_summary(connection, profile_id))
    return routing


def _latest_failed_run(connection: Any, profile_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT DISTINCT runs.id, runs.status, runs.started_at, runs.ended_at, runs.summary
        FROM runs
        LEFT JOIN spans ON spans.run_id = runs.id
        WHERE runs.profile_id = ?
          AND (
            runs.status IN ('failed', 'timed_out', 'errored', 'cancelled')
            OR spans.status IN ('failed', 'timed_out', 'errored', 'cancelled')
          )
        ORDER BY COALESCE(runs.ended_at, runs.started_at) DESC, runs.id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "summary": row["summary"],
    }


def _latest_active_proposal(connection: Any, profile_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, section, state, title, created_at
        FROM learning_proposals
        WHERE profile_id = ?
          AND state = 'pending'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    return _proposal_summary(row)


def _latest_proposal_with_state(connection: Any, profile_id: str, state: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, section, state, title, created_at
        FROM learning_proposals
        WHERE profile_id = ?
          AND state = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (profile_id, state),
    ).fetchone()
    return _proposal_summary(row)


def _proposal_summary(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "section": row["section"],
        "state": row["state"],
        "title": row["title"],
        "created_at": row["created_at"],
    }


def _latest_eval_spec_for_proposal(connection: Any, proposal_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, status, trust_level, eval_type, created_at
        FROM eval_specs
        WHERE proposal_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (proposal_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "trust_level": row["trust_level"],
        "eval_type": row["eval_type"],
        "created_at": row["created_at"],
    }


def _latest_eval_run_for_proposal(
    connection: Any,
    proposal_id: str,
    *,
    status: Optional[str] = None,
) -> dict[str, Any] | None:
    where = "proposal_id = ?"
    args: tuple[Any, ...] = (proposal_id,)
    if status is not None:
        where += " AND status = ?"
        args = (proposal_id, status)
    row = connection.execute(
        f"""
        SELECT id, status, eval_spec_id, replay_run_id, created_at
        FROM eval_runs
        WHERE {where}
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        args,
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "eval_spec_id": row["eval_spec_id"],
        "replay_run_id": row["replay_run_id"],
        "created_at": row["created_at"],
    }


def _latest_replay_run_for_proposal(connection: Any, proposal_id: str) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT id, status, eval_spec_id, side_effect_mode, created_at
        FROM replay_runs
        WHERE proposal_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (proposal_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "status": row["status"],
        "eval_spec_id": row["eval_spec_id"],
        "side_effect_mode": row["side_effect_mode"],
        "created_at": row["created_at"],
    }


def _policy_for_profile(connection: Any, profile_id: str) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT context_mode, harness_mode, allow_repo_patch
        FROM autonomy_policies
        WHERE profile_id = ?
        """,
        (profile_id,),
    ).fetchone()
    if row is None:
        return {
            "context_mode": "propose",
            "harness_mode": "propose",
            "allow_repo_patch": False,
        }
    return {
        "context_mode": row["context_mode"],
        "harness_mode": row["harness_mode"],
        "allow_repo_patch": bool(row["allow_repo_patch"]),
    }


def _harness_workspace_summary(connection: Any, profile_id: str) -> dict[str, Any]:
    row = connection.execute(
        "SELECT root_path FROM profiles WHERE id = ?",
        (profile_id,),
    ).fetchone()
    root_path = row["root_path"] if row is not None else None
    if not isinstance(root_path, str) or not root_path:
        return {
            "harness_workspace_root": None,
            "harness_workspace_root_status": "missing",
            "harness_workspace_root_required": True,
        }
    workspace_root = Path(root_path).expanduser()
    status = "available"
    if not workspace_root.exists():
        status = "not_found"
    elif not workspace_root.is_dir():
        status = "not_directory"
    return {
        "harness_workspace_root": str(workspace_root),
        "harness_workspace_root_status": status,
        "harness_workspace_root_required": status != "available",
    }


def _suggested_commands(
    *,
    db_path: Path,
    connection: Any,
    profile_id: str,
    routing: dict[str, Any],
) -> list[dict[str, Any]]:
    state = str(routing.get("state") or "")
    proposal_id = routing.get("proposal_id")
    eval_spec_id = routing.get("eval_spec_id")
    operator_adapter_id = _latest_enabled_adapter_id(connection, "operator_adapters", profile_id)
    replay_adapter_id = _latest_enabled_adapter_id(connection, "replay_adapters", profile_id)
    commands: list[dict[str, Any]] = []

    if state == "setup_sources":
        commands.append(
            _command(
                "discover_sources",
                "Discover local Hermes/OpenClaw sources",
                ["discover-sources", "--db", str(db_path), "--profile-id", profile_id, "--json"],
                mutating=False,
            )
        )
    elif state == "needs_analysis":
        if operator_adapter_id is not None:
            commands.append(
                _command(
                    "analyze_operator",
                    "Run registered operator analysis",
                    [
                        "analyze",
                        "--db",
                        str(db_path),
                        "--operator",
                        operator_adapter_id,
                        "--profile-id",
                        profile_id,
                        "--json",
                    ],
                    mutating=True,
                )
            )
        else:
            commands.append(
                _command(
                    "operator_adapter_bootstrap",
                    "Register installed operator CLI presets",
                    ["operator-adapter-bootstrap", "--db", str(db_path), "--profile-id", profile_id, "--json"],
                    mutating=True,
                    requires=["installed Codex, Claude, Hermes, or OpenClaw CLI"],
                )
            )
        commands.append(
            _command(
                "operator_prompt",
                "Prepare operator evidence and prompt artifacts",
                [
                    "operator-prompt",
                    "--db",
                    str(db_path),
                    "--profile-id",
                    profile_id,
                    "--output-dir",
                    str(_artifact_dir(db_path, "operator-prompts", profile_id)),
                    "--json",
                ],
                mutating=True,
            )
        )
    elif state == "needs_eval_generation" and isinstance(proposal_id, str):
        commands.append(
            _command(
                "generate_evals",
                "Generate eval specs for the active proposal",
                ["generate-evals", "--db", str(db_path), proposal_id, "--json"],
                mutating=True,
            )
        )
    elif state == "needs_replay_or_eval" and isinstance(eval_spec_id, str):
        if replay_adapter_id is not None:
            commands.append(
                _command(
                    "run_replay_adapter",
                    "Run registered replay adapter and linked eval",
                    [
                        "replay-adapter-run",
                        "--db",
                        str(db_path),
                        replay_adapter_id,
                        eval_spec_id,
                        "--run-eval",
                        "--json",
                    ],
                    mutating=True,
                )
            )
        commands.append(
            _command(
                "run_eval",
                "Run eval directly if replay evidence is not required",
                ["run-eval", "--db", str(db_path), eval_spec_id, "--json"],
                mutating=True,
                requires=["eval spec that does not require completed replay evidence"],
            )
        )
    elif state == "ready_for_autonomy" and isinstance(proposal_id, str):
        if routing.get("next_action") == "run_autonomy":
            args = ["run-autonomy", "--db", str(db_path), "--profile-id", profile_id]
            requires: list[str] = []
            if routing.get("proposal_section") == "harness":
                if not bool(routing.get("harness_repo_patch_allowed", False)):
                    requires.append("repo patch policy enabled with --repo-patch on")
                workspace_root = routing.get("harness_workspace_root")
                workspace_status = routing.get("harness_workspace_root_status")
                if workspace_status == "available" and isinstance(workspace_root, str):
                    args.extend(["--harness-workspace-root", workspace_root])
                else:
                    requires.append("existing harness workspace root")
            args.append("--json")
            commands.append(
                _command(
                    "run_autonomy",
                    "Run profile autonomy gate",
                    args,
                    mutating=True,
                    requires=requires,
                )
            )
        commands.append(
            _command(
                "proposal_detail",
                "Review proposal detail and evidence chain",
                ["proposal-detail", "--db", str(db_path), proposal_id, "--json"],
                mutating=False,
            )
        )
    elif state in {"loop_complete", "monitor"}:
        commands.append(
            _command(
                "dashboard_metrics",
                "Inspect current product-loop metrics",
                ["dashboard-metrics", "--db", str(db_path), "--profile-id", profile_id, "--json"],
                mutating=False,
            )
        )

    return commands


def _command(
    intent: str,
    label: str,
    args: list[str],
    *,
    mutating: bool,
    requires: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "label": label,
        "cli_args": ["python3", "-m", "kyoko", *args],
        "mutating": mutating,
        "requires": requires or [],
    }


def _artifact_dir(db_path: Path, kind: str, profile_id: str) -> Path:
    return db_path.parent / kind / profile_id


def _latest_enabled_adapter_id(connection: Any, table: str, profile_id: str) -> Optional[str]:
    row = connection.execute(
        f"""
        SELECT id
        FROM {table}
        WHERE profile_id = ?
          AND enabled = 1
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (profile_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["id"])
