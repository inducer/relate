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

from django.utils import six
from django.utils.translation import (
        ugettext_lazy as _, string_concat)
from django.utils.functional import lazy
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
from django.core.exceptions import (
        PermissionDenied, SuspiciousOperation,
        ObjectDoesNotExist)
from django.db import transaction
from django.utils.safestring import mark_safe
mark_safe_lazy = lazy(mark_safe, six.text_type)
from django import forms
from django import http

from relate.utils import StyledForm, local_now, as_local_time
from crispy_forms.layout import Submit

from course.constants import (
        flow_permission,
        participation_role,
        flow_session_expiration_mode,
        FLOW_SESSION_EXPIRATION_MODE_CHOICES,
        is_expiration_mode_allowed,
        flow_rule_kind,
        grade_aggregation_strategy,
        GRADE_AGGREGATION_STRATEGY_CHOICES
        )
from course.models import (
        FlowSession, FlowPageData, FlowPageVisit,
        FlowPageVisitGrade,
        get_feedback_for_grade,
        GradeChange, update_bulk_feedback)

from course.utils import (
        FlowContext, FlowPageContext, PageOrdinalOutOfRange,
        instantiate_flow_page_with_ctx,
        course_view, render_course_page,
        get_session_start_rule,
        get_session_access_rule,
        get_session_grading_rule,
        FlowSessionGradingRule)
from course.views import get_now_or_fake_time


# {{{ grade page visit

def grade_page_visit(visit, visit_grade_model=FlowPageVisitGrade,
        grade_data=None, graded_at_git_commit_sha=None):
    if not visit.is_submitted_answer:
        raise RuntimeError(_("cannot grade ungraded answer"))

    flow_session = visit.flow_session
    course = flow_session.course
    page_data = visit.page_data

    most_recent_grade = visit.get_most_recent_grade()
    if most_recent_grade is not None and grade_data is None:
        grade_data = most_recent_grade.grade_data

    from course.content import (
            get_course_repo,
            get_course_commit_sha,
            get_flow_desc,
            get_flow_page_desc,
            instantiate_flow_page)

    repo = get_course_repo(course)

    course_commit_sha = get_course_commit_sha(
            course, flow_session.participation)

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

    answer_feedback = page.grade(
            grading_page_context, visit.page_data.data,
            visit.answer, grade_data=grade_data)

    grade = visit_grade_model()
    grade.visit = visit
    grade.grade_data = grade_data
    grade.max_points = page.max_points(visit.page_data)
    grade.graded_at_git_commit_sha = graded_at_git_commit_sha

    bulk_feedback_json = None
    if answer_feedback is not None:
        grade.correctness = answer_feedback.correctness
        grade.feedback, bulk_feedback_json = answer_feedback.as_json()

    grade.save()

    update_bulk_feedback(page_data, grade, bulk_feedback_json)

# }}}


# {{{ start flow

def start_flow(repo, course, participation, flow_id, flow_desc,
        access_rules_tag, now_datetime):
    from course.content import get_course_commit_sha
    course_commit_sha = get_course_commit_sha(course, participation)

    session = FlowSession(
        course=course,
        participation=participation,
        active_git_commit_sha=course_commit_sha.decode(),
        flow_id=flow_id,
        in_progress=True,
        expiration_mode=flow_session_expiration_mode.end,
        access_rules_tag=access_rules_tag)

    session.save()

    # Create flow grading opportunity. This makes the flow
    # show up in the grade book.

    from course.utils import get_flow_rules
    from course.models import get_flow_grading_opportunity
    for grading_rule in get_flow_rules(
            flow_desc, flow_rule_kind.grading, participation,
            flow_id, now_datetime, consider_exceptions=False):
        identifier = getattr(grading_rule, "grade_identifier", None)
        if identifier is not None:
            get_flow_grading_opportunity(
                    course, flow_id, flow_desc,
                    FlowSessionGradingRule(
                        grade_identifier=identifier,
                        grade_aggregation_strategy=getattr(
                            grading_rule, "grade_aggregation_strategy"),
                        ))

    # will implicitly modify and save the session if there are changes
    from course.content import adjust_flow_session_page_data
    adjust_flow_session_page_data(repo, session,
            course.identifier, flow_desc, course_commit_sha)

    return session

# }}}


# {{{ finish flow

