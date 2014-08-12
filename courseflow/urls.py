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

from django.conf.urls import patterns, include, url
from django.contrib import admin

urlpatterns = patterns('',
    url(r"^login/$",
        "course.auth.sign_in"),
    url(r"^login/by-email/$",
        "course.auth.sign_in_by_email"),
    url(r"^login/token"
        "/(?P<sign_in_key>[a-zA-Z0-9]+)"
        "/$",
        "course.auth.sign_in_stage2_with_token"),
    url(r"^logout/$",
        "django.contrib.auth.views.logout",
        {"next_page": "course.views.home"}),
    url(r"^profile/$",
        "course.auth.user_profile",
        ),

    # troubleshooting
    url(r'^user/impersonate/$', 'course.auth.impersonate'),
    url(r'^user/stop_impersonating/$', 'course.auth.stop_impersonating'),

    url(r'^time/set-fake-time/$', 'course.views.set_fake_time'),

    # course
    url(r'^$', 'course.views.home', name='home'),

    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/$",
        "course.views.course_page",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/grades/$",
        "course.views.view_grades",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/instant-message/$",
        "course.im.send_instant_message",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/enroll/$",
        "course.enrollment.enroll",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/media/(?P<commit_sha>[a-f0-9]+)"
        "/(?P<media_path>.*)$",
        "course.views.get_media",),

    # time labels
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/check-time-labels/$",
        "course.views.check_time_labels",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/create-recurring-time-labels/$",
        "course.views.create_recurring_time_labels",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/renumber-time-labels/$",
        "course.views.renumber_time_labels",),

    # versioning
    url(r"^new-course/$",
        "course.versioning.set_up_new_course"),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/fetch/$",
        "course.versioning.fetch_course_updates",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/update/$",
        "course.versioning.update_course",),

    # flow-related
    url(r"^course"
         "/(?P<course_identifier>[-a-zA-Z0-9]+)"
         "/flow"
         "/(?P<flow_identifier>[-_a-zA-Z0-9]+)"
         "/start"
         "/$",
         "course.flow.start_flow",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/flow"
        "/(?P<flow_identifier>[-_a-zA-Z0-9]+)"
        "/(?P<ordinal>[0-9]+)"
        "/$",
        "course.flow.view_flow_page",),
    url(r"^course"
        "/(?P<course_identifier>[-a-zA-Z0-9]+)"
        "/flow"
        "/(?P<flow_identifier>[-_a-zA-Z0-9]+)"
        "/finish"
        "/$",
        "course.flow.finish_flow",),

    url(r'^admin/', include(admin.site.urls)),
)
