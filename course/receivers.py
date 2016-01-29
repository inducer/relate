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
from django.dispatch import receiver
from accounts.models import User
from course.models import (
        Course, Participation, participation_status, ParticipationPreapproval,
        )

# {{{ Update enrollment status when a User/Course instance is saved
@receiver(post_save, sender=User)
@receiver(post_save, sender=Course)
def update_requested_participation_status(sender, created, instance, **kwargs):
    
    if isinstance(instance, Course):
        course = instance
        requested_qset = Participation.objects.filter(
                course=course, status=participation_status.requested)
        print "i am working as course!"

    elif isinstance(instance, User):
        user = instance
        requested_qset = Participation.objects.filter(
                user=user, status=participation_status.requested)
        print "i am working as user!"
    
    if not created:
        if requested_qset is None:
            pass

        for requested in requested_qset:
            if isinstance(instance, Course):
                user = requested.user
            elif isinstance(instance, User):
                course = requested.course

            update_requested_user_course(user=user, course=course)
            
def update_requested_user_course(user, course):
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
                                 institutional_id__iexact\
                                         =user.institutional_id))
                    except ParticipationPreapproval.DoesNotExist:
                        pass
        pass

    def enroll(status, role):
        participations = Participation.objects.filter(
                course=course, user=user)

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

    if preapproval is not None:
        role = preapproval.role
        enroll(participation_status.active, role)

        from course.enrollment import send_enrollment_decision
        send_enrollment_decision(requested, True)


# }}}
# vim: foldmethod=marker
