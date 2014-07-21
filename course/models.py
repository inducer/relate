from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError

from jsonfield import JSONField


# {{{ user status

class user_status:
    requested = "requested"
    active = "active"

USER_STATUS_CHOICES = (
        (user_status.requested, "Requested"),
        (user_status.active, "Active"),
        )


class UserStatus(models.Model):
    user = models.OneToOneField(User, db_index=True)
    status = models.CharField(max_length=50,
            choices=USER_STATUS_CHOICES)
    registration_key = models.CharField(max_length=50,
            null=True, unique=True, db_index=True)
    key_time = models.DateTimeField(default=now)

    class Meta:
        verbose_name_plural = "user statuses"
        ordering = ("key_time",)
# }}}


# {{{ course

class Course(models.Model):
    identifier = models.CharField(max_length=200, unique=True,
            help_text="A URL identifier. Alphanumeric with dashes, "
            "no spaces",
            db_index=True)
    git_source = models.CharField(max_length=200, blank=True,
            help_text="A Git URL from which to pull course updates")
    ssh_private_key = models.CharField(max_length=2000, blank=True,
            help_text="An SSH private key to use for Git authentication")

    enrollment_approval_required = models.BooleanField(
            default=False)
    enrollment_required_email_suffix = models.CharField(
            max_length=200, blank=True, null=True)

    course_robot_email_address = models.EmailField()
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


class TimeMark(models.Model):
    """A time mark is an identifier that can be used in datespecs in lecture content.
    """

    course = models.ForeignKey(Course)
    kind = models.CharField(max_length=50,
            help_text="Should be lower_case_with_underscores, no spaces allowed.")
    ordinal = models.IntegerField(blank=True, null=True)

    time = models.DateTimeField()

    class Meta:
        ordering = ("course", "time")


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


PARTICIPATION_STATUS_CHOICES = (
        (participation_status.requested, "Requested"),
        (participation_status.active, "Active"),
        (participation_status.dropped, "Dropped"),
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


# {{{ flow visit tracking

class flow_visit_state:
    in_progress = "in_progress"
    expired = "expired"
    completed = "completed"


FLOW_VISIT_STATE_CHOICES = (
        (flow_visit_state.in_progress, "In progress"),
        (flow_visit_state.expired, "Expired"),
        (flow_visit_state.completed, "Completed"),
        )


class FlowVisit(models.Model):
    participation = models.ForeignKey(Participation, null=True, blank=True)
    active_git_commit_sha = models.CharField(max_length=200)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)
    completion_time = models.DateTimeField(null=True, blank=True)

    state = models.CharField(max_length=50, choices=FLOW_VISIT_STATE_CHOICES)

    class Meta:
        ordering = ("participation",)


class FlowPageData(models.Model):
    flow_visit = models.ForeignKey(FlowVisit)
    ordinal = models.IntegerField()

    group_id = models.CharField(max_length=200)
    page_id = models.CharField(max_length=200)

    data = JSONField(null=True, blank=True)

    class Meta:
        unique_together = (("flow_visit", "ordinal"),)
        verbose_name_plural = "flow page data"

    def __unicode__(self):
        return "Data for %s's visit %d to '%s/%s' in '%s'" % (
                self.flow_visit.participation.user,
                self.flow_visit.id,
                self.group_id,
                self.page_id,
                self.flow_visit.flow_id)


class FlowPageVisit(models.Model):
    page_data = models.ForeignKey(FlowPageData, db_index=True)
    visit_time = models.DateTimeField(default=now, db_index=True)

    answer = JSONField(null=True, blank=True)

# }}}


# {{{ flow access

class flow_permission:
    # access flow start page
    view = "view"

    # review past attempts
    view_past = "view_past"

    # start new for-credit visit
    start_credit = "start_credit"

    # start new not-for-credit visit
    start_no_credit = "start_no_credit"

    # see correct answer
    see_correct_answer = "see_correct_answer"

FLOW_PERMISSION_CHOICES = (
        (flow_permission.view, "View flow start page"),
        (flow_permission.view_past, "Review past attempts"),
        (flow_permission.start_credit, "Start for-credit visit"),
        (flow_permission.start_no_credit, "Start not-for-credit visit"),
        (flow_permission.see_correct_answer, "See correct answer"),
        )


class FlowAccessException(models.Model):
    participation = models.ForeignKey(Participation, db_index=True)
    flow_id = models.CharField(max_length=200, blank=False, null=False)
    expiration = models.DateTimeField(blank=True, null=True)

    stipulations = JSONField(blank=True, null=True)

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

    max_points = models.DecimalField(max_digits=10, decimal_places=2)

    due_time = models.DateTimeField(default=None, blank=True, null=True)

    class Meta:
        verbose_name_plural = "grading opportunities"
        ordering = ("course", "due_time", "identifier")

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
    comment = models.TextField(blank=True, null=True)

    due_time = models.DateTimeField(default=None, blank=True, null=True)

    creator = models.ForeignKey(User, null=True)
    grade_time = models.DateTimeField(default=now, db_index=True)

    class Meta:
        ordering = ("opportunity", "participation", "grade_time")

    def __unicode__(self):
        return "%s %s on %s" % (self.participation, self.state,
                self.opportunity.name)

    def clean(self):
        if self.opportunity.course != self.participation.course:
            raise ValidationError("Participation and opportunity must live "
                    "in the same course")

# }}}

# vim: foldmethod=marker
