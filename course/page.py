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

from course.validation import validate_struct, ValidationError, validate_markup
from course.content import remove_prefix
from crispy_forms.helper import FormHelper
from django.utils.safestring import mark_safe
import django.forms as forms

import re
import sys


__doc__ = """

.. autoclass:: PageBase
.. autoclass:: AnswerFeedback
.. autoclass:: PageContext

"""


class PageContext(object):
    """
    .. attribute:: course
    """

    def __init__(self, course, repo, commit_sha):
        self.course = course
        self.repo = repo
        self.commit_sha = commit_sha


def markup_to_html(page_context, text):
    from course.content import markup_to_html

    return markup_to_html(
            page_context.course,
            page_context.repo,
            page_context.commit_sha,
            text)


# {{{ answer feedback type

class AnswerFeedback(object):
    """
    .. attribute:: correctness

        A :class:`float` between 0 and 1 (inclusive),
        indicating the degree of correctness of the
        answer.

    .. attribute:: correct_answer

        Text (as a full sentence) describing the correct answer.

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
                feedback = "Your answer was not correct."
            elif correctness == 1:
                feedback = "Your answer was correct."
            elif correctness > 0.5:
                feedback = "Your answer was mostly correct."
            else:
                feedback = "Your answer was somewhat correct."

        self.correctness = correctness
        self.correct_answer = correct_answer
        self.feedback = feedback

# }}}


# {{{ abstract page base class

class PageBase(object):
    """The abstract interface of a flow page.

    .. attribute:: location

        A string 'location' for reporting errors.

    .. attribute:: id

        The page identifier.

    .. automethod:: make_page_data
    .. automethod:: title
    .. automethod:: body
    .. automethod:: expects_answer
    .. automethod:: max_points
    .. automethod:: answer_data
    .. automethod:: make_form
    .. automethod:: post_form
    .. automethod:: grade
    """

    def __init__(self, vctx, location, id):
        """
        :arg vctx: a :class:`course.validation.ValidationContext`
        """

        self.location = location
        self.id = id

    def make_page_data(self):
        """Return (possibly randomly generated) data that is used to generate
        the content on this page. This is passed to methods below as the *page_data*
        argument. One possible use for this argument would be a random permutation
        of choices that is generated once (at flow setup) and then used whenever
        this page is shown.
        """
        return {}

    def title(self, page_context, page_data):
        """Return the (non-HTML) title of this page."""

        raise NotImplementedError()

    def body(self, page_context, page_data):
        """Return the (HTML) body of the page."""

        raise NotImplementedError()

    def expects_answer(self):
        """
        :return: a :class:`bool` indicating whether this page lets the
            user provide an answer of some type.
        """
        raise NotImplementedError()

    def max_points(self, page_data):
        """
        :return: a :class:`int` or :class:`float` indicating how many points
            are achievable on this page.
        """
        raise NotImplementedError()

    def answer_data(self, page_context, page_data, form):
        raise NotImplementedError()
        """Return a JSON-persistable object reflecting the user's answer on the
        form. This will be passed to methods below as *answer_data*.
        """

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        """
        :arg answer_data: value returned by :meth:`answer_data`.
             May be *None*.
        :return: a tuple (form, form_html), where *form* is a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If *answer_is_final* is *True*, the form should be read-only.

            *form_html* is the HTML of the rendered form. If *None*, the form
            will automatically be rendered using
            :func:`crispy_forms.utils.render_crispy_form`.
        """

        raise NotImplementedError()

    def post_form(self, page_context, page_data, post_data, files_data):
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :return: a tuple (form, form_html), where *form* is a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If *answer_is_final* is *True*, the form should be read-only.

            *form_html* is the HTML of the rendered form. It should not include
            a ``<form>`` HTML tag or a Django CSRF token. If *None*, the form
            will automatically be rendered using
            :func:`crispy_forms.utils.render_crispy_form`.
        """
        raise NotImplementedError()

    def grade(self, page_context, page_data, answer_data, grade_data):
        """Grade the answer contained in *answer_data*.

        :arg answer_data: value returned by :meth:`answer_data`,
            or *None*, which means that no answer was supplied.
        :arg grade_data: is a (currently unimplemented) interface to
            feed in persisted information from deferred/human grading.
        :return: a :class:`AnswerFeedback` instanstance, or *None* if the
            grade is not yet available.
        """

        raise NotImplementedError()

