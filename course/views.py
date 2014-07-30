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
from django.core.exceptions import PermissionDenied
from django.db import transaction
import django.forms as forms

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit

from bootstrap3_datetime.widgets import DateTimePicker

from course.auth import get_role_and_participation
from course.models import (Course, participation_role, TimeLabel)

from course.content import (get_course_repo, get_course_desc)


def get_active_commit_sha(course, participation):
    sha = course.active_git_commit_sha

    if participation is not None and participation.preview_git_commit_sha:
        sha = participation.preview_git_commit_sha

    return sha.encode()


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
        return desc.course_start

    courses_and_descs_and_invalid_flags.sort(key=course_sort_key)

    return render(request, "course/home.html", {
        "courses_and_descs_and_invalid_flags": courses_and_descs_and_invalid_flags
        })

# }}}


# {{{ course page

def check_course_state(course, role):
    if course.hidden:
        if role not in [participation_role.teaching_assistant,
                participation_role.instructor]:
            raise PermissionDenied("only course staff have access")
    elif not course.valid:
        if role != participation_role.instructor:
            raise PermissionDenied("only the instructor has access")


def course_page(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    check_course_state(course, role)

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, course, commit_sha)

    from course.content import get_processed_course_chunks
    chunks = get_processed_course_chunks(course, course_desc,
            role)

    return render(request, "course/course-page.html", {
        "course": course,
        "course_desc": course_desc,
        "participation": participation,
        "role": role,
        "chunks": chunks,
        "participation_role": participation_role,
        })

# }}}


# {{{ media

def get_media(request, course_identifier, media_path):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)

    repo = get_course_repo(course)

    # FIXME There's a corner case with flows here, which may be on a
    # different commit.
    commit_sha = get_active_commit_sha(course, participation)

    from course.content import get_repo_blob
    data = get_repo_blob(repo, "media/"+media_path, commit_sha).data

    from mimetypes import guess_type
    content_type = guess_type(media_path)

    from django.http import HttpResponse
    return HttpResponse(data, content_type=content_type)

# }}}


# {{{ time labels

def validate_time_labels(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)
    if role != participation_role.instructor:
        raise PermissionDenied("only instructors may do that")

    repo = get_course_repo(course)
    commit_sha = get_active_commit_sha(course, participation)
    course_desc = get_course_desc(repo, course, commit_sha)

    invalid_datespecs = set()

    from course.content import InvalidDatespec, parse_date_spec

    def datespec_callback(datespec):
        try:
            parse_date_spec(course, datespec, return_now_on_error=False)
        except InvalidDatespec as e:
            invalid_datespecs.add(e.datespec)

    from course.validation import validate_course_content
    validate_course_content(
            repo, course.course_file, commit_sha,
            datespec_callback=datespec_callback)

    return render(request, "course/invalid-datespec-list.html", {
        "course": course,
        "course_desc": course_desc,
        "participation": participation,
        "role": role,
        "participation_role": participation_role,
        "invalid_datespecs": sorted(invalid_datespecs),
        })


class RecurringTimeLabelForm(forms.Form):
    kind = forms.CharField(required=True,
            help_text="Should be lower_case_with_underscores, no spaces allowed.")
    time = forms.DateTimeField(
            widget=DateTimePicker(
                options={"format": "YYYY-MM-DD HH:mm", "pickSeconds": False}))
    interval = forms.ChoiceField(required=True,
            choices=(
                ("weekly", "Weekly"),
                ))
    starting_ordinal = forms.IntegerField(required=True, initial=1)
    count = forms.IntegerField(required=True)

    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(Submit("submit", "Create"))

        super(RecurringTimeLabelForm, self).__init__(*args, **kwargs)


@transaction.atomic
def create_recurring_time_labels(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)
    if role != participation_role.instructor:
        raise PermissionDenied("only instructors may do that")

    repo = get_course_repo(course)
    commit_sha = get_active_commit_sha(course, participation)
    course_desc = get_course_desc(repo, course, commit_sha)

    if request.method == "POST":
        form = RecurringTimeLabelForm(request.POST, request.FILES)
        if form.is_valid():

            time = form.cleaned_data["time"]
            ordinal = form.cleaned_data["starting_ordinal"]
            interval = form.cleaned_data["interval"]

            import datetime

            for i in xrange(form.cleaned_data["count"]):
                label = TimeLabel()
                label.course = course
                label.kind = form.cleaned_data["kind"]
                label.ordinal = ordinal
                label.time = time
                label.save()

                if interval == "weekly":
                    date = time.date()
                    date += datetime.timedelta(weeks=1)
                    print type(time.tzinfo)
                    time = time.tzinfo.localize(
                            datetime.datetime(date.year, date.month, date.day,
                                time.hour, time.minute, time.second))
                    del date
                else:
                    raise ValueError("unknown interval: %s" % interval)

                ordinal += 1

            messages.add_message(request, messages.SUCCESS,
                    "Time labels created.")
    else:
        form = RecurringTimeLabelForm()

    return render(request, "course/generic-course-form.html", {
        "participation": participation,
        "form": form,
        "form_description": "Create recurring time labels",
        "course": course,
        "course_desc": course_desc,
    })


class RenumberTimeLabelsForm(forms.Form):
    kind = forms.CharField(required=True,
            help_text="Should be lower_case_with_underscores, no spaces allowed.")
    starting_ordinal = forms.IntegerField(required=True, initial=1)

    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(Submit("submit", "Renumber"))

        super(RenumberTimeLabelsForm, self).__init__(*args, **kwargs)


@transaction.atomic
def renumber_time_labels(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)

    role, participation = get_role_and_participation(request, course)
    if role != participation_role.instructor:
        raise PermissionDenied("only instructors may do that")

    repo = get_course_repo(course)
    commit_sha = get_active_commit_sha(course, participation)
    course_desc = get_course_desc(repo, course, commit_sha)

    if request.method == "POST":
        form = RenumberTimeLabelsForm(request.POST, request.FILES)
        if form.is_valid():
            labels = list(TimeLabel.objects
                    .filter(course=course, kind=form.cleaned_data["kind"])
                    .order_by('time'))

            if labels:
                queryset = (TimeLabel.objects
                    .filter(course=course, kind=form.cleaned_data["kind"]))

                queryset.delete()

                ordinal = form.cleaned_data["starting_ordinal"]
                for label in labels:
                    new_label = TimeLabel()
                    new_label.course = course
                    new_label.kind = form.cleaned_data["kind"]
                    new_label.ordinal = ordinal
                    new_label.time = label.time
                    new_label.save()

                    ordinal += 1

                messages.add_message(request, messages.SUCCESS,
                        "Time labels renumbered.")
            else:
                messages.add_message(request, messages.ERROR,
                        "No time labels found.")

    else:
        form = RenumberTimeLabelsForm()

    return render(request, "course/generic-course-form.html", {
        "participation": participation,
        "form": form,
        "form_description": "Renumber time labels",
        "course": course,
        "course_desc": course_desc,
    })
# }}}


# vim: foldmethod=marker
