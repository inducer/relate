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
from django.contrib import messages  # noqa
from django.core.exceptions import (
        PermissionDenied, ObjectDoesNotExist, SuspiciousOperation)
import django.forms as forms
import django.views.decorators.http as http_dec
from django import http
from django.utils.safestring import mark_safe
from django.db import transaction
from django.utils import six
from django.utils.translation import (
        ugettext_lazy as _,
        ugettext,
        string_concat,
        pgettext,
        pgettext_lazy,
        )
from django.utils.functional import lazy
from django.contrib.auth.decorators import login_required

from django_select2.forms import Select2Widget

mark_safe_lazy = lazy(mark_safe, six.text_type)

from django.views.decorators.cache import cache_control

from crispy_forms.layout import Submit, Layout, Div

from relate.utils import StyledForm
from bootstrap3_datetime.widgets import DateTimePicker

from course.auth import get_role_and_participation
from course.constants import (
        participation_role,
        participation_status,
        FLOW_PERMISSION_CHOICES,
        )
from course.models import (
        Course,
        InstantFlowRequest,
        Participation,
        FlowSession,
        FlowRuleException)

from course.content import get_course_repo
from course.utils import course_view, render_course_page


NONE_SESSION_TAG = "<<<NONE>>>"  # noqa


# {{{ home

def home(request):
    now_datetime = get_now_or_fake_time(request)

    current_courses = []
    past_courses = []
    for course in Course.objects.filter(listed=True):
        role, participation = get_role_and_participation(request, course)

        show = True
        if course.hidden:
            if role not in [participation_role.teaching_assistant,
                    participation_role.instructor]:
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

def check_course_state(course, role):
    """
    Check to see if the course is hidden.

    If hidden, only allow access to 'ta' and 'instructor' roles
    """
    if course.hidden:
        if role not in [participation_role.teaching_assistant,
                        participation_role.instructor]:
            raise PermissionDenied(_("only course staff have access"))


@course_view
def course_page(pctx):
    from course.content import get_processed_page_chunks, get_course_desc
    page_desc = get_course_desc(pctx.repo, pctx.course, pctx.course_commit_sha)

    chunks = get_processed_page_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, page_desc,
            pctx.role, get_now_or_fake_time(pctx.request),
            facilities=pctx.request.relate_facilities)

    show_enroll_button = (
            pctx.course.accepts_enrollment
            and pctx.role == participation_role.unenrolled)

    if pctx.request.user.is_authenticated() and Participation.objects.filter(
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
                from django.core.urlresolvers import reverse
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
def static_page(pctx, page_path):
    from course.content import get_staticpage_desc, get_processed_page_chunks
    try:
        page_desc = get_staticpage_desc(pctx.repo, pctx.course,
                pctx.course_commit_sha, "staticpages/"+page_path+".yml")
    except ObjectDoesNotExist:
        raise http.Http404()

    chunks = get_processed_page_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, page_desc,
            pctx.role, get_now_or_fake_time(pctx.request),
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

    role, participation = get_role_and_participation(request, course)

    repo = get_course_repo(course)
    return get_repo_file_response(repo, "media/" + media_path, commit_sha.encode())


def repo_file_etag_func(request, course_identifier, commit_sha, path):
    return ":".join([course_identifier, commit_sha, path])


@cache_control(max_age=3600*24*31)  # cache for a month
@http_dec.condition(etag_func=repo_file_etag_func)
def get_repo_file(request, course_identifier, commit_sha, path):
    commit_sha = commit_sha.encode()

    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)

    return get_repo_file_backend(
            request, course, role, participation, commit_sha, path)


def current_repo_file_etag_func(request, course_identifier, path):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(
            request, course)

    from course.views import check_course_state
    check_course_state(course, role)

    from course.content import get_course_commit_sha
    commit_sha = get_course_commit_sha(course, participation)

    return ":".join([course_identifier, commit_sha.decode(), path])


@http_dec.condition(etag_func=current_repo_file_etag_func)
def get_current_repo_file(request, course_identifier, path):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(
            request, course)

    from course.content import get_course_commit_sha
    commit_sha = get_course_commit_sha(course, participation)

    return get_repo_file_backend(
            request, course, role, participation, commit_sha, path)


def get_repo_file_backend(request, course, role, participation,
                          commit_sha, path):
    """
    Check if a file should be accessible.  Then call for it if
    the permission is not denied.

    Order is important here.  An in-exam request takes precedence.

    Note: an access_role of "public" is equal to "unenrolled"
    """

    # check to see if the course is hidden
    from course.views import check_course_state
    check_course_state(course, role)

    # retrieve local path for the repo for the course
    repo = get_course_repo(course)

    # set access to public (or unenrolled), student, etc
    access_kind = role
    if request.relate_exam_lockdown:
        access_kind = "in_exam"

    from course.content import is_repo_file_accessible_as
    if not is_repo_file_accessible_as(access_kind, repo, commit_sha, path):
        raise PermissionDenied()

    return get_repo_file_response(repo, path, commit_sha)


