from __future__ import annotations

import fnmatch
import json
import posixpath
import re
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .storage import StorageError, connect, initialize_database, utc_now


UNSAFE_SIDE_EFFECT_MODES = {"live_network", "unknown"}
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|client[_-]?secret|access[_-]?key|"
    r"refresh[_-]?token|secret|password|passwd|pwd|token|credential|"
    r"private[_-]?key|cookie)\b\s*[:=]\s*[\"']?([^\"'\s#]+)"
)
SECRET_VALUE_PATTERNS = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{20,}")),
)
SECRET_PLACEHOLDERS = {
    "",
    "...",
    "changeme",
    "example",
    "example-value",
    "placeholder",
    "redacted",
    "[redacted]",
    "${token}",
    "${api_key}",
}


class HarnessError(Exception):
    """Raised when a harness proposal cannot be prepared."""


@dataclass(frozen=True)
class HarnessPrepareReport:
    proposal_id: str
    profile_id: str
    patch_transaction_ids: tuple[str, ...]
    state: str


@dataclass(frozen=True)
class HarnessPatchApplyReport:
    patch_transaction_id: str
    proposal_id: str
    profile_id: str
    target_paths: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class HarnessPatchRollbackReport:
    patch_transaction_id: str
    proposal_id: str
    profile_id: str
    target_paths: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class HarnessTargetLockReport:
    profile_id: str
    target_path: str
    human_locked: bool
    reason: Optional[str] = None
    actor_agent_identity_id: Optional[str] = None

    def to_json(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "target_path": self.target_path,
            "human_locked": self.human_locked,
            "reason": self.reason,
            "actor_agent_identity_id": self.actor_agent_identity_id,
        }


@dataclass(frozen=True)
class UnifiedDiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class UnifiedDiffFilePatch:
    path: str
    old_path: str
    new_path: str
    hunks: tuple[UnifiedDiffHunk, ...]


def prepare_harness_proposal(*, db_path: Path, proposal_id: str) -> HarnessPrepareReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        proposal = _get_proposal(connection, proposal_id)
        profile_id = str(proposal["profile_id"])
        _ensure_kyoko_source(connection, profile_id)
        changes = _validate_prepare_allowed(connection, proposal)

        now = utc_now()
        producer = _json_loads(proposal["producer_json"], {})
        agent_identity_id = producer.get("agent_identity_id") if isinstance(producer, dict) else None

        _insert_timeline_event(
            connection,
            event_id=f"event_{proposal_id}_harness_prepare_started",
            profile_id=profile_id,
            entity_type="learning_proposal",
            entity_id=proposal_id,
            kind="harness_prepare_started",
            at=now,
            agent_identity_id=agent_identity_id if isinstance(agent_identity_id, str) else None,
            metadata={"section": "harness"},
        )

        patch_transaction_ids = _create_patch_transactions(connection, proposal, changes, now)
        # Proposal stays "pending" while its patch transactions are gated/applied; there is
        # no separate "gated" proposal state in the collapsed 3+1 model.

        _insert_timeline_event(
            connection,
            event_id=f"event_{proposal_id}_harness_prepared",
            profile_id=profile_id,
            entity_type="learning_proposal",
            entity_id=proposal_id,
            kind="harness_prepared",
            at=now,
            agent_identity_id=agent_identity_id if isinstance(agent_identity_id, str) else None,
            metadata={"patch_transaction_ids": list(patch_transaction_ids)},
        )

    return HarnessPrepareReport(
        proposal_id=proposal_id,
        profile_id=profile_id,
        patch_transaction_ids=tuple(patch_transaction_ids),
        state="pending",
    )


