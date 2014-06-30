from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.urlresolvers import reverse


class user_status:
    requested = "requested"
    active = "active"

USER_STATUS_CHOICES = (
        (user_status.requested, "Requested"),
        (user_status.active, "Active"),
        )


class UserStatus(models.Model):
    user = models.OneToOneField(User)
    status = models.CharField(max_length=50,
            choices=USER_STATUS_CHOICES)
    registration_key = models.CharField(max_length=50,
            null=True, unique=True, db_index=True)


class Course(models.Model):
    identifier = models.CharField(max_length=200, unique=True,
            help_text="A URL identifier. Alphanumeric with dashes, "
            "no spaces",
            db_index=True)
    git_source = models.CharField(max_length=200, blank=True,
            help_text="A Git URL from which to pull course updates")
    ssh_private_key = models.CharField(max_length=2000, blank=True,
            help_text="An SSH private key to use for Git authentication")
    xmpp_id = models.CharField(max_length=200, blank=True,
            help_text="An XMPP ID")
    xmpp_password = models.CharField(max_length=200, blank=True,
            help_text="An XMPP ID")
    active_git_commit_sha = models.CharField(max_length=200, null=True,
            blank=True)

    participants = models.ManyToManyField(User,
            through='Participation')

    def __unicode__(self):
        return self.identifier

    def get_absolute_url(self):
        return reverse("course.views.course_page", args=(self.identifier,))


class participation_role:
    instructor = "instructor"
    teaching_assistant = "ta"
    student = "student"
    unenrolled = "student"


PARTICIPATION_ROLE_CHOICES = (
        (participation_role.instructor, "Instructor"),
        (participation_role.teaching_assistant, "Teaching Assistant"),
        (participation_role.student, "Student"),
        # unenrolled is only used internally
        )


class participation_status:
    requested = "requested"
    email_confirmed = "email_confirmed"
    active = "active"
    dropped = "dropped"


PARTICIPATION_STATUS_CHOICES = (
        (participation_status.requested, "Requested"),
        (participation_status.email_confirmed, "Email confirmed"),
        (participation_status.active, "Active"),
        (participation_status.dropped, "Dropped"),
        )


class Participation(models.Model):
    user = models.ForeignKey(User)
    course = models.ForeignKey(Course)

    enroll_time = models.DateTimeField(default=now)
    role = models.CharField(max_length=50,
            choices=PARTICIPATION_ROLE_CHOICES)
    status = models.CharField(max_length=50,
            choices=PARTICIPATION_STATUS_CHOICES)

    time_factor = models.DecimalField(
            max_digits=10, decimal_places=2,
            default=1)

    def __unicode__(self):
        return "%s in %s as %s" % (
                self.user, self.course, self.role)


class InstantFlowRequest(models.Model):
    course = models.ForeignKey(Course)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)
    end_time = models.DateTimeField()


class flow_visit_state:
    in_progress = "in_progress"
    expired = "expired"
    completed = "completed"


class FlowVisit(models.Model):
    participation = models.ForeignKey(Participation)
    active_git_commit_sha = models.CharField(max_length=200)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)

    state = models.CharField(max_length=50)


class FlowPageVisit(models.Model):
    ordinal = models.IntegerField()
    flow_visit = models.ForeignKey(FlowVisit)

    page_id = models.CharField(max_length=200)
    visit_time = models.DateTimeField(default=now)
    answer_time = models.DateTimeField(default=now)
    answer_value = models.CharField(max_length=200)
    points = models.DecimalField(max_digits=10, decimal_places=2)
