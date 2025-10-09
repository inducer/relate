from __future__ import annotations


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

from contextlib import ContextDecorator
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    Concatenate,
    ParamSpec,
    TypeVar,
    cast,
)

from django import forms, http
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, render
from django.utils import translation
from django.utils.safestring import SafeString, mark_safe
from django.utils.translation import gettext as _, pgettext_lazy
from pytools import not_none
from typing_extensions import override

from course.constants import (
    FlowPermission,
    GradeAggregationStrategy,
    ParticipationPermission,
)
from course.content import (
    CourseCommitSHADoesNotExist,
    FlowDesc,
    FlowRule,
    FlowSessionAccessMode,
    FlowSessionAccessRuleDesc,
    FlowSessionGradingMode,
    FlowSessionGradingRuleDesc,
    FlowSessionStartMode,
    FlowSessionStartRuleDesc,
    get_course_commit_sha,
    get_course_repo,
    get_flow_desc,
    get_rule_ta,
)
from course.page.base import PageBase, PageContext
from course.validation import ValidationContext
from relate.utils import (
    RelateHttpRequest,
    remote_address_from_request,
    string_concat,
)


# {{{ mypy

if TYPE_CHECKING:
    import datetime
    from collections.abc import Callable, Collection, Hashable, Iterable, Sequence, Set
    from ipaddress import IPv4Address, IPv6Address

    from course.models import (
        Course,
        ExamTicket,
        FlowPageData,
        FlowPageVisit,
        FlowSession,
        Participation,
    )
    from course.repo import Repo_ish

# }}}

import re
from itertools import starmap


P = ParamSpec("P")


CODE_CELL_DIV_ATTRS_RE = re.compile(r'(<div class="[^>]*code_cell[^>"]*")(>)')


def getattr_with_fallback(
        aggregates: Iterable[Any], attr_name: str, default: Any = None) -> Any:
    for agg in aggregates:
        result = getattr(agg, attr_name, None)
        if result is not None:
            return result

    return default


# {{{ flow permissions

def _eval_generic_conditions(
        rule: FlowSessionStartRuleDesc
            | FlowSessionAccessRuleDesc,
        course: Course,
        participation: Participation | None,
        now_datetime: datetime.datetime,
        flow_id: str,
        login_exam_ticket: ExamTicket | None,
        *,
        remote_ip_address: IPv4Address | IPv6Address | None = None,
        ) -> bool:

    if rule.if_before:
        if not (now_datetime <= rule.if_before.eval(course)):
            return False

    if rule.if_after:
        if not (now_datetime >= rule.if_after.eval(course)):
            return False

    if rule.if_has_role:
        from course.enrollment import get_participation_role_identifiers
        roles = get_participation_role_identifiers(course, participation)
        if all(role not in rule.if_has_role for role in roles):
            return False

    if rule.if_signed_in_with_matching_exam_ticket:
        if login_exam_ticket is None:
            return False
        if login_exam_ticket.exam.flow_id != flow_id:
            return False
        if login_exam_ticket.participation != participation:
            return False

    if rule.if_has_prairietest_exam_access is not None:
        if remote_ip_address is None:
            return False
        if participation is None:
            return False

        from prairietest.utils import has_access_to_exam
        if not has_access_to_exam(
                    course,
                    participation.user.email,
                    (participation.user.institutional_id
                        if participation.user.institutional_id_verified else None),
                    rule.if_has_prairietest_exam_access,
                    now_datetime,
                    remote_ip_address,
                ):
            return False

    return True


def _eval_generic_session_conditions(
        rule: FlowSessionAccessRuleDesc | FlowSessionGradingRuleDesc,
        session: FlowSession,
        ) -> bool:

    if rule.if_has_tag:
        if session.access_rules_tag != rule.if_has_tag:
            return False

    if rule.if_started_before:
        if not session.start_time < rule.if_started_before.eval(session.course):
            return False

    return True


def _eval_participation_tags_conditions(
        rule: Any,
        participation: Participation | None,
        ) -> bool:

    participation_tags_any_set = (
        set(rule.if_has_participation_tags_any or []))
    participation_tags_all_set = (
        set(rule.if_has_participation_tags_all or []))

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


