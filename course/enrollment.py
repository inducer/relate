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
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.conf import settings
from django.core.urlresolvers import reverse
from django.db import transaction
from django import forms

from crispy_forms.layout import Submit

from course.models import (
        get_user_status, user_status,
        Course,
        Participation, ParticipationPreapproval,
        participation_role, participation_status,
        PARTICIPATION_ROLE_CHOICES)

from course.views import get_role_and_participation
from course.utils import course_view, render_course_page

from relate.utils import StyledForm


# {{{ enrollment

@login_required
@transaction.atomic
def enroll(request, course_identifier):
    if request.method != "POST":
        raise SuspiciousOperation("can only enroll using POST request")

    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.unenrolled:
        messages.add_message(request, messages.ERROR,
                "Already enrolled. Cannot re-renroll.")
        return redirect("course.views.course_page", course_identifier)

    user = request.user
    ustatus = get_user_status(user)
    if (course.enrollment_required_email_suffix
            and ustatus.status != user_status.active):
        messages.add_message(request, messages.ERROR,
                "Your email address is not yet confirmed. "
                "Confirm your email to continue.")
        return redirect("course.views.course_page", course_identifier)

    if (course.enrollment_required_email_suffix
            and not user.email.endswith(course.enrollment_required_email_suffix)):

        messages.add_message(request, messages.ERROR,
                "Enrollment not allowed. Please use your '%s' email to "
                "enroll." % course.enrollment_required_email_suffix)
        return redirect("course.views.course_page", course_identifier)

    def enroll(status, role):
        participations = Participation.objects.filter(course=course, user=user)

        assert participations.count() <= 1
        if participations.count() == 0:
            participation = Participation()
            participation.user = user
            participation.course = course
            participation.role = role
            participation.status = status
            participation.save()
        else:
            (participation,) = participations
            participation.status = status
            participation.save()

        return participation

    preapproval = None
    if request.user.email:
        try:
            preapproval = ParticipationPreapproval.objects.get(
                    course=course, email__iexact=request.user.email)
        except ParticipationPreapproval.DoesNotExist:
            pass

    role = participation_role.student

    if preapproval is not None:
        role = preapproval.role

    if course.enrollment_approval_required and preapproval is None:
        enroll(participation_status.requested, role)

        from django.template.loader import render_to_string
        message = render_to_string("course/enrollment-request-email.txt", {
            "user": user,
            "course": course,
            "admin_uri": request.build_absolute_uri(
                    reverse("admin:course_participation_changelist"))
            })
        from django.core.mail import send_mail
        send_mail("[%s] New enrollment request" % course_identifier,
                message,
                settings.ROBOT_EMAIL_FROM,
                recipient_list=[course.email])

        messages.add_message(request, messages.INFO,
                "Enrollment request sent. You will receive notifcation "
                "by email once your request has been acted upon.")
    else:
        enroll(participation_status.active, role)

        messages.add_message(request, messages.SUCCESS,
                "Successfully enrolled.")

    return redirect("course.views.course_page", course_identifier)

# }}}


# {{{ admin actions

def decide_enrollment(approved, modeladmin, request, queryset):
    count = 0

    for participation in queryset:
        if participation.status != participation_status.requested:
            continue

        if approved:
            participation.status = participation_status.active
        else:
            participation.status = participation_status.denied
        participation.save()

        course = participation.course
        from django.template.loader import render_to_string
        message = render_to_string("course/enrollment-decision-email.txt", {
            "user": participation.user,
            "approved": approved,
            "course": course,
            "course_uri": request.build_absolute_uri(
                    reverse("course.views.course_page",
                        args=(course.identifier,)))
            })

        from django.core.mail import EmailMessage
        msg = EmailMessage("[%s] Your enrollment request" % course.identifier,
                message,
                course.email,
                [participation.user.email])
        msg.cc = [course.email]
        msg.send()

        count += 1

    messages.add_message(request, messages.INFO,
            "%d requests processed." % count)


def approve_enrollment(modeladmin, request, queryset):
    decide_enrollment(True, modeladmin, request, queryset)

approve_enrollment.short_description = "Approve enrollment"


def deny_enrollment(modeladmin, request, queryset):
    decide_enrollment(False, modeladmin, request, queryset)

deny_enrollment.short_description = "Deny enrollment"

# }}}


# {{{ preapprovals

class BulkPreapprovalsForm(StyledForm):
    role = forms.ChoiceField(
            choices=PARTICIPATION_ROLE_CHOICES,
            initial=participation_role.student)
    emails = forms.CharField(required=True, widget=forms.Textarea,
            help_text="Enter fully qualified email addresses, one per line.")

    def __init__(self, *args, **kwargs):
        super(BulkPreapprovalsForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", "Preapprove",
                    css_class="col-lg-offset-2"))


@login_required
@transaction.atomic
@course_view
def create_preapprovals(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied("only instructors may do that")

    request = pctx.request

    if request.method == "POST":
        form = BulkPreapprovalsForm(request.POST)
        if form.is_valid():

            created_count = 0
            exist_count = 0

            role = form.cleaned_data["role"]
            for l in form.cleaned_data["emails"].split("\n"):
                l = l.strip()

                if not l:
                    continue

                try:
                    preapproval = ParticipationPreapproval.objects.get(
                            email__iexact=l,
                            course=pctx.course)
                except ParticipationPreapproval.DoesNotExist:
                    pass
                else:
                    exist_count += 1
                    continue

                preapproval = ParticipationPreapproval()
                preapproval.email = l
                preapproval.course = pctx.course
                preapproval.role = role
                preapproval.creator = request.user
                preapproval.save()

                created_count += 1

            messages.add_message(request, messages.INFO,
                    "%d preapprovals created, %d already existed."
                    % (created_count, exist_count))
            return redirect("course.views.home")

    else:
        form = BulkPreapprovalsForm()

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Create Participation Preapprovals",
    })

# }}}


# vim: foldmethod=marker
