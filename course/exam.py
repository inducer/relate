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
from django.utils.translation import ugettext, ugettext_lazy as _
from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.core.exceptions import (  # noqa
        PermissionDenied, ObjectDoesNotExist, SuspiciousOperation)
from django.contrib import messages  # noqa
from django.contrib.auth.decorators import permission_required
from django.db import transaction

from crispy_forms.layout import Submit

from course.models import Exam, ExamTicket, Participation, FlowSession
from course.utils import course_view, render_course_page
from course.constants import (
        exam_ticket_states,
        participation_status,
        participation_role)
from course.views import get_now_or_fake_time

from relate.utils import StyledForm


ticket_alphabet = "ABCDEFGHJKLPQRSTUVWXYZabcdefghjkpqrstuvwxyz23456789"


def gen_ticket_code():
    from random import choice
    return "".join(choice(ticket_alphabet) for i in range(8))


# {{{ issue ticket

class UserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        user = obj
        return (
                _("%(user_email)s - %(user_lastname)s, "
                    "%(user_firstname)s")
                % {
                    "user_email": user.email,
                    "user_lastname": user.last_name,
                    "user_firstname": user.first_name})


class IssueTicketForm(StyledForm):
    def __init__(self, *args, **kwargs):
        initial_exam = kwargs.pop("initial_exam", None)

        super(IssueTicketForm, self).__init__(*args, **kwargs)

        self.fields["user"] = UserChoiceField(
                queryset=(get_user_model().objects
                    .filter(
                        is_active=True,
                        )
                    .order_by("last_name")),
                required=True,
                help_text=_("Select participant for whom ticket is to "
                "be issued."),
                label=_("Participant"))
        self.fields["exam"] = forms.ModelChoiceField(
                queryset=(
                    Exam.objects.filter(
                        active=True)),
                required=True,
                initial=initial_exam,
                label=_("Exam"))

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
    if request.method == "POST":
        form = IssueTicketForm(request.POST)

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
                ticket.save()

                messages.add_message(request, messages.SUCCESS,
                        _(
                            "Ticket issued for <b>%(participation)s</b>. "
                            "The ticket code is <b>%(ticket_code)s</b>."
                            ) % {"participation": participation,
                                 "ticket_code": ticket.code})

                form = IssueTicketForm(initial_exam=exam)

    else:
        form = IssueTicketForm()

    return render(request, "generic-form.html", {
        "form_description":
            _("Issue Exam Ticket"),
        "form": form,
        })

# }}}


# {{{ batch-issue tickets

class BatchIssueTicketsForm(StyledForm):
    def __init__(self, course, *args, **kwargs):
        super(BatchIssueTicketsForm, self).__init__(*args, **kwargs)

        self.fields["exam"] = forms.ModelChoiceField(
                queryset=(
                    Exam.objects.filter(
                        course=course,
                        active=True
                        )),
                required=True,
                label=_("Exam"))
        self.fields["format"] = forms.ChoiceField(
                choices=(
                    ("list", _("List")),
                    ("cards", _("Cards")),
                    ),
                label=_("Ticket Format"),
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
@transaction.atomic
def batch_issue_exam_tickets(pctx):
    if pctx.role not in [
            participation_role.instructor,
            ]:
        raise PermissionDenied(
                _("must be instructor or TA to batch-issue tickets"))

    form_text = ""

    request = pctx.request
    if request.method == "POST":
        form = BatchIssueTicketsForm(pctx.course, request.POST)

        if form.is_valid():
            exam = form.cleaned_data["exam"]

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
                    .order_by(
                        "user__username")):
                ticket = ExamTicket()
                ticket.exam = exam
                ticket.participation = participation
                ticket.creator = request.user
                ticket.state = exam_ticket_states.valid
                ticket.code = gen_ticket_code()
                ticket.save()

                tickets.append(ticket)

            from django.template.loader import render_to_string
            form_text = render_to_string(
                    "course/exam-ticket-%s.html" % form.cleaned_data["format"],
                    {"tickets": tickets})

            messages.add_message(request, messages.SUCCESS,
                    _("%d tickets issued.") % len(tickets))

            form = None

    else:
        form = BatchIssueTicketsForm(pctx.course)

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_text": form_text,
        "form_description": ugettext("Batch-Issue Exam Tickets")
        })

# }}}


# {{{ check in

