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

from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError

from jsonfield import JSONField


# {{{ user status

class user_status:
    unconfirmed = "unconfirmed"
    active = "active"

USER_STATUS_CHOICES = (
        (user_status.unconfirmed, "Unconfirmed"),
        (user_status.active, "Active"),
        )


def get_user_status(user):
    try:
        return user.user_status
    except AttributeError:
        ustatus = UserStatus()
        ustatus.user = user
        ustatus.status = user_status.unconfirmed
        ustatus.save()

        return ustatus


class UserStatus(models.Model):
    user = models.OneToOneField(User, db_index=True, related_name="user_status")
    status = models.CharField(max_length=50,
            choices=USER_STATUS_CHOICES)
    sign_in_key = models.CharField(max_length=50,
            null=True, unique=True, db_index=True, blank=True)
    key_time = models.DateTimeField(default=now)

    class Meta:
        verbose_name_plural = "user statuses"
        ordering = ("key_time",)

    def __unicode__(self):
        return "User status for %s" % self.user

# }}}


# {{{ course

class Course(models.Model):
    identifier = models.CharField(max_length=200, unique=True,
            help_text="A course identifier. Alphanumeric with dashes, "
            "no spaces. This is visible in URLs and determines the location "
            "on your file system where the course's git repository lives.",
            db_index=True)

    hidden = models.BooleanField(
            default=True,
            help_text="Is the course only visible to course staff?")
    valid = models.BooleanField(
            default=True,
            help_text="Whether the course content has passed validation.")

    git_source = models.CharField(max_length=200, blank=True,
            help_text="A Git URL from which to pull course updates. "
            "If you're just starting out, enter "
            "<tt>git://github.com/inducer/courseflow-sample</tt> "
            "to get some sample content.")
    ssh_private_key = models.TextField(blank=True,
            help_text="An SSH private key to use for Git authentication")

    course_file = models.CharField(max_length=200,
            default="course.yml",
            help_text="Name of a YAML file in the git repository that contains "
            "the root course descriptor.")

    enrollment_approval_required = models.BooleanField(
            default=False,
            help_text="If set, each enrolling student must be "
            "individually approved.")
    enrollment_required_email_suffix = models.CharField(
            max_length=200, blank=True, null=True,
            help_text="Enrollee's email addresses must end in the "
            "specified suffix, such as '@illinois.edu'.")

    email = models.EmailField(
            help_text="This email address will be used in the 'From' line "
            "of automated emails sent by CourseFlow. It will also receive "
            "notifications about required approvals.")
    course_xmpp_id = models.CharField(max_length=200, blank=True)
    course_xmpp_password = models.CharField(max_length=200, blank=True)
    active_git_commit_sha = models.CharField(max_length=200, null=False,
            blank=False)

    participants = models.ManyToManyField(User,
            through='Participation')

    def __unicode__(self):
        return self.identifier

    def get_absolute_url(self):
        return reverse("course.views.course_page", args=(self.identifier,))

# }}}


class TimeLabel(models.Model):
    """A time label is an identifier that can be used to specify dates in
    course content.
    """

    course = models.ForeignKey(Course)
    kind = models.CharField(max_length=50,
            help_text="Should be lower_case_with_underscores, no spaces allowed.")
    ordinal = models.IntegerField(blank=True, null=True)

    time = models.DateTimeField()

    class Meta:
        ordering = ("course", "time")
        unique_together = (("course", "kind", "ordinal"))

    def __unicode__(self):
        if self.ordinal is not None:
            return "%s %s" % (self.kind, self.ordinal)
        else:
            return self.kind


# {{{ participation

class participation_role:
    instructor = "instructor"
    teaching_assistant = "ta"
    student = "student"
    unenrolled = "unenrolled"


PARTICIPATION_ROLE_CHOICES = (
        (participation_role.instructor, "Instructor"),
        (participation_role.teaching_assistant, "Teaching Assistant"),
        (participation_role.student, "Student"),
        # unenrolled is only used internally
        )


class participation_status:
    requested = "requested"
    active = "active"
    dropped = "dropped"
    denied = "denied"


PARTICIPATION_STATUS_CHOICES = (
        (participation_status.requested, "Requested"),
        (participation_status.active, "Active"),
        (participation_status.dropped, "Dropped"),
        (participation_status.denied, "Denied"),
        )


class Participation(models.Model):
    user = models.ForeignKey(User)
    course = models.ForeignKey(Course)

    enroll_time = models.DateTimeField(default=now)
    role = models.CharField(max_length=50,
            choices=PARTICIPATION_ROLE_CHOICES)
    temporary_role = models.CharField(max_length=50,
            choices=PARTICIPATION_ROLE_CHOICES, null=True, blank=True)
    status = models.CharField(max_length=50,
            choices=PARTICIPATION_STATUS_CHOICES)

    time_factor = models.DecimalField(
            max_digits=10, decimal_places=2,
            default=1)

    preview_git_commit_sha = models.CharField(max_length=200, null=True,
            blank=True)

    def __unicode__(self):
        return "%s in %s as %s" % (
                self.user, self.course, self.role)

    class Meta:
        unique_together = (("user", "course"),)
        ordering = ("course", "user")

