# -*- coding: utf-8 -*-

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
from course.models import (
        UserStatus,
        Course, Event,
        Participation, ParticipationPreapproval,
        InstantFlowRequest,
        FlowSession, FlowPageData,
        FlowPageVisit, FlowPageVisitGrade,
        FlowAccessException, FlowAccessExceptionEntry,
        GradingOpportunity, GradeChange, InstantMessage)
from django import forms
from course.enrollment import (approve_enrollment, deny_enrollment)


# {{{ user status

class UserStatusAdmin(admin.ModelAdmin):
    def get_user_first_name(self, obj):
        return obj.user.first_name

    get_user_first_name.short_description = "First name"
    get_user_first_name.admin_order_field = "user__first_name"

    def get_user_last_name(self, obj):
        return obj.user.last_name

    get_user_last_name.short_description = "Last name"
    get_user_last_name.admin_order_field = "user__last_name"

    list_display = (
            "user",
            "get_user_first_name",
            "get_user_last_name",
            "status",
            "key_time")
    list_filter = ("status",)

    date_hierarchy = "key_time"

    search_fields = (
            "user__username",
            "user__first_name",
            "user__last_name",
            )

    def __unicode__(self):
        return u"%s in status %s" % (self.user, self.status)

admin.site.register(UserStatus, UserStatusAdmin)

# }}}


class UnsafePasswordInput(forms.TextInput):
    # This sends passwords back to the user--not ideal, but OK for the XMPP
    # password.
    input_type = 'password'


class CourseAdminForm(forms.ModelForm):
    class Meta:
        model = Course
        widgets = {
                "course_xmpp_password": UnsafePasswordInput
                }
        exclude = ()


class CourseAdmin(admin.ModelAdmin):
    list_display = ("identifier", "hidden", "valid")
    list_filter = ("hidden", "valid",)

    form = CourseAdminForm

    save_on_top = True

admin.site.register(Course, CourseAdmin)


# {{{ events

class EventAdmin(admin.ModelAdmin):
    list_display = ("course", "kind", "ordinal", "time", "end_time")
    list_filter = ("course", "kind")

    date_hierarchy = "time"

    def __unicode__(self):
        return u"%s %d in %s" % (self.kind, self.ordinal, self.course)

    list_editable = ("ordinal", "time", "end_time")

admin.site.register(Event, EventAdmin)

# }}}


# {{{ participation

class ParticipationAdmin(admin.ModelAdmin):
    def get_user_first_name(self, obj):
        return obj.user.first_name

    get_user_first_name.short_description = "First name"
    get_user_first_name.admin_order_field = "participation__user__first_name"

    def get_user_last_name(self, obj):
        return obj.user.last_name

    get_user_last_name.short_description = "Last name"
    get_user_last_name.admin_order_field = "participation__user__last_name"

    list_display = (
            "user",
            "get_user_first_name",
            "get_user_last_name",
            "course",
            "role",
            "status",
            "enroll_time")
    list_filter = ("course", "role", "status")

    search_fields = (
            "course__identifier",
            "user__username",
            "user__first_name",
            "user__last_name",
            )

    actions = [approve_enrollment, deny_enrollment]

admin.site.register(Participation, ParticipationAdmin)


class ParticipationPreapprovalAdmin(admin.ModelAdmin):
    list_display = ["email", "course", "role"]
    list_filter = ["course", "role"]

    search_fields = (
            "email",
            )

admin.site.register(ParticipationPreapproval, ParticipationPreapprovalAdmin)

# }}}


class InstantFlowRequestAdmin(admin.ModelAdmin):
    pass

admin.site.register(InstantFlowRequest, InstantFlowRequestAdmin)


# {{{ flow sessions

class FlowPageDataInline(admin.TabularInline):
    model = FlowPageData
    extra = 0


class FlowSessionAdmin(admin.ModelAdmin):
    def get_participant(self, obj):
        if obj.participation is None:
            return None

        return obj.participation.user

    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "participation__user"

    search_fields = (
            "id",
            "flow_id",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            )

    list_display = (
            "flow_id",
            "get_participant",
            "course",
            "start_time",
            "in_progress",
            "for_credit",
            )
    list_display_links = (
            "flow_id",
            "get_participant",
            )

    date_hierarchy = "start_time"

    list_filter = (
            "course",
            "flow_id",
            "in_progress",
            "for_credit",
            )

    inlines = (FlowPageDataInline,)

    raw_id_fields = ("participation",)

    save_on_top = True

