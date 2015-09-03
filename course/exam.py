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

from course.models import Exam, ExamTicket, Participation
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
                help_text=_("Select participant for whom exception is to "
                "be granted."),
                label=_("Participant"))
        self.fields["exam"] = forms.ModelChoiceField(
                queryset=(
                    Exam.objects.filter(
                        active=True)),
                required=True,
                initial=initial_exam,
                label=_("Exam"))

        self.helper.add_input(
                Submit(
                    "issue",
                    _("Issue ticket"),
                    css_class="col-lg-offset-2"))


@permission_required("course.can_check_in_student")
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
                ticket = ExamTicket()
                ticket.exam = exam
                ticket.participation = participation
                ticket.creator = request.user
                ticket.state = exam_ticket_states.valid
                ticket.code = gen_ticket_code()
                ticket.save()

                messages.add_message(request, messages.SUCCESS,
                        _(
                            "Ticket issued for <b>%s</b>. "
                            "The ticket code is <b>%s</b>."
                            ) % (participation, ticket.code))

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
                    _("Issue tickets"),
                    css_class="col-lg-offset-2"))


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
                        state=exam_ticket_states.valid,
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
                    state=exam_ticket_states.valid,
                    )

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
                Submit("submit", _("Check in"),
                    css_class="col-lg-offset-2"))


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
                        state=exam_ticket_states.valid,
                        )
                ticket.state = exam_ticket_states.used
                ticket.usage_time = now_datetime
                ticket.save()

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

# vim: foldmethod=marker
