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

import multiprocessing
import multiprocessing.connection
import operator
import os
import pathlib
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.test import override_settings

import relate.call_with_timeout as timeout_module
from relate.call_with_timeout import TIMED_OUT, call_with_timeout_if_safe


def _return_value(x: object):
    return x


def _sleep_and_return(seconds: float, x: object):
    time.sleep(seconds)
    return x


def _raise_value_error(msg: str):
    raise ValueError(msg)


def _worker_pid():
    return os.getpid()


def _sleep_and_return_pid(seconds: float):
    time.sleep(seconds)
    return os.getpid()


def _mark_started_and_sleep(marker_path: str, seconds: float):
    pathlib.Path(marker_path).write_text(str(os.getpid()))
    time.sleep(seconds)


def _large_integer_calc() -> int:
    return 10000000**10000000


def _call_from_daemonic_process(
            conn: multiprocessing.connection.Connection,
        ) -> None:
    result = call_with_timeout_if_safe(0, _worker_pid)
    conn.send((os.getpid(), result, timeout_module._timeout_pool is None))
    conn.close()


@pytest.fixture(autouse=True)
def clean_timeout_worker_pool():
    yield
    timeout_module._close_timeout_pool()


class TestCallWithTimeout:
    def test_returns_result_on_success(self):
        result = call_with_timeout_if_safe(5, _return_value, 42)
        assert result == 42

    def test_returns_result_with_multiple_args(self):
        result = call_with_timeout_if_safe(5, operator.add, 3, 4)
        assert result == 7

    def test_daemonic_process_executes_directly(self):
        ctx = multiprocessing.get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        process = ctx.Process(
                target=_call_from_daemonic_process,
                args=(child_conn,),
                daemon=True)
        process.start()
        child_conn.close()
        try:
            assert parent_conn.poll(10)
            process_pid, result_pid, no_pool_created = parent_conn.recv()
            process.join(10)
            assert process.exitcode == 0
        finally:
            if process.is_alive():
                process.kill()
                process.join()
            process.close()
            parent_conn.close()

        assert result_pid == process_pid
        assert no_pool_created

    def test_reuses_worker(self):
        assert (
                call_with_timeout_if_safe(5, _worker_pid)
                == call_with_timeout_if_safe(5, _worker_pid))

    def test_reuses_worker_across_calling_threads(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            first_pid = executor.submit(
                    call_with_timeout_if_safe, 5, _worker_pid).result()
        with ThreadPoolExecutor(max_workers=1) as executor:
            second_pid = executor.submit(
                    call_with_timeout_if_safe, 5, _worker_pid).result()
        assert first_pid == second_pid

    @override_settings(RELATE_TIMEOUT_WORKER_POOL_SIZE=2)
    def test_worker_count_is_bounded(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                    executor.submit(
                        call_with_timeout_if_safe, 5, _sleep_and_return_pid, 0.2)
                    for _ in range(4)
                    ]
        assert len({future.result() for future in futures}) == 2

    @override_settings(
            RELATE_TIMEOUT_WORKER_POOL_SIZE=1,
            RELATE_TIMEOUT_WORKER_MAX_IDLE_SECONDS=0.1,
            )
    def test_idle_worker_is_retired(self):
        call_with_timeout_if_safe(5, _worker_pid)
        pool = timeout_module._get_timeout_pool()

        with pool._condition:
            [worker] = pool._available
            assert pool._condition.wait_for(
                lambda: worker not in pool._workers,
                timeout=5,
            )

        assert not worker.is_alive()

        # A retired worker can be replaced for the next request.
        assert call_with_timeout_if_safe(5, _worker_pid) is not TIMED_OUT

    def test_returns_timed_out_sentinel_when_slow(self):
        result = call_with_timeout_if_safe(1, _sleep_and_return, 10.0, "never")
        assert result is TIMED_OUT
        assert call_with_timeout_if_safe(5, _return_value, 42) == 42

    def test_pool_close_while_worker_is_busy(self, tmp_path: pathlib.Path):
        marker_path = tmp_path / "started"
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                    call_with_timeout_if_safe, 5, _mark_started_and_sleep,
                    str(marker_path), 10)
            deadline = time.monotonic() + 5
            while not marker_path.exists():
                assert time.monotonic() < deadline
                time.sleep(0.01)

            timeout_module._close_timeout_pool()
            assert future.result() is TIMED_OUT

    def test_slow_integer_math_times_out(self):
        result = call_with_timeout_if_safe(2, _large_integer_calc)
        assert result is TIMED_OUT

    def test_raises_exception_on_error(self):
        with pytest.raises(ValueError, match="boom"):
            call_with_timeout_if_safe(5, _raise_value_error, "boom")

    def test_none_return_value(self):
        result = call_with_timeout_if_safe(5, _return_value, None)
        assert result is None

    def test_complex_return_value(self):
        result = call_with_timeout_if_safe(5, _return_value, {"key": [1, 2, 3]})
        assert result == {"key": [1, 2, 3]}
