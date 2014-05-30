from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.core.urlresolvers import reverse


class Course(models.Model):
    identifier = models.CharField(max_length=200, unique=True,
            help_text="A URL identifier. Alphanumeric with dashes, "
            "no spaces.",
            db_index=True)
    git_source = models.CharField(max_length=200, blank=True,
            help_text="A Git URL from which to pull course updates.")
    xmpp_id = models.CharField(max_length=200, blank=True,
            help_text="An XMPP ID")
    active_git_commit_sha = models.CharField(max_length=200, null=True)

    participants = models.ManyToManyField(User,
            through='Participation')

    def __unicode__(self):
        return self.identifier

    def get_absolute_url(self):
        return reverse("course.views.course_page", args=(self.identifier,))



class role:
    instructor = "instructor"
    teaching_assistant = "ta"
    student = "student"
    unenrolled = "student"


ROLE_CHOICES = (
        (role.instructor, "Instructor"),
        (role.teaching_assistant, "Teaching Assistant"),
        (role.student, "Student"),
        # unenrolled is only used internally
        )


class participation_status:
    requested = "requested"
    email_confirmed = "email_confirmed"
    active = "active"
    dropped = "dropped"


STATUS_CHOICES = (
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
            choices=ROLE_CHOICES)
    status = models.CharField(max_length=50,
            choices=STATUS_CHOICES)

    registration_key = models.CharField(max_length=50)

    #time_factor = models.DecimalField(max_digits=10, decimal_places=2)


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


# {{{ sync commands

class sync_commands:
    update = "update"


SYNC_COMMAND_CHOICES = (
        (sync_commands.update, "Update"),
        )

class sync_command_status:
    waiting = "waiting"
    running = "running"
    error = "error"
    success = "success"

class sync_commands:
    update = "update"

class SyncCommand(models.Model):
    course = models.ForeignKey(Course)
    command = models.CharField(max_length=200,
            choices=SYNC_COMMAND_CHOICES)
    command_timestamp = models.DateTimeField(default=now)
    status = models.CharField(max_length=200)
    status_timestamp = models.DateTimeField(default=now)
    message = models.CharField(max_length=2000)

# }}}
