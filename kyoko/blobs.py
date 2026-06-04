from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .storage import StorageError, connect, initialize_database, utc_now


DEFAULT_BLOB_RETENTION_DAYS: Optional[int] = None


@dataclass(frozen=True)
class BlobPutReport:
    blob_id: str
    sha256: str
    size_bytes: int
    path: Path
    created: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "blob_id": self.blob_id,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "path": str(self.path),
            "created": self.created,
        }


@dataclass(frozen=True)
class StorageReport:
    db_path: Path
    blob_root: Path
    db_size_bytes: int
    wal_size_bytes: int
    registered_blobs: int
    registered_blob_bytes: int
    missing_blobs: tuple[dict[str, Any], ...]
    orphan_files: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "blob_root": str(self.blob_root),
            "db_size_bytes": self.db_size_bytes,
            "wal_size_bytes": self.wal_size_bytes,
            "registered_blobs": self.registered_blobs,
            "registered_blob_bytes": self.registered_blob_bytes,
            "missing_blobs": list(self.missing_blobs),
            "orphan_files": list(self.orphan_files),
        }


@dataclass(frozen=True)
class PruneReport:
    dry_run: bool
    cutoff: Optional[str]
    pruned_blobs: tuple[dict[str, Any], ...]
    pruned_bytes: int

    def to_json(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "cutoff": self.cutoff,
            "pruned_blobs": list(self.pruned_blobs),
            "pruned_bytes": self.pruned_bytes,
        }


def default_blob_root(db_path: Path) -> Path:
    return db_path.parent / "blobs"


