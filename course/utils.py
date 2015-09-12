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
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import ugettext as _

from course.views import (
        get_role_and_participation
        )
from course.content import (
        get_course_repo, get_course_desc, get_flow_desc,
        parse_date_spec, get_course_commit_sha)
from course.constants import (
        participation_role,
        flow_permission, flow_rule_kind)
from course.models import (
        Course,
        FlowRuleException,
        InstantFlowRequest,
        FlowSession)


# {{{ flow permissions

class FlowSessionRuleBase(object):
    def __init__(self, **attrs):
        for name in self.__slots__:
            setattr(self, name, attrs.get(name))


class FlowSessionStartRule(FlowSessionRuleBase):
    __slots__ = [
            "tag_session",
            "may_start_new_session",
            "may_list_existing_sessions",
            ]


class FlowSessionAccessRule(FlowSessionRuleBase):
    __slots__ = [
            "permissions",
            "message",
            ]

    def human_readable_permissions(self):
        from course.models import FLOW_PERMISSION_CHOICES
        permission_dict = dict(FLOW_PERMISSION_CHOICES)
        return [permission_dict[p] for p in self.permissions]


class FlowSessionGradingRule(FlowSessionRuleBase):
    __slots__ = [
            "grade_identifier",
            "grade_aggregation_strategy",
            "due",
            "description",
            "credit_percent",
            ]


def _eval_generic_conditions(rule, course, role, now_datetime):
    if hasattr(rule, "if_before"):
        ds = parse_date_spec(course, rule.if_before)
        if not (now_datetime <= ds):
            return False

    if hasattr(rule, "if_after"):
        ds = parse_date_spec(course, rule.if_after)
        if not (now_datetime >= ds):
            return False

    if hasattr(rule, "if_has_role"):
        if role not in rule.if_has_role:
            return False

    return True


def get_flow_rules(flow_desc, kind, participation, flow_id, now_datetime,
        consider_exceptions=True, default_rules_desc=[]):
    if (not hasattr(flow_desc, "rules")
            or not hasattr(flow_desc.rules, kind)):
        rules = default_rules_desc[:]
    else:
        rules = getattr(flow_desc.rules, kind)[:]

    if consider_exceptions:
        for exc in (
                FlowRuleException.objects
                .filter(
                    participation=participation,
                    active=True,
                    kind=kind,
                    flow_id=flow_id)
                # rules created first will get inserted first, and show up last
                .order_by("creation_time")):

            if exc.expiration is not None and now_datetime > exc.expiration:
                continue

            from relate.utils import dict_to_struct
            rules.insert(0, dict_to_struct(exc.rule))

    return rules


def get_session_start_rule(course, participation, role, flow_id, flow_desc,
        now_datetime, remote_address=None, for_rollover=False):
    """Return a :class:`FlowSessionStartRule` if a new session is
    permitted or *None* if no new session is allowed.
    """

    from relate.utils import dict_to_struct
    rules = get_flow_rules(flow_desc, flow_rule_kind.start,
            participation, flow_id, now_datetime,
            default_rules_desc=[
                dict_to_struct(dict(
                    may_start_new_session=True,
                    may_list_existing_sessions=False))])

    for rule in rules:
        if not _eval_generic_conditions(rule, course, role, now_datetime):
            continue

        if not for_rollover and hasattr(rule, "if_in_facility"):
            if not is_address_in_facility(remote_address, rule.if_in_facility):
                continue

        if not for_rollover and hasattr(rule, "if_has_in_progress_session"):
            session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    flow_id=flow_id,
                    in_progress=True).count()

            if bool(session_count) != rule.if_has_in_progress_session:
                continue

        if not for_rollover and hasattr(rule, "if_has_session_tagged"):
            tagged_session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    access_rules_tag=rule.if_has_session_tagged,
                    flow_id=flow_id).count()

            if not tagged_session_count:
                continue

        if not for_rollover and hasattr(rule, "if_has_fewer_sessions_than"):
            session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    flow_id=flow_id).count()

            if session_count >= rule.if_has_fewer_sessions_than:
                continue

        if not for_rollover and hasattr(rule, "if_has_fewer_tagged_sessions_than"):
            tagged_session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    access_rules_tag__isnull=False,
                    flow_id=flow_id).count()

            if tagged_session_count >= rule.if_has_fewer_tagged_sessions_than:
                continue

        return FlowSessionStartRule(
                tag_session=getattr(rule, "tag_session", None),
                may_start_new_session=getattr(
                    rule, "may_start_new_session", True),
                may_list_existing_sessions=getattr(
                    rule, "may_list_existing_sessions", True),
                )

    return FlowSessionStartRule(
            may_list_existing_sessions=False,
            may_start_new_session=False)


