from __future__ import annotations

__copyright__ = """
Copyright (C) 2014 Andreas Kloeckner
Copyright (c) 2016 Polyconseil SAS. (the WSGI wrapping bits)
Copyright (C) 2019 Isuru Fernando
"""

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

import re

from django.shortcuts import (  # noqa
        render, get_object_or_404, redirect)
from django.contrib import messages
import django.forms as forms
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import (PermissionDenied, SuspiciousOperation)
from django.utils.translation import (
        gettext_lazy as _,
        gettext,
        pgettext,
        pgettext_lazy,
        )

from django_select2.forms import Select2Widget
from bootstrap_datepicker_plus.widgets import DateTimePickerInput
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from django.db import transaction

from django import http

from relate.utils import StyledForm, StyledModelForm, string_concat
from crispy_forms.layout import Submit

from course.models import (
        Course,
        Participation,
        ParticipationRole)

from course.auth import with_course_api_auth

from course.utils import (
    course_view, render_course_page,
    get_course_specific_language_choices)
import paramiko
import paramiko.client

from dulwich.repo import Repo
import dulwich.client  # noqa

from course.constants import (
        participation_status,
        participation_permission as pperm,
        )

from typing import cast

# {{{ for mypy

from typing import Tuple, List, Text, Any, Dict, Union, Optional, TYPE_CHECKING  # noqa
if TYPE_CHECKING:
    from dulwich.client import GitClient  # noqa
    from dulwich.objects import Commit  # noqa
    import dulwich.web # noqa
    from course.auth import APIContext # noqa

# }}}


def _remove_prefix(prefix: bytes, s: bytes) -> bytes:

    assert s.startswith(prefix)

    return s[len(prefix):]


def transfer_remote_refs(
        repo: Repo, fetch_pack_result: dulwich.client.FetchPackResult) -> None:

    valid_refs = []

    for ref, sha in fetch_pack_result.refs.items():
        if (ref.startswith(b"refs/heads/")
                and not ref.startswith(b"refs/heads/origin/")):
            new_ref = b"refs/remotes/origin/"+_remove_prefix(b"refs/heads/", ref)
            valid_refs.append(new_ref)
            repo[new_ref] = sha

    for ref in repo.get_refs().keys():
        if ref.startswith(b"refs/remotes/origin/") and ref not in valid_refs:
            del repo[ref]


def get_dulwich_client_and_remote_path_from_course(
        course: Course) -> Tuple[
                Union[dulwich.client.GitClient, dulwich.client.SSHGitClient], bytes]:
    # noqa
    ssh_kwargs = {}
    if course.ssh_private_key:
        from io import StringIO
        key_file = StringIO(course.ssh_private_key)
        ssh_kwargs["pkey"] = paramiko.RSAKey.from_private_key(key_file)

    def get_dulwich_ssh_vendor():
        from dulwich.contrib.paramiko_vendor import ParamikoSSHVendor
        vendor = ParamikoSSHVendor(**ssh_kwargs)
        return vendor

    # writing to another module's global variable: gross!
    dulwich.client.get_ssh_vendor = get_dulwich_ssh_vendor

    from dulwich.client import get_transport_and_path
    client, remote_path = get_transport_and_path(
            course.git_source)

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
            "preapproval_require_verified_inst_id",
            "enrollment_required_email_suffix",
            "from_email",
            "notify_email",
            "force_lang",
            )
        widgets = {
                "start_date": DateTimePickerInput(options={"format": "YYYY-MM-DD"}),
                "end_date": DateTimePickerInput(options={"format": "YYYY-MM-DD"}),
                "force_lang": forms.Select(
                    choices=get_course_specific_language_choices()),
                }

    def __init__(self, *args: Any, **kwargs: Any) -> None:

        super().__init__(*args, **kwargs)

        self.helper.add_input(
                Submit("submit", _("Validate and create")))


