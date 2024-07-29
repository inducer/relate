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

import django.forms as forms
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _

from course.page.base import (
    AnswerFeedback,
    PageBaseWithTitle,
    PageBaseWithValue,
    markup_to_html,
)
from course.validation import ValidationError, validate_markup
from relate.utils import StyledForm, string_concat


class ChoiceAnswerForm(StyledForm):
    def __init__(self, field, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["choice"] = field
        # Translators: "choice" in Choice Answer Form in a single-choice question.
        self.fields["choice"].label = _("Choice")


class MultipleChoiceAnswerForm(StyledForm):
    def __init__(self, field, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["choice"] = field

        # Translators: "Choice" in Choice Answer Form in a multiple
        # choice question in which multiple answers can be chosen.
        self.fields["choice"].label = _("Select all that apply:")


def markup_to_html_plain(page_context, s):
    s = markup_to_html(page_context, s)
    if s.startswith("<p>") and s.endswith("</p>"):
        s = s[3:-4]
    return s


# {{{ choice data model

class ChoiceModes:
    INCORRECT = "incorrect"
    CORRECT = "correct"
    DISREGARD = "disregard"
    ALWAYS_CORRECT = "always_correct"

    values = [INCORRECT, CORRECT, DISREGARD, ALWAYS_CORRECT]


class ChoiceInfo:
    CORRECT_TAG = "~CORRECT~"
    DISREGARD_TAG = "~DISREGARD~"
    ALWAYS_CORRECT_TAG = "~ALWAYS_CORRECT~"

    def __init__(self, mode, text):
        assert mode in ChoiceModes.values

        self.mode = mode
        self.text = text

    @classmethod
    def parse_from_yaml(cls, vctx, location, node):
        # could be a number or a bool due to sloppy YAML
        try:
            node = str(node)
        except Exception:
            raise ValidationError(
                    _("%(location)s: unable to convert to string")
                    % {"location": location})

        tag_mode_dict = {
            cls.CORRECT_TAG: ChoiceModes.CORRECT,
            cls.DISREGARD_TAG: ChoiceModes.DISREGARD,
            cls.ALWAYS_CORRECT_TAG: ChoiceModes.ALWAYS_CORRECT
        }

        s = node

        item_mode = [None]

        def find_tag_by_mode(mode):
            for k, v in tag_mode_dict.items():  # pragma: no branch
                if v == mode:
                    return k

        def mode_from_prefix(s):
            for prefix in tag_mode_dict.keys():
                if s.startswith(prefix):
                    s = s[len(prefix):].strip()

                    if item_mode[0] is not None:
                        raise ValidationError(
                                _("%(location)s: more than one choice modes "
                                  "set: '%(modes)s'")
                                % {"location": location,
                                   "modes":
                                       "".join([find_tag_by_mode(item_mode[0]),
                                                  prefix])
                                   })

                    item_mode[0] = tag_mode_dict[prefix]
                    s = mode_from_prefix(s)
            return s

        s = mode_from_prefix(s)

        if item_mode[0] is None:
            item_mode[0] = ChoiceModes.INCORRECT

        if vctx is not None:
            validate_markup(vctx, location, s)

        return ChoiceInfo(item_mode[0], s)

    def to_json(self):
        return {"mode": self.mode, "text": self.text}

# }}}


# {{{ choice question base

class ChoiceQuestionBase(PageBaseWithTitle, PageBaseWithValue):
    @classmethod
    def process_choice_string(cls, page_context, s):
        s = markup_to_html_plain(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        self.correct_choice_count = 0
        self.disregard_choice_count = 0
        self.always_correct_choice_count = 0

        self.choices = []

        for choice_idx, choice_desc in enumerate(page_desc.choices):
            choice = ChoiceInfo.parse_from_yaml(
                    vctx,
                    _("%(location)s, choice %(idx)d") %
                    {"location": location,
                     "idx": choice_idx+1},
                    choice_desc)
            self.choices.append(choice)

            if choice.mode == ChoiceModes.CORRECT:
                self.correct_choice_count += 1

            if choice.mode == ChoiceModes.DISREGARD:
                self.disregard_choice_count += 1

            if choice.mode == ChoiceModes.ALWAYS_CORRECT:
                self.always_correct_choice_count += 1

    def required_attrs(self):
        return (*super().required_attrs(), ("prompt", "markup"), ("choices", list))

    def allowed_attrs(self):
        return (*super().allowed_attrs(), ("shuffle", bool))

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def initialize_page_data(self, page_context):
        import random
        perm = list(range(len(self.choices)))
        if getattr(self.page_desc, "shuffle", False):
            random.shuffle(perm)

        return {"permutation": perm}

    def check_page_data(self, page_data):
        if (
                "permutation" not in page_data
                or (set(page_data["permutation"])
                    != set(range(len(self.choices))))):
            from course.page import InvalidPageData
            raise InvalidPageData(gettext(
                "existing choice permutation not "
                "suitable for number of choices in question"))

    def unpermuted_indices_with_mode(self, mode):
        return [i for i, choice in enumerate(self.choices)
                if choice.mode == mode]

    def unpermuted_correct_indices(self):
        return self.unpermuted_indices_with_mode(ChoiceModes.CORRECT)

    def unpermuted_disregard_indices(self):
        return self.unpermuted_indices_with_mode(ChoiceModes.DISREGARD)

    def unpermuted_always_correct_indices(self):
        return self.unpermuted_indices_with_mode(ChoiceModes.ALWAYS_CORRECT)

    def make_form(self, page_context, page_data, answer_data, page_behavior):
        self.check_page_data(page_data)

        if answer_data is not None:
            form_data = {"choice": answer_data["choice"]}
            form = self.make_choice_form(
                    page_context, page_data, page_behavior, form_data)
        else:
            form = self.make_choice_form(
                    page_context, page_data, page_behavior)

        return form

    def process_form_post(self, page_context, page_data, post_data, files_data,
            page_behavior):
        return self.make_choice_form(
                    page_context, page_data, page_behavior, post_data, files_data)

# }}}


# {{{ choice question

class ChoiceQuestion(ChoiceQuestionBase):
    """
    A page asking the participant to choose one of multiple answers.

    Example:

    .. code-block:: yaml

        type: ChoiceQuestion
        id: fp_accuracy
        shuffle: True
        prompt: |
            # Floating point "machine epsilon"
            For a (binary) floating point system of the form
            $(s_1.s_2s_3)_2\\cdot 2^{p}$ that has an exponent range from $-128$ to
            $127$ and that uses three bits to store the significand $s$, what is the
            difference between 1 and the smallest representable number greater than
            one?
        choices:
            - $2^{-3}$
            - $2^{-4}$
            - $2^{-1}$
            - ~CORRECT~  $2^{-2}$
        answer_explanation: |

            That's just what it is.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``ChoiceQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

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

    .. attribute:: answer_explanation

        Text justifying the answer, written in :ref:`markup`.
    """

    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        if self.correct_choice_count < 1:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("one or more correct answer(s) "
                        "expected, %(n_correct)d found"))
                    % {
                        "location": location,
                        "n_correct": self.correct_choice_count})

        if self.disregard_choice_count:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("ChoiceQuestion does not allow any choices "
                        "marked 'disregard'"))
                    % {"location": location})

        if self.always_correct_choice_count:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("ChoiceQuestion does not allow any choices "
                        "marked 'always_correct'"))
                    % {"location": location})

    def allowed_attrs(self):
        return (*super().allowed_attrs(), ("answer_explanation", "markup"))

    def make_choice_form(
            self, page_context, page_data, page_behavior, *args, **kwargs):
        permutation = page_data["permutation"]

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.choices[src_i].text))
                for i, src_i in enumerate(permutation))

        form = ChoiceAnswerForm(
            forms.TypedChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.RadioSelect()),
            *args, **kwargs)

        if not page_behavior.may_change_answer:
            form.fields["choice"].widget.attrs["disabled"] = True

        return form

    def answer_data(self, page_context, page_data, form, files_data):
        return {"choice": form.cleaned_data["choice"]}

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=gettext("No answer provided."))

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        if permutation[choice] in self.unpermuted_correct_indices():
            correctness = 1
        else:
            correctness = 0

        return AnswerFeedback(correctness=correctness)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        corr_idx = self.unpermuted_correct_indices()[0]
        result = (string_concat(_("A correct answer is"), ": '%s'.")
                % self.process_choice_string(
                    page_context,
                    self.choices[corr_idx].text))

        if hasattr(self.page_desc, "answer_explanation"):
            result += markup_to_html(page_context, self.page_desc.answer_explanation)

        return result

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        return self.process_choice_string(
                page_context,
                self.choices[permutation[choice]].text)

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        self.check_page_data(page_data)

        if answer_data is None:
            return None

        permutation = page_data["permutation"]

        unpermuted_choice = permutation[answer_data["choice"]]

        import json
        return ".json", json.dumps({
                "choices": [choice.to_json() for choice in self.choices],
                "permutation": permutation,
                "unpermuted_choice": unpermuted_choice,
                })