def get_flow_session_graded_answers_qset(flow_session):
    from django.db.models import Q
    qset = (FlowPageVisit.objects
            .filter(flow_session=flow_session)
            .filter(Q(answer__isnull=False) | Q(is_synthetic=True)))

    if not flow_session.in_progress:
        # Ungraded answers *can* show up in non-in-progress flows as a result
        # of a race between a 'save' and the 'end session'. If this happens,
        # we'll go ahead and ignore those.
        qset = qset.filter(is_submitted_answer=True)

    return qset


def get_prev_answer_visit(page_data):
    previous_answer_visits = (
            get_flow_session_graded_answers_qset(page_data.flow_session)
            .filter(page_data=page_data)
            .order_by("-visit_time"))

    for prev_visit in previous_answer_visits[:1]:
        return prev_visit

    return None


def assemble_answer_visits(flow_session):
    answer_visits = [None] * flow_session.page_count

    answer_page_visits = (
            get_flow_session_graded_answers_qset(flow_session)
            .order_by("visit_time"))

    for page_visit in answer_page_visits:
        if page_visit.page_data.ordinal is not None:
            answer_visits[page_visit.page_data.ordinal] = page_visit

        if not flow_session.in_progress:
            assert page_visit.is_submitted_answer is True

    return answer_visits


def count_answered_gradable(fctx, flow_session, answer_visits):
    all_page_data = (FlowPageData.objects
            .filter(
                flow_session=flow_session,
                ordinal__isnull=False)
            .order_by("ordinal"))

    answered_count = 0
    unanswered_count = 0
    for i, page_data in enumerate(all_page_data):
        assert i == page_data.ordinal

        if answer_visits[i] is not None:
            answer_data = answer_visits[i].answer
        else:
            answer_data = None

        page = instantiate_flow_page_with_ctx(fctx, page_data)
        if page.expects_answer() and page.is_answer_gradable():
            if answer_data is None:
                unanswered_count += 1
            else:
                answered_count += 1

    return (answered_count, unanswered_count)


class GradeInfo(object):
    """An object to hold a tally of points and page counts of various types in a flow.

    .. attribute:: points

        The final grade, in points. May be *None* if the grade is not yet
        final.
    """

    def __init__(self,
            points, provisional_points, max_points, max_reachable_points,
            fully_correct_count, partially_correct_count, incorrect_count,
            unknown_count):
        self.points = points
        self.provisional_points = provisional_points
        self.max_points = max_points
        self.max_reachable_points = max_reachable_points
        self.fully_correct_count = fully_correct_count
        self.partially_correct_count = partially_correct_count
        self.incorrect_count = incorrect_count
        self.unknown_count = unknown_count

    # Rounding to larger than 100% will break the percent bars on the
    # flow results page.
    FULL_PERCENT = 99.99

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


def gather_grade_info(fctx, flow_session, answer_visits):
    """
    :returns: a :class:`GradeInfo`
    """

    all_page_data = (FlowPageData.objects
            .filter(
                flow_session=flow_session,
                ordinal__isnull=False)
            .order_by("ordinal"))

    points = 0
    provisional_points = 0
    max_points = 0
    max_reachable_points = 0
    fully_correct_count = 0
    partially_correct_count = 0
    incorrect_count = 0
    unknown_count = 0

    for i, page_data in enumerate(all_page_data):
        page = instantiate_flow_page_with_ctx(fctx, page_data)

        assert i == page_data.ordinal

        if answer_visits[i] is None:
            # This is true in principle, but early code to deal with survey questions
            # didn't generate synthetic answer visits for survey questions, so this
            # can't actually be enforced.

            # assert not page.expects_answer()
            continue

        if not page.is_answer_gradable():
            continue

        grade = answer_visits[i].get_most_recent_grade()
        assert grade is not None

        feedback = get_feedback_for_grade(grade)

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

    return GradeInfo(
            points=points,
            provisional_points=provisional_points,
            max_points=max_points,
            max_reachable_points=max_reachable_points,

            fully_correct_count=fully_correct_count,
            partially_correct_count=partially_correct_count,
            incorrect_count=incorrect_count,
            unknown_count=unknown_count)


@transaction.atomic
def grade_page_visits(fctx, flow_session, answer_visits, force_regrade=False):
    for i in range(len(answer_visits)):
        answer_visit = answer_visits[i]

        if answer_visit is not None:
            answer_visit.is_submitted_answer = True
            answer_visit.save()

        else:
            page_data = flow_session.page_data.get(ordinal=i)
            page = instantiate_flow_page_with_ctx(fctx, page_data)

            if not page.expects_answer():
                continue

            # Create a synthetic visit to attach a grade
            answer_visit = FlowPageVisit()
            answer_visit.flow_session = flow_session
            answer_visit.page_data = page_data
            answer_visit.is_synthetic = True
            answer_visit.answer = None
            answer_visit.is_submitted_answer = True
            answer_visit.save()

            answer_visits[i] = answer_visit

            if not page.is_answer_gradable():
                continue

        if (answer_visit is not None
                and (not answer_visit.grades.count() or force_regrade)):
            grade_page_visit(answer_visit,
                    graded_at_git_commit_sha=fctx.course_commit_sha)


