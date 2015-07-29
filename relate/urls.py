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
from course.constants import COURSE_ID_REGEX, FLOW_ID_REGEX

import django.contrib.auth.views
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

urlpatterns = [
    url(r"^login/$",
        course.auth.sign_in_by_user_pw,
        name="relate-sign_in_by_user_pw"),
    url(r"^login/sign-up/$",
        course.auth.sign_up,
        name="relate-sign_up"),
    url(r"^login/reset-password/$",
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
        django.contrib.auth.views.logout,
        {"next_page": "relate-home"},
        name="relate-logout"),
    url(r"^profile/$",
        course.auth.user_profile,
        name="relate-user_profile"),

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
        "/grading/statistics"
        "/" + FLOW_ID_REGEX +
        "/$",
        course.grading.show_grading_statistics,
        name="relate-show_grading_statistics"),
    # }}}

    # {{{ enrollment

    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/enroll/$",
        course.enrollment.enroll,
        name="relate-enroll"),
    url(r"^course"
        "/" + COURSE_ID_REGEX +
        "/preapprove"
        "/$",
        course.enrollment.create_preapprovals,
        name="relate-create_preapprovals"),

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
        "/repo-file/(?P<commit_sha>[a-f0-9]+)"
        "/(?P<path>.*)$",
        course.views.get_repo_file,
        name="relate-get_repo_file"),

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
        "/(?P<flow_session_id>[0-9]+)"
        "/(?P<ordinal>[0-9]+)"
        "/$",
        course.flow.view_flow_page,
        name="relate-view_flow_page"),
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
        "/(?P<flow_session_id>[0-9]+)"
        "/finish"
        "/$",
        course.flow.finish_flow_session_view,
        name="relate-finish_flow_session_view"),

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
        "/regrade-not-for-credit-flows"
        "/$",
        course.flow.regrade_not_for_credit_flows_view,
        name="relate-regrade_not_for_credit_flows_view"),

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

    url(r'^admin/', include(admin.site.urls)),
]

if settings.RELATE_MAINTENANCE_MODE:
    urlpatterns = [
        # course
        url(r'^.*$', 'course.views.maintenance'),
    ]

# vim: fdm=marker
