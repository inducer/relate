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


from django.utils.translation import ugettext as _
from django.shortcuts import (  # noqa
        get_object_or_404, redirect)
from relate.utils import (
        retry_transaction_decorator,
        as_local_time, format_datetime_local)
from django.contrib import messages
from django.core.exceptions import (  # noqa
        PermissionDenied, SuspiciousOperation,
        ObjectDoesNotExist)
from django import http

from course.models import (
        FlowSession, FlowPageVisitGrade,
        get_flow_grading_opportunity,
        get_feedback_for_grade,
        update_bulk_feedback)
from course.utils import (
        course_view, render_course_page,
        get_session_grading_rule,
        FlowPageContext)
from course.views import get_now_or_fake_time
from course.page import InvalidPageData

from django.conf import settings
from django.utils import translation
from course.constants import (
        participation_permission as pperm,
        )

# {{{ for mypy

if False:
    from typing import Text, Any, Optional, Dict  # noqa
    from course.models import (  # noqa
            GradingOpportunity)
    from course.utils import (  # noqa
            CoursePageContext)
    import datetime  # noqa
    from django.db.models import query  # noqa

# }}}


def get_prev_visit_grades(
            flow_session_id,  # type: int
            page_ordinal,  # type: int
            reversed_on_visit_time_and_grade_time=False  # type: Optional[bool]
        ):
    # type: (...) -> query.QuerySet
    order_by_args = []  # type: List[Text]
    if reversed_on_visit_time_and_grade_time:
        order_by_args = ["-visit__visit_time", "-grade_time"]
    return (FlowPageVisitGrade.objects
            .filter(
                visit__flow_session_id=flow_session_id,
                visit__page_data__ordinal=page_ordinal,
                visit__is_submitted_answer=True)
            .order_by(*order_by_args)
            .select_related("visit"))


