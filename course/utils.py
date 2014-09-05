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
        parse_date_spec, get_active_commit_sha)
from course.models import (
        Course,
        FlowAccessException,
        FlowPageVisit,
        participation_role,
        flow_permission
        )


# {{{ flow permissions

class FlowAccessRule(object):
    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)

    def human_readable_permissions(self):
        from course.models import FLOW_PERMISSION_CHOICES
        permission_dict = dict(FLOW_PERMISSION_CHOICES)
        return [permission_dict[p] for p in self.permissions]


def get_flow_access_rules(course, participation, flow_id, flow_desc):
    rules = []

    attr_names = [
            "id",
            "roles",
            "start",
            "end",
            "allowed_session_count",
            "credit_percent",
            "permissions",
            "is_exception",
            ]

    # {{{ scan for exceptions in database

    for exc in (
            FlowAccessException.objects
            .filter(
                participation=participation,
                flow_id=flow_id)
            .order_by("expiration")):

        attrs = {
                "is_exception": True,
                "id": "exception",
                "permissions": [entry.permission for entry in exc.entries.all()],
                }
        if exc.expiration is not None:
            attrs["end"] = exc.expiration

        if exc.stipulations is not None and isinstance(exc.stipulations, dict):
            attrs.update(exc.stipulations)

        rules.append(FlowAccessRule(**attrs))

    # }}}

    if not hasattr(flow_desc, "access_rules"):
        rules.append(
                FlowAccessRule(**{
                    "permissions": [
                        flow_permission.view,
                        flow_permission.start_no_credit],
                    "is_exception": False,
                    }))

    else:
        for rule in flow_desc.access_rules:
            attrs = dict(
                    (attr_name, getattr(rule, attr_name))
                    for attr_name in attr_names
                    if hasattr(rule, attr_name))

            if "start" in attrs:
                attrs["start"] = parse_date_spec(course, attrs["start"])
            if "end" in attrs:
                attrs["end"] = parse_date_spec(course, attrs["end"])

            rules.append(FlowAccessRule(**attrs))

    # {{{ set unavailable attrs to None

    def add_attrs_with_nones(rule):
        for attr_name in attr_names:
            if not hasattr(rule, attr_name):
                setattr(rule, attr_name, None)

    for rule in rules:
        add_attrs_with_nones(rule, )

    # }}}

    return rules


def get_flow_permissions(course, participation, role, flow_id, flow_desc,
        now_datetime, rule_id):
    rules = get_flow_access_rules(course, participation, flow_id, flow_desc)

    for rule in rules:
        if rule.roles is not None:
            if role not in rule.roles:
                continue

        if rule_id is not None and rule_id == rule.id:
            return rule.permissions, rule

        if rule.start is not None:
            if now_datetime < rule.start:
                continue

        if rule.end is not None:
            if rule.end < now_datetime:
                continue

        return rule.permissions, rule

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

        # Each session sticks to 'its' assigned rules.
        # If those are not known, use the ones that were relevant
        # when the flow started.
        if flow_session is not None:
            rule_id = flow_session.access_rules_id
            now_datetime = flow_session.start_time
        else:
            from course.views import get_now_or_fake_time
            rule_id = None
            now_datetime = get_now_or_fake_time(request)

        self.permissions, self.current_access_rule = get_flow_permissions(
                self.course, self.participation, self.role,
                flow_identifier, current_flow_desc,
                now_datetime=now_datetime,
                rule_id=rule_id)

        print self.current_access_rule.id

        # }}}

    def will_receive_feedback(self):
        from course.models import flow_permission
        return (
                flow_permission.see_correctness in self.permissions
                or flow_permission.see_answer in self.permissions)

    @property
    def stipulations(self):
        from warnings import warn
        warn("FlowContext.stipulations is deprecated--use '.current_access_rule'",
                DeprecationWarning)

        return self.current_access_rule

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

        from course.flow import get_flow_session_graded_answers_qset
        previous_answer_visits = (
                get_flow_session_graded_answers_qset(flow_session)
                .filter(page_data=page_data)
                .order_by("-visit_time"))

        self.prev_answer_visit = None
        for prev_visit in previous_answer_visits[:1]:
            self.prev_answer_visit = prev_visit

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