def put_blob(
    *,
    db_path: Path,
    data: bytes,
    kind: str = "payload",
    media_type: str = "application/octet-stream",
    profile_id: Optional[str] = None,
    blob_root: Optional[Path] = None,
    redaction_mode: str = "redacted",
    retained_until: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> BlobPutReport:
    if not kind:
        raise StorageError("blob_kind_required")
    if not media_type:
        raise StorageError("blob_media_type_required")
    initialize_database(db_path)
    if profile_id is not None:
        with connect(db_path) as connection:
            row = connection.execute("SELECT id FROM profiles WHERE id = ?", (profile_id,)).fetchone()
            if row is None:
                raise StorageError(f"profile_not_found:{profile_id}")

    sha256 = hashlib.sha256(data).hexdigest()
    blob_id = f"blob_sha256_{sha256[:32]}"
    root = blob_root or default_blob_root(db_path)
    blob_path = root / sha256[:2] / sha256
    created = not blob_path.exists()
    blob_path.parent.mkdir(parents=True, exist_ok=True)
    if created:
        blob_path.write_bytes(data)

    now = utc_now()
    preview = _preview(data, media_type, redaction_mode=redaction_mode)
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO payload_blobs (
              id,
              profile_id,
              kind,
              media_type,
              sha256,
              size_bytes,
              path,
              preview,
              redaction_mode,
              retained_until,
              metadata_json,
              created_at,
              updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              profile_id = COALESCE(excluded.profile_id, payload_blobs.profile_id),
              kind = excluded.kind,
              media_type = excluded.media_type,
              size_bytes = excluded.size_bytes,
              path = excluded.path,
              preview = excluded.preview,
              redaction_mode = excluded.redaction_mode,
              retained_until = COALESCE(excluded.retained_until, payload_blobs.retained_until),
              metadata_json = excluded.metadata_json,
              updated_at = excluded.updated_at
            """,
            (
                blob_id,
                profile_id,
                kind,
                media_type,
                sha256,
                len(data),
                str(blob_path),
                preview,
                redaction_mode,
                retained_until,
                _json_dumps(metadata or {}),
                now,
                now,
            ),
        )

    return BlobPutReport(
        blob_id=blob_id,
        sha256=sha256,
        size_bytes=len(data),
        path=blob_path,
        created=created,
    )


def put_json_blob(
    *,
    db_path: Path,
    payload: Any,
    kind: str = "payload",
    profile_id: Optional[str] = None,
    blob_root: Optional[Path] = None,
    redaction_mode: str = "redacted",
    retained_until: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> BlobPutReport:
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return put_blob(
        db_path=db_path,
        data=data,
        kind=kind,
        media_type="application/json",
        profile_id=profile_id,
        blob_root=blob_root,
        redaction_mode=redaction_mode,
        retained_until=retained_until,
        metadata=metadata,
    )


def list_payload_blobs(db_path: Path, *, profile_id: Optional[str] = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    query = "SELECT * FROM payload_blobs"
    params: tuple[Any, ...] = ()
    if profile_id is not None:
        query += " WHERE profile_id = ?"
        params = (profile_id,)
    query += " ORDER BY created_at DESC, id ASC"
    with connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [_decode_blob_row(row) for row in rows]


def storage_report(db_path: Path, *, blob_root: Optional[Path] = None) -> StorageReport:
    initialize_database(db_path)
    root = blob_root or default_blob_root(db_path)
    rows = list_payload_blobs(db_path)
    registered_paths = {str(Path(row["path"])) for row in rows}
    missing: list[dict[str, Any]] = []
    registered_bytes = 0
    for row in rows:
        registered_bytes += int(row["size_bytes"])
        path = Path(row["path"])
        if not path.exists():
            missing.append({"blob_id": row["id"], "path": str(path), "size_bytes": row["size_bytes"]})

    orphan_files: list[dict[str, Any]] = []
    if root.exists():
        for path in root.rglob("*"):
            if path.is_file() and str(path) not in registered_paths:
                orphan_files.append({"path": str(path), "size_bytes": path.stat().st_size})

    return StorageReport(
        db_path=db_path,
        blob_root=root,
        db_size_bytes=_file_size(db_path),
        wal_size_bytes=_file_size(Path(f"{db_path}-wal")),
        registered_blobs=len(rows),
        registered_blob_bytes=registered_bytes,
        missing_blobs=tuple(missing),
        orphan_files=tuple(orphan_files),
    )


def prune_payload_blobs(
    db_path: Path,
    *,
    older_than_days: Optional[int] = None,
    profile_id: Optional[str] = None,
    dry_run: bool = True,
    now: Optional[datetime] = None,
) -> PruneReport:
    if older_than_days is not None and older_than_days < 0:
        raise StorageError("older_than_days_must_be_non_negative")
    initialize_database(db_path)
    current_time = now or datetime.now(timezone.utc)
    cutoff_dt = current_time - timedelta(days=older_than_days) if older_than_days is not None else None
    cutoff = _format_utc(cutoff_dt) if cutoff_dt is not None else None

    rows = list_payload_blobs(db_path, profile_id=profile_id)
    eligible: list[dict[str, Any]] = []
    for row in rows:
        reason = _prune_reason(row, current_time=current_time, cutoff_dt=cutoff_dt)
        if reason is not None:
            eligible.append({**row, "reason": reason})

    pruned_bytes = sum(int(row["size_bytes"]) for row in eligible)
    if not dry_run and eligible:
        with connect(db_path) as connection:
            for row in eligible:
                path = Path(row["path"])
                if path.exists():
                    path.unlink()
                connection.execute("DELETE FROM payload_blobs WHERE id = ?", (row["id"],))

    return PruneReport(
        dry_run=dry_run,
        cutoff=cutoff,
        pruned_blobs=tuple(_prune_payload(row) for row in eligible),
        pruned_bytes=pruned_bytes,
    )


def retained_until_for_days(days: Optional[int], *, now: Optional[datetime] = None) -> Optional[str]:
    if days is None:
        return None
    if days < 0:
        raise StorageError("retention_days_must_be_non_negative")
    current_time = now or datetime.now(timezone.utc)
    return _format_utc(current_time + timedelta(days=days))


def _prune_reason(
    row: dict[str, Any],
    *,
    current_time: datetime,
    cutoff_dt: Optional[datetime],
) -> Optional[str]:
    retained_until = row.get("retained_until")
    if isinstance(retained_until, str) and retained_until:
        retained_until_dt = _parse_utc(retained_until)
        if retained_until_dt <= current_time:
            return "expired"
    if cutoff_dt is not None:
        created_at = _parse_utc(str(row["created_at"]))
        if created_at <= cutoff_dt:
            return "older_than_days"
    return None


def _prune_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "blob_id": row["id"],
        "path": row["path"],
        "size_bytes": row["size_bytes"],
        "reason": row["reason"],
    }


def _decode_blob_row(row: Any) -> dict[str, Any]:
    payload = dict(row)
    payload["metadata"] = _json_loads(payload.pop("metadata_json"), {})
    return payload


def _preview(data: bytes, media_type: str, *, redaction_mode: str = "redacted") -> str:
    if redaction_mode != "unredacted":
        return "[REDACTED:blob_preview]"
    if media_type.startswith("text/") or media_type == "application/json":
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return ""
        return text[:500]
    return ""


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _parse_utc(value: str) -> datetime:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise StorageError(f"invalid_utc_datetime:{value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_loads(value: Any, default: Any) -> Any:
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
