from __future__ import annotations


__copyright__ = "Copyright (C) 2015 Andreas Kloeckner"

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

from typing import TYPE_CHECKING, Any, cast

from celery import Task, shared_task
from django.db import transaction
from django.utils.timezone import now
from django.utils.translation import gettext as _

from course.content import get_course_repo
from course.models import Course, FlowPageData, FlowPageVisit, FlowSession
from relate.utils import retry_transaction_decorator


if TYPE_CHECKING:
    from types import EllipsisType

    from course.ai_grading import AIGradeResult
    from course.grading import AIGradeDraftTaskResult
    from course.models import FlowPageVisitGrade
    from course.page.base import (
        GradeData,
        PageBaseWithHumanTextFeedback,
        PageContext,
        PageData,
    )
    from course.repo import RevisionID_ish


@shared_task(bind=True)
def expire_in_progress_sessions(self, course_id, flow_id, rule_tag, now_datetime,
        past_due_only):
    course = Course.objects.get(id=course_id)
    repo = get_course_repo(course)

    sessions = (FlowSession.objects
            .filter(
                course=course,
                flow_id=flow_id,
                participation__isnull=False,
                access_rules_tag=rule_tag,
                in_progress=True,
                ))

    count = 0
    nsessions = sessions.count()

    from course.flow import expire_flow_session_standalone

    for i, session in enumerate(sessions):
        if expire_flow_session_standalone(repo, course, session, now_datetime,
                past_due_only=past_due_only):
            count += 1

        self.update_state(
                state="PROGRESS",
                meta={"current": i, "total": nsessions})

    repo.close()

    return {"message": _("%d sessions expired.") % count}


@shared_task(bind=True)
def finish_in_progress_sessions(self, course_id, flow_id, rule_tag, now_datetime,
        past_due_only):
    course = Course.objects.get(id=course_id)
    repo = get_course_repo(course)

    sessions = (FlowSession.objects
            .filter(
                course=course,
                flow_id=flow_id,
                participation__isnull=False,
                access_rules_tag=rule_tag,
                in_progress=True,
                ))

    count = 0
    nsessions = sessions.count()

    from course.flow import finish_flow_session_standalone
    for i, session in enumerate(sessions):
        from course.flow import adjust_flow_session_page_data
        adjust_flow_session_page_data(repo, session, respect_preview=False)

        if finish_flow_session_standalone(repo, course, session,
                now_datetime=now_datetime, past_due_only=past_due_only):
            count += 1

        self.update_state(
                state="PROGRESS",
                meta={"current": i, "total": nsessions})

    repo.close()

    return {"message": _("%d sessions ended.") % count}


@shared_task(bind=True)
def recalculate_ended_sessions(self, course_id, flow_id, rule_tag):
    course = Course.objects.get(id=course_id)
    repo = get_course_repo(course)

    sessions = (FlowSession.objects
            .filter(
                course=course,
                flow_id=flow_id,
                participation__isnull=False,
                access_rules_tag=rule_tag,
                in_progress=False,
                ))

    nsessions = sessions.count()
    count = 0

    from course.flow import recalculate_session_grade
    for session in sessions:
        recalculate_session_grade(repo, course, session)
        count += 1

        self.update_state(
                state="PROGRESS",
                meta={"current": count, "total": nsessions})

    repo.close()

    return {"message": _("Grades recalculated for %d sessions.") % count}


@shared_task(bind=True)
def regrade_flow_sessions(self, course_id, flow_id, access_rules_tag, inprog_value):
    course = Course.objects.get(id=course_id)
    repo = get_course_repo(course)

    sessions = (FlowSession.objects
            .filter(
                course=course,
                participation__isnull=False,
                flow_id=flow_id))

    if access_rules_tag:
        sessions = sessions.filter(access_rules_tag=access_rules_tag)

    if inprog_value is not None:
        sessions = sessions.filter(in_progress=inprog_value)

    nsessions = sessions.count()
    count = 0

    from course.flow import regrade_session
    for session in sessions:
        regrade_session(repo, course, session)
        count += 1

        self.update_state(
                state="PROGRESS",
                meta={"current": count, "total": nsessions})

    repo.close()

    return {"message": _("%d sessions regraded.") % count}


