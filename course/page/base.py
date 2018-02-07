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

import six

import django.forms as forms

from course.validation import validate_struct, ValidationError
from course.constants import MAX_EXTRA_CREDIT_FACTOR
from relate.utils import StyledForm, Struct, string_concat
from django.forms import ValidationError as FormValidationError
from django.utils.safestring import mark_safe
from django.utils.functional import lazy
from django.utils.translation import (
        ugettext_lazy as _,
        ugettext,
        )
from django.utils import translation
from django.conf import settings

# {{{ mypy

if False:
    from typing import Text, Optional, Any, Tuple, Dict, Callable, FrozenSet  # noqa
    from django import http  # noqa
    from course.models import (  # noqa
            Course,
            FlowSession
            )
    from course.content import Repo_ish  # noqa

# }}}


mark_safe_lazy = lazy(mark_safe, six.text_type)


class PageContext(object):
    """
    .. attribute:: course
    .. attribute:: repo
    .. attribute:: commit_sha
    .. attribute:: flow_session

        May be None.

    .. attribute:: page_uri

    Note that this is different from :class:`course.utils.FlowPageContext`,
    which is used internally by the flow views.
    """

    def __init__(
            self,
            course,  # type: Course
            repo,  # type: Repo_ish
            commit_sha,  # type: bytes
            flow_session,  # type: FlowSession
            in_sandbox=False,  # type: bool
            page_uri=None,  # type: Optional[str]
            ):
        # type: (...) -> None

        self.course = course
        self.repo = repo
        self.commit_sha = commit_sha
        self.flow_session = flow_session
        self.in_sandbox = in_sandbox
        self.page_uri = page_uri


class PageBehavior(object):
    """
    .. attribute:: show_correctness
    .. attribute:: show_answer
    .. attribute:: may_change_answer
    """

    def __init__(
            self,
            show_correctness,  # type: bool
            show_answer,  # type: bool
            may_change_answer,  # type:bool
            ):
        # type: (...) -> None

        self.show_correctness = show_correctness
        self.show_answer = show_answer
        self.may_change_answer = may_change_answer

    def __bool__(self):
        # This is for compatiblity: page_behavior used to be a bool argument
        # 'answer_is_final'.
        return not self.may_change_answer

    __nonzero__ = __bool__


def markup_to_html(
        page_context,  # type: PageContext
        text,  # type: Text
        use_jinja=True,  # type: bool
        reverse_func=None,  # type: Callable
        ):
    # type: (...) -> Text
    from course.content import markup_to_html as mth

    return mth(
            page_context.course,
            page_context.repo,
            page_context.commit_sha,
            text,
            use_jinja=use_jinja,
            reverse_func=reverse_func)


# {{{ answer feedback type

def get_auto_feedback(correctness):
    # type: (Optional[float]) -> Text
    if correctness is None:
        return six.text_type(_("No information on correctness of answer."))
    elif abs(correctness - 0) < 1e-5:
        return six.text_type(_("Your answer is not correct."))
    elif abs(correctness - 1) < 1e-5:
        return six.text_type(_("Your answer is correct."))
    elif correctness > 1:
        return six.text_type(
                string_concat(
                    _("Your answer is correct and earned bonus points."),
                    " (%.1f %%)")
                % (100*correctness))
    elif correctness > 0.5:
        return six.text_type(
                string_concat(
                    _("Your answer is mostly correct."),
                    " (%.1f %%)")
                % (100*correctness))
    else:
        return six.text_type(
                string_concat(
                    _("Your answer is somewhat correct. "),
                    "(%.1f%%)")
                % (100*correctness))


