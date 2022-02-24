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

from typing import cast, List, Text

import datetime

from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages  # noqa
from django.core.exceptions import (
        PermissionDenied, ObjectDoesNotExist, SuspiciousOperation)
import django.forms as forms
import django.views.decorators.http as http_dec
from django import http
from django.utils.safestring import mark_safe
from django.db import transaction
from django.utils.translation import (
        gettext_lazy as _,
        gettext,
        pgettext,
        pgettext_lazy,
        )
from django.utils.functional import lazy
from django.contrib.auth.decorators import login_required

from django_select2.forms import Select2Widget

mark_safe_lazy = lazy(mark_safe, str)

from django.views.decorators.cache import cache_control

from crispy_forms.layout import Submit, Layout, Div

from relate.utils import StyledForm, StyledModelForm, string_concat

from course.auth import get_pre_impersonation_user
from course.enrollment import (
        get_participation_for_request,
        get_participation_permissions)
from course.constants import (
        participation_permission as pperm,
        participation_status,
        FLOW_PERMISSION_CHOICES,
        flow_rule_kind, FLOW_RULE_KIND_CHOICES
        )
from course.models import (
        Course,
        InstantFlowRequest,
        Participation,
        FlowSession,
        FlowRuleException)

from course.content import get_course_repo

from course.utils import (  # noqa
        course_view,
        render_course_page,
        CoursePageContext,
        get_course_specific_language_choices)

# {{{ for mypy

from typing import Tuple, Text, Any, Iterable, Dict, Optional, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from course.content import (  # noqa
        FlowDesc,
        )

    from accounts.models import User  # noqa

# }}}


NONE_SESSION_TAG = string_concat("<<<", _("NONE"), ">>>")  # noqa


# {{{ home

def home(request: http.HttpRequest) -> http.HttpResponse:
    now_datetime = get_now_or_fake_time(request)

    current_courses = []
    past_courses = []
    for course in Course.objects.filter(listed=True):
        participation = get_participation_for_request(request, course)

        show = True
        if course.hidden:
            perms = get_participation_permissions(course, participation)
            if (pperm.view_hidden_course_page, None) not in perms:
                show = False

        if show:
            if (course.end_date is None
                    or now_datetime.date() <= course.end_date):
                current_courses.append(course)
            else:
                past_courses.append(course)

    def course_sort_key_minor(course):
        return course.number if course.number is not None else ""

    def course_sort_key_major(course):
        return (course.start_date
                if course.start_date is not None else now_datetime.date())

    current_courses.sort(key=course_sort_key_minor)
    past_courses.sort(key=course_sort_key_minor)
    current_courses.sort(key=course_sort_key_major, reverse=True)
    past_courses.sort(key=course_sort_key_major, reverse=True)

    return render(request, "course/home.html", {
        "current_courses": current_courses,
        "past_courses": past_courses,
        })

# }}}


# {{{ pages

def check_course_state(
        course: Course, participation: Participation | None) -> None:
    """
    Check to see if the course is hidden.

    If hidden, only allow access to 'ta' and 'instructor' roles
    """
    if course.hidden:
        if participation is None:
            raise PermissionDenied(_("course page is currently hidden"))
        if not participation.has_permission(pperm.view_hidden_course_page):
            raise PermissionDenied(_("course page is currently hidden"))


@course_view
def course_page(pctx: CoursePageContext) -> http.HttpResponse:
    from course.content import get_processed_page_chunks, get_course_desc
    page_desc = get_course_desc(pctx.repo, pctx.course, pctx.course_commit_sha)

    chunks = get_processed_page_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, page_desc,
            pctx.role_identifiers(), get_now_or_fake_time(pctx.request),
            facilities=pctx.request.relate_facilities)

    show_enroll_button = (
            pctx.course.accepts_enrollment
            and pctx.participation is None)

    if pctx.request.user.is_authenticated and Participation.objects.filter(
            user=pctx.request.user,
            course=pctx.course,
            status=participation_status.requested).count():
        show_enroll_button = False

        messages.add_message(pctx.request, messages.INFO,
                _("Your enrollment request is pending. You will be "
                "notified once it has been acted upon."))

        from course.models import ParticipationPreapproval

        if ParticipationPreapproval.objects.filter(
                course=pctx.course).exclude(institutional_id=None).count():
            if not pctx.request.user.institutional_id:
                from django.urls import reverse
                messages.add_message(pctx.request, messages.WARNING,
                        _("This course uses institutional ID for "
                        "enrollment preapproval, please <a href='%s' "
                        "role='button' class='btn btn-md btn-primary'>"
                        "fill in your institutional ID &nbsp;&raquo;"
                        "</a> in your profile.")
                        % (
                            reverse("relate-user_profile")
                            + "?referer="
                            + pctx.request.path
                            + "&set_inst_id=1"
                            )
                        )
            else:
                if pctx.course.preapproval_require_verified_inst_id:
                    messages.add_message(pctx.request, messages.WARNING,
                            _("Your institutional ID is not verified or "
                            "preapproved. Please contact your course "
                            "staff.")
                            )

    return render_course_page(pctx, "course/course-page.html", {
        "chunks": chunks,
        "show_enroll_button": show_enroll_button,
        })


