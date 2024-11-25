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
from typing import cast

import django.forms as forms
from crispy_forms.bootstrap import PrependedAppendedText
from crispy_forms.layout import HTML, Layout
from django.utils.safestring import mark_safe
from django.utils.translation import gettext, gettext_lazy as _

from course.content import remove_prefix
from course.page.base import (
    AnswerFeedback,
    PageBaseWithoutHumanGrading,
    PageBaseWithValue,
    markup_to_html,
)
from course.page.text import TextQuestionBase, parse_matcher
from course.validation import ValidationError, validate_markup, validate_struct
from relate.utils import Struct, string_concat


# {{{ for mypy


# }}}

# {{{ multiple text question

class InlineMultiQuestionForm(forms.Form):
    no_offset_labels = True

    def __init__(self, read_only, dict_for_form, page_context, *args, **kwargs):
        from crispy_forms.helper import FormHelper
        self.helper = FormHelper()
        super().__init__(*args, **kwargs)
        html_list = dict_for_form["html_list"]
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

            # for fields embedded in html, the defined html_list can be
            # longer than the answer_instance_list.
            if idx < len(answer_instance_list):
                field_name = answer_instance_list[idx].name
                self.fields[field_name] = answer_instance_list[idx] \
                        .get_form_field(page_context, force_required=force_required)
                if correctness_list is None:
                    self.helper.layout.extend([
                            answer_instance_list[idx].get_field_layout()])
                else:
                    self.helper.layout.extend([
                            answer_instance_list[idx].get_field_layout(
                                correctness=correctness_list[idx])])
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

    def clean(self):
        cleaned_data = super().clean()
        answer_name_list = [answer_instance.name
                for answer_instance in self.answer_instance_list]

        for answer in list(cleaned_data.keys()):
            idx = answer_name_list.index(answer)
            instance_idx = self.answer_instance_list[idx]
            field_name_idx = instance_idx.name
            if hasattr(instance_idx, "matchers"):
                for i, validator in enumerate(instance_idx.matchers):  # pragma: no branch  # noqa
                    try:
                        validator.validate(cleaned_data[answer])
                    except forms.ValidationError:
                        if i + 1 == len(instance_idx.matchers):
                            # last one, and we flunked -> not valid
                            import sys
                            _tp, e, _ = sys.exc_info()
                            self.add_error(field_name_idx, e)
                    else:
                        # Found one that will take the input. Good enough.
                        break


def get_question_class(location, q_type, answers_desc):
    for question_class in ALLOWED_EMBEDDED_QUESTION_CLASSES:
        if question_class.type == q_type:
            return question_class
    else:
        raise ValidationError(
            string_concat(
                "%(location)s: ",
                _("unknown embedded question type '%(type)s'"))
            % {
                "location": location,
                "type": q_type})


def parse_question(vctx, location, name, answers_desc):
    if isinstance(answers_desc, Struct):
        return (get_question_class(location, answers_desc.type, answers_desc)
            (vctx, location, name, answers_desc))
    else:
        raise ValidationError(
                string_concat(
                    "%s: ",
                    _("Embedded question '{}' must be a struct".format(name)))
                % location)


class AnswerBase:
    """Abstract interface for answer class of different type.
    .. attribute:: type
    .. attribute:: form_field_class
    """

    def __init__(self, vctx, location, name, answers_desc):
        self.name = name
        self.answers_desc = answers_desc

        self.required = getattr(answers_desc, "required", False)

    def get_answer_text(self, page_context, answer):
        raise NotImplementedError()

    def get_correct_answer_text(self, page_context):
        raise NotImplementedError()

    def get_correctness(self, answer):
        raise NotImplementedError()

    def get_weight(self, answer):
        if answer is None or answer == "":
            return 0
        return self.weight * self.get_correctness(answer)

    def get_field_layout(self, correctness=None):
        kwargs = {
            "template": "course/custom_crispy_inline_prepended_appended_text.html",
            "prepended_text": getattr(self.answers_desc, "prepended_text", ""),
            "appended_text": getattr(self.answers_desc, "appended_text", ""),
            "use_popover": "true",
            "popover_title": getattr(self.answers_desc, "hint_title", ""),
            "popover_content": getattr(self.answers_desc, "hint", "")}
        if correctness is None:
            kwargs["style"] = self.get_width_str()
        else:
            kwargs["style"] = self.get_width_str(self.width + 2)
            kwargs["correctness"] = correctness

        return PrependedAppendedText(self.name, **kwargs)

    def get_form_field(self, page_context):
        raise NotImplementedError()


