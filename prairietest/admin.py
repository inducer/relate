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

from typing import TYPE_CHECKING

from django import forms, http
from django.contrib import admin
from django.db.models import QuerySet
from django.urls import reverse
from django.utils.safestring import mark_safe

from accounts.models import User
from course.constants import participation_permission as pperm
from prairietest.models import AllowEvent, DenyEvent, Facility, MostRecentDenyEvent


if TYPE_CHECKING:
    from accounts.models import User


class FacilityAdminForm(forms.ModelForm):
    class Meta:
        model = Facility
        fields = "__all__"
        widgets = {
            "secret": forms.PasswordInput(render_value=True),
        }


@admin.register(Facility)
class FacilityAdmin(admin.ModelAdmin):
    def get_queryset(self, request: http.HttpRequest) -> QuerySet:
        assert request.user.is_authenticated

        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        from course.admin import _filter_course_linked_obj_for_user
        return _filter_course_linked_obj_for_user(qs, request.user)

    def webhook_url(self, obj: Facility) -> str:
        url = reverse(
                "prairietest:webhook",
                args=(obj.course.identifier, obj.identifier),
            )
        return mark_safe(
            f"<tt>https://YOUR-HOST{url}</tt> Make sure to include the trailing slash!")

    list_display = ["course", "identifier", "webhook_url"]
    list_display_links = ["identifier"]
    list_filter = ["course", "identifier"]

    form = FacilityAdminForm


def _filter_events_for_user(queryset: QuerySet, user: User) -> QuerySet:
    if user.is_superuser:
        return queryset
    return queryset.filter(
        facility__course__participations__user=user,
        facility__course__participations__roles__permissions__permission=pperm.use_admin_interface)


@admin.register(AllowEvent)
class AllowEventAdmin(admin.ModelAdmin):
    def get_queryset(self, request: http.HttpRequest) -> QuerySet:
        assert request.user.is_authenticated

        qs = super().get_queryset(request)
        return _filter_events_for_user(qs, request.user)

    list_display = [
        "event_id", "facility", "user_uid", "start", "end", "exam_uuid"]
    list_filter = ["facility", "user_uid", "exam_uuid"]


@admin.register(DenyEvent)
class DenyEventAdmin(admin.ModelAdmin):
    def get_queryset(self, request: http.HttpRequest) -> QuerySet:
        assert request.user.is_authenticated

        qs = super().get_queryset(request)
        return _filter_events_for_user(qs, request.user)

    list_display = [
        "event_id", "facility", "start", "end", "deny_uuid"]
    list_filter = ["facility"]


@admin.register(MostRecentDenyEvent)
class MostRecentDenyEventAdmin(admin.ModelAdmin):
    def get_queryset(self, request: http.HttpRequest) -> QuerySet:
        assert request.user.is_authenticated

        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(
            event__facility__course__participations__user=request.user,
            event__facility__course__participations__roles__permissions__permission=pperm.use_admin_interface)

    list_display = ["deny_uuid", "end"]
