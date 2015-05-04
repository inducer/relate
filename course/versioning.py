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
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.urlresolvers import reverse

from django.db import transaction

from relate.utils import StyledForm, StyledModelForm
from crispy_forms.layout import Submit

from course.models import (
        Course,
        Participation, participation_role, participation_status)

from course.utils import course_view, render_course_page
import pygit2


class PyGit2RemoteWithSSHKey(pygit2.Remote):
    def __init__(self, repo, url, ssh_private_key):
        super(PyGit2RemoteWithSSHKey, self).__init__(repo, url)
        self.ssh_private_key = ssh_private_key

        self.fetched_tips = {}


RELATE_REMOTE_NAME = "relate-fetch"


def mop_up_remote(repo):
    for r in repo.remotes:
        if r.name == RELATE_REMOTE_NAME:
            repo.remotes.delete(RELATE_REMOTE_NAME)


def get_git_remote_from_course(repo, course):
    mop_up_remote(repo)
    remote = repo.create_remote(
            RELATE_REMOTE_NAME,
            course.git_source)

    try:
        fetched_tips = {}

        def update_tips(refname, old, new):
            fetched_tips[refname] = (old, new)

        def credentials(url, username_from_url, allowed_types):
            return pygit2.Keypair(
                    username=username_from_url,
                    privkey=course.ssh_private_key)

        remote.update_tips = update_tips
        remote.credentials = credentials

        return remote, fetched_tips

    finally:
        mop_up_remote(repo)


# {{{ new course setup

class CourseCreationForm(StyledModelForm):
    class Meta:
        model = Course
        fields = (
            "identifier", "hidden", "listed",
            "accepts_enrollment",
            "git_source", "ssh_private_key",
            "course_file",
            "events_file",
            "enrollment_approval_required",
            "enrollment_required_email_suffix",
            "from_email",
            "notify_email",
            )

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
                        repo = pygit2.init_repository(
                                repo_path,
                                bare=True)

                        remote, fetched_tips = get_git_remote_from_course(
                                repo, new_course)

                        remote.fetch()
                        (_, new_sha), = fetched_tips.values()

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
                                % reverse("relate-check_events",
                                    args=(new_course.identifier,)))
                except:
                    # Don't coalesce this handler with the one below. We only want
                    # to delete the directory if we created it. Trust me.

                    # Work around read-only files on Windows.
                    # https://docs.python.org/3.5/library/shutil.html#rmtree-example

                    import os
                    import stat
                    import shutil

                    def remove_readonly(func, path, _):
                        "Clear the readonly bit and reattempt the removal"
                        os.chmod(path, stat.S_IWRITE)
                        func(path)

                    shutil.rmtree(repo_path, onerror=remove_readonly)

                    raise

            except Exception as e:
                from traceback import print_exc
                print_exc()

                messages.add_message(request, messages.ERROR,
                        "Course creation failed: %s: %s" % (
                            type(e).__name__, str(e)))
            else:
                return redirect(
                        "relate-course_page",
                        new_course.identifier)

    else:
        form = CourseCreationForm()

    return render(request, "generic-form.html", {
        "form_description": "Set up new course",
        "form": form
        })

# }}}


# {{{ update

def is_parent_commit(repo, potential_parent, child):
    for commit in repo.walk(child.id):
        if commit.id == potential_parent.id:
            return True

    return False


