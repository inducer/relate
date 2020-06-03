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

from typing import cast, Text

import datetime  # noqa
import markdown
from traitlets.config import Config

from django.shortcuts import (  # noqa
        render, get_object_or_404)
from django import http
from django.core.exceptions import ObjectDoesNotExist
from django.utils import translation
from django.utils.translation import (
        ugettext as _, pgettext_lazy)
from django.utils.decorators import ContextDecorator

from relate.utils import string_concat
from course.content import (
    get_course_repo, get_flow_desc,
    parse_date_spec, get_course_commit_sha,
    CourseCommitSHADoesNotExist)
from course.constants import (
        flow_permission, flow_rule_kind)
from course.content import (  # noqa
        FlowDesc,
        FlowPageDesc,
        FlowSessionAccessRuleDesc
        )
from course.page.base import (  # noqa
        PageBase,
        PageContext,
        )

# {{{ mypy

if False:
    from typing import (  # noqa
        Tuple, List, Iterable, Any, Optional, Union, Dict, FrozenSet, Text,
        Callable)
    from relate.utils import Repo_ish  # noqa
    from course.models import (  # noqa
            Course,
            Participation,
            ExamTicket,
            FlowSession,
            FlowPageData,
            )
    from course.content import Repo_ish  # noqa
    from codemirror import CodeMirrorTextarea  # noqa


# }}}

import re
CODE_CELL_DIV_ATTRS_RE = re.compile('(<div class="[^>]*code_cell[^>"]*")(>)')


def getattr_with_fallback(aggregates, attr_name, default=None):
    # type: (Iterable[Any], Text, Any) -> Any
    for agg in aggregates:
        result = getattr(agg, attr_name, None)
        if result is not None:
            return result

    return default


# {{{ flow permissions

class FlowSessionRuleBase(object):
    pass


class FlowSessionStartRule(FlowSessionRuleBase):
    def __init__(
            self,
            tag_session=None,  # type: Optional[Text]
            may_start_new_session=None,  # type: Optional[bool]
            may_list_existing_sessions=None,  # type: Optional[bool]
            default_expiration_mode=None,  # type: Optional[Text]
            ):
        # type: (...) -> None
        self.tag_session = tag_session
        self.may_start_new_session = may_start_new_session
        self.may_list_existing_sessions = may_list_existing_sessions
        self.default_expiration_mode = default_expiration_mode


class FlowSessionAccessRule(FlowSessionRuleBase):
    def __init__(
            self,
            permissions,  # type: FrozenSet[Text]
            message=None,  # type: Optional[Text]
            ):
        # type: (...) -> None
        self.permissions = permissions
        self.message = message

    def human_readable_permissions(self):
        from course.models import FLOW_PERMISSION_CHOICES
        permission_dict = dict(FLOW_PERMISSION_CHOICES)
        return [permission_dict[p] for p in self.permissions]


class FlowSessionGradingRule(FlowSessionRuleBase):
    def __init__(
            self,
            grade_identifier,  # type: Optional[Text]
            grade_aggregation_strategy,  # type: Text
            due,  # type: Optional[datetime.datetime]
            generates_grade,  # type: bool
            description=None,  # type: Optional[Text]
            credit_percent=None,  # type: Optional[float]
            use_last_activity_as_completion_time=None,  # type: Optional[bool]
            max_points=None,  # type: Optional[float]
            max_points_enforced_cap=None,  # type: Optional[float]
            bonus_points=None,  # type: Optional[float]
            ):
        # type: (...) -> None

        self.grade_identifier = grade_identifier
        self.grade_aggregation_strategy = grade_aggregation_strategy
        self.due = due
        self.generates_grade = generates_grade
        self.description = description
        self.credit_percent = credit_percent
        self.use_last_activity_as_completion_time = \
                use_last_activity_as_completion_time
        self.max_points = max_points
        self.max_points_enforced_cap = max_points_enforced_cap
        self.bonus_points = bonus_points