def get_repo_file_response(repo, path, commit_sha):
    from course.content import get_repo_blob_data_cached

    try:
        data = get_repo_blob_data_cached(repo, path, commit_sha)
    except ObjectDoesNotExist:
        raise http.Http404()

    from mimetypes import guess_type
    content_type, _ = guess_type(path)

    if content_type is None:
        content_type = "application/octet-stream"

    return http.HttpResponse(data, content_type=content_type)

# }}}


# {{{ time travel

class FakeTimeForm(StyledForm):
    time = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
            label=_('Time'))

    def __init__(self, *args, **kwargs):
        super(FakeTimeForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                # Translators: "set" fake time.
                Submit("set", _("Set")))
        self.helper.add_input(
                # Translators: "unset" fake time.
                Submit("unset", _("Unset")))


def get_fake_time(request):
    if "relate_fake_time" in request.session:
        import datetime

        from django.conf import settings
        from pytz import timezone
        tz = timezone(settings.TIME_ZONE)
        return tz.localize(
                datetime.datetime.fromtimestamp(
                    request.session["relate_fake_time"]))
    else:
        return None


def get_now_or_fake_time(request):
    fake_time = get_fake_time(request)
    if fake_time is None:
        from django.utils.timezone import now
        return now()
    else:
        return fake_time


def set_fake_time(request):
    if not request.user.is_staff:
        raise PermissionDenied(_("only staff may set fake time"))

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
        from django.conf import settings

        super(FakeFacilityForm, self).__init__(*args, **kwargs)

        self.fields["facilities"] = forms.MultipleChoiceField(
                choices=(
                    (name, name)
                    for name in settings.RELATE_FACILITIES),
                widget=forms.CheckboxSelectMultiple,
                required=False,
                label=_("Facilities"),
                help_text=_("Facilities you wish to pretend to be in"))

        self.fields["custom_facilities"] = forms.CharField(
                label=_("Custom facilities"),
                required=False,
                help_text=_("More (non-predefined) facility names, separated "
                    "by commas, which would like to pretend to be in"))

        self.helper.add_input(
                # Translators: "set" fake facility.
                Submit("set", _("Set")))
        self.helper.add_input(
                # Translators: "unset" fake facility.
                Submit("unset", _("Unset")))


