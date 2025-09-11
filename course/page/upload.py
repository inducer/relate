from __future__ import annotations


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

from typing import TYPE_CHECKING, Any, Literal, Self, TypeAlias

import django.forms as forms
from crispy_forms.layout import Field, Layout
from django.utils.translation import gettext as _, gettext_lazy
from pydantic import NonNegativeFloat, ValidationInfo, model_validator
from typing_extensions import override

from course.page.base import (
    AnswerData,
    PageBaseWithCorrectAnswer,
    PageBaseWithHumanTextFeedback,
    PageBaseWithTitle,
    PageBaseWithValue,
    PageBehavior,
    PageContext,
    PageData,
    markup_to_html,
)
from course.validation import Markup, get_validation_context
from relate.utils import StyledFormBase, StyledVerticalForm


if TYPE_CHECKING:
    from django.core.files import File
    from django.http import HttpRequest


# {{{ upload question

class FileUploadForm(StyledVerticalForm):
    uploaded_file = forms.FileField(required=True,
            label=gettext_lazy("Uploaded file"))

    def __init__(self, maximum_megabytes, mime_types, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.max_file_size = maximum_megabytes * 1024**2
        self.mime_types = mime_types

        # 'accept=' doesn't work right for at least application/octet-stream.
        # We'll start with a whitelist.
        allow_accept = False
        if mime_types == ["application/pdf"]:
            allow_accept = True

        field_kwargs = {}
        if allow_accept:
            field_kwargs["accept"] = ",".join(mime_types)

        self.helper.layout = Layout(
                Field("uploaded_file", **field_kwargs))

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data["uploaded_file"]
        from django.template.defaultfilters import filesizeformat

        if uploaded_file.size > self.max_file_size:
            raise forms.ValidationError(
                    _("Please keep file size under %(allowedsize)s. "
                    "Current filesize is %(uploadedsize)s.")
                    % {"allowedsize": filesizeformat(self.max_file_size),
                        "uploadedsize": filesizeformat(uploaded_file.size)})

        if self.mime_types is not None and self.mime_types == ["application/pdf"]:
            if uploaded_file.read()[:4] != b"%PDF":
                raise forms.ValidationError(_("Uploaded file is not a PDF."))

        return uploaded_file


UploadableMimeType: TypeAlias = Literal[
            "application/pdf",
            "text/plain",
            "application/octet-stream",
]


class FileUploadQuestion(PageBaseWithTitle, PageBaseWithValue,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):
    """
    A page allowing the submission of a file upload that will be
    graded with text feedback by a human grader.

    Supports automatic computation of point values from textual feedback.
    See :ref:`points-from-feedback`.

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

    .. attribute:: rubric

        Required.
        The grading guideline for this question, in :ref:`markup`.
    """

    type: Literal["FileUploadQuestion"]  = "FileUploadQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    prompt: Markup
    mime_types: list[UploadableMimeType]
    maximum_megabytes: NonNegativeFloat

    correct_answer: Markup | None = None

    @model_validator(mode="after")
    def check_has_value(self, info: ValidationInfo) -> Self:
        vctx = get_validation_context(info)
        if self.value is None:
            vctx.add_warning("upload question does not have assigned point value")

        return self

    @override
    def human_feedback_point_value(self,
                page_context: PageContext,
                page_data: Any
            ) -> float | None:
        return self.max_points(page_data)

    @override
    def body_attr_for_title(self):
        return "prompt"

    @override
    def body(self, page_context: PageContext, page_data: PageData) -> str:
        return markup_to_html(page_context, self.prompt)

    def get_submission_filename_pattern(self,
                page_context: PageContext,
                mime_type: str | None):
        from mimetypes import guess_extension
        if mime_type is not None:
            ext = guess_extension(mime_type)
        else:
            ext = ".bin"

        username = "anon"
        flow_id = "unk_flow"
        if page_context.flow_session is not None:
            if page_context.flow_session.participation is not None:
                username = page_context.flow_session.participation.user.username
            if page_context.flow_session.flow_id:
                flow_id = page_context.flow_session.flow_id

        return ("submission/"
                f"{page_context.course.identifier}/"
                "file-upload/"
                f"{flow_id}/"
                f"{self.id}/"
                f"{username}"
                f"{ext}")

    def file_to_answer_data(self,
                page_context: PageContext,
                uploaded_file: File,
                mime_type: str | None):
        if len(self.mime_types) == 1:
            mime_type, = self.mime_types

        from django.conf import settings

        uploaded_file.seek(0)
        saved_name = settings.RELATE_BULK_STORAGE.save(
                self.get_submission_filename_pattern(page_context, mime_type),
                uploaded_file)

        return {
                "storage_filename": saved_name,
                "mime_type": mime_type,
                }

    @staticmethod
    def get_content_from_answer_data(answer_data) -> tuple[bytes, str]:
        mime_type = answer_data.get("mime_type", "application/octet-stream")

        if "storage_filename" in answer_data:
            from django.conf import settings
            with settings.RELATE_BULK_STORAGE.open(
                    answer_data["storage_filename"]) as inf:
                return inf.read(), mime_type

        elif "base64_data" in answer_data:
            from base64 import b64decode
            return b64decode(answer_data["base64_data"]), mime_type

        else:
            raise ValueError("could not get submitted data from answer_data JSON")

    @override
    def make_form(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        form = FileUploadForm(
                self.maximum_megabytes, self.mime_types)
        return form

    @override
    def process_form_post(
            self,
            page_context: PageContext,
            page_data: PageData,
            post_data: Any,
            files_data: Any,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        form = FileUploadForm(
                self.maximum_megabytes, self.mime_types,
                post_data, files_data)
        return form

    @override
    def form_to_html(
            self,
            request: HttpRequest,
            page_context: PageContext,
            form: StyledFormBase,
            answer_data: AnswerData,
            ):
        ctx: dict[str, object] = {"form": form}
        if answer_data is not None:
            from base64 import b64encode
            subm_data, subm_mime = self.get_content_from_answer_data(answer_data)
            ctx["mime_type"] = subm_mime
            ctx["data_url"] = f"data:{subm_mime};base64,{b64encode(subm_data).decode()}"

        from django.template.loader import render_to_string
        return render_to_string(
                "course/file-upload-form.html", ctx, request)

    def answer_data(self, page_context, page_data, form, files_data):
        uploaded_file = files_data["uploaded_file"]
        return self.file_to_answer_data(page_context, uploaded_file,
                mime_type=uploaded_file.content_type)

    @override
    def normalized_answer(
                self,
                page_context: PageContext,
                page_data: PageData,
                answer_data: AnswerData
            ) -> str | None:
        return None

    @override
    def normalized_bytes_answer(self,
                page_context: PageContext,
                page_data: PageData,
                answer_data: AnswerData,
            ) -> tuple[str, bytes] | None:
        if answer_data is None:
            return None

        subm_data, subm_mime = self.get_content_from_answer_data(answer_data)

        from mimetypes import guess_extension
        ext = guess_extension(subm_mime)

        if ext is None:
            ext = ".dat"

        return (ext, subm_data)

# }}}


# vim: foldmethod=marker