admin.site.register(FlowSession, FlowSessionAdmin)

# }}}


# {{{ flow page visit

class FlowPageVisitGradeInline(admin.TabularInline):
    model = FlowPageVisitGrade
    extra = 0


class FlowPageVisitAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.flow_session.course
    get_course.short_description = "Course"
    get_course.admin_order_field = "flow_session__course"

    def get_flow_id(self, obj):
        return obj.flow_session.flow_id
    get_flow_id.short_description = "Flow ID"
    get_flow_id.admin_order_field = "flow_session__flow_id"

    def get_page_id(self, obj):
        return "%s/%s (%d)" % (
                obj.page_data.group_id,
                obj.page_data.page_id,
                obj.page_data.ordinal)

    get_page_id.short_description = "Page ID"
    get_page_id.admin_order_field = "page_data__page_id"

    def get_participant(self, obj):
        if obj.flow_session.participation:
            return obj.flow_session.participation.user
        else:
            return "(anonymous)"

    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "flow_session__participation"

    list_filter = (
            "flow_session__participation__course",
            "flow_session__flow_id",
            "is_graded_answer",
            "is_synthetic",
            )
    date_hierarchy = "visit_time"
    list_display = (
            "get_course",
            "get_flow_id",
            "get_page_id",
            "get_participant",
            "visit_time",
            "remote_address",
            "is_graded_answer",
            )
    list_display_links = (
            "get_course",
            "get_flow_id",
            "get_page_id",
            "visit_time",
            )

    search_fields = (
            "id",
            "flow_session__flow_id",
            "page_data__group_id",
            "page_data__page_id",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            )

    raw_id_fields = ("flow_session", "page_data")

    inlines = (FlowPageVisitGradeInline,)

    save_on_top = True

admin.site.register(FlowPageVisit, FlowPageVisitAdmin)

# }}}


# {{{ flow access

class FlowAccessExceptionEntryInline(admin.StackedInline):
    model = FlowAccessExceptionEntry
    extra = 5


class FlowAccessExceptionAdmin(admin.ModelAdmin):
    inlines = (FlowAccessExceptionEntryInline,)

    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = "Course"
    get_course.admin_order_field = "participation__course"

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "participation__user"

    list_display = (
            "get_participant",
            "get_course",
            "flow_id",
            "expiration",
            "creation_time",
            )
    list_display_links = (
            "get_participant",
            "flow_id",
            )
    list_filter = (
            "participation__course",
            "flow_id",
            )

    date_hierarchy = "creation_time"

    raw_id_fields = ("participation",)


admin.site.register(FlowAccessException, FlowAccessExceptionAdmin)

# }}}


# {{{ grading

class GradingOpportunityAdmin(admin.ModelAdmin):
    list_display = ("course",  "name", "due_time", "identifier",)
    list_filter = ("course",)

admin.site.register(GradingOpportunity, GradingOpportunityAdmin)


class GradeChangeAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = "Course"
    get_course.admin_order_field = "participation__course"

    def get_opportunity(self, obj):
        return obj.opportunity.name
    get_opportunity.short_description = "Opportunity"
    get_opportunity.admin_order_field = "opportunity"

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "participation__user"

    def get_percentage(self, obj):
        return round(100*obj.points/obj.max_points)
    get_percentage.short_description = "%"

    list_display = (
            "get_opportunity",
            "get_participant",
            "get_course",
            "state",
            "points",
            "get_percentage",
            "grade_time",
            )
    list_display_links = (
            "get_opportunity",
            "get_participant",
            )
    date_hierarchy = "grade_time"

    list_filter = (
            "opportunity__course",
            "opportunity",
            "state",
            )

    raw_id_fields = ("flow_session",)

admin.site.register(GradeChange, GradeChangeAdmin)

# }}}


# {{{ instant message

class InstantMessageAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = "Course"
    get_course.admin_order_field = "participation__course"

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "participation__user"

    list_filter = ("participation__course",)
    list_display = (
            "get_course",
            "get_participant",
            "time",
            "text",
            )

    date_hierarchy = "time"

    search_fields = (
            "text",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            )

admin.site.register(InstantMessage, InstantMessageAdmin)

# }}}

# vim: foldmethod=marker
