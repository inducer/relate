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


from typing import Tuple, Any
from django.utils.translation import (
        gettext_lazy as _, gettext)
from course.validation import validate_struct, ValidationError
import django.forms as forms

from relate.utils import StyledForm, Struct, string_concat
from course.page.base import (
        AnswerFeedback, PageBaseWithTitle, PageBaseWithValue, markup_to_html,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer,

        get_editor_interaction_mode)

import re
import sys

CORRECT_ANSWER_PATTERN = string_concat(_("A correct answer is"), ": '%s'.")  # noqa


class TextAnswerForm(StyledForm):
    # prevents form submission with codemirror's empty textarea
    use_required_attribute = False

    @staticmethod
    def get_text_widget(widget_type, read_only=False, check_only=False,
            interaction_mode=None, initial_text=None):
        """Returns None if no widget found."""

        if widget_type in [None, "text_input"]:
            if check_only:
                return True

            widget = forms.TextInput()
            widget.attrs["autofocus"] = None
            if read_only:
                widget.attrs["readonly"] = None
            return widget, None

        elif widget_type == "textarea":
            if check_only:
                return True

            widget = forms.Textarea()
            # widget.attrs["autofocus"] = None
            if read_only:
                widget.attrs["readonly"] = None
            return widget, None

        elif widget_type.startswith("editor:"):
            if check_only:
                return True

            from course.utils import get_codemirror_widget
            cm_widget, cm_help_text = get_codemirror_widget(
                    language_mode=widget_type[widget_type.find(":")+1:],
                    interaction_mode=interaction_mode,
                    read_only=read_only)

            return cm_widget, cm_help_text

        else:
            return None, None

    def __init__(self, read_only, interaction_mode, validators, *args, **kwargs):
        widget_type = kwargs.pop("widget_type", "text_input")
        initial_text = kwargs.pop("initial_text", None)

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

        self.style_codemirror_widget()

    def clean(self):
        cleaned_data = super().clean()

        answer = cleaned_data.get("answer", "")
        for i, validator in enumerate(self.validators):
            try:
                validator.validate(answer)
            except forms.ValidationError:
                if i + 1 == len(self.validators):
                    # last one, and we flunked -> not valid
                    raise
            else:
                # Found one that will take the input. Good enough.
                break


# {{{ validators

class RELATEPageValidator:
    type = "relate_page"

    def __init__(self, vctx, location, validator_desc):
        self.validator_desc = validator_desc

        validate_struct(
                vctx,
                location,
                validator_desc,
                required_attrs=(
                    ("type", str),
                    ),
                allowed_attrs=(
                    ("page_type", str),
                    ),
                )

    def validate(self, new_page_source):
        from relate.utils import dict_to_struct
        import yaml

        try:
            page_desc = dict_to_struct(yaml.safe_load(new_page_source))

            from course.validation import (
                    validate_flow_page, ValidationContext)
            vctx = ValidationContext(
                    # FIXME
                    repo=None,
                    commit_sha=None)

            validate_flow_page(vctx, "submitted page", page_desc)

            if page_desc.type != self.validator_desc.page_type:
                raise ValidationError(gettext("page must be of type '%s'")
                        % self.validator_desc.page_type)

        except Exception:
            tp, e, _ = sys.exc_info()

            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {"err_type": tp.__name__, "err_str": str(e)})


TEXT_ANSWER_VALIDATOR_CLASSES = [
        RELATEPageValidator,
        ]


def get_validator_class(location, validator_type):
    for validator_class in TEXT_ANSWER_VALIDATOR_CLASSES:
        if validator_class.type == validator_type:
            return validator_class

    raise ValidationError(
            string_concat(
                "%(location)s: ",
                _("unknown validator type"),
                "'%(type)s'")
            % {"location": location, "type": validator_type})


def parse_validator(vctx, location, validator_desc):
    if not isinstance(validator_desc, Struct):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    _("must be struct"))
                % location)

    if not hasattr(validator_desc, "type"):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    "matcher must supply 'type'")
                % location)

    return (get_validator_class(location, validator_desc.type)
        (vctx, location, validator_desc))

# }}}


# {{{ matchers

