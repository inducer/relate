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

from course.validation import validate_struct, ValidationError
from crispy_forms.helper import FormHelper
import django.forms as forms
import re


class PageContext(object):
    def __init__(self, course, ordinal, page_count):
        self.course = course
        self.ordinal = ordinal
        self.page_count = page_count


class AnswerFeedback(object):
    """
    .. attribute:: correctness

        A :class:`float` between 0 and 1 (inclusive),
        indicating the degree of correctness of the
        answer.

    .. attribute:: correct_answer

        Text describing the correct answer.

    .. attribute:: feedback

        Text (as a full sentence) providing feedback to the student about the
        provided answer. Should not reveal the correct answer.

        May be None, in which case generic feedback
        is generated from :attr:`correctness`.
    """

    def __init__(self, correctness, correct_answer, feedback=None):
        if correctness < 0 or correctness > 1:
            raise ValueError("Invalid correctness value")

        if feedback is None:
            if correctness == 0:
                feedback = "Your answer is not correct."
            elif correctness == 1:
                feedback = "Your answer is correct."
            elif correctness > 0.5:
                feedback = "Your answer is mostly correct."
            else:
                feedback = "Your answer is somewhat correct."

        self.correctness = correctness
        self.correct_answer = correct_answer
        self.feedback = feedback


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

    def make_answer_data(self, page_context, data, form):
        raise NotImplementedError()

    def grade(self, page_context, data, answer_data):
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

        if len(page_desc.answers) == 0:
            raise ValidationError("%s: at least one answer must be provided"
                    % location)

        if not page_desc.answers[0].startswith("plain:"):
            raise ValidationError("%s: first answer must be 'plain:' to serve as "
                    "correct answer" % location)

        for i, answer in enumerate(page_desc.answers):
            if answer.startswith("regex:"):
                try:
                    re.compile(answer.lstrip("regex:"))
                except:
                    raise ValidationError("%s, answer %d: regex did not compile"
                            % (location, i+1))
            elif answer.startswith("plain:"):
                pass
            else:
                raise ValidationError("%s, answer %d: unknown answer type"
                        % (location, i+1))

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
            answer_data, answer_is_final):
        answer = {"answer": answer_data["answer"]}
        form = TextAnswerForm(answer)

        if answer_is_final:
            self.fields['answer'].widget.attrs['readonly'] = True

        return form

    def post_form(self, page_context, data, post_data, files_data):
        return TextAnswerForm(post_data, files_data)

    def make_answer_data(self, page_context, data, form):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, data, answer_data):
        correctness = 0

        answer = answer_data["answer"]

        for correct_answer in self.page_desc.answers:
            if correct_answer.startswith("regex:"):
                pattern = re.compile(answer.lstrip("regex:"))

                if pattern.match(answer):
                    correctness = 1
                    break

            elif answer.startswith("plain:"):
                pattern = answer.lstrip("plain:")

                if pattern == answer:
                    correctness = 1
                    break

            else:
                raise ValueError("unknown text answer type")

        return AnswerFeedback(
                correctness=correctness,
                correct_answer=self.page_desc.answers[0].lstrip("plain:"))


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
