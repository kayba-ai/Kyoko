from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from .hermes_import import HermesImportError, HermesKanbanImportReport, ingest_hermes_kanban_db
from .openclaw_import import OpenClawImportError, OpenClawSessionImportReport, ingest_openclaw_sessions


class SourceDiscoveryError(Exception):
    """Raised when a discovered source cannot be resolved or imported."""


@dataclass(frozen=True)
class SourceDiscoveryReport:
    db_path: Path
    home: Path
    candidates: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "home": str(self.home),
            "candidates": list(self.candidates),
        }


@dataclass(frozen=True)
class DiscoveredSourceImportReport:
    db_path: Path
    candidate: dict[str, Any]
    import_report: Union[HermesKanbanImportReport, OpenClawSessionImportReport]

    def to_json(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "candidate": self.candidate,
            "import": self.import_report.to_json(),
        }


def discover_local_sources(
    *,
    db_path: Path,
    home: Optional[Path] = None,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    include_missing: bool = False,
) -> SourceDiscoveryReport:
    selected_home = (home.expanduser() if home is not None else Path.home()).resolve()
    candidates: list[dict[str, Any]] = []
    candidates.extend(
        _discover_hermes(
            db_path=db_path,
            home=selected_home,
            profile_id=profile_id,
            profile_name=profile_name,
            root_path=root_path,
            include_missing=include_missing,
        )
    )
    candidates.extend(
        _discover_openclaw(
            db_path=db_path,
            home=selected_home,
            profile_id=profile_id,
            profile_name=profile_name,
            root_path=root_path,
            include_missing=include_missing,
        )
    )
    candidates.sort(key=lambda row: (row["kind"], row["id"]))
    return SourceDiscoveryReport(db_path=db_path, home=selected_home, candidates=tuple(candidates))