def _eval_generic_conditions(
        rule,  # type: Any
        course,  # type: Course
        participation,  # type: Optional[Participation]
        now_datetime,  # type: datetime.datetime
        flow_id,  # type: Text
        login_exam_ticket,  # type: Optional[ExamTicket]
        ):
    # type: (...) -> bool

    if hasattr(rule, "if_before"):
        ds = parse_date_spec(course, rule.if_before)
        if not (now_datetime <= ds):
            return False

    if hasattr(rule, "if_after"):
        ds = parse_date_spec(course, rule.if_after)
        if not (now_datetime >= ds):
            return False

    if hasattr(rule, "if_has_role"):
        from course.enrollment import get_participation_role_identifiers
        roles = get_participation_role_identifiers(course, participation)
        if all(role not in rule.if_has_role for role in roles):
            return False

    if (hasattr(rule, "if_signed_in_with_matching_exam_ticket")
            and rule.if_signed_in_with_matching_exam_ticket):
        if login_exam_ticket is None:
            return False
        if login_exam_ticket.exam.flow_id != flow_id:
            return False

    return True


def _eval_generic_session_conditions(
        rule,  # type: Any
        session,  # type: FlowSession
        now_datetime,  # type: datetime.datetime
        ):
    # type: (...) -> bool

    if hasattr(rule, "if_has_tag"):
        if session.access_rules_tag != rule.if_has_tag:
            return False

    if hasattr(rule, "if_started_before"):
        ds = parse_date_spec(session.course, rule.if_started_before)
        if not session.start_time < ds:
            return False

    return True


def _eval_participation_tags_conditions(
        rule,  # type: Any
        participation,  # type: Optional[Participation]
        ):
    # type: (...) -> bool

    participation_tags_any_set = (
        set(getattr(rule, "if_has_participation_tags_any", [])))
    participation_tags_all_set = (
        set(getattr(rule, "if_has_participation_tags_all", [])))

    if participation_tags_any_set or participation_tags_all_set:
        if not participation:
            # Return False for anonymous users if only
            # if_has_participation_tags_any or if_has_participation_tags_all
            # is not empty.
            return False
        ptag_set = set(participation.tags.all().values_list("name", flat=True))
        if not ptag_set:
            return False
        if (
                participation_tags_any_set
                and not participation_tags_any_set & ptag_set):
            return False
        if (
                participation_tags_all_set
                and not participation_tags_all_set <= ptag_set):
            return False

    return True


def get_flow_rules(
        flow_desc,  # type: FlowDesc
        kind,  # type: Text
        participation,  # type: Optional[Participation]
        flow_id,  # type: Text
        now_datetime,  # type: datetime.datetime
        consider_exceptions=True,  # type: bool
        default_rules_desc=[]  # type: List[Any]
        ):
    # type: (...) -> List[Any]

    if (not hasattr(flow_desc, "rules")
            or not hasattr(flow_desc.rules, kind)):
        rules = default_rules_desc[:]
    else:
        rules = getattr(flow_desc.rules, kind)[:]

    from course.models import FlowRuleException
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


def get_session_start_rule(
        course,  # type: Course
        participation,  # type: Optional[Participation]
        flow_id,  # type: Text
        flow_desc,  # type: FlowDesc
        now_datetime,  # type: datetime.datetime
        facilities=None,  # type: Optional[FrozenSet[Text]]
        for_rollover=False,  # type: bool
        login_exam_ticket=None,  # type: Optional[ExamTicket]
        ):
    # type: (...) -> FlowSessionStartRule

    """Return a :class:`FlowSessionStartRule` if a new session is
    permitted or *None* if no new session is allowed.
    """

    if facilities is None:
        facilities = frozenset()

    from relate.utils import dict_to_struct
    rules = get_flow_rules(flow_desc, flow_rule_kind.start,
            participation, flow_id, now_datetime,
            default_rules_desc=[
                dict_to_struct(dict(
                    may_start_new_session=True,
                    may_list_existing_sessions=False))])

    from course.models import FlowSession  # noqa
    for rule in rules:
        if not _eval_generic_conditions(rule, course, participation,
                now_datetime, flow_id=flow_id,
                login_exam_ticket=login_exam_ticket):
            continue

        if not _eval_participation_tags_conditions(rule, participation):
            continue

        if not for_rollover and hasattr(rule, "if_in_facility"):
            if rule.if_in_facility not in facilities:
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
                default_expiration_mode=getattr(
                    rule, "default_expiration_mode", None),
                )

    return FlowSessionStartRule(
            may_list_existing_sessions=False,
            may_start_new_session=False)


