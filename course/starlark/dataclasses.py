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
from dataclasses import Field, dataclass, field, fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from types import GenericAlias, NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    TypeVar,
    Union,  # pyright: ignore[reportDeprecated]
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

import starlark as sl
from django.db.models import Model


if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from _typeshed import DataclassInstance


def type_to_starlark(tp: type[object] | str | Any) -> str:
    if tp == datetime:
        return "Timestamp"
    if isinstance(tp, type) and issubclass(tp, Model):
        return "typing.Any"

    origin = get_origin(tp)
    if isinstance(tp, GenericAlias):
        args  = ", ".join(type_to_starlark(arg) for arg in get_args(tp))
        return f"{type_to_starlark(get_origin(tp))}[{args}]"
    elif origin is Union or origin is UnionType:  # pyright: ignore[reportDeprecated]
        return " | ".join(type_to_starlark(arg) for arg in get_args(tp))
    elif tp == NoneType:
        return "None"
    elif tp is object:
        return "typing.Any"
    elif isinstance(tp, type):
        result = tp.__name__
        if result == "Set":
            return "list"
    else:
        return str(tp)

    return (result
        .replace("StarlarkTimestamp", "Timestamp")
        .replace("IdentifierStr", "str")
    )


def camel_to_snake_case(s: str):
    # https://stackoverflow.com/a/1176023
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def dataclass_to_starlark_name(dc: type[DataclassInstance]) -> str:
    return dc.__name__


def value_to_starlark(obj: object) -> str:
    if isinstance(obj, StrEnum):
        return f"{type(obj).__name__}({str(obj)!r})"

    return repr(obj)


def field_to_starlark(field: Field[object], type_hint: Any):
    tp = type_to_starlark(type_hint)
    if field.default is dataclasses.MISSING:
        return tp
    else:
        return f"field({tp}, {value_to_starlark(field.default)})"


def dataclass_to_starlark(dc: type[DataclassInstance]) -> str:
    type_hints = get_type_hints(dc)
    name = dataclass_to_starlark_name(dc)
    field_decls = [
        f"    {fld.name}={field_to_starlark(fld, type_hint=type_hints[fld.name])},"
        for fld in fields(dc)
    ]
    field_decls_str = "\n".join(field_decls) + "\n"
    return f"{name} = record(\n{field_decls_str})"


T = TypeVar("T")


@dataclass(frozen=True)
class ToStarlarkConverter:
    _type_to_converter: dict[
            type,
            Callable[[ToStarlarkConverter, object], object]
        ] = field(default_factory=dict)

    def __post_init__(self):
        def convert_list(
                    conv: ToStarlarkConverter,
                    obj: Sequence[object],
                ) -> list[object]:
            return [conv(li) for li in obj]
        self.register_type(list, convert_list)
        self.register_type(tuple, convert_list)

        self.register_type(NoneType, lambda _conv, obj: obj)
        self.register_type(str, lambda _conv, obj: obj)
        self.register_type(int, lambda _conv, obj: obj)
        self.register_type(float, lambda _conv, obj: obj)
        self.register_type(datetime, lambda _conv, dt: dt.timestamp())
        self.register_type(Model, lambda _conv, obj: sl.OpaquePythonObject(obj))

    def register_type(self,
                      tp: type[T],
                      converter: Callable[[ToStarlarkConverter, T], object]):
        if tp in self._type_to_converter:
            raise ValueError(f"converter for type '{tp}' already registered")
        self._type_to_converter[tp] = cast(
                        "Callable[[ToStarlarkConverter, object], object]",
                        converter)

    def __call__(self, obj: object) -> object:
        if is_dataclass(obj):
            return {
                "_record_type": type(obj).__name__,
                "fields": {fld.name: self(getattr(obj, fld.name))
                    for fld in fields(obj)}
            }
        for tp in type(obj).__mro__:
            converter = self._type_to_converter.get(tp)
            if converter is not None:
                return converter(self, obj)

        raise ValueError(f"unable to convert {type(obj)}")


to_starlark = ToStarlarkConverter()
