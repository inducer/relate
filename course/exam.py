# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2015 Andreas Kloeckner"

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

import six

from django.contrib.auth import get_user_model
import django.forms as forms
from django.utils.translation import (
        ugettext, ugettext_lazy as _, string_concat,
        pgettext)
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.core.exceptions import (  # noqa
        PermissionDenied, ObjectDoesNotExist, SuspiciousOperation)
from django.contrib import messages  # noqa
from django.contrib.auth.decorators import permission_required
from django import http  # noqa
from django.db import transaction
from django.db.models import Q
from django.urls import reverse

from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect

from crispy_forms.layout import Submit
from bootstrap3_datetime.widgets import DateTimePicker

from course.models import (Exam, ExamTicket, Participation,
        FlowSession)
from course.utils import course_view, render_course_page
from course.constants import (
        exam_ticket_states,
        participation_status,
        participation_permission as pperm)
from course.views import get_now_or_fake_time

from relate.utils import StyledForm


# {{{ mypy

if False:
    import datetime  # noqa
    from typing import Optional, Text, Tuple, FrozenSet  # noqa

# }}}


ticket_alphabet = "ABCDEFGHJKLPQRSTUVWXYZabcdefghjkpqrstuvwxyz23456789"


def gen_ticket_code():
    from random import choice
    return "".join(choice(ticket_alphabet) for i in range(8))


# {{{ issue ticket