def get_session_access_rule(
        session,  # type: FlowSession
        flow_desc,  # type: FlowDesc
        now_datetime,  # type: datetime.datetime
        facilities=None,  # type: Optional[FrozenSet[Text]]
        login_exam_ticket=None,  # type: Optional[ExamTicket]
        ):
    # type: (...) -> FlowSessionAccessRule
    """Return a :class:`ExistingFlowSessionRule`` to describe
    how a flow may be accessed.
    """

    if facilities is None:
        facilities = frozenset()

    from relate.utils import dict_to_struct
    rules = get_flow_rules(flow_desc, flow_rule_kind.access,
            session.participation, session.flow_id, now_datetime,
            default_rules_desc=[
                dict_to_struct(dict(
                    permissions=[flow_permission.view],
                    ))])  # type: List[FlowSessionAccessRuleDesc]

    for rule in rules:
        if not _eval_generic_conditions(
                rule, session.course, session.participation,
                now_datetime, flow_id=session.flow_id,
                login_exam_ticket=login_exam_ticket):
            continue

        if not _eval_participation_tags_conditions(rule, session.participation):
            continue

        if not _eval_generic_session_conditions(rule, session, now_datetime):
            continue

        if hasattr(rule, "if_in_facility"):
            if rule.if_in_facility not in facilities:
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


def get_session_grading_rule(
        session,  # type: FlowSession
        flow_desc,  # type: FlowDesc
        now_datetime  # type: datetime.datetime
        ):
    # type: (...) -> FlowSessionGradingRule

    flow_desc_rules = getattr(flow_desc, "rules", None)

    from relate.utils import dict_to_struct
    rules = get_flow_rules(flow_desc, flow_rule_kind.grading,
            session.participation, session.flow_id, now_datetime,
            default_rules_desc=[
                dict_to_struct(dict(
                    generates_grade=False,
                    ))])

    from course.enrollment import get_participation_role_identifiers
    roles = get_participation_role_identifiers(session.course, session.participation)

    for rule in rules:
        if hasattr(rule, "if_has_role"):
            if all(role not in rule.if_has_role for role in roles):
                continue

        if not _eval_generic_session_conditions(rule, session, now_datetime):
            continue

        if not _eval_participation_tags_conditions(rule, session.participation):
            continue

        if hasattr(rule, "if_completed_before"):
            ds = parse_date_spec(session.course, rule.if_completed_before)

            use_last_activity_as_completion_time = False
            if hasattr(rule, "use_last_activity_as_completion_time"):
                use_last_activity_as_completion_time = \
                        rule.use_last_activity_as_completion_time

            if use_last_activity_as_completion_time:
                last_activity = session.last_activity()
                if last_activity is not None:
                    completion_time = last_activity
                else:
                    completion_time = now_datetime
            else:
                if session.in_progress:
                    completion_time = now_datetime
                else:
                    completion_time = session.completion_time

            if completion_time > ds:
                continue

        due = parse_date_spec(session.course, getattr(rule, "due", None))
        if due is not None:
            assert due.tzinfo is not None

        generates_grade = getattr(rule, "generates_grade", True)

        grade_identifier = None
        grade_aggregation_strategy = None
        if flow_desc_rules is not None:
            grade_identifier = flow_desc_rules.grade_identifier
            grade_aggregation_strategy = getattr(
                    flow_desc_rules, "grade_aggregation_strategy", None)

        bonus_points = getattr_with_fallback((rule, flow_desc), "bonus_points", 0)
        max_points = getattr_with_fallback((rule, flow_desc), "max_points", None)
        max_points_enforced_cap = getattr_with_fallback(
                (rule, flow_desc), "max_points_enforced_cap", None)

        grade_aggregation_strategy = cast(Text, grade_aggregation_strategy)

        return FlowSessionGradingRule(
                grade_identifier=grade_identifier,
                grade_aggregation_strategy=grade_aggregation_strategy,
                due=due,
                generates_grade=generates_grade,
                description=getattr(rule, "description", None),
                credit_percent=getattr(rule, "credit_percent", 100),
                use_last_activity_as_completion_time=getattr(
                    rule, "use_last_activity_as_completion_time", False),

                bonus_points=bonus_points,
                max_points=max_points,
                max_points_enforced_cap=max_points_enforced_cap,
                )

    raise RuntimeError(_("grading rule determination was unable to find "
            "a grading rule"))