def get_session_access_rule(session, role, flow_desc, now_datetime,
        remote_address=None):
    """Return a :class:`ExistingFlowSessionRule`` to describe
    how a flow may be accessed.
    """

    from relate.utils import dict_to_struct
    rules = get_flow_rules(flow_desc, flow_rule_kind.access,
            session.participation, session.flow_id, now_datetime,
            default_rules_desc=[
                dict_to_struct(dict(
                    permissions=[flow_permission.view],
                    ))])

    for rule in rules:
        if not _eval_generic_conditions(rule, session.course, role, now_datetime):
            continue

        if hasattr(rule, "if_in_facility"):
            if not is_address_in_facility(remote_address, rule.if_in_facility):
                continue

        if hasattr(rule, "if_has_tag"):
            if session.access_rules_tag != rule.if_has_tag:
                continue

        if hasattr(rule, "if_in_progress"):
            if session.in_progress != rule.if_in_progress:
                continue

        if hasattr(rule, "if_expiration_mode"):
            if session.expiration_mode != rule.if_expiration_mode:
                continue

        if hasattr(rule, "if_session_duration_shorter_than_minutes"):
            duration_min = (now_datetime - session.start_time).total_seconds() / 60

            if session.participation is not None:
                duration_min /= float(session.participation.time_factor)

            if duration_min > rule.if_session_duration_shorter_than_minutes:
                continue

        if hasattr(rule, "if_in_facility"):
            if not is_address_in_facility(remote_address, rule.if_in_facility):
                continue

        permissions = set(rule.permissions)

        # {{{ deal with deprecated permissions

        if "modify" in permissions:
            permissions.remove("modify")
            permissions.update([
                flow_permission.submit_answer,
                flow_permission.end_session,
                ])

        if "see_answer" in permissions:
            permissions.remove("see_answer")
            permissions.add(flow_permission.see_answer_after_submission)

        # }}}

        # Remove 'modify' permission from not-in-progress sessions
        if not session.in_progress:
            for perm in [
                    flow_permission.submit_answer,
                    flow_permission.end_session,
                    ]:
                if perm in permissions:
                    permissions.remove(perm)

        return FlowSessionAccessRule(
                permissions=frozenset(permissions),
                message=getattr(rule, "message", None)
                )

    return FlowSessionAccessRule(permissions=frozenset())


def get_session_grading_rule(session, role, flow_desc, now_datetime):
    from relate.utils import dict_to_struct
    rules = get_flow_rules(flow_desc, flow_rule_kind.grading,
            session.participation, session.flow_id, now_datetime,
            default_rules_desc=[
                dict_to_struct(dict(
                    grade_identifier=None,
                    ))])

    for rule in rules:
        if hasattr(rule, "if_has_role"):
            if role not in rule.if_has_role:
                continue

        if hasattr(rule, "if_has_tag"):
            if session.access_rules_tag != rule.if_has_tag:
                continue

        if hasattr(rule, "if_completed_before"):
            ds = parse_date_spec(session.course, rule.if_completed_before)
            if session.in_progress and now_datetime > ds:
                continue
            if not session.in_progress and session.completion_time > ds:
                continue

        due = parse_date_spec(session.course, getattr(rule, "due", None))
        if due is not None:
            assert due.tzinfo is not None

        return FlowSessionGradingRule(
                grade_identifier=getattr(rule, "grade_identifier", None),
                grade_aggregation_strategy=getattr(
                    rule, "grade_aggregation_strategy", None),
                due=due,
                description=getattr(rule, "description", None),
                credit_percent=getattr(rule, "credit_percent", 100))

    raise RuntimeError(_("grading rule determination was unable to find "
            "a grading rule"))

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

        self.course_commit_sha = get_course_commit_sha(
                self.course, self.participation)

        self.repo = get_course_repo(self.course)
        self.course_desc = get_course_desc(self.repo, self.course,
                self.course_commit_sha)

    @property
    def remote_address(self):
        import ipaddress
        try:
            return ipaddress.ip_address(self.request.META['REMOTE_ADDR'])
        except:
            return None