class ExamTicketBackend(object):
    def authenticate(self, username=None, code=None, now_datetime=None):
        try:
            user = get_user_model().objects.get(
                    username=username,
                    is_active=True)
            ticket = ExamTicket.objects.get(
                    participation__user=user,
                    code=code,
                    state__in=(
                        exam_ticket_states.valid,
                        exam_ticket_states.used,
                        )
                    )

            from django.conf import settings
            from datetime import timedelta

            validity_period = timedelta(
                    minutes=settings.RELATE_TICKET_MINUTES_VALID_AFTER_USE)

            if (ticket.state == exam_ticket_states.used
                    and now_datetime >= ticket.usage_time + validity_period):
                return None
            if ticket.exam.no_exams_before >= now_datetime:
                return None
            if (
                    ticket.exam.no_exams_after is not None
                    and
                    ticket.exam.no_exams_after <= now_datetime):
                return None

        except ObjectDoesNotExist:
            return None

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
            widget=forms.PasswordInput())

    def __init__(self, *args, **kwargs):
        super(ExamCheckInForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Check in")))


def check_in_for_exam(request):
    now_datetime = get_now_or_fake_time(request)

    if request.method == "POST":
        form = ExamCheckInForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            code = form.cleaned_data["code"]

            from django.contrib.auth import authenticate, login
            user = authenticate(username=username, code=code,
                    now_datetime=now_datetime)

            if user is None:
                messages.add_message(request, messages.ERROR,
                        _("Invalid check-in data."))

            else:
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

                request.session["relate_session_exam_ticket_pk"] = ticket.pk

                return redirect("relate-view_start_flow",
                        ticket.exam.course.identifier,
                        ticket.exam.flow_id)

    else:
        form = ExamCheckInForm()

    return render(request, "generic-form.html", {
        "form_description":
            _("Check in for Exam"),
        "form": form
        })

# }}}


def is_from_exams_only_facility(request):
    import ipaddress

    remote_address = ipaddress.ip_address(six.text_type(request.META['REMOTE_ADDR']))

    exams_only = False

    from django.conf import settings
    for name, props in six.iteritems(settings.RELATE_FACILITIES):
        if not props.get("exams_only", False):
            continue

        ip_ranges = props.get("ip_ranges", [])
        for ir in ip_ranges:
            if remote_address in ipaddress.ip_network(six.text_type(ir)):
                exams_only = True
                break

        if exams_only:
            break

    return exams_only


# {{{ lockdown middleware

class ExamFacilityMiddleware(object):
    def process_request(self, request):
        exams_only = is_from_exams_only_facility(request)

        if not exams_only:
            return None

        if (exams_only and
                "relate_session_exam_ticket_pk" in request.session):
            # ExamLockdownMiddleware is in control.
            return None

        from django.core.urlresolvers import resolve
        resolver_match = resolve(request.path)

        from course.exam import check_in_for_exam, issue_exam_ticket
        from course.auth import (user_profile, sign_in_by_email,
                sign_in_stage2_with_token, sign_in_by_user_pw)
        from django.contrib.auth.views import logout

        ok = False
        if resolver_match.func in [
                sign_in_by_email,
                sign_in_stage2_with_token,
                sign_in_by_user_pw,
                check_in_for_exam,
                user_profile,
                logout]:
            ok = True

        elif request.user.is_staff:
            ok = True

        elif (
                request.user.has_perm("course.can_issue_exam_tickets")
                and
                resolver_match.func == issue_exam_ticket):
            ok = True

        if not ok:
            return redirect("relate-check_in_for_exam")


class ExamLockdownMiddleware(object):
    def process_request(self, request):
        request.relate_exam_lockdown = False

        if "relate_session_exam_ticket_pk" in request.session:
            ticket_pk = request.session['relate_session_exam_ticket_pk']

            try:
                ticket = ExamTicket.objects.get(pk=ticket_pk)
            except ObjectDoesNotExist:
                messages.add_message(request, messages.ERROR,
                        _("Error while processing exam lockdown: ticket not found."))
                raise SuspiciousOperation()

            if not ticket.exam.lock_down_sessions:
                return None

            request.relate_exam_lockdown = True

            flow_session_ids = [fs.id for fs in FlowSession.objects.filter(
                    participation=ticket.participation,
                    flow_id=ticket.exam.flow_id)]

            from django.core.urlresolvers import resolve
            resolver_match = resolve(request.path)

            from course.views import (get_repo_file, get_current_repo_file)
            from course.flow import (view_start_flow, view_flow_page,
                    update_expiration_mode, finish_flow_session_view)
            from course.auth import user_profile
            from django.contrib.auth.views import logout

            ok = False
            if resolver_match.func in [
                    get_repo_file,
                    get_current_repo_file,

                    user_profile,
                    logout]:
                ok = True

            elif (resolver_match.func == view_start_flow
                    and
                    resolver_match.kwargs["course_identifier"]
                    == ticket.exam.course.identifier
                    and
                    resolver_match.kwargs["flow_id"]
                    == ticket.exam.flow_id):
                ok = True

            elif (
                    resolver_match.func in [
                        view_flow_page,
                        update_expiration_mode,
                        finish_flow_session_view]
                    and
                    int(resolver_match.kwargs["flow_session_id"])
                    in flow_session_ids):
                ok = True

            if not ok:
                raise PermissionDenied("not allowed in exam lock-down")

# }}}


# {{{ lockdown context processor

def exam_lockdown_context_processor(request):
    return {
            "relate_exam_lockdown": request.relate_exam_lockdown,
            }

# }}}


# {{{ lockdown sign-in checker

def may_sign_in(request, user):
    exams_only = is_from_exams_only_facility(request)

    if not exams_only:
        return True
    else:
        if user.is_staff:
            return True
        elif user.has_perm("course.can_issue_exam_tickets"):
            return True

    return False

# }}}


# vim: foldmethod=marker
