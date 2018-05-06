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

from django.conf.urls import include, url
from django.contrib import admin
from django.conf import settings
from course.constants import COURSE_ID_REGEX, FLOW_ID_REGEX, STATICPAGE_PATH_REGEX

import course.auth
import course.views
import course.im
import course.sandbox
import course.grades
import course.grading
import course.calendar
import course.versioning
import course.flow
import course.analytics
import course.exam
import course.api

urlpatterns = [
    url(r"^login/$",
        course.auth.sign_in_choice,
        name="relate-sign_in_choice"),
    url(r"^login/user-password/$",
        course.auth.sign_in_by_user_pw,
        name="relate-sign_in_by_user_pw"),
    url(r"^login/sign-up/$",
        course.auth.sign_up,
        name="relate-sign_up"),
    url(r"^login/reset-password/$",
        course.auth.reset_password,
        name="relate-reset_password"),
    url(r"^login/reset-password/(?P<field>instid)/$",
        course.auth.reset_password,
        name="relate-reset_password"),
    url(r"^login/reset-password/stage-2"
        "/(?P<user_id>[0-9]+)"
        "/(?P<sign_in_key>[a-zA-Z0-9]+)",
        course.auth.reset_password_stage2,
        name="relate-reset_password_stage2"),
    url(r"^login/by-email/$",
        course.auth.sign_in_by_email,
        name="relate-sign_in_by_email"),
    url(r"^login/token"
        "/(?P<user_id>[0-9]+)"
        "/(?P<sign_in_key>[a-zA-Z0-9]+)"
        "/$",
        course.auth.sign_in_stage2_with_token,
        name="relate-sign_in_stage2_with_token"),
    url(r"^logout/$",
        course.auth.sign_out,
        name="relate-logout"),
    url(r"^logout-confirmation/$",
        course.auth.sign_out_confirmation,
        name="relate-logout-confirmation"),
    url(r"^profile/$",
        course.auth.user_profile,
        name="relate-user_profile"),
    url(
        r"^course"
        "/" + COURSE_ID_REGEX +
        "/auth-tokens/$",
        course.auth.manage_authentication_tokens,
        name="relate-manage_authentication_tokens"),

    url(r"^generate-ssh-key/$",
        course.views.generate_ssh_keypair,
        name="relate-generate_ssh_keypair"),

    url(r"^monitor-task"
        "/(?P<task_id>[-0-9a-f]+)"
        "$",
        course.views.monitor_task,
        name="relate-monitor_task"),

    # {{{ troubleshooting

    url(r'^user/impersonate/$',
        course.auth.impersonate,
        name="relate-impersonate"),
    url(r'^user/stop_impersonating/$',
        course.auth.stop_impersonating,
        name="relate-stop_impersonating"),

    url(r'^time/set-fake-time/$',
        course.views.set_fake_time,
        name="relate-set_fake_time"),

    url(r'^time/set-pretend-facilities/$',
        course.views.set_pretend_facilities,
        name="relate-set_pretend_facilities"),

    # }}}

    # {{{ course

    url(r'^$', course.views.home, name='relate-home'),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/$",
        course.views.course_page,
        name="relate-course_page"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/edit/$",
        course.views.edit_course,
        name="relate-edit_course"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/page"
        "/" + STATICPAGE_PATH_REGEX +
        "/$",
        course.views.static_page,
        name="relate-content_page"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/instant-message/$",
        course.im.send_instant_message,
        name="relate-send_instant_message"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/sandbox/markup/$",
        course.sandbox.view_markup_sandbox,
        name="relate-view_markup_sandbox"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/sandbox/page/$",
        course.sandbox.view_page_sandbox,
        name="relate-view_page_sandbox"),

    url("^purge-pageview-data/$",
        course.flow.purge_page_view_data,
        name="relate-purge_page_view_data"),

    # }}}

    # {{{ grading

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/my/$",
        course.grades.view_participant_grades,
        name="relate-view_participant_grades"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/participant"
        "/(?P<participation_id>[0-9]+)"
        "/$",
        course.grades.view_participant_grades,
        name="relate-view_participant_grades"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/participants/$",
        course.grades.view_participant_list,
        name="relate-view_participant_list"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/opportunities/$",
        course.grades.view_grading_opportunity_list,
        name="relate-view_grading_opportunity_list"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/overview/$",
        course.grades.view_gradebook,
        name="relate-view_gradebook"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/overview/csv/$",
        course.grades.export_gradebook_csv,
        name="relate-export_gradebook_csv"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/by-opportunity"
        "/(?P<opp_id>[0-9]+)"
        "/$",
        course.grades.view_grades_by_opportunity,
        name="relate-view_grades_by_opportunity"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/single-grade"
        "/(?P<participation_id>[0-9]+)"
        "/(?P<opportunity_id>[0-9]+)"
        "/$",
        course.grades.view_single_grade,
        name="relate-view_single_grade"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/reopen-session"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<opportunity_id>[0-9]+)"
        "/$",
        course.grades.view_reopen_session,
        name="relate-view_reopen_session"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading"
        "/csv-import"
        "/$",
        course.grades.import_grades,
        name="relate-import_grades"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading"
        "/flow-page"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/$",
        course.grading.grade_flow_page,
        name="relate-grade_flow_page"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/prev_grades"
        "/flow-page"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/$",
        course.grading.get_prev_grades_dropdown_content,
        name="relate-get_prev_grades_dropdown_content"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/statistics"
        "/" + FLOW_ID_REGEX +
        "/$",
        course.grading.show_grader_statistics,
        name="relate-show_grader_statistics"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grading/download-submissions"
        "/" + FLOW_ID_REGEX +
        "/$",
        course.grades.download_all_submissions,
        name="relate-download_all_submissions"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/edit-grading-opportunity"
         "/(?P<opportunity_id>[-0-9]+)"
        "/$",
        course.grades.edit_grading_opportunity,
        name="relate-edit_grading_opportunity"),

    # }}}

    # {{{ enrollment

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/enroll/$",
        course.enrollment.enroll_view,
        name="relate-enroll"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/preapprove"
        "/$",
        course.enrollment.create_preapprovals,
        name="relate-create_preapprovals"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/query-participations"
        "/$",
        course.enrollment.query_participations,
        name="relate-query_participations"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/edit-participation"
         "/(?P<participation_id>[-0-9]+)"
        "/$",
        course.enrollment.edit_participation,
        name="relate-edit_participation"),

    # }}}

    # {{{ media

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/media/(?P<commit_sha>[a-f0-9]+)"
        "/(?P<media_path>.*)$",
        course.views.get_media,
        name="relate-get_media"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/file-version/(?P<commit_sha>[a-f0-9]+)"
        "/(?P<path>.*)$",
        course.views.get_repo_file,
        name="relate-get_repo_file"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/f"
        "/(?P<path>.*)$",
        course.views.get_current_repo_file,
        name="relate-get_current_repo_file"),

    # }}}

    # {{{ calendar

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/create-recurring-events/$",
        course.calendar.create_recurring_events,
        name="relate-create_recurring_events"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/renumber-events/$",
        course.calendar.renumber_events,
        name="relate-renumber_events"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/calendar/$",
        course.calendar.view_calendar,
        name="relate-view_calendar"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/calendar-edit/$",
        course.calendar.edit_calendar,
        name="relate-edit_calendar"),

    # }}}

    # {{{ versioning

    url(r"^new-course/$",
        course.versioning.set_up_new_course,
        name="relate-set_up_new_course"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/update/$",
        course.versioning.update_course,
        name="relate-update_course"),

    # }}}

    # {{{ flow-related

    url(r"^course"
        "/" + COURSE_ID_REGEX +
         "/flow"
         "/" + FLOW_ID_REGEX +
         "/start"
         "/$",
         course.flow.view_start_flow,
         name="relate-view_start_flow"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
         "/flow-session"
         "/(?P<flow_session_id>[-0-9]+)"
         "/resume"
         "/$",
         course.flow.view_resume_flow,
         name="relate-view_resume_flow"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-session"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/$",
        course.flow.view_flow_page,
        name="relate-view_flow_page"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/prev_answers"
        "/flow-page"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/$",
        course.flow.get_prev_answer_visits_dropdown_content,
        name="relate-get_prev_answer_visits_dropdown_content"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-session"
        "/(?P<flow_session_id>[-0-9]+)"
        "/update-expiration-mode"
        "/$",
        course.flow.update_expiration_mode,
        name="relate-update_expiration_mode"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-session"
        "/(?P<flow_session_id>[-0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/update-bookmark-state"
        "/$",
        course.flow.update_page_bookmark_state,
        name="relate-update_page_bookmark_state"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-session"
        "/(?P<flow_session_id>[0-9]+)"
        "/finish"
        "/$",
        course.flow.finish_flow_session_view,
        name="relate-finish_flow_session_view"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-session"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/flow-page-interaction-email"
        "/$",
        course.flow.send_email_about_flow_page,
        name="relate-flow_page_interaction_email"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-session"
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<page_ordinal>[0-9]+)"
        "/unsubmit/$",
        course.flow.view_unsubmit_flow_page,
        name="relate-unsubmit_flow_page"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/test-flow"
        "/$",
        course.views.test_flow,
        name="relate-test_flow"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/instant-flow"
        "/$",
        course.views.manage_instant_flow_requests,
        name="relate-manage_instant_flow_requests"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/regrade-flows"
        "/$",
        course.flow.regrade_flows_view,
        name="relate-regrade_flows_view"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grant-exception"
        "/$",
        course.views.grant_exception,
        name="relate-grant_exception"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grant-exception"
        "/(?P<participation_id>[0-9]+)"
        "/" + FLOW_ID_REGEX +
        "/$",
        course.views.grant_exception_stage_2,
        name="relate-grant_exception_stage_2"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/grant-exception"
        "/(?P<participation_id>[0-9]+)"
        "/" + FLOW_ID_REGEX +
        "/(?P<session_id>[0-9]+)"
        "/$",
        course.views.grant_exception_stage_3,
        name="relate-grant_exception_stage_3"),

    # }}}

    # {{{ analytics

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-analytics"
        "/$",
        course.analytics.flow_list,
        name="relate-flow_list"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-analytics"
        "/" + FLOW_ID_REGEX +
        "/$",
        course.analytics.flow_analytics,
        name="relate-flow_analytics"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/flow-analytics"
        "/" + FLOW_ID_REGEX +
        "/page"
        "/(?P<group_id>[-_a-zA-Z0-9]+)"
        "/(?P<page_id>[-_a-zA-Z0-9]+)"
        "/$",
        course.analytics.page_analytics,
        name="relate-page_analytics"),

    # }}}

    # {{{ exams

    url(r"^issue-exam-ticket"
        "/$",
        course.exam.issue_exam_ticket,
        name="relate-issue_exam_ticket"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/batch-issue-exam-tickets"
        "/$",
        course.exam.batch_issue_exam_tickets,
        name="relate-batch_issue_exam_tickets"),
    url(r"^exam-check-in/$",
        course.exam.check_in_for_exam,
        name="relate-check_in_for_exam"),
    url(r"^list-available-exams/$",
        course.exam.list_available_exams,
        name="relate-list_available_exams"),

    # }}}

    # {{{ django-select2

    url(r'^select2/', include('django_select2.urls')),

    #}}}

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/api/v1/get-flow-sessions$",
        course.api.get_flow_sessions,
        name="relate-course_get_flow_session"),

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/api/v1/get-flow-session-content$",
        course.api.get_flow_session_content,
        name="relate-course_get_flow_session_content"),

    url(r'^admin/', admin.site.urls),
]

if settings.RELATE_SIGN_IN_BY_SAML2_ENABLED:
    urlpatterns.extend([
        url(r'^saml2/', include('djangosaml2.urls')),
        ])
    if settings.DEBUG:  # pragma: no cover
        import djangosaml2.views
        urlpatterns.extend([
            # Keep commented unless debugging SAML2.
            url(r'^saml2-test/', djangosaml2.views.echo_attributes),
            ])

# vim: fdm=marker
