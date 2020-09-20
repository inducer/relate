# -*- coding: utf-8 -*-

from __future__ import division

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

from django.utils.translation import (
        gettext, gettext_lazy as _)
from django.contrib.auth.decorators import login_required
from django.utils.functional import lazy
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
from django.core.exceptions import (
        PermissionDenied, SuspiciousOperation,
        ObjectDoesNotExist)
from django.db import transaction
from django.db.models import query  # noqa
from django.utils.safestring import mark_safe
mark_safe_lazy = lazy(mark_safe, str)
from django import forms
from django import http
from django.conf import settings
from django.urls import reverse

from crispy_forms.helper import FormHelper

from relate.utils import (
        StyledForm, local_now, as_local_time,
        format_datetime_local, string_concat)
from crispy_forms.layout import Submit
from django_select2.forms import Select2Widget

from course.constants import (
        flow_permission,
        participation_permission as pperm,
        flow_session_expiration_mode,
        FLOW_SESSION_EXPIRATION_MODE_CHOICES,
        is_expiration_mode_allowed,
        grade_aggregation_strategy,
        GRADE_AGGREGATION_STRATEGY_CHOICES,
        flow_session_interaction_kind
        )
from course.models import (
        Participation,
        Course,
        FlowSession, FlowPageData, FlowPageVisit,
        FlowPageVisitGrade,
        get_feedback_for_grade,
        GradeChange, update_bulk_feedback)

from course.utils import (
        FlowContext,
        FlowPageContext,
        PageOrdinalOutOfRange,
        instantiate_flow_page_with_ctx,
        course_view, render_course_page,
        get_session_start_rule,
        get_session_access_rule,
        get_session_grading_rule,
        FlowSessionGradingRule,
        LanguageOverride,
        )
from course.exam import get_login_exam_ticket
from course.page import InvalidPageData
from course.views import get_now_or_fake_time
from relate.utils import retry_transaction_decorator

# {{{ mypy

from typing import Any, Optional, Iterable, Sequence, Tuple, Text, List, FrozenSet, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    import datetime  # noqa
    from course.models import Course  # noqa
    from accounts.models import User  # noqa
    from course.utils import (  # noqa
            CoursePageContext,
            FlowSessionStartRule,
            )
    from course.content import (  # noqa
            FlowDesc,
            )
    from course.page.base import (  # noqa
            PageBase,
            PageBehavior,
            AnswerFeedback
            )
    from relate.utils import Repo_ish  # noqa

# }}}


# {{{ page data wrangling

@retry_transaction_decorator(serializable=True)
def _adjust_flow_session_page_data_inner(repo, flow_session,
        course_identifier, flow_desc, commit_sha):
    from course.page.base import PageContext
    pctx = PageContext(
            course=flow_session.course,
            repo=repo,
            commit_sha=commit_sha,
            flow_session=flow_session,
            in_sandbox=False,
            page_uri=None)

    def remove_page(fpd):
        if fpd.page_ordinal is not None:
            fpd.page_ordinal = None
            fpd.save()

    desc_group_ids = []

    ordinal = [0]
    for grp in flow_desc.groups:
        desc_group_ids.append(grp.id)

        shuffle = getattr(grp, "shuffle", False)
        max_page_count = getattr(grp, "max_page_count", None)

        available_page_ids = [page_desc.id for page_desc in grp.pages]

        if max_page_count is None:
            max_page_count = len(available_page_ids)

        group_pages = []

        # {{{ helper functions

        def find_page_desc(page_id):
            new_page_desc = None

            for page_desc in grp.pages:  # pragma: no branch
                if page_desc.id == page_id:
                    new_page_desc = page_desc
                    break

            assert new_page_desc is not None

            return new_page_desc

        def instantiate_page(page_desc):
            from course.content import instantiate_flow_page
            return instantiate_flow_page(
                    "course '%s', flow '%s', page '%s/%s'"
                    % (course_identifier, flow_session.flow_id,
                        grp.id, page_desc.id),
                    repo, page_desc, commit_sha)

        def create_fpd(new_page_desc):
            page = instantiate_page(new_page_desc)

            data = page.initialize_page_data(pctx)
            return FlowPageData(
                    flow_session=flow_session,
                    page_ordinal=None,
                    page_type=new_page_desc.type,
                    group_id=grp.id,
                    page_id=new_page_desc.id,
                    data=data,
                    title=page.title(pctx, data))

        def add_page(fpd):
            if fpd.page_ordinal != ordinal[0]:
                fpd.page_ordinal = ordinal[0]
                fpd.save()

            page_desc = find_page_desc(fpd.page_id)
            page = instantiate_page(page_desc)
            title = page.title(pctx, fpd.data)

            if fpd.title != title:
                fpd.title = title
                fpd.save()

            ordinal[0] += 1
            available_page_ids.remove(fpd.page_id)

            group_pages.append(fpd)

        # }}}

        if shuffle:
            # maintain order of existing pages as much as possible
            for fpd in (FlowPageData.objects
                    .filter(
                        flow_session=flow_session,
                        group_id=grp.id,
                        page_ordinal__isnull=False)
                    .order_by("page_ordinal")):

                if (fpd.page_id in available_page_ids
                        and len(group_pages) < max_page_count):
                    add_page(fpd)
                else:
                    remove_page(fpd)

            assert len(group_pages) <= max_page_count

            from random import choice

            # then add randomly chosen new pages
            while len(group_pages) < max_page_count and available_page_ids:
                new_page_id = choice(available_page_ids)

                new_page_fpds = (FlowPageData.objects
                        .filter(
                            flow_session=flow_session,
                            group_id=grp.id,
                            page_id=new_page_id))

                if new_page_fpds.count():
                    # We already have FlowPageData for this page, revive it
                    new_page_fpd, = new_page_fpds
                    assert new_page_fpd.page_id == new_page_id
                else:
                    # Make a new FlowPageData instance
                    page_desc = find_page_desc(new_page_id)
                    assert page_desc.id == new_page_id
                    new_page_fpd = create_fpd(page_desc)
                    assert new_page_fpd.page_id == new_page_id

                add_page(new_page_fpd)

        else:
            # reorder pages to order in flow
            id_to_fpd = dict(
                    ((fpd.group_id, fpd.page_id), fpd)
                    for fpd in FlowPageData.objects.filter(
                        flow_session=flow_session,
                        group_id=grp.id))

            for page_desc in grp.pages:
                key = (grp.id, page_desc.id)

                if key in id_to_fpd:
                    fpd = id_to_fpd.pop(key)
                else:
                    fpd = create_fpd(page_desc)

                if len(group_pages) < max_page_count:
                    add_page(fpd)

            for fpd in id_to_fpd.values():
                remove_page(fpd)

    # {{{ remove pages orphaned because of group renames

    for fpd in (
            FlowPageData.objects
            .filter(
                flow_session=flow_session,
                page_ordinal__isnull=False)
            .exclude(group_id__in=desc_group_ids)
            ):
        remove_page(fpd)

    # }}}

    return ordinal[0]  # new page count


def adjust_flow_session_page_data(repo, flow_session,
        course_identifier, flow_desc=None, respect_preview=True):
    # type: (Repo_ish, FlowSession, Text, Optional[FlowDesc], bool) -> None

    """
    The caller may *not* be in a transaction that has a weaker isolation
    level than *serializable*.
    """

    from course.content import get_course_commit_sha, get_flow_desc
    commit_sha = get_course_commit_sha(
            flow_session.course,
            flow_session.participation if respect_preview else None)
    revision_key = "2:"+commit_sha.decode()

    if flow_desc is None:
        flow_desc = get_flow_desc(repo, flow_session.course,
                flow_session.flow_id, commit_sha)

    if flow_session.page_data_at_revision_key == revision_key:
        return

    new_page_count = _adjust_flow_session_page_data_inner(
            repo, flow_session, course_identifier, flow_desc,
            commit_sha)

    # These are idempotent, so they don't need to be guarded by a seqcst
    # transaction.
    flow_session.page_count = new_page_count
    flow_session.page_data_at_revision_key = revision_key
    flow_session.save()

# }}}


# {{{ grade page visit

def grade_page_visit(visit, visit_grade_model=FlowPageVisitGrade,
        grade_data=None, respect_preview=True):
    # type: (FlowPageVisit, type, Any, bool) -> None
    if not visit.is_submitted_answer:
        raise RuntimeError(_("cannot grade ungraded answer"))

    flow_session = visit.flow_session
    course = flow_session.course
    page_data = visit.page_data

    most_recent_grade = visit.get_most_recent_grade()  # type: Optional[FlowPageVisitGrade]  # noqa
    if most_recent_grade is not None and grade_data is None:
        grade_data = most_recent_grade.grade_data

    from course.content import (
            get_course_repo,
            get_course_commit_sha,
            get_flow_desc,
            get_flow_page_desc,
            instantiate_flow_page)

    with get_course_repo(course) as repo:
        course_commit_sha = get_course_commit_sha(
                course, flow_session.participation if respect_preview else None)

        flow_desc = get_flow_desc(repo, course,
                flow_session.flow_id, course_commit_sha)

        page_desc = get_flow_page_desc(
                flow_session.flow_id,
                flow_desc,
                page_data.group_id, page_data.page_id)

        page = instantiate_flow_page(
                location="flow '%s', group, '%s', page '%s'"
                % (flow_session.flow_id, page_data.group_id, page_data.page_id),
                repo=repo, page_desc=page_desc,
                commit_sha=course_commit_sha)

        assert page.expects_answer()
        if not page.is_answer_gradable():
            return

        from course.page import PageContext
        grading_page_context = PageContext(
                course=course,
                repo=repo,
                commit_sha=course_commit_sha,
                flow_session=flow_session)

        with LanguageOverride(course=course):
            answer_feedback = page.grade(
                    grading_page_context, visit.page_data.data,
                    visit.answer, grade_data=grade_data)

        grade = visit_grade_model()
        grade.visit = visit
        grade.grade_data = grade_data
        grade.max_points = page.max_points(visit.page_data)
        grade.graded_at_git_commit_sha = course_commit_sha.decode()

        bulk_feedback_json = None
        if answer_feedback is not None:
            grade.correctness = answer_feedback.correctness
            grade.feedback, bulk_feedback_json = answer_feedback.as_json()

        grade.save()

        update_bulk_feedback(page_data, grade, bulk_feedback_json)

# }}}


# {{{ start flow