class TextAnswerMatcher:
    """Abstract interface for matching text answers.

    .. attribute:: type
    .. attribute:: is_case_sensitive

        Only used for answer normalization. Matchers are responsible for
        case sensitivity themselves.
    """
    ALLOWED_ATTRIBUTES: Tuple[Any, ...] = ()

    def __init__(self, vctx, location, matcher_desc):
        self.matcher_desc = matcher_desc
        validate_struct(
                vctx, location, matcher_desc,
                required_attrs=(
                    ("type", str),
                    ("value", self.VALUE_VALIDATION_TYPE),
                    ),
                allowed_attrs=(
                    ("correctness", (int, float)),
                    ("feedback", str),
                    ) + self.ALLOWED_ATTRIBUTES,
                )

        assert matcher_desc.type == self.type
        self.value = matcher_desc.value

        if hasattr(matcher_desc, "correctness"):
            from course.constants import MAX_EXTRA_CREDIT_FACTOR
            if not 0 <= matcher_desc.correctness <= MAX_EXTRA_CREDIT_FACTOR:
                raise ValidationError(
                        string_concat(
                            "%s: ",
                            _("correctness value is out of bounds"))
                        % (location))

            self.correctness = matcher_desc.correctness
        else:
            self.correctness = 1

        self.feedback = getattr(matcher_desc, "feedback", None)

    def validate(self, s):
        """Called to validate form input against simple input mistakes.

        Should raise :exc:`django.forms.ValidationError` on error.
        """

        pass  # pragma: no cover

    def grade(self, s):
        raise NotImplementedError()

    def correct_answer_text(self):
        """May return *None* if not known."""
        raise NotImplementedError()


EXTRA_SPACES_RE = re.compile(r"\s\s+")


def multiple_to_single_spaces(s):
    return EXTRA_SPACES_RE.sub(" ", s).strip()


class CaseSensitivePlainMatcher(TextAnswerMatcher):
    type = "case_sens_plain"
    is_case_sensitive = True

    VALUE_VALIDATION_TYPE = str

    def __init__(self, vctx, location, matcher_desc):
        super().__init__(vctx, location, matcher_desc)

    def grade(self, s):
        if multiple_to_single_spaces(self.value) == multiple_to_single_spaces(s):
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    def correct_answer_text(self):
        if self.correctness >= 1:
            return self.value
        else:
            return None


class PlainMatcher(CaseSensitivePlainMatcher):
    type = "plain"
    is_case_sensitive = False

    def grade(self, s):
        if (multiple_to_single_spaces(self.value.lower())
                == multiple_to_single_spaces(s.lower())):
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)


class RegexMatcher(TextAnswerMatcher):
    type = "regex"

    VALUE_VALIDATION_TYPE = str
    ALLOWED_ATTRIBUTES = (
            ("flags", list),
            )

    RE_FLAGS = [
            "A", "ASCII", "DOTALL", "I", "IGNORECASE", "M", "MULTILINE", "S",
            "U", "UNICODE", "VERBOSE", "X",
            # omitted, grade should be locale-independent
            # "L", "LOCALE"
            ]

    def __init__(self, vctx, location, matcher_desc):
        super().__init__(vctx, location, matcher_desc)

        flags = getattr(self.matcher_desc, "flags", None)
        if flags is None:
            self.is_case_sensitive = type(self) == CaseSensitiveRegexMatcher
            if self.is_case_sensitive:
                re_flags = 0
            else:
                re_flags = re.IGNORECASE
        else:
            if type(self) == CaseSensitiveRegexMatcher:
                raise ValidationError(
                        string_concat("%s: ",
                            _("may not specify flags in CaseSensitiveRegexMatcher"))
                        % (location))

            re_flags = 0
            for flag in flags:
                if not isinstance(flag, str):
                    raise ValidationError(
                            string_concat("%s: ", _("regex flag is not a string"))
                            % (location))
                if flag not in self.RE_FLAGS:
                    raise ValidationError(
                            string_concat("%s: ", _("regex flag is invalid"))
                            % (location))
                re_flags |= getattr(re, flag)

            self.is_case_sensitive = "I" in flags or "IGNORECASE" in flags
        try:
            self.regex = re.compile(self.value, re_flags)
        except Exception:
            tp, e, __ = sys.exc_info()

            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("regex '%(pattern)s' did not compile"),
                        ": %(err_type)s: %(err_str)s")
                    % {
                        "location": location,
                        "pattern": self.value,
                        "err_type": tp.__name__,
                        "err_str": str(e)})

    def grade(self, s):
        match = self.regex.match(s)
        if match is not None:
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    def correct_answer_text(self):
        return None