FlowRuleT = TypeVar("FlowRuleT", bound=FlowRule)


def get_flow_rules(
        flow_desc: FlowDesc,
        type: type[FlowRuleT],
        participation: Participation | None,
        flow_id: str,
        now_datetime: datetime.datetime,
        consider_exceptions: bool = True,
        ) -> list[FlowRuleT]:
    from course.content import (
        FlowSessionAccessRuleDesc,
        FlowSessionGradingRuleDesc,
        FlowSessionStartRuleDesc,
    )

    rules: list[FlowRuleT] = []
    if type is FlowSessionStartRuleDesc:
        rules = cast("list[FlowRuleT]", flow_desc.rules.start)
    elif type is FlowSessionAccessRuleDesc:
        rules = cast("list[FlowRuleT]", flow_desc.rules.access)
    elif type is FlowSessionGradingRuleDesc:
        rules = cast("list[FlowRuleT]", flow_desc.rules.grading)
    else:
        raise AssertionError()

    rules = rules.copy()

    from course.models import FlowRuleException
    if consider_exceptions and participation is not None:
        course = participation.course

        vctx = ValidationContext(
                repo=get_course_repo(course),
                commit_sha=course.active_git_commit_sha.encode(),
                course=course)

        for exc in (
                FlowRuleException.objects
                .filter(
                    participation=participation,
                    active=True,
                    kind=type.kind,
                    flow_id=flow_id)
                # rules created first will get inserted first, and show up last
                .order_by("creation_time")):

            if exc.expiration is not None and now_datetime > exc.expiration:
                continue

            rules.insert(0, get_rule_ta(type).validate_python(exc.rule, context=vctx))

    return rules


def get_session_start_mode(
        course: Course,
        participation: Participation | None,
        flow_id: str,
        flow_desc: FlowDesc,
        now_datetime: datetime.datetime,
        facilities: Collection[str] | None = None,
        for_rollover: bool = False,
        login_exam_ticket: ExamTicket | None = None,
        *,
        remote_ip_address: IPv4Address | IPv6Address | None = None,
        ) -> FlowSessionStartMode:

    if facilities is None:
        facilities = frozenset()

    rules = get_flow_rules(
            flow_desc, FlowSessionStartRuleDesc,
            participation, flow_id, now_datetime,
            )

    from course.models import FlowSession
    for rule in rules:
        if not _eval_generic_conditions(rule, course, participation,
                now_datetime, flow_id=flow_id,
                login_exam_ticket=login_exam_ticket,
                remote_ip_address=remote_ip_address):
            continue

        if not _eval_participation_tags_conditions(rule, participation):
            continue

        if not for_rollover and rule.if_in_facility is not None:
            if rule.if_in_facility not in facilities:
                continue

        if not for_rollover and rule.if_has_in_progress_session is not None:
            session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    flow_id=flow_id,
                    in_progress=True).count()

            if bool(session_count) != rule.if_has_in_progress_session:
                continue

        if not for_rollover and rule.if_has_session_tagged is not None:
            tagged_session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    access_rules_tag=rule.if_has_session_tagged,
                    flow_id=flow_id).count()

            if not tagged_session_count:
                continue

        if not for_rollover and rule.if_has_fewer_sessions_than is not None:
            session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    flow_id=flow_id).count()

            if session_count >= rule.if_has_fewer_sessions_than:
                continue

        if not for_rollover and rule.if_has_fewer_tagged_sessions_than is not None:
            tagged_session_count = FlowSession.objects.filter(
                    participation=participation,
                    course=course,
                    access_rules_tag__isnull=False,
                    flow_id=flow_id).count()

            if tagged_session_count >= rule.if_has_fewer_tagged_sessions_than:
                continue

        return FlowSessionStartMode(
                tag_session=rule.tag_session,
                may_start_new_session=rule.may_start_new_session,
                may_list_existing_sessions=rule.may_list_existing_sessions,
                default_expiration_mode=rule.default_expiration_mode,
                )

    return FlowSessionStartMode(
            may_list_existing_sessions=False,
            may_start_new_session=False)


