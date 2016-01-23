# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2016 Dong Zhuang, Andreas Kloeckner"

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

from django.db.models.signals import post_save
from django.db import transaction
from django.dispatch import receiver

from accounts.models import User
from course.models import (
        Course, Participation, participation_status, 
        ParticipationPreapproval,
        )

# {{{ Update enrollment status when a User/Course instance is saved
@receiver(post_save, sender=User)
@receiver(post_save, sender=Course)
@transaction.atomic
def update_requested_participation_status(sender, created, instance, 
        **kwargs):

    if created:
        return

    if isinstance(instance, Course):
        course = instance
        requested_qset = Participation.objects.filter(
                course=course, status=participation_status.requested)
    elif isinstance(instance, User):
        user = instance
        requested_qset = Participation.objects.filter(
                user=user, status=participation_status.requested)
    else:
        return

    if requested_qset:

        for requested in requested_qset:
            if isinstance(instance, Course):
                user = requested.user
            elif isinstance(instance, User):
                course = requested.course
            else:
                continue

            may_preapprove, role = may_preapprove_role(course, user)

            if may_preapprove:
                from course.enrollment import handle_enrollment_request

                handle_enrollment_request(
                    course, user, participation_status.active, role)


def may_preapprove_role(course, user):
    if not user.is_active:
        return False, None

    preapproval = None
    if user.email:
        try:
            preapproval = ParticipationPreapproval.objects.get(
                    course=course, email__iexact=user.email)
        except ParticipationPreapproval.DoesNotExist:
            if user.institutional_id:
                if not (course.preapproval_require_verified_inst_id
                        and not user.institutional_id_verified):
                    try:
                        preapproval = (
                                ParticipationPreapproval.objects.get(
                                    course=course,
                                    institutional_id__iexact=\
                                            user.institutional_id))
                    except ParticipationPreapproval.DoesNotExist:
                        pass

    if preapproval:
        return True, preapproval.role
    else:
        return False, None

# }}}
# vim: foldmethod=marker
