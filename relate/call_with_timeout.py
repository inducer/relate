from __future__ import annotations


__copyright__ = "Copyright (C) 2026 Andreas Kloeckner"

__license__ = """
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
"""


import atexit
import multiprocessing
import multiprocessing.connection
import os
import queue
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar, final

from typing_extensions import Sentinel


if TYPE_CHECKING:
    from collections.abc import Callable


ResultT = TypeVar("ResultT")
P = ParamSpec("P")

TIMED_OUT = Sentinel("TIMED_OUT")


@dataclass(frozen=True)
class _RaisedException:
    exc_value: Exception


# 'spawn' avoids inheriting the WSGI process's database connections.
MP_CONTEXT = multiprocessing.get_context("spawn")

_REAPER_MAX_INTERVAL_SECONDS = 60


def _install_parent_death_signal(expected_parent_pid: int) -> None:
    if sys.platform != "linux":
        # A Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE could
        # provide equivalent defense in depth if larger Windows deployments
        # demonstrate a need for it.
        return

    import ctypes

    pr_set_pdeathsig = 1
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(pr_set_pdeathsig, signal.SIGKILL, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno))

    # PR_SET_PDEATHSIG is armed too late if the parent died between spawning us
    # and the prctl call. Checking after arming closes that race.
    if os.getppid() != expected_parent_pid:
        os.kill(os.getpid(), signal.SIGKILL)


def _call_with_timeout_worker(
            conn: multiprocessing.connection.Connection,
            expected_parent_pid: int,
        ) -> None:
    _install_parent_death_signal(expected_parent_pid)

    from django.db import connections
    connections.close_all()

    try:
        while True:
            job = conn.recv()
            if job is None:
                return

            f, args, kwargs = job
            try:
                conn.send(f(*args, **kwargs))
            except Exception as exc:
                conn.send(_RaisedException(exc))
    except (EOFError, OSError):
        pass
    finally:
        conn.close()


_WORKER_CONNECTION_CLOSED = object()


@final
class _TimeoutWorker:
    def __init__(self) -> None:
        self.conn: Any | None = None
        self.process: Any | None = None
        self.result: Any = _WORKER_CONNECTION_CLOSED
        self.result_ready = threading.Event()
        self.receiver: threading.Thread | None = None
        self.last_used = time.monotonic()
        self._lifecycle_lock = threading.Lock()

    def _receive_results(
                self, conn: multiprocessing.connection.Connection) -> None:
        while True:
            try:
                self.result = conn.recv()
            except (EOFError, OSError):
                self.result = _WORKER_CONNECTION_CLOSED
                self.result_ready.set()
                return
            else:
                self.result_ready.set()

    def start(self) -> None:
        parent_conn, child_conn = MP_CONTEXT.Pipe()
        process = MP_CONTEXT.Process(
                target=_call_with_timeout_worker,
                args=(child_conn, os.getpid()),
                daemon=True)
        process_started = False
        try:
            process.start()
            process_started = True
            child_conn.close()
            self.conn = parent_conn
            self.process = process
            self.receiver = threading.Thread(
                    target=self._receive_results, args=(parent_conn,), daemon=True)
            self.receiver.start()
        except BaseException:
            child_conn.close()
            parent_conn.close()
            if process_started:
                if process.is_alive():
                    process.kill()
                process.join()
                process.close()
            raise

    def is_alive(self) -> bool:
        with self._lifecycle_lock:
            return (
                    self.conn is not None
                    and self.process is not None
                    and self.process.is_alive())

    def dispatch(self, job: tuple[Any, tuple[Any, ...], dict[str, Any]]) -> None:
        with self._lifecycle_lock:
            if self.conn is None:
                raise BrokenPipeError
            self.result = _WORKER_CONNECTION_CLOSED
            self.result_ready.clear()
            self.conn.send(job)

    def close(self) -> None:
        with self._lifecycle_lock:
            if self.conn is not None:
                try:
                    self.conn.send(None)
                except (BrokenPipeError, EOFError, OSError):
                    pass
                self.conn.close()
                self.conn = None

            if self.process is not None:
                self.process.join(timeout=1)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join()
                self.process.close()
                self.process = None

    def kill(self) -> None:
        with self._lifecycle_lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

            if self.process is not None:
                if self.process.is_alive():
                    self.process.kill()
                self.process.join()
                self.process.close()
                self.process = None

    def abandon_after_fork(self) -> None:
        """Drop inherited handles without affecting the original process's worker."""
        if self.conn is not None:
            self.conn.close()
            self.conn = None
        self.process = None