def start_flow(
        repo,  # type: Repo_ish
        course,  # type: Course
        participation,  # type: Optional[Participation]
        user,  # type: Any
        flow_id,  # type: Text
        flow_desc,  # type: FlowDesc
        session_start_rule,  # type: FlowSessionStartRule
        now_datetime,  # type: datetime.datetime
        ):
    # type: (...) -> FlowSession

    # This function does not need to be transactionally atomic.
    # The only essential part is the creation of the session.
    # The remainder of the function (opportunity creation and
    # page setup) is atomic and gets retried.

    from course.content import get_course_commit_sha
    course_commit_sha = get_course_commit_sha(course, participation)

    if participation is not None:
        assert participation.user == user

    exp_mode = flow_session_expiration_mode.end
    if session_start_rule.default_expiration_mode is not None:
        exp_mode = session_start_rule.default_expiration_mode

    assert exp_mode in dict(FLOW_SESSION_EXPIRATION_MODE_CHOICES)

    session = FlowSession(
        course=course,
        participation=participation,
        user=user,
        active_git_commit_sha=course_commit_sha.decode(),
        flow_id=flow_id,
        start_time=now_datetime,
        in_progress=True,
        expiration_mode=exp_mode,
        access_rules_tag=session_start_rule.tag_session)

    session.save()

    # Create flow grading opportunity. This makes the flow
    # show up in the grade book.

    rules = getattr(flow_desc, "rules", None)
    if rules is not None:
        identifier = rules.grade_identifier

        if identifier is not None:
            from course.models import get_flow_grading_opportunity
            get_flow_grading_opportunity(
                    course, flow_id, flow_desc,
                    identifier,
                    rules.grade_aggregation_strategy)

    # will implicitly modify and save the session if there are changes
    adjust_flow_session_page_data(repo, session,
            course.identifier, flow_desc, respect_preview=True)

    return session

# }}}


# {{{ finish flow

def get_multiple_flow_session_graded_answers_qset(flow_sessions):
    # type: (List[FlowSession]) -> query.QuerySet

    from django.db.models import Q
    qset = (FlowPageVisit.objects
            .filter(flow_session__in=flow_sessions)
            .filter(Q(answer__isnull=False) | Q(is_synthetic=True))
            .order_by("flow_session__id"))

    # Ungraded answers *can* show up in non-in-progress flows as a result
    # of a race between a 'save' and the 'end session'. If this happens,
    # we'll go ahead and ignore those.
    qset = qset.filter(
        (Q(flow_session__in_progress=False) & Q(is_submitted_answer=True))
        | Q(flow_session__in_progress=True))

    return qset


def get_flow_session_graded_answers_qset(flow_session):
    # type: (FlowSession) -> query.QuerySet

    return get_multiple_flow_session_graded_answers_qset([flow_session])


def get_prev_answer_visits_qset(page_data):
    # type: (FlowPageData) -> query.QuerySet
    return (
            get_flow_session_graded_answers_qset(page_data.flow_session)
            .filter(page_data=page_data)
            .order_by("-visit_time"))


def get_first_from_qset(qset):
    # type: (query.QuerySet) -> Optional[Any]
    for item in qset[:1]:
        return item

    return None


def get_prev_answer_visit(page_data):
    return get_first_from_qset(get_prev_answer_visits_qset(page_data))


def assemble_page_grades(flow_sessions):
    # type: (List[FlowSession]) -> List[List[Optional[FlowPageVisitGrade]]]
    """
    Given a list of flow sessions, return a list of lists of FlowPageVisitGrade
    objects corresponding to the most recent page grades for each page of the
    flow session.  If a page is not graded, the corresponding entry is None.

    Note that, even if the flow sessions belong to the same flow, the length
    of the lists may vary since the flow page count may vary per session.
    """
    id_to_fsess_idx = {fsess.id: i for i, fsess in enumerate(flow_sessions)}
    answer_visit_ids = [
            [None] * fsess.page_count for fsess in flow_sessions
            ]  # type: List[List[Optional[int]]]

    # Get all answer visits corresponding to the sessions. The query result is
    # typically very large.
    all_answer_visits = (
        get_multiple_flow_session_graded_answers_qset(flow_sessions)
        .order_by("visit_time")
        .values("id", "flow_session_id", "page_data__page_ordinal",
                "is_submitted_answer"))

    for answer_visit in all_answer_visits:
        fsess_idx = id_to_fsess_idx[answer_visit["flow_session_id"]]
        page_ordinal = answer_visit["page_data__page_ordinal"]
        if page_ordinal is not None:
            answer_visit_ids[fsess_idx][page_ordinal] = answer_visit["id"]

        if not flow_sessions[fsess_idx].in_progress:
            assert answer_visit["is_submitted_answer"] is True

    flat_answer_visit_ids = []
    for visit_id_list in answer_visit_ids:
        for visit_id in visit_id_list:
            if visit_id is not None:
                flat_answer_visit_ids.append(visit_id)

    # Get all grade visits associated with the answer visits.
    grades = (FlowPageVisitGrade.objects
              .filter(visit__in=flat_answer_visit_ids)
              .order_by("visit__id")
              .order_by("grade_time"))

    grades_by_answer_visit = {}
    for grade in grades:
        grades_by_answer_visit[grade.visit_id] = grade

    def get_grades_for_visit_group(visit_group):
        # type: (List[Optional[int]]) -> List[Optional[FlowPageVisit]]

        return [grades_by_answer_visit.get(visit_id)
            for visit_id in visit_group]

    return [get_grades_for_visit_group(group) for group in answer_visit_ids]


def assemble_answer_visits(flow_session):
    # type: (FlowSession) -> List[Optional[FlowPageVisit]]

    answer_visits = [None] * flow_session.page_count  # type: List[Optional[FlowPageVisit]]  # noqa

    answer_page_visits = (
            get_flow_session_graded_answers_qset(flow_session)
            .order_by("visit_time"))

    for page_visit in answer_page_visits:
        if page_visit.page_data.page_ordinal is not None:
            answer_visits[page_visit.page_data.page_ordinal] = page_visit

        if not flow_session.in_progress:
            assert page_visit.is_submitted_answer is True

    return answer_visits


def get_all_page_data(flow_session):
    # type: (FlowSession) -> Iterable[FlowPageData]

    return (FlowPageData.objects
            .filter(
                flow_session=flow_session,
                page_ordinal__isnull=False)
            .order_by("page_ordinal"))


def get_interaction_kind(
        fctx,  # type: FlowContext
        flow_session,  # type: FlowSession
        flow_generates_grade,  # type: bool
        all_page_data,  # type: Iterable[FlowPageData]
        ):
    # type: (...) -> Text

    has_interactive = False
    has_gradable = False

    for i, page_data in enumerate(all_page_data):
        assert i == page_data.page_ordinal

        page = instantiate_flow_page_with_ctx(fctx, page_data)
        if page.expects_answer():
            has_interactive = True
            if page.is_answer_gradable():
                has_gradable = True

    if has_interactive:
        if has_gradable:
            if flow_generates_grade:
                return flow_session_interaction_kind.permanent_grade
            else:
                return flow_session_interaction_kind.practice_grade
        else:
            return flow_session_interaction_kind.ungraded
    else:
        return flow_session_interaction_kind.noninteractive


def get_session_answered_page_data(
        fctx,  # type: FlowContext
        flow_session,  # type: FlowSession
        answer_visits  # type: List[Optional[FlowPageVisit]]
        ):
    # type: (...) -> Tuple[List[FlowPageData], List[FlowPageData], bool]
    all_page_data = get_all_page_data(flow_session)

    answered_page_data_list = []  # type: List[FlowPageData]
    unanswered_page_data_list = []  # type: List[FlowPageData]
    is_interactive_flow = False  # type: bool

    for i, page_data in enumerate(all_page_data):
        assert i == page_data.page_ordinal

        avisit = answer_visits[i]
        if avisit is not None:
            answer_data = avisit.answer
        else:
            answer_data = None

        page = instantiate_flow_page_with_ctx(fctx, page_data)
        if page.expects_answer():
            is_interactive_flow = True
            if not page.is_optional_page:
                if answer_data is None:
                    unanswered_page_data_list.append(page_data)
                else:
                    answered_page_data_list.append(page_data)

    return (answered_page_data_list, unanswered_page_data_list, is_interactive_flow)


class GradeInfo(object):
    """An object to hold a tally of points and page counts of various types in a flow.

    .. attribute:: points

        The final grade, in points. May be *None* if the grade is not yet
        final.
    """

    def __init__(
            self,
            points,  # type: Optional[float]
            provisional_points,  # type: Optional[float]
            max_points,  # type: Optional[float]
            max_reachable_points,  # type: Optional[float]
            fully_correct_count,  # type: int
            partially_correct_count,  # type: int
            incorrect_count,  # type: int
            unknown_count,  # type: int
            optional_fully_correct_count=0,  # type: int
            optional_partially_correct_count=0,  # type: int
            optional_incorrect_count=0,  # type: int
            optional_unknown_count=0,  # type: int
            ):
        # type: (...) -> None
        self.points = points
        self.provisional_points = provisional_points
        self.max_points = max_points
        self.max_reachable_points = max_reachable_points
        self.fully_correct_count = fully_correct_count
        self.partially_correct_count = partially_correct_count
        self.incorrect_count = incorrect_count
        self.unknown_count = unknown_count
        self.optional_fully_correct_count = optional_fully_correct_count
        self.optional_partially_correct_count = optional_partially_correct_count
        self.optional_incorrect_count = optional_incorrect_count
        self.optional_unknown_count = optional_unknown_count

    # Rounding to larger than 100% will break the percent bars on the
    # flow results page.
    FULL_PERCENT = 99.99

    # {{{ point percentages

    def points_percent(self):
        """Only to be used for visualization purposes."""

        if self.max_points is None or self.max_points == 0:
            if self.points == 0:
                return 100
            else:
                return 0
        else:
            return self.FULL_PERCENT*self.provisional_points/self.max_points

    def missed_points_percent(self):
        """Only to be used for visualization purposes."""

        return (self.FULL_PERCENT
                - self.points_percent()
                - self.unreachable_points_percent())

    def unreachable_points_percent(self):
        """Only to be used for visualization purposes."""

        if (self.max_points is None
                or self.max_reachable_points is None
                or self.max_points == 0):
            return 0
        else:
            return self.FULL_PERCENT*(
                    self.max_points - self.max_reachable_points)/self.max_points

    def total_points_percent(self):
        return (
                self.points_percent()
                + self.missed_points_percent()
                + self.unreachable_points_percent())

    # }}}

    # {{{ page counts

    def total_count(self):
        return (self.fully_correct_count
                + self.partially_correct_count
                + self.incorrect_count
                + self.unknown_count)

    def fully_correct_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT*self.fully_correct_count/self.total_count()

    def partially_correct_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT*self.partially_correct_count/self.total_count()

    def incorrect_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT*self.incorrect_count/self.total_count()

    def unknown_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT*self.unknown_count/self.total_count()

    def optional_total_count(self):
        return (self.optional_fully_correct_count
                + self.optional_partially_correct_count
                + self.optional_incorrect_count
                + self.optional_unknown_count)

    def optional_fully_correct_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT * self.optional_fully_correct_count\
               / self.optional_total_count()

    def optional_partially_correct_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT * self.optional_partially_correct_count\
               / self.optional_total_count()

    def optional_incorrect_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT * self.optional_incorrect_count\
               / self.optional_total_count()

    def optional_unknown_percent(self):
        """Only to be used for visualization purposes."""
        return self.FULL_PERCENT * self.optional_unknown_count\
               / self.optional_total_count()

    # }}}


