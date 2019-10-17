# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2019 Isuru Fernando"

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

import textwrap

import django.forms as forms
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied
from django.utils.translation import ugettext_lazy as _
from django import http  # noqa
from django.utils.timezone import now

from crispy_forms.layout import Submit

from course.utils import course_view, render_course_page

from course.constants import participation_permission as pperm
from course.utils import (  # noqa
        CoursePageContext)
from course.content import get_yaml_from_repo
from course.validation import ValidationError
from relate.utils import string_concat, as_local_time

# {{{ for mypy

if False:
    from typing import Text, Optional, Any, Iterable, Dict, List  # noqa
    from relate.utils import Repo_ish  # noqa

# }}}


class CreateForm(forms.Form):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    def __init__(self, form_fields):
        super(CreateForm, self).__init__()

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()

        self.form_fields = form_fields
        self.created_time = now()
        self.id = as_local_time(self.created_time).strftime("%Y%m%d_%H%M%S_%f")

        for field in form_fields:
            field_data = dict(required=True,
                              initial=field.value,
                              label=field.label)
            if field.type == "Choice":
                self.fields[field.id] = forms.ChoiceField(
                        choices=[(c, c) for c in field.choices],
                        **field_data)
            elif field.type == "Text":
                self.fields[field.id] = forms.CharField(
                        **field_data)
            elif field.type == "Integer":
                self.fields[field.id] = forms.IntegerField(
                        **field_data)

            if field.id == "template_in":
                self.template_in = field.value
            if field.id == "template_out":
                file_out = field.value.rsplit(".", 1)
                self.template_out = file_out[0] + "_" + self.id
                if len(file_out) > 1:
                    self.template_out += "." + file_out[-1]
            if field.id == "announce":
                self.announce = str(field.value).lower() == "true"

        self.helper.add_input(
                Submit("submit", _("Submit"), accesskey="p"),
                )
        self.helper.add_input(
                Submit("reset", _("Reset"), css_class="btn-default"),
                )
        self.helper.add_input(
                Submit("validate", _("Validate"), css_class="btn-default"),
                )

    def get_jinja_text(self):
        created_time = as_local_time(self.created_time).strftime("%Y-%m-%d @ %H:%M")

        text = "{{% with id=\"{id}\",\n".format(id=self.id)
        for field in self.form_fields:
            text += "        {field_name}=\"{field_value}\",\n".format(
                        field_name=field.id, field_value=field.value)
        text += "        created_time=\"{created_time}\" %}}".format(
                        created_time=created_time)
        text += textwrap.dedent("""
                {{% include "{template_in}" %}}
                {{% endwith %}}
                """).format(template_in=self.template_in)
        return text, self.template_out


def process_value(field):
    try:
        if field.type == "Integer":
            field.value = int(field.value)
        elif field.type == "Float":
            field.value = float(field.value)
    except ValueError:
        # This condition is impossible if the user uses the web UI
        raise ValidationError(
                _("form field '%(id)s' value '%(field_value)s' is"
                  " not a '%(field_type)s'.") % {'field_value': field.value,
                                                 'field_type': field.type,
                                                 'id': field.id})


def process_form_fields(form_fields, data):
    if "reset" in data:
        data = {}
    for field in form_fields:
        if not hasattr(field, "label"):
            field.label = field.id

        if field.id in data:
            field.value = data[field.id]

        if field.type == "Choice":
            choices = []
            for value in field.choices:
                if value.startswith("~DEFAULT~"):
                    v = value[9:].strip()
                    choices.append(v)
                    if not hasattr(field, "value"):
                        field.value = v
                else:
                    choices.append(value)
            field.choices = choices
        process_value(field)


def get_form(repo, form_name, commit_sha):
    contents = get_yaml_from_repo(repo, "forms/%s.yml" % form_name, commit_sha)
    contents.name = form_name
    return contents


def get_all_forms(repo, commit_sha):
    from course.content import list_dir_yaml_ids
    form_names = list_dir_yaml_ids(repo, commit_sha, "forms")
    forms = []
    for name in form_names:
        contents = get_form(repo, name, commit_sha)
        forms.append(contents)
    return forms


@course_view
def view_all_forms(pctx):
    if not pctx.has_permission(pperm.update_content):
        raise PermissionDenied()

    forms = get_all_forms(pctx.repo, pctx.course_commit_sha)

    return render_course_page(pctx, "course/forms.html", {
        "forms": forms,
    })


