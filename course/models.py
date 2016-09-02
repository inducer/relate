# -*- coding: utf-8 -*-

from __future__ import division, unicode_literals

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

from typing import cast, Any, Optional, Text, Iterable  # noqa

import six

from django.db import models
from django.utils.timezone import now
from django.urls import reverse
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.utils.translation import (
        ugettext_lazy as _, pgettext_lazy, string_concat)
from django.core.validators import RegexValidator
from django.db.models.signals import post_save
from django.dispatch import receiver

from django.conf import settings

from course.constants import (  # noqa
        user_status, USER_STATUS_CHOICES,
        participation_status, PARTICIPATION_STATUS_CHOICES,
        flow_permission, FLOW_PERMISSION_CHOICES,
        flow_session_expiration_mode, FLOW_SESSION_EXPIRATION_MODE_CHOICES,
        grade_aggregation_strategy, GRADE_AGGREGATION_STRATEGY_CHOICES,
        grade_state_change_types, GRADE_STATE_CHANGE_CHOICES,
        flow_rule_kind, FLOW_RULE_KIND_CHOICES,
        exam_ticket_states, EXAM_TICKET_STATE_CHOICES,
        participation_permission, PARTICIPATION_PERMISSION_CHOICES,

        COURSE_ID_REGEX
        )

from course.page.base import AnswerFeedback


# {{{ mypy

if False:
    from course.content import FlowDesc  # noqa

# }}}


from jsonfield import JSONField
from yamlfield.fields import YAMLField


# {{{ course

class Course(models.Model):
    identifier = models.CharField(max_length=200, unique=True,
            help_text=_("A course identifier. Alphanumeric with dashes, "
            "no spaces. This is visible in URLs and determines the location "
            "on your file system where the course's git repository lives. "
            "This should <em>not</em> be changed after the course has been created "
            "without also moving the course's git on the server."),
            verbose_name=_('Course identifier'),
            db_index=True,
            validators=[
                RegexValidator(
                    "^"+COURSE_ID_REGEX+"$",
                    message=_(
                        "Identifier may only contain letters, "
                        "numbers, and hypens ('-').")),
                    ]
            )
    name = models.CharField(
            null=True, blank=False,
            max_length=200,
            verbose_name=_('Course name'),
            help_text=_("A human-readable name for the course. "
                "(e.g. 'Numerical Methods')"))
    number = models.CharField(
            null=True, blank=False,
            max_length=200,
            verbose_name=_('Course number'),
            help_text=_("A human-readable course number/ID "
                "for the course (e.g. 'CS123')"))
    time_period = models.CharField(
            null=True, blank=False,
            max_length=200,
            verbose_name=_('Time Period'),
            help_text=_("A human-readable description of the "
                "time period for the course (e.g. 'Fall 2014')"))

    start_date = models.DateField(
            verbose_name=_('Start date'),
            null=True, blank=True)
    end_date = models.DateField(
            verbose_name=_('End date'),
            null=True, blank=True)

    hidden = models.BooleanField(
            default=True,
            help_text=_("Is the course only accessible to course staff?"),
            verbose_name=_('Only visible to course staff'))
    listed = models.BooleanField(
            default=True,
            help_text=_("Should the course be listed on the main page?"),
            verbose_name=_('Listed on main page'))
    accepts_enrollment = models.BooleanField(
            default=True,
            verbose_name=_('Accepts enrollment'))

    git_source = models.CharField(max_length=200, blank=True,
            help_text=_("A Git URL from which to pull course updates. "
            "If you're just starting out, enter "
            "<tt>git://github.com/inducer/relate-sample</tt> "
            "to get some sample content."),
            verbose_name=_('git source'))
    ssh_private_key = models.TextField(blank=True,
            help_text=_("An SSH private key to use for Git authentication. "
            "Not needed for the sample URL above."
            "You may use <a href='/generate-ssh-key'>this tool</a> to generate "
            "a key pair."),
            verbose_name=_('SSH private key'))
    course_root_path = models.CharField(max_length=200, blank=True,
            help_text=_(
                'Subdirectory <em>within</em> the git repository to use as '
                'course root directory. Not required, and usually blank. '
                'Use only if your course content lives in a subdirectory '
                'of your git repository. '
                'Should not include trailing slash.'),
            verbose_name=_('Course root in repository'))

    course_file = models.CharField(max_length=200,
            default="course.yml",
            help_text=_("Name of a YAML file in the git repository that "
            "contains the root course descriptor."),
            verbose_name=_('Course file'))
    events_file = models.CharField(max_length=200,
            default="events.yml",
            help_text=_("Name of a YAML file in the git repository that "
            "contains calendar information."),
            verbose_name=_('Events file'))

    enrollment_approval_required = models.BooleanField(
            default=False,
            help_text=_("If set, each enrolling student must be "
            "individually approved."),
            verbose_name=_('Enrollment approval required'))
    preapproval_require_verified_inst_id = models.BooleanField(
            default=True,
            help_text=_("If set, students cannot get participation "
                        "preapproval using institutional ID if "
                        "the institutional ID they provided is not "
                        "verified."),
            verbose_name=_('Prevent preapproval by institutional ID if not '
                           'verified?'))
    enrollment_required_email_suffix = models.CharField(
            max_length=200, blank=True, null=True,
            help_text=_("Enrollee's email addresses must end in the "
            "specified suffix, such as '@illinois.edu'."),
            verbose_name=_('Enrollment required email suffix'))

    from_email = models.EmailField(
            # Translators: replace "RELATE" with the brand name of your
            # website if necessary.
            help_text=_("This email address will be used in the 'From' line "
            "of automated emails sent by RELATE."),
            verbose_name=_('From email'))

    notify_email = models.EmailField(
            help_text=_("This email address will receive "
            "notifications about the course."),
            verbose_name=_('Notify email'))

    # {{{ XMPP

    course_xmpp_id = models.CharField(max_length=200, blank=True, null=True,
            help_text=_("(Required only if the instant message feature is "
            "desired.) The Jabber/XMPP ID (JID) the course will use to sign "
            "in to an XMPP server."),
            verbose_name=_('Course xmpp ID'))
    course_xmpp_password = models.CharField(max_length=200, blank=True, null=True,
            help_text=_("(Required only if the instant message feature is "
            "desired.) The password to go with the JID above."),
            verbose_name=_('Course xmpp password'))

    recipient_xmpp_id = models.CharField(max_length=200, blank=True, null=True,
            help_text=_("(Required only if the instant message feature is "
            "desired.) The JID to which instant messages will be sent."),
            verbose_name=_('Recipient xmpp ID'))

    # }}}

    active_git_commit_sha = models.CharField(max_length=200, null=False,
            blank=False,
            verbose_name=_('Active git commit SHA'))

    participants = models.ManyToManyField(settings.AUTH_USER_MODEL,
            through='Participation')

    class Meta:
        verbose_name = _("Course")
        verbose_name_plural = _("Courses")

    def __unicode__(self):
        return self.identifier

    if six.PY3:
        __str__ = __unicode__

    def get_absolute_url(self):
        return reverse("relate-course_page", args=(self.identifier,))