def gather_grade_info(
        fctx,  # type: FlowContext
        flow_session,  # type: FlowSession
        grading_rule,  # type: FlowSessionGradingRule
        answer_visits,  # type: List[Optional[FlowPageVisit]]
        ):
    # type: (...) -> GradeInfo
    """
    :returns: a :class:`GradeInfo`
    """

    all_page_data = get_all_page_data(flow_session)

    bonus_points = grading_rule.bonus_points
    points = bonus_points
    provisional_points = bonus_points
    max_points = bonus_points
    max_reachable_points = bonus_points

    fully_correct_count = 0
    partially_correct_count = 0
    incorrect_count = 0
    unknown_count = 0

    optional_fully_correct_count = 0
    optional_partially_correct_count = 0
    optional_incorrect_count = 0
    optional_unknown_count = 0

    for i, page_data in enumerate(all_page_data):
        page = instantiate_flow_page_with_ctx(fctx, page_data)

        assert i == page_data.page_ordinal

        av = answer_visits[i]

        if av is None:
            # This is true in principle, but early code to deal with survey questions
            # didn't generate synthetic answer visits for survey questions, so this
            # can't actually be enforced.

            # assert not page.expects_answer()
            continue

        if not page.is_answer_gradable():
            continue

        grade = av.get_most_recent_grade()
        assert grade is not None

        feedback = get_feedback_for_grade(grade)

        if page.is_optional_page:
            if feedback is None or feedback.correctness is None:
                optional_unknown_count += 1
                continue

            if feedback.correctness == 1:
                optional_fully_correct_count += 1
            elif feedback.correctness == 0:
                optional_incorrect_count += 1
            else:
                optional_partially_correct_count += 1

        else:
            max_points += grade.max_points

            if feedback is None or feedback.correctness is None:
                unknown_count += 1
                points = None
                continue

            max_reachable_points += grade.max_points

            page_points = grade.max_points*feedback.correctness

            if points is not None:
                points += page_points

            provisional_points += page_points

            if grade.max_points > 0:
                if feedback.correctness == 1:
                    fully_correct_count += 1
                elif feedback.correctness == 0:
                    incorrect_count += 1
                else:
                    partially_correct_count += 1

    # {{{ adjust max_points if requested

    if grading_rule.max_points is not None:
        max_points = grading_rule.max_points

    # }}}

    # {{{ enforce points cap

    if grading_rule.max_points_enforced_cap is not None:
        max_reachable_points = min(
                max_reachable_points, grading_rule.max_points_enforced_cap)
        if points is not None:
            points = min(
                    points, grading_rule.max_points_enforced_cap)
        assert provisional_points is not None
        provisional_points = min(
                provisional_points, grading_rule.max_points_enforced_cap)

    # }}}

    return GradeInfo(
            points=points,
            provisional_points=provisional_points,
            max_points=max_points,
            max_reachable_points=max_reachable_points,

            fully_correct_count=fully_correct_count,
            partially_correct_count=partially_correct_count,
            incorrect_count=incorrect_count,
            unknown_count=unknown_count,

            optional_fully_correct_count=optional_fully_correct_count,
            optional_partially_correct_count=optional_partially_correct_count,
            optional_incorrect_count=optional_incorrect_count,
            optional_unknown_count=optional_unknown_count)


@transaction.atomic
def grade_page_visits(
        fctx,  # type: FlowContext
        flow_session,  # type: FlowSession
        answer_visits,  # type: List[Optional[FlowPageVisit]]
        force_regrade=False,  # type: bool
        respect_preview=True,  # type: bool
        ):
    # type: (...) -> None
    for i in range(len(answer_visits)):
        answer_visit = answer_visits[i]

        if answer_visit is not None:
            answer_visit.is_submitted_answer = True
            answer_visit.save()

        else:
            page_data = flow_session.page_data.get(page_ordinal=i)
            page = instantiate_flow_page_with_ctx(fctx, page_data)

            if not page.expects_answer():
                continue

            # Create a synthetic visit to attach a grade
            new_answer_visit = FlowPageVisit()

            new_answer_visit.flow_session = flow_session
            new_answer_visit.page_data = page_data
            new_answer_visit.is_synthetic = True
            new_answer_visit.answer = None
            new_answer_visit.is_submitted_answer = True
            new_answer_visit.save()

            answer_visits[i] = answer_visit = new_answer_visit

            if not page.is_answer_gradable():
                continue

        assert answer_visit is not None
        if not answer_visit.grades.count() or force_regrade:  # type: ignore
            grade_page_visit(answer_visit, respect_preview=respect_preview)


@retry_transaction_decorator()
def finish_flow_session(fctx, flow_session, grading_rule,
        force_regrade=False, now_datetime=None, respect_preview=True):
    """
    :returns: :class:`GradeInfo`
    """
    # Do not be tempted to call adjust_flow_session_page_data in here.
    # This function may be called from within a transaction.

    if not flow_session.in_progress:
        raise RuntimeError(_("Can't end a session that's already ended"))

    assert isinstance(grading_rule, FlowSessionGradingRule)

    if now_datetime is None:
        from django.utils.timezone import now
        now_datetime = now()

    answer_visits = assemble_answer_visits(flow_session)

    grade_page_visits(fctx, flow_session, answer_visits,
            force_regrade=force_regrade,
            respect_preview=respect_preview)

    # ORDERING RESTRICTION: Must grade pages before gathering grade info

    # {{{ determine completion time

    completion_time = now_datetime
    if grading_rule.use_last_activity_as_completion_time:
        last_activity = flow_session.last_activity()
        if last_activity is not None:
            completion_time = last_activity

    flow_session.completion_time = completion_time

    # }}}

    flow_session.in_progress = False
    flow_session.save()

    return grade_flow_session(fctx, flow_session, grading_rule,
            answer_visits)


def expire_flow_session(
        fctx,  # type: FlowContext
        flow_session,  # type: FlowSession
        grading_rule,  # type: FlowSessionGradingRule
        now_datetime,  # type: datetime.datetime
        past_due_only=False,  # type:bool
        ):
    # type: (...) -> bool

    # This function does not need to be transactionally atomic.
    # It only does one atomic 'thing' in each execution path.

    if not flow_session.in_progress:
        raise RuntimeError(_("Can't expire a session that's not in progress"))
    if flow_session.participation is None:
        raise RuntimeError(_("Can't expire an anonymous flow session"))

    assert isinstance(grading_rule, FlowSessionGradingRule)

    if past_due_only:
        if grading_rule.due is None:
            return False
        elif now_datetime < grading_rule.due:
            return False

    adjust_flow_session_page_data(fctx.repo, flow_session,
            flow_session.course.identifier, fctx.flow_desc,
            respect_preview=False)

    if flow_session.expiration_mode == flow_session_expiration_mode.roll_over:
        session_start_rule = get_session_start_rule(
                flow_session.course, flow_session.participation,
                flow_session.flow_id, fctx.flow_desc, now_datetime,
                for_rollover=True)

        if not session_start_rule.may_start_new_session:
            # No new session allowed: finish.
            finish_flow_session(fctx, flow_session, grading_rule,
                                now_datetime=now_datetime, respect_preview=False)
            return True
        else:

            flow_session.access_rules_tag = session_start_rule.tag_session

            # {{{ FIXME: This is weird and should probably not exist.

            access_rule = get_session_access_rule(
                    flow_session, fctx.flow_desc, now_datetime)

            if session_start_rule.default_expiration_mode is not None:
                flow_session.expiration_mode = \
                        session_start_rule.default_expiration_mode

            elif not is_expiration_mode_allowed(
                    flow_session.expiration_mode, access_rule.permissions):
                flow_session.expiration_mode = flow_session_expiration_mode.end

            # }}}

            flow_session.save()

            return True

    elif flow_session.expiration_mode == flow_session_expiration_mode.end:
        finish_flow_session(fctx, flow_session, grading_rule,
                            now_datetime=now_datetime, respect_preview=False)
        return True
    else:
        raise ValueError(
                _("invalid expiration mode '%(mode)s' on flow session ID "
                "%(session_id)d") % {
                    "mode": flow_session.expiration_mode,
                    "session_id": flow_session.id})


def get_flow_session_attempt_id(flow_session):
    # type: (FlowSession) -> Text
    return "flow-session-%d" % flow_session.id


def grade_flow_session(
        fctx,  # type: FlowContext
        flow_session,  # type: FlowSession
        grading_rule,  # type: FlowSessionGradingRule
        answer_visits=None,  # type: Optional[List[Optional[FlowPageVisit]]]
        ):
    # type: (...) -> GradeInfo

    """Updates the grade on an existing flow session and logs a
    grade change with the grade records subsystem.
    """

    if answer_visits is None:
        answer_visits = assemble_answer_visits(flow_session)

    grade_info = gather_grade_info(fctx, flow_session, grading_rule, answer_visits)
    assert grade_info is not None

    comment = None
    points = grade_info.points

    if (points is not None
            and grading_rule.credit_percent is not None
            and grading_rule.credit_percent != 100):
        comment = (
                # Translators: grade flow: calculating grade.
                _("Counted at %(percent).1f%% of %(point).1f points") % {
                    "percent": grading_rule.credit_percent,
                    "point": points})
        points = points * grading_rule.credit_percent / 100

    flow_session.points = points
    flow_session.max_points = grade_info.max_points

    flow_session.append_comment(comment)
    flow_session.save()

    # Need to save grade record even if no grade is available yet, because
    # a grade record may *already* be saved, and that one might be mistaken
    # for the current one.
    if (grading_rule.grade_identifier
            and grading_rule.generates_grade
            and flow_session.participation is not None):
        from course.models import get_flow_grading_opportunity
        gopp = get_flow_grading_opportunity(
                flow_session.course, flow_session.flow_id, fctx.flow_desc,
                grading_rule.grade_identifier,
                grading_rule.grade_aggregation_strategy)

        from course.models import grade_state_change_types
        gchange = GradeChange()
        gchange.opportunity = gopp
        gchange.participation = flow_session.participation
        gchange.state = grade_state_change_types.graded
        gchange.attempt_id = get_flow_session_attempt_id(flow_session)
        gchange.points = points
        gchange.max_points = grade_info.max_points
        # creator left as NULL
        gchange.flow_session = flow_session
        gchange.comment = comment

        previous_grade_changes = list(GradeChange.objects
                .filter(
                    opportunity=gchange.opportunity,
                    participation=gchange.participation,
                    attempt_id=gchange.attempt_id,
                    flow_session=gchange.flow_session)
                .order_by("-grade_time")
                [:1])

        # only save if modified or no previous grades
        do_save = True
        if previous_grade_changes:
            previous_grade_change, = previous_grade_changes
            if (previous_grade_change.points == gchange.points
                    and previous_grade_change.max_points == gchange.max_points
                    and previous_grade_change.state == gchange.state
                    and previous_grade_change.comment == gchange.comment):
                do_save = False
        else:
            # no previous grade changes
            if points is None:
                do_save = False

        if do_save:
            gchange.save()

    return grade_info


