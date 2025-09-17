# pyright: reportUninitializedInstanceVariable=none

from __future__ import annotations

from django.utils.safestring import SafeString, mark_safe


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
import html.parser as html_parser
import os
import re
import sys
from collections.abc import Set
from dataclasses import dataclass, field
from itertools import starmap
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Self,
    TypeVar,
    cast,
)
from xml.etree.ElementTree import Element, tostring

import dulwich
import dulwich.objects
import dulwich.repo
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ObjectDoesNotExist
from django.urls import NoReverseMatch
from django.utils.timezone import now
from django.utils.translation import gettext as _
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor
from pydantic import (
    AfterValidator,
    EmailStr,
    Field,
    PositiveInt,
    StringConstraints,
    TypeAdapter,
    ValidationInfo,
    model_validator,
)
from typing_extensions import deprecated, override
from yaml import safe_load as load_yaml

from course.constants import (
    ATTRIBUTES_FILENAME,
    FlowPermission,
    FlowRuleKind,
    FlowSessionExpirationMode,
    GradeAggregationStrategy,
)
from course.page.base import PageBase  # noqa: TC001
from course.validation import (
    Blob_ish,
    Datespec,
    EventStr,
    FacilityStr,
    FileSystemFakeRepo,
    FileSystemFakeRepoFile,
    FileSystemFakeRepoTree,
    IdentifierStr,
    Markup,
    ParticipationRoleStr,
    ParticipationTagStr,
    ValidationContext,
    content_dataclass,
    get_validation_context,
    validate_nonempty,
)
from relate.utils import SubdirRepoWrapper


if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Mapping, Set

    from course.models import Course, Participation
    from course.validation import (
        Tree_ish,
    )
    from relate.utils import Repo_ish


T = TypeVar("T")
Date_ish = datetime.datetime | datetime.date

ModelT = TypeVar("ModelT")


CACHE_KEY_ROOT = "py4"


# {{{ chunks and static pages

@content_dataclass()
class ChunkRulesDesc:
    if_has_role: frozenset[ParticipationRoleStr] = Field(default_factory=frozenset)
    if_before: Datespec | None = None
    if_after: Datespec | None = None
    if_in_facility: FacilityStr | None = None
    shown: bool | None = None
    weight: float


@content_dataclass()
class ChunkDesc:
    """
    .. autoattribute:: weight
    .. autoattribute:: shown
    .. autoattribute:: title
    .. autoattribute:: rules
    .. autoattribute:: content
    """

    id: IdentifierStr
    weight: float = 0
    title: str | None = None
    rules: list[ChunkRulesDesc] = Field(default_factory=list)
    shown: bool = True
    content: Markup

    def get_title(self) -> str:
        if self.title is not None:
            return self.title

        title = extract_title_from_markup(self.content)
        assert title is not None
        return title

    @model_validator(mode="after")
    def check_has_title(self) -> Self:
        if self.title is not None:
            return self

        title = extract_title_from_markup(self.content)
        if title is not None:
            return self

        raise ValueError(_("no title present (as attribute or in markup)"))


