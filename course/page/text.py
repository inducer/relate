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

import re
from abc import ABC, abstractmethod
from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Literal,
    Self,
    TypeAlias,
)

import django.forms as forms
from django.utils.translation import gettext, gettext_lazy as _
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)
from pytools import memoize_method, not_none
from typing_extensions import override

from course.page.base import (
    AnswerData,
    AnswerFeedback,
    GradeData,
    PageBase,
    PageBaseUngraded,
    PageBaseWithCorrectAnswer,
    PageBaseWithHumanTextFeedback,
    PageBaseWithoutHumanGrading,
    PageBaseWithTitle,
    PageBaseWithValue,
    PageBehavior,
    PageContext,
    PageData,
    get_editor_interaction_mode,
    markup_to_html,
)
from course.repo import EmptyRepo
from course.validation import (
    Markup,
    PointCount,
    ValidationContext,
    validate_nonempty,
)
from relate.utils import (
    StyledFormBase,
    StyledVerticalForm,
    string_concat,
)


if TYPE_CHECKING:
    from collections.abc import Sequence


CORRECT_ANSWER_PATTERN = string_concat(_("A correct answer is"), ": '%s'.")


def parse_sympy(s: float | str):
    if isinstance(s, (complex, float, int)):
        from sympy import sympify
        return sympify(s)

    from pymbolic import parse
    from pymbolic.interop.sympy import PymbolicToSympyMapper

    # use pymbolic because it has a semi-secure parser
    return PymbolicToSympyMapper()(parse(s))


# {{{ data model/validation

class WidgetType(StrEnum):
    TEXT_INPUT = "text_input"
    TEXTAREA = "textarea"
    EDITOR = "editor"


