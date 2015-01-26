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

from django.views.decorators.cache import cache_control

from crispy_forms.layout import Submit

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

from course.content import (get_course_repo, get_course_desc)
from course.utils import course_view, render_course_page


# {{{ home

def home(request):
    courses_and_descs_and_invalid_flags = []
    for course in Course.objects.filter(listed=True):
        repo = get_course_repo(course)
        desc = get_course_desc(repo, course, course.active_git_commit_sha.encode())

        role, participation = get_role_and_participation(request, course)

        show = True
        if course.hidden:
            if role not in [participation_role.teaching_assistant,
                    participation_role.instructor]:
                show = False

        if not course.valid:
            if role != participation_role.instructor:
                show = False

        if show:
            courses_and_descs_and_invalid_flags.append(
                    (course, desc, not course.valid))

    def course_sort_key(entry):
        course, desc, invalid_flag = entry
        return course.identifier

    courses_and_descs_and_invalid_flags.sort(key=course_sort_key)

    return render(request, "course/home.html", {
        "courses_and_descs_and_invalid_flags": courses_and_descs_and_invalid_flags
        })

# }}}


def maintenance(request):
    return render(request, "maintenance.html")


# {{{ course page

def check_course_state(course, role):
    if course.hidden:
        if role not in [participation_role.teaching_assistant,
                participation_role.instructor]:
            raise PermissionDenied("only course staff have access")
    elif not course.valid:
        if role != participation_role.instructor:
            raise PermissionDenied("only the instructor has access")


@course_view
def course_page(pctx):
    from course.content import get_processed_course_chunks
    chunks = get_processed_course_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, pctx.course_desc,
            pctx.role, get_now_or_fake_time(pctx.request))

    return render_course_page(pctx, "course/course-page.html", {
        "chunks": chunks,
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

    from course.content import get_repo_blob_data_cached
    try:
        data = get_repo_blob_data_cached(
                repo, "media/"+media_path, commit_sha.encode())
    except ObjectDoesNotExist:
        raise http.Http404()

    from mimetypes import guess_type
    content_type = guess_type(media_path)

    return http.HttpResponse(data, content_type=content_type)

# }}}


# {{{ time travel

class FakeTimeForm(StyledForm):
    time = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "pickSeconds": False}))

    def __init__(self, *args, **kwargs):
        super(FakeTimeForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("set", "Set", css_class="col-lg-offset-2"))
        self.helper.add_input(
                Submit("unset", "Unset"))


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
        raise PermissionDenied("only staff may set fake time")

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
        "form_description": "Set fake time",
    })


def fake_time_context_processor(request):
    return {
            "fake_time": get_fake_time(request),
            }

# }}}


# {{{ instant flow requests

class InstantFlowRequestForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super(InstantFlowRequestForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True)
        self.fields["duration_in_minutes"] = forms.IntegerField(
                required=True, initial=20)

        self.helper.add_input(
                Submit("add", "Add", css_class="col-lg-offset-2"))
        self.helper.add_input(
                Submit("cancel", "Cancel all"))


@course_view
def manage_instant_flow_requests(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied("must be instructor to manage instant flow requests")

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
            raise SuspiciousOperation("invalid operation")

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
                raise SuspiciousOperation("invalid operation")

    else:
        form = InstantFlowRequestForm(flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Manage Instant Flow Requests",
    })

# }}}


# {{{ test flow

class FlowTestForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super(FlowTestForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True)

        self.helper.add_input(
                Submit("test", mark_safe("Go &raquo;"), css_class="col-lg-offset-2"))


@course_view
def test_flow(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to test flows")

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = FlowTestForm(flow_ids, request.POST, request.FILES)
        if "test" not in request.POST:
            raise SuspiciousOperation("invalid operation")

        if form.is_valid():
            return redirect("course.flow.start_flow",
                    pctx.course.identifier,
                    form.cleaned_data["flow_id"])

    else:
        form = FlowTestForm(flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Test Flow",
    })

# }}}


# {{{ flow access exceptions

class ParticipationChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        user = obj.user
        return "%s - %s, %s" % (user.email, user.last_name, user.first_name)


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
                help_text="Select participant for whom exception is to be granted.")
        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True)

        self.helper.add_input(
                Submit(
                    "next", mark_safe("Next &raquo;"),
                    css_class="col-lg-offset-2"))