# }}}


# {{{ event

class Event(models.Model):
    """An event is an identifier that can be used to specify dates in
    course content.
    """

    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)
    kind = models.CharField(max_length=50,
            # Translators: format of event kind in Event model
            help_text=_("Should be lower_case_with_underscores, no spaces "
            "allowed."),
            verbose_name=_('Kind of event'))
    ordinal = models.IntegerField(blank=True, null=True,
            # Translators: ordinal of event of the same kind
            verbose_name=_('Ordinal of event'))

    time = models.DateTimeField(verbose_name=_('Start time'))
    end_time = models.DateTimeField(null=True, blank=True,
            verbose_name=_('End time'))
    all_day = models.BooleanField(default=False,
            # Translators: for when the due time is "All day", how the webpage
            # of a event is displayed.
            help_text=_("Only affects the rendering in the class calendar, "
            "in that a start time is not shown"),
            verbose_name=_('All day'))

    shown_in_calendar = models.BooleanField(default=True,
            verbose_name=_('Shown in calendar'))

    class Meta:
        verbose_name = _("Event")
        verbose_name_plural = _("Events")
        ordering = ("course", "time")
        unique_together = (("course", "kind", "ordinal"))

    def __unicode__(self):
        if self.ordinal is not None:
            return "%s %s" % (self.kind, self.ordinal)
        else:
            return self.kind

    if six.PY3:
        __str__ = __unicode__

# }}}


# {{{ participation

class ParticipationTag(models.Model):
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)
    name = models.CharField(max_length=100, unique=True,
            # Translators: name format of ParticipationTag
            help_text=_("Format is lower-case-with-hyphens. "
            "Do not use spaces."),
            verbose_name=_('Name of participation tag'))
    shown_to_participant = models.BooleanField(default=False,
            verbose_name=_('Shown to pariticpant'))

    def clean(self):
        super(ParticipationTag, self).clean()

        import re
        name_valid_re = re.compile(r"^\w+$")

        if name_valid_re.match(self.name) is None:
            # Translators: "Name" is the name of a ParticipationTag
            raise ValidationError(
                    {"name": _("Name contains invalid characters.")})

    def __unicode__(self):
        return "%s (%s)" % (self.name, self.course)

    if six.PY3:
        __str__ = __unicode__

    class Meta:
        verbose_name = _("Participation tag")
        verbose_name_plural = _("Participation tags")
        unique_together = (("course", "name"),)
        ordering = ("course", "name")


class ParticipationRole(models.Model):
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)
    identifier = models.CharField(
            max_length=100, blank=False, null=False,
            help_text=_("A symbolic name for this role, used in course code. "
            "lower_case_with_underscores, no spaces. May be any string. The "
            "name 'unenrolled' is special and refers to anyone not enrolled "
            "in the course."),
            verbose_name=_('Role identifier'))
    name = models.CharField(max_length=200, blank=False, null=False,
            help_text=_("A human-readable description of this role."),
            verbose_name=_('Role name'))

    is_default_for_new_participants = models.BooleanField(default=False,
            verbose_name=_('Is default role for new participants'))
    is_default_for_unenrolled = models.BooleanField(default=False,
            verbose_name=_('Is default role for unenrolled users'))

    def clean(self):
        super(ParticipationRole, self).clean()

        import re
        name_valid_re = re.compile(r"^\w+$")

        if name_valid_re.match(self.identifier) is None:
            # Translators: "Name" is the name of a ParticipationTag
            raise ValidationError(
                    {"name": _("Name contains invalid characters.")})

    def __unicode__(self):
        return _("%s in %s") % (self.identifier, self.course)

    if six.PY3:
        __str__ = __unicode__

    class Meta:
        verbose_name = _("Participation role")
        verbose_name_plural = _("Participation roles")
        unique_together = (("course", "identifier"),)
        ordering = ("course", "identifier")


class ParticipationPermissionBase(models.Model):
    permission = models.CharField(max_length=200, blank=False, null=False,
            choices=PARTICIPATION_PERMISSION_CHOICES,
            verbose_name=_('Permission'))
    argument = models.CharField(max_length=200, blank=True, null=True,
            verbose_name=_('Argument'))

    class Meta:
        abstract = True

    def __unicode__(self):
        if self.argument:
            return "%s %s" % (self.permission, self.argument)
        else:
            return self.permission

    if six.PY3:
        __str__ = __unicode__


class ParticipationRolePermission(ParticipationPermissionBase):
    role = models.ForeignKey(ParticipationRole,
            verbose_name=_('Role'), on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("Participation role permission")
        verbose_name_plural = _("Participation role permissions")
        unique_together = (("role", "permission", "argument"),)


class Participation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
            verbose_name=_('User ID'), on_delete=models.CASCADE,
            related_name="participations")
    course = models.ForeignKey(Course, related_name="participations",
            verbose_name=_('Course'), on_delete=models.CASCADE)

    enroll_time = models.DateTimeField(default=now,
            verbose_name=_('Enroll time'))
    role = models.CharField(max_length=50,
            verbose_name=_("Role (unused)"),)
    roles = models.ManyToManyField(ParticipationRole, blank=True,
            verbose_name=_("Roles"), related_name="participation")

    status = models.CharField(max_length=50,
            choices=PARTICIPATION_STATUS_CHOICES,
            verbose_name=_('Participation status'))

    time_factor = models.DecimalField(
            max_digits=10, decimal_places=2,
            default=1,
            help_text=_("Multiplier for time available on time-limited "
            "flows"),
            verbose_name=_('Time factor'))

    preview_git_commit_sha = models.CharField(max_length=200, null=True,
            blank=True,
            verbose_name=_('Preview git commit SHA'))

    tags = models.ManyToManyField(ParticipationTag, blank=True,
            verbose_name=_('Tags'))

    def __unicode__(self):
        # Translators: displayed format of Participation: some user in some
        # course as some role
        return _("%(user)s in %(course)s as %(role)s") % {
                "user": self.user, "course": self.course,
                "role": "/".join(
                    role.identifier
                    for role in self.roles.all())
                }

    if six.PY3:
        __str__ = __unicode__

    class Meta:
        verbose_name = _("Participation")
        verbose_name_plural = _("Participations")
        unique_together = (("user", "course"),)
        ordering = ("course", "user")

    def get_role_desc(self):
        return ", ".join(role.name for role in self.roles.all())

    # {{{ permissions handling

    def permissions(self):
        try:
            return self._permissions_cache
        except AttributeError:
            pass

        perm = (
                list(
                    ParticipationRolePermission.objects.filter(
                        role__course=self.course,
                        role__participation=self)
                    .values_list("permission", "argument"))
                +
                list(
                    ParticipationPermission.objects.filter(
                        participation=self)
                    .values_list("permission", "argument")))

        perm = frozenset(
                (permission, argument) if argument else (permission, None)
                for permission, argument in perm)

        self._permissions_cache = perm
        return perm

    def has_permission(self, perm, argument=None):
        return (perm, argument) in self.permissions()

    # }}}