@final
class _WorkerStartRequest:
    def __init__(self, worker: _TimeoutWorker) -> None:
        self.worker = worker
        self.done = threading.Event()
        self.exception: BaseException | None = None


@final
class _TimeoutWorkerPool:
    def __init__(self, *, max_workers: int, max_idle_seconds: float) -> None:
        if max_workers < 1:
            raise ValueError("timeout worker pool size must be positive")
        if max_idle_seconds <= 0:
            raise ValueError("timeout worker maximum idle time must be positive")

        self.owner_pid = os.getpid()
        self.max_workers = max_workers
        self.max_idle_seconds = max_idle_seconds
        self._condition = threading.Condition()
        self._workers: set[_TimeoutWorker] = set()
        self._available: list[_TimeoutWorker] = []
        self._workers_being_started = 0
        self._closed = False
        self._manager_requests: queue.Queue[_WorkerStartRequest | None] = (
                queue.Queue())
        self._manager = threading.Thread(
                target=self._manage_workers,
                name="relate-timeout-worker-manager",
                daemon=True)
        self._manager.start()

    def acquire(self, deadline: float) -> _TimeoutWorker | None:
        while True:
            with self._condition:
                while self._available:
                    worker = self._available.pop()
                    if worker.is_alive():
                        return worker
                    self._workers.discard(worker)
                    worker.close()

                if self._closed:
                    return None

                if len(self._workers) + self._workers_being_started < self.max_workers:
                    self._workers_being_started += 1
                    worker = _TimeoutWorker()
                    request = _WorkerStartRequest(worker)
                    self._manager_requests.put(request)
                    break

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)

        request.done.wait()
        if request.exception is not None:
            with self._condition:
                self._workers_being_started -= 1
                self._condition.notify()
            raise request.exception

        with self._condition:
            self._workers_being_started -= 1
            if self._closed:
                self._condition.notify()
            else:
                self._workers.add(worker)
                return worker

        worker.close()
        return None

    def release(self, worker: _TimeoutWorker) -> None:
        if not worker.is_alive():
            self.discard(worker)
            return

        worker.last_used = time.monotonic()
        with self._condition:
            if self._closed or worker not in self._workers:
                should_close = True
            else:
                self._available.append(worker)
                self._condition.notify()
                should_close = False

        if should_close:
            worker.close()

    def discard(self, worker: _TimeoutWorker) -> None:
        with self._condition:
            self._workers.discard(worker)
            try:
                self._available.remove(worker)
            except ValueError:
                pass
            self._condition.notify()
        worker.kill()

    def _manage_workers(self) -> None:
        """
        Main function of worker management thread.

        Start requests are handled here because of ``PR_SET_DEATHSIG`` semantics,
        which attach to the specific thread that created the process. This
        provides a stable place to attach the processes, compared to whichever
        worker thread happened to request it.

        The management thread will die when the WSGI server reaps the process.
        ``PR_SET_DEATHSIG`` will reap the workers.
        """
        interval = min(_REAPER_MAX_INTERVAL_SECONDS, self.max_idle_seconds)
        next_reap = time.monotonic() + interval

        while True:
            try:
                request = self._manager_requests.get(
                        timeout=max(0, next_reap - time.monotonic()))
            except queue.Empty:
                request = None
                should_stop = False
            else:
                should_stop = request is None

            if should_stop:
                return

            if request is not None:
                try:
                    request.worker.start()
                except BaseException as exc:
                    request.exception = exc
                finally:
                    request.done.set()

            if time.monotonic() >= next_reap:
                self._reap_idle_workers()
                next_reap = time.monotonic() + interval

    def _reap_idle_workers(self) -> None:
        cutoff = time.monotonic() - self.max_idle_seconds
        with self._condition:
            expired = [
                    worker for worker in self._available
                    if worker.last_used <= cutoff
                    ]
            if expired:
                expired_set = set(expired)
                self._available = [
                        worker for worker in self._available
                        if worker not in expired_set
                        ]
                self._workers.difference_update(expired_set)
                self._condition.notify_all()

        for worker in expired:
            worker.close()

    def close(self) -> None:
        if self.owner_pid != os.getpid():
            self.abandon_after_fork()
            return

        with self._condition:
            if self._closed:
                return
            self._closed = True
            workers = list(self._workers)
            self._workers.clear()
            self._available.clear()
            self._condition.notify_all()

        for worker in workers:
            worker.close()
        self._manager_requests.put(None)
        self._manager.join()

    def abandon_after_fork(self) -> None:
        for worker in self._workers:
            worker.abandon_after_fork()
        self._workers.clear()
        self._available.clear()
        self._closed = True