# }}}


class InstantFlowRequest(models.Model):
    course = models.ForeignKey(Course)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)
    end_time = models.DateTimeField()


# {{{ flow session tracking

class FlowSession(models.Model):
    participation = models.ForeignKey(Participation, null=True, blank=True)
    active_git_commit_sha = models.CharField(max_length=200)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)
    completion_time = models.DateTimeField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)

    in_progress = models.BooleanField(default=None)
    for_credit = models.BooleanField(default=None)

    # Non-normal: These fields can be recomputed, albeit at great expense.
    #
    # Looking up the corresponding GradeChange is also invalid because
    # some flow sessions are not for credit and still have results.

    points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True)
    max_points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True)
    result_comment = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ("participation", "-start_time")

    def __unicode__(self):
        return "%s's session %d on '%s'" % (
                self.participation.user,
                self.id,
                self.flow_id)

    def percentage(self):
        return 100*self.points/self.max_points


class FlowPageData(models.Model):
    flow_session = models.ForeignKey(FlowSession)
    ordinal = models.IntegerField()

    group_id = models.CharField(max_length=200)
    page_id = models.CharField(max_length=200)

    data = JSONField(null=True, blank=True)

    class Meta:
        unique_together = (("flow_session", "ordinal"),)
        verbose_name_plural = "flow page data"

    def __unicode__(self):
        return "Data for %s's visit %d to '%s/%s' in '%s'" % (
                self.flow_session.participation.user,
                self.flow_session.id,
                self.group_id,
                self.page_id,
                self.flow_session.flow_id)

    # Django's templates are a little daft.
    def previous_ordinal(self):
        return self.ordinal - 1

    def next_ordinal(self):
        return self.ordinal + 1


class FlowPageVisit(models.Model):
    # This is redundant (because the FlowSession is available through
    # page_data), but it helps the admin site understand the link
    # and provide editing.
    flow_session = models.ForeignKey(FlowSession, db_index=True)

    page_data = models.ForeignKey(FlowPageData, db_index=True)
    visit_time = models.DateTimeField(default=now, db_index=True)

    answer = JSONField(null=True, blank=True)
    answer_is_final = models.NullBooleanField()

    grade_data = JSONField(null=True, blank=True)

    def __unicode__(self):
        return "%s's visit to '%s/%s' in '%s' on %s" % (
                self.flow_session.participation.user,
                self.page_data.group_id,
                self.page_data.page_id,
                self.flow_session.flow_id,
                self.visit_time)

    class Meta:
        unique_together = (("page_data", "visit_time"),)

# }}}


# {{{ flow access

class flow_permission:
    view = "view"
    view_past = "view_past"
    start_credit = "start_credit"
    start_no_credit = "start_no_credit"

    see_correctness = "see_correctness"
    see_answer = "see_answer"

FLOW_PERMISSION_CHOICES = (
        (flow_permission.view, "View flow"),
        (flow_permission.view_past, "Review past attempts"),
        (flow_permission.start_credit, "Start for-credit session"),
        (flow_permission.start_no_credit, "Start not-for-credit session"),
        (flow_permission.see_correctness, "See whether answer is correct"),
        (flow_permission.see_answer, "See the correct answer"),
        )


class FlowAccessException(models.Model):
    participation = models.ForeignKey(Participation, db_index=True)
    flow_id = models.CharField(max_length=200, blank=False, null=False)
    expiration = models.DateTimeField(blank=True, null=True)

    stipulations = JSONField(blank=True, null=True,
            help_text="A dictionary of the same things that can be added "
            "to a flow access rule, such as allowed_session_count or "
            "credit_percent. If not specified here, values will default "
            "to the stipulations in the course content.")

    creator = models.ForeignKey(User, null=True)
    creation_time = models.DateTimeField(default=now, db_index=True)

    def __unicode__(self):
        return "Access exception for '%s' to '%s' in '%s'" % (
                self.participation.user, self.flow_id,
                self.participation.course)


class FlowAccessExceptionEntry(models.Model):
    exception = models.ForeignKey(FlowAccessException,
            related_name="entries")
    permission = models.CharField(max_length=50,
            choices=FLOW_PERMISSION_CHOICES)

    def __unicode__(self):
        return self.permission

# }}}


# {{{ grading

class grade_aggregation_strategy:
    max_grade = "max_grade"
    avg_grade = "avg_grade"
    min_grade = "min_grade"

    use_earliest = "use_earliest"
    use_latest = "use_latest"


GRADE_AGGREGATION_STRATEGY_CHOICES = (
        (grade_aggregation_strategy.max_grade, "Use the max grade"),
        (grade_aggregation_strategy.avg_grade, "Use the avg grade"),
        (grade_aggregation_strategy.min_grade, "Use the min grade"),

        (grade_aggregation_strategy.use_earliest, "Use the earliest grade"),
        (grade_aggregation_strategy.use_latest, "Use the latest grade"),
        )