def import_discovered_source(
    *,
    db_path: Path,
    candidate_id: str,
    home: Optional[Path] = None,
    profile_id: Optional[str] = None,
    profile_name: Optional[str] = None,
    root_path: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> DiscoveredSourceImportReport:
    if not candidate_id:
        raise SourceDiscoveryError("candidate_id_required")
    report = discover_local_sources(
        db_path=db_path,
        home=home,
        profile_id=profile_id,
        profile_name=profile_name,
        root_path=root_path,
        include_missing=False,
    )
    candidates = {candidate["id"]: candidate for candidate in report.candidates}
    candidate = candidates.get(candidate_id)
    if candidate is None:
        raise SourceDiscoveryError(f"source_candidate_not_found:{candidate_id}")
    if candidate.get("status") != "ready":
        raise SourceDiscoveryError(f"source_candidate_not_ready:{candidate_id}:{candidate.get('status')}")

    kind = candidate.get("kind")
    try:
        if kind == "hermes_kanban":
            imported = ingest_hermes_kanban_db(
                db_path=db_path,
                kanban_db_path=Path(str(candidate["path"])).expanduser(),
                profile_id=profile_id,
                profile_name=profile_name,
                root_path=root_path,
                board=str(candidate.get("metadata", {}).get("board") or "default"),
                output_path=_output_path(output_dir, candidate_id),
            )
        elif kind == "openclaw_sessions":
            imported = ingest_openclaw_sessions(
                db_path=db_path,
                source_path=Path(str(candidate["path"])).expanduser(),
                profile_id=profile_id,
                profile_name=profile_name,
                root_path=root_path,
                agent_id=str(candidate.get("metadata", {}).get("agent_id") or "main"),
                output_path=_output_path(output_dir, candidate_id),
            )
        else:
            raise SourceDiscoveryError(f"unsupported_source_candidate_kind:{kind}")
    except (HermesImportError, OpenClawImportError) as exc:
        raise SourceDiscoveryError(str(exc)) from exc
    return DiscoveredSourceImportReport(db_path=db_path, candidate=candidate, import_report=imported)


def _discover_hermes(
    *,
    db_path: Path,
    home: Path,
    profile_id: Optional[str],
    profile_name: Optional[str],
    root_path: Optional[Path],
    include_missing: bool,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[Path] = set()
    default_db = home / ".hermes" / "kanban.db"
    board_dbs: list[tuple[str, Path]] = [("default", default_db)]
    boards_root = home / ".hermes" / "kanban" / "boards"
    if boards_root.exists():
        for path in sorted(boards_root.glob("*/kanban.db")):
            board_dbs.append((path.parent.name, path))

    for board, path in board_dbs:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        exists = path.exists()
        if not exists and not include_missing:
            continue
        candidates.append(
            {
                "id": f"hermes_{_slug(board)}",
                "kind": "hermes_kanban",
                "label": f"Hermes Kanban ({board})",
                "path": str(path),
                "exists": exists,
                "status": "ready" if exists else "missing",
                "import_command": _hermes_import_command(
                    db_path=db_path,
                    kanban_db_path=path,
                    board=board,
                    profile_id=profile_id,
                    profile_name=profile_name,
                    root_path=root_path,
                ),
                "metadata": {
                    "board": board,
                    "default_path": path == default_db,
                },
            }
        )
    return candidates


def _discover_openclaw(
    *,
    db_path: Path,
    home: Path,
    profile_id: Optional[str],
    profile_name: Optional[str],
    root_path: Optional[Path],
    include_missing: bool,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[Path] = set()
    agents_root = home / ".openclaw" / "agents"
    session_dirs: list[tuple[str, Path]] = []
    if agents_root.exists():
        for path in sorted(agents_root.glob("*/sessions")):
            if path.is_dir():
                session_dirs.append((path.parent.name, path))
    legacy_sessions = home / ".openclaw" / "sessions"
    if legacy_sessions.exists():
        session_dirs.append(("main", legacy_sessions))
    if include_missing and not session_dirs:
        session_dirs.append(("main", agents_root / "main" / "sessions"))

    for agent_id, path in session_dirs:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        store_path = path / "sessions.json"
        session_count = _session_store_count(store_path)
        transcript_count = _jsonl_count(path)
        exists = path.exists()
        if exists:
            status = "ready" if session_count or transcript_count else "empty"
        else:
            status = "missing"
        if status == "missing" and not include_missing:
            continue
        candidates.append(
            {
                "id": f"openclaw_{_slug(agent_id)}",
                "kind": "openclaw_sessions",
                "label": f"OpenClaw sessions ({agent_id})",
                "path": str(path),
                "exists": exists,
                "status": status,
                "import_command": _openclaw_import_command(
                    db_path=db_path,
                    session_path=path,
                    agent_id=agent_id,
                    profile_id=profile_id,
                    profile_name=profile_name,
                    root_path=root_path,
                ),
                "metadata": {
                    "agent_id": agent_id,
                    "sessions_json": str(store_path),
                    "session_count": session_count,
                    "transcript_count": transcript_count,
                },
            }
        )
    return candidates


def _hermes_import_command(
    *,
    db_path: Path,
    kanban_db_path: Path,
    board: str,
    profile_id: Optional[str],
    profile_name: Optional[str],
    root_path: Optional[Path],
) -> str:
    parts = [
        "python3",
        "-m",
        "kyoko",
        "import-hermes-kanban",
        "--db",
        str(db_path),
        str(kanban_db_path),
        "--board",
        board,
    ]
    _append_optional_profile_args(parts, profile_id=profile_id, profile_name=profile_name, root_path=root_path)
    parts.append("--json")
    return _shell_join(parts)


def _openclaw_import_command(
    *,
    db_path: Path,
    session_path: Path,
    agent_id: str,
    profile_id: Optional[str],
    profile_name: Optional[str],
    root_path: Optional[Path],
) -> str:
    parts = [
        "python3",
        "-m",
        "kyoko",
        "import-openclaw-sessions",
        "--db",
        str(db_path),
        str(session_path),
        "--agent-id",
        agent_id,
    ]
    _append_optional_profile_args(parts, profile_id=profile_id, profile_name=profile_name, root_path=root_path)
    parts.append("--json")
    return _shell_join(parts)


def _append_optional_profile_args(
    parts: list[str],
    *,
    profile_id: Optional[str],
    profile_name: Optional[str],
    root_path: Optional[Path],
) -> None:
    if profile_id:
        parts.extend(["--profile-id", profile_id])
    if profile_name:
        parts.extend(["--profile-name", profile_name])
    if root_path is not None:
        parts.extend(["--root-path", str(root_path)])


def _session_store_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    sessions = payload.get("sessions") if isinstance(payload.get("sessions"), dict) else payload
    return len(sessions) if isinstance(sessions, dict) else 0


def _jsonl_count(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return len([item for item in path.glob("*.jsonl") if not item.name.endswith(".trajectory-path.jsonl")])


def _shell_join(parts: list[str]) -> str:
    return shlex.join(parts)


def _output_path(output_dir: Optional[Path], candidate_id: str) -> Optional[Path]:
    if output_dir is None:
        return None
    return output_dir / f"{_slug(candidate_id)}-source-events.json"


def _slug(value: str) -> str:
    text = str(value or "unknown").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"
