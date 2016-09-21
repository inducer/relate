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

from course.constants import participation_permission as pperm


# {{{ sandbox form

class SandboxForm(forms.Form):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

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

        # 'strip' attribute was added to CharField in Django 1.9
        # with 'True' as default value.
        if hasattr(self.fields["content"], "strip"):
            self.fields["content"].strip = False

        self.helper.add_input(
                Submit("preview", _("Preview"), accesskey="p"),
                )
        self.helper.add_input(
                Submit("clear", _("Clear"), css_class="btn-default"),
                )

# }}}


# {{{ markup sandbox

@course_view
def view_markup_sandbox(pctx):
    if not pctx.has_permission(pperm.use_markup_sandbox):
        raise PermissionDenied()

    request = pctx.request
    preview_text = ""

    def make_form(data=None):
        help_text = (ugettext("Enter <a href=\"http://documen.tician.de/"
                "relate/content.html#relate-markup\">"
                "RELATE markup</a>."))
        return SandboxForm(
                None, "markdown", request.user.editor_mode,
                help_text,
                data)

    if request.method == "POST" and "preview" in request.POST:
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


# {{{ page sandbox data retriever

def get_sandbox_data_for_page(pctx, page_desc, key):
    stored_data_tuple = pctx.request.session.get(key)

    # Session storage uses JSON and may turn tuples into lists.
    if (isinstance(stored_data_tuple, (list, tuple))
            and len(stored_data_tuple) == 3):
        stored_data_page_type, stored_data_page_id, \
            stored_data = stored_data_tuple

        if (
                stored_data_page_type == page_desc.type
                and
                stored_data_page_id == page_desc.id):
            return stored_data

    return None

# }}}


# {{{ page sandbox form

class PageSandboxForm(SandboxForm):
    def __init__(self, initial_text,
            language_mode, interaction_mode, help_text, *args, **kwargs):
        super(PageSandboxForm, self).__init__(
                initial_text, language_mode, interaction_mode, help_text,
                *args, **kwargs)

        self.helper.add_input(
                Submit("clear_response", _("Clear Response Data"),
                    css_class="btn-default"),
                )

# }}}


# {{{ page sandbox

@course_view
def view_page_sandbox(pctx):
    if not pctx.has_permission(pperm.use_page_sandbox):
        raise PermissionDenied()

    from course.validation import ValidationError
    from relate.utils import dict_to_struct, Struct
    import yaml

    PAGE_SESSION_KEY = (  # noqa
            "cf_validated_sandbox_page:" + pctx.course.identifier)
    ANSWER_DATA_SESSION_KEY = (  # noqa
        "cf_page_sandbox_answer_data:" + pctx.course.identifier)
    PAGE_DATA_SESSION_KEY = (  # noqa
        "cf_page_sandbox_page_data:" + pctx.course.identifier)

    request = pctx.request
    page_source = pctx.request.session.get(PAGE_SESSION_KEY)

    page_errors = None
    page_warnings = None

    is_clear_post = (request.method == "POST" and "clear" in request.POST)
    is_clear_response_post = (request.method == "POST"
            and "clear_response" in request.POST)
    is_preview_post = (request.method == "POST" and "preview" in request.POST)

    def make_form(data=None):
        return PageSandboxForm(
                page_source, "yaml", request.user.editor_mode,
                ugettext("Enter YAML markup for a flow page."),
                data)

    if is_preview_post:
        edit_form = make_form(pctx.request.POST)
        new_page_source = None

        if edit_form.is_valid():
            try:
                from pytools.py_codegen import remove_common_indentation
                new_page_source = remove_common_indentation(
                        edit_form.cleaned_data["content"],
                        require_leading_newline=False)
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

    elif is_clear_post:
        page_source = None
        pctx.request.session[PAGE_DATA_SESSION_KEY] = None
        pctx.request.session[ANSWER_DATA_SESSION_KEY] = None
        del pctx.request.session[PAGE_DATA_SESSION_KEY]
        del pctx.request.session[ANSWER_DATA_SESSION_KEY]
        edit_form = make_form()

    elif is_clear_response_post:
        page_source = None
        pctx.request.session[PAGE_DATA_SESSION_KEY] = None
        pctx.request.session[ANSWER_DATA_SESSION_KEY] = None
        del pctx.request.session[PAGE_DATA_SESSION_KEY]
        del pctx.request.session[ANSWER_DATA_SESSION_KEY]
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
        # Try to recover page_data, answer_data
        page_data = get_sandbox_data_for_page(
                pctx, page_desc, PAGE_DATA_SESSION_KEY)

        answer_data = get_sandbox_data_for_page(
                pctx, page_desc, ANSWER_DATA_SESSION_KEY)

        from course.models import FlowSession
        from course.page import PageContext
        page_context = PageContext(
                course=pctx.course,
                repo=pctx.repo,
                commit_sha=pctx.course_commit_sha,

                # This helps code pages retrieve the editor pref.
                flow_session=FlowSession(
                    course=pctx.course,
                    participation=pctx.participation),

                in_sandbox=True)

        if page_data is None:
            page_data = page.initialize_page_data(page_context)
            pctx.request.session[PAGE_DATA_SESSION_KEY] = (
                    page_desc.type, page_desc.id, page_data)

        title = page.title(page_context, page_data)
        body = page.body(page_context, page_data)

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
                try:
                    page_form = page.make_form(page_context, page_data,
                            answer_data, page_behavior)

                except:
                    import sys
                    tp, e, _ = sys.exc_info()

                    page_errors = (
                            ugettext("Page failed to load/validate "
                                "(change page ID to clear faults)")
                            + ": "
                            + "%(err_type)s: %(err_str)s" % {
                                "err_type": tp.__name__, "err_str": e})
                    have_valid_page = False

                    page_form = None

            if page_form is not None:
                page_form.helper.add_input(
                        Submit("submit",
                            ugettext("Submit answer"),
                            accesskey="g"))
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