class GradingOpportunity(models.Model):
    course = models.ForeignKey(Course)

    identifier = models.CharField(max_length=200, blank=False, null=False,
            help_text="A symbolic name for this grade. "
            "lower_case_with_underscores, no spaces.")
    name = models.CharField(max_length=200, blank=False, null=False,
            help_text="A human-readable identifier for the grade.")
    flow_id = models.CharField(max_length=200, blank=True, null=True,
            help_text="Flow identifier that this grading opportunity "
            "is linked to, if any")

    aggregation_strategy = models.CharField(max_length=20,
            choices=GRADE_AGGREGATION_STRATEGY_CHOICES)

    due_time = models.DateTimeField(default=None, blank=True, null=True)

    class Meta:
        verbose_name_plural = "grading opportunities"
        ordering = ("course", "due_time", "identifier")
        unique_together = (("course", "identifier"),)

    def __unicode__(self):
        return "%s in %s" % (self.name, self.course)


class grade_state_change_types:
    grading_started = "grading_started"
    graded = "graded"
    retrieved = "retrieved"
    unavailable = "unavailable"
    extension = "extension"
    report_sent = "report_sent"
    do_over = "do_over"
    exempt = "exempt"


GRADE_STATE_CHANGE_CHOICES = (
        (grade_state_change_types.grading_started, 'Grading started'),
        (grade_state_change_types.graded, 'Graded'),
        (grade_state_change_types.retrieved, 'Retrieved'),
        (grade_state_change_types.unavailable, 'Unavailable'),
        (grade_state_change_types.extension, 'Extension'),
        (grade_state_change_types.report_sent, 'Report sent'),
        (grade_state_change_types.do_over, 'Do-over'),
        (grade_state_change_types.exempt, 'Exempt'),
        )


class GradeChange(models.Model):
    opportunity = models.ForeignKey(GradingOpportunity)

    participation = models.ForeignKey(Participation)

    state = models.CharField(max_length=50,
            choices=GRADE_STATE_CHANGE_CHOICES)

    points = models.DecimalField(max_digits=10, decimal_places=2,
            blank=True, null=True)
    max_points = models.DecimalField(max_digits=10, decimal_places=2)

    comment = models.TextField(blank=True, null=True)

    due_time = models.DateTimeField(default=None, blank=True, null=True)

    creator = models.ForeignKey(User, null=True)
    grade_time = models.DateTimeField(default=now, db_index=True)

    flow_session = models.ForeignKey(FlowSession, null=True, blank=True,
            related_name="grade_changes")

    class Meta:
        ordering = ("opportunity", "participation", "grade_time")

    def __unicode__(self):
        return "%s %s on %s" % (self.participation, self.state,
                self.opportunity.name)

    def clean(self):
        if self.opportunity.course != self.participation.course:
            raise ValidationError("Participation and opportunity must live "
                    "in the same course")

    def percentage(self):
        return 100*self.points/self.max_points

# }}}


# {{{ grade state machine

class GradeStateMachine(object):
    def __init__(self):
        self.opportunity = None

        self.state = None
        self._clear_grades()
        self.due_time = None
        self.last_report_time = None

        # applies to *all* grade changes
        self._last_grade_change_time = None

    def _clear_grades(self):
        self.state = None
        self.last_grade_time = None
        self.valid_percentages = []

    def _consume_grade_change(self, gchange):
        if self.opportunity is None:
            self.opportunity = gchange.opportunity
            self.due_time = self.opportunity.due_time
        else:
            assert self.opportunity.pk == gchange.opportunity.pk

        # check that times are increasing
        if self._last_grade_change_time is not None:
            assert gchange.grade_time > self._last_grade_change_time
            self._last_grade_change_time = gchange.grade_time

        if gchange.state == grade_state_change_types.graded:
            if self.state == grade_state_change_types.unavailable:
                raise ValueError("cannot accept grade once opportunity has been "
                        "marked 'unavailable'")
            if self.state == grade_state_change_types.exempt:
                raise ValueError("cannot accept grade once opportunity has been "
                        "marked 'exempt'")

            if self.due_time is not None and gchange.grade_time > self.due_time:
                raise ValueError("cannot accept grade after due date")

            self.state = gchange.state
            self.valid_percentages.append(gchange.percentage())

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
            raise RuntimeError("invalid grade change state '%s'" % gchange.state)

    def consume(self, iterable):
        for gchange in iterable:
            self._consume_grade_change(gchange)

        return self

    def percentage(self):
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
            raise ValueError("invalid grade aggregation strategy '%s'" % strategy)

# }}}


# {{{ flow <-> grading integration

def get_flow_grading_opportunity(course, flow_id, flow_desc):
    gopps = (GradingOpportunity.objects
            .filter(course=course)
            .filter(flow_id=flow_id))

    if gopps.count() == 0:
        gopp = GradingOpportunity()
        gopp.course = course
        gopp.identifier = "flow_"+flow_id.replace("-", "_")
        gopp.name = "Flow: %s" % flow_desc.title
        gopp.aggregation_strategy = flow_desc.grade_aggregation_strategy
        gopp.flow_id = flow_id
        gopp.save()

        return gopp
    else:
        gopp, = gopps
        return gopp

# }}}

# vim: foldmethod=marker