@transaction.atomic
def finish_flow_session(fctx, flow_session, grading_rule,
        force_regrade=False, now_datetime=None):
    if not flow_session.in_progress:
        raise RuntimeError(_("Can't end a session that's already ended"))

    assert isinstance(grading_rule, FlowSessionGradingRule)

    answer_visits = assemble_answer_visits(flow_session)

    (answered_count, unanswered_count) = count_answered_gradable(
            fctx, flow_session, answer_visits)

    is_graded_flow = bool(answered_count + unanswered_count)

    if is_graded_flow:
        grade_page_visits(fctx, flow_session, answer_visits,
                force_regrade=force_regrade)

    # ORDERING RESTRICTION: Must grade pages before gathering grade info

    if now_datetime is None:
        from django.utils.timezone import now
        now_datetime = now()

    flow_session.completion_time = now_datetime

    flow_session.in_progress = False
    flow_session.save()

    return grade_flow_session(fctx, flow_session, grading_rule,
            answer_visits)


@transaction.atomic
def expire_flow_session(fctx, flow_session, grading_rule, now_datetime,
        past_due_only=False):
    if not flow_session.in_progress:
        raise RuntimeError(_("Can't expire a session that's not in progress"))
    if flow_session.participation is None:
        raise RuntimeError(_("Can't expire an anonymous flow session"))

    assert isinstance(grading_rule, FlowSessionGradingRule)

    if (past_due_only
            and grading_rule.due is not None
            and now_datetime < grading_rule.due):
        return False

    if flow_session.expiration_mode == flow_session_expiration_mode.roll_over:
        session_start_rule = get_session_start_rule(flow_session.course,
                flow_session.participation, flow_session.participation.role,
                flow_session.flow_id, fctx.flow_desc, now_datetime,
                for_rollover=True)

        if not session_start_rule.may_start_new_session:
            # No new session allowed: finish.
            return finish_flow_session(fctx, flow_session, grading_rule,
                    now_datetime=now_datetime)

        flow_session.access_rules_tag = session_start_rule.tag_session

        access_rule = get_session_access_rule(flow_session,
                flow_session.participation.role,
                fctx.flow_desc, now_datetime)

        if not is_expiration_mode_allowed(
                flow_session.expiration_mode, access_rule.permissions):
            flow_session.expiration_mode = flow_session_expiration_mode.end
        flow_session.save()

        return True

    elif flow_session.expiration_mode == flow_session_expiration_mode.end:
        return finish_flow_session(fctx, flow_session, grading_rule,
                now_datetime=now_datetime)
    else:
        raise ValueError(
                _("invalid expiration mode '%(mode)s' on flow session ID "
                "%(session_id)d") % {
                    'mode': flow_session.expiration_mode,
                    'session_id': flow_session.id})