class ParticipationPermission(ParticipationPermissionBase):
    participation = models.ForeignKey(Participation,
            verbose_name=_('Participation'), on_delete=models.CASCADE)

    class Meta:
        verbose_name = _("Participation permission")
        verbose_name_plural = _("Participation permissionss")
        unique_together = (("participation", "permission", "argument"),)


class ParticipationPreapproval(models.Model):
    email = models.EmailField(max_length=254, null=True, blank=True,
            verbose_name=_('Email'))
    institutional_id = models.CharField(max_length=254, null=True, blank=True,
            verbose_name=_('Institutional ID'))
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)
    role = models.CharField(max_length=50,
            verbose_name=_("Role (unused)"),)
    roles = models.ManyToManyField(ParticipationRole, blank=True,
            verbose_name=_("Roles"), related_name="+")

    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
            verbose_name=_('Creator'), on_delete=models.SET_NULL)
    creation_time = models.DateTimeField(default=now, db_index=True,
            verbose_name=_('Creation time'))

    def __unicode__(self):
        if self.email:
            # Translators: somebody's email in some course in Participation
            # Preapproval
            return _("Email %(email)s in %(course)s") % {
                "email": self.email, "course": self.course}
        elif self.institutional_id:
            # Translators: somebody's Institutional ID in some course in
            # Participation Preapproval
            return _("Institutional ID %(inst_id)s in %(course)s") % {
                    "inst_id": self.institutional_id, "course": self.course}

    if six.PY3:
        __str__ = __unicode__

    class Meta:
        verbose_name = _("Participation preapproval")
        verbose_name_plural = _("Participation preapprovals")
        unique_together = (("course", "email"),)
        ordering = ("course", "email")


def add_default_roles_and_permissions(course,
        role_model=ParticipationRole,
        role_permission_model=ParticipationRolePermission):
    from course.constants import participation_permission as pp

    rpm = role_permission_model

    def add_unenrolled_permissions(role):
        rpm(role=role, permission=pp.view_calendar).save()
        rpm(role=role, permission=pp.access_files_for,
                argument="unenrolled").save()
        rpm(role=role, permission=pp.access_files_for,
                argument="public").save()

    def add_student_permissions(role):
        rpm(role=role, permission=pp.send_instant_message).save()
        rpm(role=role, permission=pp.access_files_for,
                argument="student").save()

        add_unenrolled_permissions(role)

    def add_teaching_assistant_permissions(role):
        rpm(role=role, permission=pp.impersonate_role,
                argument="student").save()
        rpm(role=role, permission=pp.set_fake_time).save()
        rpm(role=role, permission=pp.set_pretend_facility).save()
        rpm(role=role, permission=pp.view_hidden_course_page).save()
        rpm(role=role, permission=pp.access_files_for,
                argument="ta").save()
        rpm(role=role, permission=pp.access_files_for,
                argument="in_exam").save()

        rpm(role=role, permission=pp.issue_exam_ticket).save()

        rpm(role=role, permission=pp.view_flow_sessions_from_role,
                argument="student").save()
        rpm(role=role, permission=pp.view_gradebook).save()
        rpm(role=role, permission=pp.assign_grade).save()
        rpm(role=role, permission=pp.view_grader_stats).save()

        rpm(role=role, permission=pp.impose_flow_session_deadline).save()
        rpm(role=role, permission=pp.end_flow_session).save()
        rpm(role=role, permission=pp.regrade_flow_session).save()
        rpm(role=role, permission=pp.recalculate_flow_session_grade).save()

        rpm(role=role, permission=pp.reopen_flow_session).save()
        rpm(role=role, permission=pp.grant_exception).save()
        rpm(role=role, permission=pp.view_analytics).save()

        rpm(role=role, permission=pp.preview_content).save()
        rpm(role=role, permission=pp.use_markup_sandbox).save()
        rpm(role=role, permission=pp.use_page_sandbox).save()
        rpm(role=role, permission=pp.test_flow).save()
        rpm(role=role, permission=pp.query_participation).save()
        rpm(role=role, permission=pp.edit_participation).save()

        add_student_permissions(role)

    def add_instructor_permisisons(role):
        rpm(role=role, permission=pp.use_admin_interface)
        rpm(role=role, permission=pp.impersonate_role,
                argument="ta").save()
        rpm(role=role, permission=pp.edit_course_permissions).save()
        rpm(role=role, permission=pp.edit_course).save()
        rpm(role=role, permission=pp.access_files_for,
                argument="instructor").save()

        rpm(role=role, permission=pp.edit_exam).save()
        rpm(role=role, permission=pp.batch_issue_exam_ticket).save()

        rpm(role=role, permission=pp.view_flow_sessions_from_role,
                argument="ta").save()
        rpm(role=role, permission=pp.edit_grading_opportunity).save()
        rpm(role=role, permission=pp.batch_import_grade).save()
        rpm(role=role, permission=pp.batch_export_grade).save()
        rpm(role=role, permission=pp.batch_download_submission).save()

        rpm(role=role, permission=pp.batch_impose_flow_session_deadline).save()
        rpm(role=role, permission=pp.batch_end_flow_session).save()
        rpm(role=role, permission=pp.batch_regrade_flow_session).save()
        rpm(role=role, permission=pp.batch_recalculate_flow_session_grade).save()

        rpm(role=role, permission=pp.update_content).save()
        rpm(role=role, permission=pp.edit_events).save()
        rpm(role=role, permission=pp.manage_instant_flow_requests).save()
        rpm(role=role, permission=pp.preapprove_participation).save()

        add_teaching_assistant_permissions(role)

    instructor = role_model(
            course=course, identifier="instructor",
            name=_("Instructor"))
    instructor.save()
    teaching_assistant = role_model(
            course=course, identifier="ta",
            name=_("Teaching Assistant"))
    teaching_assistant.save()
    student = role_model(
            course=course, identifier="student",
            name=_("Student"),
            is_default_for_new_participants=True)
    student.save()
    unenrolled = role_model(
            course=course, identifier="unenrolled",
            name=_("Unenrolled"),
            is_default_for_unenrolled=True)
    unenrolled.save()

    add_unenrolled_permissions(unenrolled)
    add_student_permissions(student)
    add_teaching_assistant_permissions(teaching_assistant)
    add_instructor_permisisons(instructor)


@receiver(post_save, sender=Course, dispatch_uid="add_default_permissions")
def _set_up_course_permissions(sender, instance, created, raw, using, update_fields,
        **kwargs):
    if created:
        add_default_roles_and_permissions(instance)

# }}}


# {{{ instant flow request