@course_view
def view_form(pctx, form_id):
    if not pctx.has_permission(pperm.update_content):
        raise PermissionDenied()

    form_info = get_form(pctx.repo, form_id, pctx.course_commit_sha)

    from course.enrollment import get_participation_role_identifiers
    roles = get_participation_role_identifiers(
            pctx.course, pctx.participation)

    if not any(role in form_info.access_roles for role in roles):
        raise PermissionDenied()

    def back_to_form(form, form_info):
        return render_course_page(pctx, "course/form.html", {
            "form": form,
            "description": form_info.description,
            "title": form_info.title,
        })

    request = pctx.request

    if request.method != "POST":
        process_form_fields(form_info.fields, {})
        form = CreateForm(form_info.fields)
        return back_to_form(form, form_info)

    process_form_fields(form_info.fields, request.POST)
    form = CreateForm(form_info.fields)

    if "clear" in request.POST:
        return back_to_form(form, form_info)

    page_source, file_out = form.get_jinja_text()

    # {{{ Check if file already exists

    course = pctx.course
    content_repo = pctx.repo

    from course.content import SubdirRepoWrapper
    if isinstance(content_repo, SubdirRepoWrapper):
        repo = content_repo.repo
    else:
        repo = content_repo

    repo_head = repo[b"HEAD"]
    repo_contents = [(entry.path, entry.sha, entry.mode) for entry in
                        repo.object_store.iter_tree_contents(repo_head.tree)]
    for entry in repo_contents:
        if entry[0].decode("utf-8") == file_out:
            messages.add_message(request, messages.ERROR,
                _("Target file: '%s'  already exists ") % file_out)
            return back_to_form(form, form_info)
    # }}}

    # {{{ Create a blob (file) and save in object store
    from dulwich.objects import Blob
    blob = Blob.from_string(page_source.encode("utf-8"))
    repo.object_store.add_object(blob)

    # }}}

    # {{{ Create a tree with the contents from HEAD and new file
    from dulwich.index import commit_tree
    repo_contents.append((file_out.encode("utf-8"), blob.id, 0o100644))
    tree_id = commit_tree(repo.object_store, repo_contents)

    user = pctx.participation.user
    committer = "{} <{}>".format(user.username, user.email).encode("utf-8")
    message = "Create page {} with form {}".format(file_out, form_id).encode("utf-8")

    # }}}

    # {{{ Create a commit with the tree and parent as HEAD.
    from dulwich.objects import Commit
    commit = Commit()
    commit.tree = tree_id
    commit.parents = [repo_head.id]
    commit.author = commit.committer = committer
    commit.commit_time = commit.author_time = int(now().timestamp())
    commit.commit_timezone = commit.author_timezone = 0
    commit.encoding = b"UTF-8"
    commit.message = message
    repo.object_store.add_object(commit)

    # }}}

    # {{{ validate

    from course.validation import validate_course_content, ValidationError
    try:
        warnings = validate_course_content(
                content_repo, course.course_file, course.events_file,
                commit.id, course=course)
    except ValidationError as e:
        messages.add_message(request, messages.ERROR,
                _("Course content did not validate successfully: '%s' "
                "Update not applied.") % str(e))
        return back_to_form(form, form_info)
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

    if "validate" in request.POST:
        return back_to_form(form, form_info)

    if pctx.participation.preview_git_commit_sha is not None:
        messages.add_message(request, messages.ERROR,
                _("Cannot apply update while previewing. "))
        return back_to_form(form, form_info)

    if repo[b"HEAD"] != repo_head:
        messages.add_message(request, messages.ERROR,
                _("Repo updated by somebody else. Try again."))
        return back_to_form(form, form_info)

    repo[b"HEAD"] = commit.id
    course.active_git_commit_sha = commit.id.decode()
    course.save()
    messages.add_message(request, messages.SUCCESS,
            _("Update applied. "))

    # {{{ Create InstantFlow

    if form_info.type == "flow" and hasattr(form, "announce") and form.announce:
        from course.models import InstantFlowRequest
        from datetime import timedelta
        ifr = InstantFlowRequest()
        ifr.course = course
        ifr.flow_id = file_out.rsplit("/", 1)[-1][:-4]
        ifr.start_time = form.created_time
        ifr.end_time = form.created_time + timedelta(minutes=20)
        ifr.save()
    # }}}

    return back_to_form(form, form_info)