# }}}


class Page(PageBase):
    """A page showing static content."""

    def __init__(self, vctx, location, page_desc):
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

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

        validate_markup(vctx, location, page_desc.content)

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.content)

    def expects_answer(self):
        return False


# {{{ text question

class TextAnswerForm(forms.Form):
    answer = forms.CharField(required=True)

    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(TextAnswerForm, self).__init__(*args, **kwargs)

        self.fields["answer"].widget.attrs["autofocus"] = None


REGEX_PREFIX = "regex:"
PLAIN_PREFIX = "plain:"


class TextQuestion(PageBase):
    def __init__(self, vctx, location, page_desc):
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

        validate_markup(vctx, location, page_desc.prompt)

        for i, answer in enumerate(page_desc.answers):
            ans_location = "%s, answer %d" % (location, i+1)

            if answer.startswith(REGEX_PREFIX):
                try:
                    re.compile(remove_prefix(REGEX_PREFIX, answer))
                except:
                    raise ValidationError("%s: regex did not compile" % ans_location)
            elif answer.startswith(PLAIN_PREFIX):
                pass
            else:
                raise ValidationError("%s: unknown answer type" % ans_location)

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return self.page_desc.value

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = TextAnswerForm(answer)
        else:
            answer = None
            form = TextAnswerForm()

        if answer_is_final:
            form.fields['answer'].widget.attrs['readonly'] = True

        return (form, None)

    def post_form(self, page_context, page_data, post_data, files_data):
        return (TextAnswerForm(post_data, files_data), None)

    def answer_data(self, page_context, page_data, form):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):
        correct_answer_text = ("A correct answer is: '%s'."
                % remove_prefix("plain:", self.page_desc.answers[0]))

        correctness = 0

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    correct_answer=correct_answer_text)

        answer = answer_data["answer"]

        for correct_answer in self.page_desc.answers:
            if correct_answer.startswith(REGEX_PREFIX):
                pattern = re.compile(remove_prefix(REGEX_PREFIX, correct_answer))

                match = pattern.match(answer)
                if match:
                    correctness = 1
                    break

            elif correct_answer.startswith(PLAIN_PREFIX):
                pattern = remove_prefix(PLAIN_PREFIX, correct_answer)

                if pattern == answer:
                    correctness = 1
                    break

            else:
                raise ValueError("unknown text answer type in '%s'" % correct_answer)

        return AnswerFeedback(
                correctness=correctness,
                correct_answer=correct_answer_text)

# }}}


# {{{ symbolic question

def parse_sympy(s):
    if isinstance(s, unicode):
        # Sympy is not spectacularly happy with unicode function names
        s = s.encode()

    from pymbolic import parse
    from pymbolic.sympy_interface import PymbolicToSympyMapper

    # use pymbolic because it has a semi-secure parser
    return PymbolicToSympyMapper()(parse(s))


class SymbolicAnswerForm(TextAnswerForm):
    def clean(self):
        cleaned_data = super(SymbolicAnswerForm, self).clean()

        try:
            parse_sympy(cleaned_data["answer"])
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%s: %s"
                    % (tp.__name__, str(e)))


