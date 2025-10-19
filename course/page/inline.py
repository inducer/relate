from __future__ import annotations


__copyright__ = "Copyright (C) 2015 Andreas Kloeckner, Dong Zhuang"

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

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Annotated, Any, ClassVar, Literal, Self, cast

import django.forms as forms
from crispy_forms.bootstrap import PrependedAppendedText
from crispy_forms.layout import HTML, Layout
from django.utils.html import format_html_join
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _
from pydantic import (
    AfterValidator,
    BaseModel,
    Discriminator,
    Field,
    NonNegativeFloat,
    ValidationInfo,
    model_validator,
)
from typing_extensions import override

from course.page.base import (
    AnswerData,
    AnswerFeedback,
    GradeData,
    PageBaseWithoutHumanGrading,
    PageBaseWithTitle,
    PageBaseWithValue,
    PageBehavior,
    PageContext,
    PageData,
    markup_to_html,
)
from course.page.choice import ChoiceDesc, ChoiceMode
from course.page.text import Matcher  # noqa: TC001
from course.validation import (
    CSSDimension,
    CSSDimensionMax,
    CSSDimensionSum,
    CSSUnit,
    IdentifierStr,
    Markup,
    get_validation_context,
    validate_nonempty,
)
from relate.utils import StyledFormBase, StyledVerticalForm, string_concat


if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from django.http import HttpRequest


# {{{ multiple text question

@dataclass(frozen=True)
class FormInfo:
    html_list: Sequence[Blank | str]
    answers: Mapping[str, AnswerBase]
    field_correctness: Mapping[str, float | None] | None = None


class InlineMultiQuestionForm(StyledVerticalForm):
    no_offset_labels: ClassVar[bool] = True
    answers: Mapping[str, AnswerBase]

    def __init__(self,
                read_only: bool,
                form_info: FormInfo,
                page_context: PageContext,
                *args, **kwargs):
        super().__init__(*args, **kwargs)
        html_list = form_info.html_list
        self.answers = answers = form_info.answers

        field_correctness = form_info.field_correctness

        self.helper.layout = Layout()

        # for question with only one field, the field is forced
        # to be "required".
        if len(answers) == 1:
            force_required = True
        else:
            force_required = False

        for t_or_b in html_list:
            if isinstance(t_or_b, Blank):
                field_name = t_or_b.identifier
                self.fields[field_name] = answers[field_name] \
                        .get_form_field(page_context, force_required=force_required)
                if field_correctness is None:
                    self.helper.layout.extend([
                            answers[field_name].get_field_layout(field_name)])
                else:
                    self.helper.layout.extend([
                            answers[field_name].get_field_layout(
                                field_name, correctness=field_correctness[field_name])])
                if read_only:
                    if isinstance(self.fields[field_name].widget,
                                  forms.widgets.Select):
                        # This will also disable the option dropdown
                        self.fields[field_name].widget.attrs["disabled"] \
                            = "disabled"
                    else:
                        # Then it should be a TextInput widget
                        self.fields[field_name].widget.attrs["readonly"] \
                            = "readonly"
            elif isinstance(t_or_b, str):
                if t_or_b:
                    self.helper.layout.append(HTML(t_or_b))
            else:
                raise AssertionError()

    @override
    def clean(self):
        cleaned_data = super().clean()

        for name in list(cleaned_data.keys()):
            answer = self.answers[name]
            if isinstance(answer, ShortAnswer):
                for i, validator in enumerate(answer.correct_answer):  # pragma: no branch  # noqa
                    try:
                        validator.validate_text(cleaned_data[name])
                    except forms.ValidationError as e:
                        if i + 1 == len(answer.correct_answer):
                            # last one, and we flunked -> not valid
                            self.add_error(name, e)
                    else:
                        # Found one that will take the input. Good enough.
                        break

        return cleaned_data