# length unit used is "em"
DEFAULT_WIDTH = 10
MINIMUM_WIDTH = 4

EM_LEN_DICT = {
        "em": 1,
        "pt": 10.00002,
        "cm": 0.35146,
        "mm": 3.5146,
        "in": 0.13837,
        "%": ""}

ALLOWED_LENGTH_UNIT = EM_LEN_DICT.keys()
WIDTH_STR_RE = re.compile(r"^(\d*\.\d+|\d+)\s*(.*)$")


class ShortAnswer(AnswerBase):
    type = "ShortAnswer"
    form_field_class = forms.CharField

    @staticmethod
    def get_length_attr_em(location: str, width_attr: str) -> float | None:
        """
        generate the length for input box, the unit is 'em'
        """

        if width_attr is None:
            return None

        if isinstance(width_attr, int | float):
            return width_attr

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
            return float(length_value)/cast(float, EM_LEN_DICT[length_unit])

    def __init__(self, vctx, location, name, answers_desc):
        super().__init__(
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
                ("prepended_text", str),
                ("appended_text", str),
                ("hint", str),
                ("hint_title", str),
                ("width", (str, int, float)),
                ("required", bool),
                ),
            )

        weight = getattr(answers_desc, "weight", 0)
        if weight < 0:
            raise ValidationError(
                    string_concat(
                        "%s: %s: ",
                        _("'weight' must be a non-negative value, "
                          "got '%s' instead") % str(weight))
                    % (location, self.name))
        self.weight = weight

        if len(answers_desc.correct_answer) == 0:
            raise ValidationError(
                    string_concat(
                        "%s: %s: ",
                        _("at least one answer must be provided"))
                    % (location, self.name))

        self.hint = getattr(self.answers_desc, "hint", "")
        width = getattr(self.answers_desc, "width", None)

        parsed_length = self.get_length_attr_em(
            f"{location}: {self.name}: 'width'", width)

        self.width = 0
        if parsed_length is not None:
            self.width = max(MINIMUM_WIDTH, parsed_length)
        else:
            self.width = DEFAULT_WIDTH

        self.width_str = "width: " + str(self.width) + "em"

        self.matchers = [
                parse_matcher(
                    vctx,
                    string_concat("%s, ",
                                  # Translators: refers to optional
                                  # correct answer for checking
                                  # correctness submitted by students.
                                  _("answer"),
                                  " %d") % (location, i+1),
                    answer)
                for i, answer in enumerate(answers_desc.correct_answer)]

        if not any(matcher.correct_answer_text() is not None
                for matcher in self.matchers):
            raise ValidationError(
                    string_concat(
                        "%s: %s: ",
                        _("no matcher is able to provide a plain-text "
                        "correct answer"))
                    % (location, self.name))

    def get_width_str(self, opt_width=0):
        return "width: " + str(max(self.width, opt_width)) + "em"

    def get_answer_text(self, page_context, answer):
        from django.utils.html import escape
        return escape(answer)

    def get_correct_answer_text(self, page_context):

        unspec_correct_answer_text = None
        for matcher in self.matchers:  # pragma: no branch
            unspec_correct_answer_text = matcher.correct_answer_text()
            if unspec_correct_answer_text is not None:
                break

        assert unspec_correct_answer_text is not None
        return ("{}{}{}".format(
                   getattr(self.answers_desc, "prepended_text", "").strip(),
                   unspec_correct_answer_text,
                   getattr(self.answers_desc, "appended_text", "").strip())
                )

    def get_correctness(self, answer):

        correctnesses = [0]
        # If empty an list, sometime it will cause ValueError:
        # max() arg is an empty sequence, observed in SandBox

        for matcher in self.matchers:
            try:
                matcher.validate(answer)
            except forms.ValidationError:
                continue

            correctnesses.append(matcher.grade(answer).correctness)

        return max(correctnesses)

    def get_form_field(self, page_context, force_required=False):
        return (self.form_field_class)(
                    required=self.required or force_required,
                    widget=None,
                    help_text=None,
                    label=""
                )