def get_session_access_mode(
        session: FlowSession,
        flow_desc: FlowDesc,
        now_datetime: datetime.datetime,
        facilities: Collection[str] | None = None,
        login_exam_ticket: ExamTicket | None = None,
        *,
        remote_ip_address: IPv4Address | IPv6Address | None = None,
        ) -> FlowSessionAccessMode:

    if facilities is None:
        facilities = frozenset()

    rules: list[FlowSessionAccessRuleDesc] = get_flow_rules(
            flow_desc, FlowSessionAccessRuleDesc,
            session.participation, session.flow_id, now_datetime)

    for rule in rules:
        if not _eval_generic_conditions(
                    rule, session.course, session.participation,
                    now_datetime, flow_id=session.flow_id,
                    login_exam_ticket=login_exam_ticket,
                    remote_ip_address=remote_ip_address,
                ):
            continue

        if not _eval_participation_tags_conditions(rule, session.participation):
            continue

        if not _eval_generic_session_conditions(rule, session):
            continue

        if rule.if_in_facility:
            if rule.if_in_facility not in facilities:
                continue

        if rule.if_in_progress:
            if session.in_progress != rule.if_in_progress:
                continue

        if rule.if_expiration_mode:
            if session.expiration_mode != rule.if_expiration_mode:
                continue

        if rule.if_session_duration_shorter_than_minutes is not None:
            duration_min = (now_datetime - session.start_time).total_seconds() / 60

            if session.participation is not None:
                duration_min /= float(session.participation.time_factor)

            if duration_min > rule.if_session_duration_shorter_than_minutes:
                continue

        permissions = set(rule.permissions)

        # Remove 'modify' permission from not-in-progress sessions
        if not session.in_progress:
            permissions.difference_update([
                    FlowPermission.submit_answer,
                    FlowPermission.end_session,
                    ])

        return FlowSessionAccessMode(
                permissions=frozenset(permissions),
                message=rule.message,
                )

    return FlowSessionAccessMode(permissions=frozenset())


@dataclass(frozen=True, kw_only=True)
class FlowSessionGradingModeWithFlowLevelInfo(FlowSessionGradingMode):
    grade_identifier: str | None = None
    grade_aggregation_strategy: GradeAggregationStrategy | None = None


def get_session_grading_mode(
        session: FlowSession,
        flow_desc: FlowDesc,
        now_datetime: datetime.datetime
        ) -> FlowSessionGradingModeWithFlowLevelInfo:

    rules: list[FlowSessionGradingRuleDesc] = get_flow_rules(
            flow_desc, FlowSessionGradingRuleDesc,
            session.participation, session.flow_id, now_datetime,
            )

    from course.enrollment import get_participation_role_identifiers
    roles = get_participation_role_identifiers(session.course, session.participation)

    for rule in rules:
        if rule.if_has_role:
            if all(role not in rule.if_has_role for role in roles):
                continue

        if not _eval_generic_session_conditions(rule, session):
            continue

        if not _eval_participation_tags_conditions(rule, session.participation):
            continue

        if rule.if_completed_before is not None:
            if rule.use_last_activity_as_completion_time:
                last_activity = session.last_activity()
                if last_activity is not None:
                    completion_time = last_activity
                else:
                    completion_time = now_datetime
            else:
                if session.in_progress:
                    completion_time = now_datetime
                else:
                    completion_time = not_none(session.completion_time)

            if completion_time > rule.if_completed_before.eval(session.course):
                continue

        due = rule.due
        generates_grade = rule.generates_grade

        grade_identifier = None
        grade_aggregation_strategy = None
        grade_identifier = flow_desc.rules.grade_identifier
        grade_aggregation_strategy = flow_desc.rules.grade_aggregation_strategy

        return FlowSessionGradingModeWithFlowLevelInfo(
                grade_identifier=grade_identifier,
                grade_aggregation_strategy=grade_aggregation_strategy,
                due=due,
                generates_grade=generates_grade,
                description=rule. description,
                credit_percent=rule.credit_percent,
                use_last_activity_as_completion_time=rule.use_last_activity_as_completion_time,

                bonus_points=rule.bonus_points,
                max_points=rule.max_points,
                max_points_enforced_cap=rule.max_points_enforced_cap,
                )

    raise RuntimeError(_("grading rule determination was unable to find "
            "a grading rule"))