class InstantFlowRequest(models.Model):
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)
    flow_id = models.CharField(max_length=200,
            verbose_name=_('Flow ID'))
    start_time = models.DateTimeField(default=now,
            verbose_name=_('Start time'))
    end_time = models.DateTimeField(
            verbose_name=_('End time'))
    cancelled = models.BooleanField(default=False,
            verbose_name=_('Cancelled'))

    class Meta:
        verbose_name = _("Instant flow request")
        verbose_name_plural = _("Instant flow requests")

    def __unicode__(self):
        return _("Instant flow request for "
                "%(flow_id)s in %(course)s at %(start_time)s") \
                % {
                        "flow_id": self.flow_id,
                        "course": self.course,
                        "start_time": self.start_time,
                        }

    if six.PY3:
        __str__ = __unicode__

# }}}


# {{{ flow session

class FlowSession(models.Model):
    # This looks like it's redundant with 'participation', below--but it's not.
    # 'participation' is nullable.
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)

    participation = models.ForeignKey(Participation, null=True, blank=True,
            db_index=True, related_name="flow_sessions",
            verbose_name=_('Participation'), on_delete=models.CASCADE)

    # This looks like it's redundant with participation, above--but it's not.
    # Again--'participation' is nullable, and it is useful to be able to
    # remember what user a session belongs to, even if they're not enrolled.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
            verbose_name=_('User'), on_delete=models.SET_NULL)

    active_git_commit_sha = models.CharField(max_length=200,
            verbose_name=_('Active git commit SHA'))
    flow_id = models.CharField(max_length=200, db_index=True,
            verbose_name=_('Flow ID'))
    start_time = models.DateTimeField(default=now,
            verbose_name=_('Start time'))
    completion_time = models.DateTimeField(null=True, blank=True,
            verbose_name=_('Completion time'))
    page_count = models.IntegerField(null=True, blank=True,
            verbose_name=_('Page count'))

    # This field allows avoiding redundant checks for whether the
    # page data is in line with the course material and the current
    # version of RELATE.
    # See course.flow.adjust_flow_session_page_data.
    page_data_at_revision_key = models.CharField(
            max_length=200, null=True, blank=True,
            verbose_name=_('Page data at course revision'),
            help_text=_(
                "Page set-up data is up-to date for this revision of the "
                "course material"))

    in_progress = models.BooleanField(default=None,
            verbose_name=_('In progress'))
    access_rules_tag = models.CharField(max_length=200, null=True,
            blank=True,
            verbose_name=_('Access rules tag'))
    expiration_mode = models.CharField(max_length=20, null=True,
            default=flow_session_expiration_mode.end,
            choices=FLOW_SESSION_EXPIRATION_MODE_CHOICES,
            verbose_name=_('Expiration mode'))

    # Non-normal: These fields can be recomputed, albeit at great expense.
    #
    # Looking up the corresponding GradeChange is also invalid because
    # some flow sessions are not for credit and still have results.

    points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True,
            verbose_name=_('Points'))
    max_points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True,
            verbose_name=_('Max point'))
    result_comment = models.TextField(blank=True, null=True,
            verbose_name=_('Result comment'))

    class Meta:
        verbose_name = _("Flow session")
        verbose_name_plural = _("Flow sessions")
        ordering = ("course", "-start_time")

    def __unicode__(self):
        if self.participation is None:
            return _("anonymous session %(session_id)d on '%(flow_id)s'") % {
                    'session_id': self.id,
                    'flow_id': self.flow_id}
        else:
            return _("%(user)s's session %(session_id)d on '%(flow_id)s'") % {
                    'user': self.participation.user,
                    'session_id': self.id,
                    'flow_id': self.flow_id}

    if six.PY3:
        __str__ = __unicode__

    def append_comment(self, s):
        # type: (Text) -> None
        if s is None:
            return

        if self.result_comment:
            self.result_comment += "\n" + s
        else:
            self.result_comment = s

    def points_percentage(self):
        if self.points is None:
            return None
        elif self.max_points:
            return 100*self.points/self.max_points
        else:
            return None

    def answer_visits(self):
        # only use this from templates
        from course.flow import assemble_answer_visits
        return assemble_answer_visits(self)

    def last_activity(self):
        for visit in (FlowPageVisit.objects
                .filter(
                    flow_session=self,
                    answer__isnull=False,
                    is_synthetic=False)
                .order_by("-visit_time")
                [:1]):
            return visit.visit_time

        return None

    def get_expiration_mode_desc(self):
        return dict(FLOW_SESSION_EXPIRATION_MODE_CHOICES).get(
                self.expiration_mode)

# }}}


# {{{ flow page data

class FlowPageData(models.Model):
    flow_session = models.ForeignKey(FlowSession, related_name="page_data",
            verbose_name=_('Flow session'), on_delete=models.CASCADE)
    ordinal = models.IntegerField(null=True, blank=True,
            verbose_name=_('Ordinal'))

    # This exists to catch changing page types in course content,
    # which will generally lead to an inconsistency disaster.
    page_type = models.CharField(max_length=200,
            verbose_name=_('Page type as indicated in course content'),
            null=True, blank=True)

    group_id = models.CharField(max_length=200,
            verbose_name=_('Group ID'))
    page_id = models.CharField(max_length=200,
            verbose_name=_('Page ID'))

    data = JSONField(null=True, blank=True,
            # Show correct characters in admin for non ascii languages.
            dump_kwargs={'ensure_ascii': False},
            verbose_name=_('Data'))
    title = models.CharField(max_length=1000,
            verbose_name=_('Page Title'), null=True, blank=True)

    bookmarked = models.BooleanField(default=False,
            help_text=_("A user-facing 'marking' feature to allow participants to "
                "easily return to pages that still need their attention."),
            verbose_name=_('Bookmarked'))

    class Meta:
        verbose_name = _("Flow page data")
        verbose_name_plural = _("Flow page data")

    def __unicode__(self):
        # flow page data
        return (_("Data for page '%(group_id)s/%(page_id)s' "
                "(ordinal %(ordinal)s) in %(flow_session)s") % {
                    'group_id': self.group_id,
                    'page_id': self.page_id,
                    'ordinal': self.ordinal,
                    'flow_session': self.flow_session})

    if six.PY3:
        __str__ = __unicode__

    # Django's templates are a little daft. No arithmetic--really?
    def previous_ordinal(self):
        return self.ordinal - 1

    def next_ordinal(self):
        return self.ordinal + 1

    def human_readable_ordinal(self):
        return self.ordinal + 1

# }}}


# {{{ flow page visit