class FlowContext(object):
    def __init__(self, repo, course, flow_id,
            participation=None, flow_session=None):
        """*participation* and *flow_session* are not stored and only used
        to figure out versioning of the flow content.
        """

        self.repo = repo
        self.course = course
        self.flow_id = flow_id

        from django.core.exceptions import ObjectDoesNotExist

        self.course_commit_sha = get_course_commit_sha(
                self.course, participation)

        try:
            self.flow_desc = get_flow_desc(self.repo, self.course,
                    flow_id, self.course_commit_sha)
        except ObjectDoesNotExist:
            raise http.Http404()


class PageOrdinalOutOfRange(http.Http404):
    pass


class FlowPageContext(FlowContext):
    """This object acts as a container for all the information that a flow page
    may need to render itself or respond to a POST.

    Note that this is different from :class:`course.page.PageContext`,
    which is used for in the page API.
    """

    def __init__(self, repo, course, flow_id, ordinal,
             participation, flow_session):
        FlowContext.__init__(self, repo, course, flow_id,
                participation, flow_session=flow_session)

        from course.content import adjust_flow_session_page_data
        adjust_flow_session_page_data(repo, flow_session,
                course.identifier, self.flow_desc)

        if ordinal >= flow_session.page_count:
            raise PageOrdinalOutOfRange()

        from course.models import FlowPageData
        page_data = self.page_data = get_object_or_404(
                FlowPageData, flow_session=flow_session, ordinal=ordinal)

        from course.content import get_flow_page_desc
        try:
            self.page_desc = get_flow_page_desc(
                    flow_session, self.flow_desc, page_data.group_id,
                    page_data.page_id)
        except ObjectDoesNotExist:
            self.page_desc = None
            self.page = None
            self.page_context = None
        else:
            self.page = instantiate_flow_page_with_ctx(self, page_data)

            from course.page import PageContext
            self.page_context = PageContext(
                    course=self.course, repo=self.repo,
                    commit_sha=self.course_commit_sha,
                    flow_session=flow_session)

        self._prev_answer_visit = False

    @property
    def prev_answer_visit(self):
        if self._prev_answer_visit is False:
            from course.flow import get_prev_answer_visit
            self._prev_answer_visit = get_prev_answer_visit(self.page_data)

        return self._prev_answer_visit

    @property
    def ordinal(self):
        return self.page_data.ordinal


def instantiate_flow_page_with_ctx(fctx, page_data):
    from course.content import get_flow_page_desc
    page_desc = get_flow_page_desc(
            fctx.flow_id, fctx.flow_desc,
            page_data.group_id, page_data.page_id)

    from course.content import instantiate_flow_page
    return instantiate_flow_page(
            "course '%s', flow '%s', page '%s/%s'"
            % (fctx.course.identifier, fctx.flow_id,
                page_data.group_id, page_data.page_id),
            fctx.repo, page_desc, fctx.course_commit_sha)

# }}}


def course_view(f):
    def wrapper(request, course_identifier, *args, **kwargs):
        pctx = CoursePageContext(request, course_identifier)
        return f(pctx, *args, **kwargs)

    from functools import update_wrapper
    update_wrapper(wrapper, f)

    return wrapper


def render_course_page(pctx, template_name, args,
        allow_instant_flow_requests=True):
    args = args.copy()

    from course.views import get_now_or_fake_time
    now_datetime = get_now_or_fake_time(pctx.request)

    if allow_instant_flow_requests:
        instant_flow_requests = list((InstantFlowRequest.objects
                .filter(
                    course=pctx.course,
                    start_time__lte=now_datetime,
                    end_time__gte=now_datetime,
                    cancelled=False)
                .order_by("start_time")))
    else:
        instant_flow_requests = []

    args.update({
        "course": pctx.course,
        "course_desc": pctx.course_desc,
        "participation": pctx.participation,
        "role": pctx.role,
        "participation_role": participation_role,
        "num_instant_flow_requests": len(instant_flow_requests),
        "instant_flow_requests":
        [(i+1, r) for i, r in enumerate(instant_flow_requests)],
        })

    return render(pctx.request, template_name, args)