class SymbolicQuestion(PageBase):
    def __init__(self, vctx, location, page_desc):
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

        for answer in page_desc.answers:
            try:
                parse_sympy(answer)
            except:
                tp, e, _ = sys.exc_info()
                raise ValidationError("%s: %s: %s"
                        % (location, tp.__name__, str(e)))

        validate_markup(vctx, location, page_desc.prompt)

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return self.page_desc.value

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = SymbolicAnswerForm(answer)
        else:
            form = SymbolicAnswerForm()

        if answer_is_final:
            form.fields['answer'].widget.attrs['readonly'] = True

        return (form, None)

    def post_form(self, page_context, page_data, post_data, files_data):
        return (SymbolicAnswerForm(post_data, files_data), None)

    def answer_data(self, page_context, page_data, form):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):
        correct_answer_text = ("A correct answer is: '%s'."
                % self.page_desc.answers[0])

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    correct_answer=correct_answer_text)

        correctness = 0

        answer = parse_sympy(answer_data["answer"])

        from sympy import simplify
        for correct_answer in self.page_desc.answers:
            correct_answer_sym = parse_sympy(correct_answer)

            if simplify(answer - correct_answer_sym) == 0:
                correctness = 1

        return AnswerFeedback(correctness=correctness,
                correct_answer=correct_answer_text)

# }}}


# {{{ choice question

class ChoiceAnswerForm(forms.Form):
    def __init__(self, field, *args, **kwargs):
        self.helper = FormHelper()
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-lg-2"
        self.helper.field_class = "col-lg-8"

        super(ChoiceAnswerForm, self).__init__(*args, **kwargs)

        self.fields["choice"] = field


class ChoiceQuestion(PageBase):
    CORRECT_TAG = "~CORRECT~"

    def __init__(self, vctx, location, page_desc):
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

        correct_choice_count = 0
        for choice in page_desc.choices:
            if choice.startswith(self.CORRECT_TAG):
                correct_choice_count += 1

        if correct_choice_count != 1:
            raise ValidationError("%s: exactly one correct answer expected, %d found"
                    % (location, correct_choice_count))

        validate_markup(vctx, location, page_desc.prompt)

        PageBase.__init__(self, vctx, location, page_desc.id)
        self.page_desc = page_desc

    def title(self, page_context, page_data):
        return self.page_desc.title

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return self.page_desc.value

    def make_page_data(self):
        import random
        perm = range(len(self.page_desc.choices))
        random.shuffle(perm)

        return {"permutation": perm}

    def make_choice_form(self, page_context, page_data, *args, **kwargs):
        permutation = page_data["permutation"]

        def process_choice_string(s):
            s = remove_prefix(self.CORRECT_TAG, s)

            s = markup_to_html(page_context, s)

            # allow HTML in option
            s = mark_safe(s)

            return s

        choices = tuple(
                (i,  process_choice_string(self.page_desc.choices[src_i]))
                for i, src_i in enumerate(permutation))

        return ChoiceAnswerForm(
            forms.TypedChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.RadioSelect()),
            *args, **kwargs)

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            form_data = {"choice": answer_data["choice"]}
            form = self.make_choice_form(page_context, page_data, form_data)
        else:
            form = self.make_choice_form(page_context, page_data)

        if answer_is_final:
            form.fields['choice'].widget.attrs['disabled'] = True

        return (form, None)

    def post_form(self, page_context, page_data, post_data, files_data):
        return (
                self.make_choice_form(
                    page_context, page_data, post_data, files_data),
                None)

    def answer_data(self, page_context, page_data, form):
        return {"choice": form.cleaned_data["choice"]}

    def grade(self, page_context, page_data, answer_data, grade_data):
        for i, choice_text in enumerate(self.page_desc.choices):
            if choice_text.startswith(self.CORRECT_TAG):
                unpermuted_correct_idx = i

        correct_answer_text = ("A correct answer is: '%s'."
                % remove_prefix(
                    self.CORRECT_TAG,
                    self.page_desc.choices[unpermuted_correct_idx]).lstrip())

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    correct_answer=correct_answer_text)

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        if permutation[choice] == unpermuted_correct_idx:
            correctness = 1
        else:
            correctness = 0

        return AnswerFeedback(correctness=correctness,
                correct_answer=correct_answer_text)

# }}}

# vim: foldmethod=marker
