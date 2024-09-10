from __future__ import annotations


__copyright__ = "Copyright (C) 2024 University of Illinois Board of Trustees"

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

from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from course.models import Course


FACILITY_ID_REGEX = "(?P<facility_id>[a-zA-Z][a-zA-Z0-9_]*)"


class Facility(models.Model):
    id = models.BigAutoField(primary_key=True)

    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    identifier = models.CharField(max_length=200, unique=True,
                validators=[RegexValidator(f"^{FACILITY_ID_REGEX}$")],
                db_index=True)

    description = models.TextField(blank=True, null=True)
    secret = models.CharField(max_length=220)

    class Meta:
        indexes = [
            models.Index(fields=["course", "identifier"]),
        ]
        verbose_name_plural = _("Facilities")

    def __str__(self) -> str:
        return f"PrairieTest Facility '{self.identifier}' in {self.course.identifier}"


class Event(models.Model):
    id = models.BigAutoField(primary_key=True)

    facility = models.ForeignKey(Facility, on_delete=models.CASCADE)
    event_id = models.UUIDField()
    created = models.DateTimeField(verbose_name=_("Created time"))
    received_time = models.DateTimeField(default=now,
            verbose_name=_("Received time"))

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["event_id"]),
            models.Index(fields=["created"]),
        ]


class AllowEvent(Event):
    user_uid = models.CharField(max_length=200)
    user_uin = models.CharField(max_length=200)
    exam_uuid = models.UUIDField()
    start = models.DateTimeField(verbose_name=_("Start time"))
    end = models.DateTimeField(verbose_name=_("End time"))
    cidr_blocks = models.JSONField()

    def __str__(self) -> str:
        return f"PrairieTest allow event {self.event_id} for {self.user_uid}"

    class Meta:
        indexes = [
            models.Index(fields=["user_uid", "exam_uuid", "start"]),
            models.Index(fields=["user_uid", "exam_uuid", "end"]),
        ]


class DenyEvent(Event):
    deny_uuid = models.UUIDField()
    start = models.DateTimeField(verbose_name=_("Start time"))
    end = models.DateTimeField(verbose_name=_("End time"))
    cidr_blocks = models.JSONField()

    def __str__(self) -> str:
        return f"PrairieTest deny event {self.event_id} with {self.deny_uuid}"

    class Meta:
        indexes = [
            models.Index(fields=["deny_uuid", "created"]),
            models.Index(fields=["deny_uuid", "start"]),
            models.Index(fields=["deny_uuid", "end"]),
        ]


class MostRecentDenyEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    deny_uuid = models.UUIDField(unique=True)
    end = models.DateTimeField(verbose_name=_("End time"))
    event = models.ForeignKey(DenyEvent, on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["end"]),
            ]

    def __str__(self) -> str:
        return f"PrairieTest current deny event with {self.deny_uuid}"


def save_deny_event(devt: DenyEvent) -> None:
    with transaction.atomic():
        devt.save()

        try:
            mrde = (MostRecentDenyEvent
                .objects.select_for_update().prefetch_related("event")
                .get(deny_uuid=devt.deny_uuid))
        except MostRecentDenyEvent.DoesNotExist:
            mrde = MostRecentDenyEvent(
                deny_uuid=devt.deny_uuid,
                end=devt.end,
                event=devt)
            mrde.save()

        if mrde.event.created < devt.created:
            mrde.end = devt.end
            mrde.event = devt
            mrde.save()
