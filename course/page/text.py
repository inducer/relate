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


from django.utils.translation import (
        ugettext_lazy as _, ugettext, string_concat)
from django.utils.safestring import mark_safe
from course.validation import validate_struct, validate_markup, ValidationError
from course.content import remove_prefix
import django.forms as forms

from relate.utils import StyledForm, Struct, StyledInlineForm
from course.page.base import (
        AnswerFeedback, PageBaseWithTitle, PageBaseWithValue, markup_to_html,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer,

        get_editor_interaction_mode)

import re
import sys


class TextAnswerForm(StyledForm):
    @staticmethod
    def get_text_widget(widget_type, read_only=False, check_only=False,
            interaction_mode=None):
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

        elif widget_type in ["editor:markdown", "editor:yaml"]:
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

        super(TextAnswerForm, self).__init__(*args, **kwargs)
        widget, help_text = self.get_text_widget(
                    widget_type, read_only,
                    interaction_mode=interaction_mode)
        self.validators = validators
        self.fields["answer"] = forms.CharField(
                required=True,
                widget=widget,
                help_text=help_text,
                label=_("Answer"))

    def clean(self):
        cleaned_data = super(TextAnswerForm, self).clean()

        answer = cleaned_data.get("answer", "")
        for validator in self.validators:
            validator.validate(answer)


# {{{ validators

class RELATEPageValidator(object):
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
            page_desc = dict_to_struct(yaml.load(new_page_source))

            from course.validation import (
                    validate_flow_page, ValidationContext)
            vctx = ValidationContext(
                    # FIXME
                    repo=None,
                    commit_sha=None)

            validate_flow_page(vctx, "submitted page", page_desc)

            if page_desc.type != self.validator_desc.page_type:
                raise ValidationError(ugettext("page must be of type '%s'")
                        % self.validator_desc.page_type)

        except:
            import sys
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
            % {'location': location, 'type': validator_type})


def parse_validator(vctx, location, validator_desc):
    if not isinstance(validator_desc, Struct):
        raise ValidationError(
                string_concat(
                    "%s: ",
                    _("must be struct or string"))
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

class TextAnswerMatcher(object):
    """Abstract interface for matching text answers.

    .. attribute:: type
    .. attribute:: is_case_sensitive
    .. attribute:: pattern_type

        "struct" or "string"
    """

    def __init__(self, vctx, location, pattern):
        pass

    def validate(self, s):
        """Called to validate form input against simple input mistakes.

        Should raise :exc:`django.forms.ValidationError` on error.
        """

        pass

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
    pattern_type = "string"

    def __init__(self, vctx, location, pattern):
        self.pattern = pattern

    def grade(self, s):
        return int(
                multiple_to_single_spaces(self.pattern)
                ==
                multiple_to_single_spaces(s))

    def correct_answer_text(self):
        return self.pattern


class PlainMatcher(CaseSensitivePlainMatcher):
    type = "plain"
    is_case_sensitive = False
    pattern_type = "string"

    def grade(self, s):
        return int(
            multiple_to_single_spaces(self.pattern.lower())
            ==
            multiple_to_single_spaces(s.lower()))


class RegexMatcher(TextAnswerMatcher):
    type = "regex"
    re_flags = re.I
    is_case_sensitive = False
    pattern_type = "string"

    def __init__(self, vctx, location, pattern):
        try:
            self.pattern = re.compile(pattern, self.re_flags)
        except:
            tp, e, _ = sys.exc_info()

            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("regex '%(pattern)s' did not compile"),
                        ": %(err_type)s: %(err_str)s")
                    % {
                        "location": location,
                        "pattern": pattern,
                        "err_type": tp.__name__,
                        "err_str": str(e)})

    def grade(self, s):
        match = self.pattern.match(s)
        if match is not None:
            return 1
        else:
            return 0

    def correct_answer_text(self):
        return None


class CaseSensitiveRegexMatcher(RegexMatcher):
    type = "case_sens_regex"
    re_flags = 0
    is_case_sensitive = True
    pattern_type = "string"


def parse_sympy(s):
    if isinstance(s, unicode):
        # Sympy is not spectacularly happy with unicode function names
        s = s.encode()

    from pymbolic import parse
    from pymbolic.sympy_interface import PymbolicToSympyMapper

    # use pymbolic because it has a semi-secure parser
    return PymbolicToSympyMapper()(parse(s))


