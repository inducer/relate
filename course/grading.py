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


import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, NotRequired, TypedDict, cast

from django import http
from django.contrib import messages
from django.core import signing
from django.core.exceptions import (
    ObjectDoesNotExist,
    PermissionDenied,
    SuspiciousOperation,
)
from django.shortcuts import (
    get_object_or_404,
    render,
)
from django.utils.translation import gettext as _
from pydantic import BaseModel, ConfigDict, ValidationError
from pytools import not_none

from course.constants import ParticipationPermission as PPerm
from course.models import (
    FlowPageVisitGrade,
    FlowSession,
    get_feedback_for_grade,
    get_flow_grading_opportunity,
)
from course.page import InvalidPageData
from course.utils import (
    FlowPageContext,
    course_view,
    get_session_grading_mode,
    render_course_page,
)
from course.views import get_now_or_fake_time
from relate.utils import retry_transaction_decorator


# {{{ for mypy

if TYPE_CHECKING:
    import datetime

    from django.db.models import query

    from course.models import GradingOpportunity
    from course.page.base import AnswerData, GradeData
    from course.utils import CoursePageContext
    from relate.utils import StyledFormBase

# }}}


@dataclass
class PointsSpec:
    points: float | None
    max_points: float | None
    identifier: str | None
    match_start: int
    match_length: int


def parse_points_specs(feedback_text: str) -> list[PointsSpec]:
    """Parse feedback points specifications, with UTF-16 offsets for JS clients."""
    def parse_number(text: str) -> float:
        # Match Number.parseFloat's numeric-prefix behavior.
        match = re.match(r"\s*(-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+))", text)
        if match is None:
            raise ValueError(f"Numeral not understood: {text}")
        return float(match[1])

    result: list[PointsSpec] = []
    for body_match in re.finditer(r"\[pts:\s*([^\]]*)\]", feedback_text):
        body = body_match[1]
        match = re.fullmatch(
            r"([-0-9.]*)\s*((?:/\s*[-0-9.]*)?)\s*"
            r"((?:#[a-zA-Z_][a-zA-Z_0-9]*)?)\s*", body)
        if match is None:
            raise ValueError(f"Points spec not understood: '{body}'")

        points_str, max_points_str, identifier_str = match.groups()
        points = parse_number(points_str) if points_str else None
        max_points = parse_number(max_points_str[1:]) if max_points_str else None
        if max_points is not None and max_points <= 0:
            raise ValueError(f"Point denominator must be positive: '{body}'")

        result.append(PointsSpec(
            points=points,
            max_points=max_points,
            identifier=identifier_str or None,
            match_start=len(feedback_text[:body_match.start()].encode(
                "utf-16-le", errors="surrogatepass")) // 2,
            match_length=len(body_match[0].encode(
                "utf-16-le", errors="surrogatepass")) // 2,
        ))
    return result


class PointsTotals(TypedDict):
    points: float | None
    maxPoints: float | None


def sum_points_specs(points_specs: list[PointsSpec]) -> PointsTotals:
    """Sum points and explicit denominators, rejecting missing point values.

    Totals remain *None* if no corresponding values occur in *points_specs*.
    """
    points = None
    max_points = None
    for pspec in points_specs:
        if pspec.points is None:
            raise ValueError("Not applying points total when a pts spec "
                             "is missing a point value.")
        points = (0 if points is None else points) + pspec.points
        if pspec.max_points is not None:
            max_points = (0 if max_points is None else max_points) + pspec.max_points

    return {"points": points, "maxPoints": max_points}


def get_prev_visit_grades(
            course_identifier: str,
            flow_session_id: int,
            page_ordinal: int,
            reversed_on_visit_time_and_grade_time: bool | None = False
        ) -> query.QuerySet[FlowPageVisitGrade]:
    order_by_args: list[str] = []
    if reversed_on_visit_time_and_grade_time:
        order_by_args = ["-visit__visit_time", "-grade_time"]
    return (FlowPageVisitGrade.objects
            .filter(
                visit__flow_session_id=flow_session_id,
                visit__page_data__page_ordinal=page_ordinal,
                visit__is_submitted_answer=True,
                visit__flow_session__course__identifier=course_identifier)
            .order_by(*order_by_args)
            .select_related("visit"))


@course_view
def get_prev_grades_dropdown_content(pctx, flow_session_id, page_ordinal,
                                     prev_grade_id):
    """
    :return: serialized prev_grades items for rendering past-grades-dropdown
    """
    request = pctx.request
    if request.method != "GET":
        raise PermissionDenied()

    if not pctx.participation:
        raise PermissionDenied(_("may not view grade book"))
    if not pctx.participation.has_permission(PPerm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))

    page_ordinal = int(page_ordinal)
    flow_session_id = int(flow_session_id)

    prev_grades = get_prev_visit_grades(pctx.course_identifier,
                                        flow_session_id, page_ordinal, True)

    return render(pctx.request, "course/prev-grades-dropdown.html", {
                      "prev_grades": prev_grades,
                      "prev_grade_id": (
                          None
                          if prev_grade_id == "None" else
                          int(prev_grade_id)),
                  })


