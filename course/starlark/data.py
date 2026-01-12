from __future__ import annotations

from annotated_types import Ge
from pydantic import AllowInfNan

from course.validation import PointCount


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
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, Self, TypeAlias

from pytools import not_none

from course.constants import FlowSessionExpirationMode


if TYPE_CHECKING:
    from _typeshed import ConvertibleToFloat

    from course.models import (
        FlowPageData,
        FlowPageVisit,
        FlowSession as FlowSessionModel,
        Participation as ParticipationModel,
    )


Opaque: TypeAlias = object


def float_or_none(v: ConvertibleToFloat | None) -> float | None:
    if v is None:
        return v
    else:
        return float(v)


@dataclass(frozen=True, kw_only=True)
class Participation:
    """
    .. autoattribute:: id
    .. autoattribute:: username
    .. autoattribute:: email
    .. autoattribute:: institutional_id
    .. autoattribute:: tags
    .. autoattribute:: roles
    .. autoattribute:: time_factor
    """
    id: int
    username: str
    email: str
    institutional_id: str | None
    tags: list[str]
    roles: list[str]
    time_factor: float = 1.0

    @classmethod
    def from_relate(cls, part: ParticipationModel | Self):
        if isinstance(part, Participation):
            return part

        # Mypy can't figure this out on its own:
        from course.models import Participation as ParticipationModel
        assert isinstance(part, ParticipationModel)

        return cls(
            id=part.id,
            username=part.user.username,
            email=part.user.email,
            institutional_id=(
                part.user.institutional_id
                if part.user.institutional_id_verified else None
            ),
            tags=[tag.name for tag in part.tags.all()],
            roles=[role.identifier for role in part.roles.all()],
            time_factor=float(part.time_factor),
        )


@dataclass(frozen=True, kw_only=True)
class FlowSession:
    """
    .. autoattribute:: id
    .. autoattribute:: start_time
    .. autoattribute:: completion_time
    .. autoattribute:: last_activity
    .. autoattribute:: expiration_mode
    .. autoattribute:: access_rules_tag
    .. autoattribute:: points
    .. autoattribute:: max_points
    """
    id: int
    start_time: datetime
    completion_time: datetime | None
    last_activity: datetime
    expiration_mode: FlowSessionExpirationMode | None
    access_rules_tag: str | None
    points: float | None
    max_points: float | None

    @classmethod
    def from_relate(cls, sess: FlowSessionModel | Self):
        if isinstance(sess, FlowSession):
            return sess

        # Mypy can't figure this out on its own:
        from course.models import FlowSession as FlowSessionModel
        assert isinstance(sess, FlowSessionModel)

        last_activity = sess.last_activity()
        if last_activity is None:
            last_activity = sess.start_time

        return cls(
            id=sess.id,
            start_time=sess.start_time,
            completion_time=sess.completion_time,
            last_activity=last_activity,
            expiration_mode=FlowSessionExpirationMode(sess.expiration_mode)
                if sess.expiration_mode is not None else None,
            access_rules_tag=sess.access_rules_tag,
            points=float_or_none(sess.points),
            max_points=float_or_none(sess.max_points),
        )


@dataclass(frozen=True, kw_only=True)
class FlowSessionStartRuleArgs:
    """
    .. autoattribute:: course
    .. autoattribute:: now
    .. autoattribute:: participation
    .. autoattribute:: flow_id
    .. autoattribute:: sessions
    .. autoattribute:: facilities
    .. autoattribute:: has_matching_exam_ticket
    """
    course: Opaque
    now: datetime
    participation: Participation | None
    flow_id: str
    sessions: list[FlowSession]
    facilities: list[str]
    has_matching_exam_ticket: bool


@dataclass(frozen=True, kw_only=True)
class FlowPageAttempt:
    """
    .. autoattribute:: time
    """
    time: datetime

    @classmethod
    def from_relate(cls, visit: FlowPageVisit | Self):
        if isinstance(visit, FlowPageAttempt):
            return visit

        # Mypy can't figure this out on its own:
        from course.models import FlowPageVisit
        assert isinstance(visit, FlowPageVisit)

        assert visit.is_submitted_answer

        return cls(
            time=visit.visit_time,
        )


@dataclass(frozen=True, kw_only=True)
class FlowPageId:
    """
    .. autoattribute:: type
    .. autoattribute:: group_id
    .. autoattribute:: page_id
    """
    @classmethod
    def from_relate(cls, page_data: FlowPageData | Self):
        if isinstance(page_data, FlowPageId):
            return page_data

        # Mypy can't figure this out on its own:
        from course.models import FlowPageData
        assert isinstance(page_data, FlowPageData)

        return cls(
            type=not_none(page_data.page_type),
            group_id=page_data.group_id,
            page_id=page_data.page_id,
        )

    type: str
    group_id: str
    page_id: str


@dataclass(frozen=True, kw_only=True)
class FlowSessionAccessRuleArgs:
    """
    .. autoattribute:: course
    .. autoattribute:: now
    .. autoattribute:: participation
    .. autoattribute:: flow_id
    .. autoattribute:: session
    .. autoattribute:: facilities
    .. autoattribute:: has_matching_exam_ticket
    """
    course: Opaque
    now: datetime
    participation: Participation | None
    flow_id: str
    session: FlowSession
    facilities: list[str]
    has_matching_exam_ticket: bool


@dataclass(frozen=True, kw_only=True)
class FlowPageAccessRuleArgs(FlowSessionAccessRuleArgs):
    """
    :show-inheritance:

    .. autoattribute:: page_id
    .. autoattribute:: attempts
    """
    page_id: FlowPageId | None
    attempts: list[FlowPageAttempt] | None


@dataclass(frozen=True, kw_only=True)
class FlowPageGrade:
    """
    .. autoattribute:: grade
    .. autoattribute:: message
    """
    grade: PointCount | None
    message: str | None


SessionPointCount = Annotated[
        float,
        AllowInfNan(False),
        Ge(0)]


@dataclass(frozen=True, kw_only=True)
class FlowSessionGrade:
    """
    .. autoattribute:: points
    .. autoattribute:: certain_points
    .. autoattribute:: possible_points
    .. autoattribute:: max_reachable_points
    .. autoattribute:: message
    """
    points: SessionPointCount | None
    """Non-None only if the final grade is available."""

    certain_points: SessionPointCount | None

    possible_points: SessionPointCount | None

    max_reachable_points: SessionPointCount | None
    """The maximum number of actually attainable points on the flow, subject
    to the grading rules, but independent of the particular page results.
    """

    message: str | None


@dataclass(frozen=True, kw_only=True)
class FlowGrade:
    """
    .. autoattribute:: points
    .. autoattribute:: message
    """
    points: PointCount | None
    message: str | None
