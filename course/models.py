from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now


class Course(models.Model):
    name = models.CharField(max_length=200)
    identifier = models.CharField(max_length=200, unique=True)
    git_source = models.CharField(max_length=200, blank=True)
    xmpp_id = models.CharField(max_length=200, blank=True)
    active_git_revision = models.CharField(max_length=200)

    participants = models.ManyToManyField(User,
            through='Participation')


class role:
    instructor = "instructor"
    teaching_assistant = "ta"
    student = "student"


ROLE_CHOICES = (
        (role.instructor, "Instructor"),
        (role.teaching_assistant, "Teaching Assistant"),
        (role.student, "Student"),
        )


class status:
    requested = "requested"
    email_confirmed = "email_confirmed"
    active = "active"
    dropped = "dropped"


STATUS_CHOICES = (
        (status.requested, "Requested"),
        (status.email_confirmed, "email_confirmed"),
        (status.active, "Active"),
        (status.dropped, "Dropped"),
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


class InstantFlowRequest(models.Model):
    course = models.ForeignKey(Course)
    flow_id = models.CharField(max_length=200)
    start_time = models.DateTimeField(default=now)
    end_time = models.DateTimeField()


class FlowVisit(models.Model):
    enrollment = models.ForeignKey(User)
    git_revision = models.CharField(max_length=200)
    flow_id = models.CharField(max_length=200)
    attempt_time = models.DateTimeField(default=now)


class FlowGroupVisit(models.Model):
    flow_visit = models.ForeignKey(FlowVisit)
    flow_group_id = models.CharField(max_length=200)


class FlowPage(models.Model):
    ordinal = models.IntegerField()
    flow_group_visit = models.ForeignKey(FlowGroupVisit)

    page_id = models.CharField(max_length=200)
    visit_time = models.DateTimeField(default=now)
    answer_time = models.DateTimeField(default=now)
    answer_value = models.CharField(max_length=200)
    points = models.DecimalField(max_digits=10, decimal_places=2)
