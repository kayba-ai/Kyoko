"""Install the bundled `/kyoko-instrument` coding-agent skill.

The skill is a Markdown playbook a coding agent (Claude Code, Cursor, Codex,
...) follows to wire a repo's telemetry into Kyoko. It ships inside the package
so a `pipx install kyoko` user can drop it into their agent without cloning the
repo.

Claude Code discovers skills under `.claude/skills/<name>/SKILL.md` (project) or
`~/.claude/skills/<name>/SKILL.md` (global), so that is what we write by
default. For other agents, `--print` emits the playbook to stdout so it can be
pasted in directly.
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
    output_path: Path
    written: bool

    def to_json(self) -> dict[str, object]:
        return {
            "skill_name": self.skill_name,
            "output_path": str(self.output_path),
            "written": self.written,
            "invoke": f"/{self.skill_name}",
        }


def load_skill_text() -> str:
    try:
        return read_bundled_text(BUNDLED_SKILL_PATH)
    except AssetError as exc:
        raise SkillInstallError(str(exc)) from exc


def skill_destination(*, project_dir: Path, global_install: bool) -> Path:
    base = Path.home() if global_install else project_dir
    return base / ".claude" / "skills" / SKILL_NAME / "SKILL.md"


def install_skill(
    *,
    project_dir: Path,
    global_install: bool = False,
    force: bool = False,
) -> SkillInstallReport:
    text = load_skill_text()
    output_path = skill_destination(project_dir=project_dir, global_install=global_install)
    if output_path.exists() and not force:
        raise SkillInstallError(f"skill_exists:{output_path}")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text, encoding="utf-8")
    except OSError as exc:
        raise SkillInstallError(str(exc)) from exc
    return SkillInstallReport(skill_name=SKILL_NAME, output_path=output_path, written=True)
