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

from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
import django.forms as forms

from django.core.exceptions import PermissionDenied, SuspiciousOperation

import datetime

from course.models import (
        Course, Participation,
        FlowAccessException,
        FlowVisit,
        participation_role, participation_status, flow_visit_state)

from course.content import (
        get_course_repo, get_course_desc, parse_date_spec,
        get_flow
        )


def get_role_and_participation(request, course):
    # "wake up" lazy object
    # http://stackoverflow.com/questions/20534577/int-argument-must-be-a-string-or-a-number-not-simplelazyobject  # noqa
    user = (request.user._wrapped
            if hasattr(request.user, '_wrapped')
            else request.user)

    if not user.is_authenticated():
        return participation_role.unenrolled, None

    participations = list(Participation.objects.filter(
            user=user, course=course))

    # The uniqueness constraint should have ensured that.
    assert len(participations) <= 1

    if len(participations) == 0:
        return participation_role.unenrolled, None

    participation = participations[0]
    if participation.status != participation_status.active:
        return participation_role.unenrolled, participation
    else:
        if participation.temporary_role:
            return participation.temporary_role, participation
        else:
            return participation.role, participation


def get_active_commit_sha(course, participation):
    sha = course.active_git_commit_sha

    if participation is not None and participation.preview_git_commit_sha:
        sha = participation.preview_git_commit_sha

    return sha.encode()


def get_flow_permissions(course_desc, participation, role, flow_id, flow):
    now = datetime.datetime.now().date()

    # {{{ scan for exceptions in database

    for exc in (
            FlowAccessException.objects
            .filter(participation=participation, flow_id=flow_id)
            .order_by("expiration")):

        if exc.expiration is not None and exc.expiration < now:
            continue

        stipulations = exc.stipulations
        if not isinstance(stipulations, dict):
            stipulations = {}
        from course.content import dict_to_struct
        stipulations = dict_to_struct(exc.stipulations)

        return (
                [entry.permission for entry in exc.entries.all()],
                stipulations
                )

    # }}}

    # {{{ interpret flow rules

    for rule in flow.access_rules:
        if hasattr(rule, "roles"):
            if role not in rule.roles:
                continue

        if hasattr(rule, "start"):
            start_date = parse_date_spec(course_desc, rule.start)
            if now < start_date:
                continue

        if hasattr(rule, "end"):
            end_date = parse_date_spec(course_desc, rule.end)
            if end_date < now:
                continue

        return rule.permissions, rule

    # }}}

    raise ValueError("Flow access rules of flow '%s' did not resolve "
            "to access answer for '%s'" % (flow_id, participation))


# {{{ views

def home(request):
    courses_and_descs = []
    for course in Course.objects.all():
        repo = get_course_repo(course)
        desc = get_course_desc(repo, course.active_git_commit_sha.encode())
        courses_and_descs.append((course, desc))

    def course_sort_key(entry):
        course, desc = entry
        return desc.course_start

    courses_and_descs.sort(key=course_sort_key)

    return render(request, "course/home.html", {
        "courses_and_descs": courses_and_descs
        })


def sign_in_by_email(request):
    # FIXME
    raise NotImplementedError()


def enroll(request, course_identifier):
    # FIXME
    raise NotImplementedError()


def course_page(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    from course.content import get_processed_course_chunks
    chunks = get_processed_course_chunks(course, course_desc,
            role)

    return render(request, "course/course-page.html", {
        "course": course,
        "course_desc": course_desc,
        "participation": participation,
        "role": role,
        "chunks": chunks,
        "participation_role": participation_role,
        })


def start_flow(request, course_identifier, flow_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)
    course = get_object_or_404(Course, identifier=course_identifier)

    flow = get_flow(repo, course, flow_identifier, commit_sha)

    permissions, stipulations = get_flow_permissions(
            course_desc, participation, role, flow_identifier, flow)

    from course.models import flow_permission
    if flow_permission.view not in permissions:
        raise PermissionDenied()

    if request.method == "POST":
        from course.content import set_up_flow_visit_page_data

        if "start_credit" in request.POST:
            raise NotImplementedError("for-credit flows")
            # FIXME for-credit
        elif "start_no_credit" in request.POST:
            visit = FlowVisit()
            visit.participation = participation
            visit.active_git_commit_sha = commit_sha.decode()
            visit.flow_id = flow_identifier
            visit.state = flow_visit_state.in_progress
            visit.save()

            request.session["flow_visit_id"] = visit.id

            page_count = set_up_flow_visit_page_data(visit, flow)
            visit.page_count = page_count

            return redirect("course.views.view_flow_page",
                    course_identifier,
                    flow_identifier,
                    0)

        else:
            raise SuspiciousOperation("unrecognized POST action")

    else:
        can_start_credit = flow_permission.start_credit in permissions
        can_start_no_credit = flow_permission.start_no_credit in permissions

        # FIXME take into account max attempts
        # FIXME resumption
        # FIXME view past

        return render(request, "course/flow-start.html", {
            "participation": participation,
            "course_desc": course_desc,
            "course": course,
            "flow": flow,
            "flow_identifier": flow_identifier,
            "can_start_credit": can_start_credit,
            "can_start_no_credit": can_start_no_credit,
            })


def view_flow_page(request, course_identifier, flow_identifier, ordinal):
    # {{{ find flow_visit
    flow_visit = None
    flow_visit_id = request.session.get("flow_visit_id")

    if flow_visit_id is not None:
        flow_visits = list(FlowVisit.objects.filter(id=flow_visit_id))

        if flow_visits and flow_visits[0].flow_id == flow_identifier:
            flow_visit, = flow_visits

        del flow_visits

    if flow_visit is None:
        messages.add_message(request, messages.WARNING,
                "No ongoing flow visit for this flow. "
                "Redirected to flow start page.")

        return redirect("course.views.start_flow",
                course_identifier,
                flow_identifier)

    # }}}

    # FIXME time limits

    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    commit_sha = flow_visit.active_git_commit_sha.encode()

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    flow = get_flow(repo, course, flow_identifier, commit_sha)

    permissions, stipulations = get_flow_permissions(
            course_desc, participation, role, flow_identifier, flow)

    from course.models import FlowPageData, FlowPageVisit
    page_data = get_object_or_404(
            FlowPageData, flow_visit=flow_visit, ordinal=ordinal)

    from course.content import get_flow_page_desc
    page_desc = get_flow_page_desc(
            flow_visit, flow, page_data.group_id, page_data.page_id)

    page_visit = FlowPageVisit()
    page_visit.flow_visit = flow_visit
    page_visit.page_data = page_data
    page_visit.save()

    return render(request, "course/flow-page.html", {
        "course": course,
        "course_desc": course_desc,
        "ordinal": ordinal,
        "page_data": page_data,
        "flow_visit": flow_visit,
        "participation": participation,
        #"flow_desc": flow_desc,
        })


# }}}

# vim: foldmethod=marker
