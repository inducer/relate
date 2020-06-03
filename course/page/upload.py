# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = """
Copyright (C) 2014 Andreas Kloeckner
Copyright (c) 2020 Dong Zhuang
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


import django.forms as forms
from django.utils.translation import ugettext as _, ugettext_lazy

from course.page.base import (
        PageBaseWithTitle, PageBaseWithValue, PageBaseWithHumanTextFeedback,
        PageBaseWithCorrectAnswer,
        markup_to_html)
from course.validation import ValidationError

from relate.utils import StyledForm, string_concat

from crispy_forms.layout import Layout, Field

# {{{ mypy

if False:
    from typing import Optional, Text  # noqa

# }}}


# {{{ upload question

class FileUploadFormBase(StyledForm):
    show_save_button = False
    uploaded_file = forms.FileField(required=True,
            label=ugettext_lazy('Uploaded file'))

    def __init__(self, maximum_megabytes, mime_types, *args, **kwargs):
        super(FileUploadFormBase, self).__init__(*args, **kwargs)

        self.max_file_size = maximum_megabytes * 1024**2
        self.mime_types = mime_types

        field_kwargs = {}
        accepting_mime_types = self.get_accepting_types(mime_types)
        if accepting_mime_types:
            field_kwargs["accept"] = ",".join(accepting_mime_types)

        self.helper.layout = Layout(
                Field("uploaded_file", **field_kwargs))

    @classmethod
    def get_accepting_types(cls, mime_types):
        return []

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        from django.template.defaultfilters import filesizeformat

        if uploaded_file.size > self.max_file_size:
            raise forms.ValidationError(
                    _("Please keep file size under %(allowedsize)s. "
                    "Current filesize is %(uploadedsize)s.")
                    % {'allowedsize': filesizeformat(self.max_file_size),
                        'uploadedsize': filesizeformat(uploaded_file.size)})

        return uploaded_file


class FileUploadForm(FileUploadFormBase):
    @classmethod
    def get_accepting_types(cls, mime_types):
        # 'accept=' doesn't work right for at least application/octet-stream.
        # We'll start with a whitelist.
        allow_accept = False
        if mime_types == ["application/pdf"]:
            allow_accept = True

        if allow_accept:
            return mime_types

    def clean_uploaded_file(self):
        uploaded_file = super(FileUploadForm, self).clean_uploaded_file()

        if self.mime_types is not None and self.mime_types == ["application/pdf"]:
            if uploaded_file.read()[:4] != b"%PDF":
                raise forms.ValidationError(_("Uploaded file is not a PDF."))

        return uploaded_file


class FileUploadQuestionBase(PageBaseWithTitle, PageBaseWithValue,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):

    @property
    def ALLOWED_MIME_TYPES(self):  # noqa
        raise NotImplementedError

    @property
    def file_extension(self):
        return None

    @property
    def form_class(self):
        raise NotImplementedError

    form_template = "course/file-upload-form.html"
    default_download_name = None  # type: Optional[Text]

    def __init__(self, vctx, location, page_desc):
        super(FileUploadQuestionBase, self).__init__(vctx, location, page_desc)

        if page_desc.maximum_megabytes <= 0:
            raise ValidationError(
                string_concat(
                    location, ": ",
                    _("'maximum_megabytes' expects a positive value, "
                      "got %(value)s instead")
                    % {'value': str(page_desc.maximum_megabytes)}))

        if vctx is not None:
            if not hasattr(page_desc, "value"):
                vctx.add_warning(location, _("upload question does not have "
                        "assigned point value"))

        self.mime_types = self.ALLOWED_MIME_TYPES
        if hasattr(self.page_desc, "mime_types"):
            self.mime_types = self.page_desc.mime_types

    def required_attrs(self):
        return super(FileUploadQuestionBase, self).required_attrs() + (
                ("prompt", "markup"),
                ("maximum_megabytes", (int, float)),
                )

    def allowed_attrs(self):
        return super(FileUploadQuestionBase, self).allowed_attrs() + (
                ("correct_answer", "markup"),
                )

    def human_feedback_point_value(self, page_context, page_data):
        return self.max_points(page_data)

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    @staticmethod
    def _get_uploaded_file_buf(files_data):
        files_data["uploaded_file"].seek(0)
        return files_data["uploaded_file"].read()

    def files_data_to_answer_data(self, files_data):
        buf = self._get_uploaded_file_buf(files_data)

        if len(self.mime_types) == 1:
            mime_type, = self.mime_types
        else:
            mime_type = files_data["uploaded_file"].content_type
        from base64 import b64encode
        return {
                "base64_data": b64encode(buf).decode(),
                "mime_type": mime_type,
                }

    def make_form(self, page_context, page_data,
            answer_data, page_behavior):
        form = self.form_class(
                self.page_desc.maximum_megabytes, self.mime_types)
        return form

    def process_form_post(self, page_context, page_data, post_data, files_data,
            page_behavior):
        form = self.form_class(
                self.page_desc.maximum_megabytes, self.mime_types,
                post_data, files_data)
        return form

    def get_form_to_html_context(self, request, page_context, form, answer_data):
        ctx = {"form": form}
        if answer_data is not None:
            ctx["mime_type"] = answer_data["mime_type"]
            ctx["data_url"] = "data:%s;base64,%s" % (
                answer_data["mime_type"],
                answer_data["base64_data"],
                )
            ctx["default_download_name"] = self.default_download_name
        return ctx

    def form_to_html(self, request, page_context, form, answer_data):
        ctx = self.get_form_to_html_context(request, page_context, form, answer_data)
        from django.template.loader import render_to_string
        return render_to_string(self.form_template, ctx, request)

    def answer_data(self, page_context, page_data, form, files_data):
        return self.files_data_to_answer_data(files_data)

    def get_download_file_extension(self):
        if self.file_extension is not None:
            return self.file_extension

        ext = None
        if len(self.mime_types) == 1:
            mtype, = self.mime_types
            from mimetypes import guess_extension
            ext = guess_extension(mtype)

        if ext is None:
            ext = ".dat"
        return ext

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        ext = self.get_download_file_extension()

        from base64 import b64decode
        return ext, b64decode(answer_data["base64_data"])