class FlowPageVisit(models.Model):
    # This is redundant (because the FlowSession is available through
    # page_data), but it helps the admin site understand the link
    # and provide editing.
    flow_session = models.ForeignKey(FlowSession, db_index=True,
            verbose_name=_('Flow session'), on_delete=models.CASCADE)

    page_data = models.ForeignKey(FlowPageData, db_index=True,
            verbose_name=_('Page data'), on_delete=models.CASCADE)
    visit_time = models.DateTimeField(default=now, db_index=True,
            verbose_name=_('Visit time'))
    remote_address = models.GenericIPAddressField(null=True, blank=True,
            verbose_name=_('Remote address'))

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
            blank=True, related_name="visitor",
            verbose_name=_('User'), on_delete=models.SET_NULL)
    impersonated_by = models.ForeignKey(settings.AUTH_USER_MODEL,
            null=True, blank=True, related_name="impersonator",
            verbose_name=_('Impersonated by'), on_delete=models.SET_NULL)

    is_synthetic = models.BooleanField(default=False,
            help_text=_("Synthetic flow page visits are generated for "
            "unvisited pages once a flow is finished. This is needed "
            "since grade information is attached to a visit, and it "
            "needs a place to go."),
            verbose_name=_('Is synthetic'))

    answer = JSONField(null=True, blank=True,
            # Show correct characters in admin for non ascii languages.
            dump_kwargs={'ensure_ascii': False},
            # Translators: "Answer" is a Noun.
            verbose_name=_('Answer'))

    # is_submitted_answer may seem redundant with answers being
    # non-NULL, but it isn't. This supports saved (but as
    # yet ungraded) answers.

    # NULL means it's not an answer at all.
    #   (Should coincide with 'answer is None')
    # True means it's a final, submitted answer fit for grading.
    # False means it's just a saved answer.
    is_submitted_answer = models.NullBooleanField(
            # Translators: determine whether the answer is a final,
            # submitted answer fit for grading.
            verbose_name=_('Is submitted answer'))

    def __unicode__(self):
        result = (
                # Translators: flow page visit
                _("'%(group_id)s/%(page_id)s' in '%(session)s' "
                "on %(time)s")
                % {"group_id": self.page_data.group_id,
                    "page_id": self.page_data.page_id,
                    "session": self.flow_session,
                    "time": self.visit_time})

        if self.answer is not None:
            # Translators: flow page visit: if an answer is
            # provided by user then append the string.
            result += six.text_type(_(" (with answer)"))

        return result

    if six.PY3:
        __str__ = __unicode__

    class Meta:
        verbose_name = _("Flow page visit")
        verbose_name_plural = _("Flow page visits")
        # These must be distinguishable, to figure out what came later.
        unique_together = (("page_data", "visit_time"),)

    def get_most_recent_grade(self):
        # type: () -> Optional[FlowPageVisitGrade]

        grades = self.grades.order_by("-grade_time")[:1]

        for grade in grades:
            return grade

        return None

    def get_most_recent_feedback(self):
        grade = self.get_most_recent_grade()

        if grade is None:
            return None
        else:
            return get_feedback_for_grade(grade)

    def is_impersonated(self):
        if self.impersonated_by:
            return True
        else:
            return False

# }}}


#  {{{ flow page visit grade

class FlowPageVisitGrade(models.Model):
    visit = models.ForeignKey(FlowPageVisit, related_name="grades",
            verbose_name=_('Visit'), on_delete=models.CASCADE)

    # NULL means 'autograded'
    grader = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
            verbose_name=_('Grader'), on_delete=models.SET_NULL)
    grade_time = models.DateTimeField(db_index=True, default=now,
            verbose_name=_('Grade time'))

    graded_at_git_commit_sha = models.CharField(
            max_length=200, null=True, blank=True,
            verbose_name=_('Graded at git commit SHA'))

    grade_data = JSONField(null=True, blank=True,
            # Show correct characters in admin for non ascii languages.
            dump_kwargs={'ensure_ascii': False},
            verbose_name=_('Grade data'))

    # This data should be recomputable, but we'll cache it here,
    # because it might be very expensive (container-launch expensive
    # for code questions, for example) to recompute.

    max_points = models.FloatField(null=True, blank=True,
            # Translators: max point in grade
            help_text=_("Point value of this question when receiving "
            "full credit."),
            verbose_name=_('Max points'))
    correctness = models.FloatField(null=True, blank=True,
            # Translators: correctness in grade
            help_text=_("Real number between zero and one (inclusively) "
            "indicating the degree of correctness of the answer."),
            verbose_name=_('Correctness'))

    # This JSON object has fields corresponding to
    # :class:`course.page.AnswerFeedback`, except for
    # :attr:`course.page.AnswerFeedback.correctness`, which is stored
    # separately for efficiency.

    feedback = JSONField(null=True, blank=True,
            # Show correct characters in admin for non ascii languages.
            dump_kwargs={'ensure_ascii': False},
            # Translators: "Feedback" stands for the feedback of answers.
            verbose_name=_('Feedback'))

    def percentage(self):
        if self.correctness is not None:
            return 100*self.correctness
        else:
            return None

    def value(self):
        if self.correctness is not None and self.max_points is not None:
            return self.correctness * self.max_points
        else:
            return None

    class Meta:
        verbose_name = _("Flow page visit grade")
        verbose_name_plural = _("Flow page visit grades")
        # These must be distinguishable, to figure out what came later.
        unique_together = (("visit", "grade_time"),)

        ordering = ("visit", "grade_time")

    def __unicode__(self):
        # information on FlowPageVisitGrade class
        # Translators: return the information of the grade of a user
        # by percentage.
        return _("grade of %(visit)s: %(percentage)s") % {
                "visit": self.visit, "percentage": self.percentage()}

    if six.PY3:
        __str__ = __unicode__


class FlowPageBulkFeedback(models.Model):
    # We're only storing one of these per page, because
    # they're 'bulk' (i.e. big, like plots or program output)
    page_data = models.OneToOneField(FlowPageData,
            verbose_name=_('Page data'), on_delete=models.CASCADE)
    grade = models.ForeignKey(FlowPageVisitGrade,
            verbose_name=_('Grade'), on_delete=models.CASCADE)

    bulk_feedback = JSONField(null=True, blank=True,
            # Show correct characters in admin for non ascii languages.
            dump_kwargs={'ensure_ascii': False},
            verbose_name=_('Bulk feedback'))


def update_bulk_feedback(page_data, grade, bulk_feedback_json):
    # type: (FlowPageData, FlowPageVisitGrade, Any) -> None
    FlowPageBulkFeedback.objects.update_or_create(
            page_data=page_data,
            defaults=dict(
                grade=grade,
                bulk_feedback=bulk_feedback_json))


def get_feedback_for_grade(grade):
    # type: (FlowPageVisitGrade) -> Optional[AnswerFeedback]

    try:
        bulk_feedback_json = FlowPageBulkFeedback.objects.get(
                page_data=grade.visit.page_data,
                grade=grade).bulk_feedback
    except ObjectDoesNotExist:
        bulk_feedback_json = None

    if grade is not None:
        return AnswerFeedback.from_json(
                grade.feedback, bulk_feedback_json)
    else:
        return None

# }}}


# {{{ flow access

