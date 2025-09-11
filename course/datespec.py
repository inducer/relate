"""
.. autoclass:: Datespec
"""
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

import datetime
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Literal,
    TypeAlias,
    cast,
)

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils.timezone import now
from django.utils.translation import gettext as _
from pydantic import ValidationInfo, model_serializer, model_validator
from typing_extensions import override

from course.validation import content_dataclass, get_validation_context


if TYPE_CHECKING:
    from course.models import Course
    from course.validation import (
        ValidationContext,
    )


# {{{ datespec processing

DATE_RE = re.compile(r"^([0-9]+)\-([01][0-9])\-([0-3][0-9])$")
TRAILING_NUMERAL_RE = re.compile(r"^(.*)\s+([0-9]+)$")

END_PREFIX = "end:"


class InvalidDatespec(ValueError):
    datespec: object

    def __init__(self, datespec: object):
        ValueError.__init__(self, str(datespec))
        self.datespec = datespec


class DatespecPostprocessor(ABC):
    @classmethod
    @abstractmethod
    def parse(cls, s: str) -> tuple[str, DatespecPostprocessor | None]:
        ...

    @abstractmethod
    def apply(self, dtm: datetime.datetime) -> datetime.datetime:
        ...


AT_TIME_RE = re.compile(r"^(.*)\s*@\s*([0-2]?[0-9])\:([0-9][0-9])\s*$")


@dataclass(frozen=True)
class AtTimePostprocessor(DatespecPostprocessor):
    hour: int
    minute: int
    second: int = 0

    @classmethod
    @override
    def parse(cls, s: str):
        match = AT_TIME_RE.match(s)
        if match is not None:
            hour = int(match.group(2))
            minute = int(match.group(3))

            if not (0 <= hour < 24):
                raise InvalidDatespec(s)

            if not (0 <= minute < 60):
                raise InvalidDatespec(s)

            return match.group(1), AtTimePostprocessor(hour, minute)
        else:
            return s, None

    @override
    def apply(self, dtm: datetime.datetime) -> datetime.datetime:
        from zoneinfo import ZoneInfo
        server_tz = ZoneInfo(settings.TIME_ZONE)

        return dtm.astimezone(server_tz).replace(
                    hour=self.hour,
                    minute=self.minute,
                    second=self.second)


PLUS_DELTA_RE = re.compile(r"^(.*)\s*([+-])\s*([0-9]+)\s+"
    r"(week|day|hour|minute)s?$")


PeriodType: TypeAlias = Literal["week", "day", "hour", "minute"]


@dataclass(frozen=True)
class PlusDeltaPostprocessor(DatespecPostprocessor):
    count: int
    period: PeriodType

    @classmethod
    @override
    def parse(cls, s: str):
        match = PLUS_DELTA_RE.match(s)
        if match is not None:
            count = int(match.group(3))
            if match.group(2) == "-":
                count = -count
            period = match.group(4)

            return match.group(1), PlusDeltaPostprocessor(
                                count, cast("PeriodType", period))
        else:
            return s, None

    @override
    def apply(self, dtm: datetime.datetime):
        if self.period == "week":
            d = datetime.timedelta(weeks=self.count)
        elif self.period == "day":
            d = datetime.timedelta(days=self.count)
        elif self.period == "hour":
            d = datetime.timedelta(hours=self.count)
        elif self.period == "minute":
            d = datetime.timedelta(minutes=self.count)
        else:
            raise AssertionError()

        return dtm + d


DATESPEC_POSTPROCESSORS: list[type[DatespecPostprocessor]] = [
        AtTimePostprocessor,
        PlusDeltaPostprocessor,
        ]


def parse_date_spec(
        course: Course | None,
        datespec: str | datetime.date | datetime.datetime,
        vctx: ValidationContext | None = None,
        ) -> datetime.datetime:
    orig_datespec = datespec

    def localize_if_needed(d: datetime.datetime) -> datetime.datetime:
        if d.tzinfo is None:
            from relate.utils import localize_datetime
            return localize_datetime(d)
        else:
            return d

    if isinstance(datespec, datetime.datetime):
        return localize_if_needed(datespec)
    if isinstance(datespec, datetime.date):
        return localize_if_needed(
                datetime.datetime.combine(datespec, datetime.time.min))

    datespec_str = datespec.strip()

    # {{{ parse postprocessors

    postprocs: list[DatespecPostprocessor] = []
    while True:
        parsed_one = False
        for pp_class in DATESPEC_POSTPROCESSORS:
            datespec_str, postproc = pp_class.parse(datespec_str)
            if postproc is not None:
                parsed_one = True
                postprocs.insert(0, postproc)
                break

        datespec_str = datespec_str.strip()

        if not parsed_one:
            break

    # }}}

    def apply_postprocs(dtime: datetime.datetime) -> datetime.datetime:
        for postproc in postprocs:
            dtime = postproc.apply(dtime)

        return dtime

    match = DATE_RE.match(datespec_str)
    if match:
        res_date = datetime.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)))
        result = localize_if_needed(
                datetime.datetime.combine(res_date, datetime.time.min))
        return apply_postprocs(result)

    is_end = datespec_str.startswith(END_PREFIX)
    if is_end:
        datespec_str = datespec_str[len(END_PREFIX):]

    match = TRAILING_NUMERAL_RE.match(datespec_str)
    if match:
        # event with numeral

        event_kind = match.group(1)
        ordinal: int | None = int(match.group(2))

    else:
        # event without numeral

        event_kind = datespec_str
        ordinal = None

    from course.validation import validate_identifier
    validate_identifier(event_kind)

    if course is None:
        return now()

    from course.models import Event

    try:
        event_obj = Event.objects.get(
            course=course,
            kind=event_kind,
            ordinal=ordinal)

    except ObjectDoesNotExist:
        if vctx is not None:
            vctx.add_warning(
                    _("Unrecognized date/time specification: '%s' "
                    "(interpreted as 'now'). "
                    "You should add an event with this name.")
                    % orig_datespec)
        return now()

    if is_end:
        if event_obj.end_time is not None:
            result = event_obj.end_time
        else:
            result = event_obj.time
            if vctx is not None:
                vctx.add_warning(
                        _("event '%s' has no end time, using start time instead")
                        % orig_datespec)

    else:
        result = event_obj.time

    return apply_postprocs(result)

# }}}


@content_dataclass()
class Datespec:
    # We can't normalize these to a datetime right away, because previous behavior
    # in Relate relied on these being evaluated *after* the 'now' timestamp
    # in the flow to which they will be compared. That's janky, and nothing
    # that anyone should have ever relied on, but for compatibilities sake,
    # here we are.
    value: str | datetime.date | datetime.datetime

    @model_validator(mode="before")
    @classmethod
    def check_validity(cls, data: object, info: ValidationInfo) -> object:
        if isinstance(data, datetime.date | datetime.datetime):
            # This allows context-less creation of Datespecs in the tests
            parse_date_spec(None, data, None)
            return {"value": data}

        if isinstance(data, str | datetime.date | datetime.datetime):
            vctx = get_validation_context(info)
            parse_date_spec(vctx.course, data, vctx)
            return {"value": data}

        return data

    def eval(self, course: Course):
        return parse_date_spec(course, self.value)

    @model_serializer
    def ser_model(self) -> object:
        return self.value
