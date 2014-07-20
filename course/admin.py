from django.contrib import admin
from course.models import (
        UserStatus,
        Course, TimeMark,
        Participation, InstantFlowRequest,
        FlowVisit, FlowPageVisit,
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

class FlowVisitAdmin(admin.ModelAdmin):
    pass

admin.site.register(FlowVisit, FlowVisitAdmin)


class FlowPageVisitAdmin(admin.ModelAdmin):
    pass

admin.site.register(FlowPageVisit, FlowPageVisitAdmin)

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
