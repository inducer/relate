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
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.utils.safestring import mark_safe

from django.db import transaction

from courseflow.utils import StyledForm, StyledModelForm
from crispy_forms.layout import Submit

from course.models import (
        Course,
        Participation, participation_role, participation_status)

from course.utils import course_view, render_course_page
import paramiko
import paramiko.client


class AutoAcceptPolicy(paramiko.client.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        # simply accept the key
        return


class DulwichParamikoSSHVendor(object):
    def __init__(self, ssh_kwargs):
        self.ssh_kwargs = ssh_kwargs

    def run_command(self, host, command, username=None, port=None,
                    progress_stderr=None):
        if port is None:
            port = 22

        client = paramiko.SSHClient()

        client.set_missing_host_key_policy(AutoAcceptPolicy())
        client.connect(host, username=username, port=port,
                       **self.ssh_kwargs)

        channel = client.get_transport().open_session()

        channel.exec_command(*command)

        from dulwich.client import ParamikoWrapper
        return ParamikoWrapper(
            client, channel, progress_stderr=progress_stderr)


def get_dulwich_client_and_remote_path_from_course(course):
    ssh_kwargs = {}
    if course.ssh_private_key:
        from StringIO import StringIO
        key_file = StringIO(course.ssh_private_key.encode())
        ssh_kwargs["pkey"] = paramiko.RSAKey.from_private_key(key_file)

    def get_dulwich_ssh_vendor():
        vendor = DulwichParamikoSSHVendor(ssh_kwargs)
        return vendor

    # writing to another module's global variable: gross!
    import dulwich.client
    dulwich.client.get_ssh_vendor = get_dulwich_ssh_vendor

    from dulwich.client import get_transport_and_path
    client, remote_path = get_transport_and_path(
            course.git_source.encode())

    # Work around
    # https://bugs.launchpad.net/dulwich/+bug/1025886
    client._fetch_capabilities.remove('thin-pack')

    return client, remote_path


# {{{ new course setup

class CourseCreationForm(StyledModelForm):
    class Meta:
        model = Course
        fields = (
            "identifier", "hidden",
            "git_source", "ssh_private_key",
            "course_file",
            "events_file",
            "enrollment_approval_required",
            "enrollment_required_email_suffix",
            "email")

    def __init__(self, *args, **kwargs):
        super(CourseCreationForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", "Validate and create",
                    css_class="col-lg-offset-2"))


@login_required
def set_up_new_course(request):
    if not request.user.is_staff:
        raise PermissionDenied("only staff may create courses")

    if request.method == "POST":
        form = CourseCreationForm(request.POST)

        if form.is_valid():
            new_course = form.save(commit=False)

            from course.content import get_course_repo_path
            repo_path = get_course_repo_path(new_course)

            try:
                import os
                os.makedirs(repo_path)

                try:
                    with transaction.atomic():
                        from dulwich.repo import Repo
                        repo = Repo.init(repo_path)

                        client, remote_path = \
                            get_dulwich_client_and_remote_path_from_course(
                                    new_course)

                        remote_refs = client.fetch(remote_path, repo)
                        new_sha = repo["HEAD"] = remote_refs["HEAD"]

                        from course.validation import validate_course_content
                        validate_course_content(
                                repo, new_course.course_file,
                                new_course.events_file, new_sha)

                        new_course.valid = True
                        new_course.active_git_commit_sha = new_sha
                        new_course.save()

                        # {{{ set up a participation for the course creator

                        part = Participation()
                        part.user = request.user
                        part.course = new_course
                        part.role = participation_role.instructor
                        part.status = participation_status.active
                        part.save()

                        # }}}

                        messages.add_message(request, messages.INFO,
                                "Course content validated, creation succeeded. "
                                "You may want to view the events used "
                                "in the course content and create them. "
                                + '<a href="%s" class="btn btn-primary">'
                                'Check &raquo;</a>'
                                % reverse("course.calendar.check_events",
                                    args=(new_course.identifier,)))
                except:
                    # Don't coalesce this handler with the one below. We only want
                    # to delete the directory if we created it. Trust me.
                    import shutil
                    shutil.rmtree(repo_path)
                    raise

            except Exception as e:
                from traceback import print_exc
                print_exc()

                messages.add_message(request, messages.ERROR,
                        "Course creation failed: %s: %s" % (
                            type(e).__name__, str(e)))
            else:
                return redirect(
                        "course.views.course_page",
                        new_course.identifier)

    else:
        form = CourseCreationForm()

    return render(request, "generic-form.html", {
        "form_description": "Set up new course",
        "form": form
        })

# }}}


# {{{ fetch