class SymbolicExpressionMatcher(TextAnswerMatcher):
    type = "sym_expr"
    is_case_sensitive = True
    pattern_type = "string"

    def __init__(self, vctx, location, pattern):
        self.pattern = pattern

        try:
            self.pattern_sym = parse_sympy(pattern)
        except ImportError:
            tp, e, _ = sys.exc_info()
            if vctx is not None:
                vctx.add_warning(
                        location,
                        string_concat(
                            "%(location)s: ",
                            _("unable to check symbolic expression"),
                            "(%(err_type)s: %(err_str)s)")
                        % {
                            'location': location,
                            "err_type": tp.__name__,
                            "err_str": str(e)
                            })

        except:
            tp, e, _ = sys.exc_info()
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
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {"err_type": tp.__name__, "err_str": str(e)})

    def grade(self, s):
        from sympy import simplify
        answer_sym = parse_sympy(s)

        try:
            simp_result = simplify(answer_sym - self.pattern_sym)
        except Exception:
            return 0

        if simp_result == 0:
            return 1
        else:
            return 0

    def correct_answer_text(self):
        return self.pattern


def float_or_sympy_evalf(s):
    if isinstance(s, (int, float)):
        return s

    # avoiding IO error if empty input when
    # the is field not required
    if s == "":
        return s

    # return a float type value, expression not allowed
    return float(parse_sympy(s).evalf())


def _is_valid_float(s):
    try:
        float_or_sympy_evalf(s)
    except:
        return False
    else:
        return True


class FloatMatcher(TextAnswerMatcher):
    type = "float"
    is_case_sensitive = False
    pattern_type = "struct"

    def __init__(self, vctx, location, matcher_desc):
        self.matcher_desc = matcher_desc

        validate_struct(
                vctx,
                location,
                matcher_desc,
                required_attrs=(
                    ("type", str),
                    ("value", (int, float, str)),
                    ),
                allowed_attrs=(
                    ("rtol", (int, float, str)),
                    ("atol", (int, float, str)),
                    ),
                )

        try:
            self.matcher_desc.value = \
                    float_or_sympy_evalf(matcher_desc.value)
        except:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("'value' is not a valid float literal"))
                    % location)

        if hasattr(matcher_desc, "rtol"):
            try:
                self.matcher_desc.rtol = \
                        float_or_sympy_evalf(matcher_desc.rtol)
            except:
                raise ValidationError(
                        string_concat(
                            "%s: ",
                            _("'rtol' is not a valid float literal"))
                        % location)
        if hasattr(matcher_desc, "atol"):
            try:
                self.matcher_desc.atol = \
                        float_or_sympy_evalf(matcher_desc.atol)
            except:
                raise ValidationError(
                        string_concat(
                            "%s: ",
                            _("'atol' is not a valid float literal"))
                        % location)

        if (
                not hasattr(matcher_desc, "atol")
                and
                not hasattr(matcher_desc, "rtol")
                and
                vctx is not None):
            vctx.add_warning(location,
                    _("Float match should have either rtol or atol--"
                        "otherwise it will match any number"))

    def validate(self, s):
        try:
            float_or_sympy_evalf(s)
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {"err_type": tp.__name__, "err_str": str(e)})

    def grade(self, s):
        if s == "":
            return 0

        answer_float = float_or_sympy_evalf(s)

        if hasattr(self.matcher_desc, "atol"):
            if (abs(answer_float - self.matcher_desc.value)
                    >= self.matcher_desc.atol):
                return 0
        if hasattr(self.matcher_desc, "rtol"):
            if (abs(answer_float - self.matcher_desc.value)
                    / abs(self.matcher_desc.value)
                    >= self.matcher_desc.rtol):
                return 0

        return 1

    def correct_answer_text(self):
        return str(self.matcher_desc.value)


TEXT_ANSWER_MATCHER_CLASSES = [
        CaseSensitivePlainMatcher,
        PlainMatcher,
        RegexMatcher,
        CaseSensitiveRegexMatcher,
        SymbolicExpressionMatcher,
        FloatMatcher,
        ]