class IssueTicketForm(StyledForm):
    def __init__(self, now_datetime, *args, **kwargs):
        initial_exam = kwargs.pop("initial_exam", None)

        super(IssueTicketForm, self).__init__(*args, **kwargs)

        from course.auth import UserSearchWidget

        self.fields["user"] = forms.ModelChoiceField(
                queryset=(get_user_model().objects
                    .filter(is_active=True)
                    .order_by("last_name")),
                widget=UserSearchWidget(),
                required=True,
                help_text=_("Select participant for whom ticket is to "
                "be issued."),
                label=_("Participant"))
        self.fields["exam"] = forms.ModelChoiceField(
                queryset=(
                    Exam.objects
                    .filter(
                        Q(active=True)
                        & (
                            Q(no_exams_after__isnull=True)
                            | Q(no_exams_after__gt=now_datetime)
                            ))
                    .order_by("no_exams_before")
                    ),
                required=True,
                initial=initial_exam,
                label=_("Exam"))

        self.fields["valid_start_time"] = forms.DateTimeField(
                label=_("Start validity"),
                widget=DateTimePicker(
                    options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
                required=False)
        self.fields["valid_end_time"] = forms.DateTimeField(
                label=_("End validity"),
                widget=DateTimePicker(
                    options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
                required=False)
        self.fields["restrict_to_facility"] = forms.CharField(
                label=_("Restrict to facility"),
                help_text=_("If not blank, the exam ticket may only be used in the "
                    "given facility"),
                required=False)

        self.fields["revoke_prior"] = forms.BooleanField(
                label=_("Revoke prior exam tickets for this user"),
                required=False,
                initial=True)

        self.helper.add_input(
                Submit(
                    "issue",
                    _("Issue ticket")))


@permission_required("course.can_issue_exam_tickets")
def issue_exam_ticket(request):
    now_datetime = get_now_or_fake_time(request)

    if request.method == "POST":
        form = IssueTicketForm(now_datetime, request.POST)

        if form.is_valid():
            exam = form.cleaned_data["exam"]
            try:
                participation = Participation.objects.get(
                                course=exam.course,
                                user=form.cleaned_data["user"],
                                status=participation_status.active,
                                )

            except ObjectDoesNotExist:
                messages.add_message(request, messages.ERROR,
                        _("User is not enrolled in course."))
                participation = None

            if participation is not None:
                if form.cleaned_data["revoke_prior"]:
                    ExamTicket.objects.filter(
                            exam=exam,
                            participation=participation,
                            state__in=(
                                exam_ticket_states.valid,
                                exam_ticket_states.used,
                                )
                            ).update(state=exam_ticket_states.revoked)

                ticket = ExamTicket()
                ticket.exam = exam
                ticket.participation = participation
                ticket.creator = request.user
                ticket.state = exam_ticket_states.valid
                ticket.code = gen_ticket_code()
                ticket.valid_start_time = form.cleaned_data["valid_start_time"]
                ticket.valid_end_time = form.cleaned_data["valid_end_time"]
                ticket.restrict_to_facility = \
                        form.cleaned_data["restrict_to_facility"]
                ticket.save()

                messages.add_message(request, messages.SUCCESS,
                        _(
                            "Ticket issued for <b>%(participation)s</b>. "
                            "The ticket code is <b>%(ticket_code)s</b>."
                            ) % {"participation": participation,
                                 "ticket_code": ticket.code})

                form = IssueTicketForm(now_datetime, initial_exam=exam)

    else:
        form = IssueTicketForm(now_datetime)

    return render(request, "generic-form.html", {
        "form_description":
            _("Issue Exam Ticket"),
        "form": form,
        })

# }}}


# {{{ batch-issue tickets

INITIAL_EXAM_TICKET_TEMPLATE = string_concat("""\
# """, _("List"), """

<table class="table">
  <thead>
    <tr>
      <th>""", _("User"), "</th><th>",
        pgettext("real name of a user", "Name"), "</th><th>",
        pgettext("ticket code required to login exam", "Code"), """</th>
    </tr>
  </thead>

  {% for ticket in tickets %}
    <tr>
      <td>
        {{ ticket.participation.user.username }}
      </td>
      <td>
        {{ ticket.participation.user.get_full_name }}
      </td>
      <td>
        {{ ticket.code }}
      </td>
    </tr>
  {% endfor %}
</table>

----------------

{% for ticket in tickets %}
<h2 style="page-break-before: always">""",
_("Instructions for "  # noqa
  "{{ ticket.exam.description }}"), """
</h2>

""", _("These are personalized instructions for "
"{{ ticket.participation.user.get_full_name }}."), """

""", _("If this is not you, please let the proctor know "
"so that you can get the correct set of instructions."), """

""", _("Please sit down at your workstation and open a "
"browser at this location:"), """

""", _("Exam URL"), """: **`{{ checkin_uri }}`**

""", _("You should see boxes prompting for your user "
"name and a one-time check-in code."), """

""", _("Enter the following information"), ":", """

""", _("User name"), """: **`{{ ticket.participation.user.username }}`**

""", pgettext("ticket code required to login exam", "Code"), """: **`{{ ticket.code }}`**

""", _("You have one hour to complete the exam."), """

**""", _("Good luck!"), """**

{% endfor %}
<div style="clear:left; margin-bottom:3ex"></div>""")


class BatchIssueTicketsForm(StyledForm):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    def __init__(self, course, editor_mode, *args, **kwargs):
        super(BatchIssueTicketsForm, self).__init__(*args, **kwargs)

        from course.utils import get_codemirror_widget
        cm_widget, cm_help_text = get_codemirror_widget(
                language_mode={"name": "markdown", "xml": True},
                dependencies=("xml",),
                interaction_mode=editor_mode)

        help_text = (ugettext("Enter <a href=\"http://documen.tician.de/"
                "relate/content.html#relate-markup\">"
                "RELATE markup</a> containing Django template statements to render "
                "your exam tickets. <tt>tickets</tt> contains a list of "
                "data structures "
                "containing ticket information. For each entry <tt>tkt</tt>  "
                "in this list, "
                "use <tt>{{ tkt.participation.user.user_name }}</tt>, "
                "<tt>{{ tkt.code }}</tt>, <tt>{{ tkt.exam.description }}</tt>, "
                "and <tt>{{ checkin_uri }}</tt> as placeholders. "
                "See the example for how to use this."))

        self.fields["exam"] = forms.ModelChoiceField(
                queryset=(
                    Exam.objects.filter(
                        course=course,
                        active=True
                        )),
                required=True,
                label=_("Exam"))

        self.fields["valid_start_time"] = forms.DateTimeField(
                label=_("Start validity"),
                widget=DateTimePicker(
                    options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
                required=False)
        self.fields["valid_end_time"] = forms.DateTimeField(
                label=_("End validity"),
                widget=DateTimePicker(
                    options={"format": "YYYY-MM-DD HH:mm", "sideBySide": True}),
                required=False)
        self.fields["restrict_to_facility"] = forms.CharField(
                label=_("Restrict to facility"),
                help_text=_("If not blank, the exam ticket may only be used in the "
                    "given facility"),
                required=False)

        self.fields["format"] = forms.CharField(
                label=_("Ticket Format"),
                help_text=help_text,
                widget=cm_widget,
                initial=INITIAL_EXAM_TICKET_TEMPLATE,
                required=True)
        self.fields["revoke_prior"] = forms.BooleanField(
                label=_("Revoke prior exam tickets"),
                required=False,
                initial=False)

        self.helper.add_input(
                Submit(
                    "issue",
                    _("Issue tickets")))


@course_view
def batch_issue_exam_tickets(pctx):
    if not pctx.has_permission(pperm.batch_issue_exam_ticket):
        raise PermissionDenied(_("may not batch-issue tickets"))

    form_text = ""

    request = pctx.request
    if request.method == "POST":
        form = BatchIssueTicketsForm(pctx.course, request.user.editor_mode,
                request.POST)

        if form.is_valid():
            exam = form.cleaned_data["exam"]

            from jinja2 import TemplateSyntaxError
            from course.content import markup_to_html
            try:
                with transaction.atomic():
                    if form.cleaned_data["revoke_prior"]:
                        ExamTicket.objects.filter(
                                exam=exam,
                                state__in=(
                                    exam_ticket_states.valid,
                                    exam_ticket_states.used,
                                    )
                                ).update(state=exam_ticket_states.revoked)

                    tickets = []
                    for participation in (
                            Participation.objects.filter(
                                course=pctx.course,
                                status=participation_status.active)
                            .order_by("user__last_name")
                            ):
                        ticket = ExamTicket()
                        ticket.exam = exam
                        ticket.participation = participation
                        ticket.creator = request.user
                        ticket.state = exam_ticket_states.valid
                        ticket.code = gen_ticket_code()
                        ticket.valid_start_time = \
                                form.cleaned_data["valid_start_time"]
                        ticket.valid_end_time = form.cleaned_data["valid_end_time"]
                        ticket.restrict_to_facility = \
                                form.cleaned_data["restrict_to_facility"]
                        ticket.save()

                        tickets.append(ticket)

                    checkin_uri = pctx.request.build_absolute_uri(
                            reverse("relate-check_in_for_exam"))
                    form_text = markup_to_html(
                            pctx.course, pctx.repo, pctx.course_commit_sha,
                            form.cleaned_data["format"], jinja_env={
                                    "tickets": tickets,
                                    "checkin_uri": checkin_uri,
                                    })
            except TemplateSyntaxError as e:
                messages.add_message(request, messages.ERROR,
                    string_concat(
                        _("Template rendering failed"),
                        ": line %(lineno)d: %(err_str)s")
                    % {
                        "lineno": e.lineno,
                        "err_str": e.message.decode("utf-8")})
            except Exception as e:
                messages.add_message(request, messages.ERROR,
                    string_concat(
                        _("Template rendering failed"),
                        ": %(err_type)s: %(err_str)s")
                    % {"err_type": type(e).__name__,
                        "err_str": str(e)})
            else:
                messages.add_message(request, messages.SUCCESS,
                        _("%d tickets issued.") % len(tickets))

    else:
        form = BatchIssueTicketsForm(pctx.course, request.user.editor_mode)

    return render_course_page(pctx, "course/batch-exam-tickets-form.html", {
        "form": form,
        "form_text": form_text,
        "form_description": ugettext("Batch-Issue Exam Tickets")
        })

# }}}


# {{{ check in

def check_exam_ticket(
        username,  # type: Optional[Text]
        code,  # type: Optional[Text]
        now_datetime,  # type: datetime.datetime
        facilities  # type: Optional[FrozenSet[Text]]
        ):
    # type: (...) -> Tuple[bool, Text]
    """
    :returns: (is_valid, msg)
    """

    try:
        user = get_user_model().objects.get(
                username=username,
                is_active=True)
        ticket = ExamTicket.objects.get(
                participation__user=user,
                code=code,
                )
    except ObjectDoesNotExist:
        return (False, _("User name or ticket code not recognized."))

    if ticket.state not in [
            exam_ticket_states.valid,
            exam_ticket_states.used
            ]:
        return (False, _("Ticket is not in usable state. (Has it been revoked?)"))

    from django.conf import settings
    from datetime import timedelta

    validity_period = timedelta(
            minutes=settings.RELATE_TICKET_MINUTES_VALID_AFTER_USE)

    if (ticket.state == exam_ticket_states.used
            and now_datetime >= ticket.usage_time + validity_period):
        return (False, _("Ticket has exceeded its validity period."))

    if not ticket.exam.active:
        return (False, _("Exam is not active."))

    if now_datetime < ticket.exam.no_exams_before:
        return (False, _("Exam has not started yet."))
    if (
            ticket.exam.no_exams_after is not None
            and
            ticket.exam.no_exams_after <= now_datetime):
        return (False, _("Exam has ended."))

    if (ticket.restrict_to_facility
            and (
                facilities is None
                or ticket.restrict_to_facility not in facilities)):
        return (False,
                _("Exam ticket requires presence in facility '%s'.")
                % ticket.restrict_to_facility)
    if (
            ticket.valid_start_time is not None
            and
            now_datetime < ticket.valid_start_time):
        return (False, _("Exam ticket is not yet valid."))
    if (
            ticket.valid_end_time is not None
            and
            ticket.valid_end_time < now_datetime):
        return (False, _("Exam ticket has expired."))

    return True, _("Ticket is valid.")


class ExamTicketBackend(object):
    def authenticate(self, username=None, code=None, now_datetime=None,
            facilities=None):
        is_valid, msg = check_exam_ticket(username, code, now_datetime, facilities)

        if not is_valid:
            return None

        user = get_user_model().objects.get(
                username=username,
                is_active=True)
        return user

    def get_user(self, user_id):
        try:
            return get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return None


class ExamCheckInForm(StyledForm):
    username = forms.CharField(required=True, label=_("User name"),
            # For now, until we upgrade to a custom user model.
            max_length=30,
            help_text=_("This is typically your full email address."))
    code = forms.CharField(required=True, label=_("Code"),
            widget=forms.PasswordInput(),
            help_text=_("This is not your password, but a code that was "
                "given to you by a staff member. If you do not have one, "
                "please follow the link above to log in."))

    def __init__(self, *args, **kwargs):
        super(ExamCheckInForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Check in")))


@sensitive_post_parameters()
@csrf_protect
@never_cache
def check_in_for_exam(request):
    now_datetime = get_now_or_fake_time(request)

    if request.method == "POST":
        form = ExamCheckInForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            code = form.cleaned_data["code"]

            pretend_facilities = request.session.get(
                    "relate_pretend_facilities", None)

            is_valid, msg = check_exam_ticket(
                    username, code, now_datetime,
                    request.relate_facilities)
            if not is_valid:
                messages.add_message(request, messages.ERROR, msg)
            else:
                from django.contrib.auth import authenticate, login
                user = authenticate(
                        username=username,
                        code=code,
                        now_datetime=now_datetime,
                        facilities=request.relate_facilities)

                assert user is not None

                login(request, user)

                ticket = ExamTicket.objects.get(
                        participation__user=user,
                        code=code,
                        state__in=(
                            exam_ticket_states.valid,
                            exam_ticket_states.used,
                            )
                        )
                if ticket.state == exam_ticket_states.valid:
                    ticket.state = exam_ticket_states.used
                    ticket.usage_time = now_datetime
                    ticket.save()

                if pretend_facilities:
                    # Make pretend-facilities survive exam login.
                    request.session["relate_pretend_facilities"] = pretend_facilities

                request.session["relate_exam_ticket_pk_used_for_login"] = ticket.pk

                return redirect("relate-view_start_flow",
                        ticket.exam.course.identifier,
                        ticket.exam.flow_id)

    else:
        form = ExamCheckInForm()

    return render(request, "course/exam-check-in.html", {
        "form_description":
            _("Check in for Exam"),
        "form": form
        })

# }}}


def is_from_exams_only_facility(request):
    from course.utils import get_facilities_config
    for name, props in six.iteritems(get_facilities_config(request)):
        if not props.get("exams_only", False):
            continue

        # By now we know that this facility is exams-only
        if name in request.relate_facilities:
            return True

    return False


def get_login_exam_ticket(request):
    # type: (http.HttpRequest) -> ExamTicket
    exam_ticket_pk = request.session.get("relate_exam_ticket_pk_used_for_login")

    if exam_ticket_pk is None:
        return None

    return ExamTicket.objects.get(pk=exam_ticket_pk)


# {{{ lockdown middleware

class ExamFacilityMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        exams_only = is_from_exams_only_facility(request)

        if not exams_only:
            return self.get_response(request)

        if (exams_only and
                "relate_session_locked_to_exam_flow_session_pk" in request.session):
            # ExamLockdownMiddleware is in control.
            return self.get_response(request)

        from django.urls import resolve
        resolver_match = resolve(request.path)

        from course.exam import check_in_for_exam, issue_exam_ticket
        from course.auth import (user_profile, sign_in_choice, sign_in_by_email,
                sign_in_stage2_with_token, sign_in_by_user_pw, sign_out, impersonate,
                stop_impersonating)
        from course.views import set_pretend_facilities
        from course.flow import view_start_flow, view_resume_flow, view_flow_page

        ok = False
        if resolver_match.func in [
                sign_in_choice,
                sign_in_by_email,
                sign_in_stage2_with_token,
                sign_in_by_user_pw,
                impersonate,
                stop_impersonating,
                check_in_for_exam,
                list_available_exams,
                view_start_flow,
                view_resume_flow,
                user_profile,
                sign_out,
                set_pretend_facilities]:
            ok = True

        elif request.path.startswith("/saml2"):
            ok = True

        elif request.path.startswith("/select2"):
            ok = True

        elif (
                (request.user.is_staff
                    or
                    request.user.has_perm("course.can_issue_exam_tickets"))
                and
                resolver_match.func == issue_exam_ticket):
            ok = True

        if not ok:
            if (request.user.is_authenticated
                    and resolver_match.func is view_flow_page):
                messages.add_message(request, messages.INFO,
                        _("Access to flows in an exams-only facility "
                            "is only granted if the flow is locked down. "
                            "To do so, add 'lock_down_as_exam_session' to "
                            "your flow's access permissions."))

            if request.user.is_authenticated:
                return redirect("relate-list_available_exams")
            else:
                return redirect("relate-sign_in_choice")

        return self.get_response(request)


class ExamLockdownMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.relate_exam_lockdown = False

        if "relate_session_locked_to_exam_flow_session_pk" in request.session:
            exam_flow_session_pk = request.session[
                    "relate_session_locked_to_exam_flow_session_pk"]

            try:
                exam_flow_session = FlowSession.objects.get(pk=exam_flow_session_pk)
            except ObjectDoesNotExist:
                msg = _("Error while processing exam lockdown: "
                        "flow session not found.")
                messages.add_message(request, messages.ERROR, msg)
                raise PermissionDenied(msg)

            request.relate_exam_lockdown = True

            from django.urls import resolve
            resolver_match = resolve(request.path)

            from course.views import (get_repo_file, get_current_repo_file)
            from course.flow import (
                    view_start_flow, view_resume_flow, view_flow_page,
                    update_expiration_mode, update_page_bookmark_state,
                    finish_flow_session_view)
            from course.auth import (user_profile, sign_in_choice, sign_in_by_email,
                    sign_in_stage2_with_token, sign_in_by_user_pw, sign_out)

            ok = False
            if resolver_match.func in [
                    get_repo_file,
                    get_current_repo_file,

                    check_in_for_exam,
                    list_available_exams,

                    sign_in_choice,
                    sign_in_by_email,
                    sign_in_stage2_with_token,
                    sign_in_by_user_pw,
                    user_profile,
                    sign_out]:
                ok = True

            elif request.path.startswith("/saml2"):
                ok = True

            elif request.path.startswith("/select2"):
                ok = True

            elif (
                    resolver_match.func in [
                        view_resume_flow,
                        view_flow_page,
                        update_expiration_mode,
                        update_page_bookmark_state,
                        finish_flow_session_view]
                    and
                    int(resolver_match.kwargs["flow_session_id"])
                    == exam_flow_session_pk):
                ok = True

            elif (
                    resolver_match.func == view_start_flow
                    and
                    resolver_match.kwargs["flow_id"]
                    == exam_flow_session.flow_id):
                ok = True

            if not ok:
                messages.add_message(request, messages.ERROR,
                        _("Your RELATE session is currently locked down "
                        "to this exam flow. Navigating to other parts of "
                        "RELATE is not currently allowed. "
                        "To exit this exam, log out."))
                return redirect("relate-view_start_flow",
                        exam_flow_session.course.identifier,
                        exam_flow_session.flow_id)

        return self.get_response(request)

# }}}


# {{{ list available exams

def list_available_exams(request):
    now_datetime = get_now_or_fake_time(request)

    if request.user.is_authenticated:
        participations = (
                Participation.objects.filter(
                    user=request.user,
                    status=participation_status.active))
    else:
        participations = []

    from django.db.models import Q
    exams = (
            Exam.objects
            .filter(
                course__in=[p.course for p in participations],
                active=True,
                listed=True,
                no_exams_before__lt=now_datetime)
            .filter(
                Q(no_exams_after__isnull=True)
                |
                Q(no_exams_after__gt=now_datetime))
            .order_by("no_exams_before", "course__number"))

    return render(request, "course/list-exams.html", {
        "exams": exams
        })

# }}}


# {{{ lockdown context processor

def exam_lockdown_context_processor(request):
    return {
            "relate_exam_lockdown": getattr(
                request, "relate_exam_lockdown", None)
            }

# }}}


# vim: foldmethod=marker
