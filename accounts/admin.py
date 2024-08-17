from __future__ import annotations


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


from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as UserAdminBase
from django.utils.translation import gettext_lazy as _

from course.admin import _filter_course_linked_obj_for_user, _filter_courses_for_user
from course.models import Course, Participation

from .models import User


def _get_filter_participations_for_user(user):
    participations = Participation.objects.all()
    if not user.is_superuser:
        participations = _filter_course_linked_obj_for_user(participations, user)
    return participations


class CourseListFilter(admin.SimpleListFilter):
    title = _("Course")
    parameter_name = "course__identifier"

    def lookups(self, request, model_admin):
        course_identifiers = (
            _filter_courses_for_user(Course.objects, request.user)
            .values_list("identifier", flat=True))
        return zip(course_identifiers, course_identifiers, strict=True)

    def queryset(self, request, queryset):
        if self.value():
            participations = (
                _get_filter_participations_for_user(request.user)
                .filter(course__identifier=self.value()))
            return queryset.filter(pk__in=participations.values_list("user__pk"))
        else:
            return queryset


@admin.register(User)
class UserAdmin(UserAdminBase):
    save_on_top = True

    list_display = (*tuple(UserAdminBase.list_display),
        "name_verified", "status", "institutional_id", "institutional_id_verified")
    list_editable = ("first_name", "last_name",
            "name_verified",
            "status",
            "institutional_id", "institutional_id_verified",
            "name_verified",)
    list_filter = (
            *UserAdminBase.list_filter,
            "status", CourseListFilter)  # type: ignore
    search_fields = (*tuple(UserAdminBase.search_fields), "institutional_id")

    fieldsets = UserAdminBase.fieldsets[:1] + (
            (UserAdminBase.fieldsets[1][0], {"fields": (
                "status",
                "first_name",
                "last_name",
                "name_verified",
                "email",
                "institutional_id",
                "institutional_id_verified",
                "editor_mode",)
                }),
            ) + UserAdminBase.fieldsets[2:]
    ordering = ["-date_joined"]

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if request is not None and request.user.is_superuser:
            return fieldsets
        return tuple(
            fields for fields in fieldsets
             if "is_superuser" not in fields[1]["fields"]
             and "is_staff" not in fields[1]["fields"]
             and "user_permissions" not in fields[1]["fields"])

    def get_list_display(self, request):
        list_display = super().get_list_display(request)
        if request is not None and request.user.is_superuser:
            return list_display
        return tuple(f for f in list_display if f != "is_staff")

    def get_list_filter(self, request):
        list_filter = super().get_list_filter(request)
        if request is not None and request.user.is_superuser:
            return list_filter
        return tuple(f for f in list_filter if f != "is_staff")