class AnswerFeedback(object):
    """
    .. attribute:: correctness

        A non-negative :class:`float` value, normally
        between 0 and 1 (inclusive), and it can be increased to at most 10
        (`course.constants.MAX_EXTRA_CREDIT_FACTOR`).
        It indicates the degree of correctness of the
        answer. May be *None*.

    .. attribute:: feedback

        Text (at least as a full sentence, or even multi-paragraph HTML)
        providing feedback to the student about the provided answer. Should not
        reveal the correct answer.

        May be None, in which case generic feedback
        is generated from :attr:`correctness`.

    .. attribute:: bulk_feedback
    """

    def __init__(self, correctness, feedback=None, bulk_feedback=None):
        # type: (Optional[float], Optional[Text], Optional[Text]) -> None

        if correctness is not None:
            # allow for extra credit
            if correctness < 0 or correctness > MAX_EXTRA_CREDIT_FACTOR:
                raise ValueError(_("Invalid correctness value"))

        if feedback is None:
            feedback = get_auto_feedback(correctness)

        self.correctness = correctness
        self.feedback = feedback
        self.bulk_feedback = bulk_feedback

    def as_json(self):
        # type: () -> Tuple[Dict[Text, Any], Dict[Text, Any]]
        result = {
                "correctness": self.correctness,
                "feedback": self.feedback,
                }
        bulk_result = {
                "bulk_feedback": self.bulk_feedback,
                }

        return result, bulk_result

    @staticmethod
    def from_json(json, bulk_json):
        # type: (Any, Any) -> Optional[AnswerFeedback]

        if json is None:
            return json

        if bulk_json is not None:
            bulk_feedback = bulk_json.get("bulk_feedback")
        else:
            bulk_feedback = None

        return AnswerFeedback(
                correctness=json["correctness"],
                feedback=json["feedback"],
                bulk_feedback=bulk_feedback,
                )

    def percentage(self):
        # type: () -> Optional[float]

        if self.correctness is not None:
            return 100*self.correctness
        else:
            return None

# }}}


# {{{ abstract page base class

class InvalidPageData(RuntimeError):
    pass