@shared_task(soft_time_limit=600, time_limit=660)
def draft_ai_grade(
        course_id: int,
        visit_id: int,
        commit_sha: str,
        source_grade_id: int | None,
        initiated_by_id: int | None = None,
        ) -> AIGradeDraftTaskResult:
    """Create an unreleased, AI-attributed grade for an unchanged submission."""
    from course.ai_grading import AIGradingError, request_ai_grade
    from course.content import get_flow_desc, get_flow_page
    from course.models import FlowPageVisitGrade, get_feedback_for_grade
    from course.page import PageContext
    from course.page.base import AnswerData, PageBaseWithHumanTextFeedback
    from course.repo import deserialize_revision

    revision = deserialize_revision(commit_sha)
    course = Course.objects.get(pk=course_id)
    visit = FlowPageVisit.objects.select_related(
            "page_data", "flow_session").get(
                    pk=visit_id, flow_session__course=course)
    source_grade = (FlowPageVisitGrade.objects.get(pk=source_grade_id, visit=visit)
                    if source_grade_id is not None else None)
    grade_data = cast("GradeData", source_grade.grade_data
                      if source_grade is not None else None)
    with get_course_repo(course) as repo:
        flow_desc = get_flow_desc(repo, course, visit.flow_session.flow_id, revision)
        page = get_flow_page(visit.flow_session.flow_id, flow_desc,
                             visit.page_data.group_id, visit.page_data.page_id)
        if (not isinstance(page, PageBaseWithHumanTextFeedback)
                or not page.supports_ai_grading()):
            return {"state": "failed", "message": _(
                "Page does not support AI grading.")}
        context = PageContext(course=course, repo=repo, commit_sha=revision,
                              flow_session=visit.flow_session)
        grading_input = page.make_ai_grading_input(
                context, cast("PageData", visit.page_data.data),
                cast("AnswerData", visit.answer), grade_data,
                previous_feedback=get_feedback_for_grade(source_grade))
        if grading_input is None:
            return {"state": "failed", "message": _(
                "Page does not support AI grading.")}
        try:
            suggestion = request_ai_grade(course, grading_input)
        except AIGradingError as exc:
            import logging
            logging.getLogger(__name__).exception("AI draft request failed")
            return {"state": "failed", "message": _(
                "AI drafting failed. Please try again or contact "
                "the course administrator.") + f"\n{type(exc).__name__}: {exc}"}
        grade = _persist_ai_grade_for_visit(
                visit, page, context, suggestion,
                override_human_grades=True, redraft_ai_grades=True,
                initiated_by_id=initiated_by_id, source_grade_id=source_grade_id)
        if grade is None:
            return {"state": "unavailable", "message": _(
                "The submission or grade changed while drafting. "
                "Please request a new draft.")}
        return {"state": "ready", "grade_id": grade.pk}


@shared_task(bind=True)
def batch_ai_grade_flow_page(
        self: Task[..., dict[str, str]],
        course_id: int,
        flow_id: str,
        group_id: str,
        page_id: str,
        override_human_grades: bool = False,
        initiated_by_id: int | None = None,
        redraft_ai_grades: bool = False,
        ) -> dict[str, str]:

    from course.ai_grading import (
        AIGradingError,
        get_openai_client,
        request_ai_grade,
    )
    from course.content import get_course_commit_sha, get_flow_desc, get_flow_page
    from course.models import get_feedback_for_grade
    from course.page import PageContext
    from course.page.base import (
        AnswerData,
        PageBaseWithHumanTextFeedback,
    )

    course = Course.objects.get(id=course_id)
    with get_course_repo(course) as repo:
        course_commit_sha: RevisionID_ish = get_course_commit_sha(course, None)
        flow_desc = get_flow_desc(repo, course, flow_id, course_commit_sha)
        page = get_flow_page(flow_id, flow_desc, group_id, page_id)

        if (not isinstance(page, PageBaseWithHumanTextFeedback)
                or not page.supports_ai_grading()):
            return {"message": _(
                "Page '%(group_id)s/%(page_id)s' does not support human "
                "(or AI) grading.")
                % {"group_id": group_id, "page_id": page_id}}

        try:
            get_openai_client(course)
        except AIGradingError as exc:
            return {"message": str(exc)}

        page_data_objs = (FlowPageData.objects
                .filter(
                    flow_session__course=course,
                    flow_session__flow_id=flow_id,
                    flow_session__in_progress=False,
                    group_id=group_id,
                    page_id=page_id)
                .select_related("flow_session"))

        n = page_data_objs.count()
        drafted = 0
        skipped = 0

        for i, page_data in enumerate(page_data_objs):
            self.update_state(
                    state="PROGRESS", meta={"current": i, "total": n})

            visit = (FlowPageVisit.objects
                    .filter(page_data=page_data, is_submitted_answer=True)
                    .order_by("-visit_time", "-pk")
                    .first())

            if visit is None:
                skipped += 1
                continue

            most_recent_grade = visit.get_most_recent_grade()
            grade_data = cast(
                    "GradeData", cast("Any", most_recent_grade).grade_data
                    if most_recent_grade is not None else None)
            if (most_recent_grade is not None
                    and ((most_recent_grade.ai_generated_by is not None
                            and not redraft_ai_grades)
                        or (most_recent_grade.ai_generated_by is None
                            and grade_data is not None
                            and not override_human_grades))):
                # A placeholder with no grade data is still ungraded. Otherwise,
                # human grades and AI drafts each require their own opt-in.
                skipped += 1
                continue

            page_context = PageContext(
                    course=course, repo=repo, commit_sha=course_commit_sha,
                    flow_session=visit.flow_session)

            visit_page_data = cast("PageData", cast("Any", page_data).data)
            answer_data = cast("AnswerData", cast("Any", visit).answer)
            grading_input = page.make_ai_grading_input(
                    page_context, visit_page_data, answer_data, grade_data,
                    previous_feedback=get_feedback_for_grade(most_recent_grade))
            if grading_input is None:
                skipped += 1
                continue

            # No database transaction may span the external request.
            ai_result = request_ai_grade(course, grading_input)
            if _persist_ai_grade_for_visit(
                    visit, page, page_context, ai_result,
                    override_human_grades=override_human_grades,
                    redraft_ai_grades=redraft_ai_grades,
                    initiated_by_id=initiated_by_id):
                drafted += 1
            else:
                skipped += 1

        return {"message": _(
                "%(drafted)d grade(s) drafted, %(skipped)d already graded "
                "(skipped)")
                % {"drafted": drafted, "skipped": skipped}}


