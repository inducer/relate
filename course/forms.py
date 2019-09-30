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

from typing import cast, Tuple
import os
import uuid
import textwrap
import yaml

import django.forms as forms
from django.utils.safestring import mark_safe
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.utils.translation import ugettext, ugettext_lazy as _
from django import http  # noqa

from crispy_forms.layout import Submit

from course.utils import course_view, render_course_page

from course.constants import participation_permission as pperm
from course.utils import (  # noqa
        CoursePageContext)
from course.content import FlowPageDesc, get_course_repo, get_repo_blob, get_yaml_from_repo, expand_yaml_macros
from relate.utils import dict_to_struct, Struct

# {{{ for mypy

if False:
    from typing import Text, Optional, Any, Iterable, Dict  # noqa

# }}}

# {{{ sandbox session key prefix

PAGE_SESSION_KEY_PREFIX = "cf_validated_sandbox_page"
ANSWER_DATA_SESSION_KEY_PREFIX = "cf_page_sandbox_answer_data"
PAGE_DATA_SESSION_KEY_PREFIX = "cf_page_sandbox_page_data"

# }}}


class CreateForm(forms.Form):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    def __init__(self, form_fields):
        super(CreateForm, self).__init__()

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()

        self.form_fields = form_fields
        self.id = str(uuid.uuid1()).replace("-", "")

        from django.utils.timezone import now
        self.created_time = now().strftime("%Y-%m-%d @ %H:%M")

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
        text = textwrap.dedent("""
                {{% with id="{id}",
                """).format(id=self.id)
        for field in self.form_fields:
            text += "        {field_name}=\"{field_value}\",\n".format(field_name=field.id, field_value=field.value)
        text += "        created_time=\"{created_time}\" %}}".format(created_time=self.created_time)
        text += textwrap.dedent("""
                {{% include "{template_in}" %}}
                {{% endwith %}}
                """).format(template_in=self.template_in)
        return text, self.template_out


def process_value(field):
    if field.type == "Integer":
        try:
            field.value = int(field.value)
        except ValueError:
            pass
    elif field.type == "Float":
        try:
            field.value = float(field.value)
        except ValueError:
            pass


def process_form_fields(form_fields, data):
    if "reset" in data:
        data = {}
    for field in form_fields:
        if not hasattr(field, "label"):
            field.label = field.id
        if not hasattr(field, "help"):
            field.help = field.label

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


def list_form_names(repo, commit_sha):
    # type: (Repo_ish, bytes) -> List[Text]
    form_names = []
    try:
        form_tree = get_repo_blob(repo, "forms", commit_sha)
    except ObjectDoesNotExist:
        # That's OK--no forms yet.
        pass
    else:
        for entry in form_tree.items():
            if entry.path.endswith(b".yml"):
                form_names.append(entry.path[:-4].decode("utf-8"))

    return sorted(form_names)


def get_form(repo, form_name, commit_sha):
    contents = get_yaml_from_repo(repo, "forms/%s.yml" % form_name, commit_sha)
    contents.name = form_name
    return contents


def get_all_forms(repo, commit_sha):
    form_names = list_form_names(repo, commit_sha)
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

    def back_to_form(form, form_info, page_errors=None, page_warnings=None):
        return render_course_page(pctx, "course/form.html", {
            "form": form,
            "description": form_info.description,
            "title": form_info.title,
            "page_errors": page_errors,
            "page_warnings": page_warnings,
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

    new_page_source, file_out = form.get_jinja_text()
    page_warnings = None
    page_errors = None
    try:
        new_page_source = expand_yaml_macros(
                pctx.repo, pctx.course_commit_sha, new_page_source)

        yaml_data = yaml.safe_load(new_page_source)  # type: ignore
        page_desc = dict_to_struct(yaml_data)

        if not isinstance(page_desc, Struct):
            raise ValidationError("Provided page source code is not "
                    "a dictionary. Do you need to remove a leading "
                    "list marker ('-') or some stray indentation?")

        from course.validation import validate_flow_desc, ValidationContext
        vctx = ValidationContext(
                repo=pctx.repo,
                commit_sha=pctx.course_commit_sha)

        validate_flow_desc(vctx, "form", page_desc)

        page_warnings = vctx.warnings

    except Exception:
        import sys
        tp, e, _ = sys.exc_info()

        page_errors = (
                ugettext("Page failed to load/validate")
                + ": "
                + "%(err_type)s: %(err_str)s" % {
                    "err_type": tp.__name__, "err_str": e})  # type: ignore

        return back_to_form(form, form_info, page_errors, page_warnings)
    else:
        # Yay, it did validate.
        pass

    if "validate" in request.POST:
        return back_to_form(form, form_info, page_errors, page_warnings)

    return render_course_page(pctx, "course/form.html", {
        "form": form,
        "description": form_info.description,
        "title": form_info.title,
    })