@permission_required("course.add_course")
def set_up_new_course(request: http.HttpRequest) -> http.HttpResponse:
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

                        fetch_pack_result = client.fetch(remote_path, repo)
                        if not fetch_pack_result.refs:
                            raise RuntimeError(_("No refs found in remote repository"
                                    " (i.e. no master branch, no HEAD). "
                                    "This looks very much like a blank repository. "
                                    "Please create course.yml in the remote "
                                    "repository before creating your course."))

                        transfer_remote_refs(repo, fetch_pack_result)
                        new_sha = repo[b"HEAD"] = fetch_pack_result.refs[b"HEAD"]

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
                except Exception as e:
                    # Don't coalesce this handler with the one below. We only want
                    # to delete the directory if we created it. Trust me.

                    # Make sure files opened for 'repo' above are actually closed.
                    if repo is not None:  # noqa
                        repo.close()  # noqa

                    from relate.utils import force_remove_path

                    try:
                        force_remove_path(repo_path)
                    except OSError:
                        messages.add_message(request, messages.WARNING,
                                gettext("Failed to delete unused "
                                "repository directory '%s'.")
                                % repo_path)

                    # We don't raise the OSError thrown by force_remove_path
                    # This is to ensure correct error msg for PY2.
                    raise e

                else:
                    assert repo is not None
                    repo.close()

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

def is_ancestor_commit(
        repo: Repo, potential_ancestor: Commit, child: Commit,
        max_history_check_size: Optional[int] = None) -> bool:

    queue = [repo[parent] for parent in child.parents]

    while queue:
        entry = queue.pop()
        if entry == potential_ancestor:
            return True

        if max_history_check_size is not None:
            max_history_check_size -= 1

            if max_history_check_size == 0:
                return False

        queue.extend(repo[parent] for parent in entry.parents)

    return False


ALLOWED_COURSE_REVISIOIN_COMMANDS = [
    "fetch", "fetch_update", "update", "fetch_preview",
    "preview", "end_preview"]


def run_course_update_command(
        request, repo, content_repo, pctx, command, new_sha, may_update,
        prevent_discarding_revisions):
    if command not in ALLOWED_COURSE_REVISIOIN_COMMANDS:
        raise RuntimeError(_("invalid command"))

    if command.startswith("fetch"):
        if command != "fetch":
            command = command[6:]

        client, remote_path = \
            get_dulwich_client_and_remote_path_from_course(pctx.course)

        fetch_pack_result = client.fetch(remote_path, repo)

        assert isinstance(fetch_pack_result, dulwich.client.FetchPackResult)

        transfer_remote_refs(repo, fetch_pack_result)
        remote_head = fetch_pack_result.refs[b"HEAD"]
        if prevent_discarding_revisions:
            # Guard against bad scenario:
            # Local is not ancestor of remote, i.e. the branches have diverged.
            if not is_ancestor_commit(repo, repo[b"HEAD"], repo[remote_head],
                    max_history_check_size=20) and \
                    repo[b"HEAD"] != repo[remote_head]:
                raise RuntimeError(_("internal git repo has more commits. Fetch, "
                                     "merge and push."))

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
                _("Course content did not validate successfully: '%s' "
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
                        % {"location": w.location, "warningtext": w.text}
                        for w in warnings)))

    # }}}

    if command == "preview":
        messages.add_message(request, messages.INFO,
                _("Preview activated."))

        pctx.participation.preview_git_commit_sha = new_sha.decode()
        pctx.participation.save()

    elif command == "update" and may_update:  # pragma: no branch
        pctx.course.active_git_commit_sha = new_sha.decode()
        pctx.course.save()

        if pctx.participation.preview_git_commit_sha is not None:
            pctx.participation.preview_git_commit_sha = None
            pctx.participation.save()

            messages.add_message(request, messages.INFO,
                    _("Preview ended."))

        messages.add_message(request, messages.SUCCESS,
                _("Update applied. "))


