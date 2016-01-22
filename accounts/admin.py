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


from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as UserAdminBase
from django.utils.translation import ugettext_lazy as _  # noqa
from . models import User


def _remove_from_fieldsets(fs, field_name):
    return tuple(
        (heading, {"fields":
            tuple(
                f for f in props["fields"]
                if f != field_name)})
        for heading, props in fs)


class UserAdmin(UserAdminBase):
    # list_display = tuple(
    #         f for f in UserAdminBase.list_display
    #         if f != "is_staff")
    # list_filter = tuple(
    #         f for f in UserAdminBase.list_filter
    #         if f != "is_staff")
    # fieldsets = _remove_from_fieldsets(
    #         UserAdminBase.fieldsets, "is_staff")

    list_display = tuple(UserAdminBase.list_display) + (
            "name_verified",
            "status",
            "institutional_id", "institutional_id_verified",
            )
    list_editable = ("first_name", "last_name",
            "name_verified",
            "status",
            "institutional_id", "institutional_id_verified",
            "name_verified",)
    list_filter = tuple(UserAdminBase.list_filter) + (
            "status", "participations__course")
    search_fields = tuple(UserAdminBase.search_fields) + (
            "institutional_id",)

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


admin.site.register(User, UserAdmin)
