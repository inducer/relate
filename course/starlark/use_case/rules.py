from __future__ import annotations

from course.starlark.dataclasses import to_starlark


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

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from typing_extensions import override

from course.starlark.data import (
    FlowSession as StarlarkFlowSession,
    FlowSessionStartRuleArgs,
    Participation as StarlarkParticipation,
)
from course.starlark.use_case import StarlarkUseCase


if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from course.models import Course, FlowSession, Participation
    from course.repo import Repo_ish, RevisionID_ish
    from course.starlark.module import StarlarkModule


START_RULES_LEADER = """
load("relate/types.star", "FlowSessionExpirationMode", "Timestamp",
    "Participation", "FlowSession", "parse_date_spec",
    _from_py="from_py", _PY_TYPE_MAP="PY_TYPE_MAP")
load("relate/rules.star",
    "FlowSessionStartMode", "FlowSessionStartRuleArgs", "has_prairietest_access")
"""


START_RULES_TRAILER = """
def wrap_rule(args: dict):
    return rule(_from_py(_PY_TYPE_MAP, args))
"""


class FlowStartRulesUseCase(StarlarkUseCase):
    @override
    def get_module(self,
                repo: Repo_ish,
                commit_sha: RevisionID_ish,
                location: str | None,
                code: str,
            ) -> StarlarkModule:
        wrapped_code = f"{START_RULES_LEADER}\n{code}\n{START_RULES_TRAILER}"
        from course.starlark.module import get_starlark_module_from_source
        return get_starlark_module_from_source(
                repo, commit_sha, location, wrapped_code)

    def __call__(self,
                mod: StarlarkModule,
                *,
                course: Course | None,
                now: datetime,
                participation: Participation | StarlarkParticipation | None,
                sessions: Sequence[FlowSession | StarlarkFlowSession],
                facilities: Collection[str],
                has_matching_exam_ticket: bool,
            ):
        from course.content import flow_session_start_mode_ta
        return flow_session_start_mode_ta.validate_python(
            mod.module.call("wrap_rule",
                to_starlark(FlowSessionStartRuleArgs(
                                course=course,
                                now=now,
                                participation=StarlarkParticipation.from_relate(participation)
                                    if participation is not None else None,
                                sessions=[
                                    StarlarkFlowSession.from_relate(sess)
                                    for sess in sessions],
                                facilities=list(facilities),
                                has_matching_exam_ticket=has_matching_exam_ticket))

                            ))

    @override
    def run_tests(self, mod: StarlarkModule, course: Course | None):
        now = datetime.now()
        hour = timedelta(hours=1)

        self(mod, course=None, now=now, participation=None, sessions=[],
             facilities=[], has_matching_exam_ticket=False)
        if not course:
            participation = StarlarkParticipation(
                id=1,
                username="johndoe@illinois.edu",
                email="johndoe@illinois.edu",
                institutional_id=None,
                tags=["online"],
                roles=["student"],
            )
            self(mod, course=None, now=now, participation=participation, sessions=[],
                 facilities=[], has_matching_exam_ticket=False)
            self(mod, course=None, now=now, participation=participation, sessions=[],
                 facilities=["cbtf"], has_matching_exam_ticket=False)
            # sess_1 = StarlarkFlowSession(
            #     id=1,
            #     start_time=now - hour,

            # )