class AnswerBase(BaseModel, ABC):  # pyright: ignore[reportUnsafeMultipleInheritance]
    """
    .. autoattribute:: type
    """
    type: str

    weight: NonNegativeFloat

    prepended_text: str | None = None
    appended_text: str | None = None
    hint: str | None = None
    hint_title: str | None = None
    width: CSSDimension = Field(
                    default_factory=lambda: CSSDimension(dimension=10, unit=CSSUnit.EM))

    required: bool = False

    @abstractmethod
    def get_answer_text(self, page_context: PageContext, answer: str) -> str:
        ...

    @abstractmethod
    def get_correct_answer_text(self, page_context: PageContext) -> str:
        ...

    @abstractmethod
    def get_correctness(self, answer: str) -> float:
        ...

    def get_weighted_correctness(self, answer: str) -> float:
        if not answer:
            return 0
        return self.weight * self.get_correctness(answer)

    @abstractmethod
    def get_width_str(self,
                min_width: CSSDimension | CSSDimensionSum | None = None
            ) -> str | None:
        ...

    def get_field_layout(self, name: str, correctness: float | None = None):
        kwargs: dict[str, str | float | None] = {
            "template": "course/custom_crispy_inline_prepended_appended_text.html",
            "prepended_text": self.prepended_text or "",
            "appended_text": self.appended_text or "",
            "use_popover": "true",
            "popover_title": self.hint_title or "",
            "popover_content": self.hint or ""}
        if correctness is None:
            kwargs["style"] = self.get_width_str()
        else:
            kwargs["style"] = self.get_width_str(
                        CSSDimensionSum((self.width,
                                        CSSDimension(dimension=2, unit=CSSUnit.EM))))
            kwargs["correctness"] = correctness

        return PrependedAppendedText(name, **kwargs)  # pyright: ignore[reportArgumentType]

    @abstractmethod
    def get_form_field(self,
                page_context: PageContext,
                force_required: bool
            ) -> forms.Field:
        ...


class ShortAnswer(AnswerBase):
    type: Literal["ShortAnswer"] = "ShortAnswer"  # pyright: ignore[reportIncompatibleVariableOverride]

    correct_answer: Annotated[
        list[Matcher],
        AfterValidator(validate_nonempty)]

    @model_validator(mode="after")
    def check_has_correct_answer_text(self) -> Self:
        if all(a.correct_answer_text() is None for a in self.correct_answer):
            raise ValueError(
                _("no matcher is able to provide a plain-text correct answer"))

        return self

    @override
    def get_width_str(self,
                min_width: CSSDimension | CSSDimensionSum | None = None):
        width = self.width
        if min_width:
            width = CSSDimensionMax((width, min_width))
        return f"width: {width}"

    @override
    def get_answer_text(self, page_context: PageContext, answer: str):
        return answer

    @override
    def get_correct_answer_text(self, page_context: PageContext):
        unspec_correct_answer_text = None
        for matcher in self.correct_answer:  # pragma: no branch
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text is not None
        return ("{}{}{}".format(
                   (self.prepended_text or "").strip(),
                   unspec_correct_answer_text,
                   (self.appended_text or "").strip())
                )

    @override
    def get_correctness(self, answer: str):
        correctnesses: list[float] = [0]
        # If empty an list, sometime it will cause ValueError:
        # max() arg is an empty sequence, observed in SandBox

        for matcher in self.correct_answer:
            try:
                matcher.validate_text(answer)
            except forms.ValidationError:
                continue

            matcher_corr = matcher.grade(answer).correctness
            if matcher_corr is not None:
                correctnesses.append(matcher_corr)

        return max(correctnesses)

    @override
    def get_form_field(self, page_context: PageContext, force_required: bool):
        return forms.CharField(
                    required=self.required or force_required,
                    widget=None,
                    label=""
                )


