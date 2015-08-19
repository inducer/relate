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
from django.utils.translation import (
        ugettext_lazy as _, ugettext, string_concat)

from relate.utils import StyledForm
from course.page.base import (
        AnswerFeedback, PageBaseWithTitle, PageBaseWithValue, markup_to_html)
from course.content import remove_prefix
from course.validation import validate_markup, ValidationError


class ChoiceAnswerForm(StyledForm):
    def __init__(self, field, *args, **kwargs):
        super(ChoiceAnswerForm, self).__init__(*args, **kwargs)

        self.fields["choice"] = field
        # Translators: "choice" in Choice Answer Form in a single-choice question.
        self.fields["choice"].label = _("Choice")


class MultipleChoiceAnswerForm(StyledForm):
    def __init__(self, field, *args, **kwargs):
        super(MultipleChoiceAnswerForm, self).__init__(*args, **kwargs)

        self.fields["choice"] = field

        # Translators: "Choice" in Choice Answer Form in a multiple
        # choice question in which multiple answers can be chosen.
        self.fields["choice"].label = _("Choices")


# {{{ choice question

class ChoiceQuestion(PageBaseWithTitle, PageBaseWithValue):
    """
    A page asking the participant to choose one of multiple answers.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``ChoiceQuestion``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: value

        |value-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: choices

        A list of choices, each in :ref:`markup`. Correct
        choices are indicated by the prefix ``~CORRECT~``.

    .. attribute:: shuffle

        Optional. ``True`` or ``False``. If true, the choices will
        be presented in random order.
    """

    CORRECT_TAG = "~CORRECT~"

    @classmethod
    def process_choice_string(cls, page_context, s):
        if not isinstance(s, str):
            s = str(s)
        s = remove_prefix(cls.CORRECT_TAG, s)
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, page_desc):
        super(ChoiceQuestion, self).__init__(vctx, location, page_desc)

        correct_choice_count = 0
        for choice_idx, choice in enumerate(page_desc.choices):
            try:
                choice = str(choice)
            except:
                raise ValidationError(
                        string_concat(
                            "%(location)s, ",
                            _("choice %(idx)d: unable to convert to string")
                            )
                        % {'location': location, 'idx': choice_idx+1})

            if choice.startswith(self.CORRECT_TAG):
                correct_choice_count += 1

            if vctx is not None:
                validate_markup(vctx, location,
                        remove_prefix(self.CORRECT_TAG, choice))

        if correct_choice_count < 1:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("one or more correct answer(s) "
                        "expected, %(n_correct)d found"))
                    % {
                        'location': location,
                        'n_correct': correct_choice_count})

    def required_attrs(self):
        return super(ChoiceQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("choices", list),
                )

    def allowed_attrs(self):
        return super(ChoiceQuestion, self).allowed_attrs() + (
                ("shuffle", bool),
                )

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def make_page_data(self):
        import random
        perm = range(len(self.page_desc.choices))
        if getattr(self.page_desc, "shuffle", False):
            random.shuffle(perm)

        return {"permutation": perm}

    def make_choice_form(self, page_context, page_data, *args, **kwargs):
        permutation = page_data["permutation"]

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.page_desc.choices[src_i]))
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

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        return self.make_choice_form(
                    page_context, page_data, post_data, files_data)

    def answer_data(self, page_context, page_data, form, files_data):
        return {"choice": form.cleaned_data["choice"]}

    def unpermuted_correct_indices(self):
        result = []
        for i, choice_text in enumerate(self.page_desc.choices):
            if str(choice_text).startswith(self.CORRECT_TAG):
                result.append(i)

        return result

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=ugettext("No answer provided."))

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        if permutation[choice] in self.unpermuted_correct_indices():
            correctness = 1
        else:
            correctness = 0

        return AnswerFeedback(correctness=correctness)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        corr_idx = self.unpermuted_correct_indices()[0]
        return (string_concat(_("A correct answer is"), ": '%s'.")
                % self.process_choice_string(
                    page_context,
                    self.page_desc.choices[corr_idx]).lstrip())

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        return self.process_choice_string(
                page_context,
                self.page_desc.choices[permutation[choice]])
# }}}


# {{{ multiple choice question