@course_view
def get_prev_grades_dropdown_content(pctx, flow_session_id, page_ordinal):
    """
    :return: serialized prev_grades items for rendering past-grades-dropdown
    """
    request = pctx.request
    if not request.is_ajax() or request.method != "GET":
        raise PermissionDenied()

    try:
        page_ordinal = int(page_ordinal)
        flow_session_id = int(flow_session_id)
    except ValueError:
        raise http.Http404()

    if not pctx.participation:
        raise PermissionDenied(_("may not view grade book"))
    if not pctx.participation.has_permission(pperm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    prev_grades = get_prev_visit_grades(flow_session_id, page_ordinal, True)

    def serialize(obj):
        return {
            "id": obj.id,
            "visit_time": (
                format_datetime_local(as_local_time(obj.visit.visit_time))),
            "grade_time": format_datetime_local(as_local_time(obj.grade_time)),
            "value": obj.value(),
        }

    return http.JsonResponse(
        {"result": [serialize(pgrade) for pgrade in prev_grades]})


# {{{ grading driver

@course_view
def grade_flow_page(pctx, flow_session_id, page_ordinal):
    # type: (CoursePageContext, int, int) -> http.HttpResponse
    now_datetime = get_now_or_fake_time(pctx.request)

    page_ordinal = int(page_ordinal)

    viewing_prev_grade = False
    prev_grade_id = pctx.request.GET.get("grade_id")
    if prev_grade_id is not None:
        try:
            prev_grade_id = int(prev_grade_id)
            viewing_prev_grade = True
        except ValueError:
            raise SuspiciousOperation("non-integer passed for 'grade_id'")

    if not pctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    flow_session = get_object_or_404(FlowSession, id=int(flow_session_id))

    if flow_session.course.pk != pctx.course.pk:
        raise SuspiciousOperation(
                _("Flow session not part of specified course"))
    if flow_session.participation is None:
        raise SuspiciousOperation(
                _("Cannot grade anonymous session"))

    from course.flow import adjust_flow_session_page_data
    adjust_flow_session_page_data(pctx.repo, flow_session,
            pctx.course.identifier, respect_preview=False)

    fpctx = FlowPageContext(pctx.repo, pctx.course, flow_session.flow_id,
            page_ordinal, participation=flow_session.participation,
            flow_session=flow_session, request=pctx.request)

    if fpctx.page_desc is None:
        raise http.Http404()

    assert fpctx.page is not None
    assert fpctx.page_context is not None

    # {{{ enable flow session zapping

    all_flow_sessions = list(FlowSession.objects
            .filter(
                course=pctx.course,
                flow_id=flow_session.flow_id,
                participation__isnull=False,
                in_progress=flow_session.in_progress)
            .order_by(
                # Datatables will default to sorting the user list
                # by the first column, which happens to be the username.
                # Match that sorting.
                "participation__user__username",
                "start_time"))

    next_flow_session_id = None
    prev_flow_session_id = None
    for i, other_flow_session in enumerate(all_flow_sessions):
        if other_flow_session.pk == flow_session.pk:
            if i > 0:
                prev_flow_session_id = all_flow_sessions[i-1].id
            if i + 1 < len(all_flow_sessions):
                next_flow_session_id = all_flow_sessions[i+1].id

    # }}}

    prev_grades = get_prev_visit_grades(flow_session_id, page_ordinal)

    # {{{ reproduce student view

    form = None
    feedback = None
    answer_data = None
    grade_data = None
    shown_grade = None

    if fpctx.page.expects_answer():
        if fpctx.prev_answer_visit is not None and prev_grade_id is None:
            answer_data = fpctx.prev_answer_visit.answer

            shown_grade = fpctx.prev_answer_visit.get_most_recent_grade()
            if shown_grade is not None:
                feedback = get_feedback_for_grade(shown_grade)
                grade_data = shown_grade.grade_data
            else:
                feedback = None
                grade_data = None

            if shown_grade is not None:
                prev_grade_id = shown_grade.id

        elif prev_grade_id is not None:
            try:
                shown_grade = prev_grades.filter(id=prev_grade_id).get()
            except ObjectDoesNotExist:
                raise http.Http404()

            feedback = get_feedback_for_grade(shown_grade)
            grade_data = shown_grade.grade_data
            answer_data = shown_grade.visit.answer

        else:
            feedback = None

        from course.page.base import PageBehavior
        page_behavior = PageBehavior(
                show_correctness=True,
                show_answer=False,
                may_change_answer=False)

        try:
            form = fpctx.page.make_form(
                    fpctx.page_context, fpctx.page_data.data,
                    answer_data, page_behavior)
        except InvalidPageData as e:
            messages.add_message(pctx.request, messages.ERROR,
                    _(
                        "The page data stored in the database was found "
                        "to be invalid for the page as given in the "
                        "course content. Likely the course content was "
                        "changed in an incompatible way (say, by adding "
                        "an option to a choice question) without changing "
                        "the question ID. The precise error encountered "
                        "was the following: ")+str(e))

            return render_course_page(pctx, "course/course-base.html", {})

    if form is not None:
        form_html = fpctx.page.form_to_html(
                pctx.request, fpctx.page_context, form, answer_data)
    else:
        form_html = None

    # }}}

    # {{{ grading form

    if (fpctx.page.expects_answer()
            and fpctx.page.is_answer_gradable()
            and fpctx.prev_answer_visit is not None
            and not flow_session.in_progress
            and not viewing_prev_grade):
        request = pctx.request
        if pctx.request.method == "POST":
            if not pctx.has_permission(pperm.assign_grade):
                raise PermissionDenied(_("may not assign grades"))

            grading_form = fpctx.page.post_grading_form(
                    fpctx.page_context, fpctx.page_data, grade_data,
                    request.POST, request.FILES)
            if grading_form.is_valid():
                grade_data = fpctx.page.update_grade_data_from_grading_form_v2(
                        request,
                        fpctx.page_context, fpctx.page_data, grade_data,
                        grading_form, request.FILES)

                with translation.override(settings.RELATE_ADMIN_EMAIL_LOCALE):
                    feedback = fpctx.page.grade(
                            fpctx.page_context, fpctx.page_data,
                            answer_data, grade_data)

                if feedback is not None:
                    correctness = feedback.correctness
                else:
                    correctness = None

                feedback_json = None  # type: Optional[Dict[Text, Any]]
                bulk_feedback_json = None  # type: Optional[Dict[Text, Any]]

                if feedback is not None:
                    feedback_json, bulk_feedback_json = feedback.as_json()
                else:
                    feedback_json = bulk_feedback_json = None

                most_recent_grade = FlowPageVisitGrade(
                        visit=fpctx.prev_answer_visit,
                        grader=pctx.request.user,
                        graded_at_git_commit_sha=pctx.course_commit_sha,

                        grade_data=grade_data,

                        max_points=fpctx.page.max_points(fpctx.page_data),
                        correctness=correctness,
                        feedback=feedback_json)

                prev_grade_id = _save_grade(fpctx, flow_session, most_recent_grade,
                        bulk_feedback_json, now_datetime)
        else:
            grading_form = fpctx.page.make_grading_form(
                    fpctx.page_context, fpctx.page_data, grade_data)

    else:
        grading_form = None

    if grading_form is not None:
        from crispy_forms.layout import Submit
        grading_form.helper.form_class += " relate-grading-form"
        grading_form.helper.add_input(
                Submit(
                    "submit", _("Submit"),
                    accesskey="s",
                    css_class="relate-grading-save-button"))

        grading_form_html = fpctx.page.grading_form_to_html(
                pctx.request, fpctx.page_context, grading_form, grade_data)

    else:
        grading_form_html = None

    # }}}

    # {{{ compute points_awarded

    max_points = None
    points_awarded = None
    if (fpctx.page.expects_answer()
            and fpctx.page.is_answer_gradable()):
        max_points = fpctx.page.max_points(fpctx.page_data)
        if feedback is not None and feedback.correctness is not None:
            points_awarded = max_points * feedback.correctness

    # }}}

    grading_rule = get_session_grading_rule(
            flow_session, fpctx.flow_desc, get_now_or_fake_time(pctx.request))

    if grading_rule.grade_identifier is not None:
        grading_opportunity = get_flow_grading_opportunity(
                pctx.course, flow_session.flow_id, fpctx.flow_desc,
                grading_rule.grade_identifier,
                grading_rule.grade_aggregation_strategy
                )  # type: Optional[GradingOpportunity]
    else:
        grading_opportunity = None

    return render_course_page(
            pctx,
            "course/grade-flow-page.html",
            {
                "flow_identifier": fpctx.flow_id,
                "flow_session": flow_session,
                "flow_desc": fpctx.flow_desc,
                "ordinal": fpctx.ordinal,
                "page_data": fpctx.page_data,

                "body": fpctx.page.body(
                    fpctx.page_context, fpctx.page_data.data),
                "form": form,
                "form_html": form_html,
                "feedback": feedback,
                "max_points": max_points,
                "points_awarded": points_awarded,
                "shown_grade": shown_grade,
                "prev_grade_id": prev_grade_id,

                "grading_opportunity": grading_opportunity,

                "prev_flow_session_id": prev_flow_session_id,
                "next_flow_session_id": next_flow_session_id,

                "grading_form": grading_form,
                "grading_form_html": grading_form_html,
                "correct_answer": fpctx.page.correct_answer(
                    fpctx.page_context, fpctx.page_data.data,
                    answer_data, grade_data),


                # Wrappers used by JavaScript template (tmpl) so as not to
                # conflict with Django template's tag wrapper
                "JQ_OPEN": '{%',
                'JQ_CLOSE': '%}',
            })


@retry_transaction_decorator()
def _save_grade(
        fpctx,  # type: FlowPageContext
        flow_session,  # type: FlowSession
        most_recent_grade,  # type: FlowPageVisitGrade
        bulk_feedback_json,  # type: Any
        now_datetime,  # type: datetime.datetime
        ):
    # type: (...) -> int
    most_recent_grade.save()
    most_recent_grade_id = most_recent_grade.id

    update_bulk_feedback(
            fpctx.prev_answer_visit.page_data,
            most_recent_grade,
            bulk_feedback_json)

    grading_rule = get_session_grading_rule(
            flow_session, fpctx.flow_desc, now_datetime)

    from course.flow import grade_flow_session
    grade_flow_session(fpctx, flow_session, grading_rule)

    return most_recent_grade_id

# }}}


# {{{ grader statistics

@course_view
def show_grader_statistics(pctx, flow_id):
    if not pctx.has_permission(pperm.view_grader_stats):
        raise PermissionDenied(_("may not view grader stats"))

    grades = (FlowPageVisitGrade.objects
            .filter(
                visit__flow_session__course=pctx.course,
                visit__flow_session__flow_id=flow_id,

                # There are just way too many autograder grades, which makes this
                # report super slow.
                grader__isnull=False)
            .order_by(
                "visit__id",
                "grade_time")
            .select_related("visit")
            .select_related("grader")
            .select_related("visit__page_data"))

    graders = set()

    # tuples: (ordinal, id)
    pages = set()

    counts = {}
    grader_counts = {}
    page_counts = {}

    def commit_grade_info(grade):
        grader = grade.grader
        page = (grade.visit.page_data.ordinal,
                grade.visit.page_data.group_id + "/" + grade.visit.page_data.page_id)

        graders.add(grader)
        pages.add(page)

        key = (page, grade.grader)
        counts[key] = counts.get(key, 0) + 1

        grader_counts[grader] = grader_counts.get(grader, 0) + 1
        page_counts[page] = page_counts.get(page, 0) + 1

    last_grade = None

    for grade in grades.iterator():
        if last_grade is not None and last_grade.visit != grade.visit:
            commit_grade_info(last_grade)

        last_grade = grade

    if last_grade is not None:
        commit_grade_info(last_grade)

    graders = sorted(graders,
            key=lambda grader: grader.last_name if grader is not None else None)
    pages = sorted(pages)

    stats_table = [
            [
                counts.get((page, grader), 0)
                for grader in graders
                ]
            for page in pages
            ]
    page_counts = [
            page_counts.get(page, 0)
            for page in pages
            ]
    grader_counts = [
            grader_counts.get(grader, 0)
            for grader in graders
            ]

    return render_course_page(
            pctx,
            "course/grading-statistics.html",
            {
                "flow_id": flow_id,
                "pages": pages,
                "graders": graders,
                "pages_stats_counts": list(zip(pages, stats_table, page_counts)),
                "grader_counts": grader_counts,
            })

# }}}

# vim: foldmethod=marker