@course_view
def static_page(pctx: CoursePageContext, page_path: str) -> http.HttpResponse:
    from course.content import get_staticpage_desc, get_processed_page_chunks
    try:
        page_desc = get_staticpage_desc(pctx.repo, pctx.course,
                pctx.course_commit_sha, "staticpages/"+page_path+".yml")
    except ObjectDoesNotExist:
        raise http.Http404()

    chunks = get_processed_page_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, page_desc,
            pctx.role_identifiers(), get_now_or_fake_time(pctx.request),
            facilities=pctx.request.relate_facilities)

    return render_course_page(pctx, "course/static-page.html", {
        "chunks": chunks,
        "show_enroll_button": False,
        })

# }}}


# {{{ media

def media_etag_func(request, course_identifier, commit_sha, media_path):
    return ":".join([course_identifier, commit_sha, media_path])


@cache_control(max_age=3600*24*31)  # cache for a month
@http_dec.condition(etag_func=media_etag_func)
def get_media(request, course_identifier, commit_sha, media_path):
    course = get_object_or_404(Course, identifier=course_identifier)

    with get_course_repo(course) as repo:
        return get_repo_file_response(
            repo, "media/" + media_path, commit_sha.encode())


def repo_file_etag_func(request, course_identifier, commit_sha, path):
    return ":".join([course_identifier, commit_sha, path])


@cache_control(max_age=3600*24*31)  # cache for a month
@http_dec.condition(etag_func=repo_file_etag_func)
def get_repo_file(request, course_identifier, commit_sha, path):
    commit_sha = commit_sha.encode()

    course = get_object_or_404(Course, identifier=course_identifier)

    participation = get_participation_for_request(request, course)

    return get_repo_file_backend(
            request, course, participation, commit_sha, path)


def current_repo_file_etag_func(
        request: http.HttpRequest, course_identifier: str, path: str) -> str:
    course = get_object_or_404(Course, identifier=course_identifier)
    participation = get_participation_for_request(request, course)

    check_course_state(course, participation)

    from course.content import get_course_commit_sha
    commit_sha = get_course_commit_sha(course, participation)

    return ":".join([course_identifier, commit_sha.decode(), path])


@http_dec.condition(etag_func=current_repo_file_etag_func)
def get_current_repo_file(
        request: http.HttpRequest, course_identifier: str, path: str
        ) -> http.HttpResponse:
    course = get_object_or_404(Course, identifier=course_identifier)
    participation = get_participation_for_request(request, course)

    from course.content import get_course_commit_sha
    commit_sha = get_course_commit_sha(course, participation)

    return get_repo_file_backend(
            request, course, participation, commit_sha, path)


def get_repo_file_backend(
        request: http.HttpRequest,
        course: Course,
        participation: Participation | None,
        commit_sha: bytes,
        path: str,
        ) -> http.HttpResponse:
    # noqa
    """
    Check if a file should be accessible.  Then call for it if
    the permission is not denied.

    Order is important here.  An in-exam request takes precedence.

    Note: an access_role of "public" is equal to "unenrolled"
    """

    # check to see if the course is hidden
    check_course_state(course, participation)

    # set access to public (or unenrolled), student, etc
    if request.relate_exam_lockdown:
        access_kinds = ["in_exam"]
    else:
        from course.enrollment import get_participation_permissions
        access_kinds = [
                arg
                for perm, arg in get_participation_permissions(course, participation)
                if perm == pperm.access_files_for
                and arg is not None]

    from course.content import is_repo_file_accessible_as

    # retrieve local path for the repo for the course
    with get_course_repo(course) as repo:
        if not is_repo_file_accessible_as(access_kinds, repo, commit_sha, path):
            raise PermissionDenied()

        return get_repo_file_response(repo, path, commit_sha)


def get_repo_file_response(
        repo: Any, path: str, commit_sha: bytes
        ) -> http.HttpResponse:

    from course.content import get_repo_blob_data_cached

    try:
        data = get_repo_blob_data_cached(repo, path, commit_sha)
    except ObjectDoesNotExist:
        raise http.Http404()

    from mimetypes import guess_type
    content_type, __ = guess_type(path)

    if content_type is None:
        content_type = "application/octet-stream"

    return http.HttpResponse(data, content_type=content_type)

# }}}


# {{{ time travel