# }}}


# {{{ contexts

class AnyArgumentType:  # noqa
    pass


ANY_ARGUMENT = AnyArgumentType()


class CoursePageContext(object):
    def __init__(self, request, course_identifier):
        # type: (http.HttpRequest, Text) -> None

        self.request = request
        self.course_identifier = course_identifier
        self._permissions_cache = None  # type: Optional[FrozenSet[Tuple[Text, Optional[Text]]]]  # noqa
        self._role_identifiers_cache = None  # type: Optional[List[Text]]
        self.old_language = None

        # using this to prevent nested using as context manager
        self._is_in_context_manager = False

        from course.models import Course  # noqa
        self.course = get_object_or_404(Course, identifier=course_identifier)

        from course.enrollment import get_participation_for_request
        self.participation = get_participation_for_request(
                request, self.course)

        from course.views import check_course_state
        check_course_state(self.course, self.participation)

        self.repo = get_course_repo(self.course)

        try:
            sha = get_course_commit_sha(
                self.course, self.participation,
                repo=self.repo,
                raise_on_nonexistent_preview_commit=True)
        except CourseCommitSHADoesNotExist as e:
            from django.contrib import messages
            messages.add_message(request, messages.ERROR, str(e))

            sha = self.course.active_git_commit_sha.encode()

        self.course_commit_sha = sha

    def role_identifiers(self):
        # type: () -> List[Text]
        if self._role_identifiers_cache is not None:
            return self._role_identifiers_cache

        from course.enrollment import get_participation_role_identifiers
        self._role_identifiers_cache = get_participation_role_identifiers(
                self.course, self.participation)
        return self._role_identifiers_cache

    def permissions(self):
        # type: () -> FrozenSet[Tuple[Text, Optional[Text]]]
        if self.participation is None:
            if self._permissions_cache is not None:
                return self._permissions_cache

            from course.enrollment import get_participation_permissions
            perm = get_participation_permissions(self.course, self.participation)

            self._permissions_cache = perm

            return perm
        else:
            return self.participation.permissions()

    def has_permission(self, perm, argument=None):
        # type: (Text, Union[Text, AnyArgumentType, None]) -> bool
        if argument is ANY_ARGUMENT:
            return any(perm == p
                    for p, arg in self.permissions())
        else:
            return (perm, argument) in self.permissions()

    def _set_course_lang(self, action):
        # type: (Text) -> None
        if self.course.force_lang and self.course.force_lang.strip():
            if action == "activate":
                self.old_language = translation.get_language()
                translation.activate(self.course.force_lang)
            else:
                if self.old_language is None:
                    # This should be a rare case, but get_language() can be None.
                    # See django.utils.translation.override.__exit__()
                    translation.deactivate_all()
                else:
                    translation.activate(self.old_language)

    def __enter__(self):
        if self._is_in_context_manager:
            raise RuntimeError(
                "Nested use of 'course_view' as context manager "
                "is not allowed.")
        self._is_in_context_manager = True
        self._set_course_lang(action="activate")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._is_in_context_manager = False
        self._set_course_lang(action="deactivate")
        self.repo.close()