class WidgetDesc(BaseModel):
    type: WidgetType = WidgetType.TEXT_INPUT
    language: str | None = None

    model_config: ClassVar[ConfigDict] = ConfigDict(
                                use_enum_values=True, extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def normalize_to_dict(cls, data: Any) -> Any:
        if data is None:
            return {"type": "text_input", "language": None}
        if isinstance(data, str):
            if ":" in data:
                tp, lang, *rest = data.split(":")
                if rest:
                    raise ValueError("more than one colon found")
            else:
                tp = data
                lang = None

            return {"type": WidgetType(tp), "language": lang}
        return data


def float_or_sympy_evalf(s: str | float) -> float:
    if isinstance(s, int | float):
        return s

    if not isinstance(s, str):
        raise TypeError("expected string, int or float for floating point "
                "literal")

    try:
        return float(s)
    except ValueError:
        pass

    if s == "":
        raise ValueError("floating point value expected, empty string found")

    # return a float type value, expression not allowed
    return float(parse_sympy(s).evalf())


def _validate_float_expr(s: float | str):
    float_or_sympy_evalf(s)
    return s


FloatExpression: TypeAlias = Annotated[
        float | str,
        AfterValidator(_validate_float_expr)]


RegexFlag: TypeAlias = Literal[
            "A", "ASCII", "DOTALL", "I", "IGNORECASE", "M", "MULTILINE", "S",
            "U", "UNICODE", "VERBOSE", "X",
            # omitted, grade should be locale-independent
            # "L", "LOCALE"
        ]


def _validate_sympy_parseable(s: float | str) -> float | str:
    parse_sympy(s)
    return s


ExpressionStr: TypeAlias = Annotated[
            float | str,
            AfterValidator(_validate_sympy_parseable)
        ]

# }}}


class TextAnswerForm(StyledVerticalForm):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    @staticmethod
    def get_text_widget(
                widget_type: WidgetDesc,
                read_only: bool = False,
                interaction_mode: str | None = None,
                initial_text: str | None = None):
        """Returns None if no widget found."""

        help_text = None
        widget: forms.Widget
        if widget_type.type == WidgetType.TEXT_INPUT:
            widget = forms.TextInput()

        elif widget_type.type == WidgetType.TEXTAREA == "textarea":
            widget = forms.Textarea()

        elif widget_type.type == WidgetType.EDITOR:
            from course.utils import get_codemirror_widget
            widget, help_text = get_codemirror_widget(
                    language_mode=widget_type.language,
                    interaction_mode=interaction_mode)

        else:
            return None, None

        widget.attrs["autofocus"] = None
        if read_only:
            widget.attrs["readonly"] = None
        return widget, help_text

    def __init__(self, *args: object,
            read_only: bool,
            widget_type: WidgetDesc,
            interaction_mode: str,
            initial_text: str | None,
            validators: Sequence[TextValidatorBase | TextAnswerMatcher],
            **kwargs: object):

        super().__init__(*args, **kwargs)
        widget, help_text = self.get_text_widget(
                    widget_type, read_only,
                    interaction_mode=interaction_mode)
        self.validators = validators
        self.fields["answer"] = forms.CharField(
                required=True,
                initial=initial_text,
                widget=widget,
                help_text=help_text,
                label=_("Answer"))

    def clean(self):
        cleaned_data = super().clean()

        answer = cleaned_data.get("answer", "")
        for i, validator in enumerate(self.validators):
            try:
                validator.validate_text(answer)
            except forms.ValidationError:
                if i + 1 == len(self.validators):
                    # last one, and we flunked -> not valid
                    raise
            else:
                # Found one that will take the input. Good enough.
                break


# {{{ validators

class TextValidatorBase(BaseModel, ABC):  # pyright: ignore[reportUnsafeMultipleInheritance]
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    type: str

    @abstractmethod
    def validate_text(self, s: str, /) -> None:
        ...


class NoopValidator(TextValidatorBase):
    # This exists because discriminated unions must have two entries in pydantic.
    type: Literal["noop"]  # pyright: ignore[reportIncompatibleVariableOverride]

    @override
    def validate_text(self, new_page_source: str):
        pass


class RELATEPageValidator(TextValidatorBase):
    type: Literal["relate_page"] = "relate_page"  # pyright: ignore[reportIncompatibleVariableOverride]
    page_type: str

    @override
    def validate_text(self, new_page_source: str):
        import yaml

        try:
            page = PageBase.model_validate(
                        yaml.safe_load(new_page_source),
                        context=ValidationContext(repo=EmptyRepo(),
                                                  commit_sha=b"(NO REVSISION)"))

            if page.type != self.page_type:
                raise ValueError(gettext("page must be of type '%s'")
                        % self.page_type)

        except Exception as e:
            raise forms.ValidationError(f"{type(e).__name__}: {e!s}")


TextValidator: TypeAlias = Annotated[
        NoopValidator |
        RELATEPageValidator,
        Field(discriminator="type"),
]

# }}}


# {{{ matchers

MATCHER_RE = re.compile(r"^\<([a-zA-Z0-9_:.]+)\>(.*)$")


class TextAnswerMatcher(ABC, BaseModel):  # pyright: ignore[reportUnsafeMultipleInheritance]
    """Abstract interface for matching text answers.

    .. attribute:: type
    .. attribute:: is_case_sensitive

        Only used for answer normalization. Matchers are responsible for
        case sensitivity themselves.
    """
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    type: str
    correctness: PointCount = 1
    feedback: str | None = None

    @abstractmethod
    def validate_text(self, s: str):
        """Called to validate form input against simple input mistakes.

        Should raise :exc:`django.forms.ValidationError` on error.
        """
        ...

    @abstractmethod
    def grade(self, s: str) -> AnswerFeedback:
        raise NotImplementedError()

    @abstractmethod
    def correct_answer_text(self) -> str | None:
        raise NotImplementedError()

    @property
    @abstractmethod
    def is_case_sensitive(self) -> bool:
        ...


EXTRA_SPACES_RE = re.compile(r"\s\s+")


def multiple_to_single_spaces(s: str):
    return EXTRA_SPACES_RE.sub(" ", s).strip()


class CaseSensitivePlainMatcher(TextAnswerMatcher):
    type: Literal["case_sens_plain"] = "case_sens_plain"  # pyright: ignore[reportIncompatibleVariableOverride]

    value: str

    @override
    def validate_text(self, s: str):
        pass

    @override
    def grade(self, s: str):
        if multiple_to_single_spaces(self.value) == multiple_to_single_spaces(s):
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    @override
    def correct_answer_text(self):
        if self.correctness >= 1:
            return self.value
        else:
            return None

    @property
    @override
    def is_case_sensitive(self) -> bool:
        return True


class PlainMatcher(CaseSensitivePlainMatcher):
    type: Literal["plain"] = "plain"  # type: ignore[assignment] # pyright: ignore[reportIncompatibleVariableOverride]

    @override
    def grade(self, s: str):
        if (multiple_to_single_spaces(self.value.lower())
                == multiple_to_single_spaces(s.lower())):
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    @property
    @override
    def is_case_sensitive(self) -> bool:
        return False


class RegexMatcher(TextAnswerMatcher):
    type: Literal["regex", "case_sens_regex"] = "regex"  # pyright: ignore[reportIncompatibleVariableOverride]

    value: str
    flags: list[RegexFlag] | None = None

    @model_validator(mode="after")
    def check_valid_regex(self) -> Self:
        try:
            re.compile(self.value, self.regex_flags)
        except Exception as e:
            raise ValueError(_("not a valid regular expression: {}: {}")
                             .format(type(e).__name__, str(e)))
        return self

    @override
    def validate_text(self, s: str):
        # FIXME: Could have a validation regex
        pass

    @property
    @memoize_method
    def regex_flags(self):
        if self.type == "case_sens_regex":
            if self.flags is not None:
                raise ValueError("cannot specify flags with case_sens_regex")
            return 0

        if self.flags is None:
            return re.IGNORECASE
        else:
            re_flags = 0
            for flag in self.flags:
                re_flags |= getattr(re, flag)
            return re_flags

    @override
    def grade(self, s: str):
        regex = re.compile(self.value, self.regex_flags)

        match = regex.match(s)
        if match is not None:
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    @override
    def correct_answer_text(self):
        return None

    @property
    @override
    def is_case_sensitive(self) -> bool:
        if self.flags is None:
            return False
        else:
            return "I" in self.flags or "IGNORECASE" in self.flags


class SymbolicExpressionMatcher(TextAnswerMatcher):
    type: Literal["sym_expr"] = "sym_expr"  # pyright: ignore[reportIncompatibleVariableOverride]

    value: ExpressionStr

    @override
    def validate_text(self, s: str):
        try:
            parse_sympy(s)
        except Exception as e:
            raise forms.ValidationError(f"{type(e).__name__}: {e!s}")

    @override
    def grade(self, s: str):
        try:
            answer_sym = parse_sympy(s)
        except Exception:
            return AnswerFeedback(0)

        from sympy import simplify
        try:
            simp_result = simplify(answer_sym - parse_sympy(self.value))
        except Exception:
            return AnswerFeedback(0)

        if simp_result == 0:
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    @override
    def correct_answer_text(self):
        if self.correctness >= 1:
            return str(self.value)
        else:
            return None

    @property
    @override
    def is_case_sensitive(self) -> bool:
        return True


class FloatMatcher(TextAnswerMatcher):
    type: Literal["float"] = "float"  # pyright: ignore[reportIncompatibleVariableOverride]

    value: FloatExpression

    rtol: FloatExpression | None = None
    atol: FloatExpression | None = None

    @model_validator(mode="after")
    def check_tolerances(self) -> Self:
        value = float_or_sympy_evalf(self.value)
        if value == 0 and self.rtol is not None:
            raise ValueError(_("'rtol' not allowed when 'value' is zero"))

        if self.atol is None and self.rtol is None:
            raise ValueError(
                    gettext("Float match should have either rtol or atol--"
                        "otherwise it will match any number"))

        return self

    @override
    def validate_text(self, s: str):
        try:
            float_or_sympy_evalf(s)
        except Exception as e:
            raise forms.ValidationError(f"{type(e).__name__}: {e!s}")

    @override
    def grade(self, s: str):
        try:
            answer_float = float_or_sympy_evalf(s)
        except Exception:
            # Should not happen, no need to give verbose feedback.
            return AnswerFeedback(0)

        good_afb = AnswerFeedback(self.correctness, self.feedback)
        bad_afb = AnswerFeedback(0)

        value = float_or_sympy_evalf(self.value)

        from math import isinf, isnan
        if isinf(value):
            return good_afb if isinf(answer_float) else bad_afb
        if isnan(value):
            return good_afb if isnan(answer_float) else bad_afb
        if isinf(answer_float) or isnan(answer_float):
            return bad_afb

        if self.atol is not None:
            atol = float_or_sympy_evalf(self.atol)
            if (abs(answer_float - value) > atol):
                return bad_afb
        if self.rtol is not None:
            rtol = float_or_sympy_evalf(self.rtol)
            if abs(answer_float - value) / abs(value) > rtol:
                return bad_afb

        return good_afb

    @override
    def correct_answer_text(self):
        if self.correctness >= 1:
            return str(self.value)
        else:
            return None

    @property
    @override
    def is_case_sensitive(self) -> bool:
        return False


def normalize_matcher_to_dict(data: Any) -> Any:
    if isinstance(data, str):
        match = MATCHER_RE.match(data)

        if match is not None:
            return {
                "type": match.group(1),
                "value": match.group(2),
                }
    return data


Matcher: TypeAlias = Annotated[
        CaseSensitivePlainMatcher |
        PlainMatcher |
        RegexMatcher |
        SymbolicExpressionMatcher |
        FloatMatcher,
        Field(discriminator="type"),
        BeforeValidator(normalize_matcher_to_dict,)
]

# }}}


# {{{ text question base

class TextQuestionBase(PageBaseWithTitle, ABC):
    """
    A page asking for a textual answer

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``TextQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: widget

        |text-widget-page-attr|

    .. attribute:: initial_text

        Text with which to prepopulate the input widget.
    """
    prompt: Markup
    widget: WidgetDesc = Field(
        default_factory=lambda: WidgetDesc(type=WidgetType.TEXT_INPUT, language=None))

    initial_text: str | None = None

    @override
    def body_attr_for_title(self) -> str:
        return "prompt"

    @override
    def body(self, page_context: PageContext, page_data: PageData) -> str:
        return markup_to_html(page_context, self.prompt)

    @abstractmethod
    def get_validators(self) -> Sequence[TextValidatorBase | TextAnswerMatcher]:
        ...

    @override
    def make_form(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:

        kwargs = {}

        if answer_data is not None:
            kwargs.update({"data": {"answer": answer_data["answer"]}})

        return TextAnswerForm(
            read_only=not page_behavior.may_change_answer,
            widget_type=self.widget,
            interaction_mode=get_editor_interaction_mode(page_context),
            validators=self.get_validators(),
            initial_text=self.initial_text,
            **kwargs)

    @override
    def process_form_post(self,
            page_context: PageContext,
            page_data: PageData,
            post_data: Any,
            files_data: Any,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        return TextAnswerForm(
                post_data, files_data,
                read_only=not page_behavior.may_change_answer,
                interaction_mode=get_editor_interaction_mode(page_context),
                validators=self.get_validators(),
                widget_type=self.widget,
                initial_text=self.initial_text)

    @override
    def answer_data(self,
            page_context: PageContext,
            page_data: PageData,
            form: forms.Form,
            files_data: Any,
            ) -> AnswerData:
        return {"answer": form.cleaned_data["answer"].strip()}

    def _is_case_sensitive(self) -> bool:
        return True

    @override
    def normalized_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> str | None:
        if answer_data is None:
            return None

        normalized_answer = answer_data["answer"]

        if not self._is_case_sensitive():
            normalized_answer = normalized_answer.lower()

        return normalized_answer

    @override
    def normalized_bytes_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData,
            ) -> tuple[str, bytes] | None:
        if answer_data is None:
            return None

        return (".txt", answer_data["answer"].encode("utf-8"))

# }}}


# {{{ survey text question

class SurveyTextQuestion(TextQuestionBase, PageBaseUngraded):
    """
    A page asking for a textual answer, without any notion of 'correctness'

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``SurveyTextQuestion``

    .. attribute:: is_optional_page

        |is-optional-page-attr|

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: widget

        |text-widget-page-attr|

    .. attribute:: initial_text

        Text with which to prepopulate the input widget.

    .. attribute:: answer_comment

        A comment that is shown in the same situations a 'correct answer' would
        be.
    """
    type: Literal["SurveyTextQuestion"] = "SurveyTextQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    answer_comment: Markup | None = None

    @override
    def get_validators(self):
        return []

    @override
    def page_correct_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> str | None:
        if self.answer_comment is not None:
            return markup_to_html(page_context, self.answer_comment)
        else:
            return None

    @override
    def expects_answer(self):
        return True

# }}}


# {{{ text question

class TextQuestion(TextQuestionBase, PageBaseWithValue, PageBaseWithoutHumanGrading):
    """
    A page asking for a textual answer.

    Example:

    .. code-block:: yaml

        type: TextQuestion
        id: fwd_err
        prompt: |
            # Forward Error
            Consider the function $f(x)=1/x$, which we approximate by its Taylor
            series about 1:
            $$
              f(x)\\approx 1-(x-1)+\\cdots
            $$
            What is the **forward error** of using this approximation at $x=0.5$?
        answers:
        -   type: float
            value: 0.5
            rtol: 0.01
        -   <plain>HI THERE
        answer_explanation: |

            That's just what it is.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``TextQuestion``

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

    .. attribute:: widget

        |text-widget-page-attr|

    .. attribute:: initial_text

        Text with which to prepopulate the input widget.

    .. attribute:: answers

        A list of answers. Each answer consists of a 'matcher'
        and an answer template for that matcher to use. Each type of matcher
        requires one of two syntax variants to be used. The
        'simple/abbreviated' syntax::

            - <plain>some_text

        or the 'structured' syntax::

            - type: float
              value: 1.25
              rtol: 0.2

              # All structured-form matchers allow (but do not require) these:
              correctness: 0.5
              feedback: "Close, but not quite"

        If ``correctness`` is not explicitly given, the answer is considered
        fully correct. The ``answers`` list of answers is evaluated in order.
        The first applicable matcher yielding the highest correctness value
        will determine the result shown to the user.

        Here are examples of all the supported simple/abbreviated matchers:

        - ``<plain>some_text`` Matches exactly ``some_text``, in a
          case-insensitive manner.
          (i.e. capitalization does not matter)

        - ``<case_sens_plain>some_text`` Matches exactly ``some_text``, in a
          case-sensitive manner.
          (i.e. capitalization matters)

        - ``<regex>[a-z]+`` Matches anything matched by the given
          (Python-style) regular expression that
          follows. Case-insensitive, i.e. capitalization does not matter.

        - ``<sym_expr>x+2*y`` Matches anything that :mod:`sympy` considers
          equivalent to the given expression. Equivalence is determined
          by simplifying ``user_answer - given_expr`` and testing the result
          against 0 using :mod:`sympy`.

        Each simple matcher may also be given in structured form, e.g.::

            -   type: sym_expr
                value: x+2*y

        Additionally, the following structured-only matchers exist:

        - Floating point. Example::

              -   type: float
                  value: 1.25
                  rtol: 0.2  # relative tolerance
                  atol: 0.2  # absolute tolerance

        - Regular expression. Example::

              -   type: regex
                  value: [a-z]+
                  flags: [IGNORECASE, DOTALL]  # see python regex documentation
                  # if not given, defaults to "[IGNORECASE]"

    .. attribute:: answer_explanation

        Text justifying the answer, written in :ref:`markup`.
    """

    type: Literal["TextQuestion"] = "TextQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    answers: Annotated[list[Matcher], AfterValidator(validate_nonempty)]
    answer_explanation: Markup | None = None

    @model_validator(mode="after")
    def check_has_correct_answer_text(self) -> Self:
        if all(a.correct_answer_text() is None for a in self.answers):
            raise ValueError(
                _("no matcher is able to provide a plain-text correct answer"))

        return self

    @override
    def get_validators(self):
        return self.answers

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

        answer = answer_data["answer"]

        # Must start with 'None' to allow matcher to set feedback for zero
        # correctness.
        afb = None

        for matcher in self.answers:
            try:
                matcher.validate_text(answer)
            except forms.ValidationError:
                continue

            matcher_afb = matcher.grade(answer)
            if matcher_afb.correctness is not None:
                if afb is None:
                    afb = matcher_afb
                elif matcher_afb.correctness > not_none(afb.correctness):
                    afb = matcher_afb

        if afb is None:
            afb = AnswerFeedback(0)

        return afb

    @override
    def page_correct_answer(self,
            page_context: PageContext,
            page_data: PageData,
            answer_data: AnswerData | None,
            grade_data: GradeData | None,
            ) -> str | None:
        # FIXME: Could use 'best' match to answer

        unspec_correct_answer_text = None
        for matcher in self.answers:  # pragma: no branch
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text

        result = CORRECT_ANSWER_PATTERN % unspec_correct_answer_text

        if self.answer_explanation is not None:
            result += markup_to_html(page_context, self.answer_explanation)

        return result

    @override
    def _is_case_sensitive(self):
        return any(matcher.is_case_sensitive for matcher in self.answers)

# }}}


# {{{ human-graded text question

class HumanGradedTextQuestion(TextQuestionBase, PageBaseWithValue,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):
    """
    A page asking for a textual answer, with human-graded feedback.

    Supports automatic computation of point values from textual feedback.
    See :ref:`points-from-feedback`.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``HumanGradedTextQuestion``

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

    .. attribute:: widget

        |text-widget-page-attr|

    .. attribute:: initial_text

        Text with which to prepopulate the input widget.

    .. attribute:: validators

        Optional.
        TODO

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.

    .. attribute:: rubric

        Required.
        The grading guideline for this question, in :ref:`markup`.
    """
    type: Literal["HumanGradedTextQuestion"] = "HumanGradedTextQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    validators: list[TextValidator] = Field(default_factory=list)

    @override
    def human_feedback_point_value(self,
                page_context: PageContext,
                page_data: PageData):
        return self.max_points(page_data)

    @override
    def get_validators(self):
        return self.validators

# }}}


# {{{ rich text

class RichTextAnswerForm(StyledVerticalForm):
    def __init__(self, read_only: bool, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        from course.utils import ProseMirrorTextarea
        self.fields["answer"] = forms.JSONField(
                required=True,
                widget=ProseMirrorTextarea(attrs={"readonly": read_only}),
                help_text=ProseMirrorTextarea.math_help_text,
                label=_("Answer"))


class HumanGradedRichTextQuestion(PageBaseWithValue, PageBaseWithTitle,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):
    """
    A page asking for a textual answer, with human-graded feedback.

    Supports automatic computation of point values from textual feedback.
    See :ref:`points-from-feedback`.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``HumanGradedRichTextQuestion``

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

    .. attribute:: correct_answer

        Optional.
        Content that is revealed when answers are visible
        (see :ref:`flow-permissions`). Written in :ref:`markup`.

    .. attribute:: rubric

        Required.
        The grading guideline for this question, in :ref:`markup`.
    """
    type: Literal["HumanGradedRichTextQuestion"] = "HumanGradedRichTextQuestion"  # pyright: ignore[reportIncompatibleVariableOverride]

    prompt: Markup

    @override
    def body(self, page_context: PageContext, page_data: Any) -> str:
        return markup_to_html(page_context, self.prompt)

    @override
    def body_attr_for_title(self) -> str:
        return "prompt"

    @override
    def human_feedback_point_value(self,
                page_context: PageContext,
                page_data: PageData
            ) -> float:
        return self.max_points(page_data)

    @override
    def make_form(
            self,
            page_context: PageContext,
            page_data: Any,
            answer_data: Any,
            page_behavior: Any,
            ) -> StyledFormBase:
        kwargs = {}

        if answer_data is not None:
            from json import dumps
            kwargs.update({"data": {"answer": dumps(answer_data["answer"])}})

        return RichTextAnswerForm(
            read_only=not page_behavior.may_change_answer,
            **kwargs)

    @override
    def process_form_post(
            self,
            page_context: PageContext,
            page_data: Any,
            post_data: Any,
            files_data: Any,
            page_behavior: PageBehavior,
            ) -> StyledFormBase:
        return RichTextAnswerForm(
                not page_behavior.may_change_answer,
                post_data, files_data,
                )

    @override
    def answer_data(self, page_context, page_data, form, files_data):
        data = form.cleaned_data["answer"]
        assert isinstance(data, dict)
        return {"answer": data}

    @override
    def normalized_answer(
            self,
            page_context: PageContext,
            page_data: Any,
            answer_data: Any
            ) -> str | None:
        if answer_data is None:
            return None

        from json import dumps

        from django.utils.html import escape
        return escape(dumps(answer_data["answer"]))

    @override
    def normalized_bytes_answer(
            self,
            page_context: PageContext,
            page_data: Any,
            answer_data: Any,
            ) -> tuple[str, bytes] | None:
        return None

# }}}

# vim: foldmethod=marker
