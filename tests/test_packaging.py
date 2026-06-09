import configparser
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import zipfile

import kyoko.release_smoke as release_smoke
from kyoko.release_smoke import (
    ReleaseInstallSmokeReport,
    ReleaseSmokeError,
    run_release_install_smoke,
    run_release_install_smoke_matrix,
)


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def _copy_build_source(self, destination: Path) -> Path:
        source = destination / "source"
        source.mkdir()
        for filename in ("LICENSE", "MANIFEST.in", "README.md", "pyproject.toml", "setup.cfg", "setup.py"):
            shutil.copy2(ROOT / filename, source / filename)
        for dirname in ("kyoko", "docs", "examples", "scripts", "tests"):
            shutil.copytree(
                ROOT / dirname,
                source / dirname,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", "*.pyo", "*.egg-info"
                ),
            )
        return source

    def test_setup_cfg_exposes_runtime_package_contract(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(ROOT / "setup.cfg")
        manifest = (ROOT / "MANIFEST.in").read_text()

        self.assertEqual(parser["metadata"]["name"], "kyoko")
        self.assertEqual(parser["metadata"]["license"], "Apache-2.0")
        self.assertEqual(parser["metadata"]["license_files"], "LICENSE")
        self.assertEqual(parser["options"]["python_requires"], ">=3.12")
        self.assertIn("jsonschema>=4.0", parser["options"]["install_requires"])
        self.assertIn("ace-framework>=0.12.0", parser["options.extras_require"]["ace"])
        self.assertIn("kyoko*", parser["options.packages.find"]["include"])
        self.assertIn("assets/**/*.json", parser["options.package_data"]["kyoko"])
        self.assertIn(
            "kyoko = kyoko.cli:main",
            parser["options.entry_points"]["console_scripts"],
        )
        self.assertIn("recursive-include kyoko/assets *.json", manifest)
        self.assertIn("recursive-include docs *.md *.json *.sql", manifest)
        self.assertIn("recursive-include examples *.mjs *.py", manifest)
        self.assertIn("recursive-include scripts *.py", manifest)
        self.assertIn("recursive-include tests *.py", manifest)
        self.assertIn("global-exclude __pycache__ *.py[cod] .DS_Store", manifest)

    def test_pyproject_uses_legacy_compatible_setuptools_floor(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text()

        self.assertIn('requires = ["setuptools>=58", "wheel>=0.37"]', pyproject)
        self.assertIn('build-backend = "setuptools.build_meta"', pyproject)

    def test_ci_workflow_runs_local_release_gates(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

        self.assertIn('python-version: "3.12"', workflow)
        self.assertIn("python scripts/validate_gate_artifacts.py", workflow)
        self.assertIn("python -m unittest discover -s tests", workflow)
        self.assertIn("python -m kyoko doctor --safe-smokes --json", workflow)
        self.assertIn(
            "python -m kyoko release-smoke --artifact both --install-deps --json",
            workflow,
        )

    def test_built_wheel_includes_cli_entry_point_and_assets(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)
            source = self._copy_build_source(tmpdir)
            wheel_dir = tmpdir / "wheel"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    str(source),
                    "--no-deps",
                    "--no-build-isolation",
                    "--wheel-dir",
                    str(wheel_dir),
                ],
                cwd=source,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
            )

            wheels = list(wheel_dir.glob("kyoko-*.whl"))
            self.assertEqual(len(wheels), 1, result.stdout)
            with zipfile.ZipFile(wheels[0]) as archive:
                names = set(archive.namelist())
                entry_point_files = [
                    name for name in names if name.endswith(".dist-info/entry_points.txt")
                ]
                license_files = [
                    name
                    for name in names
                    if name.endswith(".dist-info/LICENSE")
                    or name.endswith(".dist-info/licenses/LICENSE")
                ]
                self.assertEqual(len(entry_point_files), 1, sorted(entry_point_files))
                self.assertEqual(len(license_files), 1, sorted(license_files))
                entry_points = archive.read(entry_point_files[0]).decode()
                license_text = archive.read(license_files[0]).decode()

            self.assertIn("kyoko = kyoko.cli:main", entry_points)
            self.assertIn("Apache License", license_text)
            self.assertIn("kyoko/fixture_replay.py", names)
            self.assertIn("kyoko/fixture_replay_server.py", names)
            self.assertIn("kyoko/assets/learning-proposals/valid-harness-proposal.json", names)
            self.assertIn(
                "kyoko/assets/learning-proposals/valid-harness-generated-file-proposal.json",
                names,
            )
            self.assertIn("kyoko/assets/schemas/learning-proposal.schema.json", names)
            self.assertIn(
                "kyoko/assets/source-events/hermes-news-research-minimal.json", names
            )
            self.assertIn(
                "kyoko/assets/replay-results/researcher-fetch-timeout-success.json",
                names,
            )

    def test_built_sdist_includes_packaging_metadata_and_assets(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)
            source = self._copy_build_source(tmpdir)
            sdist_dir = tmpdir / "sdist"
            sdist_dir.mkdir()
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import setuptools.build_meta as build_meta; "
                        f"print(build_meta.build_sdist({str(sdist_dir)!r}))"
                    ),
                ],
                cwd=source,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=True,
            )

            output_lines = [
                line.strip() for line in result.stdout.splitlines() if line.strip()
            ]
            sdist_name = output_lines[-1]
            sdist_path = sdist_dir / sdist_name
            self.assertTrue(sdist_path.exists(), result.stdout)
            prefix = sdist_name[: -len(".tar.gz")]

            with tarfile.open(sdist_path, "r:gz") as archive:
                names = set(archive.getnames())

            self.assertIn(f"{prefix}/setup.cfg", names)
            self.assertIn(f"{prefix}/setup.py", names)
            self.assertIn(f"{prefix}/MANIFEST.in", names)
            self.assertIn(f"{prefix}/pyproject.toml", names)
            self.assertIn(f"{prefix}/LICENSE", names)
            self.assertIn(f"{prefix}/kyoko/fixture_replay.py", names)
            self.assertIn(f"{prefix}/kyoko/fixture_replay_server.py", names)
            self.assertIn(
                f"{prefix}/kyoko/assets/learning-proposals/valid-harness-proposal.json",
                names,
            )
            self.assertIn(
                f"{prefix}/kyoko/assets/learning-proposals/valid-harness-generated-file-proposal.json",
                names,
            )
            self.assertIn(
                f"{prefix}/kyoko/assets/schemas/learning-proposal.schema.json", names
            )
            self.assertIn(
                f"{prefix}/kyoko/assets/source-events/hermes-news-research-minimal.json",
                names,
            )
            self.assertIn(
                f"{prefix}/kyoko/assets/replay-results/researcher-fetch-timeout-success.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/doctor-readiness.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/generate-checks.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/checks.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/check-assertion-presets.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/run-check.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/check-detail.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/check-lock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/check-locks.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/check-unlock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/check-approve.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-detail.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/bundled-assets.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/bundled-assets-export.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/demo.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/status.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/ingest.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/ingest-otlp.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/wal-checkpoint.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/load-smoke.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/ace-compat.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/ace-diff-proposals.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/blob-put.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/blobs.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/storage-report.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/prune.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/prune-retention.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/dashboard-metrics.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/dashboard-smoke.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/runs.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/run-detail.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/policy.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/policy-set.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/prepare-harness.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/harness-patches.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/harness-target-locks.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/harness-target-lock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/harness-target-unlock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/apply-harness.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/rollback-harness.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/skills.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/skill-revisions.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/skill-lock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/skill-unlock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/skill-rollback.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/context-rules.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/context-rule-revisions.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/context-rule-lock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/context-rule-unlock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/context-rule-rollback.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/run-autonomy.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-prompt.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/analyze-mock.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/mcp-install-plan.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/mcp-install.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-presets.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-adapter-bootstrap.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-adapters.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-adapter-register.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-adapter-run.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-runs.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-adapter-register.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-adapters.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-adapter-run.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/complete-replay.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-command.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-template.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-health.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-run.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-start.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-status.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-logs.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/replay-server-stop.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/source-adapter-template.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/integration-smoke-source.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/integration-smoke-replay-server.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/discover-sources.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/import-discovered-source.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-smoke-prepare-matrix.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/operator-smoke-command.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/release-smoke.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/release-smoke-matrix.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/mcp-install-smoke-matrix.contract.golden.json",
                names,
            )
            self.assertIn(
                f"{prefix}/docs/fixtures/cli-json/project-bootstrap.contract.golden.json",
                names,
            )
            self.assertIn(f"{prefix}/docs/specs/0007-first-run-demo.md", names)
            self.assertIn(
                f"{prefix}/docs/fixtures/storage/legacy-schema-v14.sql",
                names,
            )
            self.assertIn(
                f"{prefix}/examples/source-hooks/langgraph_source_hook.py",
                names,
            )
            self.assertIn(
                f"{prefix}/examples/replay-hooks/hermes_replay_hook.py",
                names,
            )
            self.assertIn(f"{prefix}/scripts/validate_gate_artifacts.py", names)
            self.assertIn(f"{prefix}/tests/test_source_hook_examples.py", names)

    def test_release_install_smoke_installs_wheel_and_sdist(self) -> None:
        # An ambient install of the project (e.g. CI `python -m pip install -e .`, or
        # any `pip install .`) leaves a `kyoko.egg-info` in the source tree. Only the
        # release smoke itself must not create one, so snapshot its state up front and
        # assert no *new* egg-info appears.
        egg_info = ROOT / "kyoko.egg-info"
        egg_info_preexisting = egg_info.exists()
        with TemporaryDirectory() as tmpdir_name:
            output_dir = Path(tmpdir_name) / "release-smoke"

            report = run_release_install_smoke(
                project_root=ROOT,
                output_dir=output_dir,
                artifact_types=("wheel", "sdist"),
                run_demo=True,
            )
            payload = report.to_json()

            self.assertTrue(payload["passed"])
            self.assertEqual(
                [artifact["artifact_type"] for artifact in payload["artifacts"]],
                ["wheel", "sdist"],
            )
            for artifact in payload["artifacts"]:
                self.assertEqual(artifact["installed_version"], "0.1.1")
                self.assertTrue(artifact["install_ok"])
                self.assertIn(artifact["install_strategy"], {"pip", "legacy_setup_py"})
                self.assertTrue(artifact["doctor_ok"])
                self.assertEqual(artifact["doctor_summary"]["failed"], 0)
                self.assertGreaterEqual(artifact["doctor_summary"]["passed"], 7)
                self.assertTrue(Path(artifact["artifact_path"]).exists())
                self.assertIn(
                    f"{artifact['artifact_type']}_bundled_assets",
                    [command["name"] for command in artifact["commands"]],
                )
                self.assertIn(
                    f"{artifact['artifact_type']}_fixture_replay_server_help",
                    [command["name"] for command in artifact["commands"]],
                )
            sdist_commands = payload["artifacts"][1]["commands"]
            if sdist_commands[0]["returncode"] != 0:
                self.assertTrue(payload["artifacts"][1]["legacy_fallback_used"])
                self.assertEqual(payload["artifacts"][1]["install_strategy"], "legacy_setup_py")
                self.assertEqual(payload["artifacts"][1]["modern_install_returncode"], sdist_commands[0]["returncode"])
                self.assertIn(
                    "install_sdist_legacy_setup_py",
                    [command["name"] for command in sdist_commands],
                )
            if not egg_info_preexisting:
                self.assertFalse(egg_info.exists())

    def test_release_install_smoke_bootstraps_missing_build_backend(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)
            output_dir = tmpdir / "release-smoke"
            wheel_path = tmpdir / "kyoko-0.1.0-py3-none-any.whl"
            bootstrap_report = release_smoke.CommandSmokeReport(
                name="install_build_backend",
                command=(
                    "/tmp/build-python",
                    "-m",
                    "pip",
                    "install",
                    *release_smoke.BUILD_BACKEND_REQUIREMENTS,
                ),
                cwd=output_dir,
                returncode=0,
                duration_ms=1.0,
                stdout_tail="installed",
            )
            build_report = release_smoke.CommandSmokeReport(
                name="build_wheel",
                command=("/tmp/build-python", "-m", "pip", "wheel"),
                cwd=tmpdir,
                returncode=0,
                duration_ms=1.0,
                stdout_tail="built",
            )
            artifact_report = release_smoke.ArtifactInstallSmokeReport(
                artifact_type="wheel",
                artifact_path=wheel_path,
                venv_path=tmpdir / "venv",
                run_cwd=tmpdir / "run",
                installed_version="0.1.0",
                doctor_ok=True,
                doctor_summary={"failed": 0, "passed": 1, "warnings": 0},
                dashboard_smoke_ok=None,
                dashboard_smoke_summary=None,
                commands=(),
            )
            with patch(
                "kyoko.release_smoke.python_build_backend_reason",
                return_value="python_build_backend_unavailable:setuptools.build_meta",
            ), patch(
                "kyoko.release_smoke._prepare_build_python_environment",
                return_value=("/tmp/build-python", (bootstrap_report,)),
            ) as prepare, patch(
                "kyoko.release_smoke._copy_project_source",
                return_value=tmpdir,
            ), patch(
                "kyoko.release_smoke._build_wheel",
                return_value=(wheel_path, build_report),
            ), patch(
                "kyoko.release_smoke._install_and_check_artifact",
                return_value=artifact_report,
            ) as install:
                run_release_install_smoke(
                    project_root=ROOT,
                    output_dir=output_dir,
                    artifact_types=("wheel",),
                    run_demo=False,
                )

            prepare.assert_called_once()
            self.assertEqual(prepare.call_args.kwargs["python_executable"], sys.executable)
            self.assertEqual(install.call_args.kwargs["python_executable"], "/tmp/build-python")

    def test_release_install_smoke_resolves_relative_output_dir(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)
            expected_output_dir = (tmpdir / "release-smoke").resolve()
            wheel_path = expected_output_dir / "artifacts" / "kyoko-0.1.0-py3-none-any.whl"
            artifact_report = release_smoke.ArtifactInstallSmokeReport(
                artifact_type="wheel",
                artifact_path=wheel_path,
                venv_path=expected_output_dir / "venv",
                run_cwd=expected_output_dir / "run",
                installed_version="0.1.0",
                doctor_ok=True,
                doctor_summary={"failed": 0, "passed": 1, "warnings": 0},
                dashboard_smoke_ok=None,
                dashboard_smoke_summary=None,
                commands=(),
            )
            build_report = release_smoke.CommandSmokeReport(
                name="build_wheel",
                command=(sys.executable, "-m", "pip", "wheel"),
                cwd=expected_output_dir,
                returncode=0,
                duration_ms=1.0,
                stdout_tail="built",
            )

            previous_cwd = Path.cwd()
            os.chdir(tmpdir)
            try:
                with patch(
                    "kyoko.release_smoke.python_build_backend_reason",
                    return_value=None,
                ), patch(
                    "kyoko.release_smoke._copy_project_source",
                    side_effect=lambda _root, destination: destination,
                ) as copy_source, patch(
                    "kyoko.release_smoke._build_wheel",
                    return_value=(wheel_path, build_report),
                ) as build_wheel, patch(
                    "kyoko.release_smoke._install_and_check_artifact",
                    return_value=artifact_report,
                ) as install:
                    report = run_release_install_smoke(
                        project_root=ROOT,
                        output_dir=Path("release-smoke"),
                        artifact_types=("wheel",),
                        run_demo=False,
                    )
            finally:
                os.chdir(previous_cwd)

            self.assertEqual(report.output_dir, expected_output_dir)
            self.assertTrue(copy_source.call_args.args[1].is_absolute())
            self.assertTrue(build_wheel.call_args.kwargs["project_root"].is_absolute())
            self.assertTrue(install.call_args.kwargs["output_dir"].is_absolute())

    def test_release_install_smoke_dashboard_failure_blocks_report(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            tmpdir = Path(tmpdir_name)
            output_dir = tmpdir / "release-smoke"
            wheel_path = output_dir / "artifacts" / "kyoko-0.1.0-py3-none-any.whl"
            artifact_report = release_smoke.ArtifactInstallSmokeReport(
                artifact_type="wheel",
                artifact_path=wheel_path,
                venv_path=output_dir / "venv",
                run_cwd=output_dir / "run",
                installed_version="0.1.0",
                doctor_ok=True,
                doctor_summary={"failed": 0, "passed": 1, "warnings": 0},
                dashboard_smoke_ok=False,
                dashboard_smoke_summary={"failed": 1, "passed": 10, "warnings": 0},
                commands=(),
            )
            build_report = release_smoke.CommandSmokeReport(
                name="build_wheel",
                command=(sys.executable, "-m", "pip", "wheel"),
                cwd=output_dir,
                returncode=0,
                duration_ms=1.0,
                stdout_tail="built",
            )

            with patch(
                "kyoko.release_smoke.python_build_backend_reason",
                return_value=None,
            ), patch(
                "kyoko.release_smoke._copy_project_source",
                side_effect=lambda _root, destination: destination,
            ), patch(
                "kyoko.release_smoke._build_wheel",
                return_value=(wheel_path, build_report),
            ), patch(
                "kyoko.release_smoke._install_and_check_artifact",
                return_value=artifact_report,
            ) as install:
                report = run_release_install_smoke(
                    project_root=ROOT,
                    output_dir=output_dir,
                    artifact_types=("wheel",),
                    dashboard_smoke=True,
                    run_demo=False,
                )

            payload = report.to_json()
            self.assertFalse(payload["passed"])
            self.assertTrue(payload["dashboard_smoke"])
            self.assertFalse(payload["artifacts"][0]["dashboard_smoke_ok"])
            self.assertTrue(install.call_args.kwargs["dashboard_smoke"])

    def test_install_artifact_runs_dashboard_smoke_and_summarizes_result(self) -> None:
        calls = []

        def fake_run_command(
            *,
            name: str,
            command: tuple[str, ...],
            cwd: Path,
            timeout_seconds: int,
            check: bool = True,
            tail_max_chars: int = 5000,
        ) -> release_smoke.CommandSmokeReport:
            calls.append((name, command, cwd, tail_max_chars))
            stdout_tail = ""
            if name == "wheel_metadata":
                stdout_tail = json.dumps(
                    {"module_version": "0.1.0", "version": "0.1.0"}
                ) + "\n"
            elif name == "wheel_doctor":
                stdout_tail = json.dumps(
                    {"ok": True, "summary": {"failed": 0, "passed": 11, "warnings": 1}}
                ) + "\n"
            elif name == "wheel_doctor_dashboard_smoke":
                stdout_tail = json.dumps(
                    {
                        "ok": True,
                        "summary": {"failed": 0, "passed": 12, "warnings": 0},
                        "checks": [
                            {
                                "id": "dashboard_smoke",
                                "status": "pass",
                                "detail": {
                                    "browser_backend": "npx-playwright",
                                    "viewports": [
                                        {"name": "desktop", "passed": True},
                                        {"name": "mobile", "passed": True},
                                    ],
                                },
                            }
                        ],
                    }
                ) + "\n"
            return release_smoke.CommandSmokeReport(
                name=name,
                command=command,
                cwd=cwd,
                returncode=0,
                duration_ms=1.0,
                stdout_tail=stdout_tail,
            )

        with TemporaryDirectory() as tmpdir_name:
            output_dir = Path(tmpdir_name) / "release-smoke"
            artifact_path = output_dir / "artifacts" / "kyoko-0.1.0-py3-none-any.whl"
            artifact_path.parent.mkdir(parents=True)
            artifact_path.write_bytes(b"wheel")
            with patch("kyoko.release_smoke._create_venv") as create_venv, patch(
                "kyoko.release_smoke._run_command",
                side_effect=fake_run_command,
            ):
                report = release_smoke._install_and_check_artifact(
                    artifact_type="wheel",
                    artifact_path=artifact_path,
                    output_dir=output_dir,
                    python_executable=sys.executable,
                    install_dependencies=False,
                    run_demo=True,
                    dashboard_smoke=True,
                    timeout_seconds=30,
                )

        dashboard_call = next(
            (call for call in calls if call[0] == "wheel_doctor_dashboard_smoke"),
            None,
        )
        self.assertIsNotNone(dashboard_call)
        self.assertEqual(report.dashboard_smoke_ok, True)
        self.assertEqual(
            report.dashboard_smoke_summary,
            {
                "failed": 0,
                "passed": 12,
                "warnings": 0,
                "browser_backend": "npx-playwright",
                "viewport_count": 2,
            },
        )
        self.assertIn("--dashboard-smoke", dashboard_call[1])
        self.assertIn("--dashboard-smoke-install-browser-deps", dashboard_call[1])
        self.assertIn("--dashboard-smoke-screenshot", dashboard_call[1])
        self.assertEqual(dashboard_call[3], 20000)
        create_venv.assert_called_once()

    def test_build_python_environment_bootstraps_missing_build_backend(self) -> None:
        calls = []

        def fake_run_command(
            *,
            name: str,
            command: tuple[str, ...],
            cwd: Path,
            timeout_seconds: int,
            check: bool = True,
            tail_max_chars: int = 5000,
        ) -> release_smoke.CommandSmokeReport:
            calls.append((name, command))
            return release_smoke.CommandSmokeReport(
                name=name,
                command=command,
                cwd=cwd,
                returncode=0,
                duration_ms=1.0,
                stdout_tail="",
            )

        with TemporaryDirectory() as tmpdir_name:
            output_dir = Path(tmpdir_name)
            with patch("kyoko.release_smoke._run_command", side_effect=fake_run_command):
                python, reports = release_smoke._prepare_build_python_environment(
                    python_executable="/tmp/python",
                    output_dir=output_dir,
                    timeout_seconds=30,
                )

        self.assertEqual(python, str(output_dir / "build-venv" / "bin" / "python"))
        self.assertEqual(
            [report.name for report in reports],
            ["create_build_venv", "install_build_backend", "check_build_backend"],
        )
        self.assertEqual(
            calls[1][1][-len(release_smoke.BUILD_BACKEND_REQUIREMENTS):],
            release_smoke.BUILD_BACKEND_REQUIREMENTS,
        )

    def test_sdist_install_venv_bootstraps_missing_build_backend(self) -> None:
        calls = []

        def fake_run_command(
            *,
            name: str,
            command: tuple[str, ...],
            cwd: Path,
            timeout_seconds: int,
            check: bool = True,
            tail_max_chars: int = 5000,
        ) -> release_smoke.CommandSmokeReport:
            calls.append((name, command, check))
            return release_smoke.CommandSmokeReport(
                name=name,
                command=command,
                cwd=cwd,
                returncode=1 if name == "check_sdist_build_backend" else 0,
                duration_ms=1.0,
                stdout_tail="",
            )

        with TemporaryDirectory() as tmpdir_name:
            with patch("kyoko.release_smoke._run_command", side_effect=fake_run_command):
                report = release_smoke._ensure_install_venv_build_backend(
                    python=Path("/tmp/python"),
                    run_cwd=Path(tmpdir_name),
                    timeout_seconds=30,
                )

        self.assertIsNotNone(report)
        self.assertEqual(report.name, "install_sdist_build_backend")
        self.assertEqual(calls[0][0], "check_sdist_build_backend")
        self.assertFalse(calls[0][2])
        self.assertEqual(calls[1][0], "install_sdist_build_backend")
        self.assertEqual(
            calls[1][1][-len(release_smoke.BUILD_BACKEND_REQUIREMENTS):],
            release_smoke.BUILD_BACKEND_REQUIREMENTS,
        )

    def test_sdist_install_venv_records_non_strict_build_backend_failure(self) -> None:
        calls = []

        def fake_run_command(
            *,
            name: str,
            command: tuple[str, ...],
            cwd: Path,
            timeout_seconds: int,
            check: bool = True,
            tail_max_chars: int = 5000,
        ) -> release_smoke.CommandSmokeReport:
            calls.append((name, command, check))
            return release_smoke.CommandSmokeReport(
                name=name,
                command=command,
                cwd=cwd,
                returncode=1,
                duration_ms=1.0,
                stdout_tail="wheel.bdist_wheel\n",
            )

        with TemporaryDirectory() as tmpdir_name:
            with patch("kyoko.release_smoke._run_command", side_effect=fake_run_command):
                report = release_smoke._ensure_install_venv_build_backend(
                    python=Path("/tmp/python"),
                    run_cwd=Path(tmpdir_name),
                    strict=False,
                    timeout_seconds=30,
                )

        self.assertIsNotNone(report)
        self.assertEqual(report.returncode, 1)
        self.assertEqual(calls[0][0], "check_sdist_build_backend")
        self.assertFalse(calls[0][2])
        self.assertEqual(calls[1][0], "install_sdist_build_backend")
        self.assertFalse(calls[1][2])

    def test_release_install_smoke_matrix_skips_missing_python_targets(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            report = run_release_install_smoke_matrix(
                project_root=ROOT,
                output_dir=Path(tmpdir_name) / "matrix",
                python_targets=("python-kyoko-missing-version",),
                artifact_types=("wheel",),
                run_demo=False,
            )
            payload = report.to_json()

            self.assertFalse(payload["passed"])
            self.assertEqual(
                payload["summary"],
                {"total": 1, "passed": 0, "failed": 0, "skipped": 1, "available": 0},
            )
            self.assertEqual(payload["targets"][0]["status"], "skipped")
            self.assertEqual(payload["targets"][0]["reason"], "python_executable_not_found")

    def test_release_install_smoke_matrix_fails_when_available_target_smoke_fails(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            with patch(
                "kyoko.release_smoke.run_release_install_smoke",
                side_effect=ReleaseSmokeError("command_failed:install_build_backend:1"),
            ):
                report = run_release_install_smoke_matrix(
                    project_root=ROOT,
                    output_dir=Path(tmpdir_name) / "matrix",
                    python_targets=("current",),
                    artifact_types=("wheel",),
                    run_demo=False,
                )
            payload = report.to_json()

            self.assertFalse(payload["passed"])
            self.assertEqual(
                payload["summary"],
                {"total": 1, "passed": 0, "failed": 1, "skipped": 0, "available": 1},
            )
            self.assertEqual(payload["targets"][0]["status"], "failed")
            self.assertEqual(
                payload["targets"][0]["reason"],
                "command_failed:install_build_backend:1",
            )

    def test_release_install_smoke_matrix_runs_available_python_target(self) -> None:
        with TemporaryDirectory() as tmpdir_name:
            output_dir = Path(tmpdir_name) / "matrix"
            fake_report = ReleaseInstallSmokeReport(
                project_root=ROOT,
                output_dir=output_dir / "current",
                artifact_dir=output_dir / "current" / "artifacts",
                python_executable=sys.executable,
                install_dependencies=False,
                run_demo=False,
                dashboard_smoke=False,
                artifacts=(),
                build_commands=(),
                passed=True,
                duration_ms=1.0,
            )

            with patch("kyoko.release_smoke.run_release_install_smoke", return_value=fake_report) as smoke:
                report = run_release_install_smoke_matrix(
                    project_root=ROOT,
                    output_dir=output_dir,
                    python_targets=("current",),
                    artifact_types=("wheel",),
                    run_demo=False,
                )

            self.assertTrue(report.passed)
            self.assertEqual(report.to_json()["summary"]["passed"], 1)
            self.assertEqual(smoke.call_args.kwargs["python_executable"], sys.executable)
            self.assertEqual(smoke.call_args.kwargs["artifact_types"], ("wheel",))


if __name__ == "__main__":
    unittest.main()
