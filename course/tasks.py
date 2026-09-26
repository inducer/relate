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

from typing import TYPE_CHECKING

from celery import Task, shared_task
from django.db import transaction
from django.utils.translation import gettext as _

from course.content import get_course_repo
from course.models import Course, FlowPageData, FlowPageVisit, FlowSession


if TYPE_CHECKING:
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


@shared_task(bind=True)
def ai_grade_flow_page(
        self: Task[..., dict[str, str]],
        course_id: int,
        flow_id: str,
        group_id: str,
        page_id: str,
        ) -> dict[str, str]:
    from course.ai_grading import (
        AIGradingError,
        create_ai_grade,
        gather_calibration_examples,
        get_openai_client,
        run_ai_grading_for_visit,
    )
    from course.content import get_course_commit_sha, get_flow_desc, get_flow_page
    from course.page import PageContext
    from course.page.base import PageBaseWithHumanTextFeedback

    course = Course.objects.get(id=course_id)
    repo = get_course_repo(course)

    course_commit_sha: RevisionID_ish = get_course_commit_sha(course, None)
    flow_desc = get_flow_desc(repo, course, flow_id, course_commit_sha)
    page = get_flow_page(flow_id, flow_desc, group_id, page_id)

    if not isinstance(page, PageBaseWithHumanTextFeedback):
        repo.close()
        return {"message": _(
            "Page '%(group_id)s/%(page_id)s' does not support human "
            "(or AI) grading.")
            % {"group_id": group_id, "page_id": page_id}}

    try:
        get_openai_client(course)
    except AIGradingError as exc:
        repo.close()
        return {"message": str(exc)}

    no_session_page_context = PageContext(
            course=course, repo=repo, commit_sha=course_commit_sha,
            flow_session=None)

    calibration_examples = gather_calibration_examples(
            course, flow_id, group_id, page_id, page,
            no_session_page_context)

    grading_prompt = page.grading_prompt

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
    failed = 0

    for i, page_data in enumerate(page_data_objs):
        self.update_state(
                state="PROGRESS", meta={"current": i, "total": n})

        visit = (FlowPageVisit.objects
                .filter(page_data=page_data, is_submitted_answer=True)
                .order_by("-visit_time")
                .first())

        if visit is None:
            skipped += 1
            continue

        most_recent_grade = visit.get_most_recent_grade()
        if (most_recent_grade is not None
                and most_recent_grade.grade_data is not None
                and most_recent_grade.ai_generated_by is None):
            # Already graded (with actual grade data, as opposed to the
            # placeholder autograded-but-ungraded row created on submission)
            # by a human -- never touch it.
            skipped += 1
            continue

        page_context = PageContext(
                course=course, repo=repo, commit_sha=course_commit_sha,
                flow_session=visit.flow_session)

        try:
            point_value = page.human_feedback_point_value(
                    page_context, page_data.data)
            ai_result = run_ai_grading_for_visit(
                    course, page, page_context, page_data.data, visit.answer,
                    point_value, grading_prompt, calibration_examples)
            create_ai_grade(
                    visit, page, page_context, course_commit_sha, ai_result)
        except AIGradingError:
            failed += 1
            continue

        drafted += 1

    repo.close()

    return {"message": _(
            "%(drafted)d grade(s) drafted, %(skipped)d already graded "
            "(skipped), %(failed)d failed.")
            % {"drafted": drafted, "skipped": skipped, "failed": failed}}


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