_timeout_pool: _TimeoutWorkerPool | None = None
_timeout_pool_lock = threading.Lock()


def _after_fork_in_child() -> None:
    global _timeout_pool, _timeout_pool_lock

    # Locks and threads from the parent cannot be used safely after fork.
    pool = _timeout_pool
    _timeout_pool = None
    _timeout_pool_lock = threading.Lock()
    if pool is not None:
        pool.abandon_after_fork()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_after_fork_in_child)


def _get_timeout_pool() -> _TimeoutWorkerPool:
    global _timeout_pool

    with _timeout_pool_lock:
        if _timeout_pool is not None and _timeout_pool.owner_pid != os.getpid():
            _timeout_pool.abandon_after_fork()
            _timeout_pool = None

        if _timeout_pool is None:
            from django.conf import settings
            _timeout_pool = _TimeoutWorkerPool(
                max_workers=settings.RELATE_TIMEOUT_WORKER_POOL_SIZE,
                max_idle_seconds=settings.RELATE_TIMEOUT_WORKER_MAX_IDLE_SECONDS,
            )

        return _timeout_pool


def _close_timeout_pool() -> None:
    global _timeout_pool

    with _timeout_pool_lock:
        pool = _timeout_pool
        _timeout_pool = None

    if pool is not None:
        pool.close()


atexit.register(_close_timeout_pool)


def call_with_timeout(
            timeout: int,
            f: Callable[P, ResultT],
            *args: P.args,
            **kwargs: P.kwargs,
        ) -> ResultT | TIMED_OUT:  # type: ignore[valid-type]
    """Call *f* in a reusable worker process with a deadline.

    Workers are shared by all threads in the current process and bounded by
    ``RELATE_TIMEOUT_WORKER_POOL_SIZE``. The deadline includes waiting for a
    worker, worker creation, dispatch, and execution. Worker startup and
    argument serialization are synchronous and cannot be forcibly interrupted.
    A worker that exceeds the deadline or loses its connection is killed rather
    than returned to the pool. Idle workers are retired after
    ``RELATE_TIMEOUT_WORKER_MAX_IDLE_SECONDS``. Callables, arguments, results,
    and raised exceptions must be pickleable.

    In order to reliably avoid process leakage, the callable *f* must
    not launch subprocesses.
    """
    deadline = time.monotonic() + timeout
    if timeout <= 0:
        return TIMED_OUT

    pool = _get_timeout_pool()
    worker = pool.acquire(deadline)
    if worker is None:
        return TIMED_OUT

    if time.monotonic() >= deadline:
        pool.release(worker)
        return TIMED_OUT

    keep_worker = False
    try:
        worker.dispatch((f, args, kwargs))
        remaining = deadline - time.monotonic()
        if remaining > 0 and worker.result_ready.wait(remaining):
            result = worker.result
            if result is not _WORKER_CONNECTION_CLOSED:
                keep_worker = True
                if isinstance(result, _RaisedException):
                    raise result.exc_value
                return result
    except (BrokenPipeError, EOFError, OSError):
        pass
    finally:
        if keep_worker:
            pool.release(worker)
        else:
            pool.discard(worker)

    return TIMED_OUT