# {{{ grading driver

AI_DRAFT_TICKET_SALT = "course.ai-grade-draft"
AI_DRAFT_MAX_AGE = 15 * 60


class AIGradeDraftResponse(TypedDict):
    state: Literal["pending", "ready", "failed", "unavailable"]
    message: NotRequired[str]


class AIGradeDraftTaskResult(AIGradeDraftResponse):
    """Worker result, including the saved grade ID for stale-result checks."""

    grade_id: NotRequired[int]


class AIGradeDraftTicket(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(strict=True, extra="forbid")

    task_id: str
    user_id: int
    course_id: int
    visit_id: int
    grade_id: int | None


@course_view
def ai_grade_draft_return(pctx: CoursePageContext) -> http.HttpResponse:
    """Retrieve a saved draft only for the grader and submission that requested it."""
    from celery import states
    from celery.result import AsyncResult

    if pctx.request.method != "GET":
        return http.HttpResponseNotAllowed(["GET"])
    if not all(pctx.has_permission(permission) for permission in (
            PPerm.view_gradebook, PPerm.assign_grade, PPerm.use_ai_drafting)):
        raise PermissionDenied(_("may not draft AI grades"))
    try:
        ticket = AIGradeDraftTicket.model_validate(signing.loads(
            pctx.request.GET.get("ticket", ""),
            salt=AI_DRAFT_TICKET_SALT, max_age=AI_DRAFT_MAX_AGE))
    except signing.SignatureExpired:
        payload: AIGradeDraftResponse = {"state": "unavailable", "message": _(
            "This AI draft has expired. Please request a new draft.")}
        return http.JsonResponse(payload)
    except (signing.BadSignature, ValidationError) as exc:
        raise PermissionDenied(_("Invalid AI draft ticket.")) from exc
    if (ticket.user_id != pctx.request.user.pk
            or ticket.course_id != pctx.course.pk):
        raise PermissionDenied(_("AI draft belongs to another grader or course."))

    from course.models import FlowPageVisit
    visit = get_object_or_404(FlowPageVisit, pk=ticket.visit_id,
                             flow_session__course=pctx.course)
    current_visit = (FlowPageVisit.objects.filter(
            page_data=visit.page_data, is_submitted_answer=True)
            .order_by("-visit_time", "-pk").first())
    result: AsyncResult[AIGradeDraftTaskResult] = AsyncResult(ticket.task_id)
    task_result = result.result if result.state == states.SUCCESS else None
    saved_grade_id = (task_result.get("grade_id")
                      if isinstance(task_result, dict)
                      and task_result.get("state") == "ready" else None)
    current_grade = visit.get_most_recent_grade()
    if (visit.flow_session.in_progress or current_visit != visit
            or ((current_grade.pk if current_grade else None) != ticket.grade_id
                and (saved_grade_id is None or current_grade is None
                     or current_grade.pk != saved_grade_id))):
        payload = {"state": "unavailable", "message": _(
            "The submission or grade changed while drafting. "
            "Please request a new draft.")}
        return http.JsonResponse(payload)
    if result.state == states.SUCCESS:
        # The saved grade ID is only needed for the stale-result check above.
        # The browser simply reloads the grading page when the draft is ready.
        assert isinstance(task_result, dict)
        payload = {"state": "ready"} if saved_grade_id is not None else task_result
    elif result.state in {states.FAILURE, states.REVOKED}:
        error = result.result
        payload = {"state": "failed", "message": _(
            "AI drafting failed. Please try again or contact "
            "the course administrator.") + f"\n{type(error).__name__}: {error}"}
    else:
        payload = {"state": "pending"}
    response = http.JsonResponse(payload)
    response["Cache-Control"] = "no-store"
    return response


@course_view
def grade_flow_page(
        pctx: CoursePageContext,
        flow_session_id: int,
        page_ordinal: int
        ) -> http.HttpResponse:
    now_datetime = get_now_or_fake_time(pctx.request)

    page_ordinal = int(page_ordinal)

    viewing_prev_grade = False
    prev_grade_id_str = pctx.request.GET.get("grade_id")
    if prev_grade_id_str is not None:
        try:
            prev_grade_id = int(prev_grade_id_str)
            viewing_prev_grade = True
        except ValueError:
            raise SuspiciousOperation("non-integer passed for 'grade_id'")
    else:
        prev_grade_id = None

    if not pctx.has_permission(PPerm.view_gradebook):
        raise PermissionDenied(_("may not view grade book"))
    assert pctx.request.user.is_authenticated

    flow_session = get_object_or_404(FlowSession, id=int(flow_session_id))

    if flow_session.course.pk != pctx.course.pk:
        raise SuspiciousOperation(
                _("Flow session not part of specified course"))
    if flow_session.participation is None:
        raise SuspiciousOperation(
                _("Cannot grade anonymous session"))

    from course.flow import adjust_flow_session_page_data
    adjust_flow_session_page_data(pctx.repo, flow_session, respect_preview=False)

    fpctx = FlowPageContext(pctx.repo, pctx.course, flow_session.flow_id,
                            page_ordinal, participation=flow_session.participation,
                            flow_session=flow_session, request=pctx.request)

    if fpctx.page is None:
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

    prev_grades = get_prev_visit_grades(pctx.course_identifier, flow_session_id,
                                        page_ordinal)

    # {{{ reproduce student view

    form = None
    feedback = None
    answer_data = None
    grade_data = None
    shown_grade = None

    page_expects_answer = fpctx.page.expects_answer()

    if page_expects_answer:
        if fpctx.prev_answer_visit is not None and prev_grade_id is None:
            answer_data = cast("AnswerData", fpctx.prev_answer_visit.answer)

            shown_grade = fpctx.prev_answer_visit.get_most_recent_grade()
            if shown_grade is not None:
                feedback = get_feedback_for_grade(shown_grade)
                grade_data = cast("GradeData | None", shown_grade.grade_data)
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
            grade_data = cast("GradeData | None", shown_grade.grade_data)
            answer_data = cast("AnswerData | None", shown_grade.visit.answer)

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

    from course.page.base import PageBaseWithHumanTextFeedback

    candidate = fpctx.page
    ai_page = (
            candidate
            if isinstance(candidate, PageBaseWithHumanTextFeedback)
            and candidate.supports_ai_grading() else None)
    may_draft_ai = (
            ai_page is not None
            and pctx.has_permission(PPerm.assign_grade)
            and pctx.has_permission(PPerm.use_ai_drafting)
            and bool(pctx.course.ai_grading_api_base_url
                and pctx.course.ai_grading_api_key
                and pctx.course.ai_grading_model))
    grading_form: StyledFormBase | None = None

    if (page_expects_answer
            and fpctx.page.is_answer_gradable()
            and fpctx.prev_answer_visit is not None
            and not flow_session.in_progress
            and not viewing_prev_grade):
        request = pctx.request
        if pctx.request.method == "POST":
            if not pctx.has_permission(PPerm.assign_grade):
                raise PermissionDenied(_("may not assign grades"))

            post_data = request.POST
            drafting_ai = "draft_ai_grade" in post_data
            if drafting_ai:
                if not pctx.has_permission(PPerm.use_ai_drafting):
                    raise PermissionDenied(_("may not draft AI grades"))
                if ai_page is None:
                    raise SuspiciousOperation(_("Page does not support AI grading."))

                if (post_data.get("ai_draft_visit_id")
                        != str(fpctx.prev_answer_visit.pk)
                        or post_data.get("ai_draft_grade_id")
                        != (str(shown_grade.pk) if shown_grade else "")):
                    return http.JsonResponse({"message": _(
                        "The displayed submission or grade is out of date. "
                        "Please refresh the page before drafting.")}, status=409)

                from course.repo import serialize_revision
                from course.tasks import draft_ai_grade
                result = draft_ai_grade.delay(
                        pctx.course.pk, fpctx.prev_answer_visit.pk,
                        serialize_revision(fpctx.page_context.commit_sha),
                        shown_grade.pk if shown_grade else None,
                        initiated_by_id=request.user.pk)
                ticket_data = AIGradeDraftTicket(
                    task_id=result.id,
                    user_id=not_none(request.user.pk),
                    course_id=pctx.course.pk,
                    visit_id=fpctx.prev_answer_visit.pk,
                    grade_id=shown_grade.pk if shown_grade else None,
                )
                ticket = signing.dumps(ticket_data.model_dump(),
                                       salt=AI_DRAFT_TICKET_SALT)
                response = http.JsonResponse({"ticket": ticket})
                response["Cache-Control"] = "no-store"
                return response

            grading_form = fpctx.page.post_grading_form(
                    fpctx.page_context, fpctx.page_data, grade_data,
                    post_data, request.FILES)
            if grading_form.is_valid():
                grade_data = fpctx.page.update_grade_data_from_grading_form_v2(
                        request,
                        fpctx.page_context, fpctx.page_data, grade_data,
                        grading_form, request.FILES)
                most_recent_grade = _save_grade(
                        fpctx, flow_session, grade_data,
                        not_none(pctx.request.user.pk), now_datetime)
                feedback = get_feedback_for_grade(most_recent_grade)
                prev_grade_id = most_recent_grade.pk
        else:
            grading_form = fpctx.page.make_grading_form(
                    fpctx.page_context, fpctx.page_data, grade_data)

    else:
        grading_form = None

    grading_form_html: str | None = None

    if grading_form is not None:
        from crispy_forms.layout import Submit
        grading_form.helper.form_class += " relate-grading-form"
        grading_form.helper.add_input(
                Submit(
                    "submit", _("Submit"),
                    css_class="relate-grading-save-button"))

        if may_draft_ai:
            grading_form.helper.add_input(Submit(
                    "draft_ai_grade", _("Draft with AI"),
                    css_class="btn-secondary relate-ai-draft-button",
                    formnovalidate="formnovalidate"))

        grading_form_html = fpctx.page.grading_form_to_html(
                pctx.request, fpctx.page_context, grading_form, grade_data)

    # }}}

    # {{{ compute points_awarded

    max_points = None
    points_awarded = None
    if (page_expects_answer
            and fpctx.page.is_answer_gradable()):
        max_points = fpctx.page.max_points(fpctx.page_data)
        if feedback is not None and feedback.correctness is not None:
            points_awarded = max_points * feedback.correctness

    # }}}

    grading_rule = get_session_grading_mode(
            flow_session, fpctx.flow_desc, get_now_or_fake_time(pctx.request))

    if grading_rule.grade_identifier is not None:
        grading_opportunity: GradingOpportunity | None = \
                get_flow_grading_opportunity(
                        pctx.course, flow_session.flow_id, fpctx.flow_desc,
                        grading_rule.grade_identifier,
                        not_none(grading_rule.grade_aggregation_strategy))
    else:
        grading_opportunity = None

    return render_course_page(
            pctx,
            "course/grade-flow-page.html",
            {
                "flow_identifier": fpctx.flow_id,
                "flow_session": flow_session,
                "flow_desc": fpctx.flow_desc,
                "page_ordinal": fpctx.page_ordinal,
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
                "expects_answer": page_expects_answer,

                "grading_opportunity": grading_opportunity,

                "prev_flow_session_id": prev_flow_session_id,
                "next_flow_session_id": next_flow_session_id,

                "ai_draft_visit_id": (fpctx.prev_answer_visit.pk
                    if fpctx.prev_answer_visit else None),
                "ai_draft_grade_id": shown_grade.pk if shown_grade else None,
                "grading_form": grading_form,
                "grading_form_html": grading_form_html,
                "correct_answer": fpctx.page.page_correct_answer(
                    fpctx.page_context, fpctx.page_data.data,
                    answer_data, grade_data),
            })


def _save_grade(
        fpctx: FlowPageContext,
        flow_session: FlowSession,
        grade_data: GradeData,
        grader_id: int,
        now_datetime: datetime.datetime,
        ) -> FlowPageVisitGrade:
    """Evaluate first, then store the grade and recompute its session atomically."""
    from course.flow import grade_flow_session
    from course.grade_storage import evaluate_grade, persist_evaluated_grade

    assert fpctx.page is not None
    assert fpctx.page_context is not None

    visit = not_none(fpctx.prev_answer_visit)
    page_context = fpctx.page_context
    evaluated = evaluate_grade(visit, fpctx.page, page_context, grade_data)

    @retry_transaction_decorator()
    def store_grade_and_update_session() -> FlowPageVisitGrade:
        grade = persist_evaluated_grade(
                visit, page_context, grade_data, evaluated, grader_id=grader_id)

        grading_rule = get_session_grading_mode(
                flow_session, fpctx.flow_desc, now_datetime)
        grade_flow_session(fpctx, flow_session, grading_rule)
        return grade

    return store_grade_and_update_session()

# }}}


# {{{ grader statistics

@course_view
def show_grader_statistics(pctx, flow_id):
    if not pctx.has_permission(PPerm.view_grader_stats):
        raise PermissionDenied(_("may not view grader stats"))

    grades = (FlowPageVisitGrade.objects
            .filter(
                visit__flow_session__course=pctx.course,
                visit__flow_session__flow_id=flow_id,

                # There are just way too many autograder grades, which makes this
                # report super slow.
                grader__isnull=False,
                ai_generated_by__isnull=True)
            .order_by(
                "visit__id",
                "grade_time")
            .select_related("visit")
            .select_related("grader")
            .select_related("visit__page_data"))

    graders = set()

    # tuples: (page_ordinal, id)
    pages = set()

    counts = {}
    grader_counts = {}
    page_counts = {}

    def commit_grade_info(grade):
        grader = grade.grader
        page = (grade.visit.page_data.page_ordinal,
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
                "pages_stats_counts":
                    list(zip(pages, stats_table, page_counts, strict=True)),
                "grader_counts": grader_counts,
            })

# }}}

# vim: foldmethod=marker
