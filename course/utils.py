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
        render, get_object_or_404)
from django import http

from course.views import (
        get_role_and_participation
        )
from course.content import (
        get_course_repo, get_course_desc, get_flow_desc,
        dict_to_struct, parse_date_spec, get_active_commit_sha)
from course.models import (
        Course,
        FlowAccessException,
        FlowPageVisit,
        participation_role,
        flow_permission
        )


# {{{ flow permissions

def get_flow_permissions(course, participation, role, flow_id, flow_desc,
        now_datetime):
    # {{{ interpret flow rules

    flow_rule = None

    if not hasattr(flow_desc, "access_rules"):
        flow_rule = dict_to_struct(
                {"permissions":
                    [flow_permission.view, flow_permission.start_no_credit]})
    else:
        for rule in flow_desc.access_rules:
            if hasattr(rule, "roles"):
                if role not in rule.roles:
                    continue

            if hasattr(rule, "start"):
                start_date = parse_date_spec(course, rule.start)
                if now_datetime < start_date:
                    continue

            if hasattr(rule, "end"):
                end_date = parse_date_spec(course, rule.end)
                if end_date < now_datetime:
                    continue

            flow_rule = rule
            break

    # }}}

    # {{{ scan for exceptions in database

    for exc in (
            FlowAccessException.objects
            .filter(participation=participation, flow_id=flow_id)
            .order_by("expiration")):

        if exc.expiration is not None and exc.expiration < now_datetime:
            continue

        exc_stipulations = exc.stipulations
        if not isinstance(exc_stipulations, dict):
            exc_stipulations = {}

        stipulations = {}

        if flow_rule is not None:
            stipulations.update(
                    (key, val)
                    for key, val in flow_rule.__dict__.iteritems()
                    if not key.startswith("_"))

        stipulations.update(exc_stipulations)
        stipulations = dict_to_struct(stipulations)

        return (
                [entry.permission for entry in exc.entries.all()],
                stipulations
                )

    # }}}

    if flow_rule is not None:
        return flow_rule.permissions, flow_rule

    raise ValueError("Flow access rules of flow '%s' did not resolve "
            "to access answer for '%s'" % (flow_id, participation))


def instantiate_flow_page_with_ctx(fctx, page_data):
    from course.content import get_flow_page_desc
    page_desc = get_flow_page_desc(
            fctx.flow_session, fctx.flow_desc, page_data.group_id, page_data.page_id)

    from course.content import instantiate_flow_page
    return instantiate_flow_page(
            "course '%s', flow '%s', page '%s/%s'"
            % (fctx.course_identifier, fctx.flow_identifier,
                page_data.group_id, page_data.page_id),
            fctx.repo, page_desc, fctx.flow_commit_sha)

# }}}


# {{{ contexts

class CoursePageContext(object):
    def __init__(self, request, course_identifier):
        self.request = request
        self.course_identifier = course_identifier

        self.course = get_object_or_404(Course, identifier=course_identifier)
        self.role, self.participation = get_role_and_participation(
                request, self.course)

        from course.views import check_course_state
        check_course_state(self.course, self.role)

        self.course_commit_sha = get_active_commit_sha(
                self.course, self.participation)

        self.repo = get_course_repo(self.course)
        self.course_desc = get_course_desc(self.repo, self.course,
                self.course_commit_sha)


class FlowContext(CoursePageContext):
    def __init__(self, request, course_identifier, flow_identifier,
            flow_session=None):
        CoursePageContext.__init__(self, request, course_identifier)

        self.flow_session = flow_session
        self.flow_identifier = flow_identifier

        from course.content import get_flow_commit_sha
        from django.core.exceptions import ObjectDoesNotExist

        # Fetch 'current' version of the flow to compute permissions
        # and versioning rules.
        # Fall back to 'old' version if current git version does not
        # contain this flow any more.

        try:
            current_flow_desc_sha = self.course_commit_sha
            current_flow_desc = get_flow_desc(self.repo, self.course,
                    flow_identifier, current_flow_desc_sha)
        except ObjectDoesNotExist:
            if self.flow_session is None:
                raise http.Http404()

            current_flow_desc_sha = self.flow_session.active_git_commit_sha.encode()
            current_flow_desc = get_flow_desc(self.repo, self.course,
                    flow_identifier, current_flow_desc_sha)

        self.flow_commit_sha = get_flow_commit_sha(
                self.course, self.participation,
                current_flow_desc, self.flow_session)
        if self.flow_commit_sha == current_flow_desc_sha:
            self.flow_desc = current_flow_desc
        else:
            self.flow_desc = get_flow_desc(self.repo, self.course,
                flow_identifier, self.flow_commit_sha)

        # {{{ figure out permissions

        from course.views import get_now_or_fake_time
        self.permissions, self.stipulations = get_flow_permissions(
                self.course, self.participation, self.role,
                flow_identifier, current_flow_desc,
                get_now_or_fake_time(request))

        # }}}

    def will_receive_feedback(self):
        from course.models import flow_permission
        return (
                flow_permission.see_correctness in self.permissions
                or flow_permission.see_answer in self.permissions)

    @property
    def page_count(self):
        return self.flow_session.page_count