@retry_transaction_decorator()
def _persist_ai_grade_for_visit(
        requested_visit: FlowPageVisit,
        page: PageBaseWithHumanTextFeedback,
        page_context: PageContext,
        ai_result: AIGradeResult,
        *,
        override_human_grades: bool,
        redraft_ai_grades: bool,
        initiated_by_id: int | None,
        source_grade_id: int | EllipsisType | None = ...,
        ) -> FlowPageVisitGrade | None:
    """Save a completed suggestion only if its submission is still current.

    Only database work and the page's side-effect-free merge are retried, never
    the external AI request. Re-read grade data so concurrent edits are preserved.
    If supplied, source_grade_id requires that exact source (None means ungraded).
    """
    from course.flow import grade_flow_session
    from course.grade_storage import persist_grade
    from course.page import PageContext
    from course.utils import FlowContext, get_session_grading_mode

    page_data = FlowPageData.objects.select_for_update().get(
            pk=requested_visit.page_data.pk)
    visit = (FlowPageVisit.objects
            .filter(page_data=page_data, is_submitted_answer=True)
            .order_by("-visit_time", "-pk")
            .first())
    if visit is None or visit.pk != requested_visit.pk:
        return None

    flow_session = FlowSession.objects.select_for_update().get(
            pk=visit.flow_session.pk)
    if flow_session.in_progress:
        return None

    most_recent_grade = visit.get_most_recent_grade()
    if (source_grade_id is not ...
            and (most_recent_grade.pk if most_recent_grade else None)
            != source_grade_id):
        return None
    grade_data = cast(
            "GradeData", cast("Any", most_recent_grade).grade_data
            if most_recent_grade is not None else None)
    if (most_recent_grade is not None
            and ((most_recent_grade.ai_generated_by is not None
                    and not redraft_ai_grades)
                or (most_recent_grade.ai_generated_by is None
                    and grade_data is not None
                    and not override_human_grades))):
        return None

    visit.page_data = page_data
    visit.flow_session = flow_session
    current_context = PageContext(
            course=page_context.course, repo=page_context.repo,
            commit_sha=page_context.commit_sha, flow_session=flow_session)
    grade_data = page.update_grade_data_from_ai_grading(
            current_context, cast("PageData", cast("Any", page_data).data),
            grade_data, ai_result)
    grade = persist_grade(
            visit, page, current_context, grade_data,
            grader_id=initiated_by_id,
            ai_generated_by=page_context.course.ai_grading_model)
    flow_context = FlowContext(
            page_context.repo, page_context.course, flow_session.flow_id,
            flow_session.participation)
    grading_mode = get_session_grading_mode(
            flow_session, flow_context.flow_desc, now())
    grade_flow_session(flow_context, flow_session, grading_mode)
    return grade


@shared_task(bind=True)
@transaction.atomic
def purge_page_view_data(self, course_id):
    course = Course.objects.get(id=course_id)

    _num_total, num_deleted_by_kind = FlowPageVisit.objects.filter(
            flow_session__course=course,
            answer__isnull=True).delete()

    return {"message": _("%d page views purged.")
            % num_deleted_by_kind.get("course.FlowPageVisit", 0)}


# vim: foldmethod=marker
