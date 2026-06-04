from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .operator_adapters import (
    OperatorAdapterError,
    OperatorAdapterRegisterReport,
    register_operator_adapter,
)


@dataclass(frozen=True)
class OperatorPreset:
    adapter_id: str
    name: str
    operator_kind: str
    command: tuple[str, ...]
    note: str

    def to_json(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "name": self.name,
            "operator_kind": self.operator_kind,
            "command": list(self.command),
            "note": self.note,
        }


@dataclass(frozen=True)
class OperatorBootstrapReport:
    registered: tuple[OperatorAdapterRegisterReport, ...]
    skipped: tuple[dict[str, str], ...]

    def to_json(self) -> dict[str, object]:
        return {
            "registered": [
                {
                    "adapter_id": report.adapter_id,
                    "profile_id": report.profile_id,
                    "name": report.name,
                    "operator_kind": report.operator_kind,
                    "command": list(report.command),
                    "output_dir": report.output_dir,
                    "timeout_seconds": report.timeout_seconds,
                    "enabled": report.enabled,
                }
                for report in self.registered
            ],
            "skipped": list(self.skipped),
        }


OPERATOR_PRESETS: dict[str, OperatorPreset] = {
    "codex": OperatorPreset(
        adapter_id="codex",
        name="Codex",
        operator_kind="codex",
        command=(
            "codex",
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--color",
            "never",
            "-",
        ),
        note="Uses local Codex auth/subscription, reads the Kyoko prompt from stdin, and runs in read-only mode.",
    ),
    "claude": OperatorPreset(
        adapter_id="claude",
        name="Claude Code",
        operator_kind="claude",
        command=(
            "claude",
            "--print",
            "--input-format",
            "text",
            "--output-format",
            "text",
            "--permission-mode",
            "dontAsk",
            "--allowedTools",
            "Read",
            "--no-session-persistence",
        ),
        note="Uses local Claude Code auth/subscription, reads the Kyoko prompt from stdin, and only allows the Read tool.",
    ),
    "hermes": OperatorPreset(
        adapter_id="hermes",
        name="Hermes",
        operator_kind="hermes",
        command=(
            "hermes",
            "-z",
            "{prompt}",
        ),
        note="Uses local Hermes auth/subscription and passes the inline Kyoko prompt through one-shot mode.",
    ),
    "openclaw": OperatorPreset(
        adapter_id="openclaw",
        name="OpenClaw",
        operator_kind="openclaw",
        command=(
            "openclaw",
            "agent",
            "--agent",
            "main",
            "--local",
            "--message",
            "{prompt}",
            "--timeout",
            "120",
        ),
        note="Uses local OpenClaw mode with the main agent and passes the inline Kyoko prompt as the message.",
    ),
}


def list_operator_presets() -> list[dict[str, object]]:
    return [preset.to_json() for preset in OPERATOR_PRESETS.values()]


def operator_preset_choices() -> tuple[str, ...]:
    return ("all", *OPERATOR_PRESETS.keys())


def bootstrap_operator_adapters(
    *,
    db_path: Path,
    target: str = "all",
    profile_id: Optional[str] = None,
    output_dir: Optional[Path] = None,
    timeout_seconds: int = 120,
    enabled: bool = True,
) -> OperatorBootstrapReport:
    if target != "all" and target not in OPERATOR_PRESETS:
        raise OperatorAdapterError(f"unsupported_operator_preset:{target}")

    targets = tuple(OPERATOR_PRESETS) if target == "all" else (target,)
    registered: list[OperatorAdapterRegisterReport] = []
    skipped: list[dict[str, str]] = []

    for selected in targets:
        preset = OPERATOR_PRESETS[selected]
        executable = shutil.which(preset.command[0])
        if not executable:
            detail = {
                "adapter_id": preset.adapter_id,
                "command": preset.command[0],
                "reason": "command_not_found",
            }
            if target == "all":
                skipped.append(detail)
                continue
            raise OperatorAdapterError(f"operator_preset_command_not_found:{preset.command[0]}")

        report = register_operator_adapter(
            db_path=db_path,
            adapter_id=preset.adapter_id,
            name=preset.name,
            operator_kind=preset.operator_kind,
            command=preset.command,
            profile_id=profile_id,
            output_dir=output_dir,
            timeout_seconds=timeout_seconds,
            enabled=enabled,
            metadata={
                "preset": True,
                "executable": executable,
                "note": preset.note,
            },
        )
        registered.append(report)

    return OperatorBootstrapReport(registered=tuple(registered), skipped=tuple(skipped))