class ChoicesAnswer(AnswerBase):
    type: Literal["ChoicesAnswer"] = "ChoicesAnswer"  # pyright: ignore[reportIncompatibleVariableOverride]

    choices: Annotated[list[ChoiceDesc], AfterValidator(validate_nonempty)]

    @model_validator(mode="after")
    def check_choice_modes(self) -> Self:
        if any(ch.mode == ChoiceMode.ALWAYS_CORRECT for ch in self.choices):
            raise ValueError(_("'always_correct' choices not allowed"))
        if any(ch.mode == ChoiceMode.DISREGARD for ch in self.choices):
            raise ValueError(_("'disregard' choices not allowed"))
        if sum(int(ch.mode == ChoiceMode.CORRECT) for ch in self.choices) < 1:
            raise ValueError(_("at least one 'correct' choice is required"))

        return self

    @classmethod
    def process_choice_string(cls, page_context: PageContext, s: str):
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    @override
    def get_answer_text(self, page_context: PageContext, answer: str):
        if answer == "":
            return answer
        return mark_safe(
            self.process_choice_string(
                page_context, self.choices[int(answer)].text))

    @override
    def get_width_str(self,
                min_width: CSSDimension | CSSDimensionSum | None = None
            ) -> str | None:
        return None

    def correct_indices(self):
        return [i for i, choice in enumerate(self.choices)
            if choice.mode == ChoiceMode.CORRECT]

    @override
    def get_correct_answer_text(self, page_context: PageContext):
        corr_idx = self.correct_indices()[0]
        return ("{}{}{}".format(
                    (self.prepended_text or "").strip(),
                    self.process_choice_string(
                        page_context, self.choices[corr_idx].text).lstrip(),
                    (self.appended_text or "").strip())
                )

    def get_max_correct_answer_len(self, page_context: PageContext):
        return max(len(answer) for answer in
            [self.process_choice_string(page_context, choice.text)
                for choice in self.choices])

    @override
    def get_correctness(self, answer: str):
        if answer == "":
            return 0
        if int(answer) in self.correct_indices():
            return 1
        return 0

    @override
    def get_form_field(self, page_context: PageContext, force_required: bool):
        choices = tuple(
            (i, self.process_choice_string(page_context, ch_i.text))
            for i, ch_i in enumerate(self.choices))
        choices = (
            (None, "-" * self.get_max_correct_answer_len(page_context)),
            *choices)
        return forms.ChoiceField(
            required=self.required or force_required,
            choices=tuple(choices),
            widget=None,
            label=""
        )


WRAPPED_NAME_RE = re.compile(r"\[\[([a-zA-Z_]\w*)\]\]")


@dataclass(frozen=True)
class Blank:
    identifier: str


def parse_question(question: str) -> list[str | Blank]:
    result: list[str | Blank] = []

    last_end = 0
    for m in WRAPPED_NAME_RE.finditer(question):
        if m.start(0) > last_end:
            result.append(question[last_end:m.start(0)])

        result.append(Blank(m.group(1)))
        last_end = m.end(0)

    trailing = question[last_end:]
    if trailing:
        result.append(trailing)

    return result