def unsubmit_page(prev_answer_visit, now_datetime):
    # type: (FlowPageVisit, datetime.datetime) -> None

    prev_answer_visit.id = None
    prev_answer_visit.visit_time = now_datetime
    prev_answer_visit.remote_address = None
    prev_answer_visit.user = None
    prev_answer_visit.is_synthetic = True

    assert prev_answer_visit.is_submitted_answer
    prev_answer_visit.is_submitted_answer = False

    prev_answer_visit.save()


def reopen_session(
        now_datetime,  # type: datetime.datetime
        session,  # type: FlowSession
        force=False,  # type: bool
        suppress_log=False,  # type: bool
        unsubmit_pages=False,  # type: bool
        ):
    # type: (...) -> None

    with transaction.atomic():
        if session.in_progress:
            raise RuntimeError(
                    _("Cannot reopen a session that's already in progress"))
        if session.participation is None:
            raise RuntimeError(
                    _("Cannot reopen anonymous sessions"))

        session.in_progress = True
        session.points = None
        session.max_points = None

        if not suppress_log:
            session.append_comment(
                    _("Session reopened at %(now)s, previous completion time "
                    "was '%(complete_time)s'.") % {
                        "now": format_datetime_local(now_datetime),
                        "complete_time": format_datetime_local(
                            as_local_time(session.completion_time))
                        })

        session.completion_time = None
        session.save()

        if unsubmit_pages:
            answer_visits = assemble_answer_visits(session)

            for visit in answer_visits:
                if visit is not None:
                    unsubmit_page(visit, now_datetime)


def finish_flow_session_standalone(
        repo,  # type: Repo_ish
        course,  # type: Course
        session,  # type: FlowSession
        force_regrade=False,  # type: bool
        now_datetime=None,  # type: Optional[datetime.datetime]
        past_due_only=False,  # type: bool
        respect_preview=True,  # type:bool
        ):
    # type: (...) -> bool

    # Do not be tempted to call adjust_flow_session_page_data in here.
    # This function may be called from within a transaction.

    assert session.participation is not None

    if now_datetime is None:
        from django.utils.timezone import now
        now_datetime_filled = now()
    else:
        now_datetime_filled = now_datetime

    fctx = FlowContext(repo, course, session.flow_id)

    grading_rule = get_session_grading_rule(session, fctx.flow_desc,
            now_datetime_filled)

    if past_due_only:
        if grading_rule.due is None:
            return False
        elif now_datetime_filled < grading_rule.due:
            return False

    finish_flow_session(fctx, session, grading_rule,
            force_regrade=force_regrade,
            now_datetime=now_datetime_filled,
            respect_preview=respect_preview)

    return True


def expire_flow_session_standalone(
        repo,  # type: Any
        course,  # type: Course
        session,  # type: FlowSession
        now_datetime,  # type: datetime.datetime
        past_due_only=False,  # type: bool
        ):
    # type: (...) -> bool
    assert session.participation is not None

    fctx = FlowContext(repo, course, session.flow_id)

    grading_rule = get_session_grading_rule(session, fctx.flow_desc, now_datetime)

    return expire_flow_session(fctx, session, grading_rule, now_datetime,
            past_due_only=past_due_only)


def regrade_session(
        repo,  # type: Repo_ish
        course,  # type: Course
        session,  # type: FlowSession
        ):
    # type: (...) -> None
    adjust_flow_session_page_data(repo, session, course.identifier,
            respect_preview=False)

    if session.in_progress:
        with transaction.atomic():
            answer_visits = assemble_answer_visits(session)  # type: List[Optional[FlowPageVisit]]  # noqa

            for i in range(len(answer_visits)):
                answer_visit = answer_visits[i]

                if answer_visit is not None:
                    if answer_visit.get_most_recent_grade():
                        # Only make a new grade if there already is one.
                        grade_page_visit(answer_visit, respect_preview=False)
    else:
        prev_completion_time = session.completion_time

        now_datetime = local_now()
        with transaction.atomic():
            session.append_comment(
                    _("Session regraded at %(time)s.") % {
                        "time": format_datetime_local(now_datetime)
                        })
            session.save()

            reopen_session(now_datetime, session, force=True, suppress_log=True)
            finish_flow_session_standalone(
                    repo, course, session, force_regrade=True,
                    now_datetime=prev_completion_time,
                    respect_preview=False)


def recalculate_session_grade(repo, course, session):
    # type: (Repo_ish, Course, FlowSession) -> None

    """Only redoes the final grade determination without regrading
    individual pages.
    """

    if session.in_progress:
        raise RuntimeError(_("cannot recalculate grade on in-progress session"))

    prev_completion_time = session.completion_time

    adjust_flow_session_page_data(repo, session, course.identifier,
            respect_preview=False)

    with transaction.atomic():
        now_datetime = local_now()
        session.append_comment(
                _("Session grade recomputed at %(time)s.") % {
                    "time": format_datetime_local(now_datetime)
                    })
        session.save()

        reopen_session(now_datetime, session, force=True, suppress_log=True)
        finish_flow_session_standalone(
                repo, course, session, force_regrade=False,
                now_datetime=prev_completion_time,
                respect_preview=False)

# }}}


def lock_down_if_needed(
        request,  # type: http.HttpRequest
        permissions,  # type: FrozenSet[Text]
        flow_session,  # type: FlowSession
        ):
    # type: (...) -> None

    if flow_permission.lock_down_as_exam_session in permissions:
        request.session[
                "relate_session_locked_to_exam_flow_session_pk"] = \
                        flow_session.pk


# {{{ view: start flow

