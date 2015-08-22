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

import django.forms as forms
from django.utils.safestring import mark_safe
from django.contrib import messages  # noqa
from django.core.exceptions import PermissionDenied
from django.utils.translation import ugettext, ugettext_lazy as _

from crispy_forms.layout import Submit

from course.utils import course_view, render_course_page

from course.constants import participation_role


# {{{ sandbox form

class SandboxForm(forms.Form):
    def __init__(self, initial_text,
            language_mode, interaction_mode, help_text, *args, **kwargs):
        super(SandboxForm, self).__init__(*args, **kwargs)

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"

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

        self.helper.add_input(
                Submit(
                    "preview", _("Preview"),
                    accesskey="p"))

# }}}


# {{{ markup sandbox

@course_view
def view_markup_sandbox(pctx):
    request = pctx.request
    preview_text = ""

    from course.models import get_user_status
    ustatus = get_user_status(request.user)

    def make_form(data=None):
        help_text = (ugettext("Enter <a href=\"http://documen.tician.de/"
                "relate/content.html#relate-markup\">"
                "RELATE markup</a>."))
        return SandboxForm(
                None, "markdown", ustatus.editor_mode,
                help_text,
                data)

    if request.method == "POST":
        form = make_form(request.POST)

        if form.is_valid():
            from course.content import markup_to_html
            try:
                preview_text = markup_to_html(
                        pctx.course, pctx.repo, pctx.course_commit_sha,
                        form.cleaned_data["content"])
            except:
                import sys
                tp, e, _ = sys.exc_info()

                messages.add_message(pctx.request, messages.ERROR,
                        ugettext("Markup failed to render")
                        + ": "
                        + "%(err_type)s: %(err_str)s" % {
                            "err_type": tp.__name__, "err_str": e})

        form = make_form(request.POST)

    else:
        form = make_form()

    return render_course_page(pctx, "course/sandbox-markup.html", {
        "form": form,
        "preview_text": preview_text,
    })

# }}}


# {{{ page sandbox