# }}}


# {{{ contexts

class AnyArgumentType:
    pass


ANY_ARGUMENT = AnyArgumentType()


class CoursePageContext:
    request: RelateHttpRequest
    course_identifier: str
    old_language: str | None

    course: Course
    participation: Participation | None
    repo: Repo_ish
    course_commit_sha: bytes

    _permissions_cache: frozenset[tuple[str, str | None]] | None
    _role_identifiers_cache: Set[str] | None
    _is_in_context_manager: bool

    def __init__(self, request: http.HttpRequest, course_identifier: str) -> None:

        # account for monkeypatching
        self.request = cast("RelateHttpRequest", request)

        self.course_identifier = course_identifier
        self._permissions_cache = None
        self._role_identifiers_cache = None
        self.old_language = None

        # using this to prevent nested using as context manager
        self._is_in_context_manager = False

        from course.models import Course
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

    def role_identifiers(self) -> Set[str]:
        if self._role_identifiers_cache is not None:
            return self._role_identifiers_cache

        from course.enrollment import get_participation_role_identifiers
        self._role_identifiers_cache = get_participation_role_identifiers(
                self.course, self.participation)
        return self._role_identifiers_cache

    def permissions(self) -> frozenset[tuple[str, str | None]]:
        if self.participation is None:
            if self._permissions_cache is not None:
                return self._permissions_cache

            from course.enrollment import get_participation_permissions
            perm = get_participation_permissions(self.course, self.participation)

            self._permissions_cache = perm

            return perm
        else:
            return self.participation.permissions()

    def has_permission(self,
                perm: ParticipationPermission,
                argument: str | AnyArgumentType | None = None
            ) -> bool:
        if argument is ANY_ARGUMENT:
            return any(perm == p
                    for p, arg in self.permissions())
        else:
            return (perm, argument) in self.permissions()

    def _set_course_lang(self, action: str) -> None:
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


class FlowContext:
    repo: Repo_ish
    course: Course
    flow_id: str
    course_commit_sha: bytes
    flow_desc: FlowDesc

    def __init__(
            self,
            repo: Repo_ish,
            course: Course,
            flow_id: str,
            participation: Participation | None = None) -> None:
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
    page_context: PageContext | None
    page: PageBase | None
    page_data: FlowPageData

    def __init__(
            self,
            repo: Repo_ish,
            course: Course,
            flow_id: str,
            page_ordinal: int,
            participation: Participation | None,
            flow_session: FlowSession,
            request: http.HttpRequest | None = None,
            ) -> None:
        super().__init__(repo, course, flow_id, participation)

        if page_ordinal >= not_none(flow_session.page_count):
            raise PageOrdinalOutOfRange()

        from course.models import FlowPageData
        page_data = self.page_data = get_object_or_404(
                FlowPageData, flow_session=flow_session, page_ordinal=page_ordinal)

        from course.content import get_flow_page
        try:
            self.page = get_flow_page(
                    flow_session.flow_id, self.flow_desc, page_data.group_id,
                    page_data.page_id)
        except ObjectDoesNotExist:
            self.page = None
            self.page_context = None
        else:
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
                    page_uri=page_uri,
                    request=request)

        self._prev_answer_visit = False

    @property
    def prev_answer_visit(self):
        if self._prev_answer_visit is False:
            from course.flow import get_prev_answer_visit
            self._prev_answer_visit = get_prev_answer_visit(self.page_data)

        return cast("FlowPageVisit | None", self._prev_answer_visit)

    @property
    def page_ordinal(self):
        return self.page_data.page_ordinal


def get_flow_page_with_ctx(
        fctx: FlowContext, page_data: FlowPageData) -> PageBase:
    from course.content import get_flow_page
    return get_flow_page(
            fctx.flow_id, fctx.flow_desc,
            page_data.group_id, page_data.page_id)

