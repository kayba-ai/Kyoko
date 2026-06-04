from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .ace_bridge import AceNativeRunReport, run_native_ace_command
from .bundled_assets import bundled_asset_path
from .storage import ingest_source_fixture


FIXTURE_PROFILE_ID = "profile_news_research_001"
FIXTURE_SPAN_ID = "span_fetch_timeout_001"


@dataclass(frozen=True)
class AceLegacyOfflineSmokeReport:
    db_path: Path
    output_dir: Path
    source_fixture_path: Path
    command_path: Path
    native_run: AceNativeRunReport

    def to_json(self, *, include_proposals: bool = True) -> dict[str, Any]:
        native_payload = self.native_run.to_json(include_proposals=include_proposals)
        diff = native_payload.get("diff") if isinstance(native_payload.get("diff"), dict) else {}
        proposal_ids = diff.get("proposal_ids") if isinstance(diff.get("proposal_ids"), list) else []
        unsupported_changes = (
            diff.get("unsupported_changes") if isinstance(diff.get("unsupported_changes"), list) else []
        )
        passed = (
            bool(native_payload.get("passed"))
            and bool(proposal_ids)
            and not unsupported_changes
        )
        return {
            "kind": "legacy_ace_offline_adapter_smoke",
            "db_path": str(self.db_path),
            "output_dir": str(self.output_dir),
            "source_fixture_path": str(self.source_fixture_path),
            "command_path": str(self.command_path),
            "profile_id": self.native_run.profile_id,
            "passed": passed,
            "external_command_invoked": True,
            "installed_ace_package_invoked": True,
            "provider_backed": False,
            "live_operator_invoked": False,
            "external_model_invoked": False,
            "native_run": native_payload,
        }


def run_legacy_ace_offline_adapter_smoke(
    *,
    db_path: Path,
    output_dir: Optional[Path] = None,
    persist: bool = False,
    schema_path: Optional[Path] = None,
    timeout_seconds: int = 60,
) -> AceLegacyOfflineSmokeReport:
    source_fixture_path = bundled_asset_path("source-events/hermes-news-research-minimal.json")
    ingest_source_fixture(db_path, source_fixture_path)
    command_path = Path(__file__).with_name("ace_legacy_smoke_command.py")
    native_run = run_native_ace_command(
        db_path=db_path,
        command=[sys.executable, str(command_path)],
        profile_id=FIXTURE_PROFILE_ID,
        output_dir=output_dir,
        persist=persist,
        schema_path=schema_path,
        producer_name="legacy_ace_offline_adapter",
        evidence_refs=[
            {
                "entity_type": "span",
                "entity_id": FIXTURE_SPAN_ID,
                "role": "failure",
            }
        ],
        timeout_seconds=timeout_seconds,
    )
    return AceLegacyOfflineSmokeReport(
        db_path=db_path,
        output_dir=native_run.output_dir,
        source_fixture_path=source_fixture_path,
        command_path=command_path,
        native_run=native_run,
    )