class CaseSensitiveRegexMatcher(RegexMatcher):
    type = "case_sens_regex"

    def __init__(self, vctx, location, matcher_desc):
        super().__init__(vctx, location, matcher_desc)

        if vctx is not None:
            vctx.add_warning(location, _("Uses 'case_sens_regex' matcher. "
                "This will go away in 2022. Use 'regex' with specified flags "
                "instead."))


def parse_sympy(s):
    from pymbolic import parse
    from pymbolic.interop.sympy import PymbolicToSympyMapper

    # use pymbolic because it has a semi-secure parser
    return PymbolicToSympyMapper()(parse(s))


class SymbolicExpressionMatcher(TextAnswerMatcher):
    type = "sym_expr"
    is_case_sensitive = True

    VALUE_VALIDATION_TYPE = str

    def __init__(self, vctx, location, matcher_desc):
        super().__init__(vctx, location, matcher_desc)

        try:
            self.value_sym = parse_sympy(self.value)
        except ImportError:
            tp, e, __ = sys.exc_info()
            if vctx is not None:
                vctx.add_warning(
                        location,
                        string_concat(
                            "%(location)s: ",
                            _("unable to check symbolic expression"),
                            "(%(err_type)s: %(err_str)s)")
                        % {
                            "location": location,
                            "err_type": tp.__name__,
                            "err_str": str(e)
                            })

        except Exception:
            tp, e, __ = sys.exc_info()
            raise ValidationError(
                    "%(location)s: %(err_type)s: %(err_str)s"
                    % {
                        "location": location,
                        "err_type": tp.__name__,
                        "err_str": str(e)
                        })

    def validate(self, s):
        try:
            parse_sympy(s)
        except Exception:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {"err_type": tp.__name__, "err_str": str(e)})

    def grade(self, s):
        try:
            answer_sym = parse_sympy(s)
        except Exception:
            return AnswerFeedback(0)

        from sympy import simplify
        try:
            simp_result = simplify(answer_sym - self.value_sym)
        except Exception:
            return AnswerFeedback(0)

        if simp_result == 0:
            return AnswerFeedback(self.correctness, self.feedback)
        else:
            return AnswerFeedback(0)

    def correct_answer_text(self):
        if self.correctness >= 1:
            return self.value
        else:
            return None


def float_or_sympy_evalf(s):
    if isinstance(s, (int, float,)):
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


