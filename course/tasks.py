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

from celery import shared_task
from django.db import transaction
from django.utils.translation import gettext as _

from course.content import get_course_repo
from course.models import Course, FlowPageVisit, FlowSession


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
        adjust_flow_session_page_data(repo, session, course.identifier,
                respect_preview=False)

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
@transaction.atomic
def purge_page_view_data(self, course_id):
    course = Course.objects.get(id=course_id)

    _num_total, num_deleted_by_kind = FlowPageVisit.objects.filter(
            flow_session__course=course,
            answer__isnull=True).delete()

    return {"message": _("%d page views purged.")
            % num_deleted_by_kind.get("course.FlowPageVisit", 0)}


# vim: foldmethod=marker