@course_view
def grant_exception(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to grant exceptions")

    from course.content import list_flow_ids
    flow_ids = list_flow_ids(pctx.repo, pctx.course_commit_sha)

    request = pctx.request
    if request.method == "POST":
        form = ExceptionStage1Form(pctx.course, flow_ids, request.POST)

        if form.is_valid():
            return redirect("course.views.grant_exception_stage_2",
                    pctx.course.identifier,
                    form.cleaned_data["participation"].id,
                    form.cleaned_data["flow_id"])

    else:
        form = ExceptionStage1Form(pctx.course, flow_ids)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Grant Exception",
    })


def strify_session_for_exception(session):
    from relate.utils import as_local_time
    result = ("started at %s" % as_local_time(session.start_time)
            .strftime('%b %d %Y - %I:%M %p'))

    if session.access_rules_tag:
        result += " tagged '%s'" % session.access_rules_tag

    return result


class ExceptionStage2Form(StyledForm):
    def __init__(self, sessions, *args, **kwargs):
        super(ExceptionStage2Form, self).__init__(*args, **kwargs)

        self.fields["session"] = forms.ChoiceField(
                choices=(
                    (session.id, strify_session_for_exception(session))
                    for session in sessions),
                help_text="Select the session on which the exception "
                "should be based.")

        self.helper.add_input(
                Submit(
                    "next", mark_safe("Next &raquo;"),
                    css_class="col-lg-offset-2"))


@course_view
def grant_exception_stage_2(pctx, participation_id, flow_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to grant exceptions")

    participation = get_object_or_404(Participation, id=participation_id)

    sessions = (FlowSession.objects
            .filter(
                participation=pctx.participation,
                flow_id=flow_id)
           .order_by("start_time"))

    request = pctx.request
    if request.method == "POST":
        form = ExceptionStage2Form(sessions, request.POST)

        if form.is_valid():
            return redirect(
                    "course.views.grant_exception_stage_3",
                    pctx.course.identifier,
                    participation.id,
                    flow_id,
                    form.cleaned_data["session"])

    else:
        form = ExceptionStage2Form(sessions)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Grant Exception",
    })


class ExceptionStage3Form(StyledForm):
    access_expires = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "pickSeconds": False}),
            required=False)

    def __init__(self, *args, **kwargs):
        super(ExceptionStage3Form, self).__init__(*args, **kwargs)

        for key, name in FLOW_PERMISSION_CHOICES:
            self.fields[key] = forms.BooleanField(label=name, required=False)

        self.fields["due"] = forms.DateTimeField(
                widget=DateTimePicker(
                    options={"format": "YYYY-MM-DD HH:mm", "pickSeconds": False}),
                required=False)

        self.fields["credit_percent"] = forms.IntegerField(required=False)

        self.fields["comment"] = forms.CharField(
                widget=forms.Textarea, required=True)

        self.helper.add_input(
                Submit(
                    "save", "Save",
                    css_class="col-lg-offset-2"))


@course_view
@transaction.atomic
def grant_exception_stage_3(pctx, participation_id, flow_id, session_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied("must be instructor or TA to grant exceptions")

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
            session, pctx.role, flow_desc, now_datetime)
    grading_rule = get_session_grading_rule(
            session, pctx.role, flow_desc, now_datetime)

    request = pctx.request
    if request.method == "POST":
        form = ExceptionStage3Form(request.POST)

        from course.constants import flow_rule_kind

        if form.is_valid():
            permissions = [
                    key
                    for key, _ in FLOW_PERMISSION_CHOICES
                    if form.cleaned_data[key]]

            fre_access = FlowRuleException(
                flow_id=flow_id,
                participation=participation,
                expiration=form.cleaned_data["access_expires"],
                creator=pctx.request.user,
                comment=form.cleaned_data["comment"],
                kind=flow_rule_kind.access,
                rule={"permissions": permissions})
            fre_access.save()

            fre_grading = FlowRuleException(
                flow_id=flow_id,
                participation=participation,
                creator=pctx.request.user,
                comment=form.cleaned_data["comment"],
                kind=flow_rule_kind.grading,
                rule={
                    "credit_percent": form.cleaned_data["credit_percent"],
                    "due": form.cleaned_data["due"],
                    "description": "Exception",
                    })
            fre_grading.save()

            messages.add_message(pctx.request, messages.SUCCESS,
                    "Exception granted.")
            return redirect(
                    "course.views.grant_exception",
                    pctx.course.identifier)

    else:
        data = {
                "credit_percent": grading_rule.credit_percent,
                "due": grading_rule.due,
                }
        for perm in access_rule.permissions:
            data[perm] = True

        form = ExceptionStage3Form(data)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Grant Exception",
        "form_text": "<div class='well'>Granting exception to '%s' for '%s'.</div>"
        % (participation, flow_id),
    })

# }}}


# vim: foldmethod=marker
