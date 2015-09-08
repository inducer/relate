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

import re

from course.validation import validate_struct, ValidationError
from course.constants import MAX_EXTRA_CREDIT_FACTOR
from relate.utils import StyledForm, Struct
from django.forms import ValidationError as FormValidationError
from django.utils.safestring import mark_safe
from django.utils.functional import lazy
from django.utils.translation import (
        ugettext_lazy as _,
        ugettext,
        string_concat,
        )

mark_safe_lazy = lazy(mark_safe, six.text_type)


class PageContext(object):
    """
    .. attribute:: course
    .. attribute:: repo
    .. attribute:: commit_sha
    .. attribute:: flow_session

        May be None.

    Note that this is different from :class:`course.utils.FlowPageContext`,
    which is used internally by the flow views.
    """

    def __init__(self, course, repo, commit_sha, flow_session,
            in_sandbox=False):
        self.course = course
        self.repo = repo
        self.commit_sha = commit_sha
        self.flow_session = flow_session
        self.in_sandbox = in_sandbox


class PageBehavior(object):
    """
    .. attribute:: show_correctness
    .. attribute:: show_answer
    .. attribute:: may_change_answer
    """

    def __init__(self, show_correctness, show_answer, may_change_answer):
        self.show_correctness = show_correctness
        self.show_answer = show_answer
        self.may_change_answer = may_change_answer

    def __bool__(self):
        # This is for compatiblity: page_behavior used to be a bool argument
        # 'answer_is_final'.
        return not self.may_change_answer

    __nonzero__ = __bool__


def markup_to_html(page_context, text):
    from course.content import markup_to_html

    return markup_to_html(
            page_context.course,
            page_context.repo,
            page_context.commit_sha,
            text)


# {{{ answer feedback type

