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

from typing import cast, Tuple
import os

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
from course.content import FlowPageDesc, get_course_repo, get_repo_blob, get_raw_yaml_from_repo

# {{{ for mypy

if False:
    from typing import Text, Optional, Any, Iterable, Dict  # noqa

# }}}

# {{{ sandbox session key prefix

PAGE_SESSION_KEY_PREFIX = "cf_validated_sandbox_page"
ANSWER_DATA_SESSION_KEY_PREFIX = "cf_page_sandbox_answer_data"
PAGE_DATA_SESSION_KEY_PREFIX = "cf_page_sandbox_page_data"

# }}}


class CreateFlowForm(forms.Form):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    def __init__(self, initial_text,
            language_mode, interaction_mode, help_text, *args, **kwargs):
        # type: (Text, Text, Text, Text, *Any, **Any) -> None
        super(SandboxForm, self).__init__(*args, **kwargs)

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()

        from course.utils import get_codemirror_widget
        cm_widget, cm_help_text = get_codemirror_widget(
                language_mode=language_mode,
                interaction_mode=interaction_mode)

        self.fields["content"] = forms.CharField(
                required=False,
                initial=initial_text,
                widget=cm_widget,
                help_text=mark_safe(
                    help_text
                    + " "
                    + ugettext("Press Alt/Cmd+(Shift+)P to preview.")
                    + " "
                    + cm_help_text),
                label=_("Content"))

        # 'strip' attribute was added to CharField in Django 1.9
        # with 'True' as default value.
        self.fields["content"].strip = False

        self.helper.add_input(
                Submit("preview", _("Preview"), accesskey="p"),
                )
        self.helper.add_input(
                Submit("clear", _("Clear"), css_class="btn-default"),
                )


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


def get_all_forms(repo, commit_sha):
    form_names = list_form_names(repo, commit_sha)
    forms = []
    for name in form_names:
        contents = get_raw_yaml_from_repo(repo, "forms/%s.yml" % name, commit_sha)
        contents["name"] = name
        forms.append(contents)

    return forms


def validate_form(form):
    pass


@course_view
def view_all_forms(pctx):
    if not pctx.has_permission(pperm.use_markup_sandbox):
        raise PermissionDenied()

    forms = get_all_forms(pctx.repo, pctx.course_commit_sha)

    return render_course_page(pctx, "course/forms.html", {
        "forms": forms,
    })


@course_view
def view_form(pctx, form_id):
    if not pctx.has_permission(pperm.use_markup_sandbox):
        raise PermissionDenied()

    def make_form(data=None):
        help_text = (ugettext("Enter <a href=\"http://documen.tician.de/"
                "relate/content.html#relate-markup\">"
                "RELATE markup</a>."))
        return CreateFlowForm(
                None, "markdown", request.user.editor_mode,
                help_text,
                data)

    request = pctx.request

    if request.method == "POST":
        form = make_form(request.POST)
    else:
        form = make_form()

    return render_course_page(pctx, "course/sandbox-markup.html", {
        "form": form,
        "preview_text": preview_text,
    })