class PageBase(object):
    """The abstract interface of a flow page.

    .. attribute:: location

        A string 'location' for reporting errors.

    .. attribute:: id

        The page identifier.

    .. automethod:: required_attrs
    .. automethod:: allowed_attrs

    .. automethod:: get_modified_permissions_for_page
    .. automethod:: initialize_page_data
    .. automethod:: title
    .. automethod:: body

    .. automethod:: expects_answer
    .. automethod:: is_answer_gradable
    .. automethod:: max_points

    .. rubric:: Student Input

    .. automethod:: answer_data
    .. automethod:: make_form
    .. automethod:: process_form_post
    .. automethod:: form_to_html

    .. rubric:: Grader Input

    .. automethod:: make_grading_form
    .. automethod:: post_grading_form
    .. automethod:: update_grade_data_from_grading_form_v2
    .. automethod:: grading_form_to_html

    .. rubric:: Grading/Feedback

    .. automethod:: grade
    .. automethod:: correct_answer
    .. automethod:: normalized_answer
    .. automethod:: normalized_bytes_answer
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
                            for perm in getattr(page_desc.access_rules, attr):
                                validate_flow_permission(
                                        vctx,
                                        "%s: %s" % (ar_loc, attr),
                                        perm)

                    # }}}

            self.page_desc = page_desc
            self.is_optional_page = getattr(page_desc, "is_optional_page", False)

        else:
            from warnings import warn
            warn(_("Not passing page_desc to PageBase.__init__ is deprecated"),
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
            ("is_optional_page", bool),
            )

    def get_modified_permissions_for_page(self, permissions):
        # type: (FrozenSet[Text]) -> FrozenSet[Text]
        rw_permissions = set(permissions)

        if hasattr(self.page_desc, "access_rules"):
            if hasattr(self.page_desc.access_rules, "add_permissions"):
                for perm in self.page_desc.access_rules.add_permissions:
                    rw_permissions.add(perm)

            if hasattr(self.page_desc.access_rules, "remove_permissions"):
                for perm in self.page_desc.access_rules.remove_permissions:
                    if perm in rw_permissions:
                        rw_permissions.remove(perm)

        return frozenset(rw_permissions)

    def make_page_data(self):
        # type: () -> Dict
        return {}

    def initialize_page_data(self, page_context):
        # type: (PageContext) -> Dict
        """Return (possibly randomly generated) data that is used to generate
        the content on this page. This is passed to methods below as the *page_data*
        argument. One possible use for this argument would be a random permutation
        of choices that is generated once (at flow setup) and then used whenever
        this page is shown.
        """
        data = self.make_page_data()
        if data:
            from warnings import warn
            warn(_("%s is using the make_page_data compatiblity hook, which "
                 "is deprecated.") % type(self).__name__,
                 DeprecationWarning)

        return data

    def title(self, page_context, page_data):
        # type: (PageContext, Dict) -> str

        """Return the (non-HTML) title of this page."""

        raise NotImplementedError()

    def body(self, page_context, page_data):
        # type: (PageContext, Dict) -> str

        """Return the (HTML) body of the page."""

        raise NotImplementedError()

    def expects_answer(self):
        # type: () -> bool

        """
        :return: a :class:`bool` indicating whether this page lets the
            user provide an answer of some type.
        """
        raise NotImplementedError()

    def is_answer_gradable(self):
        # type: () -> bool
        """
        :return: a :class:`bool` indicating whether answers on this can
            have :meth:`grade` called on them.

        True by default.
        """
        return True

    def max_points(self, page_data):
        # type: (Any) -> float
        """
        :return: a :class:`int` or :class:`float` indicating how many points
            are achievable on this page.
        """
        raise NotImplementedError()

    # {{{ student input

    def answer_data(
            self,
            page_context,  # type:  PageContext
            page_data,  # type: Any
            form,  # type: forms.Form
            files_data,  # type: Any
            ):
        # type: (...) -> Any
        """Return a JSON-persistable object reflecting the user's answer on the
        form. This will be passed to methods below as *answer_data*.
        """
        raise NotImplementedError()

    def make_form(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            answer_data,  # type: Any
            page_behavior,  # type: Any
            ):
        """
        :arg answer_data: value returned by :meth:`answer_data`.
             May be *None*.
        :arg page_behavior: an instance of :class:`PageBehavior`
        :return:
            a :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If ``page_behavior.may_change_answer`` is *False*, the form should
            be read-only.
        """

        raise NotImplementedError()

    def post_form(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            post_data,  # type: Any
            files_data  # type: Any
            ):
        # type: (...) -> forms.Form
        raise NotImplementedError()

    def process_form_post(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            post_data,  # type: Any
            files_data,  # type: Any
            page_behavior,  # type: PageBehavior
            ):
        # type: (...) -> forms.Form
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :arg page_behavior: an instance of :class:`PageBehavior`
        :return: a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If ``page_behavior.may_change_answer`` is *False*, the form should
            be read-only.
        """

        from warnings import warn
        warn(_("%s is using the post_form compatiblity hook, which "
                "is deprecated.") % type(self).__name__,
                DeprecationWarning)

        return self.post_form(page_context, page_data, post_data, files_data)

    def form_to_html(
            self,
            request,  # type: http.HttpRequest
            page_context,  # type: PageContext
            form,  # type: StyledForm
            answer_data,  # type: Any
            ):
        """Returns an HTML rendering of *form*."""

        from django.template import loader, RequestContext
        from django import VERSION as django_version  # noqa

        if django_version >= (1, 9):
            return loader.render_to_string(
                    "course/crispy-form.html",
                    context={"form": form},
                    request=request)
        else:
            context = RequestContext(request)
            context.update({"form": form})
            return loader.render_to_string(
                    "course/crispy-form.html",
                    context_instance=context)

    # }}}

    # {{{ grader input

    def make_grading_form(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            grade_data  # type: Any
            ):
        # type: (...) -> forms.Form
        """
        :arg grade_data: value returned by
            :meth:`update_grade_data_from_grading_form_v2`.  May be *None*.
        :return:
            a :class:`django.forms.Form` instance with *grade_data* prepopulated.
        """
        return None

    def post_grading_form(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            grade_data,  # type: Any
            post_data,  # type: Any
            files_data  # type: Any
            ):
        # type: (...) -> forms.Form
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :return: a
            :class:`django.forms.Form` instance with *grade_data* prepopulated.
        """
        raise NotImplementedError()

    def update_grade_data_from_grading_form_v2(
            self,
            request,  # type: http.HttpRequest
            page_context,  # type: PageContext
            page_data,  # type: Any
            grade_data,  # type: Any
            grading_form,  # type: Any
            files_data  # type: Any
            ):
        """Return an updated version of *grade_data*, which is a
        JSON-persistable object reflecting data on grading of this response.
        This will be passed to other methods as *grade_data*.
        """

        from warnings import warn
        warn(_("%s is using the update_grade_data_from_grading_form "
               "compatiblity hook, which "
                "is deprecated.") % type(self).__name__,
                DeprecationWarning)

        return self.update_grade_data_from_grading_form(
                page_context, page_data, grade_data, grading_form, files_data)

    def update_grade_data_from_grading_form(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            grade_data,  # type: Any
            grading_form,  # type: Any
            files_data  # type: Any
            ):

        return grade_data

    def grading_form_to_html(
            self,
            request,  # type: http.HttpRequest
            page_context,  # type: PageContext
            grading_form,  # type: Any
            grade_data  # type: Any
            ):
        # type: (...) -> Text
        """Returns an HTML rendering of *grading_form*."""

        from crispy_forms.utils import render_crispy_form
        from django.template import RequestContext
        context = RequestContext(request, {})
        return render_crispy_form(grading_form, context=context)

    # }}}

    # {{{ grading/feedback

    def grade(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            answer_data,  # type: Any
            grade_data,  # type: Any
            ):
        # type: (...) -> Optional[AnswerFeedback]
        """Grade the answer contained in *answer_data*.

        :arg answer_data: value returned by :meth:`answer_data`,
            or *None*, which means that no answer was supplied.
        :arg grade_data: value updated by
            :meth:`update_grade_data_from_grading_form_v2`
        :return: a :class:`AnswerFeedback` instanstance, or *None* if the
            grade is not yet available.
        """

        raise NotImplementedError()

    def correct_answer(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            answer_data,  # type: Any
            grade_data,  # type: Any
            ):
        # type: (...) -> Optional[Text]
        """The correct answer to this page's interaction, formatted as HTML,
        or *None*.
        """
        return None

    def normalized_answer(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            answer_data  # type: Any
            ):
        # type: (...) -> Optional[Text]
        """An HTML-formatted answer to be used for summarization and
        display in analytics.
        """
        return None

    def normalized_bytes_answer(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            answer_data,  # type: Any
            ):
        # type: (...) -> Optional[Tuple[Text, bytes]]
        """An answer to be used for batch download, given as a batch of bytes
        to be stuffed in a zip file.

        :returns: a tuple of ``(file_ext, data)`` where *file_ext* is a suggested
            file extension (inlcuding the leading period, if applicable).
            May also return *None*.

        One use case of this function is to work as input for a plagiarism
        checker.
        """
        return None

    # }}}

# }}}


# {{{ utility base classes


class PageBaseWithTitle(PageBase):
    def __init__(self, vctx, location, page_desc):
        super(PageBaseWithTitle, self).__init__(vctx, location, page_desc)

        title = None
        try:
            title = self.page_desc.title
        except AttributeError:
            pass

        if title is None:
            try:
                md_body = self.markup_body_for_title()
            except NotImplementedError:
                from warnings import warn
                warn(_("PageBaseWithTitle subclass '%s' does not implement "
                        "markdown_body_for_title()")
                        % type(self).__name__)
            else:
                from course.content import extract_title_from_markup
                title = extract_title_from_markup(md_body)

        if title is None:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("no title found in body or title attribute"))
                    % (location))

        self._title = title

    def allowed_attrs(self):
        return super(PageBaseWithTitle, self).allowed_attrs() + (
                ("title", str),
                )

    def markup_body_for_title(self):
        raise NotImplementedError()

    def title(self, page_context, page_data):
        return self._title


class PageBaseWithValue(PageBase):
    def __init__(self, vctx, location, page_desc):
        super(PageBaseWithValue, self).__init__(vctx, location, page_desc)

        if vctx is not None:
            if hasattr(page_desc, "value") and self.is_optional_page:
                raise ValidationError(
                    string_concat(
                        location,
                        _("Attribute 'value' should be removed when "
                          "'is_optional_page' is True.")))

    def allowed_attrs(self):
        return super(PageBaseWithValue, self).allowed_attrs() + (
                ("value", (int, float)),
                )

    def expects_answer(self):
        return True

    def max_points(self, page_data):
        if self.is_optional_page:
            return 0
        return getattr(self.page_desc, "value", 1)


# }}}


# {{{ human text feedback page base

def create_default_point_scale(total_points):
    """
    Return a scale that has sensible intervals for assigning points.
    """
    if total_points <= 5:
        incr = 0.25
    elif total_points <= 10:
        incr = 0.5
    elif total_points <= 20:
        incr = 1
    else:
        incr = 5

    def as_int(x):
        return int(x) if int(x) == x else x

    points = [as_int(idx*incr) for idx in range(int(total_points/incr))]
    points.append(as_int(total_points))
    return points


class TextInputWithButtons(forms.TextInput):

    def __init__(self, button_values, *args, **kwargs):
        self.button_values = button_values
        super(TextInputWithButtons, self).__init__(*args, **kwargs)

    def render(self, name, value, attrs=None):
        html = super(TextInputWithButtons, self).render(name, value, attrs)
        from django.utils.html import format_html, mark_safe, escapejs
        id = attrs["id"]

        def make_feedback_func(feedback):
            return "'$(\"#{id}\").val(\"{feedback}\")'".format(
                                 id=id, feedback=escapejs(feedback))

        buttons = []
        # Add buttons.
        for button_value in self.button_values:
            buttons.append(format_html(
                "<button class='btn btn-xs btn-default' "
                "type='button' onclick={func}>{val}</button>",
                func=mark_safe(make_feedback_func(button_value)),
                val=button_value))

        # Add a clear button.
        buttons.append(format_html(
            "<button class='btn btn-xs btn-default' "
            "type='button' onclick={func}>Clear</button>",
            func=mark_safe(make_feedback_func(""))))

        return format_html("{html}<p>{button_row}</p>",
                           html=html, button_row=mark_safe("".join(buttons)))


class HumanTextFeedbackForm(StyledForm):
    def __init__(self, point_value, *args, **kwargs):
        super(HumanTextFeedbackForm, self).__init__(*args, **kwargs)

        self.point_value = point_value

        self.fields["grade_percent"] = forms.FloatField(
                min_value=0,
                max_value=100 * MAX_EXTRA_CREDIT_FACTOR,
                help_text=_("Grade assigned, in percent"),
                required=False,

                # avoid unfortunate scroll wheel accidents reported by graders
                widget=TextInputWithButtons(
                    [0, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 100]),
                label=_("Grade percent"))

        if point_value is not None and point_value != 0:
            self.fields["grade_points"] = forms.FloatField(
                    min_value=0,
                    max_value=MAX_EXTRA_CREDIT_FACTOR*point_value,
                    help_text=_("Grade assigned, as points out of %.1f. "
                    "Fill out either this or 'grade percent'.")
                    % point_value,
                    required=False,

                    # avoid unfortunate scroll wheel accidents reported by graders
                    widget=TextInputWithButtons(
                        create_default_point_scale(point_value)),
                    label=_("Grade points"))

        self.fields["feedback_text"] = forms.CharField(
                widget=forms.Textarea(),
                required=False,
                help_text=mark_safe_lazy(
                    _("Feedback to be shown to student, using "
                    "<a href='http://documen.tician.de/"
                    "relate/content.html#relate-markup'>"
                    "RELATE-flavored Markdown</a>")),
                label=_("Feedback text"))
        self.fields["notify"] = forms.BooleanField(
                initial=False, required=False,
                help_text=_("Checking this box and submitting the form "
                "will notify the participant "
                "with a generic message containing the feedback text"),
                label=_("Notify"))
        self.fields["may_reply"] = forms.BooleanField(
                initial=False, required=False,
                help_text=_("Allow recipient to reply to this email?"),
                label=_("May reply email to me"))
        self.fields["released"] = forms.BooleanField(
                initial=True, required=False,
                help_text=_("Whether the grade and feedback are to "
                "be shown to student. (If you would like to release "
                "all grades at once, do not use this. Instead, use "
                "the 'shown to students' checkbox for this 'grading "
                "opportunity' in the grade book admin.)"),
                label=_("Released"))
        self.fields["notes"] = forms.CharField(
                widget=forms.Textarea(),
                help_text=_("Internal notes, not shown to student"),
                required=False,
                label=_("Notes"))
        self.fields["notify_instructor"] = forms.BooleanField(
                initial=False, required=False,
                help_text=_("Checking this box and submitting the form "
                "will notify the instructor "
                "with a generic message containing the notes"),
                label=_("Notify instructor"))

    def clean(self):
        grade_percent = self.cleaned_data.get("grade_percent")
        grade_points = self.cleaned_data.get("grade_points")
        if (self.point_value is not None
                and grade_percent is not None
                and grade_points is not None):
            points_percent = 100*grade_points/self.point_value
            direct_percent = grade_percent

            if abs(points_percent - direct_percent) > 0.1:
                raise FormValidationError(
                        _("Grade (percent) and Grade (points) "
                        "disagree"))

        super(StyledForm, self).clean()

    def cleaned_percent(self):
        if self.point_value is None:
            return self.cleaned_data["grade_percent"]
        elif (self.cleaned_data["grade_percent"] is not None
                and self.cleaned_data.get("grade_points") is not None):
            points_percent = 100*self.cleaned_data["grade_points"]/self.point_value
            direct_percent = self.cleaned_data["grade_percent"]

            if abs(points_percent - direct_percent) > 0.1:
                raise RuntimeError(_("Grade (percent) and Grade (points) "
                        "disagree"))

            return max(points_percent, direct_percent)
        elif self.cleaned_data["grade_percent"] is not None:
            return self.cleaned_data["grade_percent"]

        elif self.cleaned_data.get("grade_points") is not None:
            if self.point_value:
                return 100*self.cleaned_data["grade_points"]/self.point_value
            else:
                return None
        else:
            return None


class PageBaseWithHumanTextFeedback(PageBase):
    """
    .. automethod:: human_feedback_point_value
    """
    grade_data_attrs = ["released", "grade_percent", "feedback_text", "notes"]

    def required_attrs(self):
        return super(PageBaseWithHumanTextFeedback, self).required_attrs() + (
                ("rubric", "markup"),
                )

    def human_feedback_point_value(self, page_context, page_data):
        """Subclasses can override this to make the point value of the human feedback known,
        which will enable grade entry in points.
        """
        return None

    def make_grading_form(self, page_context, page_data, grade_data):
        human_feedback_point_value = self.human_feedback_point_value(
                page_context, page_data)

        if grade_data is not None:
            form_data = {}
            for k in self.grade_data_attrs:
                form_data[k] = grade_data[k]

            return HumanTextFeedbackForm(human_feedback_point_value, form_data)
        else:
            return HumanTextFeedbackForm(human_feedback_point_value)

    def post_grading_form(self, page_context, page_data, grade_data,
            post_data, files_data):
        human_feedback_point_value = self.human_feedback_point_value(
                page_context, page_data)
        return HumanTextFeedbackForm(
                human_feedback_point_value, post_data, files_data)

    def update_grade_data_from_grading_form_v2(self, request, page_context,
            page_data, grade_data, grading_form, files_data):

        if grade_data is None:
            grade_data = {}
        for k in self.grade_data_attrs:
            if k == "grade_percent":
                grade_data[k] = grading_form.cleaned_percent()
            else:
                grade_data[k] = grading_form.cleaned_data[k]

        if grading_form.cleaned_data["notify"] and page_context.flow_session:
            with translation.override(settings.RELATE_ADMIN_EMAIL_LOCALE):
                from relate.utils import render_email_template
                from course.utils import will_use_masked_profile_for_email
                staff_email = [page_context.course.notify_email, request.user.email]
                message = render_email_template("course/grade-notify.txt", {
                    "page_title": self.title(page_context, page_data),
                    "course": page_context.course,
                    "participation": page_context.flow_session.participation,
                    "feedback_text": grade_data["feedback_text"],
                    "flow_session": page_context.flow_session,
                    "review_uri": page_context.page_uri,
                    "use_masked_profile":
                        will_use_masked_profile_for_email(staff_email)
                    })

                from django.core.mail import EmailMessage
                msg = EmailMessage(
                        string_concat("[%(identifier)s:%(flow_id)s] ",
                            _("New notification"))
                        % {'identifier': page_context.course.identifier,
                            'flow_id': page_context.flow_session.flow_id},
                        message,
                        getattr(settings, "GRADER_FEEDBACK_EMAIL_FROM",
                                page_context.course.get_from_email()),
                        [page_context.flow_session.participation.user.email])
                msg.bcc = [page_context.course.notify_email]

                if grading_form.cleaned_data["may_reply"]:
                    msg.reply_to = [request.user.email]

                if hasattr(settings, "GRADER_FEEDBACK_EMAIL_FROM"):
                    from relate.utils import get_outbound_mail_connection
                    msg.connection = get_outbound_mail_connection("grader_feedback")
                msg.send()

        if (grading_form.cleaned_data["notes"]
                and grading_form.cleaned_data["notify_instructor"]
                and page_context.flow_session):
            with translation.override(settings.RELATE_ADMIN_EMAIL_LOCALE):
                from relate.utils import render_email_template
                from course.utils import will_use_masked_profile_for_email
                staff_email = [page_context.course.notify_email, request.user.email]
                use_masked_profile = will_use_masked_profile_for_email(staff_email)
                if use_masked_profile:
                    username = (
                        page_context.flow_session.user.get_masked_profile())
                else:
                    username = (
                        page_context.flow_session.user.get_email_appellation())
                message = render_email_template(
                    "course/grade-internal-notes-notify.txt",
                    {
                        "page_title": self.title(page_context, page_data),
                        "username": username,
                        "course": page_context.course,
                        "participation": page_context.flow_session.participation,
                        "notes_text": grade_data["notes"],
                        "flow_session": page_context.flow_session,
                        "review_uri": page_context.page_uri,
                        "sender": request.user,
                    })

                from django.core.mail import EmailMessage
                msg = EmailMessage(
                        string_concat("[%(identifier)s:%(flow_id)s] ",
                            _("Grading notes from %(ta)s"))
                        % {'identifier': page_context.course.identifier,
                           'flow_id': page_context.flow_session.flow_id,
                           'ta': request.user.get_full_name()
                           },
                        message,
                        getattr(settings, "GRADER_FEEDBACK_EMAIL_FROM",
                                page_context.course.get_from_email()),
                        [page_context.course.notify_email])
                msg.bcc = [request.user.email]
                msg.reply_to = [request.user.email]

                if hasattr(settings, "GRADER_FEEDBACK_EMAIL_FROM"):
                    from relate.utils import get_outbound_mail_connection
                    msg.connection = get_outbound_mail_connection("grader_feedback")
                msg.send()

        return grade_data

    def grading_form_to_html(self, request, page_context, grading_form, grade_data):
        ctx = {
                "form": grading_form,
                "rubric": markup_to_html(page_context, self.page_desc.rubric)
                }

        from django.template.loader import render_to_string
        return render_to_string(
                "course/human-feedback-form.html", ctx, request)

    def grade(
            self,
            page_context,  # type: PageContext
            page_data,  # type: Any
            answer_data,  # type: Any
            grade_data,  # type: Any
            ):
        # type: (...) -> Optional[AnswerFeedback]
        """This method is appropriate if the grade consists *only* of the
        feedback provided by humans. If more complicated/combined feedback
        is desired, a subclass would likely override this.
        """

        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=ugettext("No answer provided."))

        if grade_data is None:
            return None

        if not grade_data["released"]:
            return None

        if (grade_data["grade_percent"] is not None
                or grade_data["feedback_text"]):
            if grade_data["grade_percent"] is not None:
                correctness = grade_data["grade_percent"]/100
                feedback_text = "<p>%s</p>" % get_auto_feedback(correctness)

            else:
                correctness = None
                feedback_text = ""

            if grade_data["feedback_text"]:
                feedback_text += (
                        string_concat(
                            "<p>",
                            _("The following feedback was provided"),
                            ":<p>")
                        + markup_to_html(
                            page_context, grade_data["feedback_text"],
                            use_jinja=False))

            return AnswerFeedback(
                    correctness=correctness,
                    feedback=feedback_text)
        else:
            return None


class PageBaseWithCorrectAnswer(PageBase):
    def allowed_attrs(self):
        return super(PageBaseWithCorrectAnswer, self).allowed_attrs() + (
            ("correct_answer", "markup"),
            )

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        if hasattr(self.page_desc, "correct_answer"):
            return markup_to_html(page_context, self.page_desc.correct_answer)
        else:
            return None

# }}}


def get_editor_interaction_mode(page_context):
    if (page_context.flow_session is not None
            and page_context.flow_session.participation is not None):
        return page_context.flow_session.participation.user.editor_mode
    else:
        return "default"


# vim: foldmethod=marker
