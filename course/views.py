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

from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
import django.forms as forms
import django.views.decorators.http as http_dec
from django import http

from django.views.decorators.cache import cache_control

from crispy_forms.layout import Submit

from courseflow.utils import StyledForm
from bootstrap3_datetime.widgets import DateTimePicker

from course.auth import get_role_and_participation
from course.models import (Course, participation_role)

from course.content import (get_course_repo, get_course_desc)
from course.utils import course_view, render_course_page


# {{{ home

def home(request):
    courses_and_descs_and_invalid_flags = []
    for course in Course.objects.all():
        repo = get_course_repo(course)
        desc = get_course_desc(repo, course, course.active_git_commit_sha.encode())

        role, participation = get_role_and_participation(request, course)

        show = True
        if course.hidden:
            if role not in [participation_role.teaching_assistant,
                    participation_role.instructor]:
                show = False

        if not course.valid:
            if role != participation_role.instructor:
                show = False

        if show:
            courses_and_descs_and_invalid_flags.append(
                    (course, desc, not course.valid))

    def course_sort_key(entry):
        course, desc, invalid_flag = entry
        return course.identifier

    courses_and_descs_and_invalid_flags.sort(key=course_sort_key)

    return render(request, "course/home.html", {
        "courses_and_descs_and_invalid_flags": courses_and_descs_and_invalid_flags
        })

# }}}


def maintenance(request):
    return render(request, "maintenance.html")


# {{{ course page

def check_course_state(course, role):
    if course.hidden:
        if role not in [participation_role.teaching_assistant,
                participation_role.instructor]:
            raise PermissionDenied("only course staff have access")
    elif not course.valid:
        if role != participation_role.instructor:
            raise PermissionDenied("only the instructor has access")


@course_view
def course_page(pctx):
    from course.content import get_processed_course_chunks
    chunks = get_processed_course_chunks(
            pctx.course, pctx.repo, pctx.course_commit_sha, pctx.course_desc,
            pctx.role, get_now_or_fake_time(pctx.request))

    return render_course_page(pctx, "course/course-page.html", {
        "chunks": chunks,
        })

# }}}


# {{{ media

def media_etag_func(request, course_identifier, commit_sha, media_path):
    return ":".join([course_identifier, commit_sha, media_path])


@cache_control(max_age=3600*24*31)  # cache for a month
@http_dec.condition(etag_func=media_etag_func)
def get_media(request, course_identifier, commit_sha, media_path):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)

    repo = get_course_repo(course)

    from course.content import get_repo_blob_data_cached
    try:
        data = get_repo_blob_data_cached(
                repo, "media/"+media_path, commit_sha.encode())
    except ObjectDoesNotExist:
        raise http.Http404()

    from mimetypes import guess_type
    content_type = guess_type(media_path)

    return http.HttpResponse(data, content_type=content_type)

# }}}


# {{{ time travel

class FakeTimeForm(StyledForm):
    time = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "pickSeconds": False}))

    def __init__(self, *args, **kwargs):
        super(FakeTimeForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("set", "Set", css_class="col-lg-offset-2"))
        self.helper.add_input(
                Submit("unset", "Unset"))


def get_fake_time(request):
    if "courseflow_fake_time" in request.session:
        import datetime

        from django.conf import settings
        from pytz import timezone
        tz = timezone(settings.TIME_ZONE)
        return tz.localize(
                datetime.datetime.fromtimestamp(
                    request.session["courseflow_fake_time"]))
    else:
        return None


def get_now_or_fake_time(request):
    fake_time = get_fake_time(request)
    if fake_time is None:
        from django.utils.timezone import now
        return now()
    else:
        return fake_time


def set_fake_time(request):
    if not request.user.is_staff:
        raise PermissionDenied("only staff may set fake time")

    if request.method == "POST":
        form = FakeTimeForm(request.POST, request.FILES)
        do_set = "set" in form.data
        if form.is_valid():
            fake_time = form.cleaned_data["time"]
            if do_set:
                import time
                request.session["courseflow_fake_time"] = \
                        time.mktime(fake_time.timetuple())
            else:
                request.session.pop("courseflow_fake_time", None)

    else:
        if "courseflow_fake_time" in request.session:
            form = FakeTimeForm({
                "time": get_fake_time(request)
                })
        else:
            form = FakeTimeForm()

    return render(request, "generic-form.html", {
        "form": form,
        "form_description": "Set fake time",
    })


def fake_time_context_processor(request):
    return {
            "fake_time": get_fake_time(request),
            }

# }}}


# {{{ grading

@course_view
def view_grades(pctx):
    messages.add_message(pctx.request, messages.ERROR,
            "Grade viewing is not yet implemented. (Sorry!) It will be "
            "once you start accumulating a sufficient number of grades.")

    return redirect("course.views.course_page", pctx.course.identifier)

# }}}


# vim: foldmethod=marker
