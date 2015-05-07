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
from django.utils.translation import ugettext as _

from course.page.base import (
        PageBaseWithTitle, PageBaseWithValue, PageBaseWithHumanTextFeedback,
        PageBaseWithCorrectAnswer,
        markup_to_html)
from course.validation import ValidationError

from relate.utils import StyledForm


# {{{ upload question

class FileUploadForm(StyledForm):
    uploaded_file = forms.FileField(required=True,label=_('Uploaded file'))

    def __init__(self, maximum_megabytes, mime_types, *args, **kwargs):
        super(FileUploadForm, self).__init__(*args, **kwargs)

        self.max_file_size = maximum_megabytes * 1024**2
        self.mime_types = mime_types

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        from django.template.defaultfilters import filesizeformat

        if uploaded_file._size > self.max_file_size:
            raise forms.ValidationError(
                    _("Please keep file size under %(allowedsize)s. "
                    "Current filesize is %(uploadedsize)s.")
                    % {'allowedsize':filesizeformat(self.max_file_size),
                        'uploadedsize':filesizeformat(uploaded_file._size)})

        if self.mime_types is not None and self.mime_types == ["application/pdf"]:
            if uploaded_file.read()[:4] != "%PDF":
                raise forms.ValidationError(_("Uploaded file is not a PDF."))

        return uploaded_file


class FileUploadQuestion(PageBaseWithTitle, PageBaseWithValue,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):
    """
    A page allowing the submission of a file upload that will be
    graded with text feedback by a human grader.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``Page``

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
        Only ``application/pdf`` is allowed for the moment.

        The value ``"application/octet-stream"`` will allow any file at all
        to be uploaded.

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
            "application/octet-stream",
            ]

    def __init__(self, vctx, location, page_desc):
        super(FileUploadQuestion, self).__init__(vctx, location, page_desc)

        if not (set(page_desc.mime_types) <= set(self.ALLOWED_MIME_TYPES)):
            raise ValidationError(_("%(location)s: unrecognized mime types '%(presenttype)s'")
                    % {'location':location, 'presenttype':", ".join(
                        set(page_desc.mime_types) - set(self.ALLOWED_MIME_TYPES))})

        if not hasattr(page_desc, "value"):
            vctx.add_warning(location, _("upload question does not have "
                    "assigned point value"))

    def required_attrs(self):
        return super(FileUploadQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("mime_types", list),
                ("maximum_megabytes", (int, float)),
                )

    def allowed_attrs(self):
        return super(FileUploadQuestion, self).allowed_attrs() + (
                ("correct_answer", "markup"),
                )

    def human_feedback_point_value(self, page_context, page_data):
        return self.max_points(page_data)

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def files_data_to_answer_data(self, files_data):
        files_data["uploaded_file"].seek(0)
        buf = files_data["uploaded_file"].read()

        if len(self.page_desc.mime_types) == 1:
            mime_type, = self.page_desc.mime_types
        else:
            mime_type = files_data["uploaded_file"].content_type
        from base64 import b64encode
        return {
                "base64_data": b64encode(buf),
                "mime_type": mime_type,
                }

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        form = FileUploadForm(
                self.page_desc.maximum_megabytes, self.page_desc.mime_types)
        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        form = FileUploadForm(
                self.page_desc.maximum_megabytes, self.page_desc.mime_types,
                post_data, files_data)
        return form

    def form_to_html(self, request, page_context, form, answer_data):
        ctx = {"form": form}
        if answer_data is not None:
            ctx["mime_type"] = answer_data["mime_type"]
            ctx["data_url"] = "data:%s;base64,%s" % (
                answer_data["mime_type"],
                answer_data["base64_data"],
                )

        from django.template import RequestContext
        from django.template.loader import render_to_string
        return render_to_string(
                "course/file-upload-form.html",
                RequestContext(request, ctx))

    def answer_data(self, page_context, page_data, form, files_data):
        return self.files_data_to_answer_data(files_data)

# }}}


# vim: foldmethod=marker
