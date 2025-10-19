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

from dataclasses import dataclass
from functools import partial
from pprint import pformat
from typing import TYPE_CHECKING, TypeVar

import starlark as sl
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext as _
from lru import LRU

from course.repo import Repo_ish, RevisionID_ish, get_repo_blob
from course.starlark.builtin import get_relate_starlark_module
from relate.utils import format_datetime_local, local_now


if TYPE_CHECKING:
    from collections.abc import Callable, Hashable, Mapping, Sequence

    from pydantic import TypeAdapter

    from course.models import Course


def relate_starlark_dialect():
    dialect = sl.Dialect.extended()
    dialect.enable_types = sl.DialectTypes.ENABLE
    dialect.enable_f_strings = True
    # FIXME Enable once we depend on sl-rust 2025.2.6
    # dialect.enable_positional_only_arguments = True
    dialect.enable_keyword_only_arguments = True
    dialect.enable_load_reexport = True
    return dialect


def relate_starlark_globals():
    return sl.Globals.standard().extended_by([
            sl.LibraryExtension.EnumType,
            sl.LibraryExtension.RecordType,
            sl.LibraryExtension.Partial,
            sl.LibraryExtension.Typing,
         ])


@dataclass(frozen=True)
class StarlarkAst:
    module: sl.AstModule
    lint: Sequence[sl.Lint]


@dataclass(frozen=True)
class StarlarkModule:
    module: sl.FrozenModule
    interface: sl.Interface
    lint: Sequence[sl.Lint]
    load_lint: Mapping[str, Sequence[sl.Lint]]


@dataclass(frozen=True)
class StarlarkModuleWithSource(StarlarkModule):
    source: str


def str_lint(lnt: sl.Lint):
    return (
        f"{lnt.resolved_location.file}: {lnt.resolved_location.span.begin.line+1}: "
        f"{lnt.severity} [{lnt.short_name}]: {lnt.problem}")


def parse_starlark(filename: str, code: str) -> StarlarkAst:
    import starlark as sl
    try:
        ast = sl.parse(filename, code, relate_starlark_dialect())
    except Exception as e:
        raise ValueError(f"unable to parse Starlark code:\n{e}")
    lint = ast.lint()
    warning_severities = [sl.EvalSeverity.Advice, sl.EvalSeverity.Disabled]
    bad_lint = [
            lnt for lnt in lint
            if lnt.severity not in warning_severities
    ]
    warn_lint = [
            lnt for lnt in lint
            if lnt.severity in warning_severities
    ]

    if bad_lint:
        lint_str = "\n".join(str_lint(lnt) for lnt in bad_lint)
        raise ValueError(f"has lint:\n{lint_str}")

    return StarlarkAst(ast, warn_lint)


def make_starlark_module(
            name: str,
            source: str,
            load_func: Callable[[str], StarlarkModule],
            extra_functions: Mapping[str, Callable[..., object]] | None = None,
        ) -> StarlarkModule:
    if extra_functions is None:
        extra_functions = {}

    ast = parse_starlark(name, source)
    loads = {
            ld.module_id: load_func(ld.module_id)
            for ld in ast.module.loads()}

    load_ifaces = {name: mod.interface for name, mod in loads.items()}
    errs, iface, _ = ast.module.typecheck(relate_starlark_globals(), load_ifaces)
    if errs:
        err_str = "\n".join(f"{err.span}: {err}" for err in errs)
        raise ValueError(f"has type errors:\n{err_str}")

    def fm_load_func(name: str):
        return load_func(name).module

    mod = sl.Module()
    for name, clbl in extra_functions.items():
        mod.add_callable(name, clbl)

    sl.eval(mod, ast.module, relate_starlark_globals(), sl.FileLoader(fm_load_func))

    load_lint = {name: mod.lint for name, mod in loads.items()}

    return StarlarkModule(mod.freeze(), iface, lint=ast.lint, load_lint=load_lint)


_MODULE_FROM_REPO_CACHE: dict[Hashable, StarlarkModule] = {}


def _load_func(repo: Repo_ish, commit_sha: RevisionID_ish, name: str):
    if name.startswith("relate/"):
        return get_relate_starlark_module(name)
    else:
        return get_starlark_module_from_repo(repo, commit_sha, name)


def get_starlark_module_from_repo(
            repo: Repo_ish,
            commit_sha: RevisionID_ish,
            name: str,
        ) -> StarlarkModule:
    key = (repo.controldir(), commit_sha, name)
    try:
        return _MODULE_FROM_REPO_CACHE[key]
    except KeyError:
        pass

    try:
        blob: bytes = get_repo_blob(repo, name, commit_sha).data
    except ObjectDoesNotExist as err:
        raise FileNotFoundError(f"{name}: {err}")
    mod = make_starlark_module(
           name, blob.decode("utf-8"),
           partial(_load_func, repo, commit_sha))

    _MODULE_FROM_REPO_CACHE[key] = mod
    return mod


_MODULE_FROM_SOURCE_CACHE: LRU[Hashable, StarlarkModuleWithSource] = LRU(500)


def get_starlark_module_from_source(
            repo: Repo_ish,
            commit_sha: RevisionID_ish,
            name: str | None,
            source: str,
            extra_functions: Mapping[str, Callable[..., object]] | None = None,
        ) -> StarlarkModuleWithSource:
    use_cache = not extra_functions

    key = (repo.controldir(), commit_sha, source)
    if use_cache:
        try:
            return _MODULE_FROM_SOURCE_CACHE[key]
        except KeyError:
            pass

    if name is None:
        name = "<inline code>"
    mod = make_starlark_module(
           name, source,
           partial(_load_func, repo, commit_sha),
           extra_functions)

    smod = StarlarkModuleWithSource(
        module=mod.module,
        interface=mod.interface,
        lint=mod.lint,
        load_lint=mod.load_lint,
        source=source,
    )

    if use_cache:
        _MODULE_FROM_SOURCE_CACHE[key] = smod

    return smod


ModelT = TypeVar("ModelT")


def notify_of_error(
            course: Course,
            source: str,
            func_name: str,
            args: tuple[object, ...],
            kwargs: dict[str, object],
            exc: Exception,
        ) -> None:
    from django.conf import settings
    from django.core.mail import EmailMessage

    from relate.utils import render_email_template

    message = render_email_template(
        "course/broken-starlark.txt", {
            "site": settings.RELATE_BASE_URL,
            "course": course,
            "func_name": func_name,
            "source": source,
            "error_message": f"{type(exc).__name__}: {exc!s}",
            "pprint_args": pformat(args),
            "pprint_kwargs": pformat(kwargs),
            "time": format_datetime_local(local_now())
        })
    msg = EmailMessage(
                 f"[{course.identifier}] {_('Starlark code failed')}",
                    message,
                    settings.ROBOT_EMAIL_FROM,
                    [course.notify_email])

    from relate.utils import get_outbound_mail_connection
    msg.connection = get_outbound_mail_connection("robot")
    msg.send()


def call_and_notify_on_error(
            course: Course | None,
            smod: StarlarkModuleWithSource,
            func_name: str,
            retval_ta: TypeAdapter[ModelT],
            *args: object,
            **kwargs: object,
        ) -> ModelT:
    try:
        retval = smod.module.call(func_name, *args, **kwargs)
    except Exception as e:
        if course is not None:
            notify_of_error(course, smod.source, func_name, args, kwargs, e)
        raise

    try:
        return retval_ta.validate_python(retval)
    except Exception as e:
        if course is not None:
            notify_of_error(course, smod.source, func_name, args, kwargs, e)
        raise