@content_dataclass()
class StaticPageDesc:
    chunks: list[ChunkDesc]

    @model_validator(mode="before")
    @classmethod
    def normalize_content_to_chunks(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if (("content" not in data and "chunks" not in data)
                    or ("content" in data and "chunks" in data)):
                raise ValueError("exactly one of 'chunks' and 'content' is required")

            if "content" in data:
                data["chunks"] = [{"content": data.pop("content")}]

        return data

    @model_validator(mode="after")
    def check_chunk_id_uniqueness(self) -> Self:
        if len({c.id for c in self.chunks}) != len(self.chunks):
            raise ValueError("chunk IDs are not unique")
        return self


static_page_ta = TypeAdapter(StaticPageDesc)


class CourseDesc(StaticPageDesc):
    pass

# }}}


@content_dataclass()
class FlowRule:
    kind: ClassVar[FlowRuleKind]


# {{{ flow start rule

@dataclass(frozen=True, kw_only=True)
class FlowSessionStartMode:
    may_start_new_session: bool
    """(Mandatory) A Boolean (True/False) value indicating whether, if the
    rule applies, the participant may start a new session."""

    may_list_existing_sessions: bool
    """(Mandatory) A Boolean (True/False) value indicating whether, if the
    rule applies, the participant may view a list of existing sessions."""

    tag_session: IdentifierStr | None = None
    """(Optional) An identifier that will be applied to a newly-created
    session as a "tag".  This can be used by
    :attr:`FlowSessionAccessRuleDesc.if_has_tag` and
    :attr:`FlowSessionGradingRuleDesc.if_has_tag`."""

    lock_down_as_exam_session: bool = False
    default_expiration_mode: FlowSessionExpirationMode = FlowSessionExpirationMode.end
    """(Optional)
    The expiration mode applied when a session is first created or rolled
    over."""


@dataclass(frozen=True, kw_only=True)
class FlowSessionStartRuleDesc(FlowRule, FlowSessionStartMode):
    """Rules that govern when a new session may be started and whether
    existing sessions may be listed.

    Found in the ``start`` attribute of :class:`FlowRulesDesc`.

    .. rubric:: Conditions

    .. autoattribute:: if_after
    .. autoattribute:: if_before
    .. autoattribute:: if_has_role
    .. autoattribute:: if_has_participation_tags_any
    .. autoattribute:: if_has_participation_tags_all
    .. autoattribute:: if_in_facility
    .. autoattribute:: if_has_in_progress_session
    .. autoattribute:: if_has_session_tagged
    .. autoattribute:: if_has_fewer_sessions_than
    .. autoattribute:: if_has_fewer_tagged_sessions_than
    .. autoattribute:: if_signed_in_with_matching_exam_ticket

    .. rubric:: Rules specified

    .. autoattribute:: may_start_new_session
    .. autoattribute:: may_list_existing_sessions
    .. autoattribute:: tag_session
    .. autoattribute:: lock_down_as_exam_session
    .. autoattribute:: default_expiration_mode
    """

    kind: ClassVar[FlowRuleKind] = FlowRuleKind.start

    # conditions
    if_after: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>` that determines a date/time
    after which this rule applies."""

    if_before: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>` that determines a date/time
    before which this rule applies."""

    if_has_role: list[ParticipationRoleStr] | None = None
    """(Optional) A list of a subset of the roles defined in the course, by
    default ``unenrolled``, ``ta``, ``student``, ``instructor``."""

    if_has_participation_tags_any: list[ParticipationTagStr] | None = None
    """(Optional) A list of participation tags. Rule applies when the
    participation has at least one tag in this list."""

    if_has_participation_tags_all: list[ParticipationTagStr] \
        = field(default_factory=list)
    """(Optional) A list of participation tags. Rule applies if only the
    participation's tags include all items in this list."""

    if_in_facility: FacilityStr | None = None
    """(Optional) Name of a facility known to the RELATE web page. This rule allows
    (for example) restricting flow starting based on whether a user is physically
    located in a computer-based testing center (which RELATE can
    recognize based on IP ranges)."""

    if_has_in_progress_session: bool | None = None
    """(Optional) A Boolean (True/False) value, indicating that the rule only
    applies if the participant has an in-progress session."""

    if_has_session_tagged: IdentifierStr | None = None
    """(Optional) An identifier (or ``null``) indicating that the rule only applies
    if the participant has a session with the corresponding tag."""

    if_has_fewer_sessions_than: int | None = None
    """(Optional) An integer. The rule applies if the participant has fewer
    than this number of sessions."""

    if_has_fewer_tagged_sessions_than: int | None = None
    """(Optional) An integer. The rule applies if the participant has fewer
    than this number of sessions with access rule tags."""

    if_signed_in_with_matching_exam_ticket: bool | None = None
    """(Optional) The rule applies if the participant signed in with an exam
    ticket matching this flow."""

    if_has_prairietest_exam_access: str | None = None


start_rule_ta = TypeAdapter(FlowSessionStartRuleDesc)

# }}}


# {{{ flow access rule

@dataclass(frozen=True, kw_only=True)
class FlowSessionAccessMode(FlowRule):
    permissions: frozenset[FlowPermission]
    message: str | None = None


@dataclass(frozen=True, kw_only=True)
class FlowSessionAccessRuleDesc(FlowSessionAccessMode, FlowRule):
    """Rules that govern what a user may do with an existing session.

    Found in the ``access`` attribute of :class:`FlowRulesDesc`.

    .. rubric:: Conditions
    .. autoattribute:: if_after
    .. autoattribute:: if_before
    .. autoattribute:: if_started_before
    .. autoattribute:: if_has_role
    .. autoattribute:: if_has_participation_tags_any
    .. autoattribute:: if_has_participation_tags_all
    .. autoattribute:: if_in_facility
    .. autoattribute:: if_has_tag
    .. autoattribute:: if_in_progress
    .. autoattribute:: if_completed_before
    .. autoattribute:: if_expiration_mode
    .. autoattribute:: if_session_duration_shorter_than_minutes
    .. autoattribute:: if_signed_in_with_matching_exam_ticket

    .. rubric:: Rules specified
    .. autoattribute:: permissions
    .. autoattribute:: message

    """

    kind: ClassVar[FlowRuleKind] = FlowRuleKind.access

    # conditions
    if_after: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>` that determines a date/time
    after which this rule applies."""

    if_before: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>` that determines a date/time
    before which this rule applies."""

    if_started_before: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>`. Rule applies if the session
    was started before this time."""

    if_has_role: list[ParticipationRoleStr] = field(default_factory=list)
    """(Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``."""

    if_has_participation_tags_any: list[ParticipationTagStr] | None = None
    """(Optional) A list of participation tags. Rule applies when the
    participation has at least one tag in this list."""

    if_has_participation_tags_all: list[ParticipationTagStr] \
        = field(default_factory=list)
    """(Optional) A list of participation tags. Rule applies if only the
    participation's tags include all items in this list."""

    if_in_facility: str | None = None
    """(Optional) Name of a facility known to the RELATE web page. This rule allows
    (for example) restricting flow access based on whether a user is physically
    located in a computer-based testing center (which RELATE can
    recognize based on IP ranges)."""

    if_has_tag: IdentifierStr | None = None
    """(Optional) Rule applies if session has this tag (see
    :attr:`FlowSessionStartRuleDesc.tag_session`), an identifier."""

    if_in_progress: bool | None = None
    """(Optional) A Boolean (True/False) value. Rule applies if the session's
    in-progress status matches this Boolean value."""

    if_completed_before: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>`. Rule applies if the session
    was completed before this time."""

    if_expiration_mode: FlowSessionExpirationMode | None = None
    """(Optional) One of :class:`~course.constants.flow_session_expiration_mode`.
    Rule applies if the expiration mode (see :ref:`flow-life-cycle`)
    matches."""

    if_session_duration_shorter_than_minutes: float | None = None
    """(Optional) The rule applies if the current session has been going on for
    less than the specified number of minutes. Fractional values (e.g. "0.5")
    are accepted here."""

    if_signed_in_with_matching_exam_ticket: bool | None = False
    """(Optional) The rule applies if the participant signed in with an exam
    ticket matching this flow."""

    if_has_prairietest_exam_access: str | None = None


access_rule_ta = TypeAdapter(FlowSessionAccessRuleDesc)


# }}}


FlowRuleT = TypeVar("FlowRuleT", bound=FlowRule)


def get_rule_ta(tp: type[FlowRuleT]) -> TypeAdapter[FlowRuleT]:
    if tp is FlowSessionStartRuleDesc:
        return cast("TypeAdapter[FlowRuleT]", start_rule_ta)
    elif tp is FlowSessionAccessRuleDesc:
        return cast("TypeAdapter[FlowRuleT]", access_rule_ta)
    elif tp is FlowSessionGradingRuleDesc:
        return cast("TypeAdapter[FlowRuleT]", grading_rule_ta)
    else:
        raise AssertionError()


# {{{ flow grading rule

@dataclass(frozen=True, kw_only=True)
class FlowSessionGradingMode(FlowRule):
    credit_percent: float = 100
    """(Optional) A number indicating the percentage of credit assigned for
    this flow.  Defaults to 100 if not present. This is applied *after*
    point modifiers such as :attr:`bonus_points` and
    :attr:`max_points_enforced_cap`."""

    due: Datespec | None = None
    """A :ref:`datespec <datespec>` indicating the due date of the flow. This
    is shown to the participant and also used to batch-expire 'past-due'
    flows."""

    generates_grade: bool = True
    """(Optional) A Boolean indicating whether a grade will be recorded when this
    flow is ended. Note that the value of this rule must never change over
    the lifetime of a flow. I.e. a flow that, at some point during its lifetime,
    *may* have been set to generate a grade must *always* be set to generate
    a grade. Defaults to ``true``."""

    use_last_activity_as_completion_time: bool = False
    """(Optional) A Boolean indicating whether the last time a participant made
    a change to their flow should be used as the completion time.

    Defaults to ``false`` to match past behavior. ``true`` is probably the more
    sensible value for this."""

    description: Markup | None = None
    """(Optional) A description of this set of grading rules being applied to
    the flow.  Shown to the participant on the flow start page."""

    max_points: int | float | None = None
    """(Optional, an integer or floating point number if given)
    The number of points on the flow which constitute
    "100% of the achievable points". If not given, this is automatically
    computed by summing point values from all constituent pages.

    This may be used to 'grade out of N points', where N is a number that
    is lower than the actually achievable count."""

    max_points_enforced_cap: float | None = None
    """(Optional, an integer or floating point number if given)
    No participant will have a grade higher than this recorded for this flow.
    This may be used to limit the amount of 'extra credit' achieved beyond
    :attr:`max_points`."""

    bonus_points: float = 0
    """(Optional, an integer or floating point number if given)
    This number of points will be added to every participant's score."""


@dataclass(frozen=True, kw_only=True)
class FlowSessionGradingRuleDesc(FlowSessionGradingMode):
    """ Rules that govern how (permanent) grades are generated from the
    results of a flow.

    Found in the ``grading`` attribute of :class:`FlowRulesDesc`.

    .. rubric:: Conditions

    .. autoattribute:: if_has_role
    .. autoattribute:: if_has_participation_tags_any
    .. autoattribute:: if_has_participation_tags_all
    .. autoattribute:: if_started_before
    .. autoattribute:: if_started_after
    .. autoattribute:: if_has_tag
    .. autoattribute:: if_completed_before

    .. rubric:: Rules specified

    .. autoattribute:: credit_percent
    .. autoattribute:: due
    .. autoattribute:: generates_grade
    .. autoattribute:: use_last_activity_as_completion_time
    .. autoattribute:: description
    .. autoattribute:: max_points
    .. autoattribute:: max_points_enforced_cap
    .. autoattribute:: bonus_points
    """
    kind: ClassVar[FlowRuleKind] = FlowRuleKind.grading

    # conditions

    if_has_role: list[ParticipationRoleStr] = field(default_factory=list)
    """(Optional) A list of a subset of ``[unenrolled, ta, student, instructor]``."""

    if_has_participation_tags_any: list[ParticipationTagStr] | None = None
    """(Optional) A list of participation tags. Rule applies when the
    participation has at least one tag in this list."""

    if_has_participation_tags_all: \
        list[ParticipationTagStr] = field(default_factory=list)
    """(Optional) A list of participation tags. Rule applies if only the
    participation's tags include all items in this list."""

    if_has_tag: IdentifierStr | None = None
    """(Optional) Rule applies if session has this tag (see
    :attr:`FlowSessionStartRuleDesc.tag_session`), an identifier."""

    if_started_before: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>`. Rule applies if the session
    was started before this time."""

    if_completed_before: Datespec | None = None
    """(Optional) A :ref:`datespec <datespec>`. Rule applies if the session
    was completed before this time.

    When evaluating this condition for in-progress sessions, the current time,
    or, if :attr:`use_last_activity_as_completion_time` is set, the time of the
    last activity is used.

    Since September 2017, this respects
    :attr:`use_last_activity_as_completion_time`."""

    def has_conditionals(self):
        return bool(
            self.if_has_role
            or self.if_has_participation_tags_any
            or self.if_has_participation_tags_all
            or self.if_has_tag
            or self.if_started_before is not None
            or self.if_completed_before is not None
        )


grading_rule_ta = TypeAdapter(FlowSessionGradingRuleDesc)

# }}}


# {{{ flow rules

@content_dataclass()
class FlowRulesDesc:
    """
    Found in the ``rules`` attribute of a :class:`FlowDesc`.

    .. autoattribute:: tags
    .. autoattribute:: start
    .. autoattribute:: access

    .. rubric:: Grading-Related
    .. autoattribute:: grade_identifier
    .. autoattribute:: grade_aggregation_strategy
    .. autoattribute:: grading

    Rules are tested from top to bottom. The first rule
    whose conditions apply determines the access.
    """

    tags: list[IdentifierStr] = Field(default_factory=list)

    start: list[FlowSessionStartRuleDesc]
    """Rules that govern when a new session may be started and whether
    existing sessions may be listed.

    Rules are tested from top to bottom. The first rule
    whose conditions apply determines the access."""

    access: list[FlowSessionAccessRuleDesc]
    """Rules that govern what a user may do while they are interacting with an
    existing session.

    Rules are tested from top to bottom. The first rule
    whose conditions apply determines the access."""

    grading: list[FlowSessionGradingRuleDesc] | None = None
    """Rules that govern how (permanent) overall grades are generated from the
    results of a flow. These rules apply once a flow session ends/is submitted
    for grading. See :ref:`flow-life-cycle`.

    (Required if grade_identifier is not ``null``)
    """

    grade_identifier: Annotated[str, StringConstraints(min_length=1)] | None = None
    """The identifier of the grade to be generated once the
    participant completes the flow.  If ``null``, no grade is generated.
    """

    grade_aggregation_strategy: GradeAggregationStrategy | None = None
    """One of :class:`GradeAggregationStrategy`."""

    @model_validator(mode="after")
    def check_has_grading_rules_if_needed(self) -> Self:
        if self.grade_identifier is not None:
            if not self.grading:
                raise ValueError("must have grading rules if it has grade_identifier")
        return self

    @model_validator(mode="after")
    def check_has_gas_if_needed(self) -> Self:
        if self.grade_identifier is not None:
            if not self.grade_aggregation_strategy:
                raise ValueError(
                            "must have grade aggregation strategy "
                            "if it has grade_identifier")
        return self

    @model_validator(mode="after")
    def check_last_grading_rule_unconditional(self) -> Self:
        if self.grading:
            if self.grading[-1].has_conditionals():
                raise ValueError("last grading rule must be unconditional")
        return self

    @model_validator(mode="after")
    def check_tags_valid(self) -> Self:
        tags = set(self.tags)

        if self.start:
            for i, srule in enumerate(self.start):
                if (srule.if_has_session_tagged is not None
                        and srule.if_has_session_tagged not in tags):
                    raise ValueError(f"access rule {i+1}: "
                            f"unknown session tag {srule.if_has_session_tagged}")

                if srule.tag_session is not None and srule.tag_session not in tags:
                    raise ValueError(f"access rule {i+1}: "
                            f"unknown session tag {srule.if_has_session_tagged}")

        if self.access:
            for i, arule in enumerate(self.access):
                if arule.if_has_tag is not None and arule.if_has_tag not in tags:
                    raise ValueError(f"access rule {i+1}: "
                            f"unknown session tag {arule.if_has_tag}")

        if self.grading:
            for i, grule in enumerate(self.grading):
                if grule.if_has_tag is not None and grule.if_has_tag not in tags:
                    raise ValueError(f"grading rule {i+1}: "
                            f"unknown session tag {grule.if_has_tag}")

        return self

    @model_validator(mode="after")
    def check_for_ignored_permissions(self, info: ValidationInfo) -> Self:
        vctx = get_validation_context(info)
        for i, arule in enumerate(self.access):
            if arule.if_in_progress is False and (
                    FlowPermission.submit_answer in arule.permissions
                    or FlowPermission.end_session in arule.permissions):
                vctx.add_warning(
                        _("Access Rule {} Rule specifies "
                            "'submit_answer' or 'end_session' "
                            "permissions for non-in-progress flow. These "
                            "permissions will be ignored.").format(i+1))

        return self

# }}}


# {{{ flow

@content_dataclass()
class TabDesc:
    """
    .. autoattribute:: title
    .. autoattribute:: url
    """

    title: str
    """(Required) Title to be displayed on the tab."""

    url: str
    """(Required) The URL of the external web page."""


@content_dataclass()
class FlowPageGroupDesc:
    """
    .. autoattribute:: id
    .. autoattribute:: pages
    .. autoattribute:: shuffle
    .. autoattribute:: max_page_count

    """

    id: IdentifierStr
    """(Required) A symbolic name for the page group."""

    pages: Annotated[list[PageBase], AfterValidator(validate_nonempty)]
    """(Required) A list of :ref:`flow-page`"""

    shuffle: bool | None = None
    """(Optional) A boolean (True/False) indicating whether the order
    of pages should be as in the list :attr:`pages` or
    determined by random shuffling"""

    max_page_count: PositiveInt | None = None
    """(Optional) An integer limiting the page count of this group
    to a certain value. Allows selection of a random subset by combining
    with :attr:`shuffle`."""

    @model_validator(mode="after")
    def check_missing_shuffle(self, info: ValidationInfo) -> Self:
        vctx = get_validation_context(info).with_location(f"group '{self.id}'")
        if self.max_page_count is not None and self.shuffle is None:
            vctx.add_warning(
                _("shuffle attribute will be required for groups with"
                  "max_page_count in a future version. set "
                  "'shuffle: False' to match current behavior."))

        return self

    @model_validator(mode="after")
    def check_page_id_uniqueness(self) -> Self:
        if len({p.id for p in self.pages}) != len(self.pages):
            raise ValueError("page IDs are not unique")
        return self


@content_dataclass()
class FlowDesc:
    """
    .. autoattribute:: title
    .. autoattribute:: description
    .. autoattribute:: completion_text
    .. autoattribute:: rules
    .. autoattribute:: groups
    .. attribute:: pages

        A list of :ref:`pages <flow-page>`. If you specify this, a single
        :class:`FlowPageGroupDesc` will be implicitly created. Exactly one of
        :attr:`groups` or :class:`pages` must be given.

    .. autoattribute:: external_resources
    .. autoattribute:: notify_on_submit
    """

    title: str
    """A plain-text title of the flow"""

    description: Markup
    """A description shown on the start page of the flow."""

    completion_text: Markup | None = None
    """Text shown once a student has completed the flow."""

    rules: FlowRulesDesc | None = None
    """(Optional) Some rules governing students' use and grading of the flow.
    See :ref:`flow-rules`."""

    groups: Annotated[list[FlowPageGroupDesc], AfterValidator(validate_nonempty)]

    external_resources: list[TabDesc] = Field(default_factory=list)

    notify_on_submit: list[EmailStr] | None = None
    """(Optional) A list of email addresses which to notify about a flow
    submission by a participant."""

    @model_validator(mode="before")
    @classmethod
    def normalize_pages_to_groups(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if (("pages" not in data and "groups" not in data)
                    or ("pages" in data and "groups" in data)):
                raise ValueError("exactly one of 'groups' and 'pages' must be provided")

            if "pages" in data:
                assert "groups" not in data
                data["groups"] = [{"id": "main", "pages": data.pop("pages")}]

        return data

    @model_validator(mode="after")
    def check_group_id_uniqueness(self) -> Self:
        if len({g.id for g in self.groups}) != len(self.groups):
            raise ValueError("group IDs are not unique")
        return self


flow_desc_ta = TypeAdapter(FlowDesc)

# }}}


# {{{ calendar data

@content_dataclass()
class EventKindDesc:
    color: str | None = None
    title: str | None = None


@content_dataclass()
class EventDesc:
    color: str | None = None
    title: str | None = None
    description: Markup | None = None
    show_description_from: Datespec | None = None
    show_description_until: Datespec | None = None


@content_dataclass()
class CalendarDesc:
    event_kinds: dict[IdentifierStr, EventKindDesc] = Field(default_factory=dict)
    events: dict[EventStr, EventDesc] = Field(default_factory=dict)


calendar_ta = TypeAdapter(CalendarDesc)

# }}}


# {{{ repo blob getting

def get_true_repo_and_path(
            repo: Repo_ish,
            path: str
        ) -> tuple[dulwich.repo.Repo | FileSystemFakeRepo, str]:

    while isinstance(repo, SubdirRepoWrapper):
        if path:
            path = f"{repo.subdir}/{path}"
        else:
            path = repo.subdir

        repo = repo.repo

    return repo, path


def get_course_repo_path(course: Course) -> Path:
    return Path(settings.GIT_ROOT) / course.identifier


def get_course_repo(course: Course) -> Repo_ish:
    from dulwich.repo import Repo
    repo = Repo(get_course_repo_path(course))

    if course.course_root_path:
        return SubdirRepoWrapper(repo, course.course_root_path)
    else:
        return repo


def _look_up_git_object(
            repo: dulwich.repo.Repo | FileSystemFakeRepo,
            root_tree: dulwich.objects.Tree | FileSystemFakeRepoTree,
            full_name: str,
            _max_symlink_depth: int | None = None
        ) -> Tree_ish | Blob_ish:
    """Traverse git directory tree from *root_tree*, respecting symlinks."""

    if _max_symlink_depth is None:
        _max_symlink_depth = 20
    if _max_symlink_depth == 0:
        raise ObjectDoesNotExist(_("symlink nesting depth exceeded "
            "while locating '%s'") % full_name)

    # https://github.com/inducer/relate/pull/556
    # FIXME: https://github.com/inducer/relate/issues/767
    name_parts = os.path.normpath(full_name).split(os.sep)

    processed_name_parts: list[str] = []

    cur_lookup: Tree_ish | Blob_ish = root_tree

    from stat import S_ISLNK

    from course.validation import Tree_ish
    while name_parts:
        if not isinstance(cur_lookup, Tree_ish):
            raise ObjectDoesNotExist(
                    _("'%s' is not a directory, cannot lookup nested names")
                    % os.sep.join(processed_name_parts))

        name_part = name_parts.pop(0)

        if not name_part:
            # tolerate empty path components (begrudgingly)
            continue
        elif name_part == ".":
            continue

        encoded_name_part = name_part.encode()
        try:
            mode_sha = cur_lookup[encoded_name_part]
        except KeyError:
            raise ObjectDoesNotExist(_("resource '%s' not found") % full_name)

        mode, cur_lookup_sha = mode_sha

        if S_ISLNK(mode):
            if isinstance(repo, dulwich.repo.Repo):
                assert isinstance(cur_lookup_sha, bytes)
                link_data = cast("dulwich.objects.Blob", repo[cur_lookup_sha]).data
                assert isinstance(link_data, bytes)
            elif isinstance(repo, FileSystemFakeRepo):
                # The filesystem will have resolved these behind our back.
                raise AssertionError()
            link_target = os.sep.join([*processed_name_parts, link_data.decode()])
            cur_lookup = _look_up_git_object(repo, root_tree, link_target,
                    _max_symlink_depth=_max_symlink_depth-1)
        else:
            processed_name_parts.append(name_part)
            if isinstance(repo, dulwich.repo.Repo):
                assert isinstance(cur_lookup_sha, bytes)
                lkup = repo[cur_lookup_sha]
                assert isinstance(lkup, Tree_ish | Blob_ish)
            elif isinstance(repo, FileSystemFakeRepo):
                assert isinstance(cur_lookup_sha,
                                  (FileSystemFakeRepoTree, FileSystemFakeRepoFile))
                lkup = repo[cur_lookup_sha]

            cur_lookup = lkup

    return cur_lookup


def get_repo_tree(
            repo: Repo_ish | FileSystemFakeRepo,
            full_name: str,
            commit_sha: bytes) -> Tree_ish:
    """
    :arg full_name: A Unicode string indicating the file name.
    :arg commit_sha: A byte string containing the commit hash
    :arg allow_tree: Allow the resulting object to be a directory
    """

    from course.validation import FileSystemFakeRepo, FileSystemFakeRepoTree
    if isinstance(repo, FileSystemFakeRepo):
        return FileSystemFakeRepoTree(repo.root / full_name)

    dul_repo, full_name = get_true_repo_and_path(repo, full_name)

    try:
        tree_sha = dul_repo[commit_sha].tree
    except KeyError:
        raise ObjectDoesNotExist(
                _("commit sha '%s' not found") % commit_sha.decode())

    git_obj = _look_up_git_object(
            dul_repo, root_tree=dul_repo[tree_sha], full_name=full_name)

    from dulwich.objects import Tree

    from course.validation import FileSystemFakeRepoTree

    msg_full_name = full_name or _("(repo root)")

    if isinstance(git_obj, Tree | FileSystemFakeRepoTree):
        return git_obj
    else:
        raise ObjectDoesNotExist(_("resource '%s' is not a tree") % msg_full_name)


def get_repo_blob(
            repo: Repo_ish | FileSystemFakeRepo,
            full_name: str,
            commit_sha: bytes | None) -> Blob_ish:
    """
    :arg full_name: A Unicode string indicating the file name.
    :arg commit_sha: A byte string containing the commit hash
    :arg allow_tree: Allow the resulting object to be a directory
    """
    from course.validation import FileSystemFakeRepo, FileSystemFakeRepoFile
    if isinstance(repo, FileSystemFakeRepo):
        return FileSystemFakeRepoFile(full_name)

    dul_repo, full_name = get_true_repo_and_path(repo, full_name)

    try:
        tree_sha = dul_repo[commit_sha].tree
    except KeyError:
        assert commit_sha
        raise ObjectDoesNotExist(
                _("commit sha '%s' not found") % commit_sha.decode())

    git_obj = _look_up_git_object(
            dul_repo, root_tree=dul_repo[tree_sha], full_name=full_name)

    from dulwich.objects import Blob

    from course.validation import FileSystemFakeRepoFile

    msg_full_name = full_name or _("(repo root)")

    if isinstance(git_obj, Blob | FileSystemFakeRepoFile):
        return git_obj
    else:
        raise ObjectDoesNotExist(_("resource '%s' is not a file") % msg_full_name)


def get_repo_blob_data_cached(
        repo: Repo_ish, full_name: str, commit_sha: bytes) -> bytes:
    """
    :arg commit_sha: A byte string containing the commit hash
    """

    if isinstance(commit_sha, bytes):
        from urllib.parse import quote_plus
        cache_key: str | None = "%s%R%1".join((
            CACHE_KEY_ROOT,
            quote_plus(str(repo.controldir())),
            quote_plus(full_name),
            commit_sha.decode(),
            ".".join(str(s) for s in sys.version_info[:2]),
            ))
    else:
        cache_key = None

    try:
        import django.core.cache as cache
    except ImproperlyConfigured:
        cache_key = None

    result: bytes | None = None
    if cache_key is None:
        result = get_repo_blob(repo, full_name, commit_sha).data
        assert isinstance(result, bytes)
        return result

    # Byte string is wrapped in a tuple to force pickling because memcache's
    # python wrapper appears to auto-decode/encode string values, thus trying
    # to decode our byte strings. Grr.

    def_cache = cache.caches["default"]

    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        cached_result = def_cache.get(cache_key)

        if cached_result is not None:
            (result,) = cached_result
            assert isinstance(result, bytes), cache_key
            return result

    result = get_repo_blob(repo, full_name, commit_sha).data
    assert result is not None

    if len(result) <= getattr(settings, "RELATE_CACHE_MAX_BYTES", 0):
        def_cache.add(cache_key, (result,), None)

    assert isinstance(result, bytes)

    return result


def is_repo_file_accessible_as(
        access_kinds: list[str], repo: Repo_ish, commit_sha: bytes, path: str
        ) -> bool:
    """
    Check of a file in a repo directory is accessible.  For example,
    'instructor' can access anything listed in the attributes.
    'student' can access 'student' and 'unenrolled'.  The 'unenrolled' role
    can only access 'unenrolled'.

    :arg commit_sha: A byte string containing the commit hash
    """

    # set the path to .attributes.yml
    attributes_path = os.path.join(os.path.dirname(path), ATTRIBUTES_FILENAME)

    # retrieve the .attributes.yml structure
    try:
        attributes = get_raw_yaml_from_repo(repo, attributes_path,
                                            commit_sha)
    except ObjectDoesNotExist:
        # no attributes file: not accessible
        return False

    path_basename = os.path.basename(path)

    # "public" is a deprecated alias for "unenrolled".

    access_patterns: list[str] = []
    for kind in access_kinds:
        access_patterns += attributes.get(kind, [])

    from fnmatch import fnmatch
    if isinstance(access_patterns, list):
        for pattern in access_patterns:
            if isinstance(pattern, str):
                if fnmatch(path_basename, pattern):
                    return True

    return False

# }}}


# {{{ jinja interaction

JINJA_YAML_RE = re.compile(
    r"^\[JINJA\]\s*$(.*?)^\[\/JINJA\]\s*$",
    re.MULTILINE | re.DOTALL)
YAML_BLOCK_START_SCALAR_RE = re.compile(
    r"(:\s*[|>])"
    r"(J?)"
    r"((?:[0-9][-+]?|[-+][0-9]?)?)"
    r"(?:\s*\#.*)?"
    r"$")

IN_BLOCK_END_RAW_RE = re.compile(r"(.*)({%-?\s*endraw\s*-?%})(.*)")
GROUP_COMMENT_START = re.compile(r"^\s*#\s*\{\{\{")
LEADING_SPACES_RE = re.compile(r"^( *)")


def process_yaml_for_expansion(yaml_str: str) -> str:

    lines = yaml_str.split("\n")
    jinja_lines: list[str] = []

    i = 0
    line_count = len(lines)

    while i < line_count:
        ln = lines[i].rstrip()
        yaml_block_scalar_match = YAML_BLOCK_START_SCALAR_RE.search(ln)

        if yaml_block_scalar_match is not None:
            unprocessed_block_lines: list[str] = []
            allow_jinja = bool(yaml_block_scalar_match.group(2))
            ln = YAML_BLOCK_START_SCALAR_RE.sub(
                    r"\1\3", ln)

            unprocessed_block_lines.append(ln)

            leading_spaces_match = LEADING_SPACES_RE.match(ln)
            assert leading_spaces_match
            block_start_indent = len(leading_spaces_match.group(1))

            i += 1

            while i < line_count:
                ln = lines[i]

                if not ln.rstrip():
                    unprocessed_block_lines.append(ln)
                    i += 1
                    continue

                leading_spaces_match = LEADING_SPACES_RE.match(ln)
                assert leading_spaces_match
                line_indent = len(leading_spaces_match.group(1))
                if line_indent <= block_start_indent:
                    break
                else:
                    ln = IN_BLOCK_END_RAW_RE.sub(
                        r"\1{% endraw %}{{ '\2' }}{% raw %}\3", ln)
                    unprocessed_block_lines.append(ln.rstrip())
                    i += 1

            if not allow_jinja:
                jinja_lines.append("{% raw %}")
            jinja_lines.extend(unprocessed_block_lines)
            if not allow_jinja:
                jinja_lines.append("{% endraw %}")

        elif GROUP_COMMENT_START.match(ln):
            jinja_lines.extend(("{% raw %}", ln, "{% endraw %}"))
            i += 1

        else:
            jinja_lines.append(ln)
            i += 1
    return "\n".join(jinja_lines)


class GitTemplateLoader:
    def __init__(self, repo: Repo_ish, commit_sha: bytes) -> None:
        self.repo = repo
        self.commit_sha = commit_sha

    def __call__(self, template):
        data = get_repo_blob_data_cached(self.repo, template, self.commit_sha)

        return data.decode("utf-8")


class YamlBlockEscapingGitTemplateLoader(GitTemplateLoader):
    # https://github.com/inducer/relate/issues/130

    def __call__(self, template):
        source = super().__call__(template)

        _, ext = os.path.splitext(template)
        ext = ext.lower()

        if ext in [".yml", ".yaml"]:
            source = process_yaml_for_expansion(source)

        return source


class YamlBlockEscapingFileSystemLoader:
    # https://github.com/inducer/relate/issues/130

    root: Path

    def __init__(self, root: Path):
        if not isinstance(root, Path):
            root = Path(root)
        self.root = root

    def __call__(self, template: str):
        source = Path(os.path.join(self.root, template)).read_text()
        source = (self.root / template).read_text()

        _, ext = os.path.splitext(template)
        ext = ext.lower()

        if ext in [".yml", ".yaml"]:
            source = process_yaml_for_expansion(source)

        return source


def expand_yaml_macros(repo: Repo_ish, commit_sha: bytes, yaml_str: str) -> str:

    if isinstance(yaml_str, bytes):
        yaml_str = yaml_str.decode("utf-8")

    from minijinja import Environment
    jinja_env = Environment(
            loader=YamlBlockEscapingGitTemplateLoader(repo, commit_sha),
            undefined_behavior="strict",
            auto_escape_callback=lambda fn: False)

    # {{{ process explicit [JINJA] tags (deprecated)

    def compute_replacement(match):  # pragma: no cover  # deprecated
        return jinja_env.render_str(match.group(1))

    yaml_str, count = JINJA_YAML_RE.subn(compute_replacement, yaml_str)

    if count:  # pragma: no cover  # deprecated
        # The file uses explicit [JINJA] tags. Assume that it doesn't
        # want anything else processed through YAML.
        return yaml_str

    # }}}

    jinja_str = process_yaml_for_expansion(yaml_str)
    yaml_str = jinja_env.render_str(jinja_str)

    return yaml_str

# }}}


# {{{ repo yaml getting

def get_raw_yaml_from_repo(
        repo: Repo_ish, full_name: str, commit_sha: bytes) -> Any:
    """Return decoded YAML data structure from
    the given file in *repo* at *commit_sha*.

    :arg commit_sha: A byte string containing the commit hash
    """

    from urllib.parse import quote_plus
    cache_key = "%RAW%%2".join((
        CACHE_KEY_ROOT,
        quote_plus(str(repo.controldir())), quote_plus(full_name), commit_sha.decode(),
        ))

    import django.core.cache as cache
    def_cache = cache.caches["default"]

    result: Any | None = None
    # Memcache is apparently limited to 250 characters.
    if len(cache_key) < 240:
        result = def_cache.get(cache_key)
    if result is not None:
        return result

    yaml_str = expand_yaml_macros(
                repo, commit_sha,
                get_repo_blob(repo, full_name, commit_sha).data)

    result = load_yaml(yaml_str)  # type: ignore

    def_cache.add(cache_key, result, None)

    return result


LINE_HAS_INDENTING_TABS_RE = re.compile(r"^\s*\t\s*", re.MULTILINE)


def get_model_from_repo(
        vctx: ValidationContext,
        model_ta: TypeAdapter[ModelT],
        repo: Repo_ish | FileSystemFakeRepo,
        full_name: str, commit_sha: bytes,
        cached: bool = True,
        tolerate_tabs: bool = False,
    ) -> ModelT:
    """
    :arg tolerate_tabs: At one point, Relate accepted tabs
        in indentation, but it no longer does. In places where legacy compatibility
        matters, you may set *tolerate_tabs* to *True*.
    """

    if cached:
        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            cached = False
        else:
            from urllib.parse import quote_plus
            cache_key = "%%%2".join(
                    (CACHE_KEY_ROOT,
                        quote_plus(str(repo.controldir())), quote_plus(full_name),
                        commit_sha.decode()))

            def_cache = cache.caches["default"]
            result = None
            # Memcache is apparently limited to 250 characters.
            if len(cache_key) < 240:
                result = def_cache.get(cache_key)
            if result is not None:
                return result

    yaml_bytestream = get_repo_blob(
            repo, full_name, commit_sha).data
    yaml_text = yaml_bytestream.decode("utf-8")

    if not tolerate_tabs and LINE_HAS_INDENTING_TABS_RE.search(yaml_text):
        raise ValueError("File uses tabs in indentation. "
                "This is not allowed.")

    expanded = expand_yaml_macros(repo, commit_sha, yaml_bytestream)

    yaml_data = load_yaml(expanded)
    result = model_ta.validate_python(yaml_data, context=vctx)

    if cached:
        def_cache.add(cache_key, result, None)

    return result

# }}}


# {{{ markup

def _attr_to_string(key, val):
    if val is None:
        return key
    elif '"' in val:
        return f"{key}='{val}'"
    else:
        return f'{key}="{val}"'


class TagProcessingHTMLParser(html_parser.HTMLParser):
    def __init__(
                self,
                out_file,
                process_tag_func: Callable[[str, Mapping[str, str]], Mapping[str, str]]
            ) -> None:
        html_parser.HTMLParser.__init__(self)

        self.out_file = out_file
        self.process_tag_func = process_tag_func

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<{} {}>".format(tag, " ".join(
            starmap(_attr_to_string, attrs.items()))))

    def handle_endtag(self, tag):
        self.out_file.write(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        attrs = dict(attrs)
        attrs.update(self.process_tag_func(tag, attrs))

        self.out_file.write("<{} {}/>".format(tag, " ".join(
            starmap(_attr_to_string, attrs.items()))))

    def handle_data(self, data):
        self.out_file.write(data)

    def handle_entityref(self, name):
        self.out_file.write(f"&{name};")

    def handle_charref(self, name):
        self.out_file.write(f"&#{name};")

    def handle_comment(self, data):
        self.out_file.write(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.out_file.write(f"<!{decl}>")

    def handle_pi(self, data):
        raise NotImplementedError(
                _("I have no idea what a processing instruction is."))

    def unknown_decl(self, data):
        self.out_file.write(f"<![{data}]>")


@dataclass
class PreserveFragment:
    s: str


class LinkFixerTreeprocessor(Treeprocessor):
    def __init__(self, md, course, commit_sha, reverse_func):
        Treeprocessor.__init__(self)
        self.md = md
        self.course = course
        self.commit_sha = commit_sha
        self.reverse_func = reverse_func

    def reverse(self, viewname: str, args: tuple[Any, ...]) -> str:
        frag = None

        new_args = []
        for arg in args:
            if isinstance(arg, PreserveFragment):
                s = arg.s
                frag_index = s.find("#")
                if frag_index != -1:
                    frag = s[frag_index:]
                    s = s[:frag_index]

                new_args.append(s)
            else:
                new_args.append(arg)

        result = self.reverse_func(viewname, args=new_args)

        if frag is not None:
            result += frag

        return result

    def get_course_identifier(self) -> str:
        if self.course is None:
            return "bogus-course-identifier"
        else:
            return self.course.identifier

    def process_url(self, url: str) -> str | None:
        try:
            if url.startswith("course:"):
                course_id = url[7:]
                if course_id:
                    return self.reverse("relate-course_page",
                                args=(course_id,))
                else:
                    return self.reverse("relate-course_page",
                                args=(self.get_course_identifier(),))

            elif url.startswith("flow:"):
                flow_id = url[5:]
                return self.reverse("relate-view_start_flow",
                            args=(self.get_course_identifier(), flow_id))

            elif url.startswith("staticpage:"):
                page_path = url[11:]
                return self.reverse("relate-content_page",
                            args=(
                                self.get_course_identifier(),
                                PreserveFragment(page_path)))

            elif url.startswith("media:"):
                media_path = url[6:]
                return self.reverse("relate-get_media",
                            args=(
                                self.get_course_identifier(),
                                self.commit_sha.decode(),
                                PreserveFragment(media_path)))

            elif url.startswith("repo:"):
                path = url[5:]
                return self.reverse("relate-get_repo_file",
                            args=(
                                self.get_course_identifier(),
                                self.commit_sha.decode(),
                                PreserveFragment(path)))

            elif url.startswith("repocur:"):
                path = url[8:]
                return self.reverse("relate-get_current_repo_file",
                            args=(
                                self.get_course_identifier(),
                                PreserveFragment(path)))

            elif url.strip() == "calendar:":
                return self.reverse("relate-view_calendar",
                            args=(self.get_course_identifier(),))

            else:
                return None

        except NoReverseMatch:
            from base64 import b64encode
            message = ("Invalid character in RELATE URL: " + url).encode("utf-8")
            return "data:text/plain;base64,"+b64encode(message).decode()

    def process_tag(self, tag_name: str, attrs: Mapping[str, str]) -> Mapping[str, str]:
        changed_attrs = {}

        if tag_name == "table" and attrs.get("bootstrap") != "no":
            changed_attrs["class"] = "table table-condensed"

        if tag_name in ["a", "link"] and "href" in attrs:
            new_href = self.process_url(attrs["href"])

            if new_href is not None:
                changed_attrs["href"] = new_href

        elif tag_name == "img" and "src" in attrs:
            new_src = self.process_url(attrs["src"])

            if new_src is not None:
                changed_attrs["src"] = new_src

        elif tag_name == "object" and "data" in attrs:
            new_data = self.process_url(attrs["data"])

            if new_data is not None:
                changed_attrs["data"] = new_data

        return changed_attrs

    def process_etree_element(self, element: Element) -> None:
        changed_attrs = self.process_tag(element.tag, element.attrib)

        for key, val in changed_attrs.items():
            element.set(key, val)

    def walk_and_process_tree(self, root: Element) -> None:
        self.process_etree_element(root)

        for child in root:
            self.walk_and_process_tree(child)

    def run(self, root: Element) -> None:
        self.walk_and_process_tree(root)

        # root through and process Markdown's HTML stash (gross!)
        from io import StringIO

        for i, html in enumerate(self.md.htmlStash.rawHtmlBlocks):
            outf = StringIO()
            parser = TagProcessingHTMLParser(outf, self.process_tag)

            # According to
            # https://github.com/python/typeshed/blob/61ba4de28f1469d6a642c983d5a7674479c12444/stubs/Markdown/markdown/util.pyi#L44
            # this should not happen, but... *shrug*
            if isinstance(html, Element):
                html = tostring(html).decode("utf-8")
            parser.feed(html)

            self.md.htmlStash.rawHtmlBlocks[i] = outf.getvalue()


class LinkFixerExtension(Extension):
    def __init__(self,
                course: Course | None,
                commit_sha: bytes,
                reverse_func: Callable[[str], str] | None
            ) -> None:
        Extension.__init__(self)
        self.course = course
        self.commit_sha = commit_sha
        self.reverse_func = reverse_func

    def extendMarkdown(self, md):  # noqa
        md.treeprocessors.register(
            LinkFixerTreeprocessor(md, self.course, self.commit_sha,
                                    reverse_func=self.reverse_func),
            "relate_link_fixer", 0)


def remove_prefix(prefix: str, s: str) -> str:
    if s.startswith(prefix):
        return s[len(prefix):]
    else:
        return s


JINJA_PREFIX = "[JINJA]"


def expand_markup(
        course: Course | None,
        repo: Repo_ish,
        commit_sha: bytes,
        text: str,
        use_jinja: bool = True,
        jinja_env: dict[str, Any] | None = None,
        ) -> str:

    if jinja_env is None:
        jinja_env = {}

    if not isinstance(text, str):
        text = str(text)

    # {{{ process through Jinja

    if use_jinja:
        from minijinja import Environment
        env = Environment(
                loader=GitTemplateLoader(repo, commit_sha),
                undefined_behavior="strict")

        def render_notebook_cells(*args, **kwargs):
            return "[The ability to render notebooks was removed.]"

        env.add_function("render_notebook_cells", render_notebook_cells)

        text = env.render_str(text, **jinja_env)

    # }}}

    return text


def filter_html_attributes(tag: str, name: str, value: str):
    from bleach.sanitizer import ALLOWED_ATTRIBUTES

    allowed_attrs = ALLOWED_ATTRIBUTES.get(tag, [])
    result = name in allowed_attrs

    if tag == "a":
        result = (result
                or (name == "role" and value == "button")
                or (name == "class" and value.startswith("btn btn-")))
    elif tag == "img":
        result = result or name == "src"
    elif tag == "div":
        result = result or (name == "class" and value == "well")
    elif tag == "i":
        result = result or (name == "class" and value.startswith("bi bi-"))
    elif tag == "table":
        result = (result or (name == "class") or (name == "bootstrap"))

    return result


def markup_to_html(
        course: Course | None,
        repo: Repo_ish,
        commit_sha: bytes,
        text: str,
        reverse_func: Callable[[str], str] | None = None,
        validate_only: bool = False,
        use_jinja: bool = True,
        jinja_env: dict[str, Any] | None = None,
        ) -> str:

    if jinja_env is None:
        jinja_env = {}

    disable_codehilite = bool(
        getattr(settings,
                "RELATE_DISABLE_CODEHILITE_MARKDOWN_EXTENSION", True))

    if course is not None and not jinja_env:
        try:
            import django.core.cache as cache
        except ImproperlyConfigured:
            cache_key = None
        else:
            import hashlib
            cache_key = ("markup:v9:%s:%d:%s:%s:%s%s"
                    % (CACHE_KEY_ROOT,
                       course.id, course.trusted_for_markup, str(commit_sha),
                       hashlib.md5(text.encode("utf-8")).hexdigest(),
                       ":NOCODEHILITE" if disable_codehilite else ""
                       ))

            def_cache = cache.caches["default"]
            result = def_cache.get(cache_key)
            if result is not None:
                assert isinstance(result, str)
                return result

        if text.lstrip().startswith(JINJA_PREFIX):
            text = remove_prefix(JINJA_PREFIX, text.lstrip())
    else:
        cache_key = None

    text = expand_markup(
            course, repo, commit_sha, text, use_jinja=use_jinja, jinja_env=jinja_env)

    if reverse_func is None:
        from django.urls import reverse
        reverse_func = reverse

    if validate_only:
        return ""

    import markdown

    from course.mdx_mathjax import MathJaxExtension

    extensions: list[markdown.Extension | str] = [
        LinkFixerExtension(course, commit_sha, reverse_func=reverse_func),
        MathJaxExtension(),
        "markdown.extensions.extra",
    ]

    result = markdown.markdown(text,
        extensions=extensions,
        output_format="html")

    if course is None or not course.trusted_for_markup:
        import bleach
        result = bleach.clean(result,
                tags=[*bleach.ALLOWED_TAGS, "div", "span", "p", "img",
                    "h1", "h2", "h3", "h4", "h5", "h6",
                    "table", "td", "tr", "th",
                    "pre", "details", "summary", "thead", "tbody"],
                attributes=filter_html_attributes)

    result = f"<div class='relate-markup'>{result}</div>"

    assert isinstance(result, str)
    if cache_key is not None:
        def_cache.add(cache_key, result, None)

    return result


TITLE_RE = re.compile(r"^\#+\s*(.+)", re.UNICODE)


def extract_title_from_markup(markup_text: str) -> str | None:
    lines = markup_text.split("\n")

    for ln in lines[:10]:
        match = TITLE_RE.match(ln)
        if match is not None:
            return match.group(1)

    return None

# }}}


# {{{ datespec processing

DATE_RE = re.compile(r"^([0-9]+)\-([01][0-9])\-([0-3][0-9])$")
TRAILING_NUMERAL_RE = re.compile(r"^(.*)\s+([0-9]+)$")

END_PREFIX = "end:"


class InvalidDatespec(ValueError):
    def __init__(self, datespec):
        ValueError.__init__(self, str(datespec))
        self.datespec = datespec


class DatespecPostprocessor:
    @classmethod
    def parse(cls, s: str) -> tuple[str, DatespecPostprocessor | None]:
        raise NotImplementedError()

    def apply(self, dtm: datetime.datetime) -> datetime.datetime:
        raise NotImplementedError()


AT_TIME_RE = re.compile(r"^(.*)\s*@\s*([0-2]?[0-9])\:([0-9][0-9])\s*$")


class AtTimePostprocessor(DatespecPostprocessor):
    def __init__(self, hour: int, minute: int, second: int = 0) -> None:
        self.hour = hour
        self.minute = minute
        self.second = second

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
    r"(weeks?|days?|hours?|minutes?)$")


class PlusDeltaPostprocessor(DatespecPostprocessor):
    def __init__(self, count: int, period: str) -> None:

        self.count = count
        self.period = period

    @classmethod
    @override
    def parse(cls, s: str):
        match = PLUS_DELTA_RE.match(s)
        if match is not None:
            count = int(match.group(3))
            if match.group(2) == "-":
                count = -count
            period = match.group(4)

            return match.group(1), PlusDeltaPostprocessor(count, period)
        else:
            return s, None

    @override
    def apply(self, dtm: datetime.datetime):
        if self.period.startswith("week"):
            d = datetime.timedelta(weeks=self.count)
        elif self.period.startswith("day"):
            d = datetime.timedelta(days=self.count)
        elif self.period.startswith("hour"):
            d = datetime.timedelta(hours=self.count)
        else:
            assert self.period.startswith("minute")
            d = datetime.timedelta(minutes=self.count)
        return dtm + d


DATESPEC_POSTPROCESSORS: list[Any] = [
        AtTimePostprocessor,
        PlusDeltaPostprocessor,
        ]


def parse_date_spec(
        course: Course | None,
        datespec: str | datetime.date | datetime.datetime,
        vctx: ValidationContext | None = None,
        ) -> datetime.datetime:

    if datespec is None:
        return None

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
                postprocs.insert(0, cast("DatespecPostprocessor", postproc))
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


# {{{ page chunks

@dataclass(frozen=True)
class ChunkWeightShown:
    chunk: ChunkDesc
    weight: float
    shown: bool


def _compute_chunk_weight_and_shown(
        chunk: ChunkDesc,
        roles: Set[str],
        now_datetime: datetime.datetime,
        facilities: Collection[str],
        ) -> ChunkWeightShown:
    for rule in chunk.rules:
        if not rule.if_has_role <= roles:
            continue

        if rule.if_after is not None:
            if now_datetime < rule.if_after:
                continue

        if rule.if_before is not None:
            if rule.if_before < now_datetime:
                continue

        if rule.if_in_facility is not None:
            if rule.if_in_facility not in facilities:
                continue

        shown = True
        if rule.shown is not None:
            shown = rule.shown

        return ChunkWeightShown(chunk, rule.weight, shown)

    return ChunkWeightShown(chunk, 0, True)


def get_processed_page_chunks(
            course: Course,
            page_desc: StaticPageDesc,
            roles: Set[str],
            now_datetime: datetime.datetime,
            facilities: Collection[str],
        ) -> list[tuple[ChunkDesc, SafeString]]:
    cwss = [
        _compute_chunk_weight_and_shown(chunk, roles, now_datetime, facilities)
        for chunk in page_desc.chunks]

    cwss = sorted(cwss, key=lambda cws: cws.weight, reverse=True)
    return [
        (cws.chunk, mark_safe(
                    markup_to_html(course, get_course_repo(course),
                                   course.active_git_commit_sha.encode(),
                                   cws.chunk.content)))
        for cws in cwss if cws.shown]


# }}}


# {{{ repo desc getting

@deprecated("use get_model_from_repo")
def get_staticpage_desc(
            repo: Repo_ish,
            course: Course,
            commit_sha: bytes,
            filename: str
        ) -> StaticPageDesc:
    vctx = ValidationContext(repo, commit_sha, course)
    return vctx.with_location(filename).annotate_errors(
            get_model_from_repo, static_page_ta, repo, filename, commit_sha)


@deprecated("use get_model_from_repo")
def get_course_desc(repo: Repo_ish, course: Course, commit_sha: bytes) -> CourseDesc:
    return cast(
            "CourseDesc",
            get_staticpage_desc(repo, course, commit_sha, course.course_file))  # pyright: ignore[reportDeprecated]


def get_flow_desc(
        repo: Repo_ish, course: Course, flow_id: str,
        commit_sha: bytes, tolerate_tabs: bool = False) -> FlowDesc:
    """
    :arg tolerate_tabs: At one point, Relate accepted tabs
        in indentation, but it no longer does. In places where legacy
        compatibility matters, you may set *tolerate_tabs* to *True*.
    """

    vctx = ValidationContext(repo, commit_sha, course)
    location = f"flows/{flow_id}.yml"
    return vctx.with_location(location).annotate_errors(
            get_model_from_repo,
            flow_desc_ta, repo, location, commit_sha, tolerate_tabs=tolerate_tabs)


def get_flow_page(
            flow_id: str,
            flow_desc: FlowDesc,
            group_id: str,
            page_id: str) -> PageBase:
    for grp in flow_desc.groups:
        if grp.id == group_id:
            for page in grp.pages:
                if page.id == page_id:
                    return page

    raise ObjectDoesNotExist(
            _("page '%(group_id)s/%(page_id)s' in flow '%(flow_id)s'") % {
                "group_id": group_id,
                "page_id": page_id,
                "flow_id": flow_id
                })

# }}}


class CourseCommitSHADoesNotExist(Exception):
    pass


def get_course_commit_sha(
        course: Course,
        participation: Participation | None,
        repo: Repo_ish | None = None,
        raise_on_nonexistent_preview_commit: bool | None = False
        ) -> bytes:
    sha = course.active_git_commit_sha

    def is_commit_sha_valid(repo: Repo_ish, commit_sha: str) -> bool:
        if isinstance(repo, SubdirRepoWrapper):
            repo = repo.repo
        try:
            repo[commit_sha.encode()]
        except KeyError:
            if raise_on_nonexistent_preview_commit:
                raise CourseCommitSHADoesNotExist(
                    _("Preview revision '{}' does not exist--"
                      "showing active course content instead.").format(commit_sha))
            return False

        return True

    if participation is not None:
        if participation.preview_git_commit_sha:
            preview_sha = participation.preview_git_commit_sha

            if repo is not None:
                preview_sha_valid = is_commit_sha_valid(repo, preview_sha)
            else:
                with get_course_repo(course) as repo:
                    preview_sha_valid = is_commit_sha_valid(repo, preview_sha)

            if preview_sha_valid:
                sha = preview_sha

    return sha.encode()


def list_flow_ids(repo: Repo_ish, commit_sha: bytes) -> list[str]:
    flow_ids = []
    try:
        flows_tree = get_repo_tree(repo, "flows", commit_sha)
    except ObjectDoesNotExist:
        # That's OK--no flows yet.
        pass
    else:
        for entry in flows_tree.items():
            if entry.path.endswith(b".yml"):
                flow_ids.append(entry.path[:-4].decode("utf-8"))

    return sorted(flow_ids)

# vim: foldmethod=marker