def grade_flow_session(fctx, flow_session, grading_rule,
        answer_visits=None):
    """Updates the grade on an existing flow session and logs a
    grade change with the grade records subsystem.
    """

    if answer_visits is None:
        answer_visits = assemble_answer_visits(flow_session)

    (answered_count, unanswered_count) = count_answered_gradable(
            fctx, flow_session, answer_visits)

    is_graded_flow = bool(answered_count + unanswered_count)

    grade_info = gather_grade_info(fctx, flow_session, answer_visits)
    assert grade_info is not None

    comment = None
    points = grade_info.points

    if (points is not None
            and grading_rule.credit_percent is not None
            and grading_rule.credit_percent != 100):
        # Translators: grade flow: calculating grade.
        comment = (
                _("Counted at %(percent).1f%% of %(point).1f points") % {
                    'percent': grading_rule.credit_percent,
                    'point': points})
        points = points * grading_rule.credit_percent / 100

    flow_session.points = points
    flow_session.max_points = grade_info.max_points

    flow_session.append_comment(comment)
    flow_session.save()

    # Need to save grade record even if no grade is available yet, because
    # a grade record may *already* be saved, and that one might be mistaken
    # for the current one.
    if (grading_rule.grade_identifier
            and is_graded_flow
            and flow_session.participation is not None):
        from course.models import get_flow_grading_opportunity
        gopp = get_flow_grading_opportunity(
                flow_session.course, flow_session.flow_id, fctx.flow_desc,
                grading_rule)

        from course.models import grade_state_change_types
        gchange = GradeChange()
        gchange.opportunity = gopp
        gchange.participation = flow_session.participation
        gchange.state = grade_state_change_types.graded
        gchange.attempt_id = "flow-session-%d" % flow_session.id
        gchange.points = points
        gchange.max_points = grade_info.max_points
        # creator left as NULL
        gchange.flow_session = flow_session
        gchange.comment = comment

        previous_grade_changes = list(GradeChange.objects
                .filter(
                    opportunity=gchange.opportunity,
                    participation=gchange.participation,
                    state=gchange.state,
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
                    and previous_grade_change.comment == gchange.comment):
                do_save = False
        else:
            # no previous grade changes
            if points is None:
                do_save = False

        if do_save:
            gchange.save()

    return grade_info


def reopen_session(session, force=False, suppress_log=False):
    if session.in_progress:
        raise RuntimeError(
                _("Can't reopen a session that's already in progress"))
    if session.participation is None:
        raise RuntimeError(
                _("Can't reopen anonymous sessions"))

    session.in_progress = True
    session.points = None
    session.max_points = None

    if not suppress_log:
        session.append_comment(
                _("Session reopened at %(now)s, previous completion time "
                "was '%(complete_time)s'.") % {
                    'now': local_now(formatted=True),
                    'complete_time': as_local_time(session.completion_time, formatted=True)})

    session.completion_time = None
    session.save()


def finish_flow_session_standalone(repo, course, session, force_regrade=False,
        now_datetime=None, past_due_only=False):
    assert session.participation is not None

    from course.utils import FlowContext

    if now_datetime is None:
        from django.utils.timezone import now
        now_datetime = now()

    fctx = FlowContext(repo, course, session.flow_id, flow_session=session)

    grading_rule = get_session_grading_rule(
            session, session.participation.role, fctx.flow_desc, now_datetime)

    if (past_due_only
            and grading_rule.due is not None
            and now_datetime < grading_rule.due):
        return False

    finish_flow_session(fctx, session, grading_rule,
            force_regrade=force_regrade, now_datetime=now_datetime)

    return True


def expire_flow_session_standalone(repo, course, session, now_datetime,
        past_due_only=False):
    assert session.participation is not None

    from course.utils import FlowContext

    fctx = FlowContext(repo, course, session.flow_id, flow_session=session)

    grading_rule = get_session_grading_rule(
            session, session.participation.role, fctx.flow_desc, now_datetime)

    return expire_flow_session(fctx, session, grading_rule, now_datetime,
            past_due_only=past_due_only)


@transaction.atomic
def regrade_session(repo, course, session):
    if session.in_progress:
        fctx = FlowContext(repo, course, session.flow_id, flow_session=session)

        answer_visits = assemble_answer_visits(session)

        for i in range(len(answer_visits)):
            answer_visit = answer_visits[i]

            if answer_visit is not None and answer_visit.get_most_recent_grade():
                # Only make a new grade if there already is one.
                grade_page_visit(answer_visit,
                        graded_at_git_commit_sha=fctx.course_commit_sha)
    else:
        prev_completion_time = session.completion_time

        session.append_comment(
                _("Session regraded at %(time)s.") % {'time': local_now(formatted=True)})
        session.save()

        reopen_session(session, force=True, suppress_log=True)
        finish_flow_session_standalone(
                repo, course, session, force_regrade=True,
                now_datetime=prev_completion_time)


@transaction.atomic
def recalculate_session_grade(repo, course, session):
    """Only redoes the final grade determination without regrading
    individual pages.
    """

    if session.in_progress:
        raise RuntimeError(_("cannot recalculate grade on in-progress session"))

    prev_completion_time = session.completion_time

    session.append_comment(
            _("Session grade recomputed at %(time)s.") % {'time': local_now(formatted=True)})
    session.save()

    reopen_session(session, force=True, suppress_log=True)
    finish_flow_session_standalone(
            repo, course, session, force_regrade=False,
            now_datetime=prev_completion_time)

# }}}


# {{{ view: start flow

@transaction.atomic
@course_view
def view_start_flow(pctx, flow_id):
    request = pctx.request

    now_datetime = get_now_or_fake_time(request)
    fctx = FlowContext(pctx.repo, pctx.course, flow_id,
            participation=pctx.participation)

    session_start_rule = get_session_start_rule(pctx.course, pctx.participation,
            pctx.role, flow_id, fctx.flow_desc, now_datetime,
            remote_address=pctx.remote_address)

    if request.method == "POST":
        if "start" in request.POST:

            if not session_start_rule.may_start_new_session:
                raise PermissionDenied(_("new session not allowed"))

            session = start_flow(
                    pctx.repo, pctx.course, pctx.participation,
                    flow_id, fctx.flow_desc,
                    access_rules_tag=session_start_rule.tag_session,
                    now_datetime=now_datetime)

            return redirect("relate-view_flow_page",
                    pctx.course.identifier, session.id, 0)

        else:
            raise SuspiciousOperation(_("unrecognized POST action"))

    else:
        if session_start_rule.may_list_existing_sessions:
            past_sessions = (FlowSession.objects
                    .filter(
                        participation=pctx.participation,
                        flow_id=fctx.flow_id,
                        participation__isnull=False)
                   .order_by("start_time"))

            from collections import namedtuple
            SessionProperties = namedtuple("SessionProperties",  # noqa
                    ["may_view", "may_modify", "due", "grade_description"])

            past_sessions_and_properties = []
            for session in past_sessions:
                access_rule = get_session_access_rule(
                        session, pctx.role, fctx.flow_desc, now_datetime,
                        remote_address=pctx.remote_address)
                grading_rule = get_session_grading_rule(
                        session, pctx.role, fctx.flow_desc, now_datetime)

                session_properties = SessionProperties(
                        may_view=flow_permission.view in access_rule.permissions,
                        may_modify=(
                            flow_permission.submit_answer in access_rule.permissions
                            or
                            flow_permission.end_session in access_rule.permissions
                            ),
                        due=grading_rule.due,
                        grade_description=grading_rule.description)
                past_sessions_and_properties.append((session, session_properties))
        else:
            past_sessions_and_properties = []

        may_start = session_start_rule.may_start_new_session
        potential_session = FlowSession(
            course=pctx.course,
            participation=pctx.participation,
            flow_id=flow_id,
            in_progress=True,
            expiration_mode=flow_session_expiration_mode.end,
            access_rules_tag=session_start_rule.tag_session)

        new_session_grading_rule = get_session_grading_rule(
                potential_session, pctx.role, fctx.flow_desc, now_datetime)

        start_may_decrease_grade = (
                bool(past_sessions_and_properties)
                and
                new_session_grading_rule.grade_aggregation_strategy not in
                [
                    None,
                    grade_aggregation_strategy.max_grade,
                    grade_aggregation_strategy.use_earliest])

        return render_course_page(pctx, "course/flow-start.html", {
            "flow_desc": fctx.flow_desc,
            "flow_identifier": flow_id,

            "now": now_datetime,
            "may_start": may_start,
            "new_session_grading_rule": new_session_grading_rule,
            "grade_aggregation_strategy_descr": (
                dict(GRADE_AGGREGATION_STRATEGY_CHOICES).get(
                    new_session_grading_rule.grade_aggregation_strategy)),
            "start_may_decrease_grade": start_may_decrease_grade,

            "past_sessions_and_properties": past_sessions_and_properties,
            },
            allow_instant_flow_requests=False)

# }}}


# {{{ view: flow page

def get_and_check_flow_session(pctx, flow_session_id):
    try:
        flow_session = FlowSession.objects.get(id=flow_session_id)
    except ObjectDoesNotExist:
        raise http.Http404()

    if pctx.role in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        pass
    elif pctx.role in [
            participation_role.student,
            participation_role.observer,
            participation_role.auditor,
            participation_role.unenrolled]:
        if pctx.participation != flow_session.participation:
            raise PermissionDenied(_("may not view other people's sessions"))
    else:
        raise PermissionDenied()

    if flow_session.course.pk != pctx.course.pk:
        raise SuspiciousOperation()

    return flow_session


def will_receive_feedback(permissions):
    return (
            flow_permission.see_correctness in permissions
            or flow_permission.see_answer_after_submission in permissions)


def add_buttons_to_form(form, fpctx, flow_session, permissions):
    from crispy_forms.layout import Submit
    form.helper.add_input(
            Submit("save", _("Save answer"),
                css_class="col-lg-offset-2 relate-save-button"))

    if will_receive_feedback(permissions):
        if flow_permission.change_answer in permissions:
            form.helper.add_input(
                    Submit(
                        "submit", _("Submit answer for grading"),
                        accesskey="g", css_class="relate-save-button"))
        else:
            form.helper.add_input(
                    Submit("submit", _("Submit final answer"),
                        css_class="relate-save-button"))
    else:
        # Only offer 'save and move on' if student will receive no feedback
        if fpctx.page_data.ordinal + 1 < flow_session.page_count:
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


def get_pressed_button(form):
    buttons = ["save", "save_and_next", "save_and_finish", "submit"]
    for button in buttons:
        if button in form.data:
            return button

    raise SuspiciousOperation(_("could not find which button was pressed"))


def create_flow_page_visit(request, flow_session, page_data):
    FlowPageVisit(
        flow_session=flow_session,
        page_data=page_data,
        remote_address=request.META['REMOTE_ADDR'],
        is_submitted_answer=None).save()


@course_view
def view_flow_page(pctx, flow_session_id, ordinal):
    request = pctx.request

    ordinal = int(ordinal)

    flow_session_id = int(flow_session_id)
    flow_session = get_and_check_flow_session(
            pctx, flow_session_id)
    flow_id = flow_session.flow_id

    if flow_session is None:
        messages.add_message(request, messages.WARNING,
                _("No in-progress session record found for this flow. "
                "Redirected to flow start page."))

        return redirect("relate-view_start_flow",
                pctx.course.identifier,
                flow_id)

    try:
        fpctx = FlowPageContext(pctx.repo, pctx.course, flow_id, ordinal,
                participation=pctx.participation,
                flow_session=flow_session)
    except PageOrdinalOutOfRange:
        return redirect("relate-view_flow_page",
                pctx.course.identifier,
                flow_session.id,
                flow_session.page_count-1)

    access_rule = get_session_access_rule(
            flow_session, pctx.role, fpctx.flow_desc, get_now_or_fake_time(request),
            pctx.remote_address)
    permissions = fpctx.page.get_modified_permissions_for_page(
            access_rule.permissions)

    if access_rule.message:
        messages.add_message(request, messages.INFO, access_rule.message)

    page_context = fpctx.page_context
    page_data = fpctx.page_data
    answer_data = None
    grade_data = None

    if flow_permission.view not in permissions:
        raise PermissionDenied(_("not allowed to view flow"))

    if request.method == "POST":
        if "finish" in request.POST:
            return redirect("relate-finish_flow_session_view",
                    pctx.course.identifier, flow_session_id)
        else:
            submission_allowed = True

            # reject answer update if permission not present
            if flow_permission.submit_answer not in permissions:
                messages.add_message(request, messages.ERROR,
                        _("Answer submission not allowed."))
                submission_allowed = False

            # reject if previous answer was final
            if (fpctx.prev_answer_visit is not None
                    and fpctx.prev_answer_visit.is_submitted_answer
                    and flow_permission.change_answer
                        not in permissions):
                messages.add_message(request, messages.ERROR,
                        _("Already have final answer."))
                submission_allowed = False

            form = fpctx.page.post_form(
                    fpctx.page_context, fpctx.page_data.data,
                    post_data=request.POST, files_data=request.FILES)

            pressed_button = get_pressed_button(form)

            if submission_allowed and form.is_valid():
                # {{{ form validated, process answer

                messages.add_message(request, messages.INFO,
                        _("Answer saved."))

                page_visit = FlowPageVisit()
                page_visit.flow_session = flow_session
                page_visit.page_data = fpctx.page_data
                page_visit.remote_address = request.META['REMOTE_ADDR']

                answer_data = page_visit.answer = fpctx.page.answer_data(
                        fpctx.page_context, fpctx.page_data.data,
                        form, request.FILES)
                page_visit.is_submitted_answer = pressed_button == "submit"
                page_visit.save()

                answer_was_graded = page_visit.is_submitted_answer
                may_change_answer = (
                    not answer_was_graded
                    or flow_permission.change_answer
                    in permissions)

                if fpctx.page.is_answer_gradable():
                    feedback = fpctx.page.grade(
                            page_context, page_data.data, page_visit.answer,
                            grade_data=None)

                    if page_visit.is_submitted_answer:
                        grade = FlowPageVisitGrade()
                        grade.visit = page_visit
                        grade.max_points = fpctx.page.max_points(page_data.data)
                        grade.graded_at_git_commit_sha = pctx.course_commit_sha

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
                            pctx.course.identifier,
                            flow_session_id,
                            fpctx.ordinal + 1)
                elif (pressed_button == "save_and_finish"
                        and not will_receive_feedback(permissions)):
                    return redirect("relate-finish_flow_session_view",
                            pctx.course.identifier, flow_session_id)
                else:
                    form = fpctx.page.make_form(
                            page_context, page_data.data,
                            page_visit.answer, not may_change_answer)

                    # continue at common flow page generation below

                # }}}

                del page_visit

            else:
                # form did not validate
                create_flow_page_visit(request, flow_session, fpctx.page_data)

                answer_was_graded = False
                may_change_answer = True
                # because we were allowed this far in by the check above

                feedback = None

                # continue at common flow page generation below

    else:
        create_flow_page_visit(request, flow_session, fpctx.page_data)

        if fpctx.prev_answer_visit is not None:
            answer_was_graded = fpctx.prev_answer_visit.is_submitted_answer
        else:
            answer_was_graded = False

        may_change_answer = (
                (not answer_was_graded
                    or (flow_permission.change_answer in permissions))

                # can happen if no answer was ever saved
                and flow_session.in_progress

                and (flow_permission.submit_answer in permissions))

        if fpctx.page.expects_answer():
            if fpctx.prev_answer_visit is not None:
                answer_data = fpctx.prev_answer_visit.answer

                most_recent_grade = fpctx.prev_answer_visit.get_most_recent_grade()
                if most_recent_grade is not None:
                    feedback = get_feedback_for_grade(most_recent_grade)
                    grade_data = most_recent_grade.grade_data
                else:
                    feedback = None
                    grade_data = None

            else:
                feedback = None

            form = fpctx.page.make_form(
                    page_context, page_data.data,
                    answer_data, not may_change_answer)
        else:
            form = None
            feedback = None

    # start common flow page generation

    # defined at this point:
    # form, form_html, may_change_answer, answer_was_graded, feedback

    if form is not None and may_change_answer:
        form = add_buttons_to_form(form, fpctx, flow_session,
                permissions)

    show_correctness = None
    show_answer = None

    shown_feedback = None

    if fpctx.page.expects_answer() and answer_was_graded:
        show_correctness = flow_permission.see_correctness in permissions

        show_answer = flow_permission.see_answer_after_submission in permissions

        if show_correctness or show_answer:
            shown_feedback = feedback

    elif fpctx.page.expects_answer() and not answer_was_graded:
        # Don't show answer yet
        show_answer = (
                flow_permission.see_answer_before_submission in permissions)
    else:
        show_answer = (
                flow_permission.see_answer_before_submission in permissions
                or
                flow_permission.see_answer_after_submission in permissions)

    title = fpctx.page.title(page_context, page_data.data)
    body = fpctx.page.body(page_context, page_data.data)

    if show_answer:
        correct_answer = fpctx.page.correct_answer(
                page_context, page_data.data,
                answer_data, grade_data)
    else:
        correct_answer = None

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

    args = {
        "flow_identifier": fpctx.flow_id,
        "flow_desc": fpctx.flow_desc,
        "ordinal": fpctx.ordinal,
        "page_data": fpctx.page_data,
        "percentage": int(100*(fpctx.ordinal+1) / flow_session.page_count),
        "flow_session": flow_session,
        "page_numbers": zip(
            range(flow_session.page_count),
            range(1, flow_session.page_count+1)),

        "title": title, "body": body,
        "form": form,
        "form_html": form_html,

        "feedback": shown_feedback,
        "correct_answer": correct_answer,

        "show_correctness": show_correctness,
        "may_change_answer": may_change_answer,
        "may_change_graded_answer": (
            (flow_permission.change_answer
                        in permissions)
            and flow_session.in_progress),
        "will_receive_feedback": will_receive_feedback(permissions),
        "show_answer": show_answer,

        "expiration_mode_choices": expiration_mode_choices,
        "expiration_mode_choice_count": len(expiration_mode_choices),
        "expiration_mode": flow_session.expiration_mode,
    }

    if fpctx.page.expects_answer() and fpctx.page.is_answer_gradable():
        args["max_points"] = fpctx.page.max_points(fpctx.page_data)

    return render_course_page(
            pctx, "course/flow-page.html", args,
            allow_instant_flow_requests=False)

    # }}}