def validate_stipulations(stip):
    if stip is None:
        return

    if not isinstance(stip, dict):
        raise ValidationError(_("stipulations must be a dictionary"))
    allowed_keys = set(["credit_percent", "allowed_session_count"])
    if not set(stip.keys()) <= allowed_keys:
        raise ValidationError(
                string_concat(
                    _("unrecognized keys in stipulations"),
                    ": %s")
                % ", ".join(set(stip.keys()) - allowed_keys))

    if "credit_percent" in stip and not isinstance(
            stip["credit_percent"], (int, float)):
        raise ValidationError(_("credit_percent must be a float"))
    if ("allowed_session_count" in stip
            and (
                not isinstance(stip["allowed_session_count"], int)
                or stip["allowed_session_count"] < 0)):
        raise ValidationError(
                _("'allowed_session_count' must be a non-negative integer"))


# {{{ deprecated exception stuff

class FlowAccessException(models.Model):
    # deprecated

    participation = models.ForeignKey(Participation, db_index=True,
            verbose_name=_('Participation'), on_delete=models.CASCADE)
    flow_id = models.CharField(max_length=200, blank=False, null=False,
            verbose_name=_('Flow ID'))
    expiration = models.DateTimeField(blank=True, null=True,
            verbose_name=_('Expiration'))

    stipulations = JSONField(blank=True, null=True,
            # Translators: help text for stipulations in FlowAccessException
            # (deprecated)
            help_text=_("A dictionary of the same things that can be added "
            "to a flow access rule, such as allowed_session_count or "
            "credit_percent. If not specified here, values will default "
            "to the stipulations in the course content."),
            validators=[validate_stipulations],
            dump_kwargs={'ensure_ascii': False},
            verbose_name=_('Stipulations'))

    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
            verbose_name=_('Creator'), on_delete=models.SET_NULL)
    creation_time = models.DateTimeField(default=now, db_index=True,
            verbose_name=_('Creation time'))

    is_sticky = models.BooleanField(
            default=False,
            # Translators: deprecated
            help_text=_("Check if a flow started under this "
            "exception rule set should stay "
            "under this rule set until it is expired."),
            # Translators: deprecated
            verbose_name=_('Is sticky'))

    comment = models.TextField(blank=True, null=True,
            verbose_name=_('Comment'))

    def __unicode__(self):
        return (
                # Translators: flow access exception in admin (deprecated)
                _("Access exception for '%(user)s' to '%(flow_id)s' "
                "in '%(course)s'") %
                {
                    "user": self.participation.user,
                    "flow_id": self.flow_id,
                    "course": self.participation.course
                    })

    if six.PY3:
        __str__ = __unicode__


class FlowAccessExceptionEntry(models.Model):
    # deprecated

    exception = models.ForeignKey(FlowAccessException,
            related_name="entries",
            verbose_name=_('Exception'), on_delete=models.CASCADE)
    permission = models.CharField(max_length=50,
            choices=FLOW_PERMISSION_CHOICES,
            verbose_name=_('Permission'))

    class Meta:
        # Translators: FlowAccessExceptionEntry (deprecated)
        verbose_name_plural = _("Flow access exception entries")

    def __unicode__(self):
        return self.permission

    if six.PY3:
        __str__ = __unicode__

# }}}


class FlowRuleException(models.Model):
    flow_id = models.CharField(max_length=200, blank=False, null=False,
            verbose_name=_('Flow ID'))
    participation = models.ForeignKey(Participation, db_index=True,
            verbose_name=_('Participation'), on_delete=models.CASCADE)
    expiration = models.DateTimeField(blank=True, null=True,
            verbose_name=_('Expiration'))

    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
            verbose_name=_('Creator'), on_delete=models.SET_NULL)
    creation_time = models.DateTimeField(default=now, db_index=True,
            verbose_name=_('Creation time'))

    comment = models.TextField(blank=True, null=True,
            verbose_name=_('Comment'))

    kind = models.CharField(max_length=50, blank=False, null=False,
            choices=FLOW_RULE_KIND_CHOICES,
            verbose_name=_('Kind'))
    rule = YAMLField(blank=False, null=False,
            verbose_name=_('Rule'))
    active = models.BooleanField(default=True,
            verbose_name=pgettext_lazy(
                "Is the flow rule exception activated?", "Active"))

    def __unicode__(self):
        return (
                # Translators: For FlowRuleException
                _("%(kind)s exception for '%(user)s' to '%(flow_id)s'"
                "in '%(course)s'")
                % {
                    "kind": self.kind,
                    "user": self.participation.user,
                    "flow_id": self.flow_id,
                    "course": self.participation.course})

    if six.PY3:
        __str__ = __unicode__

    def clean(self):
        super(FlowRuleException, self).clean()

        if (self.kind == flow_rule_kind.grading
                and self.expiration is not None):
            raise ValidationError(_("grading rules may not expire"))

        from course.validation import (
                ValidationError as ContentValidationError,
                validate_session_start_rule,
                validate_session_access_rule,
                validate_session_grading_rule,
                ValidationContext)
        from course.content import (get_course_repo,
                get_course_commit_sha,
                get_flow_desc)

        from relate.utils import dict_to_struct
        rule = dict_to_struct(self.rule)

        repo = get_course_repo(self.participation.course)
        commit_sha = get_course_commit_sha(
                self.participation.course, self.participation)
        ctx = ValidationContext(
                repo=repo,
                commit_sha=commit_sha)

        flow_desc = get_flow_desc(repo,
                self.participation.course,
                self.flow_id, commit_sha)

        tags = None
        grade_identifier = None
        if hasattr(flow_desc, "rules"):
            tags = getattr(flow_desc.rules, "tags", None)
            grade_identifier = flow_desc.rules.grade_identifier

        try:
            if self.kind == flow_rule_kind.start:
                validate_session_start_rule(ctx, six.text_type(self), rule, tags)
            elif self.kind == flow_rule_kind.access:
                validate_session_access_rule(ctx, six.text_type(self), rule, tags)
            elif self.kind == flow_rule_kind.grading:
                validate_session_grading_rule(
                        ctx, six.text_type(self), rule, tags,
                        grade_identifier)
            else:
                # the rule refers to FlowRuleException rule
                raise ValidationError(_("invalid rule kind: ")+self.kind)

        except ContentValidationError as e:
            # the rule refers to FlowRuleException rule
            raise ValidationError(_("invalid existing_session_rules: ")+str(e))

    class Meta:
        verbose_name = _("Flow rule exception")
        verbose_name_plural = _("Flow rule exceptions")

# }}}


# {{{ grading

