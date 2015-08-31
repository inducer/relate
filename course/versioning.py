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
from django.utils.translation import (
        ugettext_lazy as _,
        ugettext,
        pgettext,
        pgettext_lazy,
        string_concat,
        )

from django.db import transaction

from relate.utils import StyledForm, StyledModelForm
from crispy_forms.layout import Submit

from course.models import (
        Course,
        Participation, participation_role, participation_status)

from course.utils import course_view, render_course_page
import paramiko
import paramiko.client
import cgi


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

        channel.exec_command(" ".join(command))

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
            "identifier", "hidden", "listed",
            "accepts_enrollment",
            "git_source", "ssh_private_key", "course_root_path",
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
                Submit("submit", _("Validate and create"),
                    css_class="col-lg-offset-2"))


@login_required
def set_up_new_course(request):
    if not request.user.is_staff:
        raise PermissionDenied(_("only staff may create courses"))

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

                        vrepo = repo
                        if new_course.course_root_path:
                            from course.content import SubdirRepoWrapper
                            vrepo = SubdirRepoWrapper(
                                    vrepo, new_course.course_root_path)

                        from course.validation import validate_course_content
                        validate_course_content(
                                vrepo, new_course.course_file,
                                new_course.events_file, new_sha)

                        del repo
                        del vrepo

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
                                _("Course content validated, creation "
                                "succeeded."))
                except:
                    # Don't coalesce this handler with the one below. We only want
                    # to delete the directory if we created it. Trust me.

                    # Work around read-only files on Windows.
                    # https://docs.python.org/3.5/library/shutil.html#rmtree-example

                    import os
                    import stat
                    import shutil

                    # Make sure files opened for 'repo' above are actually closed.
                    import gc
                    gc.collect()

                    def remove_readonly(func, path, _):  # noqa
                        "Clear the readonly bit and reattempt the removal"
                        os.chmod(path, stat.S_IWRITE)
                        func(path)

                    try:
                        shutil.rmtree(repo_path, onerror=remove_readonly)
                    except OSError:
                        messages.add_message(request, messages.WARNING,
                                ugettext("Failed to delete unused "
                                "repository directory '%s'.")
                                % repo_path)

                    raise

            except Exception as e:
                from traceback import print_exc
                print_exc()

                messages.add_message(request, messages.ERROR,
                        string_concat(
                            _("Course creation failed"),
                            ": %(err_type)s: %(err_str)s")
                        % {"err_type": type(e).__name__,
                            "err_str": str(e)})
            else:
                return redirect(
                        "relate-course_page",
                        new_course.identifier)

    else:
        form = CourseCreationForm()

    return render(request, "generic-form.html", {
        "form_description": _("Set up new course"),
        "form": form
        })

# }}}


# {{{ update

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


def run_course_update_command(
        request, repo, content_repo, pctx, command, new_sha, may_update,
        prevent_discarding_revisions):
    if command.startswith("fetch"):
        if command != "fetch":
            command = command[6:]

        if not pctx.course.git_source:
            raise RuntimeError(_("no git source URL specified"))

        client, remote_path = \
            get_dulwich_client_and_remote_path_from_course(pctx.course)

        remote_refs = client.fetch(remote_path, repo)
        remote_head = remote_refs["HEAD"]
        if (
                prevent_discarding_revisions
                and
                is_parent_commit(repo, repo[remote_head], repo["HEAD"],
                    max_history_check_size=20)):
            raise RuntimeError(_("fetch would discard commits, refusing"))

        repo["HEAD"] = remote_head

        messages.add_message(request, messages.SUCCESS, _("Fetch successful."))

        new_sha = remote_head

    if command == "fetch":
        return

    if command == "end_preview":
        messages.add_message(request, messages.INFO,
                _("Preview ended."))
        pctx.participation.preview_git_commit_sha = None
        pctx.participation.save()

        return

    # {{{ validate

    from course.validation import validate_course_content, ValidationError
    try:
        warnings = validate_course_content(
                content_repo, pctx.course.course_file, pctx.course.events_file,
                new_sha, course=pctx.course)
    except ValidationError as e:
        messages.add_message(request, messages.ERROR,
                _("Course content did not validate successfully. (%s) "
                "Update not applied.") % str(e))
        return

    else:
        if not warnings:
            messages.add_message(request, messages.SUCCESS,
                    _("Course content validated successfully."))
        else:
            messages.add_message(request, messages.WARNING,
                    string_concat(
                        _("Course content validated OK, with warnings: "),
                        "<ul>%s</ul>")
                    % ("".join(
                        "<li><i>%(location)s</i>: %(warningtext)s</li>"
                        % {'location': w.location, 'warningtext': w.text}
                        for w in warnings)))

    # }}}

    if command == "preview":
        messages.add_message(request, messages.INFO,
                _("Preview activated."))

        pctx.participation.preview_git_commit_sha = new_sha
        pctx.participation.save()

    elif command == "update" and may_update:
        pctx.course.active_git_commit_sha = new_sha
        pctx.course.valid = True
        pctx.course.save()

        messages.add_message(request, messages.SUCCESS,
                _("Update applied. "))

    else:
        raise RuntimeError(_("invalid command"))


