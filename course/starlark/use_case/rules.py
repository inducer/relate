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

from abc import ABC
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from typing_extensions import override

from course.starlark.data import (
    FlowPageAccessRuleArgs,
    FlowPageAttempt,
    FlowPageId,
    FlowSession as StarlarkFlowSession,
    FlowSessionAccessRuleArgs,
    FlowSessionStartRuleArgs,
    Participation as StarlarkParticipation,
)
from course.starlark.dataclasses import to_starlark
from course.starlark.use_case import StarlarkUseCase


if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from course.models import (
        Course,
        FlowPageData,
        FlowPageVisit,
        FlowSession,
        Participation,
    )
    from course.repo import Repo_ish, RevisionID_ish
    from course.starlark.module import StarlarkModuleWithSource


RULES_LEADER = """
load("relate/core.star", "Timestamp",
    _from_py="from_py", _PY_TYPE_MAP="PY_TYPE_MAP")
load("relate/course.star", "FlowSessionExpirationMode",
    "Participation", "FlowSession", "parse_date_spec")
load("relate/rules.star",
    "FlowSessionStartMode", "FlowSessionStartRuleArgs",
    "FlowSessionAccessRuleArgs", "FlowSessionAccessMode",
    "FlowPageAccessRuleArgs", "FlowPageAccessMode",
    "has_prairietest_access")
"""


RULES_TRAILER = """
def wrap_rule(args: dict):
    return rule(_from_py(_PY_TYPE_MAP, args))
"""


class FlowRulesUseCaseBase(StarlarkUseCase, ABC):
    @override
    def get_module(self,
                repo: Repo_ish,
                commit_sha: RevisionID_ish,
                location: str | None,
                code: str,
            ) -> StarlarkModuleWithSource:
        wrapped_code = f"{RULES_LEADER}\n{code}\n{RULES_TRAILER}"
        from course.starlark.module import get_starlark_module_from_source
        return get_starlark_module_from_source(
                repo, commit_sha, location, wrapped_code)


class FlowStartRulesUseCase(FlowRulesUseCaseBase):
    def __call__(self,
                mod: StarlarkModuleWithSource,
                *,
                course: Course | None,
                now: datetime,
                participation: Participation | StarlarkParticipation | None,
                flow_id: str,
                sessions: Sequence[FlowSession | StarlarkFlowSession],
                facilities: Collection[str],
                has_matching_exam_ticket: bool,
            ):
        from course.content import flow_session_start_mode_ta
        from course.starlark.module import call_and_notify_on_error
        return call_and_notify_on_error(
                        course, mod, "wrap_rule",
                        flow_session_start_mode_ta,
                        to_starlark(FlowSessionStartRuleArgs(
                                    course=course,
                                    now=now,
                                    participation=StarlarkParticipation.from_relate(participation)
                                        if participation is not None else None,
                                    flow_id=flow_id,
                                    sessions=[
                                        StarlarkFlowSession.from_relate(sess)
                                        for sess in sessions],
                                    facilities=list(facilities),
                                    has_matching_exam_ticket=has_matching_exam_ticket)))

    @override
    def run_tests(self, mod: StarlarkModuleWithSource, course: Course | None):
        now = datetime.now()
        hour = timedelta(hours=1)

        flow_id = "quiz-test"

        self(mod, course=None, now=now, participation=None,
             flow_id=flow_id, sessions=[],
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
            self(mod, course=None, now=now, participation=participation,
                 flow_id=flow_id, sessions=[],
                 facilities=[], has_matching_exam_ticket=False)
            self(mod, course=None, now=now, participation=participation,
                 flow_id=flow_id, sessions=[],
                 facilities=["cbtf"], has_matching_exam_ticket=False)
            # sess_1 = StarlarkFlowSession(
            #     id=1,
            #     start_time=now - hour,

            # )


class FlowSessionAccessRulesUseCase(FlowRulesUseCaseBase):
    def __call__(self,
                mod: StarlarkModuleWithSource,
                *,
                course: Course | None,
                now: datetime,
                participation: Participation | StarlarkParticipation | None,
                flow_id: str,
                session: FlowSession | StarlarkFlowSession,
                facilities: Collection[str],
                has_matching_exam_ticket: bool,
            ):
        from course.starlark.module import call_and_notify_on_error
        from course.utils import session_access_mode_ta
        return call_and_notify_on_error(
                        course, mod, "wrap_rule",
                        session_access_mode_ta,
                        to_starlark(FlowSessionAccessRuleArgs(
                                    course=course,
                                    now=now,
                                    participation=StarlarkParticipation.from_relate(participation)
                                        if participation is not None else None,
                                    flow_id=flow_id,
                                    session=StarlarkFlowSession.from_relate(session),
                                    facilities=list(facilities),
                                    has_matching_exam_ticket=has_matching_exam_ticket)))

    @override
    def run_tests(self, mod: StarlarkModuleWithSource, course: Course | None):
        pass


class FlowPageAccessRulesUseCase(FlowRulesUseCaseBase):
    def __call__(self,
                mod: StarlarkModuleWithSource,
                *,
                course: Course | None,
                now: datetime,
                participation: Participation | StarlarkParticipation | None,
                flow_id: str,
                session: FlowSession | StarlarkFlowSession,
                page_data: FlowPageData,
                attempts: Sequence[FlowPageVisit | FlowPageAttempt],
                facilities: Collection[str],
                has_matching_exam_ticket: bool,
            ):
        from course.starlark.module import call_and_notify_on_error
        from course.utils import page_access_mode_ta
        return call_and_notify_on_error(
                        course, mod, "wrap_rule",
                        page_access_mode_ta,
                        to_starlark(FlowPageAccessRuleArgs(
                                    course=course,
                                    now=now,
                                    participation=StarlarkParticipation.from_relate(participation)
                                        if participation is not None else None,
                                    flow_id=flow_id,
                                    session=StarlarkFlowSession.from_relate(session),
                                    page_id=FlowPageId.from_relate(page_data),
                                    attempts=[FlowPageAttempt.from_relate(vis)
                                        for vis in attempts],
                                    facilities=list(facilities),
                                    has_matching_exam_ticket=has_matching_exam_ticket)))

    @override
    def run_tests(self, mod: StarlarkModuleWithSource, course: Course | None):
        pass


class FlowPageGradingRulesUseCase(FlowRulesUseCaseBase):
    def __call__(self,
                mod: StarlarkModuleWithSource,
                *,
                course: Course | None,
                now: datetime,
                participation: Participation | StarlarkParticipation | None,
                flow_id: str,
                session: FlowSession | StarlarkFlowSession,
                page_data: FlowPageData,
                attempts: Sequence[FlowPageVisit | FlowPageAttempt]
            ) -> FlowPageGrade:
        pass

    @override
    def run_tests(self, mod: StarlarkModuleWithSource, course: Course | None):
        pass
