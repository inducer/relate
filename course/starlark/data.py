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
from typing import TYPE_CHECKING, Self, TypeAlias

from pydantic import TypeAdapter

from course.constants import FlowSessionExpirationMode


if TYPE_CHECKING:
    from course.models import (
        FlowSession as FlowSessionModel,
        Participation as ParticipationModel,
    )


StarlarkTimestamp: TypeAlias = float


@dataclass(frozen=True, kw_only=True)
class Participation:
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

    @classmethod
    def relate_to_json(cls, part: ParticipationModel | Self):
        return starlark_participation_ta.dump_python(cls.from_relate(part))


starlark_participation_ta = TypeAdapter(Participation)


@dataclass(frozen=True, kw_only=True)
class FlowSession:
    id: int
    start_time: StarlarkTimestamp
    completion_time: StarlarkTimestamp | None
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

        return cls(
            id=sess.id,
            start_time=sess.start_time.timestamp(),
            completion_time=sess.completion_time.timestamp()
                if sess.completion_time is not None else None,
            expiration_mode=FlowSessionExpirationMode(sess.expiration_mode)
                if sess.expiration_mode is not None else None,
            access_rules_tag=sess.access_rules_tag,
            points=float(sess.points) if sess.points is not None else None,
            max_points=float(sess.max_points) if sess.max_points is not None else None,
        )

    @classmethod
    def relate_to_json(cls, sess: FlowSessionModel | Self):
        return starlark_flow_session_ta.dump_python(cls.from_relate(sess))


starlark_flow_session_ta = TypeAdapter(FlowSession)