class ChoicesAnswer(AnswerBase):
    type = "ChoicesAnswer"
    form_field_class = forms.ChoiceField

    CORRECT_TAG = "~CORRECT~"

    @classmethod
    def process_choice_string(cls, page_context, s):
        if not isinstance(s, str):
            s = str(s)
        s = remove_prefix(cls.CORRECT_TAG, s)

        s_contain_p_tag = "<p>" in s
        s = markup_to_html(page_context, s)
        # allow HTML in option
        if not s_contain_p_tag:
            s = s.replace("<p>", "").replace("</p>", "")
        s = mark_safe(s)

        return s

    def __init__(self, vctx, location, name, answers_desc):
        super().__init__(
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
            except Exception:
                raise ValidationError(
                        string_concat(
                            "%(location)s: '%(answer_name)s' ",
                            _("choice %(idx)d: unable to convert to string")
                            )
                        % {"location": location,
                            "answer_name": self.name,
                            "idx": choice_idx+1})

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
                        "location": location,
                        "question_name": self.name,
                        "n_correct": correct_choice_count})

        self.hint = getattr(self.answers_desc, "hint", "")
        self.width = 0

    def get_answer_text(self, page_context, answer):
        if answer == "":
            return answer
        return self.process_choice_string(
            page_context, self.answers_desc.choices[int(answer)])

    def get_width_str(self, opt_width=0):
        return None

    def correct_indices(self):
        result = []
        for i, choice_text in enumerate(self.answers_desc.choices):
            if str(choice_text).startswith(self.CORRECT_TAG):
                result.append(i)
        return result

    def get_correct_answer_text(self, page_context):
        corr_idx = self.correct_indices()[0]
        return ("{}{}{}".format(
                    getattr(self.answers_desc, "prepended_text", "").strip(),
                    self.process_choice_string(
                        page_context, self.answers_desc.choices[corr_idx]).lstrip(),
                    getattr(self.answers_desc, "appended_text", "").strip())
                )

    def get_max_correct_answer_len(self, page_context):
        return max(len(answer) for answer in
            [self.process_choice_string(page_context, processed)
                for processed in self.answers_desc.choices])

    def get_correctness(self, answer):
        if answer == "":
            return 0
        if int(answer) in self.correct_indices():
            return 1
        return 0

    def get_form_field(self, page_context, force_required=False):
        choices = tuple(
            (i, self.process_choice_string(
                page_context, self.answers_desc.choices[i]))
            for i, src_i in enumerate(self.answers_desc.choices))
        choices = (
            (None, "-" * self.get_max_correct_answer_len(page_context)),
            *choices)
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
NAME_VALIDATE_RE = re.compile(r"^[a-zA-Z]+[a-zA-Z0-9_]{0,}$")


