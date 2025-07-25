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

from typing import TYPE_CHECKING, Any

from course.page.base import (
    PageBaseUngraded,
    PageBaseWithCorrectAnswer,
    PageBaseWithTitle,
    PageBehavior,
    PageContext,
    markup_to_html,
)


if TYPE_CHECKING:
    from django import forms

    from course.validation import AttrSpec
    from relate.utils import StyledForm


class Page(PageBaseWithCorrectAnswer, PageBaseWithTitle, PageBaseUngraded):
    """
    A page showing static content.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``Page``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: content

        The page's content, in :ref:`markup`.

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.
    """

    def required_attrs(self) -> AttrSpec:
        return (*super().required_attrs(), ("content", "markup"))

    def markup_body_for_title(self) -> str:
        return self.page_desc.content

    def body(self, page_context, page_data) -> str:
        return markup_to_html(page_context, self.page_desc.content)

    def expects_answer(self) -> bool:
        return False

    def max_points(self, page_data: Any) -> float:
        raise NotImplementedError()

    def answer_data(
            self,
            page_context: PageContext,
            page_data: Any,
            form: forms.Form,
            files_data: Any,
            ) -> Any:
        raise NotImplementedError()

    def make_form(
            self,
            page_context: PageContext,
            page_data: Any,
            answer_data: Any,
            page_behavior: Any,
            ) -> StyledForm:
        raise NotImplementedError()

    def process_form_post(
            self,
            page_context: PageContext,
            page_data: Any,
            post_data: Any,
            files_data: Any,
            page_behavior: PageBehavior,
            ) -> StyledForm:
        raise NotImplementedError()
