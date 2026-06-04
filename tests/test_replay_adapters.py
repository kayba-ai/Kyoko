import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from kyoko.evals import generate_evals_for_proposal
from kyoko.proposals import submit_learning_proposal
from kyoko.replay_adapters import (
    ReplayAdapterError,
    list_replay_adapters,
    register_replay_adapter,
    run_registered_replay_adapter,
)
from kyoko.storage import get_database_status, ingest_source_fixture


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "docs/fixtures/source-events/hermes-news-research-minimal.json"
VALID_PROPOSAL = ROOT / "docs/fixtures/learning-proposals/valid-context-proposal.json"
SCHEMA = ROOT / "docs/schemas/learning-proposal.schema.json"
REPLAY_COMMAND = ROOT / "tests/fixtures/replay_command.py"


class ReplayAdapterTests(unittest.TestCase):
    def test_register_and_run_replay_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            output_dir = Path(tmpdir) / "adapter-output"
            eval_spec_id = _create_eval_spec(db_path)

            register = register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                output_dir=output_dir,
            )
            adapters = list_replay_adapters(db_path)
            report = run_registered_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                eval_spec_id=eval_spec_id,
                run_eval_after=True,
            )
            status = get_database_status(db_path)

            self.assertEqual(register.adapter_id, "fixture_replay")
            self.assertEqual(register.adapter_kind, "command")
            self.assertEqual(register.profile_id, "profile_news_research_001")
            self.assertEqual(adapters[0]["command"], [sys.executable, str(REPLAY_COMMAND)])
            self.assertEqual(adapters[0]["kind"], "command")
            self.assertTrue(adapters[0]["enabled"])
            self.assertEqual(report.completion.output_run_id, "run_research_topic_replay_001")
            self.assertTrue(str(report.request_path).startswith(str(output_dir)))
            self.assertIsNotNone(report.eval_run)
            self.assertEqual(report.eval_run.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")
            self.assertEqual(status.counts["replay_adapters"], 1)
            self.assertEqual(status.counts["replay_runs"], 1)
            self.assertEqual(status.counts["eval_runs"], 1)

    def test_disabled_replay_adapter_is_not_runnable(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            register_replay_adapter(
                db_path=db_path,
                adapter_id="fixture_replay",
                name="Fixture replay",
                command=[sys.executable, str(REPLAY_COMMAND)],
                enabled=False,
            )

            with self.assertRaisesRegex(ReplayAdapterError, "disabled"):
                run_registered_replay_adapter(
                    db_path=db_path,
                    adapter_id="fixture_replay",
                    eval_spec_id=eval_spec_id,
                )

    def test_package_local_fixture_replay_adapter_runs_eval(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            eval_spec_id = _create_eval_spec(db_path)
            output_dir = Path(tmpdir) / "package-fixture-replay"

            register_replay_adapter(
                db_path=db_path,
                adapter_id="package_fixture_replay",
                name="Package fixture replay",
                command=[sys.executable, "-m", "kyoko.fixture_replay"],
                output_dir=output_dir,
            )

            report = run_registered_replay_adapter(
                db_path=db_path,
                adapter_id="package_fixture_replay",
                eval_spec_id=eval_spec_id,
                run_eval_after=True,
            )

            self.assertEqual(report.completion.status, "passed")
            self.assertEqual(report.completion.output_run_id, "run_research_topic_replay_001")
            self.assertIsNotNone(report.eval_run)
            self.assertEqual(report.eval_run.status, "passed")
            self.assertEqual(report.eval_run.promoted_trust_level, "L2_regression")
            self.assertTrue(report.raw_output_path.exists())

    def test_remote_http_adapter_requires_explicit_opt_in(self) -> None:
        with TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "kyoko.db"
            _create_eval_spec(db_path)

            with self.assertRaisesRegex(ReplayAdapterError, "remote_replay_server_requires_opt_in"):
                register_replay_adapter(
                    db_path=db_path,
                    adapter_id="remote_http_replay",
                    name="Remote HTTP replay",
                    server_url="http://example.com:61200",
                )

            report = register_replay_adapter(
                db_path=db_path,
                adapter_id="remote_http_replay",
                name="Remote HTTP replay",
                server_url="http://example.com:61200",
                allow_remote_server=True,
            )
            adapters = list_replay_adapters(db_path)

            self.assertTrue(report.allow_remote_server)
            self.assertEqual(adapters[0]["server_url"], "http://example.com:61200")
            self.assertTrue(adapters[0]["allow_remote_server"])


def _create_eval_spec(db_path: Path) -> str:
    ingest_source_fixture(db_path, FIXTURE)
    submit_learning_proposal(
        db_path=db_path,
        proposal_path=VALID_PROPOSAL,
        schema_path=SCHEMA,
    )
    report = generate_evals_for_proposal(
        db_path=db_path,
        proposal_id="proposal_context_timeout_001",
    )
    return report.eval_spec_ids[0]


if __name__ == "__main__":
    unittest.main()