class FlowContext(object):
    def __init__(self, repo, course, flow_id, participation=None):
        # type: (Repo_ish, Course, Text, Optional[Participation]) -> None

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

    def __init__(
            self,
            repo,  # type: Repo_ish
            course,  # type: Course
            flow_id,  # type: Text
            page_ordinal,  # type: int
            participation,  # type: Optional[Participation]
            flow_session,  # type: FlowSession
            request=None,  # type: Optional[http.HttpRequest]
            ):
        # type: (...) -> None
        super(FlowPageContext, self).__init__(repo, course, flow_id, participation)

        if page_ordinal >= flow_session.page_count:
            raise PageOrdinalOutOfRange()

        from course.models import FlowPageData  # noqa
        page_data = self.page_data = get_object_or_404(
                FlowPageData, flow_session=flow_session, page_ordinal=page_ordinal)

        from course.content import get_flow_page_desc
        try:
            self.page_desc = get_flow_page_desc(
                    flow_session.flow_id, self.flow_desc, page_data.group_id,
                    page_data.page_id)  # type: Optional[FlowPageDesc]
        except ObjectDoesNotExist:
            self.page_desc = None
            self.page = None  # type: Optional[PageBase]
            self.page_context = None  # type: Optional[PageContext]
        else:
            self.page = instantiate_flow_page_with_ctx(self, page_data)

            page_uri = None
            if request is not None:
                from django.urls import reverse
                page_uri = request.build_absolute_uri(
                    reverse(
                        "relate-view_flow_page",
                        args=(course.identifier, flow_session.id, page_ordinal)))

            self.page_context = PageContext(
                    course=self.course, repo=self.repo,
                    commit_sha=self.course_commit_sha,
                    flow_session=flow_session,
                    page_uri=page_uri)

        self._prev_answer_visit = False

    @property
    def prev_answer_visit(self):
        if self._prev_answer_visit is False:
            from course.flow import get_prev_answer_visit
            self._prev_answer_visit = get_prev_answer_visit(self.page_data)

        return self._prev_answer_visit

    @property
    def page_ordinal(self):
        return self.page_data.page_ordinal


def instantiate_flow_page_with_ctx(fctx, page_data):
    # type: (FlowContext, FlowPageData) -> PageBase

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


# {{{ utilties for course-based views
def course_view(f):
    def wrapper(request, course_identifier, *args, **kwargs):
        with CoursePageContext(request, course_identifier) as pctx:
            response = f(pctx, *args, **kwargs)
            pctx.repo.close()
            return response

    from functools import update_wrapper
    update_wrapper(wrapper, f)

    return wrapper


class ParticipationPermissionWrapper(object):
    def __init__(self, pctx):
        # type: (CoursePageContext) -> None
        self.pctx = pctx

    def __getitem__(self, perm):
        # type: (Text) -> bool

        from course.constants import participation_permission
        try:
            getattr(participation_permission, perm)
        except AttributeError:
            raise ValueError("permission name '%s' not valid" % perm)

        return self.pctx.has_permission(perm, ANY_ARGUMENT)

    def __iter__(self):
        raise TypeError("ParticipationPermissionWrapper is not iterable.")


def render_course_page(pctx, template_name, args,
        allow_instant_flow_requests=True):
    # type: (CoursePageContext, Text, Dict[Text, Any], bool) -> http.HttpResponse

    args = args.copy()

    from course.views import get_now_or_fake_time
    now_datetime = get_now_or_fake_time(pctx.request)

    if allow_instant_flow_requests:
        from course.models import InstantFlowRequest
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
        "pperm": ParticipationPermissionWrapper(pctx),
        "participation": pctx.participation,
        "num_instant_flow_requests": len(instant_flow_requests),
        "instant_flow_requests":
        [(i+1, r) for i, r in enumerate(instant_flow_requests)],
        })

    return render(pctx.request, template_name, args)

# }}}


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