def get_auto_feedback(correctness):
    if correctness == 0:
        return six.text_type(_("Your answer is not correct."))
    elif correctness == 1:
        return six.text_type(_("Your answer is correct."))
    elif correctness > 0.5:
        return six.text_type(
                string_concat(
                    _("Your answer is mostly correct."),
                    " (%.1f %%)")
                % (100*correctness))
    elif correctness is None:
        return six.text_type(_("No information on correctness of answer."))
    else:
        return six.text_type(
                string_concat(
                    _("Your answer is somewhat correct."),
                    "(%.1f %%)")
                % (100*correctness))


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

    .. attribute:: bulk_feedback
    """

    def __init__(self, correctness, feedback=None, bulk_feedback=None):
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
    .. automethod:: update_grade_data_from_grading_form
    .. automethod:: grading_form_to_html

    .. rubric:: Grading/Feedback

    .. automethod:: grade
    .. automethod:: correct_answer
    .. automethod:: normalized_answer
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

    def is_answer_gradable(self):
        """
        :return: a :class:`bool` indicating whether answers on this can
            have :meth:`grade` called on them.

        True by default.
        """
        return True

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
            answer_data, page_behavior):
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

    def post_form(self, page_context, page_data, post_data, files_data):
        raise NotImplementedError()

    def process_form_post(self, page_context, page_data, post_data, files_data,
            page_behavior):
        """Return a form with the POST response from *post_data* and *files_data*
        filled in.

        :arg page_behavior: an instance of :class:`PageBehavior`
        :return: a
            :class:`django.forms.Form` instance with *answer_data* prepopulated.
            If ``page_behavior.may_change_answer`` is *False*, the form should
            be read-only.
        """

        from warnings import warn
        warn("%s is using the post_form compatiblity hook, which "
                "is deprecated." % type(self).__name__,
                DeprecationWarning)

        return self.post_form(page_context, page_data, post_data, files_data)

    def form_to_html(self, request, page_context, form, answer_data):
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

    def normalized_answer(self, page_context, page_data, answer_data):
        """An HTML-formatted answer to be used for summarization and
        display in analytics.
        """
        return None

    # }}}

# }}}


# {{{ utility base classes

TITLE_RE = re.compile(r"^\#\s*(\w.*)", re.UNICODE)


def extract_title_from_markup(markup_text):
    lines = markup_text.split("\n")

    for l in lines[:5]:
        match = TITLE_RE.match(l)
        if match is not None:
            return match.group(1)

    return None


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
    def __init__(self, point_value, *args, **kwargs):
        super(HumanTextFeedbackForm, self).__init__(*args, **kwargs)

        self.point_value = point_value

        self.fields["grade_percent"] = forms.FloatField(
                min_value=0,
                max_value=100 * MAX_EXTRA_CREDIT_FACTOR,
                help_text=_("Grade assigned, in percent"),
                required=False,

                # avoid unfortunate scroll wheel accidents reported by graders
                widget=forms.TextInput,
                label=_("Grade percent"))

        if point_value is not None:
            self.fields["grade_points"] = forms.FloatField(
                    min_value=0,
                    max_value=MAX_EXTRA_CREDIT_FACTOR*point_value,
                    help_text=_("Grade assigned, as points out of %.1f. "
                    "Fill out either this or 'grade percent'.")
                    % point_value,
                    required=False,

                    # avoid unfortunate scroll wheel accidents reported by graders
                    widget=forms.TextInput,
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
        self.fields["released"] = forms.BooleanField(
                initial=True, required=False,
                help_text=_("Whether the grade and feedback are to "
                "be shown to student"),
                label=_("Released"))
        self.fields["notes"] = forms.CharField(
                widget=forms.Textarea(),
                help_text=_("Internal notes, not shown to student"),
                required=False,
                label=_("Notes"))

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
                and self.cleaned_data["grade_points"] is not None):
            points_percent = 100*self.cleaned_data["grade_points"]/self.point_value
            direct_percent = self.cleaned_data["grade_percent"]

            if abs(points_percent - direct_percent) > 0.1:
                raise RuntimeError(_("Grade (percent) and Grade (points) "
                        "disagree"))

            return max(points_percent, direct_percent)
        elif self.cleaned_data["grade_percent"] is not None:
            return self.cleaned_data["grade_percent"]

        elif self.cleaned_data["grade_points"] is not None:
            return 100*self.cleaned_data["grade_points"]/self.point_value

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

    def update_grade_data_from_grading_form(self, page_context, page_data,
            grade_data, grading_form, files_data):

        if grade_data is None:
            grade_data = {}
        for k in self.grade_data_attrs:
            if k == "grade_percent":
                grade_data[k] = grading_form.cleaned_percent()
            else:
                grade_data[k] = grading_form.cleaned_data[k]

        if grading_form.cleaned_data["notify"] and page_context.flow_session:
            from django.template.loader import render_to_string
            message = render_to_string("course/grade-notify.txt", {
                "page_title": self.title(page_context, page_data),
                "course": page_context.course,
                "participation": page_context.flow_session.participation,
                "feedback_text": grade_data["feedback_text"],
                "flow_session": page_context.flow_session,
                })

            from django.core.mail import send_mail
            from django.conf import settings
            send_mail(
                    string_concat("[%(identifier)s:%(flow_id)s] ",
                        _("New notification"))
                    % {'identifier': page_context.course.identifier,
                        'flow_id': page_context.flow_session.flow_id},
                    message,
                    settings.ROBOT_EMAIL_FROM,
                    recipient_list=[
                        page_context.flow_session.participation.user.email])

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
                            page_context, grade_data["feedback_text"]))

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

# }}}


def get_editor_interaction_mode(page_context):
    if (page_context.flow_session is not None
            and page_context.flow_session.participation is not None):
        from course.models import get_user_status
        ustatus = get_user_status(page_context.flow_session.participation.user)
        return ustatus.editor_mode
    else:
        return "default"


# vim: foldmethod=marker
