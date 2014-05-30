from django.contrib import admin
from course.models import (Course, Participation, InstantFlowRequest,
        FlowVisit, FlowPageVisit)


class CourseAdmin(admin.ModelAdmin):
    pass

admin.site.register(Course, CourseAdmin)


class ParticipationAdmin(admin.ModelAdmin):
    list_display = ["user", "course", "role", "status", "enroll_time"]
    list_filter = ["course", "role", "status"]

admin.site.register(Participation, ParticipationAdmin)


class InstantFlowRequestAdmin(admin.ModelAdmin):
    pass

admin.site.register(InstantFlowRequest, InstantFlowRequestAdmin)


class FlowVisitAdmin(admin.ModelAdmin):
    pass

admin.site.register(FlowVisit, FlowVisitAdmin)