MATCHER_RE = re.compile(r"^\<([a-zA-Z0-9_:.]+)\>(.*)$")
MATCHER_RE_2 = re.compile(r"^([a-zA-Z0-9_.]+):(.*)$")


def get_matcher_class(location, matcher_type, pattern_type):
    for matcher_class in TEXT_ANSWER_MATCHER_CLASSES:
        if matcher_class.type == matcher_type:

            if matcher_class.pattern_type != pattern_type:
                raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        # Translators: a "matcher" is used to determine
                        # if the answer to text question (blank filling
                        # question) is correct.
                        _("%(matcherclassname)s only accepts "
                            "'%(matchertype)s' patterns"))
                        % {
                            'location': location,
                            'matcherclassname': matcher_class.__name__,
                            'matchertype': pattern_type})

            return matcher_class

    raise ValidationError(
            string_concat(
                "%(location)s: ",
                _("unknown match type '%(matchertype)s'"))
            % {
                'location': location,
                'matchertype': matcher_type})


def parse_matcher_string(vctx, location, matcher_desc):
    match = MATCHER_RE.match(matcher_desc)

    if match is not None:
        matcher_type = match.group(1)
        pattern = match.group(2)
    else:
        match = MATCHER_RE_2.match(matcher_desc)

        if match is None:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("does not specify match type"))
                    % location)

        matcher_type = match.group(1)
        pattern = match.group(2)

        if vctx is not None:
            vctx.add_warning(location,
                    _("uses deprecated 'matcher:answer' style"))

    return (get_matcher_class(location, matcher_type, "string")
            (vctx, location, pattern))


def parse_matcher(vctx, location, matcher_desc):
    if isinstance(matcher_desc, (str, unicode)):
        return parse_matcher_string(vctx, location, matcher_desc)
    else:
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

        return (get_matcher_class(location, matcher_desc.type, "struct")
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

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: widget

        |text-widget-page-attr|

    """
    def __init__(self, vctx, location, page_desc):
        super(TextQuestionBase, self).__init__(vctx, location, page_desc)

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
                        'location': location,
                        'type': getattr(page_desc, "widget")})

    def required_attrs(self):
        return super(TextQuestionBase, self).required_attrs() + (
                ("prompt", "markup"),
                )

    def allowed_attrs(self):
        return super(TextQuestionBase, self).allowed_attrs() + (
                ("widget", str),
                )

    def markup_body_for_title(self):
        return self.page_desc.prompt

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        read_only = answer_is_final

        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = TextAnswerForm(
                    read_only,
                    get_editor_interaction_mode(page_context),
                    self.get_validators(), answer,
                    widget_type=getattr(self.page_desc, "widget", None))
        else:
            answer = None
            form = TextAnswerForm(
                    read_only,
                    get_editor_interaction_mode(page_context),
                    self.get_validators(),
                    widget_type=getattr(self.page_desc, "widget", None))

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        read_only = False
        return TextAnswerForm(
                read_only,
                get_editor_interaction_mode(page_context),
                self.get_validators(), post_data, files_data,
                widget_type=getattr(self.page_desc, "widget", None))

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data["answer"].strip()}

    def is_case_sensitive(self):
        return True

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        normalized_answer = answer_data["answer"]

        if not self.is_case_sensitive():
            normalized_answer = normalized_answer.lower()

        from django.utils.html import escape
        return escape(normalized_answer)

# }}}


# {{{ survey text question

class SurveyTextQuestion(TextQuestionBase):
    """
    A page asking for a textual answer, without any notion of 'correctness'

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``TextQuestion``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: prompt

        The page's prompt, written in :ref:`markup`.

    .. attribute:: widget

        |text-widget-page-attr|

    .. attribute:: answer_comment

        A comment that is shown in the same situations a 'correct answer' would
        be.
    """

    def get_validators(self):
        return []

    def allowed_attrs(self):
        return super(SurveyTextQuestion, self).allowed_attrs() + (
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
    A page asking for a textual answer

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``TextQuestion``

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

    .. attribute:: answers

        A list of answers. If the participant's response matches one of these
        answers, it is considered fully correct. Each answer consists of a 'matcher'
        and an answer template for that matcher to use. Each type of matcher
        requires one of two syntax variants to be used. The
        'simple/abbreviated' syntax::

            - <plain>some_text

        or the 'structured' syntax::

            - type: float
              value: 1.25
              rtol: 0.2

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

        - ``<case_sens_regex>[a-z]+`` Matches anything matched by the given
          (Python-style) regular expression that
          follows. Case-sensitive, i.e. capitalization matters.

        - ``<sym_expr>x+2*y`` Matches anything that :mod:`sympy` considers
          equivalent to the given expression. Equivalence is determined
          by simplifying ``user_answer - given_expr`` and testing the result
          against 0 using :mod:`sympy`.

        Here are examples of all the supported structured matchers:

        - Floating point. Example::

              -   type: float
                  value: 1.25
                  rtol: 0.2  # relative tolerance
                  atol: 0.2  # absolute tolerance

          One of ``rtol`` or ``atol`` must be given.
    """

    def __init__(self, vctx, location, page_desc):
        super(TextQuestion, self).__init__(vctx, location, page_desc)

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
        return super(TextQuestion, self).required_attrs() + (
                ("answers", list),
                )

    def get_validators(self):
        return self.matchers

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=ugettext("No answer provided."))

        answer = answer_data["answer"]

        correctness, correct_answer_text = max(
                (matcher.grade(answer), matcher.correct_answer_text())
                for matcher in self.matchers)

        return AnswerFeedback(correctness=correctness)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        # FIXME: Could use 'best' match to answer

        CA_PATTERN = string_concat(_("A correct answer is"), ": '%s'.")  # noqa

        for matcher in self.matchers:
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text

        return CA_PATTERN % unspec_correct_answer_text

    def is_case_sensitive(self):
        return any(matcher.is_case_sensitive for matcher in self.matchers)

