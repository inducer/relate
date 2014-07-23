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

from course.validation import validate_struct
from crispy_forms.helper import FormHelper
import django.forms as forms


class PageContext(object):
    def __init__(self, course, ordinal, page_count):
        self.course = course
        self.ordinal = ordinal
        self.page_count = page_count


class PageBase(object):
    """
    .. attribute:: location

        A string 'location' for reporting errors.

    .. attribute:: id

        The page identifier.
    """

    def __init__(self, location, id):
        self.location = location
        self.id = id

    def make_page_data(self):
        return {}

    def title(self, page_context, data):
        raise NotImplementedError()

    def body(self, page_context, data):
        raise NotImplementedError()

    def fresh_form(self, page_context, data):
        return None

    def form_with_answer(self, page_context, data,
            previous_answer, previous_answer_is_final):
        raise NotImplementedError()

    def post_form(self, page_context, data, post_data, files_data):
        raise NotImplementedError()


class Page(PageBase):
    def __init__(self, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("content", str),
                    ("title", str),
                    ],
                allowed_attrs=[],
                )

        PageBase.__init__(self, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, data):
        return self.page_desc.title

    def body(self, page_context, data):
        from course.content import html_body
        return html_body(page_context.course, self.page_desc.content)


class TextAnswerForm(forms.Form):
    answer = forms.CharField(required=True)

    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(TextAnswerForm, self).__init__(*args, **kwargs)


class TextQuestion(PageBase):
    def __init__(self, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("value", (int, float)),
                    ("title", str),
                    ("answers", list),
                    ("prompt", str),
                    ],
                allowed_attrs=[],
                )

        PageBase.__init__(self, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, data):
        return self.page_desc.title

    def body(self, page_context, data):
        from course.content import html_body
        return html_body(page_context.course, self.page_desc.prompt)

    def fresh_form(self, page_context, data):
        return TextAnswerForm()

    def form_with_answer(self, page_context, data,
            previous_answer, previous_answer_is_final):
        answer = {"answer": previous_answer["answer"]}
        form = TextAnswerForm(answer)

        if previous_answer_is_final:
            self.fields['answer'].widget.attrs['readonly'] = True

        return form

    def post_form(self, page_context, data, post_data, files_data):
        return TextAnswerForm(post_data, files_data)


class SymbolicQuestion(PageBase):
    def __init__(self, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("value", (int, float)),
                    ("title", str),
                    ("answers", list),
                    ("prompt", str),
                    ],
                allowed_attrs=[],
                )

        PageBase.__init__(self, location, page_desc.id)
        self.page_desc = page_desc


class ChoiceQuestion(PageBase):
    def __init__(self, location, page_desc):
        validate_struct(
                location,
                page_desc,
                required_attrs=[
                    ("type", str),
                    ("id", str),
                    ("value", (int, float)),
                    ("title", str),
                    ("choices", list),
                    ("prompt", str),
                    ],
                allowed_attrs=[],
                )

        PageBase.__init__(self, location, page_desc.id)
        self.page_desc = page_desc