class FileUploadQuestion(FileUploadQuestionBase):
    """
    A page allowing the submission of a file upload that will be
    graded with text feedback by a human grader.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``Page``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: value

        |value-page-attr|

    .. attribute:: prompt

        Required.
        The prompt for this question, in :ref:`markup`.

    .. attribute:: mime_types

        Required.
        A list of `MIME types <https://en.wikipedia.org/wiki/Internet_media_type>`_
        that the question will accept.

        For now, the following are allowed:

        * ``application/pdf`` (will check for a PDF header)
        * ``text/plain`` (no check performed)
        * ``application/octet-stream`` (no check performed)

    .. attribute:: maximum_megabytes

        Required.
        The largest file size
        (in `Mebibyte <https://en.wikipedia.org/wiki/Mebibyte>`)
        that the page will accept.

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.

    .. attribute:: rubric

        Required.
        The grading guideline for this question, in :ref:`markup`.
    """

    ALLOWED_MIME_TYPES = [
            "application/pdf",
            "text/plain",
            "application/octet-stream",
            ]

    form_class = FileUploadForm

    def __init__(self, vctx, location, page_desc):
        super(FileUploadQuestion, self).__init__(vctx, location, page_desc)

        if not (set(page_desc.mime_types) <= set(self.ALLOWED_MIME_TYPES)):
            raise ValidationError(
                string_concat(
                    location, ": ",
                    _("unrecognized mime types"),
                    " '%(presenttype)s'")
                % {
                    'presenttype': ", ".join(
                        set(page_desc.mime_types)
                        - set(self.ALLOWED_MIME_TYPES))})

    def required_attrs(self):
        return super(FileUploadQuestion, self).required_attrs() + (
                ("mime_types", list),)

# }}}

# {{{ Jupyter notebook upload question


class JupyterNotebookUploadForm(FileUploadFormBase):
    def clean_uploaded_file(self):
        uploaded_file = super(
            JupyterNotebookUploadForm, self).clean_uploaded_file()
        import sys
        try:
            if sys.version_info < (3, 6):
                # nbformat.reader.read is assuming Python 3.6+
                import json
                json.loads(uploaded_file.read().decode('utf-8'))
            else:
                from nbformat.reader import read
                read(uploaded_file)
        except Exception:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError(
                "%(err_type)s: %(err_str)s"
                % {"err_type": tp.__name__, "err_str": str(e)})
        return uploaded_file


class JupyterNotebookUploadQuestion(FileUploadQuestionBase):
    """
    A page allowing the submission of a JupyterNotebook file that will be
    graded with text feedback by a human grader.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``Page``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: value

        |value-page-attr|

    .. attribute:: prompt

        Required.
        The prompt for this question, in :ref:`markup`.

    .. attribute:: maximum_megabytes

        Required.
        The largest file size
        (in `Mebibyte <https://en.wikipedia.org/wiki/Mebibyte>`)
        that the page will accept.

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.

    .. attribute:: rubric

        Required.
        The grading guideline for this question, in :ref:`markup`.
    """

    ALLOWED_MIME_TYPES = [
        "application/x-ipynb+json"
    ]
    file_extension = ".ipynb"
    form_template = "course/file-upload-form-with-ipynb-preview.html"
    default_download_name = "my_notebook.ipynb"
    form_class = JupyterNotebookUploadForm

    def files_data_to_answer_data(self, files_data):
        buf = self._get_uploaded_file_buf(files_data)

        from course.utils import render_notebook_from_source
        from base64 import b64encode
        return {
                "base64_data": b64encode(buf).decode(),
                "mime_type": self.mime_types[0],
                "preview_base64_data": b64encode(
                    render_notebook_from_source(buf.decode()).encode()).decode()
                }

    def get_form_to_html_context(self, request, page_context, form, answer_data):
        ctx = super(JupyterNotebookUploadQuestion, self).get_form_to_html_context(
            request, page_context, form, answer_data)
        if answer_data is not None:
            ctx["preview_data_url"] = "data:text/html;base64,%s" % (
                answer_data["preview_base64_data"],
                )
            ctx["preview_base64_data"] = answer_data["preview_base64_data"]

        return ctx

# }}}

# vim: foldmethod=marker