def list_patch_transactions(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    initialize_database(db_path)

    with connect(db_path) as connection:
        try:
            rows = connection.execute(
                """
                SELECT *
                FROM patch_transactions
                ORDER BY created_at DESC, id ASC
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    return [_decode_patch_transaction(row) for row in rows]


def list_harness_target_locks(
    db_path: Path,
    *,
    profile_id: Optional[str] = None,
    locked_only: bool = True,
) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    initialize_database(db_path)

    where = []
    params: list[Any] = []
    if profile_id is not None:
        where.append("profile_id = ?")
        params.append(profile_id)
    if locked_only:
        where.append("human_locked = 1")
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT profile_id, target_path, human_locked, reason, created_at, updated_at
            FROM harness_target_locks
            {where_sql}
            ORDER BY profile_id, target_path
            """,
            params,
        ).fetchall()
    return [_decode_harness_target_lock(row) for row in rows]


def set_harness_target_lock(
    *,
    db_path: Path,
    target_path: str,
    locked: bool,
    profile_id: Optional[str] = None,
    reason: Optional[str] = None,
    actor_agent_identity_id: Optional[str] = None,
) -> HarnessTargetLockReport:
    initialize_database(db_path)
    normalized = _normalize_target_path(target_path)
    with connect(db_path) as connection:
        selected_profile_id = profile_id or _first_profile_id(connection)
        if selected_profile_id is None:
            raise HarnessError("no_profiles_found")
        _ensure_profile_exists(connection, selected_profile_id)
        _ensure_kyoko_source(connection, selected_profile_id)
        clean_actor_agent_identity_id = _validate_actor_agent_identity_id(
            connection,
            selected_profile_id,
            actor_agent_identity_id,
        )
        existing = connection.execute(
            """
            SELECT created_at
            FROM harness_target_locks
            WHERE profile_id = ? AND target_path = ?
            """,
            (selected_profile_id, normalized),
        ).fetchone()
        now = utc_now()
        created_at = str(existing["created_at"]) if existing is not None else now
        clean_reason = reason.strip() if isinstance(reason, str) and reason.strip() else None
        connection.execute(
            """
            INSERT INTO harness_target_locks (
              profile_id,
              target_path,
              human_locked,
              reason,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id, target_path) DO UPDATE SET
              human_locked = excluded.human_locked,
              reason = excluded.reason,
              updated_at = excluded.updated_at
            """,
            (
                selected_profile_id,
                normalized,
                1 if locked else 0,
                clean_reason,
                created_at,
                now,
            ),
        )
    return HarnessTargetLockReport(
        profile_id=selected_profile_id,
        target_path=normalized,
        human_locked=locked,
        reason=clean_reason,
        actor_agent_identity_id=clean_actor_agent_identity_id,
    )


def apply_patch_transaction(
    *,
    db_path: Path,
    patch_transaction_id: str,
    workspace_root: Path,
) -> HarnessPatchApplyReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        patch_transaction = _get_patch_transaction(connection, patch_transaction_id)
        if str(patch_transaction["status"]) != "ready":
            raise HarnessError(f"patch_transaction_state_not_applyable:{patch_transaction['status']}")
        patch_kind = str(patch_transaction["patch_kind"])
        if patch_kind not in {"generated_file", "unified_diff"}:
            raise HarnessError(f"unsupported_patch_apply_kind:{patch_transaction['patch_kind']}")

        proposal = _get_proposal(connection, str(patch_transaction["proposal_id"]))
        profile_id = str(patch_transaction["profile_id"])
        policy = _get_policy(connection, profile_id)
        if policy["harness_mode"] == "off":
            raise HarnessError("harness_policy_off")
        if int(policy["allow_repo_patch"]) != 1:
            raise HarnessError("repo_patch_not_allowed")
        _ensure_kyoko_source(connection, profile_id)

        target_paths = _json_loads(patch_transaction["target_paths_json"], [])
        _validate_target_paths_against_policy(
            target_paths,
            allowed_paths=_json_loads(policy["allowed_paths_json"], []),
            protected_paths=_json_loads(policy["protected_paths_json"], []),
        )
        _ensure_unlocked_harness_target_paths(connection, profile_id, target_paths)
        _check_dirty_worktree(
            workspace_root=workspace_root,
            target_paths=target_paths,
            policy=str(policy["dirty_worktree_policy"]),
        )

        root = workspace_root.resolve()
        change = _change_for_patch_transaction(patch_transaction, proposal)
        if patch_kind == "generated_file":
            files = _generated_files_for_change(change, target_paths)
            preimages = _write_generated_files(root, files)
        else:
            diff_text = _read_diff_ref_blob(connection, patch_transaction["diff_ref"])
            file_patches = _unified_diff_file_patches(diff_text, target_paths)
            preimages = _apply_unified_diff(root, file_patches)

        now = utc_now()
        rollback = {
            "required": True,
            "available": True,
            "workspace_root": str(root),
            "applied_at": now,
            "preimages": preimages,
        }
        connection.execute(
            """
            UPDATE patch_transactions
            SET status = ?,
                rollback_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("applied", _json_dumps(rollback), now, patch_transaction_id),
        )
        _insert_timeline_event(
            connection,
            event_id=f"event_{patch_transaction_id}_applied",
            profile_id=profile_id,
            entity_type="patch_transaction",
            entity_id=patch_transaction_id,
            kind="patch_transaction_applied",
            at=now,
            agent_identity_id=None,
            metadata={"target_paths": target_paths},
        )

    return HarnessPatchApplyReport(
        patch_transaction_id=patch_transaction_id,
        proposal_id=str(patch_transaction["proposal_id"]),
        profile_id=profile_id,
        target_paths=tuple(str(path) for path in target_paths),
        status="applied",
    )


def rollback_patch_transaction(
    *,
    db_path: Path,
    patch_transaction_id: str,
    workspace_root: Path,
) -> HarnessPatchRollbackReport:
    initialize_database(db_path)
    with connect(db_path) as connection:
        patch_transaction = _get_patch_transaction(connection, patch_transaction_id)
        if str(patch_transaction["status"]) != "applied":
            raise HarnessError(f"patch_transaction_state_not_rollbackable:{patch_transaction['status']}")

        profile_id = str(patch_transaction["profile_id"])
        _ensure_kyoko_source(connection, profile_id)
        rollback = _json_loads(patch_transaction["rollback_json"], {})
        if not isinstance(rollback, dict) or rollback.get("available") is not True:
            raise HarnessError("rollback_not_available")

        recorded_root = rollback.get("workspace_root")
        root = workspace_root.resolve()
        if isinstance(recorded_root, str) and Path(recorded_root).resolve() != root:
            raise HarnessError("workspace_root_mismatch")

        preimages = rollback.get("preimages")
        if not isinstance(preimages, list):
            raise HarnessError("rollback_preimages_missing")

        _restore_preimages(root, preimages)
        now = utc_now()
        rollback["rolled_back_at"] = now
        connection.execute(
            """
            UPDATE patch_transactions
            SET status = ?,
                rollback_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            ("rolled_back", _json_dumps(rollback), now, patch_transaction_id),
        )
        connection.execute(
            "UPDATE learning_proposals SET state = ?, updated_at = ? WHERE id = ?",
            ("rolled_back", now, str(patch_transaction["proposal_id"])),
        )
        target_paths = _json_loads(patch_transaction["target_paths_json"], [])
        _insert_timeline_event(
            connection,
            event_id=f"event_{patch_transaction_id}_rolled_back",
            profile_id=profile_id,
            entity_type="patch_transaction",
            entity_id=patch_transaction_id,
            kind="patch_transaction_rolled_back",
            at=now,
            agent_identity_id=None,
            metadata={"target_paths": target_paths},
        )

    return HarnessPatchRollbackReport(
        patch_transaction_id=patch_transaction_id,
        proposal_id=str(patch_transaction["proposal_id"]),
        profile_id=profile_id,
        target_paths=tuple(str(path) for path in target_paths),
        status="rolled_back",
    )


def _validate_prepare_allowed(
    connection: sqlite3.Connection,
    proposal: sqlite3.Row,
) -> list[dict[str, Any]]:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    state = str(proposal["state"])
    section = str(proposal["section"])

    if state not in {"pending"}:
        raise HarnessError(f"proposal_state_not_prepareable:{state}")
    if section != "harness":
        raise HarnessError(f"unsupported_harness_section:{section}")

    policy = _get_policy(connection, profile_id)
    if policy["harness_mode"] == "off":
        raise HarnessError("harness_policy_off")

    changes = _json_loads(proposal["proposed_changes_json"], [])
    if not isinstance(changes, list):
        raise HarnessError("invalid_proposed_changes")

    harness_changes = [
        change for change in changes if isinstance(change, dict) and change.get("type") == "harness_patch"
    ]
    if not harness_changes:
        raise HarnessError("no_harness_patch_changes")

    if _has_patch_transaction_for_proposal(connection, proposal_id):
        raise HarnessError(f"harness_proposal_already_prepared:{proposal_id}")

    allowed_paths = _json_loads(policy["allowed_paths_json"], [])
    protected_paths = _json_loads(policy["protected_paths_json"], [])
    for change in changes:
        if not isinstance(change, dict):
            raise HarnessError("invalid_change")
        change_type = change.get("type")
        if change_type == "skillbook_update":
            raise HarnessError("unsupported_harness_prepare_change:skillbook_update")
        if change_type in {"check_spec", "replay_request", "context_delivery_rule"}:
            continue
        if change_type != "harness_patch":
            raise HarnessError(f"unsupported_harness_prepare_change:{change_type}")
        _validate_harness_patch_change(
            connection,
            change,
            profile_id=profile_id,
            allowed_paths=allowed_paths,
            protected_paths=protected_paths,
        )

    return harness_changes


def _validate_harness_patch_change(
    connection: sqlite3.Connection,
    change: dict[str, Any],
    *,
    profile_id: str,
    allowed_paths: Any,
    protected_paths: Any,
) -> None:
    patch_kind = change.get("patch_kind")
    if patch_kind not in {"unified_diff", "generated_file", "command_plan"}:
        raise HarnessError(f"unsupported_patch_kind:{patch_kind}")
    if change.get("side_effect_mode") in UNSAFE_SIDE_EFFECT_MODES:
        raise HarnessError(f"unsafe_harness_side_effect_mode:{change.get('side_effect_mode')}")
    if change.get("rollback_required") is not True:
        raise HarnessError("rollback_required")

    target_paths = change.get("target_paths")
    if not isinstance(target_paths, list) or not target_paths:
        raise HarnessError("target_paths_required")
    normalized_target_paths = [_normalize_target_path(path) for path in target_paths]
    for normalized in normalized_target_paths:
        if _matches_any(normalized, protected_paths):
            raise HarnessError(f"protected_path:{normalized}")
        if not _matches_any(normalized, allowed_paths):
            raise HarnessError(f"path_not_allowed:{normalized}")
    _ensure_unlocked_harness_target_paths(connection, profile_id, normalized_target_paths)
    if patch_kind == "generated_file":
        _generated_files_for_change(change, normalized_target_paths)
    if patch_kind == "unified_diff" and not isinstance(change.get("diff_ref"), str):
        raise HarnessError("unified_diff_ref_required")


def _create_patch_transactions(
    connection: sqlite3.Connection,
    proposal: sqlite3.Row,
    changes: list[dict[str, Any]],
    now: str,
) -> list[str]:
    proposal_id = str(proposal["id"])
    profile_id = str(proposal["profile_id"])
    patch_transaction_ids: list[str] = []

    for index, change in enumerate(changes, start=1):
        patch_transaction_id = f"patch_{proposal_id}_{index}"
        target_paths = [_normalize_target_path(path) for path in change["target_paths"]]
        rollback = {
            "required": True,
            "available": False,
            "reason": "prepared_only_no_repo_write",
        }
        connection.execute(
            """
            INSERT INTO patch_transactions (
              id,
              profile_id,
              proposal_id,
              status,
              patch_kind,
              target_paths_json,
              diff_ref,
              command_plan_json,
              side_effect_mode,
              rollback_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patch_transaction_id,
                profile_id,
                proposal_id,
                "ready",
                change["patch_kind"],
                _json_dumps(target_paths),
                change.get("diff_ref"),
                _json_dumps(change.get("command_plan", [])),
                change["side_effect_mode"],
                _json_dumps(rollback),
                now,
                now,
            ),
        )
        patch_transaction_ids.append(patch_transaction_id)

    return patch_transaction_ids


def _change_for_patch_transaction(
    patch_transaction: sqlite3.Row,
    proposal: sqlite3.Row,
) -> dict[str, Any]:
    proposal_id = str(patch_transaction["proposal_id"])
    prefix = f"patch_{proposal_id}_"
    patch_transaction_id = str(patch_transaction["id"])
    if not patch_transaction_id.startswith(prefix):
        raise HarnessError(f"patch_transaction_id_mismatch:{patch_transaction_id}")
    try:
        index = int(patch_transaction_id[len(prefix) :])
    except ValueError as exc:
        raise HarnessError(f"patch_transaction_index_invalid:{patch_transaction_id}") from exc

    changes = [
        change
        for change in _json_loads(proposal["proposed_changes_json"], [])
        if isinstance(change, dict) and change.get("type") == "harness_patch"
    ]
    if index < 1 or index > len(changes):
        raise HarnessError(f"patch_transaction_change_not_found:{patch_transaction_id}")
    return changes[index - 1]


def _generated_files_for_change(
    change: dict[str, Any],
    target_paths: list[str],
) -> list[dict[str, str]]:
    files = change.get("files")
    if not isinstance(files, list) or not files:
        raise HarnessError("generated_files_required")

    normalized_targets = {_normalize_target_path(path) for path in target_paths}
    normalized_files: list[dict[str, str]] = []
    for file_payload in files:
        if not isinstance(file_payload, dict):
            raise HarnessError("generated_file_must_be_object")
        path = _normalize_target_path(file_payload.get("path"))
        content = file_payload.get("content")
        if not isinstance(content, str):
            raise HarnessError(f"generated_file_content_required:{path}")
        findings = _scan_generated_file_for_secrets(path, content)
        if findings:
            finding = findings[0]
            raise HarnessError(
                f"secret_scan_failed:{path}:{finding['kind']}:line_{finding['line']}"
            )
        normalized_files.append({"path": path, "content": content})

    file_paths = {file_payload["path"] for file_payload in normalized_files}
    if file_paths != normalized_targets:
        raise HarnessError("generated_file_target_mismatch")
    return normalized_files


def _scan_generated_file_for_secrets(path: str, content: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        assignment_match = SECRET_ASSIGNMENT_PATTERN.search(line)
        if assignment_match:
            value = assignment_match.group(2).strip().strip("\"'")
            if not _is_secret_placeholder(value):
                findings.append(
                    {
                        "path": path,
                        "line": line_number,
                        "kind": f"secret_assignment:{assignment_match.group(1).lower()}",
                    }
                )
        for kind, pattern in SECRET_VALUE_PATTERNS:
            if pattern.search(line):
                findings.append({"path": path, "line": line_number, "kind": kind})
    return findings


def _is_secret_placeholder(value: str) -> bool:
    normalized = value.strip().strip("\"'").lower()
    if normalized in SECRET_PLACEHOLDERS:
        return True
    if normalized.startswith("${") and normalized.endswith("}"):
        return True
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    return False


def _read_diff_ref_blob(connection: sqlite3.Connection, diff_ref: Any) -> str:
    if not isinstance(diff_ref, str) or not diff_ref:
        raise HarnessError("unified_diff_ref_required")
    row = connection.execute(
        "SELECT path FROM payload_blobs WHERE id = ?",
        (diff_ref,),
    ).fetchone()
    if row is None:
        raise HarnessError(f"diff_ref_not_found:{diff_ref}")
    path = Path(str(row["path"]))
    if not path.exists():
        raise HarnessError(f"diff_ref_blob_missing:{diff_ref}")
    try:
        return path.read_text()
    except UnicodeDecodeError as exc:
        raise HarnessError(f"diff_ref_not_utf8:{diff_ref}") from exc


def _unified_diff_file_patches(diff_text: str, target_paths: list[str]) -> list[UnifiedDiffFilePatch]:
    patches = _parse_unified_diff(diff_text)
    normalized_targets = {_normalize_target_path(path) for path in target_paths}
    patch_paths = {patch.path for patch in patches}
    if patch_paths != normalized_targets:
        raise HarnessError("unified_diff_target_mismatch")
    for patch in patches:
        added_lines = [
            content
            for hunk in patch.hunks
            for tag, content in hunk.lines
            if tag == "+"
        ]
        findings = _scan_generated_file_for_secrets(patch.path, "".join(added_lines))
        if findings:
            finding = findings[0]
            raise HarnessError(
                f"secret_scan_failed:{patch.path}:{finding['kind']}:line_{finding['line']}"
            )
    return patches


def _parse_unified_diff(diff_text: str) -> list[UnifiedDiffFilePatch]:
    lines = diff_text.splitlines(keepends=True)
    patches: list[UnifiedDiffFilePatch] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith("--- "):
            index += 1
            continue
        old_path = _diff_header_path(line, "--- ")
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise HarnessError("unified_diff_new_header_required")
        new_path = _diff_header_path(lines[index], "+++ ")
        index += 1
        path = _normalize_diff_path(new_path if new_path != "/dev/null" else old_path)
        hunks: list[UnifiedDiffHunk] = []
        while index < len(lines):
            if lines[index].startswith("--- "):
                break
            if lines[index].startswith("diff "):
                index += 1
                continue
            if not lines[index].startswith("@@ "):
                raise HarnessError("unified_diff_hunk_header_required")
            hunk, index = _parse_unified_diff_hunk(lines, index)
            hunks.append(hunk)
        if not hunks:
            raise HarnessError(f"unified_diff_hunks_required:{path}")
        patches.append(
            UnifiedDiffFilePatch(
                path=path,
                old_path=old_path,
                new_path=new_path,
                hunks=tuple(hunks),
            )
        )
    if not patches:
        raise HarnessError("unified_diff_required")
    return patches


def _diff_header_path(line: str, prefix: str) -> str:
    raw_path = line[len(prefix) :].strip()
    if "\t" in raw_path:
        raw_path = raw_path.split("\t", 1)[0]
    if raw_path.endswith("\n"):
        raw_path = raw_path[:-1]
    return raw_path


def _normalize_diff_path(path: str) -> str:
    if path == "/dev/null":
        raise HarnessError("unified_diff_target_path_missing")
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return _normalize_target_path(path)


def _parse_unified_diff_hunk(
    lines: list[str],
    index: int,
) -> tuple[UnifiedDiffHunk, int]:
    header = lines[index].rstrip("\n")
    match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    if match is None:
        raise HarnessError(f"unified_diff_hunk_header_invalid:{header}")
    old_start = int(match.group(1))
    old_count = int(match.group(2) or "1")
    new_start = int(match.group(3))
    new_count = int(match.group(4) or "1")
    index += 1
    hunk_lines: list[tuple[str, str]] = []
    while index < len(lines):
        line = lines[index]
        if line.startswith("@@ ") or line.startswith("--- "):
            break
        if line.startswith("\\"):
            raise HarnessError("unified_diff_no_newline_marker_not_supported")
        if not line:
            raise HarnessError("unified_diff_empty_line_invalid")
        tag = line[0]
        if tag not in {" ", "+", "-"}:
            raise HarnessError(f"unified_diff_line_invalid:{tag}")
        hunk_lines.append((tag, line[1:]))
        index += 1
    consumed_old = sum(1 for tag, _content in hunk_lines if tag in {" ", "-"})
    produced_new = sum(1 for tag, _content in hunk_lines if tag in {" ", "+"})
    if consumed_old != old_count or produced_new != new_count:
        raise HarnessError("unified_diff_hunk_count_mismatch")
    return (
        UnifiedDiffHunk(
            old_start=old_start,
            old_count=old_count,
            new_start=new_start,
            new_count=new_count,
            lines=tuple(hunk_lines),
        ),
        index,
    )


def _apply_unified_diff(root: Path, patches: list[UnifiedDiffFilePatch]) -> list[dict[str, Any]]:
    preimages: list[dict[str, Any]] = []
    planned_writes: list[tuple[Path, UnifiedDiffFilePatch, str]] = []
    planned_deletes: list[tuple[Path, UnifiedDiffFilePatch]] = []
    for patch in patches:
        file_path = _resolve_under_root(root, patch.path)
        if file_path.exists() and file_path.is_dir():
            raise HarnessError(f"target_path_is_directory:{patch.path}")
        source_lines = file_path.read_text().splitlines(keepends=True) if file_path.exists() else []
        patched_lines = _apply_unified_diff_hunks(source_lines, patch)
        preimages.append(
            {
                "path": patch.path,
                "existed": file_path.exists(),
                "content": file_path.read_text() if file_path.exists() else None,
            }
        )
        if patch.new_path == "/dev/null":
            if patched_lines:
                raise HarnessError(f"unified_diff_delete_not_empty:{patch.path}")
            planned_deletes.append((file_path, patch))
        else:
            planned_writes.append((file_path, patch, "".join(patched_lines)))

    for file_path, _patch, content in planned_writes:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
    for file_path, patch in planned_deletes:
        if file_path.exists():
            if file_path.is_dir():
                raise HarnessError(f"target_path_is_directory:{patch.path}")
            file_path.unlink()
    return preimages


def _apply_unified_diff_hunks(
    source_lines: list[str],
    patch: UnifiedDiffFilePatch,
) -> list[str]:
    output: list[str] = []
    source_index = 0
    for hunk in patch.hunks:
        hunk_old_index = max(hunk.old_start - 1, 0)
        if hunk_old_index < source_index:
            raise HarnessError(f"unified_diff_overlapping_hunks:{patch.path}")
        output.extend(source_lines[source_index:hunk_old_index])
        source_index = hunk_old_index
        for tag, content in hunk.lines:
            if tag == "+":
                output.append(content)
                continue
            if source_index >= len(source_lines):
                raise HarnessError(f"unified_diff_context_missing:{patch.path}")
            if source_lines[source_index] != content:
                raise HarnessError(f"unified_diff_context_mismatch:{patch.path}")
            if tag == " ":
                output.append(content)
            source_index += 1
    output.extend(source_lines[source_index:])
    return output


def _validate_target_paths_against_policy(
    target_paths: Any,
    *,
    allowed_paths: Any,
    protected_paths: Any,
) -> None:
    if not isinstance(target_paths, list) or not target_paths:
        raise HarnessError("target_paths_required")
    for raw_path in target_paths:
        normalized = _normalize_target_path(raw_path)
        if _matches_any(normalized, protected_paths):
            raise HarnessError(f"protected_path:{normalized}")
        if not _matches_any(normalized, allowed_paths):
            raise HarnessError(f"path_not_allowed:{normalized}")


def _check_dirty_worktree(
    *,
    workspace_root: Path,
    target_paths: list[str],
    policy: str,
) -> None:
    if policy == "allow":
        return
    root = workspace_root.resolve()
    if not (root / ".git").exists():
        return
    git_args = ["git", "-C", str(root), "status", "--porcelain"]
    if policy == "allow_touched_only":
        git_args.extend(["--", *target_paths])
    try:
        completed = subprocess.run(
            git_args,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise HarnessError("git_required_for_dirty_worktree_check") from exc
    if completed.returncode != 0:
        raise HarnessError(f"git_status_failed:{completed.returncode}")
    if completed.stdout.strip():
        if policy == "allow_touched_only":
            raise HarnessError("dirty_target_paths_block_harness_apply")
        raise HarnessError("dirty_worktree_blocks_harness_apply")


def _write_generated_files(root: Path, files: list[dict[str, str]]) -> list[dict[str, Any]]:
    preimages: list[dict[str, Any]] = []
    planned_writes: list[tuple[Path, dict[str, str]]] = []
    for file_payload in files:
        file_path = _resolve_under_root(root, file_payload["path"])
        if file_path.exists() and file_path.is_dir():
            raise HarnessError(f"target_path_is_directory:{file_payload['path']}")
        preimages.append(
            {
                "path": file_payload["path"],
                "existed": file_path.exists(),
                "content": file_path.read_text() if file_path.exists() else None,
            }
        )
        planned_writes.append((file_path, file_payload))

    for file_path, file_payload in planned_writes:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(file_payload["content"])

    return preimages


def _restore_preimages(root: Path, preimages: list[Any]) -> None:
    for preimage in reversed(preimages):
        if not isinstance(preimage, dict):
            raise HarnessError("invalid_rollback_preimage")
        path = _normalize_target_path(preimage.get("path"))
        file_path = _resolve_under_root(root, path)
        if preimage.get("existed") is True:
            content = preimage.get("content")
            if not isinstance(content, str):
                raise HarnessError(f"rollback_content_missing:{path}")
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
        else:
            if file_path.exists():
                if file_path.is_dir():
                    raise HarnessError(f"rollback_target_is_directory:{path}")
                file_path.unlink()


def _resolve_under_root(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    resolved_path = (resolved_root / relative_path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise HarnessError(f"path_escapes_workspace:{relative_path}") from exc
    return resolved_path


def _normalize_target_path(raw_path: Any) -> str:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise HarnessError("invalid_target_path")
    path = raw_path.replace("\\", "/").strip()
    if path.startswith("/"):
        raise HarnessError(f"absolute_path:{path}")
    normalized = posixpath.normpath(path)
    if normalized in {"", "."} or normalized.startswith("../") or normalized == "..":
        raise HarnessError(f"path_traversal:{path}")
    return normalized


def _matches_any(path: str, patterns: Any) -> bool:
    if not isinstance(patterns, list):
        return False
    for pattern in patterns:
        if isinstance(pattern, str) and fnmatch.fnmatchcase(path, pattern):
            return True
    return False


def _ensure_unlocked_harness_target_paths(
    connection: sqlite3.Connection,
    profile_id: str,
    target_paths: Any,
) -> None:
    locked_paths = _locked_harness_target_paths(connection, profile_id)
    if not locked_paths:
        return
    for raw_path in target_paths:
        normalized = _normalize_target_path(raw_path)
        if normalized in locked_paths:
            raise HarnessError(f"human_locked_harness_target:{normalized}")


def _locked_harness_target_paths(connection: sqlite3.Connection, profile_id: str) -> set[str]:
    try:
        rows = connection.execute(
            """
            SELECT target_path
            FROM harness_target_locks
            WHERE profile_id = ?
              AND human_locked = 1
            """,
            (profile_id,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise StorageError("harness_target_locks table is missing") from exc
    return {str(row["target_path"]) for row in rows}


def _first_profile_id(connection: sqlite3.Connection) -> Optional[str]:
    row = connection.execute("SELECT id FROM profiles ORDER BY created_at, id LIMIT 1").fetchone()
    return str(row["id"]) if row is not None else None


def _ensure_profile_exists(connection: sqlite3.Connection, profile_id: str) -> None:
    row = connection.execute("SELECT 1 FROM profiles WHERE id = ? LIMIT 1", (profile_id,)).fetchone()
    if row is None:
        raise HarnessError(f"profile_not_found:{profile_id}")


def _get_proposal(connection: sqlite3.Connection, proposal_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM learning_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("learning_proposals table is missing") from exc
    if row is None:
        raise HarnessError(f"proposal_not_found:{proposal_id}")
    return row


def _get_patch_transaction(connection: sqlite3.Connection, patch_transaction_id: str) -> sqlite3.Row:
    try:
        row = connection.execute(
            "SELECT * FROM patch_transactions WHERE id = ?",
            (patch_transaction_id,),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageError("patch_transactions table is missing") from exc
    if row is None:
        raise HarnessError(f"patch_transaction_not_found:{patch_transaction_id}")
    return row


def _get_policy(connection: sqlite3.Connection, profile_id: str) -> sqlite3.Row:
    row = connection.execute(
        "SELECT * FROM autonomy_policies WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise HarnessError(f"autonomy_policy_not_found:{profile_id}")
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
        raise HarnessError(f"actor_agent_identity_not_found:{clean_actor_agent_identity_id}")
    return clean_actor_agent_identity_id


def _has_patch_transaction_for_proposal(connection: sqlite3.Connection, proposal_id: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM patch_transactions WHERE proposal_id = ? LIMIT 1",
        (proposal_id,),
    ).fetchone()
    return row is not None


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
            _json_dumps({"harness_prepare": True}),
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


def _decode_patch_transaction(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["target_paths"] = _json_loads(payload.pop("target_paths_json"), [])
    payload["command_plan"] = _json_loads(payload.pop("command_plan_json"), [])
    payload["rollback"] = _json_loads(payload.pop("rollback_json"), {})
    return payload


def _decode_harness_target_lock(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["human_locked"] = bool(payload["human_locked"])
    return payload


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
