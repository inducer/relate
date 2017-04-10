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

import six

from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
import django.forms as forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.utils.translation import (
        ugettext_lazy as _,
        ugettext,
        pgettext,
        pgettext_lazy,
        string_concat,
        )
from django_select2.forms import Select2Widget
from bootstrap3_datetime.widgets import DateTimePicker

from django.db import transaction

from relate.utils import StyledForm, StyledModelForm
from crispy_forms.layout import Submit

from course.models import (
        Course,
        Participation,
        ParticipationRole)

from course.utils import course_view, render_course_page
import paramiko
import paramiko.client

from dulwich.repo import Repo
import dulwich.client  # noqa

from course.constants import (
        participation_status,
        participation_permission as pperm,
        )

# {{{ for mypy

if False:
    from django import http  # noqa
    from typing import Tuple, List, Text, Any, Dict  # noqa
    from dulwich.client import GitClient  # noqa

# }}}


class AutoAcceptPolicy(paramiko.client.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        # simply accept the key
        return


def _remove_prefix(prefix, s):
    # type: (bytes, bytes) -> bytes

    assert s.startswith(prefix)

    return s[len(prefix):]


def transfer_remote_refs(repo, remote_refs):
    # type: (Repo, Dict[bytes, Text]) -> None

    valid_refs = []

    if remote_refs is not None:
        for ref, sha in six.iteritems(remote_refs):
            if (ref.startswith(b"refs/heads/")
                    and not ref.startswith(b"refs/heads/origin/")):
                new_ref = b"refs/remotes/origin/"+_remove_prefix(b"refs/heads/", ref)
                valid_refs.append(new_ref)
                repo[new_ref] = sha

    for ref in repo.get_refs().keys():
        if ref.startswith(b"refs/remotes/origin/") and ref not in valid_refs:
            del repo[ref]


class DulwichParamikoSSHVendor(object):
    def __init__(self, ssh_kwargs):
        self.ssh_kwargs = ssh_kwargs

    def run_command(self, host, command, username=None, port=None,
                    progress_stderr=None):
        if not isinstance(command, bytes):
            raise TypeError(command)

        if port is None:
            port = 22

        client = paramiko.SSHClient()

        client.set_missing_host_key_policy(AutoAcceptPolicy())
        client.connect(host, username=username, port=port,
                       **self.ssh_kwargs)

        channel = client.get_transport().open_session()

        channel.exec_command(command)

        def progress_stderr(s):
            import sys
            sys.stderr.write(s.decode("utf-8"))
            sys.stderr.flush()

        try:
            from dulwich.client import ParamikoWrapper
        except ImportError:
            from dulwich.contrib.paramiko_vendor import (
                    _ParamikoWrapper as ParamikoWrapper)

        return ParamikoWrapper(
            client, channel, progress_stderr=progress_stderr)


def get_dulwich_client_and_remote_path_from_course(course):
    # type: (Course) -> Tuple[dulwich.client.GitClient, bytes]
    ssh_kwargs = {}
    if course.ssh_private_key:
        from six import StringIO
        key_file = StringIO(course.ssh_private_key)
        ssh_kwargs["pkey"] = paramiko.RSAKey.from_private_key(key_file)

    def get_dulwich_ssh_vendor():
        vendor = DulwichParamikoSSHVendor(ssh_kwargs)
        return vendor

    # writing to another module's global variable: gross!
    dulwich.client.get_ssh_vendor = get_dulwich_ssh_vendor

    from dulwich.client import get_transport_and_path
    client, remote_path = get_transport_and_path(
            course.git_source)

    try:
        # Work around
        # https://bugs.launchpad.net/dulwich/+bug/1025886
        client._fetch_capabilities.remove('thin-pack')
    except KeyError:
        pass
    except AttributeError:
        pass

    if not isinstance(client, dulwich.client.LocalGitClient):
        # LocalGitClient uses Py3 Unicode path names to refer to
        # paths, so it doesn't want an encoded path.
        remote_path = remote_path.encode("utf-8")

    return client, remote_path


# {{{ new course setup

class CourseCreationForm(StyledModelForm):
    class Meta:
        model = Course
        fields = (
            "identifier",
            "name",
            "number",
            "time_period",
            "start_date",
            "end_date",
            "hidden", "listed",
            "accepts_enrollment",
            "git_source", "ssh_private_key", "course_root_path",
            "course_file",
            "events_file",
            "enrollment_approval_required",
            "enrollment_required_email_suffix",
            "from_email",
            "notify_email",
            )
        widgets = {
                "start_date": DateTimePicker(options={"format": "YYYY-MM-DD"}),
                "end_date": DateTimePicker(options={"format": "YYYY-MM-DD"}),
                }

    def __init__(self, *args, **kwargs):
        # type: (*Any, **Any) -> None

        super(CourseCreationForm, self).__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Validate and create")))

    def clean_git_source(self):
        if not self.cleaned_data["git_source"]:
            from django.forms import ValidationError as FormValidationError
            raise FormValidationError(_("Git source must be specified"))

        return self.cleaned_data["git_source"]


@permission_required("course.add_course")
def set_up_new_course(request):
    # type: (http.HttpRequest) -> http.HttpResponse
    if request.method == "POST":
        form = CourseCreationForm(request.POST)

        if form.is_valid():
            new_course = form.save(commit=False)

            from course.content import get_course_repo_path
            repo_path = get_course_repo_path(new_course)

            try:
                import os
                os.makedirs(repo_path)

                repo = None

                try:
                    with transaction.atomic():
                        repo = Repo.init(repo_path)

                        client, remote_path = \
                            get_dulwich_client_and_remote_path_from_course(
                                    new_course)

                        remote_refs = client.fetch(remote_path, repo)
                        if remote_refs is None:
                            raise RuntimeError(_("No refs found in remote repository"
                                    " (i.e. no master branch, no HEAD). "
                                    "This looks very much like a blank repository. "
                                    "Please create course.yml in the remote "
                                    "repository before creating your course."))

                        transfer_remote_refs(repo, remote_refs)
                        new_sha = repo[b"HEAD"] = remote_refs[b"HEAD"]

                        vrepo = repo
                        if new_course.course_root_path:
                            from course.content import SubdirRepoWrapper
                            vrepo = SubdirRepoWrapper(
                                    vrepo, new_course.course_root_path)

                        from course.validation import validate_course_content
                        validate_course_content(  # type: ignore
                                vrepo, new_course.course_file,
                                new_course.events_file, new_sha)

                        del vrepo

                        new_course.active_git_commit_sha = new_sha.decode()
                        new_course.save()

                        # {{{ set up a participation for the course creator

                        part = Participation()
                        part.user = request.user
                        part.course = new_course
                        part.status = participation_status.active
                        part.save()

                        part.roles.set([
                            # created by signal handler for course creation
                            ParticipationRole.objects.get(
                                course=new_course,
                                identifier="instructor")
                            ])

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
                    if repo is not None:  # noqa
                        repo.close()  # noqa

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
        transfer_remote_refs(repo, remote_refs)
        remote_head = remote_refs[b"HEAD"]
        if (
                prevent_discarding_revisions
                and
                is_parent_commit(repo, repo[remote_head], repo[b"HEAD"],
                    max_history_check_size=20)):
            raise RuntimeError(_("fetch would discard commits, refusing"))

        repo[b"HEAD"] = remote_head

        messages.add_message(request, messages.SUCCESS, _("Fetch successful."))

        new_sha = remote_head

    if command == "fetch":
        return

    if command == "end_preview":
        pctx.participation.preview_git_commit_sha = None
        pctx.participation.save()

        messages.add_message(request, messages.INFO,
                _("Preview ended."))

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

        pctx.participation.preview_git_commit_sha = new_sha.decode()
        pctx.participation.save()

    elif command == "update" and may_update:
        pctx.course.active_git_commit_sha = new_sha.decode()
        pctx.course.save()

        if pctx.participation.preview_git_commit_sha is not None:
            pctx.participation.preview_git_commit_sha = None
            pctx.participation.save()

            messages.add_message(request, messages.INFO,
                    _("Preview ended."))

        messages.add_message(request, messages.SUCCESS,
                _("Update applied. "))

    else:
        raise RuntimeError(_("invalid command"))


class GitUpdateForm(StyledForm):

    def __init__(self, may_update, previewing, repo, *args, **kwargs):
        super(GitUpdateForm, self).__init__(*args, **kwargs)

        repo_refs = repo.get_refs()
        commit_iter = repo.get_walker(list(repo_refs.values()))

        def format_commit(commit):
            return "%s - %s" % (
                    commit.id[:8].decode(),
                    "".join(
                        commit.message
                        .decode("utf-8", errors="replace")
                        .split("\n")
                        [:1]))

        def format_sha(sha):
            return format_commit(repo[sha])

        self.fields["new_sha"] = forms.ChoiceField(
                choices=([
                    (repo_refs[ref],
                        "[%s] %s" % (
                            ref.decode("utf-8", errors="replace"),
                            format_sha(repo_refs[ref])))
                    for ref in repo_refs
                    ] +
                    [
                    (entry.commit.id, format_commit(entry.commit))
                    for entry in commit_iter
                    ]),
                required=True,
                widget=Select2Widget(),
                label=pgettext_lazy(
                    "new git SHA for revision of course contents",
                    "New git SHA"))

        self.fields["prevent_discarding_revisions"] = forms.BooleanField(
                label=_("Prevent updating to a git revision "
                    "prior to the current one"),
                initial=True, required=False)

        def add_button(desc, label):
            self.helper.add_input(Submit(desc, label))

        if may_update:
            add_button("fetch_update", _("Fetch and update"))
            add_button("update", _("Update"))

        if previewing:
            add_button("end_preview", _("End preview"))

        add_button("fetch_preview", _("Fetch and preview"))
        add_button("preview", _("Preview"))

        add_button("fetch", _("Fetch"))


def _get_commit_message_as_html(repo, commit_sha):
    if six.PY2:
        from cgi import escape
    else:
        from html import escape

    if isinstance(commit_sha, six.text_type):
        commit_sha = commit_sha.encode()

    try:
        commit = repo[commit_sha]
    except KeyError:
        return _("- not found -")

    return escape(commit.message.strip().decode(errors="replace"))


@login_required
@course_view
def update_course(pctx):
    if not (
            pctx.has_permission(pperm.update_content)
            or
            pctx.has_permission(pperm.preview_content)):
        raise PermissionDenied()

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

    may_update = pctx.has_permission(pperm.update_content)

    response_form = None
    if request.method == "POST":
        form = GitUpdateForm(may_update, previewing, repo, request.POST,
            request.FILES)
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
                import traceback
                traceback.print_exc()

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

        form = GitUpdateForm(may_update, previewing, repo,
                {
                    "new_sha": repo.head(),
                    "prevent_discarding_revisions": True,
                    })

    text_lines = [
            "<table class='table'>",
            string_concat(
                "<tr><th>",
                ugettext("Git Source URL"),
                "</th><td><tt>%(git_source)s</tt></td></tr>")
            % {'git_source': pctx.course.git_source},
            string_concat(
                "<tr><th>",
                ugettext("Public active git SHA"),
                "</th><td> %(commit)s (%(message)s)</td></tr>")
            % {
                'commit': course.active_git_commit_sha,
                'message': _get_commit_message_as_html(
                    repo, course.active_git_commit_sha)
                },
            string_concat(
                "<tr><th>",
                ugettext("Current git HEAD"),
                "</th><td>%(commit)s (%(message)s)</td></tr>")
            % {
                'commit': repo.head().decode(),
                'message': _get_commit_message_as_html(repo, repo.head())},
            ]
    if participation is not None and participation.preview_git_commit_sha:
        text_lines.append(
                string_concat(
                    "<tr><th>",
                    ugettext("Current preview git SHA"),
                    "</th><td>%(commit)s (%(message)s)</td></tr>")
                % {
                    'commit': participation.preview_git_commit_sha,
                    'message': _get_commit_message_as_html(
                        repo, participation.preview_git_commit_sha),
                })
    else:
        text_lines.append(
                "".join([
                    "<tr><th>",
                    ugettext("Current preview git SHA"),
                    "</th><td>",
                    ugettext("None"),
                    "</td></tr>",
                    ]))

    text_lines.append("</table>")

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