# }}}


# {{{ utilities for course-based views

def course_view(
            f: Callable[Concatenate[CoursePageContext, P], http.HttpResponse]
        ) -> Callable[Concatenate[http.HttpRequest, str, P], http.HttpResponse]:
    def wrapper(
                request: http.HttpRequest,
                course_identifier: str,
                *args: P.args,
                **kwargs: P.kwargs):
        with CoursePageContext(request, course_identifier) as pctx:
            response = f(pctx, *args, **kwargs)
            pctx.repo.close()
            return response

    from functools import update_wrapper
    update_wrapper(wrapper, f)

    return wrapper


class ParticipationPermissionWrapper:
    pctx: CoursePageContext

    def __init__(self, pctx: CoursePageContext) -> None:
        self.pctx = pctx

    def __getitem__(self, perm_str: str) -> bool:
        from course.constants import ParticipationPermission
        return self.pctx.has_permission(ParticipationPermission(perm_str), ANY_ARGUMENT)

    def __iter__(self):
        raise TypeError("ParticipationPermissionWrapper is not iterable.")


def render_course_page(
        pctx: CoursePageContext, template_name: str, args: dict[str, Any],
        allow_instant_flow_requests: bool = True) -> http.HttpResponse:

    args = args.copy()

    from course.views import get_now_or_fake_time
    now_datetime = get_now_or_fake_time(pctx.request)

    if allow_instant_flow_requests:
        from course.models import InstantFlowRequest
        instant_flow_requests = list(InstantFlowRequest.objects
                .filter(
                    course=pctx.course,
                    start_time__lte=now_datetime,
                    end_time__gte=now_datetime,
                    cancelled=False)
                .order_by("start_time"))
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

class PageInstanceCache:
    """Caches instances of :class:`course.page.Page`."""

    repo: Repo_ish
    course: Course
    flow_id: str
    flow_desc_cache: dict[bytes, FlowDesc]
    page_cache: dict[Hashable, PageBase]

    def __init__(self, repo: Repo_ish, course: Course, flow_id: str):
        self.repo = repo
        self.course = course
        self.flow_id = flow_id
        self.flow_desc_cache = {}
        self.page_cache = {}

    def get_flow_desc_from_cache(self, commit_sha: bytes):
        try:
            return self.flow_desc_cache[commit_sha]
        except KeyError:
            flow_desc = get_flow_desc(self.repo, self.course,
                    self.flow_id, commit_sha)
            self.flow_desc_cache[commit_sha] = flow_desc
            return flow_desc

    def get_page(self, group_id: str, page_id: str, commit_sha: bytes) -> PageBase:
        key = (group_id, page_id, commit_sha)
        try:
            return self.page_cache[key]
        except KeyError:

            from course.content import get_flow_page
            page = get_flow_page(
                    self.flow_id,
                    self.get_flow_desc_from_cache(commit_sha),
                    group_id, page_id)

            self.page_cache[key] = page
            return page

# }}}


# {{{ codemirror config

@dataclass(frozen=True)
class JsLiteral:
    js: str


def repr_js(obj: Any) -> str:
    if isinstance(obj, list):
        return "[{}]".format(", ".join(repr_js(ch) for ch in obj))
    elif isinstance(obj, dict):
        return "{{{}}}".format(", ".join(f"{k}: {repr_js(v)}" for k, v in obj.items()))
    elif isinstance(obj, bool):
        return repr(obj).lower()
    elif isinstance(obj, int | float):
        return repr(obj)
    elif isinstance(obj, str):
        return repr(obj)
    elif isinstance(obj, JsLiteral):
        return obj.js
    else:
        raise ValueError(f"unsupported object type: {type(obj)}")


