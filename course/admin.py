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

import six

from django.utils.translation import (
        ugettext_lazy as _, pgettext)
from django.contrib import admin

from course.models import (
        Course, Event,
        ParticipationTag,
        Participation, ParticipationPermission,
        ParticipationRole, ParticipationRolePermission,
        ParticipationPreapproval,
        AuthenticationToken,
        InstantFlowRequest,
        FlowSession, FlowPageData,
        FlowPageVisit, FlowPageVisitGrade,
        FlowRuleException,
        GradingOpportunity, GradeChange, InstantMessage,
        Exam, ExamTicket)
from django import forms
from relate.utils import string_concat
from course.enrollment import (approve_enrollment, deny_enrollment)
from course.constants import (
        participation_permission as pperm,
        exam_ticket_states
        )

if False:
    from typing import Any, Text, Tuple  # noqa


# {{{ permission helpers

def _filter_courses_for_user(queryset, user):
    if user.is_superuser:
        return queryset
    z = queryset.filter(
            participations__user=user,
            participations__roles__permissions__permission=pperm.use_admin_interface)
    return z


def _filter_course_linked_obj_for_user(queryset, user):
    if user.is_superuser:
        return queryset
    return queryset.filter(
            course__participations__user=user,
            course__participations__roles__permissions__permission  # noqa
            =pperm.use_admin_interface
            )


def _filter_participation_linked_obj_for_user(queryset, user):
    if user.is_superuser:
        return queryset
    return queryset.filter(
        participation__course__participations__user=user,
        participation__course__participations__roles__permissions__permission  # noqa
        =pperm.use_admin_interface)

# }}}


# {{{ list filter helper

def _filter_related_only(filter_arg):
    # type: (Text) -> Tuple[Text, Any]
    return (filter_arg, admin.RelatedOnlyFieldListFilter)

# }}}


# {{{ course

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
    list_display = (
            "identifier",
            "number",
            "name",
            "time_period",
            "start_date",
            "end_date",
            "hidden",
            "listed",
            "accepts_enrollment")
    list_editable = (
            "number",
            "name",
            "time_period",
            "start_date",
            "end_date",
            "hidden",
            "listed",
            "accepts_enrollment")
    list_filter = (
            "number",
            "time_period",
            "hidden",
            "listed",
            "accepts_enrollment")
    date_hierarchy = "start_date"

    search_fields = (
            "identifier",
            "number",
            "name",
            "time_period")

    form = CourseAdminForm

    save_on_top = True

    # {{{ permissions

    def has_add_permission(self, request):
        # These are created only through the course creation form.
        return False

    def get_queryset(self, request):
        qs = super(CourseAdmin, self).get_queryset(request)
        return _filter_courses_for_user(qs, request.user)

    # }}}


admin.site.register(Course, CourseAdmin)

# }}}


# {{{ events