class FlowPageContext(FlowContext):
    """This object acts as a container for all the information that a flow page
    may need to render itself or respond to a POST.

    Note that this is different from :class:`course.page.PageContext`,
    which is used for in the page API.
    """

    def __init__(self, request, course_identifier, flow_identifier,
            ordinal, flow_session):
        FlowContext.__init__(self, request, course_identifier, flow_identifier,
                flow_session=flow_session)

        from course.models import FlowPageData
        page_data = self.page_data = get_object_or_404(
                FlowPageData, flow_session=flow_session, ordinal=ordinal)

        from course.content import get_flow_page_desc
        self.page_desc = get_flow_page_desc(
                flow_session, self.flow_desc, page_data.group_id, page_data.page_id)

        self.page = instantiate_flow_page_with_ctx(self, page_data)

        from course.page import PageContext
        self.page_context = PageContext(
                course=self.course, repo=self.repo, commit_sha=self.flow_commit_sha)

        # {{{ dig for previous answers

        from django.db.models import Q
        previous_answer_visits = (FlowPageVisit.objects
                .filter(flow_session=flow_session)
                .filter(page_data=page_data)
                .filter(Q(answer__isnull=False) | Q(is_synthetic=True))
                .order_by("-visit_time"))

        self.prev_answer_visit = None
        for prev_visit in previous_answer_visits[:1]:
            self.prev_answer_visit = prev_visit

            if not self.flow_session.in_progress:
                assert prev_visit.is_graded_answer, prev_visit.id

        # }}}

    @property
    def ordinal(self):
        return self.page_data.ordinal

    @property
    def percentage_done(self):
        return int(100*(self.ordinal+1)/self.page_count)

    def create_visit(self, request):
        page_visit = FlowPageVisit()
        page_visit.flow_session = self.flow_session
        page_visit.page_data = self.page_data
        page_visit.remote_address = request.META['REMOTE_ADDR']
        page_visit.save()


# }}}


def course_view(f):
    def wrapper(request, course_identifier, *args, **kwargs):
        pctx = CoursePageContext(request, course_identifier)
        return f(pctx, *args, **kwargs)

    from functools import update_wrapper
    update_wrapper(wrapper, f)

    return wrapper


def render_course_page(pctx, template_name, args):
    args = args.copy()

    args.update({
        "course": pctx.course,
        "course_desc": pctx.course_desc,
        "participation": pctx.participation,
        "role": pctx.role,
        "participation_role": participation_role,
        })

    return render(pctx.request, template_name, args)


# {{{ page cache

class PageInstanceCache(object):
    """Caches instances of :class:`course.page.Page`."""

    def __init__(self, repo, course, flow_identifier):
        self.repo = repo
        self.course = course
        self.flow_identifier = flow_identifier
        self.flow_desc_cache = {}
        self.page_cache = {}

    def get_flow_desc_from_cache(self, commit_sha):
        try:
            return self.flow_desc_cache[commit_sha]
        except KeyError:
            flow_desc = get_flow_desc(self.repo, self.course,
                    self.flow_identifier, commit_sha)
            self.flow_desc_cache[commit_sha] = flow_desc
            return flow_desc

    def get_page(self, group_id, page_id, commit_sha):
        key = (group_id, page_id, commit_sha)
        try:
            return self.page_cache[key]
        except KeyError:

            from course.content import get_flow_page_desc, instantiate_flow_page
            page_desc = get_flow_page_desc(
                    self.flow_identifier,
                    self.get_flow_desc_from_cache(commit_sha),
                    group_id, page_id)

            page = instantiate_flow_page(
                    location="flow '%s', group, '%s', page '%s'"
                    % (self.flow_identifier, group_id, page_id),
                    repo=self.repo, page_desc=page_desc,
                    commit_sha=commit_sha)

            self.page_cache[key] = page
            return page

# }}}

# vim: foldmethod=marker