class FakeTimeForm(StyledForm):
    time = forms.DateTimeField(
            widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
            label=_("Time"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper.add_input(
                # Translators: "set" fake time.
                Submit("set", _("Set")))
        self.helper.add_input(
                # Translators: "unset" fake time.
                Submit("unset", _("Unset")))


def get_fake_time(request: http.HttpRequest) -> datetime.datetime | None:

    if request is not None and "relate_fake_time" in request.session:
        from django.conf import settings
        from pytz import timezone
        tz = timezone(settings.TIME_ZONE)
        return tz.localize(  # type: ignore
                datetime.datetime.fromtimestamp(
                    request.session["relate_fake_time"]))
    else:
        return None


def get_now_or_fake_time(request: http.HttpRequest) -> datetime.datetime:

    fake_time = get_fake_time(request)
    if fake_time is None:
        from django.utils.timezone import now
        return now()
    else:
        return fake_time


def may_set_fake_time(user: User | None) -> bool:

    if user is None:
        return False

    return Participation.objects.filter(
            user=user,
            roles__permissions__permission=pperm.set_fake_time
            ).count() > 0


@login_required
def set_fake_time(request):
    # allow staff to set fake time when impersonating
    pre_imp_user = get_pre_impersonation_user(request)
    if not (
            may_set_fake_time(request.user) or (
                pre_imp_user is not None
                and may_set_fake_time(pre_imp_user))):
        raise PermissionDenied(_("may not set fake time"))

    if request.method == "POST":
        form = FakeTimeForm(request.POST, request.FILES)
        do_set = "set" in form.data
        if form.is_valid():
            fake_time = form.cleaned_data["time"]
            if do_set:
                import time
                request.session["relate_fake_time"] = \
                        time.mktime(fake_time.timetuple())
            else:
                request.session.pop("relate_fake_time", None)

    else:
        if "relate_fake_time" in request.session:
            form = FakeTimeForm({
                "time": get_fake_time(request)
                })
        else:
            form = FakeTimeForm()

    return render(request, "generic-form.html", {
        "form": form,
        "form_description": _("Set fake time"),
    })


def fake_time_context_processor(request):
    return {
            "fake_time": get_fake_time(request),
            }

# }}}


# {{{ space travel (i.e. pretend to be in facility)

class FakeFacilityForm(StyledForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        from course.utils import get_facilities_config
        self.fields["facilities"] = forms.MultipleChoiceField(
                choices=(
                    (name, name)
                    for name in get_facilities_config()),
                widget=forms.CheckboxSelectMultiple,
                required=False,
                label=_("Facilities"),
                help_text=_("Facilities you wish to pretend to be in"))

        self.fields["custom_facilities"] = forms.CharField(
                label=_("Custom facilities"),
                required=False,
                help_text=_("More (non-predefined) facility names, separated "
                    "by commas, which would like to pretend to be in"))

        self.fields["add_pretend_facilities_header"] = forms.BooleanField(
                required=False,
                initial=True,
                label=_("Add fake facililities header"),
                help_text=_("Add a page header to every page rendered "
                    "while pretending to be in a facility, as a reminder "
                    "that this pretending is in progress."))

        self.helper.add_input(
                # Translators: "set" fake facility.
                Submit("set", _("Set")))
        self.helper.add_input(
                # Translators: "unset" fake facility.
                Submit("unset", _("Unset")))


def may_set_pretend_facility(user: User | None) -> bool:

    if user is None:
        return False

    return Participation.objects.filter(
            user=user,
            roles__permissions__permission=pperm.set_pretend_facility
            ).count() > 0


@login_required
def set_pretend_facilities(request):
    # allow staff to set fake time when impersonating
    pre_imp_user = get_pre_impersonation_user(request)
    if not (
            may_set_pretend_facility(request.user) or (
                pre_imp_user is not None
                and may_set_pretend_facility(pre_imp_user))):
        raise PermissionDenied(_("may not pretend facilities"))

    if request.method == "POST":
        form = FakeFacilityForm(request.POST)
        do_set = "set" in form.data
        if form.is_valid():
            if do_set:
                pretend_facilities = (
                        form.cleaned_data["facilities"]
                        + [s.strip()
                            for s in (
                                form.cleaned_data["custom_facilities"].split(","))
                            if s.strip()])

                request.session["relate_pretend_facilities"] = pretend_facilities
                request.session["relate_pretend_facilities_header"] = \
                        form.cleaned_data["add_pretend_facilities_header"]
            else:
                request.session.pop("relate_pretend_facilities", None)

    else:
        if "relate_pretend_facilities" in request.session:
            form = FakeFacilityForm({
                "facilities": [],
                "custom_facilities": ",".join(
                    request.session["relate_pretend_facilities"]),
                "add_pretend_facilities_header":
                request.session["relate_pretend_facilities_header"],
                })
        else:
            form = FakeFacilityForm()

    return render(request, "generic-form.html", {
        "form": form,
        "form_description": _("Pretend to be in Facilities"),
    })


def pretend_facilities_context_processor(request):
    return {
            "pretend_facilities": request.session.get(
                "relate_pretend_facilities", []),
            "add_pretend_facilities_header":
            request.session.get("relate_pretend_facilities_header", True),
            }

# }}}


# {{{ instant flow requests

class InstantFlowRequestForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"),
                widget=Select2Widget())
        self.fields["duration_in_minutes"] = forms.IntegerField(
                required=True, initial=20,
                label=pgettext_lazy("Duration for instant flow",
                                   "Duration in minutes"))

        self.helper.add_input(
                Submit(
                    "add",
                    pgettext("Add an instant flow", "Add")))
        self.helper.add_input(
                Submit(
                    "cancel",
                    pgettext("Cancel all instant flow(s)", "Cancel all")))


@course_view
def manage_instant_flow_requests(pctx):
    if not pctx.has_permission(pperm.manage_instant_flow_requests):
        raise PermissionDenied()

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = InstantFlowRequestForm(flow_ids, request.POST, request.FILES)
        if "add" in request.POST:
            op = "add"
        elif "cancel" in request.POST:
            op = "cancel"
        else:
            raise SuspiciousOperation(_("invalid operation"))

        now_datetime = get_now_or_fake_time(pctx.request)

        if form.is_valid():
            if op == "add":

                from datetime import timedelta
                ifr = InstantFlowRequest()
                ifr.course = pctx.course
                ifr.flow_id = form.cleaned_data["flow_id"]
                ifr.start_time = now_datetime
                ifr.end_time = (
                        now_datetime + timedelta(
                            minutes=form.cleaned_data["duration_in_minutes"]))
                ifr.save()

            else:
                assert op == "cancel"
                (InstantFlowRequest.objects
                        .filter(
                            course=pctx.course,
                            start_time__lte=now_datetime,
                            end_time__gte=now_datetime,
                            cancelled=False)
                        .order_by("start_time")
                        .update(cancelled=True))

    else:
        form = InstantFlowRequestForm(flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Manage Instant Flow Requests"),
    })

# }}}


# {{{ test flow

class FlowTestForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"),
                widget=Select2Widget())

        self.helper.add_input(
                Submit(
                    "test",
                    mark_safe_lazy(
                        string_concat(
                            pgettext("Start an activity", "Go"),
                            " &raquo;")),
                    ))


