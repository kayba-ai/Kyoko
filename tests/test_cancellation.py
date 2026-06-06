"""Tests for in-process analysis-job cancellation."""

import os
import sys
import threading
import time
import unittest

from kyoko import cancellation
from kyoko.analyze import _run_operator_subprocess


class RegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        cancellation.end("j1")

    def test_begin_binds_token_to_thread_and_registry(self) -> None:
        token = cancellation.begin("j1")
        self.assertIs(cancellation.current_token(), token)
        self.assertFalse(token.cancelled)
        self.assertTrue(cancellation.request_cancel("j1"))
        self.assertTrue(token.cancelled)
        with self.assertRaises(cancellation.CancelledError):
            token.check()

    def test_unknown_job_returns_false(self) -> None:
        self.assertFalse(cancellation.request_cancel("does-not-exist"))

    def test_end_clears_token(self) -> None:
        cancellation.begin("j1")
        cancellation.end("j1")
        self.assertIsNone(cancellation.current_token())
        self.assertFalse(cancellation.request_cancel("j1"))


class SubprocessCancelTests(unittest.TestCase):
    def test_cancel_kills_running_subprocess(self) -> None:
        token = cancellation.begin("job_cancel")
        try:
            threading.Timer(0.3, lambda: cancellation.request_cancel("job_cancel")).start()
            started = time.time()
            with self.assertRaises(cancellation.CancelledError):
                _run_operator_subprocess(
                    [sys.executable, "-c", "import time; time.sleep(30)"],
                    input="",
                    env=dict(os.environ),
                    timeout=60,
                )
            # The 30s sleep must have been killed, not waited out.
            self.assertLess(time.time() - started, 5.0)
        finally:
            cancellation.end("job_cancel")

    def test_no_token_runs_normally(self) -> None:
        # Without a bound token the helper behaves like subprocess.run.
        self.assertIsNone(cancellation.current_token())
        completed = _run_operator_subprocess(
            [sys.executable, "-c", "import sys; print(sys.stdin.read().strip())"],
            input="hello",
            env=dict(os.environ),
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout.strip(), "hello")


if __name__ == "__main__":
    unittest.main()
