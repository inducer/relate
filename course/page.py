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
from django.utils.safestring import mark_safe
import django.forms as forms

from courseflow.utils import StyledForm, Struct

import re
import sys
import six


__doc__ = """

.. autoclass:: PageBase
.. autoclass:: AnswerFeedback
.. autoclass:: PageContext

"""


class PageContext(object):
    """
    .. attribute:: course
    .. attribute:: repo
    .. attribute:: commit_sha

    Note that this is different from :class:`course.utils.FlowPageContext`,
    which is used internally by the flow views.
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

class NoNormalizedAnswerAvailable(object):
    pass


def get_auto_feedback(correctness):
    if correctness == 0:
        return "Your answer is not correct."
    elif correctness == 1:
        return "Your answer is correct."
    elif correctness > 0.5:
        return "Your answer is mostly correct. (%.1f %%)" \
                % (100*correctness)
    elif correctness is None:
        return "(No information on correctness of answer.)"
    else:
        return "Your answer is somewhat correct. (%.1f %%)" \
                % (100*correctness)


class AnswerFeedback(object):
    """
    .. attribute:: correctness

        A :class:`float` between 0 and 1 (inclusive),
        indicating the degree of correctness of the
        answer. May be *None*.

    .. attribute:: feedback

        Text (at least as a full sentence, or even multi-paragraph HTML)
        providing feedback to the student about the provided answer. Should not
        reveal the correct answer.

        May be None, in which case generic feedback
        is generated from :attr:`correctness`.

    .. attribute:: normalized_answer

        An HTML-formatted answer to be shown in analytics,
        or a :class:`NoNormalizedAnswerAvailable`, or *None*
        if no answer was provided.
    """

    def __init__(self, correctness, feedback=None,
            normalized_answer=NoNormalizedAnswerAvailable()):
        if correctness is not None:
            if correctness < 0 or correctness > 1:
                raise ValueError("Invalid correctness value")

        if feedback is None:
            feedback = get_auto_feedback(correctness)

        self.correctness = correctness
        self.feedback = feedback
        self.normalized_answer = normalized_answer

    def as_json(self):
        result = {
                "correctness": self.correctness,
                "feedback": self.feedback,
                }

        if not isinstance(self.normalized_answer, NoNormalizedAnswerAvailable):
            result["normalized_answer"] = self.normalized_answer

        return result

    @staticmethod
    def from_json(json):
        return AnswerFeedback(
                correctness=json["correctness"],
                feedback=json["feedback"],
                normalized_answer=json.get("normalized_answer",
                    NoNormalizedAnswerAvailable())
                )

    def percentage(self):
        if self.correctness is not None:
            return 100*self.correctness
        else:
            return None

# }}}


# {{{ abstract page base class

class PageBase(object):
    """The abstract interface of a flow page.

    .. attribute:: location

        A string 'location' for reporting errors.

    .. attribute:: id

        The page identifier.

    .. automethod:: required_attrs
    .. automethod:: allowed_attrs

    .. automethod:: get_modified_permissions_for_page
    .. automethod:: make_page_data
    .. automethod:: title
    .. automethod:: body
    .. automethod:: expects_answer
    .. automethod:: max_points

    .. rubric:: Student Input

    .. automethod:: answer_data
    .. automethod:: make_form
    .. automethod:: post_form
    .. automethod:: form_to_html

    .. rubric:: Grader Input

    .. automethod:: make_grading_form
    .. automethod:: post_grading_form
    .. automethod:: update_grade_data_from_grading_form
    .. automethod:: grading_form_to_html

    .. rubric:: Grading/Feedback

    .. automethod:: grade
    .. automethod:: correct_answer
    """

    def __init__(self, vctx, location, page_desc):
        """
        :arg vctx: a :class:`course.validation.ValidationContext`, or None
            if no validation is desired
        """

        self.location = location

        if isinstance(page_desc, Struct):
            if vctx is not None:
                validate_struct(
                        vctx,
                        location,
                        page_desc,
                        required_attrs=self.required_attrs(),
                        allowed_attrs=self.allowed_attrs())

                # {{{ validate access_rules

                if hasattr(page_desc, "access_rules"):
                    ar_loc = "%s: access rules" % location
                    validate_struct(
                            vctx,
                            ar_loc,
                            page_desc.access_rules,
                            required_attrs=(),
                            allowed_attrs=(
                                ("add_permissions", list),
                                ("remove_permissions", list),
                                ))

                    from course.validation import validate_flow_permission
                    for attr in ["add_permissions", "remove_permissions"]:
                        if hasattr(page_desc.access_rules, attr):
                            for perm in page_desc.access_rules.add_permissions:
                                validate_flow_permission(
                                        vctx,
                                        "%s: %s" % (ar_loc, attr),
                                        perm)

                    # }}}

            self.page_desc = page_desc

        else:
            from warnings import warn
            warn("Not passing page_desc to PageBase.__init__ is deprecated",
                    DeprecationWarning)
            id = page_desc
            del page_desc

            self.id = id

    def required_attrs(self):
        """Required attributes, as accepted by
        :func:`course.validation.validate_struct`.
        Subclasses should only add to, not remove entries from this.
        """

        return (
            ("id", str),
            ("type", str),
            )

    def allowed_attrs(self):
        """Allowed attributes, as accepted by
        :func:`course.validation.validate_struct`.
        Subclasses should only add to, not remove entries from this.
        """

        return (
            ("access_rules", Struct),
            )

    def get_modified_permissions_for_page(self, permissions):
        permissions = set(permissions)

        if hasattr(self.page_desc, "access_rules"):
            if hasattr(self.page_desc.access_rules, "add_permissions"):
                for perm in self.page_desc.access_rules.add_permissions:
                    permissions.add(perm)

            if hasattr(self.page_desc.access_rules, "remove_permissions"):
                for perm in self.page_desc.access_rules.remove_permissions:
                    if perm in permissions:
                        permissions.remove(perm)

        return permissions

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

    # {{{ student input

    def answer_data(self, page_context, page_data, form, files_data):
        """Return a JSON-persistable object reflecting the user's answer on the
        form. This will be passed to methods below as *answer_data*.
        """
        raise NotImplementedError()

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        """
        :arg answer_data: value returned by :meth:`answer_data`.
             May be *None*.
        :return:
            a :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If *answer_is_final* is *True*, the form should be read-only.
        """

        raise NotImplementedError()

    def post_form(self, page_context, page_data, post_data, files_data):
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :return: a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If *answer_is_final* is *True*, the form should be read-only.
        """
        raise NotImplementedError()

    def form_to_html(self, request, page_context, form, answer_data):
        """Returns an HTML rendering of *form*."""

        from crispy_forms.utils import render_crispy_form
        from django.template import RequestContext
        context = RequestContext(request, {})
        return render_crispy_form(form, context=context)

    # }}}

    # {{{ grader input

    def make_grading_form(self, page_context, page_data, grade_data):
        """
        :arg grade_data: value returned by
            :meth:`update_grade_data_from_grading_form`.  May be *None*.
        :return:
            a :class:`django.forms.Form` instance with *grade_data* prepopulated.
        """
        return None

    def post_grading_form(self, page_context, page_data, grade_data,
            post_data, files_data):
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :return: a
            :class:`django.forms.Form` instance with *grade_data* prepopulated.
        """
        raise NotImplementedError()

    def update_grade_data_from_grading_form(self, page_context, page_data,
            grade_data, grading_form, files_data):
        """Return an updated version of *grade_data*, which is a
        JSON-persistable object reflecting data on grading of this response.
        This will be passed to other methods as *grade_data*.
        """

        return grade_data

    def grading_form_to_html(self, request, page_context, grading_form, grade_data):
        """Returns an HTML rendering of *grading_form*."""

        from crispy_forms.utils import render_crispy_form
        from django.template import RequestContext
        context = RequestContext(request, {})
        return render_crispy_form(grading_form, context=context)

    # }}}

    # {{{ grading/feedback

    def grade(self, page_context, page_data, answer_data, grade_data):
        """Grade the answer contained in *answer_data*.

        :arg answer_data: value returned by :meth:`answer_data`,
            or *None*, which means that no answer was supplied.
        :arg grade_data: value updated by
            :meth:`update_grade_data_from_grading_form`
        :return: a :class:`AnswerFeedback` instanstance, or *None* if the
            grade is not yet available.
        """

        raise NotImplementedError()

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        """The correct answer to this page's interaction, formatted as HTML,
        or *None*.
        """
        return None

    # }}}

# }}}


# {{{ utility base classes

class PageBaseWithTitle(PageBase):
    def required_attrs(self):
        return super(PageBaseWithTitle, self).required_attrs() + (
                ("title", str),
                )

    def title(self, page_context, page_data):
        return self.page_desc.title


class PageBaseWithValue(PageBase):
    def allowed_attrs(self):
        return super(PageBaseWithValue, self).allowed_attrs() + (
                ("value", (int, float)),
                )

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        return getattr(self.page_desc, "value", 1)


# {{{ human text feedback page base

class HumanTextFeedbackForm(StyledForm):
    released = forms.BooleanField(
            initial=False, required=False,
            help_text="Whether the grade and feedback below are to be shown "
            "to student")
    grade_percent = forms.FloatField(
            min_value=0,
            max_value=1000,  # allow excessive extra credit
            help_text="Grade assigned, in percent",
            required=False)
    feedback_text = forms.CharField(
            widget=forms.Textarea(),
            required=False,
            help_text="Feedback to be shown to student, using "
            "CourseFlow-flavored Markdown")
    notes = forms.CharField(
            widget=forms.Textarea(),
            help_text="Internal notes, not shown to student",
            required=False)

    def __init__(self, *args, **kwargs):
        super(HumanTextFeedbackForm, self).__init__(*args, **kwargs)


class PageBaseWithHumanTextFeedback(PageBase):
    grade_data_attrs = ["released", "grade_percent", "feedback_text", "notes"]

    def required_attrs(self):
        return super(PageBaseWithHumanTextFeedback, self).required_attrs() + (
                ("rubric", "markup"),
                )

    def make_grading_form(self, page_context, page_data, grade_data):
        if grade_data is not None:
            form_data = {}
            for k in self.grade_data_attrs:
                form_data[k] = grade_data[k]

            return HumanTextFeedbackForm(form_data)
        else:
            return HumanTextFeedbackForm()

    def post_grading_form(self, page_context, page_data, grade_data,
            post_data, files_data):
        return HumanTextFeedbackForm(post_data, files_data)

    def update_grade_data_from_grading_form(self, page_context, page_data,
            grade_data, grading_form, files_data):

        if grade_data is None:
            grade_data = {}
        for k in self.grade_data_attrs:
            grade_data[k] = grading_form.cleaned_data[k]

        return grade_data

    def grading_form_to_html(self, request, page_context, grading_form, grade_data):
        ctx = {
                "form": grading_form,
                "rubric": markup_to_html(page_context, self.page_desc.rubric)
                }

        from django.template import RequestContext
        from django.template.loader import render_to_string
        return render_to_string(
                "course/human-feedback-form.html",
                RequestContext(request, ctx))

    def grade(self, page_context, page_data, answer_data, grade_data):
        """This method is appropriate if the grade consists *only* of the
        feedback provided by humans. If more complicated/combined feedback
        is desired, a subclass would likely override this.
        """

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.")

        if grade_data is None:
            return None

        if not grade_data["released"]:
            return None

        if grade_data["grade_percent"] is not None:
            correctness = grade_data["grade_percent"]/100
            feedback_text = "<p>%s</p>" % get_auto_feedback(correctness)

            if grade_data["feedback_text"]:
                feedback_text += (
                        "<p>The following feedback was provided:<p>"
                        + markup_to_html(page_context, grade_data["feedback_text"]))

            return AnswerFeedback(
                    correctness=correctness,
                    feedback=feedback_text)
        else:
            return None


class PageBaseWithCorrectAnswer(PageBase):
    def allowed_attrs(self):
        return super(PageBaseWithCorrectAnswer, self).required_attrs() + (
            ("correct_answer", "markup"),
            )

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        if hasattr(self.page_desc, "correct_answer"):
            return markup_to_html(page_context, self.page_desc.correct_answer)
        else:
            return None

# }}}

# }}}


class Page(PageBaseWithCorrectAnswer, PageBaseWithTitle):
    """A page showing static content."""

    def required_attrs(self):
        return super(Page, self).required_attrs() + (
            ("content", "markup"),
            )

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.content)

    def expects_answer(self):
        return False


# {{{ text question

class TextAnswerForm(StyledForm):
    answer = forms.CharField(required=True)

    def __init__(self, matchers, *args, **kwargs):
        super(TextAnswerForm, self).__init__(*args, **kwargs)

        self.matchers = matchers

        self.fields["answer"].widget.attrs["autofocus"] = None

    def clean(self):
        cleaned_data = super(TextAnswerForm, self).clean()

        answer = cleaned_data.get("answer", "")
        for matcher in self.matchers:
            matcher.validate(answer)


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

            raise ValidationError("%s: regex '%s' did not compile: %s: %s"
                    % (location, pattern, tp.__name__, str(e)))

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
        except:
            tp, e, _ = sys.exc_info()
            raise ValidationError("%s: %s: %s"
                    % (location, tp.__name__, str(e)))

    def validate(self, s):
        try:
            parse_sympy(s)
        except:
            tp, e, _ = sys.exc_info()
            raise forms.ValidationError("%s: %s"
                    % (tp.__name__, str(e)))

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
            raise forms.ValidationError("%s: %s"
                    % (tp.__name__, str(e)))

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
                raise ValidationError("%s: %s only accepts '%s' patterns"
                        % (location, matcher_class.__name__, pattern_type))

            return matcher_class

    raise ValidationError("%s: unknown match type '%s'"
            % (location, matcher_type))


def parse_matcher_string(vctx, location, matcher_desc):
    match = MATCHER_RE.match(matcher_desc)

    if match is not None:
        matcher_type = match.group(1)
        pattern = match.group(2)
    else:
        match = MATCHER_RE_2.match(matcher_desc)

        if match is None:
            raise ValidationError("%s: does not specify match type"
                    % location)

        matcher_type = match.group(1)
        pattern = match.group(2)

        if vctx is not None:
            vctx.add_warning(location, "uses deprecated 'matcher:answer' style")

    return (get_matcher_class(location, matcher_type, "string")
            (vctx, location, pattern))


def parse_matcher(vctx, location, matcher_desc):
    if isinstance(matcher_desc, (str, unicode)):
        return parse_matcher_string(vctx, location, matcher_desc)
    else:
        if not isinstance(matcher_desc, Struct):
            raise ValidationError("%s: must be struct or string"
                    % location)

        if not hasattr(matcher_desc, "type"):
            raise ValidationError("%s: matcher must supply 'type'" % location)

        return (get_matcher_class(location, matcher_desc.type, "struct")
            (vctx, location, matcher_desc))

# }}}


class TextQuestion(PageBaseWithTitle, PageBaseWithValue):
    def __init__(self, vctx, location, page_desc):
        super(TextQuestion, self).__init__(vctx, location, page_desc)

        if len(page_desc.answers) == 0:
            raise ValidationError("%s: at least one answer must be provided"
                    % location)

        self.matchers = [
                parse_matcher(
                    vctx,
                    "%s, answer %d" % (location, i+1),
                    answer)
                for i, answer in enumerate(page_desc.answers)]

        if not any(matcher.correct_answer_text() is not None
                for matcher in self.matchers):
            raise ValidationError("%s: no matcher is able to provide a plain-text "
                    "correct answer" % location)

    def required_attrs(self):
        return super(TextQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("answers", list),
                )

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = TextAnswerForm(self.matchers, answer)
        else:
            answer = None
            form = TextAnswerForm(self.matchers)

        if answer_is_final:
            form.fields['answer'].widget.attrs['readonly'] = True

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        return TextAnswerForm(self.matchers, post_data, files_data)

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.")

        answer = answer_data["answer"]

        correctness, correct_answer_text = max(
                (matcher.grade(answer), matcher.correct_answer_text())
                for matcher in self.matchers)

        normalized_answer = answer
        if not any(matcher.is_case_sensitive for matcher in self.matchers):
            normalized_answer = normalized_answer.lower()

        return AnswerFeedback(
                correctness=correctness,
                normalized_answer=normalized_answer)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        # FIXME: Could use 'best' match to answer

        CA_PATTERN = "A correct answer is: '%s'."

        for matcher in self.matchers:
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text

        return CA_PATTERN % unspec_correct_answer_text

# }}}


# {{{ choice question

class ChoiceAnswerForm(StyledForm):
    def __init__(self, field, *args, **kwargs):
        super(ChoiceAnswerForm, self).__init__(*args, **kwargs)

        self.fields["choice"] = field


class ChoiceQuestion(PageBaseWithTitle, PageBaseWithValue):
    CORRECT_TAG = "~CORRECT~"

    @classmethod
    def process_choice_string(cls, page_context, s):
        s = remove_prefix(cls.CORRECT_TAG, s)
        s = markup_to_html(page_context, s)
        # allow HTML in option
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, page_desc):
        super(ChoiceQuestion, self).__init__(vctx, location, page_desc)

        correct_choice_count = 0
        for choice_idx, choice in enumerate(page_desc.choices):
            if not isinstance(choice, six.string_types):
                raise ValidationError("%s, choice %d: not a string"
                        % (location, choice_idx+1))

            if choice.startswith(self.CORRECT_TAG):
                correct_choice_count += 1

            if vctx is not None:
                validate_markup(vctx, location,
                        remove_prefix(self.CORRECT_TAG, choice))

        if correct_choice_count < 1:
            raise ValidationError("%s: one or more correct answer(s) "
                    "expected, %d found" % (location, correct_choice_count))

    def required_attrs(self):
        return super(ChoiceQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("choices", list),
                )

    def allowed_attrs(self):
        return super(ChoiceQuestion, self).allowed_attrs() + (
                ("shuffle", bool),
                )

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
            if choice_text.startswith(self.CORRECT_TAG):
                result.append(i)

        return result

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    normalized_answer=None)

        permutation = page_data["permutation"]
        choice = answer_data["choice"]

        if permutation[choice] in self.unpermuted_correct_indices():
            correctness = 1
        else:
            correctness = 0

        return AnswerFeedback(correctness=correctness,
                normalized_answer=self.process_choice_string(
                    page_context,
                    self.page_desc.choices[permutation[choice]]))

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        corr_idx = self.unpermuted_correct_indices()[0]
        return ("A correct answer is:%s"
                % self.process_choice_string(
                    page_context,
                    self.page_desc.choices[corr_idx]).lstrip())

# }}}


# {{{ python code question

class PythonCodeForm(StyledForm):
    def __init__(self, read_only, initial_code, *args, **kwargs):
        super(PythonCodeForm, self).__init__(*args, **kwargs)

        from codemirror import CodeMirrorTextarea, CodeMirrorJavascript

        self.fields["answer"] = forms.CharField(required=True,
            widget=CodeMirrorTextarea(
                mode="python",
                theme="default",
                config={
                    "fixedGutter": True,
                    "indentUnit": 4,
                    "readOnly": read_only,
                    "extraKeys": CodeMirrorJavascript("""
                        {
                          "Tab": function(cm)
                          {
                            var spaces = \
                                    Array(cm.getOption("indentUnit") + 1).join(" ");
                            cm.replaceSelection(spaces);
                          }
                        }
                    """)
                    }),
                initial=initial_code)

    def clean(self):
        # FIXME Should try compilation
        pass


CFRUNPY_PORT = 9941


class InvalidPingResponse(RuntimeError):
    pass


def request_python_run(run_req, run_timeout):
    import json
    import httplib
    from django.conf import settings
    import docker
    import socket
    import errno
    from httplib import BadStatusLine
    from docker.errors import APIError as DockerAPIError

    debug = False
    if debug:
        def debug_print(s):
            print s
    else:
        def debug_print(s):
            pass

    docker_timeout = 15

    # DEBUGGING SWITCH: 1 for 'spawn container', 0 for 'static container'
    if 1:
        docker_cnx = docker.Client(
                base_url='unix://var/run/docker.sock',
                version='1.12', timeout=docker_timeout)

        dresult = docker_cnx.create_container(
                image=settings.CF_DOCKER_CFRUNPY_IMAGE,
                command=[
                    "/opt/cfrunpy/cfrunpy",
                    "-1"],
                mem_limit=256e6,
                user="cfrunpy")

        container_id = dresult["Id"]
    else:
        container_id = None

    try:
        # FIXME: Prohibit networking

        if container_id is not None:
            docker_cnx.start(
                    container_id,
                    port_bindings={CFRUNPY_PORT: ('127.0.0.1',)})

            port_info, = docker_cnx.port(container_id, CFRUNPY_PORT)
            port = int(port_info["HostPort"])
        else:
            port = CFRUNPY_PORT

        from time import time, sleep
        start_time = time()

        # {{{ ping until response received

        while True:
            try:
                connection = httplib.HTTPConnection('localhost', port)

                connection.request('GET', '/ping')

                response = connection.getresponse()
                response_data = response.read().decode("utf-8")

                if response_data != b"OK":
                    raise InvalidPingResponse()

                break

            except socket.error as e:
                from traceback import format_exc

                if e.errno in [errno.ECONNRESET, errno.ECONNREFUSED]:
                    if time() - start_time < docker_timeout:
                        sleep(0.1)
                        # and retry
                    else:
                        return {
                                "result": "uncaught_error",
                                "message": "Timeout waiting for container.",
                                "traceback": "".join(format_exc()),
                                }
                else:
                    raise

            except (BadStatusLine, InvalidPingResponse):
                if time() - start_time < docker_timeout:
                    sleep(0.1)
                    # and retry
                else:
                    return {
                            "result": "uncaught_error",
                            "message": "Timeout waiting for container.",
                            "traceback": "".join(format_exc()),
                            }

        # }}}

        debug_print("PING SUCCESSFUL")

        try:
            # Add a second to accommodate 'wire' delays
            connection = httplib.HTTPConnection('localhost', port,
                    timeout=1 + run_timeout)

            headers = {'Content-type': 'application/json'}

            json_run_req = json.dumps(run_req).encode("utf-8")

            debug_print("BEFPOST")
            connection.request('POST', '/run-python', json_run_req, headers)
            debug_print("AFTPOST")

            http_response = connection.getresponse()
            debug_print("GETR")
            response_data = http_response.read().decode("utf-8")
            debug_print("READR")
            return json.loads(response_data)

        except socket.timeout:
            return {"result": "timeout"}

    finally:
        if container_id is not None:
            debug_print("-----------BEGIN DOCKER LOGS for %s" % container_id)
            debug_print(docker_cnx.logs(container_id))
            debug_print("-----------END DOCKER LOGS for %s" % container_id)

            try:
                docker_cnx.remove_container(container_id, force=True)
            except DockerAPIError:
                # Oh well. No need to bother the students with this nonsense.
                pass


class PythonCodeQuestion(PageBaseWithTitle, PageBaseWithValue):
    def required_attrs(self):
        return super(PythonCodeQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("timeout", (int, float)),
                )

    def allowed_attrs(self):
        return super(PythonCodeQuestion, self).allowed_attrs() + (
                ("setup_code", str),
                ("names_for_user", list),
                ("names_from_user", list),
                ("test_code", str),
                ("correct_code", str),
                ("initial_code", str),
                )

    def _initial_code(self):
        result = getattr(self.page_desc, "initial_code", None)
        if result is not None:
            return result.strip()
        else:
            return result

    def body(self, page_context, page_data):
        from django.template.loader import render_to_string
        return render_to_string(
                "course/prompt-code-question.html",
                {
                    "prompt_html":
                    markup_to_html(page_context, self.page_desc.prompt),
                    "initial_code": self._initial_code()
                    })

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        if answer_data is not None:
            answer = {"answer": answer_data["answer"]}
            form = PythonCodeForm(
                    answer_is_final,
                    self._initial_code(),
                    answer)
        else:
            answer = None
            form = PythonCodeForm(
                    answer_is_final,
                    self._initial_code(),
                    )

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        return PythonCodeForm(
                False,
                self._initial_code(),
                post_data, files_data)

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data["answer"].strip()}

    def grade(self, page_context, page_data, answer_data, grade_data):
        from courseflow.utils import html_escape

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.",
                    normalized_answer=None)

        user_code = answer_data["answer"]

        # {{{ request run

        run_req = {"compile_only": False, "user_code": user_code}

        def transfer_attr(name):
            if hasattr(self.page_desc, name):
                run_req[name] = getattr(self.page_desc, name)

        transfer_attr("setup_code")
        transfer_attr("names_for_user")
        transfer_attr("names_from_user")
        transfer_attr("test_code")

        try:
            response_dict = request_python_run(run_req,
                    run_timeout=self.page_desc.timeout)
        except:
            from traceback import format_exc
            response_dict = {
                    "result": "uncaught_error",
                    "message": "Error connecting to container",
                    "traceback": "".join(format_exc()),
                    }

        # }}}

        # {{{ send email if the grading code broke

        if response_dict["result"] in [
                "uncaught_error",
                "setup_compile_error",
                "setup_error",
                "test_compile_error",
                "test_error"]:
            error_msg_parts = ["RESULT: %s" % response_dict["result"]]
            for key, val in sorted(response_dict.items()):
                if key != "result" and val:
                    error_msg_parts.append("-------------------------------------")
                    error_msg_parts.append(key)
                    error_msg_parts.append("-------------------------------------")
                    error_msg_parts.append(val)
            error_msg_parts.append("-------------------------------------")
            error_msg_parts.append("user code")
            error_msg_parts.append("-------------------------------------")
            error_msg_parts.append(user_code)
            error_msg_parts.append("-------------------------------------")

            error_msg = "\n".join(error_msg_parts)

            from django.template.loader import render_to_string
            message = render_to_string("course/broken-code-question-email.txt", {
                "page_id": self.page_desc.id,
                "course": page_context.course,
                "error_message": error_msg,
                })

            from django.core.mail import send_mail
            from django.conf import settings
            send_mail("[%s] code question execution failed"
                    % page_context.course.identifier,
                    message,
                    settings.ROBOT_EMAIL_FROM,
                    recipient_list=[page_context.course.email])

        # }}}

        from courseflow.utils import dict_to_struct
        response = dict_to_struct(response_dict)

        feedback_bits = []
        if hasattr(response, "points"):
            correctness = response.points
            feedback_bits.append(
                    "<p><b>%s</b></p>"
                    % get_auto_feedback(correctness))
        else:
            correctness = None

        if response.result == "success":
            pass
        elif response.result in [
                "uncaught_error",
                "setup_compile_error",
                "setup_error",
                "test_compile_error",
                "test_error"]:
            feedback_bits.append(
                    "<p>The grading code failed. Sorry about that. "
                    "The staff has been informed, and if this problem is due "
                    "to an issue with the grading code, "
                    "it will be fixed as soon as possible. "
                    "In the meantime, you'll see a traceback "
                    "below that may help you figure out what went wrong.</p>")
        elif response.result == "timeout":
            feedback_bits.append(
                    "<p>Your code took too long to execute. The problem "
                    "specifies that your code may take at most %s seconds to run. "
                    "It took longer than that and was aborted.</p>"
                    % self.page_desc.timeout)

            correctness = 0
        elif response.result == "user_compile_error":
            feedback_bits.append(
                    "<p>Your code failed to compile. An error message is below.</p>")

            correctness = 0
        elif response.result == "user_error":
            feedback_bits.append(
                    "<p>Your code failed with an exception. "
                    "A traceback is below.</p>")

            correctness = 0
        else:
            raise RuntimeError("invalid cfrunpy result: %s" % response.result)

        if hasattr(response, "feedback") and response.feedback:
            feedback_bits.append(
                    "<p>Here is some feedback on your code:"
                    "<ul>%s</ul></p>" % "".join(
                        "<li>%s</li>" % html_escape(fb_item)
                        for fb_item in response.feedback))
        if hasattr(response, "traceback") and response.traceback:
            feedback_bits.append(
                    "<p>This is the exception traceback:"
                    "<pre>%s</pre></p>" % html_escape(response.traceback))
            print repr(response.traceback)
        if hasattr(response, "stdout") and response.stdout:
            feedback_bits.append(
                    "<p>Your code printed the following output:<pre>%s</pre></p>"
                    % html_escape(response.stdout))
        if hasattr(response, "stderr") and response.stderr:
            feedback_bits.append(
                    "<p>Your code printed the following error messages:"
                    "<pre>%s</pre></p>" % html_escape(response.stderr))
        if hasattr(response, "figures"):
            fig_lines = [
                    "<p>Your code produced the following plots:</p>",
                    '<dl class="result-figure-list">',
                    ]

            for nr, mime_type, b64data in response.figures:
                fig_lines.extend([
                        "<dt>Figure %d<dt>" % nr,
                        '<dd><img alt="Figure %d" src="data:%s;base64,%s"></dd>'
                        % (nr, mime_type, b64data)])

            fig_lines.append("</dl>")
            feedback_bits.extend(fig_lines)

        return AnswerFeedback(
                correctness=correctness,
                feedback="\n".join(feedback_bits),
                normalized_answer="<pre>%s</pre>" % user_code)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        from courseflow.utils import html_escape

        if hasattr(self.page_desc, "correct_code"):
            return (
                    "The following code is a valid answer:<pre>%s</pre>"
                    % html_escape(self.page_desc.correct_code))
        else:
            return None

# }}}


# {{{ python code question with human feedback

class PythonCodeQuestionWithHumanTextFeedback(
        PythonCodeQuestion, PageBaseWithHumanTextFeedback):

    def __init__(self, vctx, location, page_desc):
        super(PythonCodeQuestionWithHumanTextFeedback, self).__init__(
                vctx, location, page_desc)

        if (vctx is not None
                and self.page_desc.human_feedback_value > self.page_desc.value):
            raise ValidationError(
                    "human_feedback_value greater than overall "
                    "value of question")

    def required_attrs(self):
        return super(
                PythonCodeQuestionWithHumanTextFeedback, self).required_attrs() + (
                        # value is otherwise optional, but we require it here
                        ("value", (int, float)),
                        ("human_feedback_value", (int, float)),
                        )

    def grade(self, page_context, page_data, answer_data, grade_data):
        """This method is appropriate if the grade consists *only* of the
        feedback provided by humans. If more complicated/combined feedback
        is desired, a subclass would likely override this.
        """

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback="No answer provided.")

        if grade_data is not None and not grade_data["released"]:
            grade_data = None

        code_feedback = PythonCodeQuestion.grade(self, page_context,
                page_data, answer_data, grade_data)

        correctness = None
        percentage = None
        if (code_feedback is not None
                and code_feedback.correctness is not None
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            correctness = (
                    code_feedback.correctness
                    * (self.page_desc.value - self.page_desc.human_feedback_value)

                    + grade_data["grade_percent"] / 100
                    * self.page_desc.human_feedback_value
                    ) / self.page_desc.value
            percentage = correctness * 100
        elif (self.page_desc.human_feedback_value == self.page_desc.value
                and grade_data is not None
                and grade_data["grade_percent"] is not None):
            correctness = grade_data["grade_percent"] / 100
            percentage = correctness * 100

        human_feedback_percentage = None
        human_feedback_text = None

        if grade_data is not None:
            if grade_data["feedback_text"] is not None:
                human_feedback_text = markup_to_html(
                        page_context, grade_data["feedback_text"])

            human_feedback_percentage = grade_data["grade_percent"]

        from django.template.loader import render_to_string
        feedback = render_to_string(
                "course/feedback-code-with-human.html",
                {
                    "percentage": percentage,
                    "code_feedback": code_feedback,
                    "human_feedback_text": human_feedback_text,
                    "human_feedback_percentage": human_feedback_percentage,
                    })

        return AnswerFeedback(
                correctness=correctness,
                feedback=feedback)

# }}}


# {{{ upload question

class FileUploadForm(StyledForm):
    uploaded_file = forms.FileField(required=True)

    def __init__(self, maximum_megabytes, mime_types, *args, **kwargs):
        super(FileUploadForm, self).__init__(*args, **kwargs)

        self.max_file_size = maximum_megabytes * 1024**2
        self.mime_types = mime_types

    def clean_uploaded_file(self):
        uploaded_file = self.cleaned_data['uploaded_file']
        if uploaded_file.content_type in self.mime_types:
            from django.template.defaultfilters import filesizeformat

            if uploaded_file._size > self.max_file_size:
                raise forms.ValidationError(
                        "Please keep file size under %s. "
                        "Current filesize is %s."
                        % (filesizeformat(self.max_file_size),
                            filesizeformat(uploaded_file._size)))
        else:
            raise forms.ValidationError("File has unsupported type"
                    "--must be one of: %s" % (", ".join(self.mime_types)))

        return uploaded_file


class FileUploadQuestion(PageBaseWithTitle, PageBaseWithValue,
        PageBaseWithHumanTextFeedback, PageBaseWithCorrectAnswer):
    ALLOWED_MIME_TYPES = [
            "application/pdf",
            ]

    def __init__(self, vctx, location, page_desc):
        super(FileUploadQuestion, self).__init__(vctx, location, page_desc)

        if not (set(page_desc.mime_types) <= set(self.ALLOWED_MIME_TYPES)):
            raise ValidationError("%s: unrecognized mime types '%s'"
                    % (location, ", ".join(
                        set(page_desc.mime_types) - set(self.ALLOWED_MIME_TYPES))))

    def required_attrs(self):
        return super(FileUploadQuestion, self).required_attrs() + (
                ("prompt", "markup"),
                ("mime_types", list),
                ("maximum_megabytes", (int, float)),
                )

    def allowed_attrs(self):
        return super(FileUploadQuestion, self).allowed_attrs() + (
                ("correct_answer", "markup"),
                )

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    @staticmethod
    def files_data_to_answer_data(files_data):
        files_data["uploaded_file"].seek(0)
        buf = files_data["uploaded_file"].read()

        from base64 import b64encode
        return {
                "base64_data": b64encode(buf),
                "mime_type": files_data["uploaded_file"].content_type,
                }

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        form = FileUploadForm(
                self.page_desc.maximum_megabytes, self.page_desc.mime_types)
        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        form = FileUploadForm(
                self.page_desc.maximum_megabytes, self.page_desc.mime_types,
                post_data, files_data)
        return form

    def form_to_html(self, request, page_context, form, answer_data):
        ctx = {"form": form}
        if answer_data is not None:
            ctx["mime_type"] = answer_data["mime_type"]
            ctx["data_url"] = "data:%s;base64,%s" % (
                answer_data["mime_type"],
                answer_data["base64_data"],
                )

        from django.template import RequestContext
        from django.template.loader import render_to_string
        return render_to_string(
                "course/file-upload-form.html",
                RequestContext(request, ctx))

    def answer_data(self, page_context, page_data, form, files_data):
        return self.files_data_to_answer_data(files_data)

# }}}


# vim: foldmethod=marker