@course_view
def update_expiration_mode(pctx, flow_session_id):
    if pctx.request.method != "POST":
        raise SuspiciousOperation(_("only POST allowed"))

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
            participation=pctx.participation,
            flow_session=flow_session)

    access_rule = get_session_access_rule(
            flow_session, pctx.role, fctx.flow_desc,
            get_now_or_fake_time(pctx.request),
            pctx.remote_address)

    if is_expiration_mode_allowed(expmode, access_rule.permissions):
        flow_session.expiration_mode = expmode
        flow_session.save()

        return http.HttpResponse("OK")
    else:
        raise PermissionDenied()

# }}}


# {{{ view: finish flow

@transaction.atomic
@course_view
def finish_flow_session_view(pctx, flow_session_id):
    now_datetime = get_now_or_fake_time(pctx.request)

    request = pctx.request

    flow_session_id = int(flow_session_id)
    flow_session = get_and_check_flow_session(
            pctx, flow_session_id)
    flow_id = flow_session.flow_id

    fctx = FlowContext(pctx.repo, pctx.course, flow_id,
            participation=pctx.participation,
            flow_session=flow_session)

    access_rule = get_session_access_rule(
            flow_session, pctx.role, fctx.flow_desc, now_datetime,
            pctx.remote_address)

    answer_visits = assemble_answer_visits(flow_session)

    from course.content import markup_to_html
    completion_text = markup_to_html(
            fctx.course, fctx.repo, pctx.course_commit_sha,
            fctx.flow_desc.completion_text)

    (answered_count, unanswered_count) = count_answered_gradable(
            fctx, flow_session, answer_visits)
    is_graded_flow = bool(answered_count + unanswered_count)

    if flow_permission.view not in access_rule.permissions:
        raise PermissionDenied()

    def render_finish_response(template, **kwargs):
        render_args = {
            "flow_identifier": fctx.flow_id,
            "flow_desc": fctx.flow_desc,
        }

        render_args.update(kwargs)
        return render_course_page(
                pctx, template, render_args,
                allow_instant_flow_requests=False)

    if request.method == "POST":
        if "submit" not in request.POST:
            raise SuspiciousOperation(_("odd POST parameters"))

        if not flow_session.in_progress:
            raise PermissionDenied(
                    _("Can't end a session that's already ended"))

        if flow_permission.end_session not in access_rule.permissions:
            raise PermissionDenied(
                    _("not permitted to end session"))

        grading_rule = get_session_grading_rule(
                flow_session, pctx.role, fctx.flow_desc, now_datetime)
        grade_info = finish_flow_session(
                fctx, flow_session, grading_rule,
                now_datetime=now_datetime)

        if is_graded_flow:
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

    if (not is_graded_flow
            or
            (flow_session.in_progress
                and flow_permission.end_session not in access_rule.permissions)):
        # No ability to end--just show completion page.

        return render_finish_response(
                "course/flow-completion.html",
                last_page_nr=flow_session.page_count-1,
                flow_session=flow_session,
                completion_text=completion_text)

    elif not flow_session.in_progress:
        # Just reviewing: re-show grades.
        grade_info = gather_grade_info(fctx, flow_session, answer_visits)

        return render_finish_response(
                "course/flow-completion-grade.html",
                completion_text=completion_text,
                grade_info=grade_info)

    else:
        # confirm ending flow
        return render_finish_response(
                "course/flow-confirm-completion.html",
                last_page_nr=flow_session.page_count-1,
                flow_session=flow_session,
                answered_count=answered_count,
                unanswered_count=unanswered_count,
                total_count=answered_count+unanswered_count)