class InlineMultiQuestion(
            PageBaseWithValue,
            PageBaseWithTitle,
            PageBaseWithoutHumanGrading
        ):
    r"""
    An auto-graded page with cloze like questions.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``InlineMultiQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: question

        The body of the question, with answer fields wrapped
        by paired ``[[`` and ``]]``, written in :ref:`markup`.

    .. attribute:: answers

        Answers of the questions, written in :ref:`markup`. Each
        cloze question require an answer struct. The question now
        support cloze question of TextAnswer and ChoiceAnswer type.

    .. attribute:: answer_explanation

        Text justifying the answer, written in :ref:`markup`.

    Example:

    .. code-block:: yaml

        type: InlineMultiQuestion
        id: inlinemulti
        value: 10
        prompt: |

            # An InlineMultiQuestion example

            Complete the following paragraph.

        question: |

            Foo and [[blank1]] are often used in code examples, or
            tutorials. $\frac{1}{5}$ is equivalent to [[blank_2]].

            The correct answer for this choice question is [[choice_a]].
            The Upper case of "foo" is [[choice2]].

            One dollar is [[blank3]], and five percent is [[blank4]], and "Bar"
            wrapped by a pair of parentheses is [[blank5]].

        answers:

            blank1:
                type: ShortAnswer
                width: 4em
                required: True
                hint: Tex can be rendered in hint, e.g. $x_1$.
                hint_title: Hint
                correct_answer:
                - <plain> BAR
                - <plain>bar

            blank_2:
                type: ShortAnswer
                width: 10em
                hint: <ol><li>with no hint title</li><li>HTML is OK</li><ol>
                correct_answer:
                - <plain> "1/5"
                - type: float
                  value: 1/5
                  rtol: 0.00001
                - <plain> 0.2

            choice_a:
                type: ChoicesAnswer
                required: True
                choices:
                - ~CORRECT~ Correct
                - Wrong

            choice2:
                type: ChoicesAnswer
                choices:
                - ~CORRECT~ FOO
                - BAR
                - fOO

            blank3:
                type: ShortAnswer
                width: 3em
                prepended_text: "$"
                hint: Blank with prepended text
                correct_answer:
                - type: float
                  value: 1
                  rtol: 0.00001
                - <plain> "1"

            blank4:
                type: ShortAnswer
                width: 3em
                appended_text: "%"
                hint: Blank with appended text
                correct_answer:
                - type: float
                  value: 5
                  rtol: 0.00001
                - <plain> "5"

            blank5:
                type: ShortAnswer
                width: 6em
                prepended_text: "("
                appended_text: ")"
                required: True
                hint: Blank with both prepended and appended text
                correct_answer:
                - <plain> BAR
                - <plain>bar

    """

    type: Literal["InlineMultiQuestion"] = "InlineMultiQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]
    prompt: Markup
    question: Markup

    answer_explanation: Markup | None = None

    answers: Annotated[
        dict[IdentifierStr,
            Annotated[ShortAnswer | ChoicesAnswer, Discriminator("type")]
            ],
        AfterValidator(validate_nonempty)]

    @model_validator(mode="before")
    @classmethod
    def adjust_weights_for_backward_compat(cls, data: Any, info: ValidationInfo) -> Any:
        vctx = get_validation_context(info)

        if isinstance(data, dict) and "answers" in data:
            if not all(isinstance(ans, dict) for ans in data["answers"].values()):
                raise ValueError("answers must be dictionaries")
            answers = cast("dict[str, dict[str, object]]", data["answers"])
            new_answers: dict[str, dict[str, object]] = {}
            all_weights = [ans.get("weight") for ans in answers.values()]
            if all(w is None for w in all_weights):
                new_answers = {
                    name: {**ans, "weight": 1}
                    for name, ans in answers.items()
                }
            elif all(w is not None for w in all_weights):
                new_answers = answers
            else:
                # Only *some* answers have no weight specified
                vctx.add_warning(gettext("Only some answers provide a weight. "
                                 "This is deprecated and will stop working in 2H2026. "
                                 "For now, those answers will default to a weight of 0."
                                 "This is probably not intended.")
                                 )
                new_answers = {
                    name: {**ans, "weight": 0} if "weight" not in ans else ans
                    for name, ans in answers.items()
                }

            return {**data, "answers": new_answers}

        return data

    @model_validator(mode="after")
    def check_weight_greater_zero(self) -> Self:
        if sum(answer.weight for answer in self.answers.values()) <= 0:
            raise ValueError("sum of answer weights should be greater than zero")
        return self

    @override
    def body_attr_for_title(self) -> str:
        return "prompt"

    @model_validator(mode="after")
    def check_question_against_answers(self) -> Self:
        text_and_blanks = parse_question(self.question)

        blank_names = [
            b.identifier for b in text_and_blanks if isinstance(b, Blank)]

        blank_names_set = set(blank_names)
        if len(blank_names_set) != len(blank_names):
            raise ValueError(_("duplicate blank identifiers in question"))

        answer_names_set = set(self.answers)

        more_answers = answer_names_set - blank_names_set
        more_blanks = blank_names_set - answer_names_set

        if more_answers:
            raise ValueError(_("answers without blanks: {}")
                             .format(", ".join(more_answers)))
        if more_blanks:
            raise ValueError(_("blanks without answers: {}")
                             .format(", ".join(more_blanks)))

        for s in text_and_blanks:
            if isinstance(s, str):
                for sep in ["[[", "]]"]:
                    if sep in s:
                        raise ValueError(
                                _("stray '{}' in question text").format(sep))

        return self

    @override
    def body(self, page_context: PageContext, page_data: PageData):
        return markup_to_html(page_context, self.prompt)

    def get_question(self, page_context: PageContext):
        # for correct render of question with more than one
        # paragraph, replace <p> tags to new input-group.

        div_start_css_class_list = [
            "input-group",
            # ensure spacing between input and text, mathjax and text
            "gap-1",
            "align-items-center"
        ]

        replace_p_start = f"<div class=\"{' '.join(div_start_css_class_list)}\">"

        question_html = markup_to_html(
            page_context,
            self.question
        ).replace(
            "<p>",
            replace_p_start
        ).replace("</p>", "</div>")

        # add mb-4 class to the last paragraph so as to add spacing before
        # submit buttons.
        last_div_start = (
            f"<div class=\"{' '.join([*div_start_css_class_list, 'mb-4'])}\">")

        # https://stackoverflow.com/a/59082116/3437454
        question_html = last_div_start.join(question_html.rsplit(replace_p_start, 1))

        return question_html

    def get_form_info(self, page_context: PageContext):
        return FormInfo(
                html_list=parse_question(self.get_question(page_context)),
                answers=self.answers,
               )

    @override
    def make_form(
            self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        read_only = not page_behavior.may_change_answer

        if answer_data is not None:
            form_info = self.get_form_info(page_context)

            answer = answer_data["answer"]
            if page_behavior.show_correctness:
                field_correctness: dict[str, float | None] = {}

                for name, answer_instance in self.answers.items():
                    try:
                        field_correctness[name] = answer_instance.get_correctness(
                                answer[name])

                    # The answer doesn't exist for newly added question
                    # for pages which have been submitted.
                    except KeyError:
                        field_correctness[name] = 1

                    form_info = replace(form_info, field_correctness=field_correctness)

            form = InlineMultiQuestionForm(
                    read_only,
                    form_info,
                    page_context,
                    answer)
        else:
            answer = None
            form = InlineMultiQuestionForm(
                    read_only,
                    self.get_form_info(page_context),
                    page_context)

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
        read_only = not page_behavior.may_change_answer

        return InlineMultiQuestionForm(
                read_only,
                self.get_form_info(page_context),
                page_context,
                post_data, files_data)

    @override
    def page_correct_answer(self,
                page_context: PageContext,
                page_data: PageData,
                answer_data: AnswerData,
                grade_data: GradeData):
        # FIXME: Could use 'best' match to answer

        text_and_blanks = parse_question(self.get_question(page_context))

        snippets: list[str] = []
        for t_or_b in text_and_blanks:
            if isinstance(t_or_b, Blank):
                snippets.append(
                        "<strong>{}</strong>".format(
                            self.answers[t_or_b.identifier]
                            .get_correct_answer_text(page_context)))
            else:
                snippets.append(t_or_b)

        CA_PATTERN = string_concat(_("A correct answer is"), ": %s")  # noqa

        result = CA_PATTERN % ("".join(snippets))

        if self.answer_explanation is not None:
            result += markup_to_html(page_context, self.answer_explanation)

        return result

    @override
    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data}

    @override
    def form_to_html(
            self,
            request: HttpRequest | None,
            page_context: PageContext,
            form: StyledFormBase,
            answer_data: AnswerData,
            ):
        """Returns an HTML rendering of *form*."""

        from django.template import loader
        context: dict[str, object] = {"form": form}

        # This happens when rendering the form in analytics view.
        if not request:
            context.update({"csrf_token": "None"})

        return loader.render_to_string(
                "course/custom-crispy-inline-form.html",
                context=context,
                request=request)

    @override
    def grade(
            self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> AnswerFeedback | None:
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=gettext("No answer provided."))

        answer_dict = answer_data["answer"]

        total_weight = sum(answer.weight for answer in self.answers.values())

        correctness = sum(
            answer.get_weighted_correctness(answer_dict[name])
            for name, answer in self.answers.items()) / total_weight

        return AnswerFeedback(correctness=correctness)

    @override
    def analytic_view_body(self,
                page_context: PageContext,
                page_data: PageData):
        form = InlineMultiQuestionForm(
            False,
            self.get_form_info(page_context),
            page_context)
        return (self.body(page_context, page_data)
                + self.form_to_html(None, page_context, form, None))

    @override
    def normalized_bytes_answer(
            self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> tuple[str, bytes] | None:
        if answer_data is None:
            return None

        answer_dict = answer_data["answer"]

        result = {}
        for name, answer in self.answers.items():
            single_answer_str = (
                answer.get_answer_text(page_context, answer_dict[name]))

            # unanswered question result in "" in answer_dict
            if single_answer_str != "":
                result[name] = single_answer_str

        import json
        return ".json", json.dumps(result).encode()

    @override
    def normalized_answer(
            self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> str | None:
        if answer_data is None:
            return None

        answer_dict = answer_data["answer"]

        return format_html_join(", ", "{}",
            [(answer.get_answer_text(page_context, answer_dict[name]),)
                for name, answer in self.answers.items()]
        )

# }}}

# vim: foldmethod=marker