@course_view
def view_page_sandbox(pctx):
    if pctx.role not in [
            participation_role.instructor,
            participation_role.teaching_assistant]:
        raise PermissionDenied(
                ugettext("must be instructor or TA to access sandbox"))

    from course.validation import ValidationError
    from relate.utils import dict_to_struct, Struct
    import yaml

    PAGE_SESSION_KEY = (  # noqa
            "cf_validated_sandbox_page:" + pctx.course.identifier)
    ANSWER_DATA_SESSION_KEY = (  # noqa
        "cf_page_sandbox_answer_data:" + pctx.course.identifier)

    request = pctx.request
    page_source = pctx.request.session.get(PAGE_SESSION_KEY)

    page_errors = None
    page_warnings = None

    is_preview_post = (request.method == "POST" and "preview" in request.POST)

    from course.models import get_user_status
    ustatus = get_user_status(request.user)

    def make_form(data=None):
        return SandboxForm(
                page_source, "yaml", ustatus.editor_mode,
                ugettext("Enter YAML markup for a flow page."),
                data)

    if is_preview_post:
        edit_form = make_form(pctx.request.POST)

        if edit_form.is_valid():
            try:
                new_page_source = edit_form.cleaned_data["content"]
                page_desc = dict_to_struct(yaml.load(new_page_source))

                if not isinstance(page_desc, Struct):
                    raise ValidationError("Provided page source code is not "
                            "a dictionary. Do you need to remove a leading "
                            "list marker ('-') or some stray indentation?")

                from course.validation import validate_flow_page, ValidationContext
                vctx = ValidationContext(
                        repo=pctx.repo,
                        commit_sha=pctx.course_commit_sha)

                validate_flow_page(vctx, "sandbox", page_desc)

                page_warnings = vctx.warnings

            except:
                import sys
                tp, e, _ = sys.exc_info()

                page_errors = (
                        ugettext("Page failed to load/validate")
                        + ": "
                        + "%(err_type)s: %(err_str)s" % {
                            "err_type": tp.__name__, "err_str": e})

            else:
                # Yay, it did validate.
                request.session[PAGE_SESSION_KEY] = page_source = new_page_source

            del new_page_source

        edit_form = make_form(pctx.request.POST)

    else:
        edit_form = make_form()

    have_valid_page = page_source is not None
    if have_valid_page:
        page_desc = dict_to_struct(yaml.load(page_source))

        from course.content import instantiate_flow_page
        try:
            page = instantiate_flow_page("sandbox", pctx.repo, page_desc,
                    pctx.course_commit_sha)
        except:
            import sys
            tp, e, _ = sys.exc_info()

            page_errors = (
                    ugettext("Page failed to load/validate")
                    + ": "
                    + "%(err_type)s: %(err_str)s" % {
                        "err_type": tp.__name__, "err_str": e})
            have_valid_page = False

    if have_valid_page:
        page_data = page.make_page_data()

        from course.page import PageContext
        page_context = PageContext(
                course=pctx.course,
                repo=pctx.repo,
                commit_sha=pctx.course_commit_sha,
                flow_session=None)

        title = page.title(page_context, page_data)
        body = page.body(page_context, page_data)

        # {{{ try to recover answer_data

        answer_data = None

        stored_answer_data_tuple = \
                pctx.request.session.get(ANSWER_DATA_SESSION_KEY)

        # Session storage uses JSON and may turn tuples into lists.
        if (isinstance(stored_answer_data_tuple, (list, tuple))
                and len(stored_answer_data_tuple) == 3):
            stored_answer_data_page_type, stored_answer_data_page_id, stored_answer_data = \
                    stored_answer_data_tuple

            if (
                    stored_answer_data_page_type == page_desc.type
                    and
                    stored_answer_data_page_id == page_desc.id):
                answer_data = stored_answer_data

        # }}}

        feedback = None
        page_form_html = None

        if page.expects_answer():
            from course.page.base import PageBehavior
            page_behavior = PageBehavior(
                    show_correctness=True,
                    show_answer=True,
                    may_change_answer=True)

            if request.method == "POST" and not is_preview_post:
                page_form = page.process_form_post(page_context, page_data,
                        request.POST, request.FILES,
                        page_behavior)

                if page_form.is_valid():

                    answer_data = page.answer_data(page_context, page_data,
                            page_form, request.FILES)

                    feedback = page.grade(page_context, page_data, answer_data,
                            grade_data=None)

                    pctx.request.session[ANSWER_DATA_SESSION_KEY] = (
                            page_desc.type, page_desc.id, answer_data)

            else:
                page_form = page.make_form(page_context, page_data,
                        answer_data, page_behavior)

            if page_form is not None:
                page_form.helper.add_input(
                        Submit("submit",
                            ugettext("Submit answer"),
                            accesskey="g",
                            css_class="col-lg-offset-2"))
                page_form_html = page.form_to_html(
                        pctx.request, page_context, page_form, answer_data)

        correct_answer = page.correct_answer(
                page_context, page_data, answer_data,
                grade_data=None)

        return render_course_page(pctx, "course/sandbox-page.html", {
            "edit_form": edit_form,
            "page_errors": page_errors,
            "page_warnings": page_warnings,
            "form": edit_form,  # to placate form.media
            "have_valid_page": True,
            "title": title,
            "body": body,
            "page_form_html": page_form_html,
            "feedback": feedback,
            "correct_answer": correct_answer,
        })

    else:

        return render_course_page(pctx, "course/sandbox-page.html", {
            "edit_form": edit_form,
            "form": edit_form,  # to placate form.media
            "have_valid_page": False,
            "page_errors": page_errors,
            "page_warnings": page_warnings,
        })

# }}}


# vim: foldmethod=marker
