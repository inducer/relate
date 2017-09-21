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

from django import http
from django.core.exceptions import PermissionDenied, SuspiciousOperation

from course.auth import with_course_api_auth, APIError
from course.constants import (
        participation_permission as pperm,
        )
import json

from course.models import FlowSession


@with_course_api_auth
def get_flow_sessions(api_ctx, course_identifier):
    if not api_ctx.has_permission(pperm.view_gradebook):
        raise PermissionDenied("token role does not have required permissions")

    try:
        flow_id = api_ctx.request.GET["flow_id"]
    except KeyError:
        raise APIError("must specify flow_id GET parameter")

    sessions = FlowSession.objects.filter(
            course=api_ctx.course,
            flow_id=flow_id)

    result = [
            dict(
                participation_username=(
                    sess.participation.user.username
                    if sess.participation is not None
                    else None),
                participation_institutional_id=(
                    sess.participation.user.institutional_id
                    if sess.participation is not None
                    else None),
                active_git_commit_sha=sess.active_git_commit_sha,
                flow_id=sess.flow_id,

                start_time=sess.start_time,
                completion_time=sess.completion_time,
                last_activity_time=sess.last_activity(),
                page_count=sess.page_count,

                in_progress=sess.in_progress,
                access_rules_tag=sess.access_rules_tag,
                expiration_mode=sess.expiration_mode,
                points=sess.points,
                max_points=sess.max_points,
                result_comment=sess.result_comment,
                )
            for sess in sessions]

    return http.JsonResponse(result, safe=False)

# vim: foldmethod=marker
