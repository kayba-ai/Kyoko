"""Install the bundled `/kyoko-instrument` coding-agent skill.

The skill is a Markdown playbook a coding agent (Claude Code, Cursor, Codex,
...) follows to wire a repo's telemetry into Kyoko. It ships inside the package
so a `pipx install kyoko` user can drop it into their agent without cloning the
repo.

Each agent discovers skills under its own root, so we write one copy per root:
Claude Code reads `.claude/skills/<name>/SKILL.md` (project) or
`~/.claude/skills/<name>/SKILL.md` (global); Codex reads `.agents/skills/`
(project) or `~/.codex/skills/` (global). For agents without a skills
directory, `--print` emits the playbook to stdout so it can be pasted in
directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .bundled_assets import AssetError, read_bundled_text

SKILL_NAME = "kyoko-instrument"
BUNDLED_SKILL_PATH = f"skills/{SKILL_NAME}/SKILL.md"


class SkillInstallError(Exception):
    """Raised when the bundled skill cannot be read or written."""


@dataclass
class SkillInstallReport:
    skill_name: str
    output_paths: list[Path]
    written: bool

    def to_json(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "output_path": str(self.output_paths[0]),
            "output_paths": [str(path) for path in self.output_paths],
            "written": self.written,
            "invoke": f"/{self.skill_name}",
        }


def load_skill_text() -> str:
    try:
        return read_bundled_text(BUNDLED_SKILL_PATH)
    except AssetError as exc:
        raise SkillInstallError(str(exc)) from exc


def skill_destinations(*, project_dir: Path, global_install: bool) -> list[Path]:
    relative = Path("skills") / SKILL_NAME / "SKILL.md"
    if global_install:
        return [Path.home() / ".claude" / relative, Path.home() / ".codex" / relative]
    return [project_dir / ".claude" / relative, project_dir / ".agents" / relative]


def install_skill(
    *,
    project_dir: Path,
    global_install: bool = False,
    force: bool = False,
) -> SkillInstallReport:
    text = load_skill_text()
    output_paths = skill_destinations(project_dir=project_dir, global_install=global_install)
    if not force:
        for output_path in output_paths:
            if output_path.exists():
                raise SkillInstallError(f"skill_exists:{output_path}")
    try:
        for output_path in output_paths:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise SkillInstallError(str(exc)) from exc
    return SkillInstallReport(skill_name=SKILL_NAME, output_paths=output_paths, written=True)