class CodeMirrorTextarea(forms.Textarea):
    @property
    def media(self):
        return forms.Media(js=["bundle-codemirror.js"])

    def __init__(self, attrs=None,
                 *,
                 language_mode=None, interaction_mode,
                 indent_unit: int,
                 autofocus: bool,
                 additional_keys: dict[str, JsLiteral],
                 **kwargs):
        super().__init__(attrs, **kwargs)
        self.language_mode = language_mode
        self.interaction_mode = interaction_mode
        self.indent_unit = indent_unit
        self.autofocus = autofocus
        self.additional_keys = additional_keys

    # TODO: Maybe add VSCode keymap?
    # https://github.com/replit/codemirror-vscode-keymap
    def render(self, name, value, attrs=None, renderer=None) -> SafeString:
        # based on
        # https://github.com/codemirror/basic-setup/blob/b3be7cd30496ee578005bd11b1fa6a8b21fcbece/src/codemirror.ts
        extensions = [
                JsLiteral(f"rlCodemirror.indentUnit.of({' ' * self.indent_unit !r})"),
                ]

        if self.interaction_mode == "vim":
            extensions.insert(0, JsLiteral("rlCodemirror.vim()"))
        elif self.interaction_mode == "emacs":
            extensions.insert(0, JsLiteral("rlCodemirror.emacs()"))

        if self.language_mode is not None:
            extensions.append(JsLiteral(f"rlCodemirror.{self.language_mode}()"))

        additional_keys = [
            {
                "key": key,
                "run": func,
            }
            for key, func in self.additional_keys.items()
        ]
        output = [super().render(
                        name, value, attrs, renderer),
                  f"""
                  <script type="text/javascript">
                    rlCodemirror.editorFromTextArea(
                        document.getElementById('id_{name}'),
                        {repr_js(extensions)},
                        {repr_js(self.autofocus)},
                        {repr_js(additional_keys)}
                        )
                  </script>
                  """]

        return mark_safe("\n".join(output))


def get_codemirror_widget(
        language_mode: str | None,
        interaction_mode: str | None,
        *,
        autofocus: bool = False,
        additional_keys: dict[str, JsLiteral] | None = None,
        ) -> tuple[CodeMirrorTextarea, str]:
    if additional_keys is None:
        additional_keys = {}

    from django.urls import reverse
    help_text = (_("Press Esc then Tab to leave the editor. ")
            + _("Set editor mode in <a href='%s'>user profile</a>.")
            % reverse("relate-user_profile"))

    if language_mode in ["python", "yaml"]:
        indent_unit = 4
    else:
        indent_unit = 2

    return CodeMirrorTextarea(
                    language_mode=language_mode,
                    interaction_mode=interaction_mode,
                    indent_unit=indent_unit,
                    autofocus=autofocus,
                    additional_keys=additional_keys,
                    ), help_text

# }}}


# {{{ prosemirror

class ProseMirrorTextarea(forms.Textarea):
    @property
    def media(self):
        return forms.Media(js=["bundle-prosemirror.js"])

    @override
    def render(self, name, value, attrs=None, renderer=None) -> SafeString:
        output = [super().render(
                        name, value, attrs, renderer),
                  f"""
                  <script type="text/javascript">
                    rlProsemirror.editorFromTextArea(
                        document.getElementById('id_{name}'),
                        )
                  </script>
                  """]

        return mark_safe("\n".join(output))

    math_help_text = mark_safe(r"""
    See the <a href="https://katex.org/docs/supported.html"
            >list of supported math commands</a>.
    More tips for using this editor to type math:
    <ul>
        <li>
        You may paste in Markdown-with-math (as accepted by
        <a
        href="https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/writing-mathematical-expressions"
        >Github</a>,
        <a href="https://pandoc.org/MANUAL.html#math">Pandoc</a>, or
        <a href="https://meta.discourse.org/t/discourse-math/65770">Discourse</a>).
        <li>
        Inline math nodes are delimited with <code>$</code>.
        After typing the closing dollar sign in
        an expression like <code>$\int_a^b f(x) dx$</code>, a math node will appear.
        </li>

        <li>
        To start a block math node, press Enter to create a blank line,
        then type <code>$$</code> followed by Space. You can type multi-line math
        expressions, and the result will render in display style.
        </li>
        <li>
        Math nodes behave like regular text when using arrow keys or Backspace.
        From within a math node, press Ctrl-Backspace to delete the entire node.
        You can select, copy, and paste math nodes just like regular text!
        </li>
    </ul>
    """)

