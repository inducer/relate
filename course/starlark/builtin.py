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
import ipaddress
from datetime import datetime
from importlib.resources import files
from typing import TYPE_CHECKING, Never

from course.constants import (
    FlowSessionExpirationMode,
    ParticipationStatus,
)
from course.content import FlowSessionStartMode
from course.starlark.data import (
    FlowPageAccessRuleArgs,
    FlowPageAttempt,
    FlowPageId,
    FlowSession,
    FlowSessionAccessRuleArgs,
    FlowSessionStartRuleArgs,
    Participation,
)
from course.starlark.dataclasses import dataclass_to_starlark
from course.utils import FlowPageAccessMode, FlowSessionAccessMode


if TYPE_CHECKING:
    from collections.abc import Callable
    from enum import StrEnum

    from course.models import Course
    from course.starlark.module import StarlarkModule


_newline = "\n"
_classes: list[type] = [
    Participation,
    FlowSession,
    FlowPageAttempt,
    FlowPageId,
    FlowSessionStartRuleArgs,
    FlowSessionStartMode,
    FlowSessionAccessRuleArgs,
    FlowSessionAccessMode,
    FlowPageAccessRuleArgs,
    FlowPageAccessMode,
]

_enums: list[type[StrEnum]] = [
    ParticipationStatus,
    FlowSessionExpirationMode,
]


def str_enum_to_starlark(enum_tp: type[StrEnum]) -> str:
    name = enum_tp.__name__
    return f"{name} = enum({', '.join(repr(s) for s in enum_tp.__members__)})"


RELATE_GENERATED_STAR = f"""
load("relate/_core_types.star", "Timestamp")

{_newline.join(str_enum_to_starlark(cls) for cls in _enums)}

{_newline.join(dataclass_to_starlark(cls) for cls in _classes)}

PY_TYPE_MAP = {{
    {", ".join(f"'{cls.__name__}': {cls.__name__}" for cls in _classes)}
}}
"""

_RELATE_MODULE_CACHE: dict[str, StarlarkModule] = {}


class StarlarkError(RuntimeError):
    pass


def error(message: str) -> Never:
    raise StarlarkError(message)


def parse_date_spec(course: Course | None, datespec: str):
    if course is not None:
        from course.datespec import parse_date_spec_or_none
        dt = parse_date_spec_or_none(course, datespec)
        return dt.timestamp() if dt is not None else dt
    else:
        return None


def has_prairietest_access(
            course: Course | None,
            user_uid: str | None,
            user_uin: str | None,
            exam_uuid: str,
            now: float,
            ip_address: str,
        ) -> bool:
    if course is not None:
        from prairietest.utils import has_access_to_exam
        return bool(has_access_to_exam(
              course, user_uid=user_uid, user_uin=user_uin,
              exam_uuid=exam_uuid,
              now=datetime.fromtimestamp(now),
              ip_address=ipaddress.ip_address(ip_address),
          ))
    else:
        return False


def get_relate_starlark_module(name: str) -> StarlarkModule:
    try:
        return _RELATE_MODULE_CACHE[name]
    except KeyError:
        pass

    extra_functions: dict[str, Callable[..., object]] = {}
    if name == "relate/_builtins.star":
        code = ""
        extra_functions = {
            "error": error,
            "parse_date_spec": parse_date_spec,
            "has_prairietest_access": has_prairietest_access,
        }
    elif name == "relate/_generated.star":
        code = RELATE_GENERATED_STAR
    else:
        lib_file = files("course.starlark.lib")
        parts = name.split("/")
        if parts[0] != "relate":
            raise FileNotFoundError(name)

        for part in parts[1:]:
            if part == "..":
                raise ValueError("'..' not allowed in library imports")
            lib_file = lib_file / part
        code = lib_file.read_text()

    def load_func(name: str):
        return get_relate_starlark_module(name)

    from course.starlark.module import make_starlark_module
    mod = make_starlark_module(name, code, load_func,
            extra_functions=extra_functions)

    _RELATE_MODULE_CACHE[name] = mod
    return mod
