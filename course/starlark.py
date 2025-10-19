from __future__ import annotations


__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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


from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, TypeAlias

import starlark as sl
from pydantic import AfterValidator

from course.repo import Repo_ish, RevisionID_ish, get_repo_blob
from course.validation import ValidationContext, get_validation_context


if TYPE_CHECKING:
    from collections.abc import Hashable, Sequence

    from pydantic import ValidationInfo


def relate_starlark_dialect():
    dialect = sl.Dialect.extended()
    dialect.enable_types = sl.DialectTypes.ENABLE
    return dialect


def relate_starlark_globals():
    return sl.Globals.standard().extended_by([
            sl.LibraryExtension.EnumType,
            sl.LibraryExtension.RecordType,
            sl.LibraryExtension.Partial,
            sl.LibraryExtension.Typing,
         ])


# @dataclass(frozen=True)
# class UseCaseTest:


# class StarlarkCodeUseCase(ABC):
    # def test_cases

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
    warning_severities = ["Disabled", "Advice"]
    bad_lint = [
            lnt for lnt in lint
            # FIXME https://github.com/inducer/starlark-pyo3/pull/36
            if str(lnt.severity) not in warning_severities
    ]
    warn_lint = [
            lnt for lnt in lint
            # FIXME https://github.com/inducer/starlark-pyo3/pull/36
            if str(lnt.severity) in warning_severities
    ]

    if bad_lint:
        lint_str = "\n".join(str_lint(lnt) for lnt in bad_lint)
        raise ValueError(f"has lint:\n{lint_str}")

    return StarlarkAst(ast, warn_lint)


def _make_starlark_module(
            repo: Repo_ish,
            commit_sha: RevisionID_ish,
            name: str,
            source: str,
        ) -> StarlarkModule:
    ast = parse_starlark(name, source)
    loads = {
            ld.module_id: get_starlark_module_from_repo(repo, commit_sha, ld.module_id)
            for ld in ast.module.loads()}

    load_ifaces = {name: mod.interface for name, mod in loads.items()}
    errs, iface, _ = ast.module.typecheck(relate_starlark_globals(), load_ifaces)
    if errs:
        err_str = "\n".join(f"{err.span}: {err}" for err in errs)
        raise ValueError(f"has type errors:\n{err_str}")

    def load_func(name: str) -> sl.FrozenModule:
        return get_starlark_module_from_repo(repo, commit_sha, name).module

    mod = sl.Module()
    sl.eval(mod, ast.module, relate_starlark_globals(), sl.FileLoader(load_func))

    load_lint= {name: mod.lint for name, mod in loads.items()}

    return StarlarkModule(mod.freeze(), iface, lint=ast.lint, load_lint=load_lint)


_MODULE_FROM_REPO_CACHE: dict[Hashable, StarlarkModule] = {}


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

    blob: bytes = get_repo_blob(repo, name, commit_sha).data
    mod = _make_starlark_module(repo, commit_sha, name, blob.decode("utf-8"))

    _MODULE_FROM_REPO_CACHE[key] = mod
    return mod


_MODULE_FROM_SOURCE_CACHE: dict[Hashable, StarlarkModule] = {}


def get_starlark_module_from_source(
            repo: Repo_ish,
            commit_sha: RevisionID_ish,
            name: str,
            source: str,
        ) -> StarlarkModule:
    key = (repo.controldir(), commit_sha, source)
    try:
        return _MODULE_FROM_SOURCE_CACHE[key]
    except KeyError:
        pass

    mod = _make_starlark_module(repo, commit_sha, name, source)

    _MODULE_FROM_SOURCE_CACHE[key] = mod
    return mod


def validate_starlark_code(s: str, info: ValidationInfo):
    vctx = get_validation_context(info)

    get_starlark_module_from_source(vctx.repo, vctx.commit_sha, str(vctx._location), s)  # pyright: ignore[reportPrivateUsage]


StarlarkCode: TypeAlias = Annotated[
        str,
        AfterValidator(validate_starlark_code)]