class MultipleChoiceQuestion(ChoiceQuestion):
    """
    A page asking the participant to choose a few of multiple available answers.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``MultipleChoiceQuestion``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: value

        |value-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: choices

        A list of choices, each in :ref:`markup`. Correct
        choices are indicated by the prefix ``~CORRECT~``.

    .. attribute:: shuffle

        Optional. ``True`` or ``False``. If true, the choices will
        be presented in random order.

    .. attribute:: allow_partial_credit

        Optional. ``True`` or ``False``. If False (default), only
        answers in which all check marks match the reference solution will
        be counted as correct.  If True, answers with subset of correct
        choices will receive credit for each matching check box, irrespective
        of whether it is checked or not.
    """

    def allowed_attrs(self):
        return super(MultipleChoiceQuestion, self).allowed_attrs() + (
                ("allow_partial_credit", bool),
                )

    def make_choice_form(self, page_context, page_data, *args, **kwargs):
        permutation = page_data["permutation"]

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.page_desc.choices[src_i]))
                for i, src_i in enumerate(permutation))

        return MultipleChoiceAnswerForm(
            forms.TypedMultipleChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.CheckboxSelectMultiple()),
            *args, **kwargs)

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=ugettext("No answer provided."))

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        unpermed_idx_set = set([permutation[idx] for idx in choice])
        correct_idx_set = set(self.unpermuted_correct_indices())

        if unpermed_idx_set == correct_idx_set:
            correctness = 1
        else:
            if not getattr(self.page_desc, "allow_partial_credit", False):
                correctness = 0
            else:
                correctness = (
                        (
                            len(self.page_desc.choices)
                            -
                            len(unpermed_idx_set
                                .symmetric_difference(correct_idx_set)))
                        /
                        len(self.page_desc.choices))

        return AnswerFeedback(correctness=correctness)

    def get_answer_html(self, page_context, idx_list, unpermute=False):
        answer_html_list = []
        if unpermute:
            idx_list = list(set(idx_list))
        for idx in idx_list:
            answer_html_list.append(
                    "<li>"
                    + (self.process_choice_string(
                        page_context,
                        self.page_desc.choices[idx])
                        .lstrip())
                    + "</li>"
                    )
        answer_html = "<ul>"+"".join(answer_html_list)+"</ul>"
        return answer_html

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        corr_idx_list = self.unpermuted_correct_indices()

        return (string_concat(_("The correct answer is"), ": '%s'.")
                % self.get_answer_html(page_context, corr_idx_list))

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        return self.get_answer_html(
            page_context,
            [permutation[idx] for idx in choice],
            unpermute=True)
# }}}


# {{{ survey choice question

class SurveyChoiceQuestion(PageBaseWithTitle):
    """
    A page asking the participant to choose one of multiple answers.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``ChoiceQuestion``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: choices

        A list of choices, each in :ref:`markup`.
    """

    @classmethod
    def process_choice_string(cls, page_context, s):
        if not isinstance(s, str):
            s = str(s)
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, page_desc):
        super(SurveyChoiceQuestion, self).__init__(vctx, location, page_desc)

        for choice_idx, choice in enumerate(page_desc.choices):
            try:
                choice = str(choice)
            except:
                raise ValidationError(
                    string_concat(
                        "%(location)s, ",
                        _("choice %(idx)d: unable to convert to string")
                        )
                    % {"location": location, "idx": choice_idx+1})

            if vctx is not None:
                validate_markup(vctx, location, choice)

    def required_attrs(self):
        return super(SurveyChoiceQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("choices", list),
                )

    def allowed_attrs(self):
        return super(SurveyChoiceQuestion, self).allowed_attrs() + (
                ("answer_comment", "markup"),
                )

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        if hasattr(self.page_desc, "answer_comment"):
            return markup_to_html(page_context, self.page_desc.answer_comment)
        else:
            return None

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def make_choice_form(self, page_context, page_data, *args, **kwargs):

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.page_desc.choices[i]))
                for i in range(len(self.page_desc.choices)))

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

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        return self.make_choice_form(
                    page_context, page_data, post_data, files_data)

    def answer_data(self, page_context, page_data, form, files_data):
        return {"choice": form.cleaned_data["choice"]}

    def expects_answer(self):
        return True

    def is_answer_gradable(self):
        return False

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        choice = answer_data["choice"]

        return self.process_choice_string(
                page_context,
                self.page_desc.choices[choice])
# }}}

# vim: foldmethod=marker