# }}}


# {{{ multiple choice question

class MultipleChoiceQuestion(ChoiceQuestionBase):
    """
    A page asking the participant to choose a few of multiple available answers.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``MultipleChoiceQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

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
        Choices marked with the prefix ``~DISREGARD~`` are
        ignored when determining the correctness of an answer.
        Choices marked with the prefix ``~ALWAYS_CORRECT~`` are
        marked as correct whether they are selected or not. The latter two
        exist to ensure fair scoring of a multi-select question in which one
        option has turned out to be flawed. The net effect of ``~DISREGARD~``
        is to score the question as if that option didn't exist.
        But some students may have received points from the broken option,
        so ``~DISREGARD~`` would take those points away. Cue lots of
        (somewhat justified) complaints from grumpy students.
        ``~ALWAYS_CORRECT~`` prevents that by grading any answer as
        a correct one, therefore never leading to a point decrease.

    .. attribute:: shuffle

        Optional. ``True`` or ``False``. If true, the choices will
        be presented in random order.

    .. attribute:: credit_mode

        One of the following:

        *   ``exact``: The question is scored as correct if and only if all
            check boxes match the correct solution.

        *   ``proportional``: Correctness is determined as the fraction
            of (checked or unchecked) boxes that match the value in the
            solution.

        *   ``proportional_correct``: Correctness is determined
            as the fraction of boxes that are checked in both the participant's
            answer and the solution relative to the total number of correct answers.
            Credit is only awarded if *no* incorrect answer is checked.

    .. attribute:: answer_explanation

        Text justifying the answer, written in :ref:`markup`.
    """

    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        pd = self.page_desc

        if hasattr(pd, "credit_mode"):
            credit_mode = pd.credit_mode

            if (
                    hasattr(pd, "allow_partial_credit")
                    or hasattr(pd, "allow_partial_credit_subset_only")):
                raise ValidationError(
                        string_concat(
                            "%(location)s: ",
                            _("'allow_partial_credit' or "
                            "'allow_partial_credit_subset_only' may not be specified"
                            "at the same time as 'credit_mode'"))
                        % {"location": location})

        else:

            partial = getattr(pd, "allow_partial_credit", False)
            partial_subset = getattr(pd, "allow_partial_credit_subset_only", False)

            if not partial and not partial_subset:
                credit_mode = "exact"
            elif partial and not partial_subset:
                credit_mode = "proportional"
            elif not partial and partial_subset:
                credit_mode = "proportional_correct"
            else:
                assert partial and partial_subset
                raise ValidationError(
                        string_concat(
                            "%(location)s: ",
                            _("'allow_partial_credit' and "
                            "'allow_partial_credit_subset_only' are not allowed to "
                            "coexist when both attribute are 'True'"))
                        % {"location": location})

        if credit_mode not in [
                "exact",
                "proportional",
                "proportional_correct"]:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("unrecognized credit_mode '%(credit_mode)s'"))
                    % {"location": location, "credit_mode": credit_mode})

        if vctx is not None and not hasattr(pd, "credit_mode"):
            vctx.add_warning(location,
                    _("'credit_mode' will be required on multi-select choice "
                        "questions in a future version. set "
                        "'credit_mode: {}' to match current behavior.")
                    .format(credit_mode))

        self.credit_mode = credit_mode

    def allowed_attrs(self):
        return (*super().allowed_attrs(),
            ("allow_partial_credit", bool),
            ("allow_partial_credit_subset_only", bool),
            ("credit_mode", str),
            ("answer_explanation", "markup"))

    def make_choice_form(self, page_context, page_data, page_behavior,
            *args, **kwargs):
        permutation = page_data["permutation"]

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.choices[src_i].text))
                for i, src_i in enumerate(permutation))

        form = MultipleChoiceAnswerForm(
            forms.TypedMultipleChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.CheckboxSelectMultiple(),
                required=False),
            *args, **kwargs)

        if not page_behavior.may_change_answer:
            form.fields["choice"].widget.attrs["disabled"] = True

        return form

    def answer_data(self, page_context, page_data, form, files_data):
        return {"choice": form.cleaned_data["choice"]}

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=gettext("No answer provided."))

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        disregard_idx_set = set(self.unpermuted_disregard_indices())
        always_correct_idx_set = set(self.unpermuted_always_correct_indices())
        unpermed_idx_set = (
                {permutation[idx] for idx in choice} - disregard_idx_set
                - always_correct_idx_set)
        correct_idx_set = (
                set(self.unpermuted_correct_indices()) - disregard_idx_set
                - always_correct_idx_set)
        num_choices = len(self.choices) - len(disregard_idx_set)

        if self.credit_mode == "exact":
            if unpermed_idx_set == correct_idx_set:
                correctness = 1
            else:
                correctness = 0

        elif self.credit_mode == "proportional":

            correctness = (
                    (
                        num_choices
                        - len(unpermed_idx_set
                            .symmetric_difference(correct_idx_set)))
                    / num_choices)

        else:
            assert self.credit_mode == "proportional_correct"

            correctness = (
                    (
                        len(unpermed_idx_set & correct_idx_set)
                        + len(always_correct_idx_set))
                    / (
                        len(correct_idx_set)
                        + len(always_correct_idx_set)))

            if not (unpermed_idx_set <= correct_idx_set):
                correctness = 0

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
                        self.choices[idx].text))
                    + "</li>"
                    )
        answer_html = "<ul>"+"".join(answer_html_list)+"</ul>"
        return answer_html

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        corr_idx_list = self.unpermuted_correct_indices()
        always_correct_idx_list = self.unpermuted_always_correct_indices()

        result = (string_concat(_("The correct answer is"), ": %s")
                    % self.get_answer_html(page_context, corr_idx_list))

        if len(always_correct_idx_list) > 0:
            result = (string_concat(result,
                        string_concat(_("Additional acceptable options are"),
                            ": %s")
                        % self.get_answer_html(page_context,
                            always_correct_idx_list)))

        if hasattr(self.page_desc, "answer_explanation"):
            result += markup_to_html(page_context, self.page_desc.answer_explanation)

        return result

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        return self.get_answer_html(
            page_context,
            [permutation[idx] for idx in choice],
            unpermute=True)

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        self.check_page_data(page_data)

        permutation = page_data["permutation"]

        if answer_data is None:
            return None
        else:
            unpermuted_choices = [permutation[ch] for ch in answer_data["choice"]]

        import json
        return ".json", json.dumps({
                "choices": [choice.to_json() for choice in self.choices],
                "permutation": permutation,
                "unpermuted_choices": unpermuted_choices,
                })

