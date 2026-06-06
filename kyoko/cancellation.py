"""In-process cooperative cancellation for analysis jobs.

The dashboard's ``AnalysisRunner`` runs each job on a worker thread inside
``kyoko serve``. A job's longest phase is an operator subprocess, so a useful
"cancel" must actually terminate that subprocess. This module keeps a registry of
in-flight jobs keyed by ``job_id``, each holding a :class:`CancelToken` that both
flags cancellation (checked at phase checkpoints) and tracks the live
subprocess(es) so a cancel can kill the process group.

**Single-process only.** A cancel request must reach the same process that runs the
job (the ``serve`` process), which is why this is an in-memory registry, not a DB
flag. The synchronous ``InlineAnalysisRunner`` (tests, no background worker) never
has a window to cancel — the launch call blocks until the job finishes — so cancel
is a no-op there, which is correct.
"""

from __future__ import annotations

import os
import signal
import threading
from typing import Any, Optional


class CancelledError(Exception):
    """Raised at a checkpoint when the current job has been cancelled."""


class CancelToken:
    """Per-job cancellation flag + the set of live subprocesses to terminate."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._procs: "set[Any]" = set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        """Raise :class:`CancelledError` if a cancel has been requested."""
        if self._event.is_set():
            raise CancelledError("cancelled")

    def request(self) -> None:
        """Flag the job cancelled and kill any registered subprocesses."""
        self._event.set()
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            _terminate(proc)

    def register_proc(self, proc: Any) -> None:
        with self._lock:
            self._procs.add(proc)
        # If the cancel landed between request() and registration, kill immediately.
        if self._event.is_set():
            _terminate(proc)

    def unregister_proc(self, proc: Any) -> None:
        with self._lock:
            self._procs.discard(proc)


def _terminate(proc: Any) -> None:
    try:
        if proc.poll() is not None:
            return  # already exited
    except Exception:
        pass
    # Operator CLIs may spawn children; kill the whole process group when we can
    # (the subprocess is launched with start_new_session=True). Fall back to a
    # direct terminate on platforms/processes where that isn't available.
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        return
    except Exception:
        pass
    try:
        proc.terminate()
    except Exception:
        pass


_local = threading.local()
_registry: "dict[str, CancelToken]" = {}
_reg_lock = threading.Lock()


def begin(job_id: str) -> CancelToken:
    """Register a token for ``job_id`` and bind it to the current thread."""
    token = CancelToken()
    with _reg_lock:
        _registry[job_id] = token
    _local.token = token
    return token


def end(job_id: str) -> None:
    """Drop the token for ``job_id`` (called in a finally around the job)."""
    _local.token = None
    with _reg_lock:
        _registry.pop(job_id, None)


def current_token() -> Optional[CancelToken]:
    """The token for the job running on this thread, if any."""
    return getattr(_local, "token", None)


def request_cancel(job_id: str) -> bool:
    """Request cancellation of an in-flight job. Returns False if it's unknown
    (already finished, never started, or running in another process)."""
    with _reg_lock:
        token = _registry.get(job_id)
    if token is None:
        return False
    token.request()
    return True