class FloatMatcher(TextAnswerMatcher):
    type = "float"
    is_case_sensitive = False

    VALUE_VALIDATION_TYPE = (int, float, str)
    ALLOWED_ATTRIBUTES = (
            ("rtol", (int, float, str)),
            ("atol", (int, float, str)),
            )

    def __init__(self, vctx, location, matcher_desc):
        super().__init__(vctx, location, matcher_desc)

        try:
            self.matcher_desc.value = \
                    float_or_sympy_evalf(self.value)
        except Exception:
            raise ValidationError(
                    string_concat(
                        "%s: 'value' ",
                        _("does not provide a valid float literal"))
                    % location)

        if hasattr(matcher_desc, "rtol"):
            try:
                self.matcher_desc.rtol = \
                        float_or_sympy_evalf(matcher_desc.rtol)
            except Exception:
                raise ValidationError(
                        string_concat(
                            "%s: 'rtol' ",
                            _("does not provide a valid float literal"))
                        % location)

            if matcher_desc.value == 0:
                raise ValidationError(
                        string_concat(
                            "%s: 'rtol' ",
                            _("not allowed when 'value' is zero"))
                        % location)

        if hasattr(matcher_desc, "atol"):
            try:
                self.matcher_desc.atol = \
                        float_or_sympy_evalf(matcher_desc.atol)
            except Exception:
                raise ValidationError(
                        string_concat(
                            "%s: 'atol' ",
                            _("does not provide a valid float literal"))
                        % location)
        else:
            if matcher_desc.value == 0:
                vctx.add_warning(location,
                         _("Float match for 'value' zero should have atol--"
                           "otherwise it will match any number"))

        if (
                not matcher_desc.value == 0
                and not hasattr(matcher_desc, "atol")
                and not hasattr(matcher_desc, "rtol")
                and vctx is not None):
            vctx.add_warning(location,
                    _("Float match should have either rtol or atol--"
                        "otherwise it will match any number"))

    def validate(self, s):
        try:
            float_or_sympy_evalf(s)
        except Exception:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {"err_type": tp.__name__, "err_str": str(e)})

    def grade(self, s):
        try:
            answer_float = float_or_sympy_evalf(s)
        except Exception:
            # Should not happen, no need to give verbose feedback.
            return AnswerFeedback(0)

        good_afb = AnswerFeedback(self.correctness, self.feedback)
        bad_afb = AnswerFeedback(0)

        from math import isnan, isinf
        if isinf(self.matcher_desc.value):
            return good_afb if isinf(answer_float) else bad_afb
        if isnan(self.matcher_desc.value):
            return good_afb if isnan(answer_float) else bad_afb
        if isinf(answer_float) or isnan(answer_float):
            return bad_afb

        if hasattr(self.matcher_desc, "atol"):
            if (abs(answer_float - self.matcher_desc.value)
                    > self.matcher_desc.atol):
                return bad_afb
        if hasattr(self.matcher_desc, "rtol"):
            if (abs(answer_float - self.matcher_desc.value)
                    / abs(self.matcher_desc.value)
                    > self.matcher_desc.rtol):
                return bad_afb

        return good_afb

    def correct_answer_text(self):
        if self.correctness >= 1:
            return str(self.matcher_desc.value)
        else:
            return None


TEXT_ANSWER_MATCHER_CLASSES = [
        CaseSensitivePlainMatcher,
        PlainMatcher,
        RegexMatcher,
        CaseSensitiveRegexMatcher,
        SymbolicExpressionMatcher,
        FloatMatcher,
        ]


MATCHER_RE = re.compile(r"^\<([a-zA-Z0-9_:.]+)\>(.*)$")


def get_matcher_class(location, matcher_type):
    for matcher_class in TEXT_ANSWER_MATCHER_CLASSES:
        if matcher_class.type == matcher_type:
            return matcher_class

    raise ValidationError(
            string_concat(
                "%(location)s: ",
                _("unknown matcher type '%(matchertype)s'"))
            % {
                "location": location,
                "matchertype": matcher_type})


def parse_matcher(vctx, location, matcher_desc):
    if isinstance(matcher_desc, str):
        match = MATCHER_RE.match(matcher_desc)

        if match is not None:
            matcher_desc = Struct({
                "type": match.group(1),
                "value": match.group(2),
                })
        else:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("matcher string does not have expected format, "
                            "expecting '<matcher type>matched string'"))
                    % location)

    if not isinstance(matcher_desc, Struct):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    _("must be struct or string"))
                % location)

    if not hasattr(matcher_desc, "type"):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    _("matcher must supply 'type'"))
                % location)

    return (get_matcher_class(location, matcher_desc.type)
        (vctx, location, matcher_desc))

# }}}


# {{{ text question base