# }}}


# {{{ facility processing

def get_facilities_config(
        request: http.HttpRequest | None = None
        ) -> dict[str, dict[str, Any]] | None:
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


class FacilityFindingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: http.HttpRequest) -> http.HttpResponse:
        pretend_facilities = request.session.get("relate_pretend_facilities")

        if pretend_facilities is not None:
            facilities = pretend_facilities
        else:
            remote_address = remote_address_from_request(request)

            facilities = set()

            facilities_config = get_facilities_config(request)
            if facilities_config is None:
                facilities_config = {}

            from ipaddress import ip_network
            for name, props in facilities_config.items():
                ip_ranges = props.get("ip_ranges", [])
                for ir in ip_ranges:
                    if remote_address in ip_network(str(ir)):
                        facilities.add(name)

        request = cast("RelateHttpRequest", request)
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
                f": {err_msg}"))

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


def will_use_masked_profile_for_email(
            recipient_email: str | Sequence[str] | None
        ) -> bool:
    if not recipient_email:
        return False
    if isinstance(recipient_email, str):
        recipient_email = [recipient_email]
    from course.models import Participation
    recipient_participations = (
        Participation.objects.filter(
            user__email__in=recipient_email
        ))
    from course.constants import ParticipationPermission as PPerm
    for part in recipient_participations:
        if part.has_permission(PPerm.view_participant_masked_profile):
            return True
    return False


def get_course_specific_language_choices() -> tuple[tuple[str, Any], ...]:

    from collections import OrderedDict

    from django.conf import settings

    all_options = ((settings.LANGUAGE_CODE, None), *tuple(settings.LANGUAGES))
    filtered_options_dict = OrderedDict(all_options)

    def get_default_option() -> tuple[str, str]:
        # For the default language used, if USE_I18N is True, display
        # "Disabled". Otherwise display its lang info.
        if not settings.USE_I18N:
            formatted_descr = (
                get_formatted_options(settings.LANGUAGE_CODE, None)[1])
        else:
            formatted_descr = _("disabled (i.e., displayed language is "
                                "determined by user's browser preference)")
        return "", string_concat("{}: ".format(_("Default")), formatted_descr)

    def get_formatted_options(
            lang_code: str, lang_descr: str | None) -> tuple[str, str]:
        if lang_descr is None:
            lang_descr = OrderedDict(settings.LANGUAGES).get(lang_code)
            if lang_descr is None:
                try:
                    lang_info = translation.get_language_info(lang_code)
                    lang_descr = lang_info["name_translated"]
                except KeyError:
                    return (lang_code.strip(), lang_code)

        return (lang_code.strip(),
                string_concat(_(lang_descr), f" ({lang_code})"))

    filtered_options = (
        [get_default_option(),
            *list(starmap(get_formatted_options, filtered_options_dict.items()))])

    # filtered_options[1] is the option for settings.LANGUAGE_CODE
    # it's already displayed when settings.USE_I18N is False
    if not settings.USE_I18N:
        filtered_options.pop(1)

    return tuple(filtered_options)


class LanguageOverride(ContextDecorator):
    def __init__(self, course: Course, deactivate: bool = False) -> None:
        self.course = course
        self.deactivate = deactivate

        if course.force_lang:
            self.language = course.force_lang
        else:
            from django.conf import settings
            self.language = settings.RELATE_ADMIN_EMAIL_LOCALE

    def __enter__(self) -> None:
        self.old_language = translation.get_language()
        if self.language is not None:
            translation.activate(self.language)
        else:
            translation.deactivate_all()

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        if self.old_language is None:
            translation.deactivate_all()
        elif self.deactivate:
            translation.deactivate()
        else:
            translation.activate(self.old_language)


class RelateJinjaMacroBase:
    def __init__(
            self,
            course: Course | None,
            repo: Repo_ish,
            commit_sha: bytes) -> None:
        self.course = course
        self.repo = repo
        self.commit_sha = commit_sha

    @property
    def name(self):
        # The name of the method used in the template
        raise NotImplementedError()

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError()


# vim: foldmethod=marker