class GitUpdateForm(StyledForm):

    def __init__(self, may_update, previewing, repo, *args, **kwargs):
        super().__init__(*args, **kwargs)

        repo_refs = repo.get_refs()
        commit_iter = repo.get_walker(list(repo_refs.values()))

        def format_commit(commit):
            return "{} - {}".format(
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
                    (repo_refs[ref].decode(),
                        "[{}] {}".format(
                            ref.decode("utf-8", errors="replace"),
                            format_sha(repo_refs[ref])))
                    for ref in repo_refs
                    ] + [
                    (entry.commit.id.decode(), format_commit(entry.commit))
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
    from html import escape

    if isinstance(commit_sha, str):
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
            or pctx.has_permission(pperm.preview_content)):
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
    form = None
    if request.method == "POST":
        form = GitUpdateForm(may_update, previewing, repo, request.POST,
            request.FILES)

        command = None
        for cmd in ALLOWED_COURSE_REVISIOIN_COMMANDS:
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
                    "new_sha": repo.head().decode(),
                    "prevent_discarding_revisions": True,
                    })

    from django.template.loader import render_to_string
    form_text = render_to_string(
        "course/git-sha-table.html", {
            "participation": participation,
            "is_previewing": previewing,
            "course": course,
            "repo": repo,
            "current_git_head": repo.head().decode(),
            "git_url": request.build_absolute_uri(
                reverse("relate-git_endpoint",
                    args=(course.identifier, ""))),
            "token_url": reverse("relate-manage_authentication_tokens",
                    args=(course.identifier,)),
        })

    assert form is not None

    return render_course_page(pctx, "course/generic-course-form.html", {
        "form": form,
        "form_text": form_text,
        "form_description": gettext("Update Course Revision"),
    })

# }}}


# {{{ git endpoint


# {{{ wsgi wrapping

# Nabbed from
# https://github.com/Polyconseil/django-viewsgi/blob/master/viewsgi.py
# (BSD-licensed)

def call_wsgi_app(
        application: dulwich.web.LimitedInputFilter,
        request: http.HttpRequest,
        prefix: str,
        ) -> http.HttpResponse:

    response = http.HttpResponse()

    # request.environ and request.META are the same object, so changes
    # to the headers by middlewares will be seen here.
    assert request.environ == request.META
    environ = request.environ.copy()
    #if len(args) > 0:
    assert environ["PATH_INFO"].startswith(prefix)
    environ["SCRIPT_NAME"] += prefix
    environ["PATH_INFO"] = environ["PATH_INFO"][len(prefix):]

    headers_set: List[Tuple[str, str]] = []
    headers_sent: List[bool] = []

    def write(data: str) -> None:
        if not headers_set:
            raise AssertionError("write() called before start_response()")
        if not headers_sent:
            # Send headers before the first output.
            for k, v in headers_set:
                response[k] = v
            headers_sent[:] = [True]
        response.write(data)
        # We could call response.flush() here, but is actually a no-op.

    def start_response(status, headers, exc_info=None):
        # Let Django handle all errors.
        if exc_info:
            raise exc_info[1].with_traceback(exc_info[2])
        if headers_set:
            raise AssertionError("start_response() called again "
                                 "without exc_info")
        response.status_code = int(status.split(" ", 1)[0])
        headers_set[:] = headers
        # Django provides no way to set the reason phrase (#12747).
        return write

    result = application(environ, start_response)
    try:
        for data in result:
            if data:
                write(data)
        if not headers_sent:
            write("")
    finally:
        if hasattr(result, "close"):
            result.close()

    return response

# }}}


GIT_AUTH_DATA_RE = re.compile(r"^(\w+):([0-9]+)_([a-z0-9]+)$")


@csrf_exempt
@with_course_api_auth("Basic")
def git_endpoint(api_ctx: APIContext, course_identifier: str,
        git_path: str) -> http.HttpResponse:

    course = api_ctx.course
    request = api_ctx.request

    if not api_ctx.has_permission(pperm.use_git_endpoint):
        raise PermissionDenied("insufficient privileges")

    from course.content import get_course_repo
    repo = get_course_repo(course)

    from course.content import SubdirRepoWrapper
    if isinstance(repo, SubdirRepoWrapper):
        true_repo = repo.repo
    else:
        true_repo = cast(dulwich.repo.Repo, repo)

    base_path = reverse(git_endpoint, args=(course_identifier, ""))
    assert base_path.endswith("/")
    base_path = base_path[:-1]

    import dulwich.web as dweb
    backend = dweb.DictBackend({"/": true_repo})
    app = dweb.make_wsgi_chain(backend)

    return call_wsgi_app(app, request, base_path)

# }}}

# vim: foldmethod=marker
