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

from crispy_forms.layout import Submit

from course.utils import course_view, render_course_page


CF_SANDBOX_VIM_MODE = "CF_SANDBOX_VIM_MODE"


# {{{ sandbox form

class SandboxForm(forms.Form):
    def __init__(self, initial_text,
            editor_mode, vim_mode, help_text, *args, **kwargs):
        super(SandboxForm, self).__init__(*args, **kwargs)

        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"

        from codemirror import CodeMirrorTextarea, CodeMirrorJavascript

        self.fields["content"] = forms.CharField(
                required=False,
                initial=initial_text,
                widget=CodeMirrorTextarea(
                    mode=editor_mode,
                    theme="default",
                    addon_css=(
                        "dialog/dialog",
                        "display/fullscreen",
                        ),
                    addon_js=(
                        "search/searchcursor",
                        "dialog/dialog",
                        "search/search",
                        "edit/matchbrackets",
                        "display/fullscreen",
                        "selection/active-line",
                        "edit/trailingspace",
                        ),
                    config={
                        "fixedGutter": True,
                        "autofocus": True,
                        "matchBrackets": True,
                        "styleActiveLine": True,
                        "showTrailingSpace": True,
                        "indentUnit": 2,
                        "vimMode": vim_mode,
                        "extraKeys": CodeMirrorJavascript("""
                            {
                              "Tab": function(cm)
                              {
                                var spaces = \
                                    Array(cm.getOption("indentUnit") + 1).join(" ");
                                cm.replaceSelection(spaces);
                              },
                              "F9": function(cm) {
                                  cm.setOption("fullScreen",
                                    !cm.getOption("fullScreen"));
                              }
                            }
                        """)
                    }),
                help_text=mark_safe(
                    help_text + " Press Alt/Cmd+(Shift+)P to preview. "
                    "Press F9 to toggle full screen mode."))

        self.fields["vim_mode"] = forms.BooleanField(
                required=False, initial=vim_mode)

        self.helper.add_input(
                Submit(
                    "preview", "Preview",
                    accesskey="p"))

# }}}


# {{{ markup sandbox

@course_view
def view_markup_sandbox(pctx):
    request = pctx.request
    preview_text = ""

    def make_form(data=None):
        help_text = ("Enter <a href=\"http://documen.tician.de/"
                "relate/content.html#courseflow-markup\">"
                "RELATE markup</a>.")
        return SandboxForm(
                None, "markdown", vim_mode,
                help_text,
                data)

    vim_mode = pctx.request.session.get(CF_SANDBOX_VIM_MODE, False)

    if request.method == "POST":
        form = make_form(request.POST)

        if form.is_valid():
            pctx.request.session[CF_SANDBOX_VIM_MODE] = \
                    vim_mode = form.cleaned_data["vim_mode"]

            from course.content import markup_to_html
            try:
                preview_text = markup_to_html(
                        pctx.course, pctx.repo, pctx.course_commit_sha,
                        form.cleaned_data["content"])
            except:
                import sys
                tp, e, _ = sys.exc_info()

                messages.add_message(pctx.request, messages.ERROR,
                        "Markup failed to render: "
                        "%s: %s" % (tp.__name__, e))

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
    from relate.utils import dict_to_struct
    import yaml

    PAGE_SESSION_KEY = "cf_validated_sandbox_page:" + pctx.course.identifier
    ANSWER_DATA_SESSION_KEY = "cf_page_sandbox_answer_data:" + pctx.course.identifier

    request = pctx.request
    page_source = pctx.request.session.get(PAGE_SESSION_KEY)

    page_errors = None

    is_preview_post = (request.method == "POST" and "preview" in request.POST)

    def make_form(data=None):
        return SandboxForm(
                page_source, "yaml", vim_mode,
                "Enter YAML markup for a flow page.",
                data)

    vim_mode = pctx.request.session.get(CF_SANDBOX_VIM_MODE, False)

    if is_preview_post:
        edit_form = make_form(pctx.request.POST)

        if edit_form.is_valid():
            pctx.request.session[CF_SANDBOX_VIM_MODE] = \
                    vim_mode = edit_form.cleaned_data["vim_mode"]

            try:
                new_page_source = edit_form.cleaned_data["content"]
                page_desc = dict_to_struct(yaml.load(new_page_source))

                from course.validation import validate_flow_page, ValidationContext
                vctx = ValidationContext(
                        repo=pctx.repo,
                        commit_sha=pctx.course_commit_sha)

                validate_flow_page(vctx, "sandbox", page_desc)

            except:
                import sys
                tp, e, _ = sys.exc_info()

                page_errors = (
                        "Page failed to load/validate: "
                        "%s: %s" % (tp.__name__, e))

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
        page = instantiate_flow_page("sandbox", pctx.repo, page_desc,
                pctx.course_commit_sha)

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
                and len(stored_answer_data_tuple) == 2):
            stored_answer_data_page_id, stored_answer_data = \
                    stored_answer_data_tuple

            if stored_answer_data_page_id == page_desc.id:
                answer_data = stored_answer_data

        # }}}

        feedback = None
        page_form_html = None

        if page.expects_answer():
            if request.method == "POST" and not is_preview_post:
                page_form = page.post_form(page_context, page_data,
                        request.POST, request.FILES)

                if page_form.is_valid():

                    answer_data = page.answer_data(page_context, page_data,
                            page_form, request.FILES)

                    feedback = page.grade(page_context, page_data, answer_data,
                            grade_data=None)

                    pctx.request.session[ANSWER_DATA_SESSION_KEY] = (
                            page_desc.id, answer_data)

            else:
                page_form = page.make_form(page_context, page_data,
                        answer_data, answer_is_final=False)

            if page_form is not None:
                page_form.helper.add_input(
                        Submit("submit", "Submit answer", accesskey="g",
                            css_class="col-lg-offset-2"))
                page_form_html = page.form_to_html(
                        pctx.request, page_context, page_form, answer_data)

        correct_answer = page.correct_answer(
                page_context, page_data, answer_data,
                grade_data=None)

        return render_course_page(pctx, "course/sandbox-page.html", {
            "edit_form": edit_form,
            "page_errors": page_errors,
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
        })

# }}}


# vim: foldmethod=marker