# }}}


# {{{ view: regrade flow

class RegradeFlowForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super(RegradeFlowForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                initial=participation_role.student,
                required=True,
                label=_("Flow ID"))
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
                Submit("regrade", _("Regrade"), css_class="col-lg-offset-2"))


@transaction.atomic
def _regrade_sessions(repo, course, sessions):
    count = 0

    from course.flow import regrade_session
    for session in sessions:
        regrade_session(repo, course, session)
        count += 1

    return count


@course_view
def regrade_not_for_credit_flows_view(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied(_("must be instructor to regrade flows"))

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = RegradeFlowForm(flow_ids, request.POST, request.FILES)
        if form.is_valid():
            sessions = (FlowSession.objects
                    .filter(
                        course=pctx.course,
                        flow_id=form.cleaned_data["flow_id"]))
            if form.cleaned_data["access_rules_tag"]:
                sessions = sessions.filter(
                        access_rules_tag=form.cleaned_data["access_rules_tag"])

            inprog_value = {
                    "any": None,
                    "yes": True,
                    "no": False,
                    }[form.cleaned_data["regraded_session_in_progress"]]

            if inprog_value is not None:
                sessions = sessions.filter(
                        in_progress=inprog_value)

            count = _regrade_sessions(pctx.repo, pctx.course, sessions)

            messages.add_message(request, messages.SUCCESS,
                    _("%d sessions regraded.") % count)
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

# vim: foldmethod=marker
