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
        Course, TimeMark,
        Participation, InstantFlowRequest,
        FlowVisit, FlowPageData, FlowPageVisit,
        FlowAccessException, FlowAccessExceptionEntry,
        GradingOpportunity, GradeChange)


# {{{ user status

class UserStatusAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "key_time")
    list_filter = ("status",)

    date_hierarchy = "key_time"

    def __unicode__(self):
        return u"%s in status %s" % (self.user, self.status)

admin.site.register(UserStatus, UserStatusAdmin)

# }}}


class CourseAdmin(admin.ModelAdmin):
    pass

admin.site.register(Course, CourseAdmin)


# {{{ time marks

class TimeMarkAdmin(admin.ModelAdmin):
    list_display = ["course", "kind", "ordinal", "time"]
    list_filter = ["course", "kind"]

    date_hierarchy = "time"

    def __unicode__(self):
        return u"%s %d in %s" % (self.kind, self.ordinal, self.course)

admin.site.register(TimeMark, TimeMarkAdmin)

# }}}


# {{{ participation

class ParticipationAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "role", "status", "enroll_time"]
    list_filter = ["course", "role", "status"]

admin.site.register(Participation, ParticipationAdmin)

# }}}


class InstantFlowRequestAdmin(admin.ModelAdmin):
    pass

admin.site.register(InstantFlowRequest, InstantFlowRequestAdmin)


# {{{ flow visits

class FlowPageDataInline(admin.TabularInline):
    model = FlowPageData
    extra = 0


class FlowPageVisitInline(admin.TabularInline):
    model = FlowPageVisit
    extra = 0

    raw_id_fields = ("page_data",)


class FlowVisitAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = "Course"
    get_course.admin_order_field = "participation__course"

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "participation__user"

    search_fields = (
            "flow_id",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            )

    list_display = (
            "flow_id",
            "get_participant",
            "get_course",
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
            "participation__course",
            "flow_id",
            "in_progress",
            "for_credit",
            )

    inlines = (FlowPageDataInline, FlowPageVisitInline)

admin.site.register(FlowVisit, FlowVisitAdmin)

# }}}


# {{{ flow access

class FlowAccessExceptionEntryInline(admin.StackedInline):
    model = FlowAccessExceptionEntry
    extra = 2


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
    get_course.short_description = "Opportunity"
    get_course.admin_order_field = "opportunity"

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = "Participant"
    get_participant.admin_order_field = "participation__user"

    list_display = (
            "get_opportunity",
            "get_participant",
            "get_course",
            "state",
            "points",
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
            "participation",
            "state",
            )

admin.site.register(GradeChange, GradeChangeAdmin)

# }}}

# vim: foldmethod=marker