# {{{ page cache

class PageInstanceCache(object):
    """Caches instances of :class:`course.page.Page`."""

    def __init__(self, repo, course, flow_id):
        self.repo = repo
        self.course = course
        self.flow_id = flow_id
        self.flow_desc_cache = {}
        self.page_cache = {}

    def get_flow_desc_from_cache(self, commit_sha):
        try:
            return self.flow_desc_cache[commit_sha]
        except KeyError:
            flow_desc = get_flow_desc(self.repo, self.course,
                    self.flow_id, commit_sha)
            self.flow_desc_cache[commit_sha] = flow_desc
            return flow_desc

    def get_page(self, group_id, page_id, commit_sha):
        key = (group_id, page_id, commit_sha)
        try:
            return self.page_cache[key]
        except KeyError:

            from course.content import get_flow_page_desc, instantiate_flow_page
            page_desc = get_flow_page_desc(
                    self.flow_id,
                    self.get_flow_desc_from_cache(commit_sha),
                    group_id, page_id)

            page = instantiate_flow_page(
                    location="flow '%s', group, '%s', page '%s'"
                    % (self.flow_id, group_id, page_id),
                    repo=self.repo, page_desc=page_desc,
                    commit_sha=commit_sha)

            self.page_cache[key] = page
            return page

# }}}


# {{{ codemirror config

def get_codemirror_widget(language_mode, interaction_mode,
        config=None, addon_css=(), addon_js=(), dependencies=(),
        read_only=False):
    theme = "default"
    if read_only:
        theme += " relate-readonly"

    from codemirror import CodeMirrorTextarea, CodeMirrorJavascript

    from django.core.urlresolvers import reverse
    help_text = (_("Press F9 to toggle full-screen mode. ")
            + _("Set editor mode in <a href='%s'>user profile</a>.")
            % reverse("relate-user_profile"))

    actual_addon_css = (
        "dialog/dialog",
        "display/fullscreen",
        ) + addon_css
    actual_addon_js = (
        "search/searchcursor",
        "dialog/dialog",
        "search/search",
        "comment/comment",
        "edit/matchbrackets",
        "display/fullscreen",
        "selection/active-line",
        "edit/trailingspace",
        ) + addon_js

    if language_mode == "python":
        indent_unit = 4
    else:
        indent_unit = 2

    actual_config = {
            "fixedGutter": True,
            #"autofocus": True,
            "matchBrackets": True,
            "styleActiveLine": True,
            "showTrailingSpace": True,
            "indentUnit": indent_unit,
            "readOnly": read_only,
            "extraKeys": CodeMirrorJavascript("""
                {
                  "Ctrl-/": "toggleComment",
                  "Tab": function(cm)
                  {
                    var spaces = \
                        Array(cm.getOption("indentUnit") + 1).join(" ");
                    cm.replaceSelection(spaces);
                  },
                  "F9": function(cm) {
                      cm.setOption("fullScreen",
                        !cm.getOption("fullScreen"));
                  }
                }
            """)
            }

    if interaction_mode == "vim":
        actual_config["vimMode"] = True
        actual_addon_js += ('../keymap/vim',)
    elif interaction_mode == "emacs":
        actual_config["keyMap"] = "emacs"
        actual_addon_js += ('../keymap/emacs',)
    elif interaction_mode == "sublime":
        actual_config["keyMap"] = "sublime"
        actual_addon_js += ('../keymap/sublime',)
    # every other interaction mode goes to default

    if config is not None:
        actual_config.update(config)

    return CodeMirrorTextarea(
                    mode=language_mode,
                    dependencies=dependencies,
                    theme=theme,
                    addon_css=actual_addon_css,
                    addon_js=actual_addon_js,
                    config=actual_config), help_text

# }}}


# {{{ facility checking

def is_address_in_facility(remote_address, facility_id):
    if remote_address is None:
        return False

    from django.conf import settings
    ip_ranges = settings.RELATE_FACILITIES.get(facility_id, {}).get("ip_ranges", [])

    import ipaddress
    for ir in ip_ranges:
        if remote_address in ipaddress.ip_network(ir):
            return True

    return False

# }}}

# vim: foldmethod=marker