class GitFetchForm(StyledForm):
    def __init__(self, *args, **kwargs):
        super(GitFetchForm, self).__init__(*args, **kwargs)

        self.helper.add_input(Submit("fetch", "Fetch"))


def is_parent_commit(repo, potential_parent, child, max_history_check_size=None):
    queue = [repo[parent] for parent in child.parents]

    while queue:
        entry = queue.pop()
        if entry == potential_parent:
            return True

        if max_history_check_size is not None:
            max_history_check_size -= 1

            if max_history_check_size == 0:
                return False

        queue.extend(repo[parent] for parent in entry.parents)

    return False


def fetch_course_updates_inner(pctx):
    import sys

    if pctx.role != participation_role.instructor:
        raise PermissionDenied("must be instructor to fetch revisisons")

    form = GitFetchForm(pctx.request.POST, pctx.request.FILES)
    if pctx.request.method == "POST":
        if form.is_valid():
            was_successful = True
            log_lines = []
            try:
                repo = pctx.repo

                if not pctx.course.git_source:
                    raise RuntimeError("no git source URL specified")

                log_lines.append("Pre-fetch head is at '%s'" % repo.head())

                client, remote_path = \
                    get_dulwich_client_and_remote_path_from_course(pctx.course)

                remote_refs = client.fetch(remote_path, repo)
                remote_head = remote_refs["HEAD"]
                if is_parent_commit(repo, repo[remote_head], repo["HEAD"],
                        max_history_check_size=10):
                    raise RuntimeError("fetch would discard commits, refusing")

                repo["HEAD"] = remote_head

                log_lines.append("Post-fetch head is at '%s'" % repo.head())

            except Exception:
                was_successful = False
                from traceback import format_exception
                log = "\n".join(log_lines) + "".join(
                        format_exception(*sys.exc_info()))
            else:
                log = "\n".join(log_lines)

            if was_successful:
                messages.add_message(pctx.request, messages.SUCCESS,
                        "Fetch successful.")
                return redirect(
                        "course.versioning.update_course",
                        pctx.course.identifier)

            return render_course_page(pctx, 'course/course-bulk-result.html', {
                "process_description": "Fetch course updates via git",
                "log": log,
                "status": "Fetch failed. See above for error.",
                "was_successful": was_successful,
                })
        else:
            form = GitFetchForm()
    else:
        form = GitFetchForm()

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_description": "Fetch New Course Revisions",
    })


@login_required
@course_view
def fetch_course_updates(pctx):
    return fetch_course_updates_inner(pctx)

# }}}


# {{{ update

class GitUpdateForm(StyledForm):
    new_sha = forms.CharField(required=True)

    def __init__(self, previewing, *args, **kwargs):
        super(GitUpdateForm, self).__init__(*args, **kwargs)

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
        self.helper.add_input(
                Submit("fetch", mark_safe("&laquo; Fetch again")))


@login_required
@course_view
def update_course(pctx):
    if pctx.role != participation_role.instructor:
        raise PermissionDenied("must be instructor to update course")

    course = pctx.course
    request = pctx.request
    repo = pctx.repo
    participation = pctx.participation

    previewing = bool(participation is not None
            and participation.preview_git_commit_sha)

    response_form = None
    if request.method == "POST":
        form = GitUpdateForm(previewing, request.POST, request.FILES)
        if "fetch" in form.data:
            return fetch_course_updates_inner(pctx)

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
                warnings = validate_course_content(
                        repo, course.course_file, course.events_file, new_sha)
            except ValidationError as e:
                messages.add_message(request, messages.ERROR,
                        "Course content did not validate successfully. (%s) "
                        "Update not applied." % str(e))
                validated = False
            else:
                if not warnings:
                    messages.add_message(request, messages.SUCCESS,
                            "Course content validated successfully.")
                else:
                    messages.add_message(request, messages.WARNING,
                            "Course content validated OK, with warnings:"
                            "<ul>%s</ul>"
                            % ("".join(
                                "<li><i>%s</i>: %s</li>" % (w.location, w.text)
                                for w in warnings)))

                validated = True

            if validated and "update" in form.data:
                messages.add_message(request, messages.INFO,
                        "Update applied. "
                        "You may want to view the events used "
                        "in the course content and check that they "
                        "are recognized. "
                        + '<p><a href="%s" class="btn btn-primary" '
                        'style="margin-top:8px">'
                        'Check &raquo;</a></p>'
                        % reverse("course.calendar.check_events",
                            args=(course.identifier,)))

                course.active_git_commit_sha = new_sha
                course.valid = True
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

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_text": "".join(
            "<p>%s</p>" % line
            for line in text_lines
            ),
        "form_description": "Update Course Revision",
    })

# }}}

# vim: foldmethod=marker
