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

import dataclasses
import re
from dataclasses import fields
from enum import StrEnum
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:

    from _typeshed import DataclassInstance


def type_to_starlark(tp: type[object] | str | Any) -> str:
    return (str(tp)
        .replace("StarlarkTimestamp", "Timestamp")
        .replace("IdentifierStr", "str")
    )


def camel_to_snake_case(s: str):
    # https://stackoverflow.com/a/1176023
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def dataclass_to_starlark_name(dc: type[DataclassInstance]) -> str:
    return dc.__name__


def dataclass_to_starlark_type(dc: type[DataclassInstance]) -> str:
    name = dataclass_to_starlark_name(dc)
    field_decls = [
        f"    {fld.name}={type_to_starlark(fld.type)},"
        for fld in fields(dc)
    ]
    field_decls_str = "\n".join(field_decls) + "\n"
    return f"{name} = record(\n{field_decls_str})"


def dataclass_to_starlark_marshal(dc: type[DataclassInstance]):
    name = dataclass_to_starlark_name(dc)
    dict_parts = [f"'{fld.name}': obj.{fld.name}" for fld in fields(dc)]
    return (
        f"def marshal_{camel_to_snake_case(name)}(obj: {name}) -> {name}:\n"
        f"   return {{{', '.join(dict_parts)}}}"
    )


def dataclass_to_starlark_unmarshal(dc: type[DataclassInstance]):
    name = dataclass_to_starlark_name(dc)
    init_kwargs = [f"{fld.name}=obj['{fld.name}']" for fld in fields(dc)]
    return (
        f"def unmarshal_{camel_to_snake_case(name)}"
        f"(obj: dict[str, typing.Any]) -> {name}:\n"
        f"   return {name}({', '.join(init_kwargs)})"
    )


def value_to_starlark(obj: object) -> str:
    if isinstance(obj, StrEnum):
        return f"{type(obj).__name__}({str(obj)!r})"

    return repr(obj)


def dataclass_to_starlark_constructor(dc: type[DataclassInstance]):
    name = dataclass_to_starlark_name(dc)
    init_kwargs = [f"{fld.name}={fld.name}" for fld in fields(dc)]
    field_decls = [
        f"{fld.name}: {type_to_starlark(fld.type)}"
        if fld.default is dataclasses.MISSING else
        f"{fld.name}: {type_to_starlark(fld.type)} = {value_to_starlark(fld.default)}"
        for fld in fields(dc)
    ]
    return (
        f"def make_{camel_to_snake_case(name)}"
        f"(*, {', '.join(field_decls)}) -> {name}:\n"
        f"   return {name}({', '.join(init_kwargs)})"
    )


def dataclass_to_starlark(dc: type[DataclassInstance]) -> str:
    return (
        f"{dataclass_to_starlark_type(dc)}\n"

        # Marshalling seems generally unnecessary; to-JSON conversion of records
        # appears to do the trick just fine.
        # f"{dataclass_to_starlark_marshal(dc)}\n"

        f"{dataclass_to_starlark_unmarshal(dc)}\n"
        f"{dataclass_to_starlark_constructor(dc)}\n"
    )
