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
from django.contrib import messages
import django.forms as forms

from django.core.exceptions import PermissionDenied

from course.models import Course, participation_role

from course.content import (get_course_repo, get_course_desc)
from course.views import (
        get_role_and_participation, get_active_commit_sha
        )

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit


# {{{ fetch

class GitFetchForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        self.helper.add_input(Submit("fetch", "Fetch"))

        super(GitFetchForm, self).__init__(*args, **kwargs)


def fetch_course_updates(request, course_identifier):
    import sys

    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.instructor:
        raise PermissionDenied("must be instructor to fetch revisisons")

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)
    course_desc = get_course_desc(repo, commit_sha)

    form = GitFetchForm(request.POST, request.FILES)
    if request.method == "POST":
        if form.is_valid():
            was_successful = True
            log_lines = []
            try:
                repo = get_course_repo(course)

                if not course.git_source:
                    raise RuntimeError("no git source URL specified")

                if course.ssh_private_key:
                    repo.auth(pkey=course.ssh_private_key.encode("ascii"))

                log_lines.append("Pre-fetch head is at '%s'" % repo.head())

                from dulwich.client import get_transport_and_path
                client, remote_path = get_transport_and_path(
                        course.git_source.encode())
                remote_refs = client.fetch(remote_path, repo)
                repo["HEAD"] = remote_refs["HEAD"]

                log_lines.append("Post-fetch head is at '%s'" % repo.head())

            except Exception:
                was_successful = False
                from traceback import format_exception
                log = "\n".join(log_lines) + "".join(
                        format_exception(*sys.exc_info()))
            else:
                log = "\n".join(log_lines)

            return render(request, 'course/course-bulk-result.html', {
                "process_description": "Fetch course updates via git",
                "log": log,
                "status": "Pull successful."
                    if was_successful
                    else "Pull failed. See above for error.",
                "was_successful": was_successful,
                "course": course,
                "course_desc": course_desc,
                })
        else:
            form = GitFetchForm()
    else:
        form = GitFetchForm()

    return render(request, "course/generic-course-form.html", {
        "participation": participation,
        "form": form,
        "form_description": "Fetch New Course Revisions",
        "course": course,
        "course_desc": course_desc,
    })

# }}}

# {{{ update


class GitUpdateForm(forms.Form):
    new_sha = forms.CharField(required=True, initial=50)

    def __init__(self, previewing, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        if previewing:
            self.helper.add_input(
                    Submit("end_preview", "End preview",
                        css_class="col-lg-offset-2"))
        else:
            self.helper.add_input(
                    Submit("preview", "Validate and preview",
                        css_class="col-lg-offset-2"))

        self.helper.add_input(
                Submit("update", "Validate and update"))
        super(GitUpdateForm, self).__init__(*args, **kwargs)


def update_course(request, course_identifier):
    course = get_object_or_404(Course, identifier=course_identifier)
    role, participation = get_role_and_participation(request, course)

    if role != participation_role.instructor:
        raise PermissionDenied("must be instructor to update course")

    commit_sha = get_active_commit_sha(course, participation)

    repo = get_course_repo(course)

    course_desc = get_course_desc(repo, commit_sha)

    previewing = bool(participation is not None
            and participation.preview_git_commit_sha)

    response_form = None
    if request.method == "POST":
        form = GitUpdateForm(previewing, request.POST, request.FILES)
        if "end_preview" in form.data:
            messages.add_message(request, messages.INFO,
                    "Preview ended.")
            participation.preview_git_commit_sha = None
            participation.save()

            previewing = False

        elif form.is_valid():
            new_sha = form.cleaned_data["new_sha"].encode("utf-8")

            from course.validation import validate_course_content, ValidationError
            try:
                validate_course_content(repo, new_sha)
            except ValidationError as e:
                messages.add_message(request, messages.ERROR,
                        "Course content did not validate successfully. (%s) "
                        "Update not applied."
                        % str(e))
                validated = False
            else:
                messages.add_message(request, messages.INFO,
                        "Course content validated successfully.")
                validated = True

            if validated and "update" in form.data:
                messages.add_message(request, messages.INFO,
                        "Update applied.")

                course.active_git_commit_sha = new_sha
                course.save()

                response_form = form

            elif validated and "preview" in form.data:
                messages.add_message(request, messages.INFO,
                        "Preview activated.")

                participation.preview_git_commit_sha = new_sha
                participation.save()

                previewing = True

    if response_form is None:
        form = GitUpdateForm(previewing,
                {"new_sha": repo.head()})

    text_lines = [
            "<b>Current git HEAD:</b> %s (%s)" % (
                repo.head(),
                repo[repo.head()].message),
            "<b>Public active git SHA:</b> %s (%s)" % (
                course.active_git_commit_sha,
                repo[course.active_git_commit_sha.encode()].message),
            ]
    if participation is not None and participation.preview_git_commit_sha:
        text_lines.append(
            "<b>Current preview git SHA:</b> %s (%s)" % (
                participation.preview_git_commit_sha,
                repo[participation.preview_git_commit_sha.encode()].message,
            ))
    else:
        text_lines.append("<b>Current preview git SHA:</b> None")

    return render(request, "course/generic-course-form.html", {
        "participation": participation,
        "form": form,
        "form_text": "".join(
            "<p>%s</p>" % line
            for line in text_lines
            ),
        "form_description": "Update Course Revision",
        "course": course,
        "course_desc": course_desc,
    })

# }}}

# vim: foldmethod=marker
