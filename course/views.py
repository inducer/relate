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
        ugettext_lazy as _ ,
        ugettext,
        string_concat,
        pgettext,
        pgettext_lazy,
        )
from django.utils.functional import lazy

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

from course.content import (get_course_repo, get_course_desc)
from course.utils import course_view, render_course_page


NONE_SESSION_TAG = "<<<NONE>>>"  # noqa


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
            raise PermissionDenied(_("only course staff have access"))
    elif not course.valid:
        if role != participation_role.instructor:
            raise PermissionDenied(_("only the instructor has access"))


@course_view
def course_page(pctx):
    from course.content import get_processed_course_chunks
    chunks = get_processed_course_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, pctx.course_desc,
            pctx.role, get_now_or_fake_time(pctx.request),
            remote_address=pctx.remote_address)

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

    return render_course_page(pctx, "course/course-page.html", {
        "chunks": chunks,
        "show_enroll_button": show_enroll_button,
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


def repo_file_etag_func(request, course_identifier, commit_sha, path):
    return ":".join([course_identifier, commit_sha, path])


@cache_control(max_age=3600*24*31)  # cache for a month
@http_dec.condition(etag_func=repo_file_etag_func)
def get_repo_file(request, course_identifier, commit_sha, path):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)

    repo = get_course_repo(course)

    from course.content import is_repo_file_public
    if not is_repo_file_public(repo, commit_sha, path):
        raise PermissionDenied()

    from course.content import get_repo_blob_data_cached

    try:
        data = get_repo_blob_data_cached(
                repo, path, commit_sha.encode())
    except ObjectDoesNotExist:
        raise http.Http404()

    from mimetypes import guess_type
    content_type = guess_type(path)

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
                Submit("set", _("Set"), css_class="col-lg-offset-2"))
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


# {{{ instant flow requests

class InstantFlowRequestForm(StyledForm):
    def __init__(self, flow_ids, *args, **kwargs):
        super(InstantFlowRequestForm, self).__init__(*args, **kwargs)

        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"))
        self.fields["duration_in_minutes"] = forms.IntegerField(
                required=True, initial=20, label=pgettext_lazy("duration for instant flow","Duration in minutes"))

        self.helper.add_input(
                Submit("add", pgettext("add an instant flow","Add"), css_class="col-lg-offset-2"))
        self.helper.add_input(
                Submit("cancel", pgettext("cancel all instant flow(s)","Cancel all")))


@course_view
def manage_instant_flow_requests(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied(_("must be instructor to manage instant flow requests"))

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
                Submit("test", mark_safe_lazy(string_concat(pgettext("Start an activity", "Go"), " &raquo;")), css_class="col-lg-offset-2"))


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
                help_text=_("Select participant for whom exception is to be granted."),
                label=_("Participant"))
        self.fields["flow_id"] = forms.ChoiceField(
                choices=[(fid, fid) for fid in flow_ids],
                required=True,
                label=_("Flow ID"))

        self.helper.add_input(
                Submit(
                    "next", mark_safe_lazy(string_concat(pgettext("Next step", "Next"), " &raquo;")),
                    css_class="col-lg-offset-2"))


@course_view
def grant_exception(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(_("must be instructor or TA to grant exceptions"))

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
    from relate.utils import as_local_time
    # Translators: %s is the string of the start time of a session.
    result = (_("started at %s") % as_local_time(session.start_time)
            .strftime('%b %d %Y - %I:%M %p'))

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
                    Submit("create_session", _("Create session (override rules)"),
                        css_class="btn-danger col-lg-offset-2"))
        else:
            self.helper.add_input(
                    Submit("create_session", _("Create session"),
                        css_class="col-lg-offset-2"))


class ExceptionStage2Form(StyledForm):
    def __init__(self, sessions, *args, **kwargs):
        super(ExceptionStage2Form, self).__init__(*args, **kwargs)

        self.fields["session"] = forms.ChoiceField(
                choices=(
                    (session.id, strify_session_for_exception(session))
                    for session in sessions),
                help_text=_("The rules that currently apply to selected session "
                "will provide the default values for the rules on the next page."),
                label=_("Session"))

        self.helper.add_input(Submit("next", mark_safe_lazy(string_concat(pgettext("Next step", "Next"), " &raquo;")),
                    css_class="col-lg-offset-2"))


@course_view
def grant_exception_stage_2(pctx, participation_id, flow_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(_("must be instructor or TA to grant exceptions"))

    # {{{ get flow data

    participation = get_object_or_404(Participation, id=participation_id)

    form_text = (string_concat("<div class='well'>", ugettext("Granting exception to '%(participation)s' for '%(flow_id)s'."), "</div>")
        % {'participation':participation, 'flow_id':flow_id})

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

    NONE_SESSION_TAG = string_concat("<<<",_("NONE"), ">>>")
    session_tag_choices = [
            (tag, tag)
            for tag in access_rules_tags] + [(NONE_SESSION_TAG, string_concat("(",_("NONE"), ")"))]

    from course.utils import get_session_start_rule
    session_start_rule = get_session_start_rule(pctx.course, participation,
            participation.role, flow_id, flow_desc, now_datetime)

    create_session_is_override = False
    if not session_start_rule.may_start_new_session:
        create_session_is_override = True
        form_text += ("<div class='alert alert-info'>%s</div>"
            % _("Creating a new session is (technically) not allowed by course "
                "rules. Clicking 'Create Session' anyway will override this rule."))

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

            start_flow(pctx.repo, pctx.course, participation, flow_id,
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
            label=pgettext_lazy("time when access expires","Access expires"),
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
                    label=_("Exception only applies to sessions with the above tag"),
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
                    "save", _("Save"),
                    css_class="col-lg-offset-2"))

        self.helper.layout = Layout(*layout)

    def clean(self):
        if (self.cleaned_data["access_expires"] is None
                and self.cleaned_data["due_same_as_access_expiration"]):
            from django.core.exceptions import ValidationError
            raise ValidationError(_("Must specify access expiration if 'due same "
                    "as access expiration' is set."))


@course_view
@transaction.atomic
def grant_exception_stage_3(pctx, participation_id, flow_id, session_id):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(_("must be instructor or TA to grant exceptions"))

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

            validate_session_access_rule(vctx, ugettext("newly created exception"),
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

            new_access_rules_tag = form.cleaned_data["set_access_rules_tag"]
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
                descr += " (%.1f%% credit)" % form.cleaned_data["credit_percent"]

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

            if (hasattr(grading_rule, "grade_identifier")
                    and grading_rule.grade_identifier is not None):
                new_grading_rule["grade_identifier"] = \
                        grading_rule.grade_identifier
            else:
                new_grading_rule["grade_identifier"] = None

            if (hasattr(grading_rule, "grade_aggregation_strategy")
                    and grading_rule.grade_aggregation_strategy is not None):
                new_grading_rule["grade_aggregation_strategy"] = \
                        grading_rule.grade_aggregation_strategy

            validate_session_grading_rule(vctx, ugettext("newly created exception"),
                    dict_to_struct(new_grading_rule), tags)

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
                    ugettext("Exception granted to '%(participation)s' for '%(flow_id)s'.") % {'participation':participation, 'flow_id':flow_id})
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
        "form_text": string_concat("<div class='well'>", ugettext("Granting exception to '%(participation)s' for '%(flow_id)s' (session %(session)s)."), "</div>")
        % {'participation':participation, 'flow_id':flow_id, 'session': strify_session_for_exception(session)},
    })

# }}}


# vim: foldmethod=marker