# }}}


# {{{ human-graded text question

class HumanGradedTextQuestion(TextQuestionBase, PageBaseWithValue,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):
    """
    A page asking for a textual answer

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``HumanGradedTextQuestion``

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
        super(HumanGradedTextQuestion, self).__init__(vctx, location, page_desc)

        self.validators = [
                parse_validator(
                    vctx,
                    "%s, validator %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(
                    getattr(page_desc, "validators", []))]

    def allowed_attrs(self):
        return super(HumanGradedTextQuestion, self).allowed_attrs() + (
                ("validators", list),
                )

    def human_feedback_point_value(self, page_context, page_data):
        return self.max_points(page_data)

    def get_validators(self):
        return self.validators

# }}}


# {{{ multiple text question

from crispy_forms.layout import Layout, Field, HTML


class MultipleTextAnswerForm(StyledInlineForm):

    def __init__(self, read_only, dict_for_form, *args, **kwargs):

        super(MultipleTextAnswerForm, self).__init__(*args, **kwargs)
        html_list = dict_for_form["HTML_list"]
        self.answer_instance_list = answer_instance_list = \
                dict_for_form["answer_instance_list"]
        self.helper.layout = Layout()

        # for question with only one field, the field is forced
        # to be "required".
        if len(answer_instance_list) == 1:
            force_required = True
        else:
            force_required = False

        for idx, html_item in enumerate(html_list):

            if html_list[idx] != "":
                self.helper.layout.extend([
                        HTML(html_item)])

            # for fields embeded in html, the defined html_list can be
            # longer than the answer_instance_list.
            if idx < len(answer_instance_list):
                field_name = answer_instance_list[idx].name
                self.fields[field_name] = answer_instance_list[idx] \
                        .get_form_field(force_required=force_required)
                self.helper.layout.extend([
                        answer_instance_list[idx].get_field_layout()])

        self.helper.layout.extend([HTML("<br/><br/>")])

    def clean(self):
        cleaned_data = super(MultipleTextAnswerForm, self).clean()
        answer_name_list = [answer_instance.name
                for answer_instance in self.answer_instance_list]

        for answer in cleaned_data.keys():
            idx = answer_name_list.index(answer)
            instance_idx = self.answer_instance_list[idx]
            if hasattr(instance_idx, "matchers"):
                for validator in instance_idx.matchers:
                    validator.validate(cleaned_data[answer])


def get_question_class(location, q_type, answers_desc):
    for question_class in ALLOWED_EMBEDDED_QUESTION_CLASSES:
        if question_class.type == q_type:
            return question_class
    else:
        raise ValidationError(
            string_concat(
                "%(location)s: ",
                _("unknown embeded question type '%(type)s'"))
            % {
                'location': location,
                'type': q_type})


def parse_question(vctx, location, name, answers_desc):
    if isinstance(answers_desc, Struct):
        return (get_question_class(location, answers_desc.type, answers_desc)
            (vctx, location, name, answers_desc))
    else:
        raise ValidationError(
                string_concat(
                    "%s: ",
                    _("must be struct"))
                % location)


class AnswerBase(object):
    """Abstract interface for answer class of different type.
    .. attribute:: type
    .. attribute:: form_field_class
    """

    def __init__(self, vctx, location, name, answers_desc):
        self.name = name
        self.answers_desc = answers_desc

        # FIXME: won't validate when required is True.
        self.required = getattr(answers_desc, "required", False)

    def get_correct_answer_text(self):
        raise NotImplementedError()

    def get_correctness(self, answer):
        raise NotImplementedError()

    def get_weight(self, answer):
        if answer is not None:
            return self.weight * self.get_correctness(answer)
        else:
            return 0

    def get_field_layout(self):
        return Field(
                self.name,
                data_toggle="popover",
                data_placement="top",
                data_html="true",
                title=getattr(self.answers_desc, "hint_title", ""),
                data_content=getattr(self.answers_desc, "hint", ""),
                style=self.width_str
                )

    def get_form_field(self):
        raise NotImplementedError()


# length unit used is "em"
DEFAULT_WIDTH = 10
MINIMUN_WIDTH = 4

EM_LEN_DICT = {
        "em": 1,
        "pt": 10.00002,
        "cm": 0.35146,
        "mm": 3.5146,
        "in": 0.13837,
        "%": ""}

ALLOWED_LENGTH_UNIT = EM_LEN_DICT.keys()
WIDTH_STR_RE = re.compile("^(\d*\.\d+|\d+)\s*(.*)$")


class ShortAnswer(AnswerBase):
    type = "ShortAnswer"
    form_field_class = forms.CharField

    @staticmethod
    def get_length_attr_em(location, width_attr):
        """
        generate the length for input box, the unit is 'em'
        """

        if isinstance(width_attr, (int, float)):
            return width_attr

        if width_attr is None:
            return None

        width_re_match = WIDTH_STR_RE.match(width_attr)
        if width_re_match:
            length_value = width_re_match.group(1)
            length_unit = width_re_match.group(2)
        else:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("unrecogonized width attribute string: "
                        "'%(width_attr)s'"))
                    % {
                        "location": location,
                        "width_attr": width_attr
                        })

        if length_unit not in ALLOWED_LENGTH_UNIT:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("unsupported length unit '%(length_unit)s', "
                          "expected length unit can be "
                          "%(allowed_length_unit)s", ))
                        % {
                            "location": location,
                            "length_unit": length_unit,
                            "allowed_length_unit": ", ".join(
                                ["'" + item + "'"
                                    for item in ALLOWED_LENGTH_UNIT])
                                })

        if length_unit == "%":
            return float(length_value)*DEFAULT_WIDTH/100.0
        else:
            return float(length_value)/EM_LEN_DICT[length_unit]

    def __init__(self, vctx, location, name, answers_desc):
        super(ShortAnswer, self).__init__(
                vctx, location, name, answers_desc)

        validate_struct(
            vctx,
            location,
            answers_desc,
            required_attrs=(
                ("type", str),
                ("correct_answer", list)
                ),
            allowed_attrs=(
                ("weight", (int, float)),
                ("hint", str),
                ("hint_title", str),
                ("width", (str, int, float)),
                ("required", bool),
                ),
            )

        self.weight = getattr(answers_desc, "weight", 0)

        if len(answers_desc.correct_answer) == 0:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("at least one answer must be provided"))
                    % location)

        self.hint = getattr(self.answers_desc, "hint", "")
        self.width = getattr(self.answers_desc, "width", None)

        parsed_length = self.get_length_attr_em(location, self.width)

        if parsed_length is not None:
            self.width_str = "width: " + str(
                    max(MINIMUN_WIDTH, parsed_length)) + "em"
        else:
            self.width_str = "width: " + str(DEFAULT_WIDTH) + "em"

        self.matchers = [
                parse_matcher(
                    vctx,
                    "%s, answer %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(answers_desc.correct_answer)]

        if not any(matcher.correct_answer_text() is not None
                for matcher in self.matchers):
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("no matcher is able to provide a plain-text "
                        "correct answer"))
                    % location)

    def get_correct_answer_text(self):
        for matcher in self.matchers:
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text
        return unspec_correct_answer_text

    def get_correctness(self, answer):
        correctness, correct_answer_text = max(
                (matcher.grade(answer), matcher.correct_answer_text())
                for matcher in self.matchers)
        return correctness

    def get_form_field(self, force_required=False):
        return (self.form_field_class)(
                    required=self.required or force_required,
                    widget=None,
                    help_text=None,
                    label=self.name
                )


class ChoicesAnswer(AnswerBase):
    type = "ChoicesAnswer"
    form_field_class = forms.ChoiceField

    CORRECT_TAG = "~CORRECT~"

    @classmethod
    def process_choice_string(cls, s):
        if not isinstance(s, str):
            s = str(s)
        s = remove_prefix(cls.CORRECT_TAG, s)

        from course.content import markup_to_html
        s_contain_p_tag = "<p>" in s
        s = markup_to_html(
                course=None,
                repo=None,
                commit_sha=None,
                text=s,
                )
        # allow HTML in option
        if not s_contain_p_tag:
            s = s.replace("<p>", "").replace("</p>", "")
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, name, answers_desc):
        super(ChoicesAnswer, self).__init__(
            vctx, location, name, answers_desc)

        validate_struct(
            vctx,
            location,
            answers_desc,
            required_attrs=(
                ("type", str),
                ("choices", list)
                ),
            allowed_attrs=(
                ("weight", (int, float)),
                ("hint", str),
                ("hint_title", str),
                ("required", bool),
                ),
            )

        self.weight = getattr(answers_desc, "weight", 0)

        correct_choice_count = 0
        for choice_idx, choice in enumerate(answers_desc.choices):
            try:
                choice = str(choice)
            except:
                raise ValidationError(
                        string_concat(
                            "%(location)s: '%(answer_name)s' ",
                            _("choice %(idx)d: unable to convert to string")
                            )
                        % {'location': location,
                            'answer_name': self.name,
                            'idx': choice_idx+1})

            if choice.startswith(self.CORRECT_TAG):
                correct_choice_count += 1

            if vctx is not None:
                validate_markup(vctx, location,
                        remove_prefix(self.CORRECT_TAG, choice))

        if correct_choice_count < 1:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("one or more correct answer(s) expected "
                        " for question '%(question_name)s', "
                        "%(n_correct)d found"))
                    % {
                        'location': location,
                        'question_name': self.name,
                        'n_correct': correct_choice_count})

        self.hint = getattr(self.answers_desc, "hint", "")
        self.width_str = ""

    def correct_indices(self):
        result = []
        for i, choice_text in enumerate(self.answers_desc.choices):
            if str(choice_text).startswith(self.CORRECT_TAG):
                result.append(i)
        return result

    def get_correct_answer_text(self):
        corr_idx = self.correct_indices()[0]
        return self.process_choice_string(
                self.answers_desc.choices[corr_idx]).lstrip()

    def get_max_correct_answer_len(self):
        return max([len(answer) for answer in
            [self.process_choice_string(processed)
                for processed in self.answers_desc.choices]])

    def get_correctness(self, answer):
        if answer == "":
            correctness = 0
        elif int(answer) >= 0:
            if int(answer) in self.correct_indices():
                correctness = 1
            else:
                correctness = 0
        return correctness

    def get_form_field(self, force_required=False):
        choices = tuple(
            (i,  self.process_choice_string(self.answers_desc.choices[i]))
            for i, src_i in enumerate(self.answers_desc.choices))
        choices = (
                (None, "-"*self.get_max_correct_answer_len()),
                ) + choices
        return (self.form_field_class)(
            required=self.required or force_required,
            choices=tuple(choices),
            widget=None,
            help_text=None,
            label=""
        )


ALLOWED_EMBEDDED_QUESTION_CLASSES = [
    ShortAnswer,
    ChoicesAnswer
]


WRAPPED_NAME_RE = re.compile(r"[^{](?=(\[\[[^\[\]]*\]\]))[^}]")
NAME_RE = re.compile(r"[^{](?=\[\[([^\[\]]*)\]\])[^}]")
NAME_VALIDATE_RE = re.compile("^[a-zA-Z]+[a-zA-Z0-9_]{0,}$")


class InlineMultiQuestion(TextQuestionBase, PageBaseWithValue):
    """
    An auto-graded page with cloze like questions.

    .. attribute:: id

        |id-page-attr|

    .. attribute:: type

        ``InlineMultiQuestion``

    .. attribute:: access_rules

        |access-rules-page-attr|

    .. attribute:: title

        |title-page-attr|

    .. attribute:: question

        The body of the question, with answer fields wrapped
        by paired ``[[`` and ``]]``, written in :ref:`markup`.

    .. attribute:: answers

        Answers of the questions, written in :ref:`markup`. Each
        cloze question require an answer struct. The question now
        support cloze question of TextAnswer and ChoiceAnswer type.

    Here is an example of :class:`InlineMultiQuestion`::

        type: InlineMultiQuestion
        id: excelbasictry3
        value: 10
        prompt: |

            # An example

            Complete the following paragraph.

        question: |

            Foo and [[blank1]] are often used in code examples, or
            tutorials. The float weight of $\frac{1}{5}$ is [[blank_2]].

            The correct answer for this choice question is [[choice_a]].
            The Upper case of "foo" is [[choice2]]

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

    """

    def __init__(self, vctx, location, page_desc):
        super(InlineMultiQuestion, self).__init__(
                vctx, location, page_desc)

        self.question = page_desc.question
        self.embeded_wrapped_name_list = WRAPPED_NAME_RE.findall(
                self.question)
        self.embeded_name_list = NAME_RE.findall(self.question)

        from relate.utils import struct_to_dict
        answers_name_list = struct_to_dict(page_desc.answers).keys()

        invalid_answer_name = []
        invalid_embeded_name = []

        for answers_name in answers_name_list:
            if NAME_VALIDATE_RE.match(answers_name) is None:
                invalid_answer_name.append(answers_name)
        if len(invalid_answer_name) > 0:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("invalid answers name %s. A valid answer "
                         "should start with letters, and hyphen and "
                          "numbers are allowed, without spaces."))
                    % (
                        location,
                        ", ".join([
                            "'" + name + "'"
                            for name in invalid_answer_name])
                        ))

        for embeded_name in self.embeded_name_list:
            if NAME_VALIDATE_RE.match(embeded_name) is None:
                invalid_embeded_name.append(embeded_name)
        if len(invalid_embeded_name) > 0:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("invalid embeded question name %s. A valid name "
                         "should start with letters, and hyphens and "
                          "underscores are allowed, without spaces."))
                        % (
                            location,
                            ", ".join([
                                "'" + name + "'"
                                for name in invalid_embeded_name])
                            ))

        if len(set(self.embeded_name_list)) < len(self.embeded_name_list):
            duplicated = list(
                 set([x for x in self.embeded_name_list
                      if self.embeded_name_list.count(x) > 1]))
            raise ValidationError(
                 string_concat(
                     "%s: ",
                     _("embeded question name %s not unique."))
                 % (location, ", ".join(duplicated)))

        no_answer_set = set(self.embeded_name_list) - set(answers_name_list)
        redundant_answer_list = list(set(answers_name_list)
                - set(self.embeded_name_list))

        if no_answer_set:
            raise ValidationError(
                 string_concat(
                     "%s: ",
                     _("correct answer(s) not provided for question %s."))
                 % (location, ", ".join(
                     ["'" + item + "'"
                         for item in list(no_answer_set)])))

        if redundant_answer_list:
            if vctx is not None:
                vctx.add_warning(location,
                        _("redundant answers %s provided for "
                            "non-existing question(s).")
                        % ", ".join(
                            ["'" + item + "'"
                                for item in redundant_answer_list]))

        # for correct render of question with more than one
        # paragraph, remove heading <p> tags and change </p>
        # to line break.
        from course.content import markup_to_html
        remainder_html = markup_to_html(
                course=None,
                repo=None,
                commit_sha=None,
                text=self.question,
                ).replace("<p>", "").replace("</p>", "<br/>")

        self.html_list = []
        for wrapped_name in self.embeded_wrapped_name_list:
            [html, remainder_html] = remainder_html.split(wrapped_name)
            self.html_list.append(html)

        if remainder_html != "":
            self.html_list.append(remainder_html)

        # make sure all [[ and ]] are paired.
        embeded_removed = " ".join(self.html_list)

        for sep in ["[[", "]]"]:
            if sep in embeded_removed:
                raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("have unpaired '%s'."))
                    % (location, sep))

        self.answer_instance_list = []
        self.total_weight = 0

        for idx, name in enumerate(self.embeded_name_list):
            answers_desc = getattr(page_desc.answers, name)

            parsed_answer = parse_question(
                    vctx, location, name, answers_desc)

            self.answer_instance_list.append(parsed_answer)
            self.total_weight += self.answer_instance_list[idx].weight

    def required_attrs(self):
        return super(InlineMultiQuestion, self).required_attrs() + (
                ("question", "markup"), ("answers", Struct),
                )

    def allowed_attrs(self):
        return super(InlineMultiQuestion, self).allowed_attrs() + (
                ("answer_comment", "markup"),
                )

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def get_dict_for_form(self):
        return {
                "HTML_list": self.html_list,
                "answer_instance_list": self.answer_instance_list,
               }

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        read_only = answer_is_final

        if answer_data is not None:
            answer = answer_data["answer"]
            form = MultipleTextAnswerForm(
                    read_only,
                    self.get_dict_for_form(),
                    answer)
        else:
            answer = None
            form = MultipleTextAnswerForm(
                    read_only,
                    self.get_dict_for_form())

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        read_only = False

        return MultipleTextAnswerForm(
                read_only,
                self.get_dict_for_form(),
                post_data, files_data)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        # FIXME: Could use 'best' match to answer

        cor_answer_output = self.question

        for idx, wrapped in enumerate(self.embeded_wrapped_name_list):
            correct_answer_i = self.answer_instance_list[idx] \
                    .get_correct_answer_text()
            cor_answer_output = cor_answer_output.replace(
                wrapped,
                "<strong>" + correct_answer_i + "</strong>")

        CA_PATTERN = string_concat(_("A correct answer is"), ": <br/> %s")  # noqa

        return CA_PATTERN % cor_answer_output

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data}

    def form_to_html(self, request, page_context, form, answer_data):
        """Returns an HTML rendering of *form*."""

        from django.template import loader, RequestContext
        from django import VERSION as DJANGO_VERSION

        if DJANGO_VERSION >= (1, 9):
            return loader.render_to_string(
                    "course/custom-crispy-inline-form.html",
                    context={"form": form},
                    request=request)
        else:
            context = RequestContext(request)
            context.update({"form": form})
            return loader.render_to_string(
                    "course/custom-crispy-inline-form.html",
                    context_instance=context)

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=ugettext("No answer provided."))

        answer_dict = answer_data["answer"]

        if self.total_weight > 0:
            achieved_weight = 0
            for answer_instance in self.answer_instance_list:
                if answer_dict[answer_instance.name] is not None:
                    achieved_weight += answer_instance.get_weight(
                            answer_dict[answer_instance.name])
            correctness = achieved_weight / self.total_weight

        # for case when all questions have no weight assigned
        else:
            n_corr = 0
            for answer_instance in self.answer_instance_list:
                if answer_dict[answer_instance.name] is not None:
                    n_corr += answer_instance.get_correctness(
                            answer_dict[answer_instance.name])
            correctness = n_corr / len(self.answer_instance_list)

        return AnswerFeedback(correctness=correctness)

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        answer_dict = answer_data["answer"]

        nml_answer_output = self.question

        for idx, wrapped_name in enumerate(self.embeded_wrapped_name_list):
            nml_answer_output = nml_answer_output.replace(
                    wrapped_name,
                    "<strong>"
                    + answer_dict[self.embeded_name_list[idx]]
                    + "</strong>")

        return nml_answer_output

# }}}

# vim: foldmethod=marker