class GradingOpportunity(models.Model):
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)

    identifier = models.CharField(max_length=200, blank=False, null=False,
            # Translators: format of identifier for GradingOpportunity
            help_text=_("A symbolic name for this grade. "
            "lower_case_with_underscores, no spaces."),
            verbose_name=_('Grading opportunity ID'))
    name = models.CharField(max_length=200, blank=False, null=False,
            # Translators: name for GradingOpportunity
            help_text=_("A human-readable identifier for the grade."),
            verbose_name=_('Grading opportunity name'))
    flow_id = models.CharField(max_length=200, blank=True, null=True,
            help_text=_("Flow identifier that this grading opportunity "
            "is linked to, if any"),
            verbose_name=_('Flow ID'))

    aggregation_strategy = models.CharField(max_length=20,
            choices=GRADE_AGGREGATION_STRATEGY_CHOICES,
            # Translators: strategy on how the grading of mutiple sessioins
            # are aggregated.
            verbose_name=_('Aggregation strategy'))

    due_time = models.DateTimeField(default=None, blank=True, null=True,
            verbose_name=_('Due time'))
    creation_time = models.DateTimeField(default=now,
            verbose_name=_('Creation time'))

    shown_in_grade_book = models.BooleanField(default=True,
            verbose_name=_('Shown in grade book'))
    shown_in_participant_grade_book = models.BooleanField(default=True,
            verbose_name=_("Shown in student grade book"))
    page_scores_in_participant_gradebook = models.BooleanField(default=False,
            verbose_name=_("Scores for individual pages are shown "
                "in the participants' grade book"))
    hide_superseded_grade_history_before = models.DateTimeField(
            verbose_name=_('Hide superseded grade history before'),
            blank=True, null=True,
            help_text=_(
                'Grade changes dated before this date that are '
                'superseded by later grade changes will not be shown to '
                'participants. '
                'This can help avoid discussions about pre-release grading '
                'adjustments.'
                'May be blank. In that case, the entire grade history is '
                'shown.'))

    class Meta:
        verbose_name = _("Grading opportunity")
        verbose_name_plural = _("Grading opportunities")
        ordering = ("course", "due_time", "identifier")
        unique_together = (("course", "identifier"),)

    def __unicode__(self):
        return (
                # Translators: For GradingOpportunity
                _("%(opportunity_name)s (%(opportunity_id)s) in %(course)s")
                % {
                    "opportunity_name": self.name,
                    "opportunity_id": self.identifier,
                    "course": self.course})

    if six.PY3:
        __str__ = __unicode__

    def get_aggregation_strategy_descr(self):
        return dict(GRADE_AGGREGATION_STRATEGY_CHOICES).get(
                self.aggregation_strategy)


class GradeChange(models.Model):
    """Per 'grading opportunity', each participant may accumulate multiple grades
    that are aggregated according to :attr:`GradingOpportunity.aggregation_strategy`.

    In addition, for each opportunity, grade changes are grouped by their 'attempt'
    identifier, where later grades with the same :attr:`attempt_id` supersede earlier
    ones.
    """
    opportunity = models.ForeignKey(GradingOpportunity,
            verbose_name=_('Grading opportunity'), on_delete=models.CASCADE)

    participation = models.ForeignKey(Participation,
            verbose_name=_('Participation'), on_delete=models.CASCADE)

    state = models.CharField(max_length=50,
            choices=GRADE_STATE_CHANGE_CHOICES,
            # Translators: something like 'status'.
            verbose_name=_('State'))

    attempt_id = models.CharField(max_length=50, null=True, blank=True,
            default="main",
            # Translators: help text of "attempt_id" in GradeChange class
            help_text=_("Grade changes are grouped by their 'attempt ID' "
            "where later grades with the same attempt ID supersede earlier "
            "ones."),
            verbose_name=_('Attempt ID'))

    points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True,
            verbose_name=_('Points'))
    max_points = models.DecimalField(max_digits=10, decimal_places=2,
            verbose_name=_('Max points'))

    comment = models.TextField(blank=True, null=True,
            verbose_name=_('Comment'))

    due_time = models.DateTimeField(default=None, blank=True, null=True,
            verbose_name=_('Due time'))

    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
            verbose_name=_('Creator'), on_delete=models.SET_NULL)
    grade_time = models.DateTimeField(default=now, db_index=True,
            verbose_name=_('Grade time'))

    flow_session = models.ForeignKey(FlowSession, null=True, blank=True,
            related_name="grade_changes",
            verbose_name=_('Flow session'), on_delete=models.SET_NULL)

    class Meta:
        verbose_name = _("Grade change")
        verbose_name_plural = _("Grade changes")
        ordering = ("opportunity", "participation", "grade_time")

    def __unicode__(self):
        # Translators: information for GradeChange
        return _("%(participation)s %(state)s on %(opportunityname)s") % {
            'participation': self.participation,
            'state': self.state,
            'opportunityname': self.opportunity.name}

    if six.PY3:
        __str__ = __unicode__

    def clean(self):
        super(GradeChange, self).clean()

        if self.opportunity.course != self.participation.course:
            raise ValidationError(_("Participation and opportunity must live "
                    "in the same course"))

    def percentage(self):
        # type: () -> Optional[float]

        if (self.max_points is not None
                and self.points is not None
                and self.max_points != 0):
            return 100*self.points/self.max_points
        else:
            return None

    def get_state_desc(self):
        return dict(GRADE_STATE_CHANGE_CHOICES).get(
                self.state)

# }}}


# {{{ grade state machine