class InlineMultiQuestion(
            TextQuestionBase,
            PageBaseWithValue,
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

    def __init__(self, vctx, location, page_desc):
        super().__init__(
                vctx, location, page_desc)

        expanded_question = page_desc.question

        self.embedded_wrapped_name_list = WRAPPED_NAME_RE.findall(expanded_question)
        self.embedded_name_list = NAME_RE.findall(expanded_question)

        answer_instance_list = []

        for name in self.embedded_name_list:
            answers_desc = getattr(self.page_desc.answers, name)

            parsed_answer = parse_question(
                    vctx, location, name, answers_desc)
            answer_instance_list.append(parsed_answer)

        self.answer_instance_list = answer_instance_list

        from relate.utils import struct_to_dict
        answers_name_list = struct_to_dict(page_desc.answers).keys()

        invalid_answer_name = []

        if not answer_instance_list:
            raise ValidationError(
                    string_concat(
                        "%(location)s: ",
                        _("InlineMultiQuestion requires at least one "
                        "answer field to be defined."))
                    % {"location": location})

        for answers_name in answers_name_list:
            if NAME_VALIDATE_RE.match(answers_name) is None:
                invalid_answer_name.append(answers_name)
        if invalid_answer_name:
            raise ValidationError(
                    string_concat(
                        "%s: ",
                        _("invalid answers name %s. "),
                        _("A valid name should start with letters. "
                            "Alphanumeric with underscores. "
                            "Do not use spaces."))
                    % (
                        location,
                        ", ".join([
                            "'" + name + "'"
                            for name in invalid_answer_name])
                        ))

        if len(set(self.embedded_name_list)) < len(self.embedded_name_list):
            duplicated = list(
                 {x for x in self.embedded_name_list
                      if self.embedded_name_list.count(x) > 1})
            raise ValidationError(
                 string_concat(
                     "%s: ",
                     _("embedded question name %s not unique."))
                 % (location, ", ".join([f"'{d}'" for d in sorted(duplicated)])))

        redundant_answer_list = list(set(answers_name_list)
                - set(self.embedded_name_list))

        if redundant_answer_list:
            if vctx is not None:
                vctx.add_warning(location,
                        _("redundant answers %s provided for "
                            "non-existing question(s).")
                        % ", ".join(
                            ["'" + item + "'"
                                for item in redundant_answer_list]))

        if vctx is not None:
            validate_markup(vctx, location, page_desc.question)

            remainder_html = page_desc.question
            html_list = []
            for wrapped_name in self.embedded_wrapped_name_list:
                [html, remainder_html] = remainder_html.split(wrapped_name)
                html_list.append(html)

            if remainder_html.strip():
                html_list.append(remainder_html)

            # make sure all [[ and ]] are paired.
            embedded_removed = " ".join(html_list)

            for sep in ["[[", "]]"]:
                if sep in embedded_removed:
                    raise ValidationError(
                        string_concat(
                            "%s: ",
                            _("question has unpaired '%s'."))
                        % (location, sep))

            for name in self.embedded_name_list:
                answers_desc = getattr(page_desc.answers, name)

                parse_question(vctx, location, name, answers_desc)

    def required_attrs(self):
        return (*super().required_attrs(), ("question", "markup"), ("answers", Struct))

    def allowed_attrs(self):
        return (*super().allowed_attrs(), ("answer_explanation", "markup"))

    def body(self, page_context, page_data):
        return markup_to_html(page_context, self.page_desc.prompt)

    def get_question(self, page_context, page_data):
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
            self.page_desc.question
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

    def get_dict_for_form(self, page_context, page_data):
        remainder_html = self.get_question(page_context, page_data)

        html_list = []
        for wrapped_name in self.embedded_wrapped_name_list:
            [html, remainder_html] = remainder_html.split(wrapped_name)
            html_list.append(html)

        # remainder_html should at least include "</p>"
        assert remainder_html, (
            f"remainder_html is unexpected not empty: {remainder_html}")
        html_list.append(remainder_html)

        return {
                "html_list": html_list,
                "answer_instance_list": self.answer_instance_list,
               }

    def make_form(self, page_context, page_data, answer_data, page_behavior):
        read_only = not page_behavior.may_change_answer

        if answer_data is not None:
            dict_feedback_form = self.get_dict_for_form(page_context, page_data)

            answer = answer_data["answer"]
            if page_behavior.show_correctness:
                correctness_list = []

                for answer_instance in self.answer_instance_list:
                    try:
                        correctness_list.append(answer_instance.get_correctness(
                                answer[answer_instance.name]))

                    # The answer doesn't exist for newly added question
                    # for pages which have been submitted.
                    except KeyError:
                        correctness_list.append(1)

                    dict_feedback_form["correctness_list"] = correctness_list

            form = InlineMultiQuestionForm(
                    read_only,
                    dict_feedback_form,
                    page_context,
                    answer)
        else:
            answer = None
            form = InlineMultiQuestionForm(
                    read_only,
                    self.get_dict_for_form(page_context, page_data),
                    page_context)

        return form

    def process_form_post(self, page_context, page_data, post_data, files_data,
            page_behavior):
        read_only = not page_behavior.may_change_answer

        return InlineMultiQuestionForm(
                read_only,
                self.get_dict_for_form(page_context, page_data),
                page_context,
                post_data, files_data)

    def correct_answer(self, page_context, page_data, answer_data, grade_data):
        # FIXME: Could use 'best' match to answer

        cor_answer_output = self.get_question(page_context, page_data)

        for idx, wrapped in enumerate(self.embedded_wrapped_name_list):
            correct_answer_i = self.answer_instance_list[idx] \
                    .get_correct_answer_text(page_context)
            cor_answer_output = cor_answer_output.replace(
                wrapped,
                "<strong>" + correct_answer_i + "</strong>")

        CA_PATTERN = string_concat(_("A correct answer is"), ": %s")  # noqa

        result = CA_PATTERN % cor_answer_output

        if hasattr(self.page_desc, "answer_explanation"):
            result += markup_to_html(page_context, self.page_desc.answer_explanation)

        return result

    def answer_data(self, page_context, page_data, form, files_data):
        return {"answer": form.cleaned_data}

    def form_to_html(self, request, page_context, form, answer_data):
        """Returns an HTML rendering of *form*."""

        from django.template import loader
        context = {"form": form}

        # This happens when rendering the form in analytics view.
        if not request:
            context.update({"csrf_token": "None"})

        return loader.render_to_string(
                "course/custom-crispy-inline-form.html",
                context=context,
                request=request)

    def grade(self, page_context, page_data, answer_data, grade_data):
        if answer_data is None:
            return AnswerFeedback(correctness=0,
                    feedback=gettext("No answer provided."))

        answer_dict = answer_data["answer"]

        total_weight = 0

        for idx in range(len(self.embedded_name_list)):
            total_weight += self.answer_instance_list[idx].weight

        if total_weight > 0:
            achieved_weight = 0
            for answer_instance in self.answer_instance_list:
                achieved_weight += answer_instance.get_weight(
                        answer_dict[answer_instance.name])
            correctness = achieved_weight / total_weight

        # for case when all questions have no weight assigned
        else:
            n_corr = 0
            for answer_instance in self.answer_instance_list:
                n_corr += answer_instance.get_correctness(
                        answer_dict[answer_instance.name])
            correctness = n_corr / len(self.answer_instance_list)

        return AnswerFeedback(correctness=correctness)

    def analytic_view_body(self, page_context, page_data):
        form = InlineMultiQuestionForm(
            False,
            self.get_dict_for_form(page_context, page_data),
            page_context)
        return (self.body(page_context, page_data)
                + self.form_to_html(None, page_context, form, None))

    def normalized_bytes_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        answer_dict = answer_data["answer"]

        result = {}
        for idx, name in enumerate(self.embedded_name_list):
            single_answer_str = (
                self.answer_instance_list[idx].get_answer_text(
                    page_context, answer_dict[self.embedded_name_list[idx]]))

            # unanswered question result in "" in answer_dict
            if single_answer_str != "":
                result[name] = single_answer_str

        import json
        return ".json", json.dumps(result)

    def normalized_answer(self, page_context, page_data, answer_data):
        if answer_data is None:
            return None

        answer_dict = answer_data["answer"]

        return ", ".join(
            [self.answer_instance_list[idx].get_answer_text(
                page_context, answer_dict[self.embedded_name_list[idx]])
                for idx, name in enumerate(self.embedded_name_list)]
        )

# }}}

# vim: foldmethod=marker