def set_pretend_facilities(request):
    if not request.user.is_staff:
        raise PermissionDenied(_("only staff may set fake facility"))

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
            else:
                request.session.pop("relate_pretend_facilities", None)

    else:
        if "relate_pretend_facilities" in request.session:
            form = FakeFacilityForm({
                "facilities": [],
                "custom_facilities": ",".join(
                    request.session["relate_pretend_facilities"])
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
            }

# }}}


# {{{ instant flow requests

class InstantFlowRequestForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super(InstantFlowRequestForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"))
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
    if pctx.role != participation_role.instructor:
        raise PermissionDenied(
                _("must be instructor to manage instant flow requests"))

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

            elif op == "cancel":
                (InstantFlowRequest.objects
                        .filter(
                            course=pctx.course,
                            start_time__lte=now_datetime,
                            end_time__gte=now_datetime,
                            cancelled=False)
                        .order_by("start_time")
                        .update(cancelled=True))
            else:
                raise SuspiciousOperation(_("invalid operation"))

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
        super(FlowTestForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"))

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
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(_("must be instructor or TA to test flows"))

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
        super(ExceptionStage1Form, self).__init__(*args, **kwargs)

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
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(
                _("must be instructor or TA to grant exceptions"))

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


def strify_session_for_exception(session):
    from relate.utils import as_local_time, format_datetime_local
    # Translators: %s is the string of the start time of a session.
    result = (_("started at %s") % format_datetime_local(
        as_local_time(session.start_time)))

    if session.access_rules_tag:
        result += " tagged '%s'" % session.access_rules_tag

    return result


class CreateSessionForm(StyledForm):
    def __init__(self, session_tag_choices, default_tag, create_session_is_override,
            *args, **kwargs):
        super(CreateSessionForm, self).__init__(*args, **kwargs)

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
    def __init__(self, sessions, *args, **kwargs):
        super(ExceptionStage2Form, self).__init__(*args, **kwargs)

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
def grant_exception_stage_2(pctx, participation_id, flow_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(
                _("must be instructor or TA to grant exceptions"))

    # {{{ get flow data

    participation = get_object_or_404(Participation, id=participation_id)

    form_text = (
            string_concat(
                "<div class='well'>",
                ugettext("Granting exception to '%(participation)s' for "
                "'%(flow_id)s'."),
                "</div>")
            % {
                'participation': participation,
                'flow_id': flow_id})

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

    NONE_SESSION_TAG = string_concat("<<<", _("NONE"), ">>>")  # noqa
    session_tag_choices = [
            (tag, tag)
            for tag in access_rules_tags] + [(NONE_SESSION_TAG,
                    string_concat("(", _("NONE"), ")"))]

    from course.utils import get_session_start_rule
    session_start_rule = get_session_start_rule(pctx.course, participation,
            participation.role, flow_id, flow_desc, now_datetime)

    create_session_is_override = False
    if not session_start_rule.may_start_new_session:
        create_session_is_override = True
        form_text += ("<div class='alert alert-info'>%s</div>" % (
            string_concat(
                "<i class='fa fa-info-circle'></i> ",
                _("Creating a new session is (technically) not allowed "
                "by course rules. Clicking 'Create Session' anyway will "
                "override this rule."))))

    default_tag = session_start_rule.tag_session
    if default_tag is None:
        default_tag = NONE_SESSION_TAG

    # }}}

    def find_sessions():
        return (FlowSession.objects
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

            start_flow(pctx.repo, pctx.course, participation,
                    user=participation.user,
                    flow_id=flow_id,
                    flow_desc=flow_desc,
                    access_rules_tag=access_rules_tag,
                    now_datetime=now_datetime)

            exception_form = None

        elif exception_form.is_valid() and "next" in request.POST:
            return redirect(
                    "relate-grant_exception_stage_3",
                    pctx.course.identifier,
                    participation.id,
                    flow_id,
                    exception_form.cleaned_data["session"])
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
    access_expires = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True,
                    "showClear": True}),
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

    def __init__(self, default_data, flow_desc, base_session_tag, *args, **kwargs):
        super(ExceptionStage3Form, self).__init__(*args, **kwargs)

        rules = getattr(flow_desc, "rules", object())
        tags = getattr(rules, "tags", [])

        layout = [Div("access_expires", css_class="well")]
        if tags:
            tags = [NONE_SESSION_TAG] + tags
            self.fields["set_access_rules_tag"] = forms.ChoiceField(
                    [(tag, tag) for tag in tags],
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
                        css_class="well"))

        permission_ids = []
        for key, name in FLOW_PERMISSION_CHOICES:
            self.fields[key] = forms.BooleanField(label=name, required=False,
                    initial=default_data.get(key) or False)

            permission_ids.append(key)

        layout.append(Div(*permission_ids, css_class="well"))

        self.fields["due_same_as_access_expiration"] = forms.BooleanField(
                required=False, help_text=_("If set, the 'Due' field will be "
                "disregarded."),
                initial=default_data.get("due_same_as_access_expiration") or False,
                label=_("Due same as access expiration"))
        self.fields["due"] = forms.DateTimeField(
                widget=DateTimePicker(
                    options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
                required=False,
                help_text=_("The due time shown to the student. Also, the "
                "time after which "
                "any session under these rules is subject to expiration."),
                initial=default_data.get("due"),
                label=_("Due time"))

        self.fields["credit_percent"] = forms.IntegerField(required=False,
                initial=default_data.get("credit_percent"),
                label=_("Credit percent"))
        layout.append(Div("due_same_as_access_expiration", "due", "credit_percent",
            css_class="well"))

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
        if (self.cleaned_data["access_expires"] is None
                and self.cleaned_data["due_same_as_access_expiration"]):
            from django.core.exceptions import ValidationError
            raise ValidationError(
                    _("Must specify access expiration if 'due same "
                    "as access expiration' is set."))


@course_view
@transaction.atomic
def grant_exception_stage_3(pctx, participation_id, flow_id, session_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(
                ugettext("must be instructor or TA to grant exceptions"))

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
    access_rule = get_session_access_rule(
            session, participation.role, flow_desc, now_datetime)
    grading_rule = get_session_grading_rule(
            session, participation.role, flow_desc, now_datetime)

    request = pctx.request
    if request.method == "POST":
        form = ExceptionStage3Form(
                {}, flow_desc, session.access_rules_tag, request.POST)

        from course.constants import flow_rule_kind

        if form.is_valid():
            permissions = [
                    key
                    for key, _ in FLOW_PERMISSION_CHOICES
                    if form.cleaned_data[key]]

            from course.validation import (
                    validate_session_access_rule,
                    validate_session_grading_rule,
                    ValidationContext)
            from relate.utils import dict_to_struct
            vctx = ValidationContext(
                    repo=pctx.repo,
                    commit_sha=pctx.course_commit_sha)

            from course.content import get_flow_desc
            flow_desc = get_flow_desc(pctx.repo,
                    pctx.course,
                    flow_id, pctx.course_commit_sha)
            tags = None
            if hasattr(flow_desc, "rules"):
                tags = getattr(flow_desc.rules, "tags", None)

            # {{{ put together access rule

            new_access_rule = {"permissions": permissions}

            if (form.cleaned_data.get("restrict_to_same_tag")
                    and session.access_rules_tag is not None):
                new_access_rule["if_has_tag"] = session.access_rules_tag

            validate_session_access_rule(
                    vctx, ugettext("newly created exception"),
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

            # }}}

            new_access_rules_tag = form.cleaned_data.get("set_access_rules_tag")
            if new_access_rules_tag == NONE_SESSION_TAG:
                new_access_rules_tag = None

            if session.access_rules_tag != new_access_rules_tag:
                session.access_rules_tag = new_access_rules_tag
                session.save()

            # {{{ put together grading rule

            due = form.cleaned_data["due"]
            if form.cleaned_data["due_same_as_access_expiration"]:
                due = form.cleaned_data["access_expires"]

            descr = ugettext("Granted excecption")
            if form.cleaned_data["credit_percent"] is not None:
                descr += string_concat(" (%.1f%% ", ugettext('credit'), ")") \
                        % form.cleaned_data["credit_percent"]

            due_local_naive = due
            if due_local_naive is not None:
                from relate.utils import as_local_time
                due_local_naive = as_local_time(due_local_naive).replace(tzinfo=None)

            new_grading_rule = {
                "description": descr,
                }

            if due_local_naive is not None:
                new_grading_rule["due"] = due_local_naive
                new_grading_rule["if_completed_before"] = due_local_naive

            if form.cleaned_data["credit_percent"] is not None:
                new_grading_rule["credit_percent"] = \
                        form.cleaned_data["credit_percent"]

            if (form.cleaned_data.get("restrict_to_same_tag")
                    and session.access_rules_tag is not None):
                new_grading_rule["if_has_tag"] = session.access_rules_tag

            if hasattr(grading_rule, "generates_grade"):
                new_grading_rule["generates_grade"] = \
                        grading_rule.generates_grade

            validate_session_grading_rule(vctx, ugettext("newly created exception"),
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

            # }}}

            messages.add_message(pctx.request, messages.SUCCESS,
                    ugettext(
                        "Exception granted to '%(participation)s' "
                        "for '%(flow_id)s'.")
                    % {
                        'participation': participation,
                        'flow_id': flow_id})
            return redirect(
                    "relate-grant_exception",
                    pctx.course.identifier)

    else:
        data = {
                "restrict_to_same_tag": session.access_rules_tag is not None,
                "credit_percent": grading_rule.credit_percent,
                #"due_same_as_access_expiration": True,
                "due": grading_rule.due,
                }
        for perm in access_rule.permissions:
            data[perm] = True

        form = ExceptionStage3Form(data, flow_desc, session.access_rules_tag)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": ugettext("Grant Exception"),
        "form_text": string_concat(
            "<div class='well'>",
            ugettext("Granting exception to '%(participation)s' "
            "for '%(flow_id)s' (session %(session)s)."),
            "</div>")
        % {
            'participation': participation,
            'flow_id': flow_id,
            'session': strify_session_for_exception(session)},
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

    import six
    prv_bio = six.StringIO()
    prv.write_private_key(prv_bio)

    prv_bio_read = six.StringIO(prv_bio.getvalue())

    pub = key_class.from_private_key(prv_bio_read)

    pub_bio = six.StringIO()
    pub_bio.write("%s %s relate-course-key" % (pub.get_name(), pub.get_base64()))

    return render(request, "course/keypair.html", {
        "public_key": prv_bio.getvalue(),
        "private_key": pub_bio.getvalue(),
        })

# }}}


# {{{ celery task monitoring

def monitor_task(request, task_id):
    from celery.result import AsyncResult
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

    if async_res.state == "SUCCESS":
        if (isinstance(async_res.result, dict)
                and "message" in async_res.result):
            progress_statement = async_res.result["message"]

    traceback = None
    if request.user.is_staff and async_res.state == "FAILURE":
        traceback = async_res.traceback

    return render(request, "course/task-monitor.html", {
        "state": async_res.state,
        "progress_percent": progress_percent,
        "progress_statement": progress_statement,
        "traceback": traceback,
        })

# }}}


# vim: foldmethod=marker
