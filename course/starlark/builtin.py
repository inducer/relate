from __future__ import annotations


__copyright__ = "Copyright (C) 2025 University of Illinois Board of Trustees"

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

from typing import TYPE_CHECKING

from course.content import FlowSessionStartMode
from course.starlark.data import (
    FlowSession,
    Participation,
)
from course.starlark.dataclasses import dataclass_to_starlark


if TYPE_CHECKING:
    from course.starlark.module import StarlarkModule


RELATE_RULES_STAR = f"""
Timestamp = float

FlowSessionExpirationMode = enum("end", "roll_over")
ParticipationStatus = enum("requested", "active", "dropped", "denied")

{dataclass_to_starlark(Participation)}
{dataclass_to_starlark(FlowSession)}
{dataclass_to_starlark(FlowSessionStartMode)}
start_mode = make_flow_session_start_mode
"""


_RELATE_MODULE_CACHE: dict[str, StarlarkModule] = {}


def get_relate_starlark_module(name: str) -> StarlarkModule:
    try:
        return _RELATE_MODULE_CACHE[name]
    except KeyError:
        pass

    if name == "relate/rules.star":
        code = RELATE_RULES_STAR
    else:
        raise FileNotFoundError(name)

    def load_func(name: str):
        return get_relate_starlark_module(name)

    from course.starlark.module import make_starlark_module
    mod = make_starlark_module(name, code, load_func)

    _RELATE_MODULE_CACHE[name] = mod
    return mod
