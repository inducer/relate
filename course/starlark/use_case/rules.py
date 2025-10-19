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

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from typing_extensions import override

from course.starlark.data import (
    FlowSession as StarlarkFlowSession,
    Participation as StarlarkParticipation,
)
from course.starlark.use_case import StarlarkUseCase


if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from course.models import Course, FlowSession, Participation
    from course.repo import Repo_ish, RevisionID_ish
    from course.starlark.module import StarlarkModule


START_RULES_LEADER = """
load("relate/rules.star", "unmarshal_participation", "unmarshal_flow_session",
    "FlowSessionExpirationMode", "Timestamp", "Participation", "FlowSession",
    "FlowSessionStartMode", "start_mode")
"""


START_RULES_TRAILER = """
def wrap_rule(
            now: Timestamp,
            participation: dict[str, typing.Any] | None,
            sessions: list[dict[str, typing.Any]],
            facilities: list[str],
            has_matching_exam_ticket: bool,
        ):
    return rule(
            now=now,
            participation=(unmarshal_participation(participation)
                if participation != None else None),
            sessions=[unmarshal_flow_session(sess) for sess in sessions],
            facilities=facilities,
            has_matching_exam_ticket=has_matching_exam_ticket)
"""


class FlowStartRulesUseCase(StarlarkUseCase):
    @override
    def get_module(self,
                repo: Repo_ish,
                commit_sha: RevisionID_ish,
                location: str | None,
                code: str
            ) -> StarlarkModule:
        wrapped_code = f"{START_RULES_LEADER}\n{code}\n{START_RULES_TRAILER}"
        from course.starlark.module import get_starlark_module_from_source
        return get_starlark_module_from_source(
                    repo, commit_sha, location, wrapped_code)

    def __call__(self,
                mod: StarlarkModule,
                now: datetime,
                participation: Participation | StarlarkParticipation | None,
                sessions: Sequence[FlowSession | StarlarkFlowSession],
                facilities: Collection[str],
                has_matching_exam_ticket: bool,
            ):
        from course.content import flow_session_start_mode_ta
        return flow_session_start_mode_ta.validate_python(
            mod.module.call("wrap_rule",
                now=now.timestamp(),
                participation=StarlarkParticipation.relate_to_json(participation)
                    if participation is not None else None,
                sessions=[
                    StarlarkFlowSession.relate_to_json(sess) for sess in sessions],
                facilities=facilities,
                has_matching_exam_ticket=has_matching_exam_ticket))

    @override
    def run_tests(self, mod: StarlarkModule, course: Course | None):
        now = datetime.now()
        hour = timedelta(hours=1)

        self(mod, now, None, [], [], False)
        if not course:
            participation = StarlarkParticipation(
                id=1,
                username="johndoe@illinois.edu",
                email="johndoe@illinois.edu",
                institutional_id=None,
                tags=["online"],
                roles=["student"],
            )
            self(mod, datetime.now(), participation, [], [], False)
            self(mod, datetime.now(), participation, [], ["cbtf"], False)
            # sess_1 = StarlarkFlowSession(
            #     id=1,
            #     start_time=now - hour,

            # )
