# -*- coding: utf-8 -*-

from __future__ import division

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


from django.utils.translation import (
        ugettext_lazy as _, ugettext, string_concat)
from django.utils.safestring import mark_safe
from course.validation import validate_struct, validate_markup, ValidationError
from course.content import remove_prefix
import django.forms as forms

from relate.utils import Struct, StyledInlineForm
from course.page.base import (
        AnswerFeedback, PageBaseWithValue, markup_to_html)

from course.page.text import TextQuestionBase, parse_matcher

import re


# {{{ multiple text question

from crispy_forms.layout import Layout, Field, HTML


class InlineMultiQuestionForm(StyledInlineForm):
    no_offset_labels = True

    def __init__(self, read_only, dict_for_form, *args, **kwargs):
        super(InlineMultiQuestionForm, self).__init__(*args, **kwargs)
        html_list = dict_for_form["HTML_list"]
        self.answer_instance_list = answer_instance_list = \
                dict_for_form["answer_instance_list"]

        correctness_list = None
        if "correctness_list" in dict_for_form:
            correctness_list = dict_for_form["correctness_list"]

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
                if correctness_list is None:
                    self.helper.layout.extend([
                            answer_instance_list[idx].get_field_layout()])
                else:
                    self.helper.layout.extend([
                            answer_instance_list[idx].get_field_layout(
                                correctness=correctness_list[idx])])
                if read_only:
                    if isinstance(self.fields[field_name].widget, 
                            forms.widgets.TextInput):
                        self.fields[field_name].widget.attrs['readonly'] \
                                = "readonly"
                    elif isinstance(self.fields[field_name].widget, 
                            forms.widgets.Select):
                        self.fields[field_name].widget.attrs['disabled'] \
                                = "disabled"
        self.helper.layout.extend([HTML("<br/><br/>")])

    def clean(self):
        cleaned_data = super(InlineMultiQuestionForm, self).clean()
        answer_name_list = [answer_instance.name
                for answer_instance in self.answer_instance_list]

        for answer in cleaned_data.keys():
            idx = answer_name_list.index(answer)
            instance_idx = self.answer_instance_list[idx]
            field_name_idx = instance_idx.name
            print field_name_idx
            if hasattr(instance_idx, "matchers"):
                for validator in instance_idx.matchers:
                    try:
                        validator.validate(cleaned_data[answer], 
                                validate_only=True)
                    except:
                        from traceback import print_exc
                        print_exc()

                        import sys
                        tp, e, _ = sys.exc_info()

                        self.add_error(field_name_idx,
                                       "%(err_type)s: %(err_str)s" % {
                                            "err_type": tp.__name__,
                                            "err_str": str(e)})


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

    def get_field_layout(self, correctness=None):
        if correctness is None:
            return Field(
                    self.name,
                    use_popover="true",
                    popover_title=getattr(self.answers_desc, "hint_title", ""),
                    popover_content=getattr(self.answers_desc, "hint", ""),
                    style=self.get_width_str()
                    )
        else:
            return Field(
                    self.name,
                    use_popover="true",
                    popover_title=getattr(self.answers_desc, "hint_title", ""),
                    popover_content=getattr(self.answers_desc, "hint", ""),
                    style=self.get_width_str(self.width + 2),
                    correctness=correctness
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

        self.width = 0
        if parsed_length is not None:
            self.width = max(MINIMUN_WIDTH, parsed_length)
        else:
            self.width = DEFAULT_WIDTH

        self.width_str = "width: " + str(self.width) + "em"

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

    def get_width_str(self, opt_width=0):
        return "width: " + str(max(self.width, opt_width)) + "em"

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
        self.width = 0

    def get_width_str(self, opt_width=0):
        return None

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

    allow_feedback_form = True

    def __init__(self, vctx, location, page_desc):
        super(InlineMultiQuestion, self).__init__(
                vctx, location, page_desc)

        self.embeded_wrapped_name_list = WRAPPED_NAME_RE.findall(
                page_desc.question)
        self.embeded_name_list = NAME_RE.findall(page_desc.question)

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
        from course.content import markup_to_html # noqa
        self.question = remainder_html = markup_to_html(
                course=None,
                repo=None,
                commit_sha=None,
                text=page_desc.question,
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

    def make_feedback_form(self, page_context, page_data,
            answer_data, answer_is_final):
        read_only = answer_is_final

        if answer_data is not None:
            dict_feedback_form = self.get_dict_for_form()
            answer_dict = answer_data["answer"]
            correctness_list = []

            for answer_instance in self.answer_instance_list:
                if answer_dict[answer_instance.name] is not None:
                    correctness_list.append(answer_instance.get_correctness(
                            answer_dict[answer_instance.name]))

                dict_feedback_form["correctness_list"] = correctness_list

            answer = answer_data["answer"]
            form = InlineMultiQuestionForm(
                    read_only,
                    dict_feedback_form,
                    answer)
        else:
            answer = None
            form = InlineMultiQuestionForm(
                    read_only,
                    self.get_dict_for_form())

        return form

    def make_form(self, page_context, page_data,
            answer_data, answer_is_final):
        read_only = answer_is_final

        if answer_data is not None:
            answer = answer_data["answer"]
            form = InlineMultiQuestionForm(
                    read_only,
                    self.get_dict_for_form(),
                    answer)
        else:
            answer = None
            form = InlineMultiQuestionForm(
                    read_only,
                    self.get_dict_for_form())

        return form

    def post_form(self, page_context, page_data, post_data, files_data):
        read_only = False

        return InlineMultiQuestionForm(
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