class GradeStateMachine(object):
    def __init__(self):
        # type: () -> None
        self.opportunity = None

        self.state = None
        self._clear_grades()
        self.due_time = None
        self.last_graded_time = None
        self.last_report_time = None

        # applies to *all* grade changes
        self._last_grade_change_time = None

    def _clear_grades(self):
        # type: () -> None

        self.state = None
        self.last_grade_time = None
        self.valid_percentages = []  # type: List[GradeChange]
        self.attempt_id_to_gchange = {}  # type: Dict[Text, GradeChange]

    def _consume_grade_change(self, gchange, set_is_superseded):
        # type: (GradeChange, bool) -> None

        if self.opportunity is None:
            opp = self.opportunity = gchange.opportunity
            assert opp is not None
            self.due_time = opp.due_time
        else:
            assert self.opportunity.pk == gchange.opportunity.pk

        assert self.opportunity is not None

        # check that times are increasing
        if self._last_grade_change_time is not None:
            assert gchange.grade_time > self._last_grade_change_time
            self._last_grade_change_time = gchange.grade_time

        if gchange.state == grade_state_change_types.graded:
            if self.state == grade_state_change_types.unavailable:
                raise ValueError(
                        _("cannot accept grade once opportunity has been "
                            "marked 'unavailable'"))
            if self.state == grade_state_change_types.exempt:
                raise ValueError(
                        _("cannot accept grade once opportunity has been "
                        "marked 'exempt'"))

            #if self.due_time is not None and gchange.grade_time > self.due_time:
                #raise ValueError("cannot accept grade after due date")

            self.state = gchange.state
            if gchange.attempt_id is not None:
                if (set_is_superseded and
                        gchange.attempt_id in self.attempt_id_to_gchange):
                    self.attempt_id_to_gchange[gchange.attempt_id] \
                            .is_superseded = True
                self.attempt_id_to_gchange[gchange.attempt_id] \
                        = gchange
            else:
                self.valid_percentages.append(gchange.percentage())

            self.last_graded_time = gchange.grade_time

        elif gchange.state == grade_state_change_types.unavailable:
            self._clear_grades()
            self.state = gchange.state

        elif gchange.state == grade_state_change_types.do_over:
            self._clear_grades()

        elif gchange.state == grade_state_change_types.exempt:
            self._clear_grades()
            self.state = gchange.state

        elif gchange.state == grade_state_change_types.report_sent:
            self.last_report_time = gchange.grade_time

        elif gchange.state == grade_state_change_types.extension:
            self.due_time = gchange.due_time

        elif gchange.state in [
                grade_state_change_types.grading_started,
                grade_state_change_types.retrieved,
                ]:
            pass
        else:
            raise RuntimeError(
                    _("invalid grade change state '%s'") % gchange.state)

    def consume(self, iterable, set_is_superseded=False):
        # type: (Iterable[GradeChange], bool) -> GradeStateMachine

        for gchange in iterable:
            gchange.is_superseded = False
            self._consume_grade_change(gchange, set_is_superseded)

        valid_grade_changes = sorted(
                (gchange
                for gchange in self.attempt_id_to_gchange.values()
                if gchange.percentage() is not None),
                key=lambda gchange: gchange.grade_time)

        self.valid_percentages.extend(
                cast(GradeChange, gchange.percentage())
                for gchange in valid_grade_changes)

        del self.attempt_id_to_gchange

        return self

    def percentage(self):
        # type: () -> Optional[float]

        """
        :return: a percentage of achieved points, or *None*
        """
        if self.opportunity is None or not self.valid_percentages:
            return None

        strategy = self.opportunity.aggregation_strategy

        if strategy == grade_aggregation_strategy.max_grade:
            return max(self.valid_percentages)
        elif strategy == grade_aggregation_strategy.min_grade:
            return min(self.valid_percentages)
        elif strategy == grade_aggregation_strategy.avg_grade:
            return sum(self.valid_percentages)/len(self.valid_percentages)
        elif strategy == grade_aggregation_strategy.use_earliest:
            return self.valid_percentages[0]
        elif strategy == grade_aggregation_strategy.use_latest:
            return self.valid_percentages[-1]
        else:
            raise ValueError(
                    _("invalid grade aggregation strategy '%s'") % strategy)

    def stringify_state(self):
        if self.state is None:
            return u"- ∅ -"
        elif self.state == grade_state_change_types.exempt:
            return "_((exempt))"
        elif self.state == grade_state_change_types.graded:
            if self.valid_percentages:
                result = "%.1f%%" % self.percentage()
                if len(self.valid_percentages) > 1:
                    result += " (/%d)" % len(self.valid_percentages)
                return result
            else:
                return u"- ∅ -"
        else:
            return "_((other state))"

    def stringify_machine_readable_state(self):
        if self.state is None:
            return u"NONE"
        elif self.state == grade_state_change_types.exempt:
            return "EXEMPT"
        elif self.state == grade_state_change_types.graded:
            if self.valid_percentages:
                return "%.3f" % self.percentage()
            else:
                return u"NONE"
        else:
            return u"OTHER_STATE"

    def stringify_percentage(self):
        if self.state == grade_state_change_types.graded:
            if self.valid_percentages:
                return "%.1f" % self.percentage()
            else:
                return u""
        else:
            return ""
# }}}


# {{{ flow <-> grading integration

def get_flow_grading_opportunity(course, flow_id, flow_desc,
        grade_identifier, grade_aggregation_strategy):
    # type: (Course, Text, FlowDesc, Text, Text) -> GradingOpportunity

    default_name = (
            # Translators: display the name of a flow
            _("Flow: %(flow_desc_title)s")
            % {"flow_desc_title": flow_desc.title})

    gopp, created = GradingOpportunity.objects.get_or_create(
            course=course,
            identifier=grade_identifier,
            defaults=dict(
                name=default_name,
                flow_id=flow_id,
                aggregation_strategy=grade_aggregation_strategy,
                ))

    # update gopp.name when flow_desc.title changed
    if not created:
        if gopp.name != default_name:
            gopp.name = default_name
            gopp.save()

    return gopp

# }}}


# {{{ XMPP log

class InstantMessage(models.Model):
    participation = models.ForeignKey(Participation,
            verbose_name=_('Participation'), on_delete=models.CASCADE)
    text = models.CharField(max_length=200,
            verbose_name=_('Text'))
    time = models.DateTimeField(default=now,
            verbose_name=_('Time'))

    class Meta:
        verbose_name = _("Instant message")
        verbose_name_plural = _("Instant messages")
        ordering = ("participation__course", "time")

    def __unicode__(self):
        return "%s: %s" % (self.participation, self.text)

    if six.PY3:
        __str__ = __unicode__

# }}}


# {{{ exams

class Exam(models.Model):
    course = models.ForeignKey(Course,
            verbose_name=_('Course'), on_delete=models.CASCADE)
    description = models.CharField(max_length=200,
            verbose_name=_('Description'))
    flow_id = models.CharField(max_length=200,
            verbose_name=_('Flow ID'))
    active = models.BooleanField(
            default=True,
            verbose_name=_('Currently active'))

    no_exams_before = models.DateTimeField(
            verbose_name=_('No exams before'))
    no_exams_after = models.DateTimeField(
            null=True, blank=True,
            verbose_name=_('No exams after'))

    class Meta:
        verbose_name = _("Exam")
        verbose_name_plural = _("Exams")
        ordering = ("course", "no_exams_before",)

    def __unicode__(self):
        return _("Exam  %(description)s in %(course)s") % {
                'description': self.description,
                'course': self.course,
                }

    if six.PY3:
        __str__ = __unicode__


class ExamTicket(models.Model):
    exam = models.ForeignKey(Exam,
            verbose_name=_('Exam'), on_delete=models.CASCADE)

    participation = models.ForeignKey(Participation, db_index=True,
            verbose_name=_('Participation'), on_delete=models.CASCADE)

    creator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
            verbose_name=_('Creator'), on_delete=models.SET_NULL)
    creation_time = models.DateTimeField(default=now,
            verbose_name=_('Creation time'))
    usage_time = models.DateTimeField(
            verbose_name=_('Date and time of first usage of ticket'),
            null=True, blank=True)

    state = models.CharField(max_length=50,
            choices=EXAM_TICKET_STATE_CHOICES,
            verbose_name=_('Exam ticket state'))

    code = models.CharField(max_length=50, db_index=True, unique=True)

    class Meta:
        verbose_name = _("Exam ticket")
        verbose_name_plural = _("Exam tickets")
        ordering = ("exam__course", "-creation_time")
        permissions = (
                ("can_issue_exam_tickets", _("Can issue exam tickets to student")),
                )

    def __unicode__(self):
        return _("Exam  ticket for %(participation)s in %(exam)s") % {
                'participation': self.participation,
                'exam': self.exam,
                }

    if six.PY3:
        __str__ = __unicode__

    def clean(self):
        super(ExamTicket, self).clean()

        try:
            if self.exam.course != self.participation.course:
                raise ValidationError(_("Participation and exam must live "
                        "in the same course"))
        except ObjectDoesNotExist:
            pass

# }}}

# vim: foldmethod=marker