@course_view
def test_flow(pctx):
    if not pctx.has_permission(pperm.test_flow):
        raise PermissionDenied()

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = FlowTestForm(flow_ids, request.POST, request.FILES)
        if "test" not in request.POST:
            raise SuspiciousOperation(_("invalid operation"))

        if form.is_valid():
            return redirect("relate-view_start_flow",
                    pctx.course.identifier,
                    form.cleaned_data["flow_id"])

    else:
        form = FlowTestForm(flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Test Flow"),
    })

# }}}


# {{{ flow access exceptions

class ParticipationChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        user = obj.user
        return (
                "%(user_email)s - %(user_fullname)s"
                % {
                    "user_email": user.email,
                    "user_fullname": user.get_full_name()
                })


class ExceptionStage1Form(StyledForm):
    def __init__(self, course, flow_ids, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["participation"] = ParticipationChoiceField(
                queryset=(Participation.objects
                    .filter(
                        course=course,
                        status=participation_status.active,
                        )
                    .order_by("user__last_name")),
                required=True,
                help_text=_("Select participant for whom exception is to "
                "be granted."),
                label=_("Participant"),
                widget=Select2Widget())
        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"))

        self.helper.add_input(
                Submit(
                    "next",
                    mark_safe_lazy(
                        string_concat(
                            pgettext("Next step", "Next"),
                            " &raquo;"))))


@course_view
def grant_exception(pctx):
    if not pctx.has_permission(pperm.grant_exception):
        raise PermissionDenied(_("may not grant exceptions"))

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = ExceptionStage1Form(pctx.course, flow_ids, request.POST)

        if form.is_valid():
            return redirect("relate-grant_exception_stage_2",
                    pctx.course.identifier,
                    form.cleaned_data["participation"].id,
                    form.cleaned_data["flow_id"])

    else:
        form = ExceptionStage1Form(pctx.course, flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Grant Exception"),
    })


def strify_session_for_exception(session: FlowSession) -> str:

    from relate.utils import as_local_time, format_datetime_local
    # Translators: %s is the string of the start time of a session.
    result = (_("started at %s") % format_datetime_local(
        as_local_time(session.start_time)))

    if session.access_rules_tag:
        result += _(" tagged '%s'") % session.access_rules_tag

    return result


