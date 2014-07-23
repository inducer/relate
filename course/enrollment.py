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
from django.conf import settings
from django.core.urlresolvers import reverse

from course.models import (
        get_user_status, user_status,
        Course, Participation,
        participation_role, participation_status)

from course.views import get_role_and_participation


# {{{ enrollment

@login_required
def enroll(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.unenrolled:
        messages.add_message(request, messages.ERROR,
                "Already enrolled. Cannot re-renroll.")
        return redirect("course.views.course_page", course_identifier)

    user = request.user
    ustatus = get_user_status(user)
    if (course.enrollment_required_email_suffix
            and not ustatus.status == user_status.active):
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

    def enroll(status):
        participations = Participation.objects.filter(course=course, user=user)

        assert participations.count() <= 1
        if participations.count() == 0:
            participation = Participation()
            participation.user = user
            participation.course = course
            participation.role = participation_role.student
            participation.status = status
            participation.save()
        else:
            (participation,) = participations
            participation.status = status
            participation.save()

        return participation

    if course.enrollment_approval_required:
        enroll(participation_status.requested)
        messages.add_message(request, messages.INFO,
                "Enrollment request sent. You will receive notifcation "
                "by email once your request has been acted upon.")

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
    else:
        enroll(participation_status.active)
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

        from django.core.mail import send_mail
        send_mail("[%s] Your enrollment request" % course.identifier,
                message,
                course.email,
                recipient_list=[participation.user.email])

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

# vim: foldmethod=marker