@course_view
def view_start_flow(pctx, flow_id):
    # type: (CoursePageContext, Text) -> http.HttpResponse
    request = pctx.request

    fctx = FlowContext(pctx.repo, pctx.course, flow_id,
            participation=pctx.participation)

    if request.method == "POST":
        return post_start_flow(pctx, fctx, flow_id)

    login_exam_ticket = get_login_exam_ticket(pctx.request)
    now_datetime = get_now_or_fake_time(request)

    session_start_rule = get_session_start_rule(
            pctx.course, pctx.participation,
            flow_id, fctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    if session_start_rule.may_list_existing_sessions:
        past_sessions = (FlowSession.objects
                .filter(
                    participation=pctx.participation,
                    flow_id=fctx.flow_id,
                    participation__isnull=False)
               .order_by("start_time"))

        from collections import namedtuple
        SessionProperties = namedtuple("SessionProperties",  # noqa
                ["may_view", "may_modify", "due", "grade_description",
                    "grade_shown"])

        past_sessions_and_properties = []
        for session in past_sessions:
            access_rule = get_session_access_rule(
                    session, fctx.flow_desc, now_datetime,
                    facilities=pctx.request.relate_facilities,
                    login_exam_ticket=login_exam_ticket)
            grading_rule = get_session_grading_rule(
                    session, fctx.flow_desc, now_datetime)

            session_properties = SessionProperties(
                    may_view=flow_permission.view in access_rule.permissions,
                    may_modify=(
                        flow_permission.submit_answer in access_rule.permissions
                        or flow_permission.end_session in access_rule.permissions
                        ),
                    due=grading_rule.due,
                    grade_description=grading_rule.description,
                    grade_shown=(
                        flow_permission.cannot_see_flow_result
                        not in access_rule.permissions))
            past_sessions_and_properties.append((session, session_properties))
    else:
        past_sessions_and_properties = []

    may_start = session_start_rule.may_start_new_session
    new_session_grading_rule = None
    start_may_decrease_grade = False
    grade_aggregation_strategy_descr = None

    if may_start:
        potential_session = FlowSession(
            course=pctx.course,
            participation=pctx.participation,
            flow_id=flow_id,
            in_progress=True,

            # default_expiration_mode ignored
            expiration_mode=flow_session_expiration_mode.end,

            access_rules_tag=session_start_rule.tag_session)

        new_session_grading_rule = get_session_grading_rule(
                potential_session, fctx.flow_desc, now_datetime)

        start_may_decrease_grade = (
                bool(past_sessions_and_properties)
                and new_session_grading_rule.grade_aggregation_strategy
                not in [
                    None,
                    grade_aggregation_strategy.max_grade,
                    grade_aggregation_strategy.use_earliest])

        grade_aggregation_strategy_descr = (
            dict(GRADE_AGGREGATION_STRATEGY_CHOICES).get(
                new_session_grading_rule.grade_aggregation_strategy))

    return render_course_page(pctx, "course/flow-start.html", {
        "flow_desc": fctx.flow_desc,
        "flow_identifier": flow_id,

        "now": now_datetime,
        "may_start": may_start,
        "new_session_grading_rule": new_session_grading_rule,
        "grade_aggregation_strategy_descr": grade_aggregation_strategy_descr,
        "start_may_decrease_grade": start_may_decrease_grade,
        "past_sessions_and_properties": past_sessions_and_properties,
        },
        allow_instant_flow_requests=False)


@retry_transaction_decorator(serializable=True)
def post_start_flow(pctx, fctx, flow_id):
    # type: (CoursePageContext, FlowContext, Text) -> http.HttpResponse

    now_datetime = get_now_or_fake_time(pctx.request)
    login_exam_ticket = get_login_exam_ticket(pctx.request)

    past_sessions = (FlowSession.objects
            .filter(
                participation=pctx.participation,
                flow_id=fctx.flow_id,
                participation__isnull=False)
           .order_by("start_time"))

    if past_sessions:
        latest_session = past_sessions.reverse()[0]

        cooldown_seconds = getattr(
            settings, "RELATE_SESSION_RESTART_COOLDOWN_SECONDS", 10)

        from datetime import timedelta
        if (
                timedelta(seconds=0)
                <= (now_datetime - latest_session.start_time)
                < timedelta(seconds=cooldown_seconds)):
            return redirect("relate-view_flow_page",
                pctx.course.identifier, latest_session.id, 0)

    session_start_rule = get_session_start_rule(
            pctx.course, pctx.participation,
            flow_id, fctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    if not session_start_rule.may_start_new_session:
        raise PermissionDenied(_("new session not allowed"))

    flow_user = pctx.request.user
    if not flow_user.is_authenticated:
        flow_user = None

    session = start_flow(
            pctx.repo, pctx.course, pctx.participation,
            user=flow_user,
            flow_id=flow_id, flow_desc=fctx.flow_desc,
            session_start_rule=session_start_rule,
            now_datetime=now_datetime)

    access_rule = get_session_access_rule(
            session, fctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    lock_down_if_needed(pctx.request, access_rule.permissions, session)

    return redirect("relate-view_flow_page",
            pctx.course.identifier, session.id, 0)

# }}}


# {{{ view: resume flow

# The purpose of this interstitial redirection page is to set the exam
# lockdown flag upon resumption/review. Without this, the exam lockdown
# middleware will refuse access to flow pages in a locked-down facility.

@course_view
def view_resume_flow(pctx, flow_session_id):
    # type: (CoursePageContext, int) -> http.HttpResponse

    now_datetime = get_now_or_fake_time(pctx.request)

    flow_session = get_and_check_flow_session(pctx, int(flow_session_id))

    fctx = FlowContext(pctx.repo, pctx.course, flow_session.flow_id,
            participation=pctx.participation)

    login_exam_ticket = get_login_exam_ticket(pctx.request)

    access_rule = get_session_access_rule(
            flow_session, fctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    lock_down_if_needed(pctx.request, access_rule.permissions,
            flow_session)

    return redirect("relate-view_flow_page",
            pctx.course.identifier, flow_session.id, 0)


# }}}


# {{{ view: flow page

def get_and_check_flow_session(pctx, flow_session_id):
    # type: (CoursePageContext, int) -> FlowSession

    try:
        flow_session = (FlowSession.objects
                .select_related("participation")
                .get(id=flow_session_id))
    except ObjectDoesNotExist:
        raise http.Http404()

    if flow_session.course.pk != pctx.course.pk:
        raise http.Http404()

    my_session = (
            pctx.participation == flow_session.participation
            or (
                # anonymous by participation
                flow_session.participation is None
                and (
                    # We don't know whose (legacy)
                    # Truly anonymous sessions belong to everyone.
                    flow_session.user is None
                    or pctx.request.user == flow_session.user)))

    if not my_session:
        my_perms = pctx.permissions()

        from course.enrollment import get_participation_role_identifiers
        owner_roles = get_participation_role_identifiers(
                pctx.course, flow_session.participation)

        allowed = False
        for orole in owner_roles:
            for perm, arg in my_perms:
                if (
                        perm == pperm.view_flow_sessions_from_role
                        and arg == orole):
                    allowed = True
                    break

            if allowed:
                break

        if not allowed:
            raise PermissionDenied(_("may not view other people's sessions"))

    return flow_session


def will_receive_feedback(permissions):
    # type: (FrozenSet[Text]) -> bool

    return (
            flow_permission.see_correctness in permissions
            or flow_permission.see_answer_after_submission in permissions)


def may_send_email_about_flow_page(flow_session, permissions):
    # type: (FlowSession, FrozenSet[Text]) -> bool

    return (
        flow_session.participation is not None
        and flow_session.user is not None
        and flow_permission.send_email_about_flow_page in permissions)


def get_page_behavior(
        page,  # type: PageBase
        permissions,  # type: FrozenSet[Text]
        session_in_progress,  # type: bool
        answer_was_graded,  # type: bool
        generates_grade,  # type: bool
        is_unenrolled_session,  # type: bool
        viewing_prior_version=False,  # type: bool
        ):
    # type: (...) -> PageBehavior
    show_correctness = False

    if page.expects_answer():
        if answer_was_graded:
            show_correctness = flow_permission.see_correctness in permissions

            show_answer = flow_permission.see_answer_after_submission in permissions

            if session_in_progress:
                # Don't reveal the answer if they can still change their mind
                show_answer = (show_answer
                        and flow_permission.change_answer not in permissions)

            show_answer = show_answer or (
                    flow_permission.see_answer_before_submission in permissions)
        else:
            # Don't show answer yet
            show_answer = (
                    flow_permission.see_answer_before_submission in permissions)
    else:
        show_answer = (
                flow_permission.see_answer_before_submission in permissions
                or flow_permission.see_answer_after_submission in permissions)

    may_change_answer = (
            not viewing_prior_version

            and (not answer_was_graded
                or (flow_permission.change_answer in permissions))

            # can happen if no answer was ever saved
            and session_in_progress

            and (flow_permission.submit_answer in permissions)

            and (generates_grade and not is_unenrolled_session
                or (not generates_grade))
            )

    from course.page.base import PageBehavior  # noqa
    return PageBehavior(
            show_correctness=show_correctness,
            show_answer=show_answer,
            may_change_answer=may_change_answer,
            )


def add_buttons_to_form(form, fpctx, flow_session, permissions):
    # type: (StyledForm, FlowPageContext, FlowSession, FrozenSet[Text]) -> StyledForm

    from crispy_forms.layout import Submit
    show_save_button = getattr(form, "show_save_button", True)
    if show_save_button:
        form.helper.add_input(
                Submit("save", _("Save answer"),
                    css_class="relate-save-button"))

    if will_receive_feedback(permissions):
        if flow_permission.change_answer in permissions:
            form.helper.add_input(
                    Submit(
                        "submit", _("Submit answer for feedback"),
                        accesskey="g",
                        css_class="relate-save-button relate-submit-button"))
        else:
            form.helper.add_input(
                    Submit("submit", _("Submit final answer"),
                        css_class="relate-save-button relate-submit-button"))
    else:
        # Only offer 'save and move on' if student will receive no feedback
        if fpctx.page_data.page_ordinal + 1 < flow_session.page_count:
            form.helper.add_input(
                    Submit("save_and_next",
                        mark_safe_lazy(
                            string_concat(
                                _("Save answer and move on"),
                                " &raquo;")),
                        css_class="relate-save-button"))
        else:
            form.helper.add_input(
                    Submit("save_and_finish",
                        mark_safe_lazy(
                            string_concat(
                                _("Save answer and finish"),
                                " &raquo;")),
                        css_class="relate-save-button"))

    return form


def create_flow_page_visit(request, flow_session, page_data):
    # type: (http.HttpRequest, FlowSession, FlowPageData) -> None

    if request.user.is_authenticated:
        # The access to 'is_authenticated' ought to wake up SimpleLazyObject.
        user = request.user
    else:
        user = None

    visit = FlowPageVisit(
        flow_session=flow_session,
        page_data=page_data,
        remote_address=request.META["REMOTE_ADDR"],
        user=user,
        is_submitted_answer=None)

    if hasattr(request, "relate_impersonate_original_user"):
        visit.impersonated_by = request.relate_impersonate_original_user

    visit.save()


@course_view
def view_flow_page(pctx, flow_session_id, page_ordinal):
    # type: (CoursePageContext, int, int) -> http.HttpResponse

    request = pctx.request
    login_exam_ticket = get_login_exam_ticket(request)

    page_ordinal = int(page_ordinal)

    flow_session_id = int(flow_session_id)
    flow_session = get_and_check_flow_session(pctx, flow_session_id)

    assert flow_session is not None

    flow_id = flow_session.flow_id

    adjust_flow_session_page_data(pctx.repo, flow_session, pctx.course.identifier,
            respect_preview=True)

    try:
        fpctx = FlowPageContext(pctx.repo, pctx.course, flow_id, page_ordinal,
                                participation=pctx.participation,
                                flow_session=flow_session,
                                request=pctx.request)
    except PageOrdinalOutOfRange:
        return redirect("relate-view_flow_page",
                pctx.course.identifier,
                flow_session.id,
                flow_session.page_count-1)

    if fpctx.page is None:
        raise http.Http404()

    assert fpctx.page_context is not None
    assert fpctx.page_data is not None

    now_datetime = get_now_or_fake_time(request)
    access_rule = get_session_access_rule(
            flow_session, fpctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    grading_rule = get_session_grading_rule(
            flow_session, fpctx.flow_desc, now_datetime)
    generates_grade = (
            grading_rule.grade_identifier is not None
            and grading_rule.generates_grade)
    del grading_rule

    permissions = fpctx.page.get_modified_permissions_for_page(
            access_rule.permissions)

    if access_rule.message:
        messages.add_message(request, messages.INFO, access_rule.message)

    lock_down_if_needed(pctx.request, permissions, flow_session)

    page_context = fpctx.page_context
    page_data = fpctx.page_data
    answer_data = None
    grade_data = None

    if flow_permission.view not in permissions:
        raise PermissionDenied(_("not allowed to view flow"))

    answer_visit = None
    prev_visit_id = None
    viewing_prior_version = False

    if request.method == "POST":
        if "finish" in request.POST:
            return redirect("relate-finish_flow_session_view",
                    pctx.course.identifier, flow_session_id)
        else:
            post_result = post_flow_page(
                    flow_session, fpctx, request, permissions, generates_grade)

            if not isinstance(post_result, tuple):
                # ought to be an HTTP response
                return post_result

            (
                page_behavior,
                prev_answer_visits,
                form,
                feedback,
                answer_data,
                answer_was_graded) = post_result

            if prev_answer_visits:
                prev_visit_id = prev_answer_visits[0].id

            # continue at common flow page generation below

    else:
        create_flow_page_visit(request, flow_session, fpctx.page_data)

        prev_answer_visits = list(
                get_prev_answer_visits_qset(fpctx.page_data))

        # {{{ fish out previous answer_visit

        prev_visit_id = pctx.request.GET.get("visit_id")
        if prev_visit_id is not None:
            try:
                prev_visit_id = int(prev_visit_id)
            except ValueError:
                raise SuspiciousOperation("non-integer passed for 'visit_id'")

        if prev_answer_visits and prev_visit_id is not None:
            answer_visit = prev_answer_visits[0]

            for ivisit, pvisit in enumerate(prev_answer_visits):
                if pvisit.id == prev_visit_id:
                    answer_visit = pvisit
                    if ivisit > 0:
                        viewing_prior_version = True

                    break

            if viewing_prior_version:
                from django.template import defaultfilters
                messages.add_message(request, messages.INFO, (
                    _("Viewing prior submission dated %(date)s. ")
                    % {
                        "date": defaultfilters.date(
                            as_local_time(answer_visit.visit_time),
                            "DATETIME_FORMAT"),
                    }
                    + '<a class="btn btn-default btn-sm" href="?" '
                    'role="button">&laquo; %s</a>'
                    % _("Go back")))

            prev_visit_id = answer_visit.id

        elif prev_answer_visits:
            answer_visit = prev_answer_visits[0]
            prev_visit_id = answer_visit.id

        else:
            answer_visit = None

        # }}}

        if answer_visit is not None:
            answer_was_graded = answer_visit.is_submitted_answer
        else:
            answer_was_graded = False

        page_behavior = get_page_behavior(
                page=fpctx.page,
                permissions=permissions,
                session_in_progress=flow_session.in_progress,
                answer_was_graded=answer_was_graded,
                generates_grade=generates_grade,
                is_unenrolled_session=flow_session.participation is None,
                viewing_prior_version=viewing_prior_version)

        if fpctx.page.expects_answer():
            if answer_visit is not None:
                answer_data = answer_visit.answer

                most_recent_grade = answer_visit.get_most_recent_grade()
                if most_recent_grade is not None:
                    feedback = get_feedback_for_grade(most_recent_grade)
                    grade_data = most_recent_grade.grade_data
                else:
                    feedback = None
                    grade_data = None

            else:
                feedback = None

            try:
                form = fpctx.page.make_form(
                        page_context, page_data.data,
                        answer_data, page_behavior)
            except InvalidPageData as e:
                messages.add_message(request, messages.ERROR,
                        gettext(
                            "The page data stored in the database was found "
                            "to be invalid for the page as given in the "
                            "course content. Likely the course content was "
                            "changed in an incompatible way (say, by adding "
                            "an option to a choice question) without changing "
                            "the question ID. The precise error encountered "
                            "was the following: ")+str(e))

                return render_course_page(pctx, "course/course-base.html", {})

        else:
            form = None
            feedback = None

    # start common flow page generation

    # defined at this point:
    # form, page_behavior, answer_was_graded, feedback
    # answer_data, grade_data

    if form is not None and page_behavior.may_change_answer:
        form = add_buttons_to_form(form, fpctx, flow_session,
                permissions)

    shown_feedback = None
    if (fpctx.page.expects_answer() and answer_was_graded
            and (
                page_behavior.show_correctness
                or page_behavior.show_answer)):
        shown_feedback = feedback

    title = fpctx.page.title(page_context, page_data.data)
    body = fpctx.page.body(page_context, page_data.data)

    if page_behavior.show_answer:
        correct_answer = fpctx.page.correct_answer(
                page_context, page_data.data,
                answer_data, grade_data)
    else:
        correct_answer = None

    if (generates_grade
            and flow_session.participation is None
            and flow_permission.submit_answer in permissions):
        messages.add_message(request, messages.INFO,
                _("Changes to this session are being prevented "
                    "because this session yields a permanent grade, but "
                    "you have not completed your enrollment process in "
                    "this course."))

    # {{{ render flow page

    if form is not None:
        form_html = fpctx.page.form_to_html(
                pctx.request, page_context, form, answer_data)
    else:
        form_html = None

    expiration_mode_choices = []

    for key, descr in FLOW_SESSION_EXPIRATION_MODE_CHOICES:
        if is_expiration_mode_allowed(key, permissions):
            expiration_mode_choices.append((key, descr))

    session_minutes = None
    time_factor = 1
    if flow_permission.see_session_time in permissions:
        if not flow_session.in_progress:
            end_time = as_local_time(flow_session.completion_time)
        else:
            end_time = now_datetime
        session_minutes = (
                end_time - flow_session.start_time).total_seconds() / 60
        if flow_session.participation is not None:
            time_factor = flow_session.participation.time_factor

    all_page_data = get_all_page_data(flow_session)

    from django.db import connection
    with connection.cursor() as c:
        c.execute(
                "SELECT DISTINCT course_flowpagedata.page_ordinal "
                "FROM course_flowpagevisit "
                "INNER JOIN course_flowpagedata "
                "ON course_flowpagedata.id = course_flowpagevisit.page_data_id "
                "WHERE course_flowpagedata.flow_session_id = %s "
                "AND course_flowpagevisit.answer IS NOT NULL "
                "ORDER BY course_flowpagedata.page_ordinal",
                [flow_session.id])

        flow_page_ordinals_with_answers = set(row[0] for row in c.fetchall())

    args = {
        "flow_identifier": fpctx.flow_id,
        "flow_desc": fpctx.flow_desc,
        "page_ordinal": fpctx.page_ordinal,
        "page_data": fpctx.page_data,
        "percentage": int(100 * (fpctx.page_ordinal+1) / flow_session.page_count),
        "flow_session": flow_session,
        "all_page_data": all_page_data,
        "flow_page_ordinals_with_answers": flow_page_ordinals_with_answers,

        "title": title, "body": body,
        "form": form,
        "form_html": form_html,

        "feedback": shown_feedback,
        "correct_answer": correct_answer,

        "show_correctness": page_behavior.show_correctness,
        "may_change_answer": page_behavior.may_change_answer,
        "may_change_graded_answer": (
            page_behavior.may_change_answer
            and (flow_permission.change_answer in permissions)),
        "will_receive_feedback": will_receive_feedback(permissions),
        "show_answer": page_behavior.show_answer,
        "may_send_email_about_flow_page":
            may_send_email_about_flow_page(flow_session, permissions),
        "expects_answer": fpctx.page.expects_answer(),

        "session_minutes": session_minutes,
        "time_factor": time_factor,

        "expiration_mode_choices": expiration_mode_choices,
        "expiration_mode_choice_count": len(expiration_mode_choices),
        "expiration_mode": flow_session.expiration_mode,

        "flow_session_interaction_kind": flow_session_interaction_kind,
        "interaction_kind": get_interaction_kind(
            fpctx, flow_session, generates_grade, all_page_data),

        "viewing_prior_version": viewing_prior_version,
        "prev_answer_visits": prev_answer_visits,
        "prev_visit_id": prev_visit_id,

        # Wrappers used by JavaScript template (tmpl) so as not to
        # conflict with Django template's tag wrapper
        "JQ_OPEN": "{%",
        "JQ_CLOSE": "%}",
    }

    if fpctx.page.expects_answer() and fpctx.page.is_answer_gradable():
        args["max_points"] = fpctx.page.max_points(fpctx.page_data)
        args["page_expect_answer_and_gradable"] = True

    if fpctx.page.is_optional_page:
        assert not getattr(args, "max_points", None)
        args["is_optional_page"] = True

    return render_course_page(
            pctx, "course/flow-page.html", args,
            allow_instant_flow_requests=False)

    # }}}


@course_view
def get_prev_answer_visits_dropdown_content(pctx, flow_session_id, page_ordinal):
    """
    :return: serialized prev_answer_visits items for past-submission-dropdown
    """
    request = pctx.request
    if not request.is_ajax() or request.method != "GET":
        raise PermissionDenied()

    page_ordinal = int(page_ordinal)
    flow_session_id = int(flow_session_id)

    flow_session = get_and_check_flow_session(pctx, flow_session_id)

    page_data = get_object_or_404(
        FlowPageData, flow_session=flow_session, page_ordinal=page_ordinal)
    prev_answer_visits = get_prev_answer_visits_qset(page_data)

    def serialize(obj):
        return {
            "id": obj.id,
            "visit_time": (
                format_datetime_local(as_local_time(obj.visit_time))),
            "is_submitted_answer": obj.is_submitted_answer,
        }

    return http.JsonResponse(
        {"result": [serialize(visit) for visit in prev_answer_visits]})


def get_pressed_button(form):
    # type: (StyledForm) -> Text

    buttons = ["save", "save_and_next", "save_and_finish", "submit"]
    for button in buttons:
        if button in form.data:
            return button

    raise SuspiciousOperation(_("could not find which button was pressed"))


@retry_transaction_decorator()
def post_flow_page(
        flow_session,  # type: FlowSession
        fpctx,  # type: FlowPageContext
        request,  # type: http.HttpRequest
        permissions,  # type: FrozenSet[Text]
        generates_grade,  # type: bool
        ):
    # type: (...) -> Tuple[PageBehavior, List[FlowPageVisit], forms.Form, Optional[AnswerFeedback], Any, bool]  # noqa
    page_context = fpctx.page_context
    page_data = fpctx.page_data

    assert page_context is not None

    submission_allowed = True

    assert fpctx.page is not None

    # reject answer update if permission not present
    if flow_permission.submit_answer not in permissions:
        messages.add_message(request, messages.ERROR,
                _("Answer submission not allowed."))
        submission_allowed = False

    prev_answer_visits = list(
            get_prev_answer_visits_qset(fpctx.page_data))

    # reject if previous answer was final
    if (prev_answer_visits
            and prev_answer_visits[0].is_submitted_answer
            and flow_permission.change_answer
                not in permissions):
        messages.add_message(request, messages.ERROR,
                _("Already have final answer."))
        submission_allowed = False

    page_behavior = get_page_behavior(
            page=fpctx.page,
            permissions=permissions,
            session_in_progress=flow_session.in_progress,
            answer_was_graded=False,
            generates_grade=generates_grade,
            is_unenrolled_session=flow_session.participation is None)

    form = fpctx.page.process_form_post(
            page_context, fpctx.page_data.data,
            post_data=request.POST, files_data=request.FILES,
            page_behavior=page_behavior)

    pressed_button = get_pressed_button(form)

    if submission_allowed and form.is_valid():
        # {{{ form validated, process answer

        messages.add_message(request, messages.SUCCESS,
                _("Answer saved."))

        answer_visit = FlowPageVisit()
        answer_visit.flow_session = flow_session
        answer_visit.page_data = fpctx.page_data
        answer_visit.remote_address = request.META["REMOTE_ADDR"]

        answer_data = answer_visit.answer = fpctx.page.answer_data(
                page_context, fpctx.page_data.data,
                form, request.FILES)
        answer_visit.is_submitted_answer = pressed_button == "submit"
        if hasattr(request, "relate_impersonate_original_user"):
            answer_visit.impersonated_by = \
                request.relate_impersonate_original_user
        answer_visit.save()

        prev_answer_visits.insert(0, answer_visit)

        answer_was_graded = answer_visit.is_submitted_answer

        page_behavior = get_page_behavior(
                page=fpctx.page,
                permissions=permissions,
                session_in_progress=flow_session.in_progress,
                answer_was_graded=answer_was_graded,
                generates_grade=generates_grade,
                is_unenrolled_session=flow_session.participation is None)

        if fpctx.page.is_answer_gradable():
            with LanguageOverride(course=fpctx.course):
                feedback = fpctx.page.grade(
                        page_context, page_data.data, answer_visit.answer,
                        grade_data=None)  # type: Optional[AnswerFeedback]

            if answer_visit.is_submitted_answer:
                grade = FlowPageVisitGrade()
                grade.visit = answer_visit
                grade.max_points = fpctx.page.max_points(page_data.data)
                grade.graded_at_git_commit_sha = fpctx.course_commit_sha

                bulk_feedback_json = None
                if feedback is not None:
                    grade.correctness = feedback.correctness
                    grade.feedback, bulk_feedback_json = feedback.as_json()

                grade.save()

                update_bulk_feedback(page_data, grade, bulk_feedback_json)

                del grade
        else:
            feedback = None

        if (pressed_button == "save_and_next"
                and not will_receive_feedback(permissions)):
            return redirect("relate-view_flow_page",
                            fpctx.course.identifier,
                            flow_session.id,
                            fpctx.page_ordinal + 1)
        elif (pressed_button == "save_and_finish"
                and not will_receive_feedback(permissions)):
            return redirect("relate-finish_flow_session_view",
                    fpctx.course.identifier, flow_session.id)
        else:
            # The form needs to be recreated here, although there
            # already is a form from the process_form_post above.  This
            # is because the value of 'answer_was_graded' may have
            # changed between then and now (and page_behavior with
            # it)--and that value depends on form validity, which we
            # can only decide once we have a form.

            form = fpctx.page.make_form(
                    page_context, page_data.data,
                    answer_data, page_behavior)

        # }}}

    else:
        # form did not validate
        create_flow_page_visit(request, flow_session, fpctx.page_data)

        answer_data = None
        answer_was_graded = False

        if prev_answer_visits:
            answer_data = prev_answer_visits[0].answer

        feedback = None
        messages.add_message(request, messages.ERROR,
                _("Failed to submit answer."))

    return (
            page_behavior,
            prev_answer_visits,
            form,
            feedback,
            answer_data,
            answer_was_graded)

# }}}


# {{{ view: send interaction email to course staffs in flow pages

@course_view
def send_email_about_flow_page(pctx, flow_session_id, page_ordinal):

    # {{{ check if interaction email is allowed for this page.

    page_ordinal = int(page_ordinal)
    flow_session_id = int(flow_session_id)
    flow_session = get_and_check_flow_session(pctx, flow_session_id)
    flow_id = flow_session.flow_id

    adjust_flow_session_page_data(pctx.repo, flow_session, pctx.course.identifier,
            respect_preview=True)

    fpctx = FlowPageContext(pctx.repo, pctx.course, flow_id, page_ordinal,
                            participation=pctx.participation,
                            flow_session=flow_session,
                            request=pctx.request)

    if fpctx.page is None:
        raise http.Http404()

    request = pctx.request
    now_datetime = get_now_or_fake_time(request)
    login_exam_ticket = get_login_exam_ticket(request)
    access_rule = get_session_access_rule(
            flow_session, fpctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    permissions = fpctx.page.get_modified_permissions_for_page(
            access_rule.permissions)

    if not may_send_email_about_flow_page(flow_session, permissions):
        raise http.Http404()

    # }}}

    review_url = reverse(
        "relate-view_flow_page",
        kwargs={"course_identifier": pctx.course.identifier,
                "flow_session_id": flow_session_id,
                "page_ordinal": page_ordinal
                }
    )

    from urllib.parse import urljoin

    review_uri = urljoin(getattr(settings, "RELATE_BASE_URL"),
                         review_url)

    if request.method == "POST":
        form = FlowPageInteractionEmailForm(review_uri, request.POST)

        if form.is_valid():

            from_email = getattr(
                    settings,
                    "STUDENT_INTERACT_EMAIL_FROM",
                    settings.ROBOT_EMAIL_FROM)
            student_email = flow_session.participation.user.email

            from course.constants import participation_status

            ta_email_list = Participation.objects.filter(
                    course=pctx.course,
                    roles__permissions__permission=pperm.assign_grade,
                    roles__identifier="ta",
                    status=participation_status.active
            ).values_list("user__email", flat=True)

            recipient_list = ta_email_list
            if not recipient_list:

                # instructors to receive the email
                recipient_list = Participation.objects.filter(
                    course=pctx.course,
                    roles__permissions__permission=pperm.assign_grade,
                    roles__identifier="instructor"
                ).values_list("user__email", flat=True)

            with LanguageOverride(course=pctx.course):

                from course.utils import will_use_masked_profile_for_email

                if will_use_masked_profile_for_email(recipient_list):
                    username = pctx.participation.user.get_masked_profile()
                else:
                    username = pctx.participation.user.get_full_name()

                page_id = FlowPageData.objects.get(
                    flow_session=flow_session_id, page_ordinal=page_ordinal).page_id

                from relate.utils import render_email_template

                message = render_email_template(
                    "course/flow-page-interaction-email.txt", {
                        "page_id": page_id,
                        "flow_session_id": flow_session_id,
                        "course": pctx.course,
                        "question_text": form.cleaned_data["message"],
                        "review_uri": review_uri,
                        "username": username
                    })

                from django.core.mail import EmailMessage
                msg = EmailMessage(
                    subject=string_concat(
                        "[%(identifier)s:%(flow_id)s--%(page_id)s] ",
                        _("Interaction request from %(username)s"))
                    % {
                            "identifier": pctx.course_identifier,
                            "flow_id": flow_session_id,
                            "page_id": page_id,
                            "username": username
                            },
                    body=message,
                    from_email=from_email,
                    to=recipient_list,
                )
                # TODO: add instructors to msg.bcc according to
                # settings in Course model.
                msg.bcc = [student_email]
                msg.reply_to = [student_email]

                from relate.utils import get_outbound_mail_connection
                msg.connection = get_outbound_mail_connection("student_interact")
                msg.send()

                messages.add_message(
                    request, messages.SUCCESS,
                    _("Email sent, and notice that you will "
                      "also receive a copy of the email."))

            return redirect("relate-view_flow_page",
                            pctx.course.identifier, flow_session_id, page_ordinal)

    else:
        form = FlowPageInteractionEmailForm(review_uri)

    return render_course_page(
            pctx, "course/generic-course-form.html", {
                "form": form,
                "form_description": _("Send interaction email"),
                })


class FlowPageInteractionEmailForm(StyledForm):
    def __init__(self, review_uri, *args, **kwargs):
        super(FlowPageInteractionEmailForm, self).__init__(*args, **kwargs)
        self.fields["message"] = forms.CharField(
                required=True,
                widget=forms.Textarea,
                help_text=string_concat(
                    _("Your questions about page %s . ") % review_uri,
                    _("Notice that <strong>only</strong> questions "
                      "for that page will be answered."),
                ),
                label=_("Message"))
        self.helper.add_input(
            Submit(
                "submit", _("Send Email"),
                css_class="relate-submit-button"))

    def clean_message(self):
        cleaned_data = super(FlowPageInteractionEmailForm, self).clean()
        message = cleaned_data.get("message")
        if len(message) < 20:
            raise forms.ValidationError(
                _("At least 20 characters are required for submission."))
        return message

# }}}


# {{{ view: update page bookmark state

@course_view
def update_page_bookmark_state(pctx, flow_session_id, page_ordinal):
    if pctx.request.method != "POST":
        raise SuspiciousOperation(_("only POST allowed"))

    flow_session = get_object_or_404(FlowSession, id=flow_session_id)

    if flow_session.participation != pctx.participation:
        raise PermissionDenied(
                _("may only change your own flow sessions"))

    bookmark_state = pctx.request.POST.get("bookmark_state")
    if bookmark_state not in ["0", "1"]:
        raise SuspiciousOperation(_("invalid bookmark state"))

    bookmark_state = bookmark_state == "1"

    fpd = get_object_or_404(FlowPageData.objects,
                            flow_session=flow_session,
                            page_ordinal=page_ordinal)

    fpd.bookmarked = bookmark_state
    fpd.save()

    return http.HttpResponse("OK")

# }}}


# {{{ view: update expiration mode

@course_view
def update_expiration_mode(pctx, flow_session_id):
    # type: (CoursePageContext, int) -> http.HttpResponse

    if pctx.request.method != "POST":
        raise SuspiciousOperation(_("only POST allowed"))

    login_exam_ticket = get_login_exam_ticket(pctx.request)

    flow_session = get_object_or_404(FlowSession, id=flow_session_id)

    if flow_session.participation != pctx.participation:
        raise PermissionDenied(
                _("may only change your own flow sessions"))
    if not flow_session.in_progress:
        raise PermissionDenied(
                _("may only change in-progress flow sessions"))

    expmode = pctx.request.POST.get("expiration_mode")
    if not any(expmode == em_key
            for em_key, _ in FLOW_SESSION_EXPIRATION_MODE_CHOICES):
        raise SuspiciousOperation(_("invalid expiration mode"))

    fctx = FlowContext(pctx.repo, pctx.course, flow_session.flow_id,
            participation=pctx.participation)

    access_rule = get_session_access_rule(
            flow_session, fctx.flow_desc,
            get_now_or_fake_time(pctx.request),
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    if is_expiration_mode_allowed(expmode, access_rule.permissions):
        flow_session.expiration_mode = expmode
        flow_session.save()

        return http.HttpResponse("OK")
    else:
        raise PermissionDenied()

# }}}


# {{{ view: finish flow

@course_view
def finish_flow_session_view(pctx, flow_session_id):
    # type: (CoursePageContext, int) -> http.HttpResponse

    # Does not need to be atomic: All writing to the db
    # is done in 'finish_flow_session' below.

    now_datetime = get_now_or_fake_time(pctx.request)
    login_exam_ticket = get_login_exam_ticket(pctx.request)

    request = pctx.request

    flow_session_id = int(flow_session_id)
    flow_session = get_and_check_flow_session(
            pctx, flow_session_id)
    flow_id = flow_session.flow_id

    fctx = FlowContext(pctx.repo, pctx.course, flow_id,
            participation=pctx.participation)

    access_rule = get_session_access_rule(
            flow_session, fctx.flow_desc, now_datetime,
            facilities=pctx.request.relate_facilities,
            login_exam_ticket=login_exam_ticket)

    from course.content import markup_to_html
    completion_text = markup_to_html(
            fctx.course, fctx.repo, pctx.course_commit_sha,
            getattr(fctx.flow_desc, "completion_text", ""))

    adjust_flow_session_page_data(pctx.repo, flow_session, pctx.course.identifier,
            fctx.flow_desc, respect_preview=True)

    answer_visits = assemble_answer_visits(flow_session)  # type: List[Optional[FlowPageVisit]]  # noqa

    (answered_page_data_list, unanswered_page_data_list, is_interactive_flow) =\
        get_session_answered_page_data(
            fctx, flow_session, answer_visits)

    if flow_permission.view not in access_rule.permissions:
        raise PermissionDenied()

    def render_finish_response(template, **kwargs):
        # type: (...) -> http.HttpResponse
        render_args = {
            "flow_identifier": fctx.flow_id,
            "flow_desc": fctx.flow_desc,
        }

        render_args.update(kwargs)
        return render_course_page(
                pctx, template, render_args,
                allow_instant_flow_requests=False)

    grading_rule = get_session_grading_rule(
            flow_session, fctx.flow_desc, now_datetime)

    if request.method == "POST":
        if "submit" not in request.POST:
            raise SuspiciousOperation(_("odd POST parameters"))

        if not flow_session.in_progress:
            messages.add_message(request, messages.ERROR,
                    _("Cannot end a session that's already ended"))

        if flow_permission.end_session not in access_rule.permissions:
            raise PermissionDenied(
                    _("not permitted to end session"))

        grade_info = finish_flow_session(
                fctx, flow_session, grading_rule,
                now_datetime=now_datetime)

        # {{{ send notify email if requested

        if (hasattr(fctx.flow_desc, "notify_on_submit")
                and fctx.flow_desc.notify_on_submit):
            staff_email = (
                fctx.flow_desc.notify_on_submit + [fctx.course.notify_email])

            from course.utils import will_use_masked_profile_for_email
            use_masked_profile = will_use_masked_profile_for_email(staff_email)

            if flow_session.participation is None or flow_session.user is None:
                # because Anonymous doesn't have get_masked_profile() method
                use_masked_profile = False

            if (grading_rule.grade_identifier
                    and flow_session.participation is not None):
                from course.models import get_flow_grading_opportunity
                review_uri = reverse("relate-view_single_grade",
                        args=(
                            pctx.course.identifier,
                            flow_session.participation.id,
                            get_flow_grading_opportunity(
                                pctx.course, flow_session.flow_id, fctx.flow_desc,
                                grading_rule.grade_identifier,
                                grading_rule.grade_aggregation_strategy).id))
            else:
                review_uri = reverse("relate-view_flow_page",
                        args=(
                            pctx.course.identifier,
                            flow_session.id,
                            0))

            with LanguageOverride(course=pctx.course):
                from relate.utils import render_email_template
                participation = flow_session.participation
                message = render_email_template("course/submit-notify.txt", {
                    "course": fctx.course,
                    "flow_session": flow_session,
                    "use_masked_profile": use_masked_profile,
                    "review_uri": pctx.request.build_absolute_uri(review_uri)
                    })

                participation_desc = repr(participation)
                if use_masked_profile:
                    participation_desc = _(
                        "%(user)s in %(course)s as %(role)s") % {
                        "user": participation.user.get_masked_profile(),
                        "course": flow_session.course,
                        "role": "/".join(
                            role.identifier
                            for role in participation.roles.all())
                    }

                from django.core.mail import EmailMessage
                msg = EmailMessage(
                        string_concat("[%(identifier)s:%(flow_id)s] ",
                            _("Submission by %(participation_desc)s"))
                        % {"participation_desc": participation_desc,
                            "identifier": fctx.course.identifier,
                            "flow_id": flow_session.flow_id},
                        message,
                        getattr(settings, "NOTIFICATION_EMAIL_FROM",
                            settings.ROBOT_EMAIL_FROM),
                        fctx.flow_desc.notify_on_submit)
                msg.bcc = [fctx.course.notify_email]

                from relate.utils import get_outbound_mail_connection
                msg.connection = (
                    get_outbound_mail_connection("notification")
                    if hasattr(settings, "NOTIFICATION_EMAIL_FROM")
                    else get_outbound_mail_connection("robot"))
                msg.send()

        # }}}

        if is_interactive_flow:
            if flow_permission.cannot_see_flow_result in access_rule.permissions:
                grade_info = None

            return render_finish_response(
                    "course/flow-completion-grade.html",
                    completion_text=completion_text,
                    grade_info=grade_info)

        else:
            return render_finish_response(
                    "course/flow-completion.html",
                    last_page_nr=None,
                    flow_session=flow_session,
                    completion_text=completion_text)

    if (not is_interactive_flow
            or (flow_session.in_progress
                and flow_permission.end_session not in access_rule.permissions)):
        # No ability to end--just show completion page.

        return render_finish_response(
                "course/flow-completion.html",
                last_page_nr=flow_session.page_count-1,
                flow_session=flow_session,
                completion_text=completion_text)

    elif not flow_session.in_progress:
        # Just reviewing: re-show grades.
        grade_info = gather_grade_info(
                fctx, flow_session, grading_rule, answer_visits)

        if flow_permission.cannot_see_flow_result in access_rule.permissions:
            grade_info = None

        return render_finish_response(
                "course/flow-completion-grade.html",
                completion_text=completion_text,
                grade_info=grade_info)

    else:
        # confirm ending flow
        answered_count = len(answered_page_data_list)
        unanswered_count = len(unanswered_page_data_list)
        required_count = answered_count + unanswered_count
        session_may_generate_grade = (
            grading_rule.generates_grade and required_count)
        return render_finish_response(
                "course/flow-confirm-completion.html",
                last_page_nr=flow_session.page_count-1,
                flow_session=flow_session,
                answered_count=answered_count,
                unanswered_count=unanswered_count,
                unanswered_page_data_list=unanswered_page_data_list,
                required_count=required_count,
                session_may_generate_grade=session_may_generate_grade)

# }}}


# {{{ view: regrade flow

class RegradeFlowForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        # type: (List[Text], *Any, **Any) -> None
        super(RegradeFlowForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"),
                widget=Select2Widget())
        self.fields["access_rules_tag"] = forms.CharField(
                required=False,
                help_text=_("If non-empty, limit the regrading to sessions "
                "started under this access rules tag."),
                label=_("Access rules tag"))
        self.fields["regraded_session_in_progress"] = forms.ChoiceField(
                choices=(
                    ("any",
                        _("Regrade in-progress and not-in-progress sessions")),
                    ("yes",
                        _("Regrade in-progress sessions only")),
                    ("no",
                        _("Regrade not-in-progress sessions only")),
                    ),
                label=_("Regraded session in progress"))

        self.helper.add_input(
                Submit("regrade", _("Regrade")))


@course_view
def regrade_flows_view(pctx):
    # type: (CoursePageContext) -> http.HttpResponse
    if not pctx.has_permission(pperm.batch_regrade_flow_session):
        raise PermissionDenied(_("may not batch-regrade flows"))

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = RegradeFlowForm(flow_ids, request.POST, request.FILES)
        if form.is_valid():
            inprog_value = {
                    "any": None,
                    "yes": True,
                    "no": False,
                    }[form.cleaned_data["regraded_session_in_progress"]]

            from course.tasks import regrade_flow_sessions
            async_res = regrade_flow_sessions.delay(
                    pctx.course.id,
                    form.cleaned_data["flow_id"],
                    form.cleaned_data["access_rules_tag"],
                    inprog_value)

            return redirect("relate-monitor_task", async_res.id)
    else:
        form = RegradeFlowForm(flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_text": string_concat(
            "<p>",
            _("This regrading process is only intended for flows that do"
            "not show up in the grade book. If you would like to regrade"
            "for-credit flows, use the corresponding functionality in "
            "the grade book."),
            "</p>"),
        "form_description": _("Regrade not-for-credit Flow Sessions"),
    })


# }}}


# {{{ view: unsubmit flow page

class UnsubmitFlowPageForm(forms.Form):
    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None
        self.helper = FormHelper()
        super(UnsubmitFlowPageForm, self).__init__(*args, **kwargs)

        self.helper.add_input(Submit("submit", _("Re-allow changes")))
        self.helper.add_input(Submit("cancel", _("Cancel")))


@course_view
def view_unsubmit_flow_page(pctx, flow_session_id, page_ordinal):
    # type: (CoursePageContext, int, int) -> http.HttpResponse

    if pctx.participation is None:
        raise PermissionDenied()

    if not pctx.has_permission(pperm.reopen_flow_session):
        raise PermissionDenied()

    request = pctx.request
    now_datetime = get_now_or_fake_time(request)

    page_ordinal = int(page_ordinal)
    flow_session_id = int(flow_session_id)

    flow_session = get_and_check_flow_session(pctx, flow_session_id)

    adjust_flow_session_page_data(pctx.repo, flow_session, pctx.course.identifier,
            respect_preview=True)

    page_data = get_object_or_404(
            FlowPageData, flow_session=flow_session, page_ordinal=page_ordinal)

    visit = get_first_from_qset(
            get_prev_answer_visits_qset(page_data)
            .filter(is_submitted_answer=True))

    if visit is None:
        messages.add_message(request, messages.INFO,
                _("No prior answers found that could be un-submitted."))
        return redirect("relate-view_flow_page",
                        pctx.course.identifier, flow_session_id, page_ordinal)

    if request.method == "POST":
        form = UnsubmitFlowPageForm(request.POST)
        if form.is_valid():
            if "submit" in request.POST:
                unsubmit_page(visit, now_datetime)
                messages.add_message(request, messages.INFO,
                        _("Flow page changes reallowed. "))

            return redirect("relate-view_flow_page",
                            pctx.course.identifier, flow_session_id, page_ordinal)
    else:
        form = UnsubmitFlowPageForm()

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form_description": _("Re-allow Changes to Flow Page"),
        "form": form
        })

# }}}


# {{{ purge page view data

def get_pv_purgeable_courses_for_user_qs(user):
    # type: (User) -> query.QuerySet
    course_qs = Course.objects.all()
    if user.is_superuser:
        # do not filter queryset
        pass
    else:
        course_qs = course_qs.filter(
                participations__user=user,
                participations__roles__permissions__permission=(
                    pperm.use_admin_interface))

    return course_qs


class PurgePageViewData(StyledForm):
    def __init__(self, user, *args, **kwargs):
        # type: (User, *Any, **Any) -> None
        self.helper = FormHelper()
        super(PurgePageViewData, self).__init__(*args, **kwargs)

        self.fields["course"] = forms.ModelChoiceField(
                queryset=get_pv_purgeable_courses_for_user_qs(user),
                required=True)

        self.helper.add_input(
                Submit("submit", _("Purge Page View Data"),
                    css_class="btn btn-danger"))


@login_required
def purge_page_view_data(request):
    purgeable_courses = get_pv_purgeable_courses_for_user_qs(request.user)
    if not purgeable_courses.count():
        raise PermissionDenied()
    if request.method == "POST":
        form = PurgePageViewData(request.user, request.POST)
        if form.is_valid():
            if "submit" in request.POST:
                course = form.cleaned_data["course"]

                from course.tasks import purge_page_view_data
                async_res = purge_page_view_data.delay(course.id)

                return redirect("relate-monitor_task", async_res.id)
    else:
        form = PurgePageViewData(request.user)

    return render(request, "generic-form.html", {
        "form_description": _("Purge Page View Data"),
        "form": form
        })

# }}}

# vim: foldmethod=marker
