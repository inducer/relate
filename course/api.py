# -*- coding: utf-8 -*-

from __future__ import division

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

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from course.auth import with_course_api_auth, APIError
from course.models import FlowSession
from course.constants import participation_permission as pperm
from course.serializers import (
    FlowSessionSerializer, FlowPageDateSerializer, FlowPageVisitSerializer,
    FlowPageVisitGradeSerializer)

# {{{ mypy

from typing import Text, Any, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from course.auth import APIContext  # noqa

# }}}


@api_view(["GET"])
@with_course_api_auth("Token")
def get_flow_sessions(api_ctx, course_identifier):
    # type: (APIContext, Text) -> Response

    if not api_ctx.has_permission(pperm.view_gradebook):
        return Response(
            exception=PermissionDenied(
                "token role does not have required permissions"),
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        flow_id = api_ctx.request.GET["flow_id"]
    except KeyError:
        raise APIError("must specify flow_id GET parameter")

    sessions = FlowSession.objects.filter(
            course=api_ctx.course,
            flow_id=flow_id)

    result = [FlowSessionSerializer(sess).data for sess in sessions]

    return Response(result)


@api_view(["GET"])
@with_course_api_auth("Token")
def get_flow_session_content(api_ctx, course_identifier):
    # type: (APIContext, Text) -> Response

    if not api_ctx.has_permission(pperm.view_gradebook):
        return Response(
            exception=PermissionDenied(
                "token role does not have required permissions"),
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        session_id_str = api_ctx.request.GET["flow_session_id"]
    except KeyError:
        raise APIError("must specify flow_id GET parameter")

    session_id = int(session_id_str)

    flow_session = get_object_or_404(FlowSession, id=session_id)

    if flow_session.course != api_ctx.course:
        return Response(
            exception=PermissionDenied(
                "session's course does not match auth context"),
            status=status.HTTP_403_FORBIDDEN
        )

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

            page_data_json = FlowPageDateSerializer(page_data).data
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
                norm_answer = None  # type: Any

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

                answer_json = FlowPageVisitSerializer(visit).data
                answer_json.pop("flow_session")
                answer_json.pop("page_data")
                if norm_answer is not None:
                    answer_json["norm_answer"] = norm_answer

                grade = visit.get_most_recent_grade()
                if grade is not None:
                    grade_json = FlowPageVisitGradeSerializer(grade).data
                    grade_json.pop("visit")
                    grade_json.pop("grade_data")

            pages.append({
                "page": page_data_json,
                "answer": answer_json,
                "grade": grade_json,
                })

    result = {
        "session": FlowSessionSerializer(flow_session).data,
        "pages": pages,
        }

    return Response(result)


# vim: foldmethod=marker