class CreateSessionForm(StyledForm):
    def __init__(
            self,
            session_tag_choices: list[tuple[str, str]],
            default_tag: str | None,
            create_session_is_override: bool,
            *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.fields["access_rules_tag_for_new_session"] = forms.ChoiceField(
                choices=session_tag_choices,
                initial=default_tag,
                help_text=_("If you click 'Create session', this tag will be "
                "applied to the new session."),
                label=_("Access rules tag for new session"))

        if create_session_is_override:
            self.helper.add_input(
                    Submit(
                        "create_session",
                        _("Create session (override rules)")))
        else:
            self.helper.add_input(
                    Submit(
                        "create_session",
                        _("Create session")))


class ExceptionStage2Form(StyledForm):
    def __init__(
            self, sessions: list[FlowSession], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.fields["session"] = forms.ChoiceField(
                choices=(
                    (session.id, strify_session_for_exception(session))
                    for session in sessions),
                help_text=_("The rules that currently apply to selected "
                "session will provide the default values for the rules "
                "on the next page."),
                label=_("Session"))

        self.helper.add_input(
                Submit(
                    "next",
                    mark_safe_lazy(
                        string_concat(
                            pgettext("Next step", "Next"),
                            " &raquo;"))))


@course_view
def grant_exception_stage_2(
        pctx: CoursePageContext, participation_id: str, flow_id: str
        ) -> http.HttpResponse:

    if not pctx.has_permission(pperm.grant_exception):
        raise PermissionDenied(_("may not grant exceptions"))

    # {{{ get flow data

    participation = get_object_or_404(Participation, id=participation_id)

    form_text = (
            string_concat(
                "<div class='relate-well'>",
                _("Granting exception to '%(participation)s' for "
                "'%(flow_id)s'."),
                "</div>")
            % {
                "participation": participation,
                "flow_id": flow_id})

    from course.content import get_flow_desc
    try:
        flow_desc = get_flow_desc(pctx.repo, pctx.course, flow_id,
                pctx.course_commit_sha)
    except ObjectDoesNotExist:
        raise http.Http404()

    now_datetime = get_now_or_fake_time(pctx.request)

    if hasattr(flow_desc, "rules"):
        access_rules_tags = getattr(flow_desc.rules, "tags", [])
    else:
        access_rules_tags = []

    from course.utils import get_session_start_rule
    session_start_rule = get_session_start_rule(pctx.course, participation,
            flow_id, flow_desc, now_datetime)

    create_session_is_override = False
    if not session_start_rule.may_start_new_session:
        create_session_is_override = True
        form_text += ("<div class='alert alert-info'>%s</div>" % (
            string_concat(
                "<i class='fa fa-info-circle'></i> ",
                _("Creating a new session is (technically) not allowed "
                "by course rules. Clicking 'Create Session' anyway will "
                "override this rule."))))

    session_tag_choices = [
            (tag, tag)
            for tag in access_rules_tags] + [(NONE_SESSION_TAG, NONE_SESSION_TAG)]

    default_tag = session_start_rule.tag_session
    if default_tag is None:
        default_tag = NONE_SESSION_TAG
    else:
        if default_tag not in access_rules_tags:
            session_tag_choices.insert(0, (default_tag, default_tag))

    # }}}

    def find_sessions() -> list[FlowSession]:

        return list(FlowSession.objects
                .filter(
                    participation=participation,
                    flow_id=flow_id)
               .order_by("start_time"))

    exception_form = None
    request = pctx.request
    if request.method == "POST":
        exception_form = ExceptionStage2Form(find_sessions(), request.POST)
        create_session_form = CreateSessionForm(
                session_tag_choices, default_tag, create_session_is_override,
                request.POST)

        if "create_session" in request.POST or "next" in request.POST:
            pass
        else:
            raise SuspiciousOperation(_("invalid command"))

        if create_session_form.is_valid() and "create_session" in request.POST:
            from course.flow import start_flow

            access_rules_tag = (
                    create_session_form.cleaned_data[
                        "access_rules_tag_for_new_session"])
            if access_rules_tag == NONE_SESSION_TAG:
                access_rules_tag = None

            new_session = start_flow(pctx.repo, pctx.course, participation,
                    user=participation.user,
                    flow_id=flow_id,
                    flow_desc=flow_desc,
                    session_start_rule=session_start_rule,
                    now_datetime=now_datetime)

            if access_rules_tag is not None:
                new_session.access_rules_tag = access_rules_tag
                new_session.save()

            exception_form = None
            messages.add_message(
                pctx.request, messages.SUCCESS,
                _("A new session%(tag)s was created for '%(participation)s' "
                  "for '%(flow_id)s'.")
                % {
                    "tag":
                        _(" tagged '%s'") % access_rules_tag
                        if access_rules_tag is not None else "",
                    "participation": participation,
                    "flow_id": flow_id})

        elif exception_form.is_valid() and "next" in request.POST:  # type: ignore
            return redirect(
                    "relate-grant_exception_stage_3",
                    pctx.course.identifier,
                    participation.id,
                    flow_id,
                    exception_form.cleaned_data["session"])  # type: ignore
    else:
        create_session_form = CreateSessionForm(
                session_tag_choices, default_tag, create_session_is_override)

    if exception_form is None:
        exception_form = ExceptionStage2Form(find_sessions())

    return render_course_page(pctx, "course/generic-course-form.html", {
        "forms": [exception_form, create_session_form],
        "form_text": form_text,
        "form_description": _("Grant Exception"),
    })


class ExceptionStage3Form(StyledForm):
    def __init__(
            self,
            default_data: dict,
            flow_desc: FlowDesc,
            base_session_tag: str,
            *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        rules = getattr(flow_desc, "rules", object())
        tags = getattr(rules, "tags", [])

        layout = []

        if tags:
            tags = [NONE_SESSION_TAG] + tags
            if base_session_tag is not None and base_session_tag not in tags:
                tags.append(base_session_tag)

            self.fields["set_access_rules_tag"] = forms.ChoiceField(
                    choices=[(tag, tag) for tag in tags],
                    initial=(base_session_tag
                        if base_session_tag is not None
                        else NONE_SESSION_TAG),
                    label=_("Set access rules tag"))
            self.fields["restrict_to_same_tag"] = forms.BooleanField(
                    label=_("Exception only applies to sessions "
                    "with the above tag"),
                    required=False,
                    initial=default_data.get("restrict_to_same_tag", True))

            layout.append(
                    Div("set_access_rules_tag", "restrict_to_same_tag",
                        css_class="relate-well"))

        access_fields = ["create_access_exception", "access_expires"]

        self.fields["create_access_exception"] = forms.BooleanField(
            required=False, help_text=_("If set, an exception for the "
            "access rules will be created."), initial=True,
            label=_("Create access rule exception"))

        self.fields["access_expires"] = forms.DateTimeField(
            widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
            required=False,
            label=pgettext_lazy("Time when access expires", "Access expires"),
            help_text=_("At the specified time, the special access granted below "
            "will expire "
            "and revert to being the same as for the rest of the class. "
            "This field may "
            "be empty, in which case this access does not expire. Note also that "
            "the grading-related entries (such as 'due date' and 'credit percent') "
            "do not expire and remain valid indefinitely, unless overridden by "
            "another exception."))

        for key, name in FLOW_PERMISSION_CHOICES:
            self.fields[key] = forms.BooleanField(label=name, required=False,
                    initial=default_data.get(key) or False)

            access_fields.append(key)

        layout.append(Div(*access_fields, css_class="relate-well"))

        self.fields["create_grading_exception"] = forms.BooleanField(
                required=False, help_text=_("If set, an exception for the "
                "grading rules will be created."), initial=True,
                label=_("Create grading rule exception"))
        self.fields["due_same_as_access_expiration"] = forms.BooleanField(
                required=False, help_text=_("If set, the 'Due time' field will be "
                "disregarded."),
                initial=default_data.get("due_same_as_access_expiration") or False,
                label=_("Due same as access expiration"))
        self.fields["due"] = forms.DateTimeField(
                widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
                required=False,
                help_text=_("The due time shown to the student. Also, the "
                "time after which "
                "any session under these rules is subject to expiration."),
                initial=default_data.get("due"),
                label=_("Due time"))

        self.fields["generates_grade"] = forms.BooleanField(required=False,
                initial=default_data.get("generates_grade", True),
                label=_("Generates grade"))
        self.fields["credit_percent"] = forms.FloatField(required=False,
                initial=default_data.get("credit_percent"),
                label=_("Credit percent"))
        self.fields["bonus_points"] = forms.FloatField(required=False,
                initial=default_data.get("bonus_points"),
                label=_("Bonus points"))
        self.fields["max_points"] = forms.FloatField(required=False,
                initial=default_data.get("max_points"),
                label=_("Maximum number of points (for percentage)"))
        self.fields["max_points_enforced_cap"] = forms.FloatField(required=False,
                initial=default_data.get("max_points_enforced_cap"),
                label=_("Maximum number of points (enforced cap)"))

        layout.append(Div("create_grading_exception",
            "due_same_as_access_expiration", "due",
            "generates_grade",
            "credit_percent", "bonus_points", "max_points",
            "max_points_enforced_cap",
            css_class="relate-well"))

        self.fields["comment"] = forms.CharField(
                widget=forms.Textarea, required=True,
                initial=default_data.get("comment"),
                label=_("Comment"))

        layout.append("comment")

        self.helper.add_input(
                Submit(
                    "save", _("Save")))

        self.helper.layout = Layout(*layout)

    def clean(self):
        access_expires = self.cleaned_data.get("access_expires")
        due_same_as_access_expiration = self.cleaned_data.get(
            "due_same_as_access_expiration")
        if (not access_expires and due_same_as_access_expiration):
            self.add_error(
                "access_expires",
                _("Must specify access expiration if 'due same "
                  "as access expiration' is set."))


@course_view
@transaction.atomic
def grant_exception_stage_3(
        pctx: CoursePageContext,
        participation_id: int,
        flow_id: str,
        session_id: int) -> http.HttpResponse:
    if not pctx.has_permission(pperm.grant_exception):
        raise PermissionDenied(_("may not grant exceptions"))

    participation = get_object_or_404(Participation, id=participation_id)

    from course.content import get_flow_desc
    try:
        flow_desc = get_flow_desc(pctx.repo, pctx.course, flow_id,
                pctx.course_commit_sha)
    except ObjectDoesNotExist:
        raise http.Http404()

    session = FlowSession.objects.get(id=int(session_id))

    now_datetime = get_now_or_fake_time(pctx.request)
    from course.utils import (
            get_session_access_rule,
            get_session_grading_rule)
    access_rule = get_session_access_rule(session, flow_desc, now_datetime)
    grading_rule = get_session_grading_rule(session, flow_desc, now_datetime)

    request = pctx.request
    if request.method == "POST":
        form = ExceptionStage3Form(
                {}, flow_desc, session.access_rules_tag, request.POST)

        if form.is_valid():
            permissions = [
                    key
                    for key, __ in FLOW_PERMISSION_CHOICES
                    if form.cleaned_data[key]]

            from course.validation import (
                    validate_session_access_rule,
                    validate_session_grading_rule,
                    ValidationContext)
            from relate.utils import dict_to_struct
            vctx = ValidationContext(
                    repo=pctx.repo,
                    commit_sha=pctx.course_commit_sha)

            flow_desc = get_flow_desc(pctx.repo,
                    pctx.course,
                    flow_id, pctx.course_commit_sha)

            tags: list[str] = []
            if hasattr(flow_desc, "rules"):
                tags = cast(List[str], getattr(flow_desc.rules, "tags", []))

            exceptions_created = []

            restricted_to_same_tag = bool(
                form.cleaned_data.get("restrict_to_same_tag")
                and session.access_rules_tag is not None)

            # {{{ put together access rule

            if form.cleaned_data["create_access_exception"]:
                new_access_rule = {"permissions": permissions}

                if restricted_to_same_tag:
                    new_access_rule["if_has_tag"] = session.access_rules_tag

                validate_session_access_rule(
                        vctx, _("newly created exception"),
                        dict_to_struct(new_access_rule), tags)

                fre_access = FlowRuleException(
                    flow_id=flow_id,
                    participation=participation,
                    expiration=form.cleaned_data["access_expires"],
                    creator=pctx.request.user,
                    comment=form.cleaned_data["comment"],
                    kind=flow_rule_kind.access,
                    rule=new_access_rule)
                fre_access.save()
                exceptions_created.append(
                    dict(FLOW_RULE_KIND_CHOICES)[fre_access.kind])

            # }}}

            session_access_rules_tag_changed = False
            if not restricted_to_same_tag:
                new_access_rules_tag = form.cleaned_data.get("set_access_rules_tag")
                if new_access_rules_tag == NONE_SESSION_TAG:
                    new_access_rules_tag = None

                if session.access_rules_tag != new_access_rules_tag:
                    session.access_rules_tag = new_access_rules_tag
                    session.save()
                    session_access_rules_tag_changed = True

                    if new_access_rules_tag is not None:
                        msg = _("Access rules tag of the selected session "
                                "updated to '%s'.") % new_access_rules_tag
                    else:
                        msg = _(
                            "Removed access rules tag of the selected session.")

                    messages.add_message(pctx.request, messages.SUCCESS, msg)

            # {{{ put together grading rule

            if form.cleaned_data["create_grading_exception"]:
                due = form.cleaned_data["due"]
                if form.cleaned_data["due_same_as_access_expiration"]:
                    due = form.cleaned_data["access_expires"]

                descr = gettext("Granted exception")
                if form.cleaned_data["credit_percent"] is not None:
                    descr += string_concat(" (%.1f%% ", gettext("credit"), ")") \
                            % form.cleaned_data["credit_percent"]

                due_local_naive = due
                if due_local_naive is not None:
                    from relate.utils import as_local_time
                    due_local_naive = (
                            as_local_time(due_local_naive)
                            .replace(tzinfo=None))

                new_grading_rule = {
                    "description": descr,
                    }

                if due_local_naive is not None:
                    new_grading_rule["due"] = due_local_naive

                for attr_name in ["credit_percent", "bonus_points",
                        "max_points", "max_points_enforced_cap", "generates_grade"]:
                    if form.cleaned_data[attr_name] is not None:
                        new_grading_rule[attr_name] = form.cleaned_data[attr_name]

                if restricted_to_same_tag:
                    new_grading_rule["if_has_tag"] = session.access_rules_tag

                validate_session_grading_rule(
                        vctx, _("newly created exception"),
                        dict_to_struct(new_grading_rule), tags,
                        grading_rule.grade_identifier)

                fre_grading = FlowRuleException(
                    flow_id=flow_id,
                    participation=participation,
                    creator=pctx.request.user,
                    comment=form.cleaned_data["comment"],
                    kind=flow_rule_kind.grading,
                    rule=new_grading_rule)
                fre_grading.save()
                exceptions_created.append(
                    dict(FLOW_RULE_KIND_CHOICES)[fre_grading.kind])

            # }}}

            if exceptions_created:
                for exc in exceptions_created:
                    messages.add_message(pctx.request, messages.SUCCESS,
                            _(
                                "'%(exception_type)s' exception granted to "
                                "'%(participation)s' for '%(flow_id)s'.")
                            % {
                                "exception_type": exc,
                                "participation": participation,
                                "flow_id": flow_id})
            else:
                if session_access_rules_tag_changed:
                    messages.add_message(
                        pctx.request, messages.WARNING,
                        _(
                            "No other exception granted to the given flow "
                            "session of '%(participation)s' "
                            "for '%(flow_id)s'.")
                        % {
                            "participation": participation,
                            "flow_id": flow_id})
                else:
                    messages.add_message(pctx.request, messages.WARNING,
                            _(
                                "No exception granted to the given flow "
                                "session of '%(participation)s' "
                                "for '%(flow_id)s'.")
                            % {
                                "participation": participation,
                                "flow_id": flow_id})
            return redirect(
                    "relate-grant_exception",
                    pctx.course.identifier)

    else:
        data = {
                "restrict_to_same_tag": session.access_rules_tag is not None,
                #"due_same_as_access_expiration": True,
                "due": grading_rule.due,
                "generates_grade": grading_rule.generates_grade,
                "credit_percent": grading_rule.credit_percent,
                "bonus_points": grading_rule.bonus_points,
                "max_points": grading_rule.max_points,
                "max_points_enforced_cap": grading_rule.max_points_enforced_cap,
                }
        for perm in access_rule.permissions:
            data[perm] = True

        form = ExceptionStage3Form(data, flow_desc, session.access_rules_tag)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": _("Grant Exception"),
        "form_text": string_concat(
            "<div class='relate-well'>",
            _("Granting exception to '%(participation)s' "
            "for '%(flow_id)s' (session %(session)s)."),
            "</div>")
        % {
            "participation": participation,
            "flow_id": flow_id,
            "session": strify_session_for_exception(session)},
    })

# }}}


# {{{ ssh keypair

@login_required
def generate_ssh_keypair(request):
    if not request.user.is_staff:
        raise PermissionDenied(_("only staff may use this tool"))

    from paramiko import RSAKey
    key_class = RSAKey
    prv = key_class.generate(bits=2048)

    import io
    prv_bio = io.StringIO()
    prv.write_private_key(prv_bio)

    prv_bio_read = io.StringIO(prv_bio.getvalue())

    pub = key_class.from_private_key(prv_bio_read)

    pub_bio = io.StringIO()
    pub_bio.write(f"{pub.get_name()} {pub.get_base64()} relate-course-key")

    return render(request, "course/keypair.html", {
        "public_key": prv_bio.getvalue(),
        "private_key": pub_bio.getvalue(),
        })

# }}}


# {{{ celery task monitoring

@login_required
def monitor_task(request, task_id):
    from celery.result import AsyncResult
    from celery import states
    async_res = AsyncResult(task_id)

    progress_percent = None
    progress_statement = None

    if async_res.state == "PROGRESS":
        meta = async_res.info
        current = meta["current"]
        total = meta["total"]
        if total > 0:
            progress_percent = 100 * (current / total)

        progress_statement = (
                _("%(current)d out of %(total)d items processed.")
                % {"current": current, "total": total})

    if async_res.state == states.SUCCESS:
        if (isinstance(async_res.result, dict)
                and "message" in async_res.result):
            progress_statement = async_res.result["message"]

    traceback = None
    if request.user.is_staff and async_res.state == states.FAILURE:
        traceback = async_res.traceback

    return render(request, "course/task-monitor.html", {
        "state": async_res.state,
        "progress_percent": progress_percent,
        "progress_statement": progress_statement,
        "traceback": traceback,
        })

# }}}


# {{{ edit course

class EditCourseForm(StyledModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["identifier"].disabled = True
        self.fields["active_git_commit_sha"].disabled = True

        self.helper.add_input(
                Submit("submit", _("Update")))

    class Meta:
        model = Course
        exclude = (
                "participants",
                "trusted_for_markup",
                )
        widgets = {
                "start_date": forms.DateInput(attrs={"type": "date"}),
                "end_date": forms.DateInput(attrs={"type": "date"}),
                "force_lang": forms.Select(
                    choices=get_course_specific_language_choices()),
                }


@course_view
def edit_course(pctx):
    if not pctx.has_permission(pperm.edit_course):
        raise PermissionDenied()

    request = pctx.request
    instance = pctx.course

    if request.method == "POST":
        form = EditCourseForm(request.POST, instance=pctx.course)
        if form.is_valid():
            if form.has_changed():
                instance = form.save()
                messages.add_message(
                    request, messages.SUCCESS,
                    _("Successfully updated course settings."))
            else:
                messages.add_message(
                    request, messages.INFO,
                    _("No change was made on the settings."))

        else:
            messages.add_message(request, messages.ERROR,
                                 _("Failed to update course settings."))

    form = EditCourseForm(instance=instance)

    # Render the page with course.force_lang, in case force_lang was updated
    from course.utils import LanguageOverride
    with LanguageOverride(instance):
        return render_course_page(pctx, "course/generic-course-form.html", {
            "form_description": _("Edit Course"),
            "form": form
            })

# }}}

# vim: foldmethod=marker