# }}}


# {{{ survey choice question

class SurveyChoiceQuestion(PageBaseWithTitle):
    """
    A page asking the participant to choose one of multiple answers.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``SurveyChoiceQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

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
        s = markup_to_html_plain(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        for choice_idx, choice in enumerate(page_desc.choices):
            try:
                choice = str(choice)
            except Exception:
                raise ValidationError(
                    string_concat(
                        "%(location)s, ",
                        _("choice %(idx)d: unable to convert to string")
                        )
                    % {"location": location, "idx": choice_idx+1})

            if vctx is not None:
                validate_markup(vctx, location, choice)

    def required_attrs(self):
        return (*super().required_attrs(), ("prompt", "markup"), ("choices", list))

    def allowed_attrs(self):
        return (*super().allowed_attrs(), ("answer_comment", "markup"))

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        if hasattr(self.page_desc, "answer_comment"):
            return markup_to_html(page_context, self.page_desc.answer_comment)
        else:
            return None

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def make_choice_form(self, page_context, page_data, page_behavior,
            *args, **kwargs):

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.page_desc.choices[i]))
                for i in range(len(self.page_desc.choices)))

        form = ChoiceAnswerForm(
            forms.TypedChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.RadioSelect()),
            *args, **kwargs)

        if not page_behavior.may_change_answer:
            form.fields["choice"].widget.attrs["disabled"] = True

        return form

    def make_form(self, page_context, page_data,
            answer_data, page_behavior):
        if answer_data is not None:
            form_data = {"choice": answer_data["choice"]}
            form = self.make_choice_form(
                    page_context, page_data, page_behavior, form_data)
        else:
            form = self.make_choice_form(
                    page_context, page_data, page_behavior)

        return form

    def process_form_post(self, page_context, page_data, post_data, files_data,
            page_behavior):
        return self.make_choice_form(
                    page_context, page_data, page_behavior, post_data, files_data)

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

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        import json
        return ".json", json.dumps({
                "choice": self.page_desc.choices,
                "0_based_answer": answer_data["choice"],
                })

# }}}

# vim: foldmethod=marker
