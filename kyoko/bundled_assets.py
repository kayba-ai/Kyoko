from __future__ import annotations

import json
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any


class AssetError(Exception):
    """Raised when a bundled Kyoko asset cannot be loaded."""


def bundled_asset_path(relative_path: str) -> Path:
    return Path(__file__).resolve().parent / "assets" / relative_path


def load_bundled_json(relative_path: str) -> dict[str, Any]:
    package_root = resources.files("kyoko.assets")
    try:
        raw = (package_root / relative_path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AssetError(f"bundled_asset_not_found:{relative_path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssetError(f"bundled_asset_invalid_json:{relative_path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise AssetError(f"bundled_asset_json_object_required:{relative_path}")
    return payload


def bundled_asset_exists(relative_path: str) -> bool:
    return (resources.files("kyoko.assets") / relative_path).is_file()


def list_bundled_assets() -> tuple[str, ...]:
    package_root = resources.files("kyoko.assets")
    assets: list[str] = []

    def walk(node: Any, prefix: str = "") -> None:
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            child_path = f"{prefix}/{child.name}" if prefix else child.name
            if child.is_dir():
                walk(child, child_path)
            elif child.is_file() and child.name.endswith(".json"):
                assets.append(child_path)

    walk(package_root)
    return tuple(assets)


def read_bundled_asset_text(relative_path: str) -> str:
    selected = _require_known_asset(relative_path)
    return (resources.files("kyoko.assets") / selected).read_text(encoding="utf-8")


def export_bundled_asset(*, relative_path: str, output_path: Path) -> Path:
    selected = _require_known_asset(relative_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(read_bundled_asset_text(selected), encoding="utf-8")
    return output_path


def export_bundled_assets(*, output_dir: Path) -> tuple[dict[str, str], ...]:
    exported: list[dict[str, str]] = []
    for relative_path in list_bundled_assets():
        output_path = output_dir / relative_path
        export_bundled_asset(relative_path=relative_path, output_path=output_path)
        exported.append({"asset": relative_path, "output_path": str(output_path)})
    return tuple(exported)


def _require_known_asset(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise AssetError(f"bundled_asset_invalid_path:{relative_path}")
    normalized = path.as_posix()
    if normalized not in list_bundled_assets():
        raise AssetError(f"bundled_asset_not_found:{relative_path}")
    return normalized
