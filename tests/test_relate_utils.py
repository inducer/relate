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

import operator
import time

import pytest

from relate.utils import TIMED_OUT, call_with_timeout


def _return_value(x):
    return x


def _sleep_and_return(seconds, x):
    time.sleep(seconds)
    return x


def _raise_value_error(msg):
    raise ValueError(msg)


def _large_integer_calc() -> int:
    return 10000000**10000000


class TestCallWithTimeout:
    def test_returns_result_on_success(self):
        result = call_with_timeout(5, _return_value, 42)
        assert result == 42

    def test_returns_result_with_multiple_args(self):
        result = call_with_timeout(5, operator.add, 3, 4)
        assert result == 7

    def test_returns_timed_out_sentinel_when_slow(self):
        result = call_with_timeout(1, _sleep_and_return, 10.0, "never")
        assert result is TIMED_OUT

    def test_slow_integer_math_times_out(self):
        result = call_with_timeout(2, _large_integer_calc)
        assert result is TIMED_OUT

    def test_raises_exception_on_error(self):
        with pytest.raises(ValueError, match="boom"):
            call_with_timeout(5, _raise_value_error, "boom")

    def test_none_return_value(self):
        result = call_with_timeout(5, _return_value, None)
        assert result is None

    def test_complex_return_value(self):
        result = call_with_timeout(5, _return_value, {"key": [1, 2, 3]})
        assert result == {"key": [1, 2, 3]}