class EventAdmin(admin.ModelAdmin):
    list_display = (
            "course",
            "kind",
            "ordinal",
            "time",
            "end_time",
            "shown_in_calendar")
    list_filter = (_filter_related_only("course"), "kind", "shown_in_calendar")

    date_hierarchy = "time"

    search_fields = (
            "course__identifier",
            "kind",
            )

    def __unicode__(self):
        return u"%s %d in %s" % (self.kind, self.ordinal, self.course)

    if six.PY3:
        __str__ = __unicode__

    list_editable = ("ordinal", "time", "end_time", "shown_in_calendar")

    # {{{ permissions

    def get_queryset(self, request):
        qs = super(EventAdmin, self).get_queryset(request)
        return _filter_course_linked_obj_for_user(qs, request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        return super(EventAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(Event, EventAdmin)

# }}}


# {{{ participation tags

class ParticipationTagAdmin(admin.ModelAdmin):
    list_filter = (_filter_related_only("course"),)

    # {{{ permissions

    def get_queryset(self, request):
        qs = super(ParticipationTagAdmin, self).get_queryset(request)
        return _filter_course_linked_obj_for_user(qs, request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        return super(ParticipationTagAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(ParticipationTag, ParticipationTagAdmin)

# }}}


# {{{ participations

class ParticipationRolePermissionInline(admin.TabularInline):
    model = ParticipationRolePermission
    extra = 3


class ParticipationRoleAdmin(admin.ModelAdmin):
    inlines = (ParticipationRolePermissionInline,)

    list_filter = (_filter_related_only("course"), "identifier")


admin.site.register(ParticipationRole, ParticipationRoleAdmin)


class ParticipationPermissionInline(admin.TabularInline):
    model = ParticipationPermission
    extra = 3


class ParticipationForm(forms.ModelForm):
    class Meta:
        model = Participation
        exclude = ("role",)

    def clean(self):
        super(ParticipationForm, self).clean()

        for tag in self.cleaned_data.get("tags", []):
            if tag.course != self.cleaned_data.get("course"):
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    {"tags": _("Tags must belong to same course as "
                               "participation.")})

        for role in self.cleaned_data.get("roles", []):
            if role.course != self.cleaned_data.get("course"):
                from django.core.exceptions import ValidationError
                raise ValidationError(
                    {"roles": _("Role must belong to same course as "
                               "participation.")})


class ParticipationAdmin(admin.ModelAdmin):
    form = ParticipationForm

    def get_roles(self, obj):
        return ", ".join(six.text_type(role.name) for role in obj.roles.all())

    get_roles.short_description = _("Roles")  # type: ignore

    def get_user(self, obj):
        from django.urls import reverse
        from django.conf import settings

        return string_concat(
                "<a href='%(link)s'>", "%(user_fullname)s",
                "</a>"
                ) % {
                    "link": reverse(
                        "admin:%s_change"
                        % settings.AUTH_USER_MODEL.replace(".", "_")
                        .lower(),
                        args=(obj.user.id,)),
                    "user_fullname": obj.user.get_full_name(
                        force_verbose_blank=True),
                    }

    get_user.short_description = pgettext("real name of a user", "Name")  # type:ignore  # noqa
    get_user.admin_order_field = "user__last_name"  # type: ignore
    get_user.allow_tags = True  # type: ignore

    list_display = (
            "user",
            "get_user",
            "course",
            "get_roles",
            "status",
            )
    list_filter = (_filter_related_only("course"), "roles__name", "status", "tags")

    raw_id_fields = ("user",)

    filter_horizontal = ("tags", "roles",)

    search_fields = (
            "course__identifier",
            "user__username",
            "user__first_name",
            "user__last_name",
            )

    actions = [approve_enrollment, deny_enrollment]

    inlines = (ParticipationPermissionInline,)

    save_on_top = True

    # {{{ permissions

    def get_queryset(self, request):
        qs = super(ParticipationAdmin, self).get_queryset(request)
        return _filter_course_linked_obj_for_user(qs, request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        if db_field.name == "tags":
            kwargs["queryset"] = _filter_course_linked_obj_for_user(
                    ParticipationTag.objects, request.user)
        return super(ParticipationAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(Participation, ParticipationAdmin)


class ParticipationPreapprovalAdmin(admin.ModelAdmin):
    def get_roles(self, obj):
        return ", ".join(six.text_type(role.name) for role in obj.roles.all())

    get_roles.short_description = _("Roles")  # type: ignore

    list_display = ("email", "institutional_id", "course", "get_roles",
            "creation_time", "creator")
    list_filter = (_filter_related_only("course"), "roles")

    search_fields = (
            "email", "institutional_id",
            )

    # {{{ permissions

    def get_queryset(self, request):
        qs = super(ParticipationPreapprovalAdmin, self).get_queryset(request)
        if request.user.is_superuser:
            return qs
        return _filter_course_linked_obj_for_user(qs, request.user)

    exclude = ("creator", "creation_time", "role")

    def save_model(self, request, obj, form, change):
        obj.creator = request.user
        obj.save()

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        return super(ParticipationPreapprovalAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(ParticipationPreapproval, ParticipationPreapprovalAdmin)

# }}}


class AuthenticationTokenAdmin(admin.ModelAdmin):
    list_display = ("id", "participation", "restrict_to_participation_role",
            "description", "valid_until", "revocation_time")

    date_hierarchy = "creation_time"

    search_fields = (
            "id", "description", "participation__user__username"
            )


admin.site.register(AuthenticationToken, AuthenticationTokenAdmin)


class InstantFlowRequestAdmin(admin.ModelAdmin):
    list_display = ("course", "flow_id", "start_time", "end_time", "cancelled")
    list_filter = (_filter_related_only("course"),)

    date_hierarchy = "start_time"

    search_fields = (
            "email",
            )


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

    get_participant.short_description = _("Participant")  # type: ignore
    get_participant.admin_order_field = "participation__user"  # type: ignore

    search_fields = (
            "=id",
            "flow_id",
            "access_rules_tag",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            "user__username",
            "user__first_name",
            "user__last_name",
            )

    list_display = (
            "id",
            "flow_id",
            "get_participant",
            "course",
            "start_time",
            "completion_time",
            "access_rules_tag",
            "in_progress",
            #"expiration_mode",
            )
    list_display_links = (
            "flow_id",
            "get_participant",
            )

    date_hierarchy = "start_time"

    list_filter = (
            _filter_related_only("course"),
            "flow_id",
            "in_progress",
            "access_rules_tag",
            "expiration_mode",
            )

    inlines = (FlowPageDataInline,)

    raw_id_fields = ("participation", "user")

    save_on_top = True

    # {{{ permissions

    def has_add_permission(self, request):
        # These are only created automatically.
        return False

    def get_queryset(self, request):
        qs = super(FlowSessionAdmin, self).get_queryset(request)
        return _filter_course_linked_obj_for_user(qs, request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        return super(FlowSessionAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(FlowSession, FlowSessionAdmin)

# }}}


# {{{ flow page visit

class FlowPageVisitGradeInline(admin.TabularInline):
    model = FlowPageVisitGrade
    extra = 0


class HasAnswerListFilter(admin.SimpleListFilter):
    title = 'has answer'

    parameter_name = 'has_answer'

    def lookups(self, request, model_admin):
        return (
            ('y', 'Yes'),
            ('n', 'No'),
        )

    def queryset(self, request, queryset):
        if self.value() is None:
            return queryset
        return queryset.filter(answer__isnull=self.value() != "y")


class FlowIdListFilter(admin.SimpleListFilter):
    """
    This is only necessary when flow_id is only accessible by FlowSession, which is
    a ForeignKey in the model
    """
    title = _("Flow ID")
    parameter_name = "flow_id"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        if not request.user.is_superuser:
            qs = qs.filter(
                flow_session__course__participations__user=request.user,
                flow_session__course__participations__roles__permissions__permission  # noqa
                =pperm.use_admin_interface)

        flow_ids = qs.values_list("flow_session__flow_id", flat=True).distinct()
        return zip(flow_ids, flow_ids)

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(flow_session__flow_id=self.value())
        else:
            return queryset


class FlowPageVisitAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.flow_session.course
    get_course.short_description = _("Course")  # type: ignore
    get_course.admin_order_field = "flow_session__course"  # type: ignore

    def get_flow_id(self, obj):
        return obj.flow_session.flow_id
    get_flow_id.short_description = _("Flow ID")  # type: ignore
    get_flow_id.admin_order_field = "flow_session__flow_id"  # type: ignore

    def get_page_id(self, obj):
        if obj.page_data.page_ordinal is None:
            return string_concat("%s/%s (", _("not in use"), ")") % (
                    obj.page_data.group_id,
                    obj.page_data.page_id)
        else:
            return "%s/%s (%s)" % (
                    obj.page_data.group_id,
                    obj.page_data.page_id,
                    obj.page_data.page_ordinal)

    get_page_id.short_description = _("Page ID")  # type: ignore
    get_page_id.admin_order_field = "page_data__page_id"  # type: ignore

    def get_participant(self, obj):
        if obj.flow_session.participation:
            return obj.flow_session.participation.user
        else:
            return string_concat("(", _("anonymous"), ")")

    get_participant.short_description = _("Owner")  # type: ignore
    get_participant.admin_order_field = "flow_session__participation"  # type: ignore

    def get_answer_is_null(self, obj):
        return obj.answer is not None
    get_answer_is_null.short_description = _("Has answer")  # type: ignore
    get_answer_is_null.boolean = True  # type: ignore

    def get_flow_session_id(self, obj):
        return obj.flow_session.id
    get_flow_session_id.short_description = _("Flow Session ID")  # type: ignore
    get_flow_session_id.admin_order_field = "flow_session__id"  # type: ignore

    list_filter = (
            HasAnswerListFilter,
            "is_submitted_answer",
            "is_synthetic",
            _filter_related_only("flow_session__participation__course"),
            FlowIdListFilter,
            )
    date_hierarchy = "visit_time"
    list_display = (
            "id",
            "get_course",
            "get_flow_id",
            "get_page_id",
            "get_participant",
            "get_flow_session_id",
            "visit_time",
            "get_answer_is_null",
            "is_submitted_answer",
            "is_synthetic",
            "user",
            "impersonated_by",
            )
    list_display_links = (
            "id",
            )

    search_fields = (
            "=id",
            "=flow_session__id",
            "flow_session__flow_id",
            "page_data__group_id",
            "page_data__page_id",
            "flow_session__participation__user__username",
            "flow_session__participation__user__first_name",
            "flow_session__participation__user__last_name",
            )

    raw_id_fields = ("flow_session", "page_data")

    inlines = (FlowPageVisitGradeInline,)

    save_on_top = True

    # {{{ permissions

    def has_add_permission(self, request):
        # These are created only automatically.
        return False

    def get_queryset(self, request):
        qs = super(FlowPageVisitAdmin, self).get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(
            flow_session__course__participations__user=request.user,
            flow_session__course__participations__roles__permissions__permission  # noqa
            =pperm.use_admin_interface)

    # }}}


admin.site.register(FlowPageVisit, FlowPageVisitAdmin)

# }}}


# {{{ flow access

class FlowRuleExceptionAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = _("Course")  # type: ignore
    get_course.admin_order_field = "participation__course"  # type: ignore

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = _("Participant")  # type: ignore
    get_participant.admin_order_field = "participation__user"  # type: ignore

    search_fields = (
            "flow_id",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            "comment",
            )

    list_display = (
            "get_participant",
            "get_course",
            "flow_id",
            "kind",
            "expiration",
            "creation_time",
            )
    list_display_links = (
            "get_participant",
            "flow_id",
            )
    list_filter = (
            _filter_related_only("participation__course"),
            "flow_id",
            "kind",
            )

    date_hierarchy = "creation_time"

    raw_id_fields = ("participation",)

    # {{{ permissions

    def has_add_permission(self, request):
        # These are only created automatically.
        return False

    def get_queryset(self, request):
        qs = super(FlowRuleExceptionAdmin, self).get_queryset(request)
        return _filter_participation_linked_obj_for_user(qs, request.user)

    exclude = ("creator", "creation_time")

    def save_model(self, request, obj, form, change):
        obj.creator = request.user
        obj.save()

    # }}}


admin.site.register(FlowRuleException, FlowRuleExceptionAdmin)

# }}}


# {{{ grading

class GradingOpportunityAdmin(admin.ModelAdmin):
    list_display = (
            "name",
            "course",
            "identifier",
            "due_time",
            "shown_in_grade_book",
            "shown_in_participant_grade_book",
            )
    list_filter = (
            _filter_related_only("course"),
            "shown_in_grade_book",
            "shown_in_participant_grade_book",
            )
    list_editable = (
            "shown_in_grade_book",
            "shown_in_participant_grade_book",
            )

    # {{{ permissions

    exclude = ("creation_time",)

    def get_queryset(self, request):
        qs = super(GradingOpportunityAdmin, self).get_queryset(request)
        return _filter_course_linked_obj_for_user(qs, request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        return super(GradingOpportunityAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(GradingOpportunity, GradingOpportunityAdmin)


class GradeChangeAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = _("Course")  # type: ignore
    get_course.admin_order_field = "participation__course"  # type: ignore

    def get_opportunity(self, obj):
        return obj.opportunity.name
    get_opportunity.short_description = _("Opportunity")  # type: ignore
    get_opportunity.admin_order_field = "opportunity"  # type: ignore

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = _("Participant")  # type: ignore
    get_participant.admin_order_field = "participation__user"  # type: ignore

    def get_percentage(self, obj):
        if obj.points is None or obj.max_points is None:
            return None
        else:
            return round(100*obj.points/obj.max_points)

    get_percentage.short_description = "%"  # type: ignore

    list_display = (
            "get_opportunity",
            "get_participant",
            "get_course",
            "state",
            "points",
            "max_points",
            "get_percentage",
            "attempt_id",
            "grade_time",
            )
    list_display_links = (
            "get_opportunity",
            "get_participant",
            )
    date_hierarchy = "grade_time"

    search_fields = (
            "opportunity__name",
            "opportunity__flow_id",
            "opportunity__identifier",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            "attempt_id",
            )

    list_filter = (
            _filter_related_only("opportunity__course"),
            _filter_related_only("opportunity"),
            "state",
            )

    raw_id_fields = ("participation", "flow_session", "opportunity")

    # {{{ permission

    def get_queryset(self, request):
        qs = super(GradeChangeAdmin, self).get_queryset(request)
        return _filter_participation_linked_obj_for_user(qs, request.user)

    exclude = ("creator", "grade_time")

    def save_model(self, request, obj, form, change):
        obj.creator = request.user
        obj.save()

    # }}}


admin.site.register(GradeChange, GradeChangeAdmin)

# }}}


# {{{ instant message

class InstantMessageAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course
    get_course.short_description = _("Course")  # type: ignore
    get_course.admin_order_field = "participation__course"  # type: ignore

    def get_participant(self, obj):
        return obj.participation.user
    get_participant.short_description = _("Participant")  # type: ignore
    get_participant.admin_order_field = "participation__user"  # type: ignore

    list_filter = (_filter_related_only("participation__course"),)
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

    raw_id_fields = ("participation",)

    # {{{ permissions

    def has_add_permission(self, request):
        # These are created only automatically.
        return False

    def get_queryset(self, request):
        qs = super(InstantMessageAdmin, self).get_queryset(request)
        return _filter_participation_linked_obj_for_user(qs, request.user)

    # }}}


admin.site.register(InstantMessage, InstantMessageAdmin)

# }}}


# {{{ exam tickets

class ExamAdmin(admin.ModelAdmin):
    list_filter = (
            _filter_related_only("course"),
            "active",
            "listed",
            )

    list_display = (
            "course",
            "flow_id",
            "active",
            "listed",
            "no_exams_before",
            )

    search_fields = (
            "flow_id",
            )

    date_hierarchy = "no_exams_before"

    # {{{ permissions

    def get_queryset(self, request):
        qs = super(ExamAdmin, self).get_queryset(request)
        return _filter_course_linked_obj_for_user(qs, request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "course":
            kwargs["queryset"] = _filter_courses_for_user(
                    Course.objects, request.user)
        return super(ExamAdmin, self).formfield_for_foreignkey(
                db_field, request, **kwargs)

    # }}}


admin.site.register(Exam, ExamAdmin)


class ExamTicketAdmin(admin.ModelAdmin):
    def get_course(self, obj):
        return obj.participation.course

    get_course.short_description = _("Course")  # type: ignore
    get_course.admin_order_field = "participation__course"  # type: ignore

    list_filter = (
            _filter_related_only("participation__course"),
            "state",
            )

    raw_id_fields = ("participation",)

    list_display = (
            "get_course",
            "exam",
            "participation",
            "state",
            "creation_time",
            "usage_time",
            )

    date_hierarchy = "usage_time"

    search_fields = (
            "exam__course__identifier",
            "exam__flow_id",
            "exam__description",
            "participation__user__username",
            "participation__user__first_name",
            "participation__user__last_name",
            )

    # {{{ permissions

    def get_queryset(self, request):
        qs = super(ExamTicketAdmin, self).get_queryset(request)
        return _filter_participation_linked_obj_for_user(qs, request.user)

    exclude = ("creator",)

    def save_model(self, request, obj, form, change):
        obj.creator = request.user
        obj.save()

    # }}}

    def revoke_exam_tickets(self, request, queryset):  # noqa
        queryset \
                .filter(state=exam_ticket_states.valid) \
                .update(state=exam_ticket_states.revoked)

    revoke_exam_tickets.short_description = _("Revoke Exam Tickets")  # type: ignore

    actions = [revoke_exam_tickets]


admin.site.register(ExamTicket, ExamTicketAdmin)

# }}}

# vim: foldmethod=marker