class TextQuestionBase(PageBaseWithTitle):
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
    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        widget = TextAnswerForm.get_text_widget(
                getattr(page_desc, "widget", None),
                check_only=True)

        if widget is None:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("unrecognized widget type"),
                        "'%(type)s'")
                    % {
                        "location": location,
                        "type": page_desc.widget})

    def required_attrs(self):
        return super().required_attrs() + (
                ("prompt", "markup"),
                )

    def allowed_attrs(self):
        return super().allowed_attrs() + (
                ("widget", str),
                ("initial_text", str),
                )

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def get_validators(self):
        raise NotImplementedError()

    def make_form(self, page_context, page_data,
            answer_data, page_behavior):

        kwargs = {
            "read_only": not page_behavior.may_change_answer,
            "interaction_mode": getattr(self.page_desc, "widget", None),
            "validators": self.get_validators(),
            "widget_type": getattr(self.page_desc, "widget", None),
            "initial_text": getattr(self.page_desc, "initial_text", None),
        }

        if answer_data is not None:
            kwargs.update({"data": {"answer": answer_data["answer"]}})

        return TextAnswerForm(**kwargs)

    def process_form_post(self, page_context, page_data, post_data, files_data,
            page_behavior):
        return TextAnswerForm(
                not page_behavior.may_change_answer,
                get_editor_interaction_mode(page_context),
                self.get_validators(), post_data, files_data,
                widget_type=getattr(self.page_desc, "widget", None))

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data["answer"].strip()}

    def _is_case_sensitive(self):
        return True

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        normalized_answer = answer_data["answer"]

        if not self._is_case_sensitive():
            normalized_answer = normalized_answer.lower()

        from django.utils.html import escape
        return escape(normalized_answer)

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        return (".txt", answer_data["answer"].encode("utf-8"))
# }}}


# {{{ survey text question

class SurveyTextQuestion(TextQuestionBase):
    """
    A page asking for a textual answer, without any notion of 'correctness'

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

    .. attribute:: answer_comment

        A comment that is shown in the same situations a 'correct answer' would
        be.
    """

    def get_validators(self):
        return []

    def allowed_attrs(self):
        return super().allowed_attrs() + (
                ("answer_comment", "markup"),
                )

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        if hasattr(self.page_desc, "answer_comment"):
            return markup_to_html(page_context, self.page_desc.answer_comment)
        else:
            return None

    def expects_answer(self):
        return True

    def is_answer_gradable(self):
        return False

# }}}


# {{{ text question

class TextQuestion(TextQuestionBase, PageBaseWithValue):
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

    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        if len(page_desc.answers) == 0:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("at least one answer must be provided"))
                    % location)

        self.matchers = [
                parse_matcher(
                    vctx,
                    "%s, answer %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(page_desc.answers)]

        if not any(matcher.correct_answer_text() is not None
                for matcher in self.matchers):
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("no matcher is able to provide a plain-text "
                        "correct answer"))
                    % location)

    def required_attrs(self):
        return super().required_attrs() + (
                ("answers", list),
                )

    def allowed_attrs(self):
        return super().allowed_attrs() + (
                ("answer_explanation", "markup"),
                )

    def get_validators(self):
        return self.matchers

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=gettext("No answer provided."))

        answer = answer_data["answer"]

        # Must start with 'None' to allow matcher to set feedback for zero
        # correctness.
        afb = None

        for matcher in self.matchers:
            try:
                matcher.validate(answer)
            except forms.ValidationError:
                continue

            matcher_afb = matcher.grade(answer)
            if matcher_afb.correctness is not None:
                if afb is None:
                    afb = matcher_afb
                elif matcher_afb.correctness > afb.correctness:
                    afb = matcher_afb

        if afb is None:
            afb = AnswerFeedback(0)

        return afb

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        # FIXME: Could use 'best' match to answer

        unspec_correct_answer_text = None
        for matcher in self.matchers:  # pragma: no branch
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text

        result = CORRECT_ANSWER_PATTERN % unspec_correct_answer_text

        if hasattr(self.page_desc, "answer_explanation"):
            result += markup_to_html(page_context, self.page_desc.answer_explanation)

        return result

    def _is_case_sensitive(self):
        return any(matcher.is_case_sensitive for matcher in self.matchers)

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

    def __init__(self, vctx, location, page_desc):
        super().__init__(vctx, location, page_desc)

        self.validators = [
                parse_validator(
                    vctx,
                    "%s, validator %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(
                    getattr(page_desc, "validators", []))]

    def allowed_attrs(self):
        return super().allowed_attrs() + (
                ("validators", list),
                )

    def human_feedback_point_value(self, page_context, page_data):
        return self.max_points(page_data)

    def get_validators(self):
        return self.validators

# }}}

# vim: foldmethod=marker