class GitUpdateForm(StyledForm):
    new_sha = forms.CharField(required=True,
            label=pgettext_lazy(
                "new git SHA for revision of course contents",
                "New git SHA"))
    prevent_discarding_revisions = forms.BooleanField(
            label=_("Prevent updating to a git revision "
                "prior to the current one"),
            initial=True, required=False)

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
            add_button("fetch_update", _("Fetch and update"))
            add_button("update", _("Update"))

        if previewing:
            add_button("end_preview", _("End preview"))
        else:
            add_button("fetch_preview", _("Fetch and preview"))
            add_button("preview", _("Preview"))

        add_button("fetch", _("Fetch"))


@login_required
@course_view
def update_course(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant
            ]:
        raise PermissionDenied(
                _("must be instructor or TA to update course"))

    course = pctx.course
    request = pctx.request
    content_repo = pctx.repo

    from course.content import SubdirRepoWrapper
    if isinstance(content_repo, SubdirRepoWrapper):
        repo = content_repo.repo
    else:
        repo = content_repo

    participation = pctx.participation

    previewing = bool(participation is not None
            and participation.preview_git_commit_sha)

    may_update = pctx.role == participation_role.instructor

    response_form = None
    if request.method == "POST":
        form = GitUpdateForm(may_update, previewing, request.POST, request.FILES)
        commands = ["fetch", "fetch_update", "update", "fetch_preview",
                "preview", "end_preview"]

        command = None
        for cmd in commands:
            if cmd in form.data:
                command = cmd
                break

        if command is None:
            raise SuspiciousOperation(_("invalid command"))

        if form.is_valid():
            new_sha = form.cleaned_data["new_sha"].encode()

            try:
                run_course_update_command(
                        request, repo, content_repo, pctx, command, new_sha,
                        may_update,
                        prevent_discarding_revisions=form.cleaned_data[
                            "prevent_discarding_revisions"])
            except Exception as e:
                messages.add_message(pctx.request, messages.ERROR,
                        string_concat(
                            pgettext("Starting of Error message",
                                "Error"),
                            ": %(err_type)s %(err_str)s")
                        % {"err_type": type(e).__name__,
                            "err_str": str(e)})
        else:
            response_form = form

    if response_form is None:
        previewing = bool(participation is not None
                and participation.preview_git_commit_sha)

        form = GitUpdateForm(may_update, previewing,
                {
                    "new_sha": repo.head(),
                    "prevent_discarding_revisions": True,
                    })

    text_lines = [
            string_concat(
                "<b>",
                ugettext("Current git HEAD"),
                ":</b> %(commit)s (%(message)s)")
            % {
                'commit': repo.head(),
                'message': cgi.escape(repo[repo.head()].message.strip())},
            string_concat(
                "<b>",
                ugettext("Public active git SHA"),
                ":</b> %(commit)s (%(message)s)")
            % {
                'commit': course.active_git_commit_sha,
                'message': (
                    cgi.escape(repo[course.active_git_commit_sha.encode()]
                        .message.strip()))
                },
            ]
    if participation is not None and participation.preview_git_commit_sha:
        text_lines.append(
                string_concat(
                    "<b>",
                    ugettext("Current preview git SHA"),
                    ":</b> %(commit)s (%(message)s)")
                % {
                    'commit': participation.preview_git_commit_sha,
                    'message': (
                        cgi.escape(repo[participation.preview_git_commit_sha
                            .encode()].message.strip())),
                })
    else:
        text_lines.append(
                "".join([
                    "<b>",
                    ugettext("Current preview git SHA"),
                    ":</b> ",
                    ugettext("None")]))

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_text": "".join(
            "<p>%s</p>" % line
            for line in text_lines
            ),
        "form_description": ugettext("Update Course Revision"),
    })

# }}}

# vim: foldmethod=marker
