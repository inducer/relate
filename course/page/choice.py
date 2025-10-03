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


from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self

import django.forms as forms
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _
from pydantic import AfterValidator, BaseModel, ConfigDict, model_validator
from typing_extensions import override

from course.page.base import (
    AnswerData,
    AnswerFeedback,
    GradeData,
    PageBaseUngraded,
    PageBaseWithoutHumanGrading,
    PageBaseWithTitle,
    PageBaseWithValue,
    PageBehavior,
    PageContext,
    PageData,
    markup_to_html,
)
from course.validation import Markup, validate_nonempty
from relate.utils import StyledFormBase, StyledVerticalForm, string_concat


# {{{ data model/validation

class ChoiceMode(StrEnum):
    INCORRECT = "incorrect"
    CORRECT = "correct"
    DISREGARD = "disregard"
    ALWAYS_CORRECT = "always_correct"


class ChoiceDesc(BaseModel):
    tag_to_mode: ClassVar[dict[str, ChoiceMode]] = {
        "~CORRECT~": ChoiceMode.CORRECT,
        "~DISREGARD~": ChoiceMode.DISREGARD,
        "~ALWAYS_CORRECT~": ChoiceMode.ALWAYS_CORRECT,
    }

    model_config: ClassVar[ConfigDict] = ConfigDict(
                                    use_enum_values=True, extra="forbid")

    mode: ChoiceMode
    text: Markup

    @model_validator(mode="before")
    @classmethod
    def normalize_str_to_dict(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return data

        try:
            data = str(data)
        except Exception:
            pass
        else:

            choice_mode: ChoiceMode | None = None

            def mode_from_prefix(s: str):
                nonlocal choice_mode

                for prefix, mode in cls.tag_to_mode.items():
                    if s.startswith(prefix):
                        s = s[len(prefix):].strip()

                        if choice_mode is not None:
                            raise ValueError(
                                    _("more than one choice mode encountered"))

                        choice_mode = mode
                        s = mode_from_prefix(s)
                return s

            s = mode_from_prefix(data)

            if choice_mode is None:
                choice_mode = ChoiceMode.INCORRECT

            return {"mode": str(choice_mode), "text": s}

        return data


class CreditMode(StrEnum):
    """
    *   ``exact``: The question is scored as correct if and only if all
        check boxes match the correct solution.

    *   ``proportional``: Correctness is determined as the fraction
        of (checked or unchecked) boxes that match the value in the
        solution.

    *   ``proportional_correct``: Correctness is determined
        as the fraction of boxes that are checked in both the participant's
        answer and the solution relative to the total number of correct answers.
        Credit is only awarded if *no* incorrect answer is checked.
    """

    EXACT = "exact"
    PROPORTIONAL = "proportional"
    PROPORTIONAL_CORRECT = "proportional_correct"

# }}}


# {{{ forms

class ChoiceAnswerForm(StyledVerticalForm):
    def __init__(self, field, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["choice"] = field
        # Translators: "choice" in Choice Answer Form in a single-choice question.
        self.fields["choice"].label = _("Choice")


class MultipleChoiceAnswerForm(StyledVerticalForm):
    def __init__(self, field, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["choice"] = field

        # Translators: "Choice" in Choice Answer Form in a multiple
        # choice question in which multiple answers can be chosen.
        self.fields["choice"].label = _("Select all that apply:")

# }}}


# {{{ choice question base

class ChoiceQuestionBase(PageBaseWithTitle, PageBaseWithValue, ABC):
    prompt: Markup
    choices: Annotated[list[ChoiceDesc], AfterValidator(validate_nonempty)]

    shuffle: bool = False
    answer_explanation: Markup | None = None

    @override
    def body_attr_for_title(self) -> str:
        return "prompt"

    @classmethod
    def process_choice_string(cls, page_context: PageContext, s: str):
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    @override
    def body(self, page_context: PageContext, page_data: PageData) -> str:
        return markup_to_html(page_context, self.prompt)

    def initialize_page_data(self, page_context):
        import random
        perm = list(range(len(self.choices)))
        if getattr(self, "shuffle", False):
            random.shuffle(perm)

        return {"permutation": perm}

    def check_page_data(self, page_data: PageData):
        if (
                "permutation" not in page_data
                or (set(page_data["permutation"])
                    != set(range(len(self.choices))))):
            from course.page import InvalidPageData
            raise InvalidPageData(gettext(
                "existing choice permutation not "
                "suitable for number of choices in question"))

    def unpermuted_indices_with_mode(self, mode: ChoiceMode):
        return [i for i, choice in enumerate(self.choices)
                if choice.mode == mode]

    def unpermuted_correct_indices(self):
        return self.unpermuted_indices_with_mode(ChoiceMode.CORRECT)

    def unpermuted_disregard_indices(self):
        return self.unpermuted_indices_with_mode(ChoiceMode.DISREGARD)

    def unpermuted_always_correct_indices(self):
        return self.unpermuted_indices_with_mode(ChoiceMode.ALWAYS_CORRECT)

    @abstractmethod
    def make_choice_form(self,
                page_context: PageContext,
                page_data: PageData,
                page_behavior: PageBehavior,
                *args,
                **kwargs
            ) -> StyledFormBase: ...

    @override
    def make_form(self,
                page_context: PageContext,
                page_data: PageData,
                answer_data: AnswerData,
                page_behavior: PageBehavior):
        self.check_page_data(page_data)

        if answer_data is not None:
            form_data = {"choice": answer_data["choice"]}
            form = self.make_choice_form(
                    page_context, page_data, page_behavior, form_data)
        else:
            form = self.make_choice_form(
                    page_context, page_data, page_behavior)

        return form

    @override
    def process_form_post(self,
            page_context: PageContext,
            page_data: PageData,
            post_data: Any,
            files_data: Any,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        return self.make_choice_form(
                    page_context, page_data, page_behavior, post_data, files_data)

# }}}


# {{{ choice question

class ChoiceQuestion(ChoiceQuestionBase, PageBaseWithoutHumanGrading):
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
    type: Literal["ChoiceQuestion"]  = "ChoiceQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    @model_validator(mode="after")
    def check_choice_modes(self) -> Self:
        if any(ch.mode == ChoiceMode.ALWAYS_CORRECT for ch in self.choices):
            raise ValueError(_("'always_correct' choices not allowed"))
        if any(ch.mode == ChoiceMode.DISREGARD for ch in self.choices):
            raise ValueError(_("'disregard' choices not allowed"))
        if sum(int(ch.mode == ChoiceMode.CORRECT) for ch in self.choices) < 1:
            raise ValueError(_("at least one 'correct' choice is required"))

        return self

    @override
    def make_choice_form(self,
                page_context: PageContext,
                page_data: PageData,
                page_behavior: PageBehavior,
                *args,
                **kwargs):
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

    @override
    def answer_data(self,
            page_context: PageContext,
            page_data: PageData,
            form: forms.Form,
            files_data: Any,
            ) -> AnswerData:
        return {"choice": form.cleaned_data["choice"]}

    @override
    def grade(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> AnswerFeedback | None:
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

    @override
    def page_correct_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> str | None:
        corr_idx = self.unpermuted_correct_indices()[0]
        result = (string_concat(_("A correct answer is"), ": %s")
                % self.process_choice_string(
                    page_context,
                    self.choices[corr_idx].text))

        if self.answer_explanation is not None:
            result += markup_to_html(page_context, self.answer_explanation)

        return result

    @override
    def normalized_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> str | None:
        if answer_data is None:
            return None

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        return self.process_choice_string(
                page_context,
                self.choices[permutation[choice]].text)

    @override
    def normalized_bytes_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> tuple[str, bytes] | None:
        self.check_page_data(page_data)

        if answer_data is None:
            return None

        permutation = page_data["permutation"]

        unpermuted_choice = permutation[answer_data["choice"]]

        import json
        return ".json", json.dumps({
                "choices": [ch.model_dump() for ch in self.choices],
                "permutation": permutation,
                "unpermuted_choice": unpermuted_choice,
                }).encode()

# }}}


# {{{ multiple choice question

class MultipleChoiceQuestion(ChoiceQuestionBase, PageBaseWithoutHumanGrading):
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

    .. attribute:: answer_explanation

        Text justifying the answer, written in :ref:`markup`.
    """

    type: Literal["MultipleChoiceQuestion"] = "MultipleChoiceQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    model_config: ClassVar[ConfigDict] = ConfigDict(use_enum_values=True)

    credit_mode: CreditMode

    @override
    def make_choice_form(self,
                page_context: PageContext,
                page_data: PageData,
                page_behavior: PageBehavior,
                *args,
                **kwargs):
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

    @override
    def answer_data(self,
            page_context: PageContext,
            page_data: PageData,
            form: forms.Form,
            files_data: Any,
            ) -> Any:
        return {"choice": form.cleaned_data["choice"]}

    @override
    def grade(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> AnswerFeedback | None:
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

        correctness: float
        if self.credit_mode == CreditMode.EXACT:
            if unpermed_idx_set == correct_idx_set:
                correctness = 1
            else:
                correctness = 0

        elif self.credit_mode == CreditMode.PROPORTIONAL:

            correctness = (
                    (
                        num_choices
                        - len(unpermed_idx_set
                            .symmetric_difference(correct_idx_set)))
                    / num_choices)

        else:
            assert self.credit_mode == CreditMode.PROPORTIONAL_CORRECT

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

    def get_answer_html(self, page_context: PageContext, idx_list, unpermute=False):
        if unpermute:
            idx_list = list(set(idx_list))

        return format_html_join(
            "\n", "{}",
            [(self.process_choice_string(
                        page_context,
                        self.choices[idx].text),)
            for idx in idx_list])

    @override
    def page_correct_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> str | None:
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

        if self.answer_explanation is not None:
            result += markup_to_html(page_context, self.answer_explanation)

        return result

    @override
    def normalized_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> str | None:
        if answer_data is None:
            return None

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        return self.get_answer_html(
            page_context,
            [permutation[idx] for idx in choice],
            unpermute=True)

    @override
    def normalized_bytes_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> tuple[str, bytes] | None:
        self.check_page_data(page_data)

        permutation = page_data["permutation"]

        if answer_data is None:
            return None
        else:
            unpermuted_choices = [permutation[ch] for ch in answer_data["choice"]]

        import json
        return ".json", json.dumps({
                "choices": [ch.model_dump() for ch in self.choices],
                "permutation": permutation,
                "unpermuted_choices": unpermuted_choices,
                }).encode()

# }}}


# {{{ survey choice question

class SurveyChoiceQuestion(PageBaseWithTitle, PageBaseUngraded):
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

    type: Literal["SurveyChoiceQuestion"] = "SurveyChoiceQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    prompt: Markup
    choices: list[str]

    answer_comment: Markup | None = None

    @override
    def body_attr_for_title(self) -> str:
        return "prompt"

    @classmethod
    def process_choice_string(cls, page_context: PageContext, s: str):
        if not isinstance(s, str):
            s = str(s)
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    @override
    def page_correct_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> str | None:
        if self.answer_comment:
            return markup_to_html(page_context, self.answer_comment)
        else:
            return None

    def markup_body_for_title(self):
        return self.prompt

    @override
    def body(self, page_context: PageContext, page_data: PageData):
        return markup_to_html(page_context, self.prompt)

    def make_choice_form(self,
                page_context: PageContext,
                page_data: PageData,
                page_behavior: PageBehavior,
                *args,
                **kwargs):

        choices = tuple(
                (i,  self.process_choice_string(
                    page_context, self.choices[i]))
                for i in range(len(self.choices)))

        form = ChoiceAnswerForm(
            forms.TypedChoiceField(
                choices=tuple(choices),
                coerce=int,
                widget=forms.RadioSelect()),
            *args, **kwargs)

        if not page_behavior.may_change_answer:
            form.fields["choice"].widget.attrs["disabled"] = True

        return form

    @override
    def make_form(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        if answer_data is not None:
            form_data = {"choice": answer_data["choice"]}
            form = self.make_choice_form(
                    page_context, page_data, page_behavior, form_data)
        else:
            form = self.make_choice_form(
                    page_context, page_data, page_behavior)

        return form

    @override
    def process_form_post(self,
            page_context: PageContext,
            page_data: PageData,
            post_data: Any,
            files_data: Any,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        return self.make_choice_form(
                    page_context, page_data, page_behavior, post_data, files_data)

    @override
    def answer_data(self,
            page_context: PageContext,
            page_data: PageData,
            form: forms.Form,
            files_data: Any,
            ) -> AnswerData:
        return {"choice": form.cleaned_data["choice"]}

    @override
    def expects_answer(self):
        return True

    @override
    def is_answer_gradable(self):
        return False

    @override
    def normalized_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> str | None:
        if answer_data is None:
            return None

        choice = answer_data["choice"]

        return self.process_choice_string(
                page_context,
                self.choices[choice])

    @override
    def normalized_bytes_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> tuple[str, bytes] | None:
        if answer_data is None:
            return None

        import json
        return ".json", json.dumps({
                "choice": self.choices,
                "0_based_answer": answer_data["choice"],
                }).encode()

# }}}

# vim: foldmethod=marker