def get_codemirror_widget(
        language_mode,  # type: Text
        interaction_mode,  # type: Text
        config=None,  # type: Optional[Dict]
        addon_css=(),  # type: Tuple
        addon_js=(),  # type: Tuple
        dependencies=(),  # type: Tuple
        read_only=False,  # type: bool
        autofocus=False,  # type: bool
        ):
    # type: (...) ->  Tuple[CodeMirrorTextarea,Text]

    from codemirror import CodeMirrorTextarea, CodeMirrorJavascript  # noqa

    theme = "default"
    if read_only:
        theme += " relate-readonly"

    from django.urls import reverse
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
                    // from https://github.com/codemirror/CodeMirror/issues/988

                    if (cm.doc.somethingSelected()) {
                        return CodeMirror.Pass;
                    }
                    var spacesPerTab = cm.getOption("indentUnit");
                    var spacesToInsert = (
                        spacesPerTab
                        - (cm.doc.getCursor("start").ch % spacesPerTab));
                    var spaces = Array(spacesToInsert + 1).join(" ");
                    cm.replaceSelection(spaces, "end", "+input");
                  },
                  "Shift-Tab": "indentLess",
                  "F9": function(cm) {
                      cm.setOption("fullScreen",
                        !cm.getOption("fullScreen"));
                  }
                }
            """)
            }

    if autofocus:
        actual_config["autofocus"] = True

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


# {{{ facility processing

def get_facilities_config(request=None):
    # type: (Optional[http.HttpRequest]) -> Optional[Dict[Text, Dict[Text, Any]]]
    from django.conf import settings

    # This is called during offline validation, where Django isn't really set up.
    # The getattr makes this usable.
    facilities = getattr(settings, "RELATE_FACILITIES", None)
    if facilities is None:
        # Only happens during offline validation. Suppresses errors there.
        return None

    if callable(facilities):
        from course.views import get_now_or_fake_time
        now_datetime = get_now_or_fake_time(request)

        result = facilities(now_datetime)
        if not isinstance(result, dict):
            raise RuntimeError("RELATE_FACILITIES must return a dictionary")
        return result
    else:
        return facilities


class FacilityFindingMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        pretend_facilities = request.session.get("relate_pretend_facilities")

        if pretend_facilities is not None:
            facilities = pretend_facilities
        else:
            import ipaddress
            remote_address = ipaddress.ip_address(
                    str(request.META['REMOTE_ADDR']))

            facilities = set()

            for name, props in get_facilities_config(request).items():
                ip_ranges = props.get("ip_ranges", [])
                for ir in ip_ranges:
                    if remote_address in ipaddress.ip_network(str(ir)):
                        facilities.add(name)

        request.relate_facilities = frozenset(facilities)

        return self.get_response(request)

# }}}


def get_col_contents_or_empty(row, index):
    if index >= len(row):
        return ""
    else:
        return row[index]


def csv_data_importable(file_contents, column_idx_list, header_count):
    import csv
    spamreader = csv.reader(file_contents)
    n_header_row = 0
    try:
        row0 = spamreader.__next__()
    except Exception as e:
        err_msg = type(e).__name__
        err_str = str(e)
        if err_msg == "Error":
            err_msg = ""
        else:
            err_msg += ": "
        err_msg += err_str

        if "line contains NUL" in err_str:
            err_msg = err_msg.rstrip(".") + ". "

            # This message changed over time.
            # Make the message uniform to please the tests.
            err_msg = err_msg.replace("NULL byte", "NUL")

            err_msg += _("Are you sure the file is a CSV file other "
                         "than a Microsoft Excel file?")

        return False, (
            string_concat(
                pgettext_lazy("Starting of Error message", "Error"),
                ": %s" % err_msg))

    from itertools import chain

    for row in chain([row0], spamreader):
        n_header_row += 1
        if n_header_row <= header_count:
            continue
        try:
            for column_idx in column_idx_list:
                if column_idx is not None:
                    str(get_col_contents_or_empty(row, column_idx-1))
        except UnicodeDecodeError:
            return False, (
                    _("Error: Columns to be imported contain "
                        "non-ASCII characters. "
                        "Please save your CSV file as utf-8 encoded "
                        "and import again.")
            )
        except Exception as e:
            return False, (
                    string_concat(
                        pgettext_lazy("Starting of Error message",
                            "Error"),
                        ": %(err_type)s: %(err_str)s")
                    % {
                        "err_type": type(e).__name__,
                        "err_str": str(e)}
                    )

    return True, ""


def will_use_masked_profile_for_email(recipient_email):
    # type: (Union[None, Text, List[Text]]) -> bool
    if not recipient_email:
        return False
    if not isinstance(recipient_email, list):
        recipient_email = [recipient_email]
    from course.models import Participation  # noqa
    recepient_participations = (
        Participation.objects.filter(
            user__email__in=recipient_email
        ))
    from course.constants import participation_permission as pperm
    for part in recepient_participations:
        if part.has_permission(pperm.view_participant_masked_profile):
            return True
    return False


def get_course_specific_language_choices():
    # type: () -> Tuple[Tuple[str, Any], ...]

    from django.conf import settings
    from collections import OrderedDict

    all_options = ((settings.LANGUAGE_CODE, None),) + tuple(settings.LANGUAGES)
    filtered_options_dict = OrderedDict(all_options)

    def get_default_option():
        # type: () -> Tuple[Text, Text]
        # For the default language used, if USE_I18N is True, display
        # "Disabled". Otherwise display its lang info.
        if not settings.USE_I18N:
            formatted_descr = (
                get_formatted_options(settings.LANGUAGE_CODE, None)[1])
        else:
            formatted_descr = _("disabled (i.e., displayed language is "
                                "determined by user's browser preference)")
        return "", string_concat("%s: " % _("Default"), formatted_descr)

    def get_formatted_options(lang_code, lang_descr):
        # type: (Text, Optional[Text]) -> Tuple[Text, Text]
        if lang_descr is None:
            lang_descr = OrderedDict(settings.LANGUAGES).get(lang_code)
            if lang_descr is None:
                try:
                    lang_info = translation.get_language_info(lang_code)
                    lang_descr = lang_info["name_translated"]
                except KeyError:
                    return (lang_code.strip(), lang_code)

        return (lang_code.strip(),
                string_concat(_(lang_descr), " (%s)" % lang_code))

    filtered_options = (
        [get_default_option()]
        + [get_formatted_options(k, v)
           for k, v in filtered_options_dict.items()])

    # filtered_options[1] is the option for settings.LANGUAGE_CODE
    # it's already displayed when settings.USE_I18N is False
    if not settings.USE_I18N:
        filtered_options.pop(1)

    return tuple(filtered_options)


class LanguageOverride(ContextDecorator):
    def __init__(self, course, deactivate=False):
        # type: (Course, bool) -> None
        self.course = course
        self.deactivate = deactivate

        if course.force_lang:
            self.language = course.force_lang
        else:
            from django.conf import settings
            self.language = settings.RELATE_ADMIN_EMAIL_LOCALE

    def __enter__(self):
        # type: () -> None
        self.old_language = translation.get_language()
        if self.language is not None:
            translation.activate(self.language)
        else:
            translation.deactivate_all()

    def __exit__(self, exc_type, exc_value, traceback):
        # type: (Any, Any, Any) -> None
        if self.old_language is None:
            translation.deactivate_all()
        elif self.deactivate:
            translation.deactivate()
        else:
            translation.activate(self.old_language)


class RelateJinjaMacroBase(object):
    def __init__(self, course, repo, commit_sha):
        # type: (Optional[Course], Repo_ish, bytes) -> None
        self.course = course
        self.repo = repo
        self.commit_sha = commit_sha

    @property
    def name(self):
        # The name of the method used in the template
        raise NotImplementedError()

    def __call__(self, *args, **kwargs):
        # type: (*Any, **Any) -> Text
        raise NotImplementedError()


# {{{ ipynb utilities

def get_default_ipynb_render_config():
    # type: () -> Config
    c = Config()
    c.ExecutePreprocessor.enabled = False
    c.CSSHTMLHeaderPreprocessor.enabled = False
    c.HighlightMagicsPreprocessor.enabled = False
    return c


def render_notebook_from_source(
        ipynb_source, indices=None,
        clear_output=False, clear_markdown=False, config=None,
        template_file=None, config_callback=None, **kwargs):
    # type: (Text, Optional[Any], Optional[bool], Optional[bool], Optional[Config], Optional[Text], Optional[Callable], **Any) -> Text  # noqa
    """
    Get HTML format of ipython notebook so as to be rendered in RELATE flow
    pages.
    :param ipynb_source: the :class:`text` read from a ipython notebook.
    :param indices: a :class:`list` instance, 0-based indices of notebook cells
    which are expected to be rendered.
    :param clear_output: a :class:`bool` instance, indicating whether existing
    execution output of code cells should be removed.
    :param clear_markdown: a :class:`bool` instance, indicating whether markdown
    cells will be ignored..
    :param config: a :class:`traitlets.config.loader.Config` instance.
    :param config_callback: a function which further handles `config` .
    :param template_file: :class:`text`, the name of the template file used. If not
    specified, built-in basic template will be used.
    :return: :class:`text`
    """
    import nbformat
    from nbformat.reader import parse_json
    nb_source_dict = parse_json(ipynb_source)

    if indices:
        nb_source_dict.update(
            {"cells": [nb_source_dict["cells"][idx] for idx in indices]})

    if clear_markdown:
        nb_source_dict.update(
            {"cells": [cell for cell in nb_source_dict["cells"]
                       if cell['cell_type'] != "markdown"]})

    nb_source_dict.update({"cells": nb_source_dict["cells"]})

    import json
    ipynb_source = json.dumps(nb_source_dict)
    notebook = nbformat.reads(ipynb_source, as_version=4)

    if not config:
        config = get_default_ipynb_render_config()

    # This is to prevent execution of arbitrary code from note book
    if clear_output:
        config.ClearOutputPreprocessor.enabled = True

    if config_callback:
        config = config_callback(config)

    template_file = template_file or "basic"

    from nbconvert import HTMLExporter
    html_exporter = HTMLExporter(
        config=config,
        template_file=template_file
    )

    (body, resources) = html_exporter.from_notebook_node(notebook)

    return "<div class='relate-notebook-container'>%s</div>" % body


class IpynbJinjaMacro(RelateJinjaMacroBase):
    name = "render_notebook_cells"

    def _render_notebook_cells(self, ipynb_path, indices=None, clear_output=False,
                 clear_markdown=False, **kwargs):
        # type: (Text, Optional[Any], Optional[bool], Optional[bool], **Any) -> Text
        from course.content import get_repo_blob_data_cached

        def config_callback(config):
            # Place the template in course template dir
            import os
            import course
            _template_path = os.path.join(
                os.path.dirname(course.__file__),
                "templates", "course", "jinja2")
            config.TemplateExporter.template_path.append(_template_path)
            return config

        try:
            ipynb_source = get_repo_blob_data_cached(self.repo, ipynb_path,
                                                     self.commit_sha).decode()

            return render_notebook_from_source(
                ipynb_source,
                indices=indices,
                clear_output=clear_output,
                clear_markdown=clear_markdown,
                config_callback=config_callback,
                template_file="nbconvert_template.tpl",
                **kwargs
            )
        except ObjectDoesNotExist:
            raise

    __call__ = _render_notebook_cells  # type: ignore


NBCONVERT_PRE_OPEN_RE = re.compile(r"<pre\s*>\s*<relate_ipynb\s*>")
NBCONVERT_PRE_CLOSE_RE = re.compile(r"</relate_ipynb\s*>\s*</pre\s*>")


class NBConvertHTMLPostprocessor(markdown.postprocessors.Postprocessor):
    def run(self, text):
        text = NBCONVERT_PRE_OPEN_RE.sub("", text)
        text = NBCONVERT_PRE_CLOSE_RE.sub("", text)
        return text


class NBConvertExtension(markdown.Extension):
    def extendMarkdown(self, md, md_globals):  # noqa
        md.postprocessors['relate_nbconvert'] = NBConvertHTMLPostprocessor(md)

# }}}


def get_custom_page_types_stop_support_deadline():
    # type: () -> Optional[datetime.datetime]
    from django.conf import settings
    custom_page_types_removed_deadline = getattr(
        settings, "RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE", None)

    force_deadline = datetime.datetime(2019, 1, 1, 0, 0, 0, 0)

    if (custom_page_types_removed_deadline is None
            or custom_page_types_removed_deadline > force_deadline):
        custom_page_types_removed_deadline = force_deadline

    from relate.utils import localize_datetime
    return localize_datetime(custom_page_types_removed_deadline)

# vim: foldmethod=marker
