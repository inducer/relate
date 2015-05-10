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

from django.utils.translation import ugettext_lazy as _ , ugettext
from course.validation import validate_struct, ValidationError
import django.forms as forms

from relate.utils import StyledForm, Struct
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

            from course.validation import validate_flow_page, ValidationContext
            vctx = ValidationContext(
                    # FIXME
                    repo=None,
                    commit_sha=None)

            validate_flow_page(vctx, "submitted page", page_desc)

            if page_desc.type != self.validator_desc.page_type:
                raise ValidationError(_("page must be of type '%s'")
                        % self.validator_desc.page_type)

        except:
            import sys
            tp, e, _ = sys.exc_info()

            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {'err_type':tp.__name__, 'err_str':str(e)})


TEXT_ANSWER_VALIDATOR_CLASSES = [
        RELATEPageValidator,
        ]


def get_validator_class(location, validator_type):
    for validator_class in TEXT_ANSWER_VALIDATOR_CLASSES:
        if validator_class.type == validator_type:
            return validator_class

    raise ValidationError(_("%(location)s: unknown validator type '%(type)s'")
            % {'location':location, 'type':validator_type})


def parse_validator(vctx, location, validator_desc):
    if not isinstance(validator_desc, Struct):
        raise ValidationError(_("%s: must be struct or string")
                % location)

    if not hasattr(validator_desc, "type"):
        raise ValidationError(_("%s: matcher must supply 'type'") % location)

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


class CaseSensitivePlainMatcher(TextAnswerMatcher):
    type = "case_sens_plain"
    is_case_sensitive = True
    pattern_type = "string"

    def __init__(self, vctx, location, pattern):
        self.pattern = pattern

    def grade(self, s):
        return int(self.pattern == s)

    def correct_answer_text(self):
        return self.pattern


class PlainMatcher(CaseSensitivePlainMatcher):
    type = "plain"
    is_case_sensitive = False
    pattern_type = "string"

    def grade(self, s):
        return int(self.pattern.lower() == s.lower())


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

            raise ValidationError(_("%(location)s: regex '%(pattern)s' did not compile: %(err_type)s: %(err_str)s")
                    % {'location':location, 'pattern':pattern, 'err_type':tp.__name__, 'err_str':str(e)})

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
	            vctx.add_warning(location, _("%(location)s: unable to check "
	                    "symbolic expression (%(err_type)s: %(err_str)s)")
	                    % {'location':location, 'err_type':tp.__name__, 'err_str':str(e)})

        except:
            tp, e, _ = sys.exc_info()
            raise ValidationError("%(location)s: %(err_type)s: %(err_str)s"
                    % {'location':location, 'err_type':tp.__name__, 'err_str':str(e)})

    def validate(self, s):
        try:
            parse_sympy(s)
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {'err_type':tp.__name__, 'err_str':str(e)})

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
                    ("value", (int, float)),
                    ),
                allowed_attrs=(
                    ("rtol", (int, float)),
                    ("atol", (int, float)),
                    ),
                )

    def validate(self, s):
        try:
            float(s)
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%(err_type)s: %(err_str)s"
                    % {'err_type':tp.__name__, 'err_str':str(e)})

    def grade(self, s):
        answer_float = float(s)

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
                # Translators: a "matcher" is used to determine if the answer to text question (blank filling question) is correct
                raise ValidationError(_("%(location)s: %(matcherclassname)s only accepts '%(matchertype)s' patterns")
                        % {'location':location, 'matcherclassname':matcher_class.__name__, 'matchertype':pattern_type})

            return matcher_class

    raise ValidationError(_("%(location)s: unknown match type '%(matchertype)s'")
            % {'location':location, 'matchertype':matcher_type})


def parse_matcher_string(vctx, location, matcher_desc):
    match = MATCHER_RE.match(matcher_desc)

    if match is not None:
        matcher_type = match.group(1)
        pattern = match.group(2)
    else:
        match = MATCHER_RE_2.match(matcher_desc)

        if match is None:
            raise ValidationError(_("%s: does not specify match type")
                    % location)

        matcher_type = match.group(1)
        pattern = match.group(2)

        if vctx is not None:
            vctx.add_warning(location, _("uses deprecated 'matcher:answer' style"))

    return (get_matcher_class(location, matcher_type, "string")
            (vctx, location, pattern))


def parse_matcher(vctx, location, matcher_desc):
    if isinstance(matcher_desc, (str, unicode)):
        return parse_matcher_string(vctx, location, matcher_desc)
    else:
        if not isinstance(matcher_desc, Struct):
            raise ValidationError(_("%s: must be struct or string")
                    % location)

        if not hasattr(matcher_desc, "type"):
            raise ValidationError(_("%s: matcher must supply 'type'") % location)

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
            raise ValidationError(_("%(location)s: unrecognized widget type '%(type)s'")
                    % {'location':location, 'type':getattr(page_desc, "widget")})

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

        TODO
    """

    def __init__(self, vctx, location, page_desc):
        super(TextQuestion, self).__init__(vctx, location, page_desc)

        if len(page_desc.answers) == 0:
            raise ValidationError(_("%s: at least one answer must be provided")
                    % location)

        self.matchers = [
                parse_matcher(
                    vctx,
                    "%s, answer %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(page_desc.answers)]

        if not any(matcher.correct_answer_text() is not None
                for matcher in self.matchers):
            raise ValidationError(_("%s: no matcher is able to provide a plain-text "
                    "correct answer") % location)

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

        CA_PATTERN = _("A correct answer is: '%s'.")  # noqa

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

# vim: foldmethod=marker