def run_course_update_command(request, pctx, command, new_sha, may_update):
    repo = pctx.repo

    if command.startswith("fetch_"):
        command = command[6:]

        if not pctx.course.git_source:
            raise RuntimeError("no git source URL specified")

        remote, fetched_tips = get_git_remote_from_course(repo, pctx.course)

        remote.fetch()
        (_, remote_head), = fetched_tips.values()

        if (repo[remote_head].id != repo[repo.head.target].id
                and is_parent_commit(
                    repo,
                    repo[remote_head],
                    repo[repo.head.target])):
            raise RuntimeError("fetch would discard commits, refusing")

        repo.reset(remote_head, pygit2.GIT_RESET_SOFT)
        new_sha = repo.head.target

        messages.add_message(request, messages.SUCCESS, "Fetch successful.")

    if command == "end_preview":
        messages.add_message(request, messages.INFO,
                "Preview ended.")
        pctx.participation.preview_git_commit_sha = None
        pctx.participation.save()

        return

    # {{{ validate

    from course.validation import validate_course_content, ValidationError
    try:
        warnings = validate_course_content(
                repo, pctx.course.course_file, pctx.course.events_file, new_sha)
    except ValidationError as e:
        messages.add_message(request, messages.ERROR,
                "Course content did not validate successfully. (%s) "
                "Update not applied." % str(e))
        return

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

    # }}}

    if command == "preview":
        messages.add_message(request, messages.INFO,
                "Preview activated.")

        pctx.participation.preview_git_commit_sha = new_sha
        pctx.participation.save()

    elif command == "update" and may_update:
        pctx.course.active_git_commit_sha = new_sha
        pctx.course.valid = True
        pctx.course.save()

        messages.add_message(request, messages.SUCCESS,
                "Update applied. "
                "You may want to view the events used "
                "in the course content and check that they "
                "are recognized. "
                + '<p><a href="%s" class="btn btn-primary" '
                'style="margin-top:8px">'
                'Check &raquo;</a></p>'
                % reverse("relate-check_events",
                    args=(pctx.course.identifier,)))

    else:
        raise RuntimeError("invalid command")


class GitUpdateForm(StyledForm):
    new_sha = forms.CharField(required=True)

    def __init__(self, may_update, previewing, *args, **kwargs):
        super(GitUpdateForm, self).__init__(*args, **kwargs)

        first_button = [True]

        def add_button(desc, label):
            if first_button[0]:
                self.helper.add_input(
                        Submit(desc, label, css_class="col-lg-offset-2"))
                first_button[0] = False
            else:
                self.helper.add_input(Submit(desc, label))

        if may_update:
            add_button("fetch_update", "Fetch and update")
            add_button("update", "Update")

        if previewing:
            add_button("end_preview", "End preview")
        else:
            add_button("fetch_preview", "Fetch and preview")
            add_button("preview", "Preview")


@login_required
@course_view
def update_course(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant
            ]:
        raise PermissionDenied("must be instructor or TA to update course")

    course = pctx.course
    request = pctx.request
    repo = pctx.repo
    participation = pctx.participation

    previewing = bool(participation is not None
            and participation.preview_git_commit_sha)

    may_update = pctx.role == participation_role.instructor

    response_form = None
    if request.method == "POST":
        form = GitUpdateForm(may_update, previewing, request.POST, request.FILES)
        commands = ["fetch_update", "update", "fetch_preview",
                "preview", "end_preview"]

        command = None
        for cmd in commands:
            if cmd in form.data:
                command = cmd
                break

        if command is None:
            raise SuspiciousOperation("invalid command")

        if form.is_valid():
            new_sha = form.cleaned_data["new_sha"].encode()

            try:
                run_course_update_command(request, pctx, command, new_sha,
                        may_update)
            except Exception as e:
                messages.add_message(pctx.request, messages.ERROR,
                        "Error: %s %s" % (type(e).__name__, str(e)))

    if response_form is None:
        previewing = bool(participation is not None
                and participation.preview_git_commit_sha)

        form = GitUpdateForm(may_update, previewing,
                {"new_sha": repo.head.target})

    text_lines = [
            "<b>Current git HEAD:</b> %s (%s)" % (
                repo.head.target,
                repo[repo.head.target].message.strip()),
            "<b>Public active git SHA:</b> %s (%s)" % (
                course.active_git_commit_sha,
                repo[course.active_git_commit_sha.encode()].message.strip()),
            ]
    if participation is not None and participation.preview_git_commit_sha:
        text_lines.append(
            "<b>Current preview git SHA:</b> %s (%s)" % (
                participation.preview_git_commit_sha,
                repo[participation.preview_git_commit_sha.encode()].message.strip(),
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
