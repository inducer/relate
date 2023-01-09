from __future__ import annotations

__copyright__ = "Copyright (C) 2017 Andreas Kloeckner"

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

from django import http
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from course.auth import with_course_api_auth, APIError
from course.constants import (
        participation_permission as pperm,
        )

from course.models import FlowSession

# {{{ mypy

from typing import Text, Any, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from course.auth import APIContext  # noqa

# }}}


def flow_session_to_json(sess: FlowSession) -> Any:
    last_activity = sess.last_activity()
    return {
            "id": sess.id,
            "participation_username": (
                sess.participation.user.username
                if sess.participation is not None
                else None),
            "participation_institutional_id": (
                sess.participation.user.institutional_id
                if sess.participation is not None
                else None),
            "active_git_commit_sha": sess.active_git_commit_sha,
            "flow_id": sess.flow_id,

            "start_time": sess.start_time.isoformat(),
            "completion_time": sess.completion_time,
            "last_activity_time": (
                last_activity.isoformat()
                if last_activity is not None
                else None),
            "page_count": sess.page_count,

            "in_progress": sess.in_progress,
            "access_rules_tag": sess.access_rules_tag,
            "expiration_mode": sess.expiration_mode,
            "points": sess.points,
            "max_points": sess.max_points,
            "result_comment": sess.result_comment,
            }


@with_course_api_auth("Token")
def get_flow_sessions(
        api_ctx: APIContext, course_identifier: str) -> http.HttpResponse:
    if not api_ctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied("token role does not have required permissions")

    try:
        flow_id = api_ctx.request.GET["flow_id"]
    except KeyError:
        raise APIError("must specify flow_id GET parameter")

    sessions = FlowSession.objects.filter(
            course=api_ctx.course,
            flow_id=flow_id)

    result = [flow_session_to_json(sess) for sess in sessions]

    return http.JsonResponse(result, safe=False)


@with_course_api_auth("Token")
def get_flow_session_content(
        api_ctx: APIContext, course_identifier: str) -> http.HttpResponse:
    if not api_ctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied("token role does not have required permissions")

    try:
        session_id_str = api_ctx.request.GET["flow_session_id"]
    except KeyError:
        raise APIError("must specify flow_id GET parameter")

    session_id = int(session_id_str)

    flow_session = get_object_or_404(FlowSession, id=session_id)

    if flow_session.course != api_ctx.course:
        raise PermissionDenied(
                "session's course does not match auth context")

    from course.content import get_course_repo
    from course.flow import adjust_flow_session_page_data, assemble_answer_visits

    with get_course_repo(api_ctx.course) as repo:
        from course.utils import FlowContext, instantiate_flow_page_with_ctx
        fctx = FlowContext(repo, api_ctx.course, flow_session.flow_id)

        adjust_flow_session_page_data(repo, flow_session, api_ctx.course.identifier,
                fctx.flow_desc)

        from course.flow import get_all_page_data
        all_page_data = get_all_page_data(flow_session)
        answer_visits = assemble_answer_visits(flow_session)

        pages = []
        for i, page_data in enumerate(all_page_data):
            page = instantiate_flow_page_with_ctx(fctx, page_data)

            assert i == page_data.page_ordinal

            page_data_json = {
                    "ordinal": i,
                    "page_type": page_data.page_type,
                    "group_id": page_data.group_id,
                    "page_id": page_data.page_id,
                    "page_data": page_data.data,
                    "title": page_data.title,
                    "bookmarked": page_data.bookmarked,
                    }
            answer_json = None
            grade_json = None

            visit = answer_visits[i]
            if visit is not None:
                from course.page.base import PageContext
                pctx = PageContext(api_ctx.course, repo, fctx.course_commit_sha,
                        flow_session)
                norm_bytes_answer_tup = page.normalized_bytes_answer(
                        pctx, page_data.data, visit.answer)

                # norm_answer needs to be JSON-encodable
                norm_answer: Any = None

                if norm_bytes_answer_tup is not None:
                    answer_file_ext, norm_bytes_answer = norm_bytes_answer_tup

                    if answer_file_ext in [".txt", ".py"]:
                        norm_answer = norm_bytes_answer.decode("utf-8")
                    elif answer_file_ext == ".json":
                        import json
                        norm_answer = json.loads(norm_bytes_answer)
                    else:
                        from base64 import b64encode
                        norm_answer = [answer_file_ext,
                                       b64encode(norm_bytes_answer).decode("utf-8")]

                answer_json = {
                        "visit_time": visit.visit_time.isoformat(),
                        "remote_address": repr(visit.remote_address),
                        "user": (
                            visit.user.username if visit.user is not None else None),
                        "impersonated_by": (
                            visit.impersonated_by.username
                            if visit.impersonated_by is not None else None),
                        "is_synthetic_visit": visit.is_synthetic,
                        "answer_data": visit.answer,
                        "answer": norm_answer,
                        }

                grade = visit.get_most_recent_grade()
                if grade is not None:
                    grade_json = {
                            "grader": (grade.grader.username
                                if grade.grader is not None else None),
                            "grade_time": grade.grade_time.isoformat(),
                            "graded_at_git_commit_sha": (
                                grade.graded_at_git_commit_sha),
                            "max_points": grade.max_points,
                            "correctness": grade.correctness,
                            "feedback": grade.feedback}

            pages.append({
                "page": page_data_json,
                "answer": answer_json,
                "grade": grade_json,
                })

    result = {
        "session": flow_session_to_json(flow_session),
        "pages": pages,
        }

    return http.JsonResponse(result, safe=False)


# vim: foldmethod=marker
