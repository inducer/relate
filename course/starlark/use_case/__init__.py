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

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from course.constants import (
    FlowSessionExpirationMode as FlowSessionExpirationMode,
    ParticipationStatus as ParticipationStatus,
)
from course.repo import (
    get_repo_blob as get_repo_blob,
)
from course.validation import IdentifierStr as IdentifierStr, get_validation_context


if TYPE_CHECKING:

    from pydantic import ValidationInfo

    from course.models import (
        Course,
        FlowSession as FlowSession,
        Participation as Participation,
    )
    from course.repo import (
        Repo_ish as Repo_ish,
        RevisionID_ish as RevisionID_ish,
    )
    from course.starlark.module import StarlarkModuleWithSource


class StarlarkUseCase(ABC):
    @abstractmethod
    def get_module(self,
                repo: Repo_ish,
                commit_sha: RevisionID_ish,
                location: str,
                code: str) -> StarlarkModuleWithSource:
        ...

    @abstractmethod
    def run_tests(self, mod: StarlarkModuleWithSource, course: Course | None):
        ...


def validate_starlark_code(use_case: StarlarkUseCase, code: str, info: ValidationInfo):
    vctx = get_validation_context(info)
    loc  = str(vctx.with_location(
              f"<code used for {type(use_case).__name__}>")._location)  # pyright: ignore[reportPrivateUsage]

    mod = use_case.get_module(vctx.repo, vctx.commit_sha, loc, code)
    use_case.run_tests(mod, vctx.course)
