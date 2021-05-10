__copyright__ = "Copyright (C) 2018 Dong Zhuang"

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

from django.test import TestCase, Client
import unittest

from course.page.choice import markup_to_html_plain

from tests.base_test_mixins import SingleCoursePageTestMixin
from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin
)
from tests.constants import PAGE_ERRORS
from tests.utils import mock

# The last item is within a pair of backticks
# https://github.com/inducer/relate/issues/121
# Notice the text must wrapped by quotes
CHOICE_MARKDOWN = """
type: ChoiceQuestion
id: simple
value: 1
shuffle: False
prompt: |

    # Good
    What is good?

choices:

  - Bad
  - Worse
  - ~CORRECT~ Well
  - "`So so`"
"""

CHOICE_MARKDOWN_WITHOUT_CORRECT_ANSWER = """
type: ChoiceQuestion
id: simple
value: 1
shuffle: False
prompt: |

    # Good
    What is good?

choices:

  - Bad
  - Worse
  - Well
  - So so
"""

CHOICE_MARKDOWN_WITH_DISREGARD = """
type: ChoiceQuestion
id: simple
value: 1
shuffle: False
prompt: |

    # Good
    What is good?

choices:

  - Bad
  - Worse
  - ~CORRECT~ Well
  - ~DISREGARD~ So so
"""

CHOICE_MARKDOWN_WITH_ALWAYS_CORRECT = """
type: ChoiceQuestion
id: simple
value: 1
shuffle: False
prompt: |

    # Good
    What is good?

choices:

  - Bad
  - Worse
  - ~CORRECT~ Well
  - ~ALWAYS_CORRECT~ So so
"""

CHOICE_MARKDOWN_WITH_ANSWER_EXPLANATION = """
type: ChoiceQuestion
id: simple
value: 1
shuffle: False
prompt: |

    # Good
    What is good?

choices:

  - Bad
  - Worse
  - ~CORRECT~ Well
  - So so

answer_explanation: This is the explanation.
"""

MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN = """
type: MultipleChoiceQuestion
id: ice_cream_toppings
%(credit_mode_str)s
value: 1
shuffle: %(shuffle)s
prompt: |
    # Ice Cream Toppings
    Which of the following are ice cream toppings?
choices:

  - ~CORRECT~ Sprinkles
  - ~CORRECT~ Chocolate chunks
  - Vacuum cleaner dust
  - Spider webs
  - ~CORRECT~ Almond bits

%(extra_attr)s
"""  # noqa

MULTIPLE_CHOICES_MARKDWON_WITH_MULTIPLE_MODE1 = """
type: MultipleChoiceQuestion
id: ice_cream_toppings
credit_mode: exact
value: 1
shuffle: False
prompt: |
    # Ice Cream Toppings
    Which of the following are ice cream toppings?
choices:

  - ~CORRECT~~CORRECT~ Sprinkles
  - ~CORRECT~ Chocolate chunks
  - Vacuum cleaner dust
  - Spider webs
  - ~CORRECT~ Almond bits
"""

MULTIPLE_CHOICES_MARKDWON_WITH_MULTIPLE_MODE2 = """
type: MultipleChoiceQuestion
id: ice_cream_toppings
credit_mode: exact
value: 1
shuffle: False
prompt: |
    # Ice Cream Toppings
    Which of the following are ice cream toppings?
choices:

  - ~DISREGARD~~CORRECT~ Sprinkles
  - ~CORRECT~ Chocolate chunks
  - Vacuum cleaner dust
  - Spider webs
  - ~CORRECT~ Almond bits
"""

MULTIPLE_CHOICES_MARKDWON_WITH_DISREGARD_PATTERN = """
type: MultipleChoiceQuestion
id: ice_cream_toppings
credit_mode: %(credit_mode)s
value: 1
shuffle: False
prompt: |
    # Ice Cream Toppings
    Which of the following are ice cream toppings?
choices:

  - ~CORRECT~ Sprinkles
  - ~CORRECT~ Chocolate chunks
  - Vacuum cleaner dust
  - Spider webs
  - ~CORRECT~ Almond bits
  - ~DISREGARD~ A flawed option
"""  # noqa

MULTIPLE_CHOICES_MARKDWON_WITH_ALWAYS_CORRECT_PATTERN = """
type: MultipleChoiceQuestion
id: ice_cream_toppings
credit_mode: %(credit_mode)s
value: 1
shuffle: False
prompt: |
    # Ice Cream Toppings
    Which of the following are ice cream toppings?
choices:

  - ~CORRECT~ Sprinkles
  - ~CORRECT~ Chocolate chunks
  - Vacuum cleaner dust
  - Spider webs
  - ~CORRECT~ Almond bits
  - ~ALWAYS_CORRECT~ A flawed option
"""  # noqa


class ChoicesQuestionTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_choice(self):
        markdown = CHOICE_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

        self.assertEqual(len(self.get_sandbox_page_data()), 3)
        page_data = self.get_sandbox_page_data()[2]
        self.assertTrue("permutation" in page_data)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": [1]})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": [2]})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

    def test_choice_without_correct(self):
        markdown = CHOICE_MARKDOWN_WITHOUT_CORRECT_ANSWER
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "one or more correct answer(s) "
            "expected, 0 found")

    def test_choice_with_disregard(self):
        markdown = CHOICE_MARKDOWN_WITH_DISREGARD
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "ChoiceQuestion does not allow any choices "
            "marked 'disregard'")

    def test_choice_with_always_correct(self):
        markdown = CHOICE_MARKDOWN_WITH_ALWAYS_CORRECT
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "ChoiceQuestion does not allow any choices "
            "marked 'always_correct'")

    def test_choice_with_explanation(self):
        markdown = CHOICE_MARKDOWN_WITH_ANSWER_EXPLANATION

        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextContains(resp, "correct_answer",
                                           "This is the explanation.")


class MultiChoicesQuestionTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    # {{{ choice with multiple modes
    def test_choice_item_with_multiple_modes1(self):
        resp = self.get_page_sandbox_preview_response(
            MULTIPLE_CHOICES_MARKDWON_WITH_MULTIPLE_MODE1)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        expected_page_error = ("ValidationError: sandbox, choice 1: "
                               "more than one choice modes set: "
                               "'~CORRECT~~CORRECT~'")
        self.assertResponseContextContains(resp, PAGE_ERRORS, expected_page_error)

    def test_choice_item_with_multiple_modes2(self):
        resp = self.get_page_sandbox_preview_response(
            MULTIPLE_CHOICES_MARKDWON_WITH_MULTIPLE_MODE2)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        expected_page_error = ("ValidationError: sandbox, choice 1: "
                               "more than one choice modes set: "
                               "'~DISREGARD~~CORRECT~'")
        self.assertResponseContextContains(resp, PAGE_ERRORS, expected_page_error)

    # }}}

    def test_shuffle(self):
        markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "True",
                       "credit_mode_str": "credit_mode: exact",
                       "extra_attr": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertEqual(len(self.get_sandbox_page_data()), 3)
        page_data = self.get_sandbox_page_data()[2]
        self.assertTrue("permutation" in page_data)

        permutation = page_data["permutation"]
        unpermed_correct_answer_idx = [0, 1, 4]
        correct_idx = []
        for idx in unpermed_correct_answer_idx:
            correct_idx.append(str(permutation.index(idx)))

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": correct_idx})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

    def test_exact_mode(self):
        markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "False",
                       "credit_mode_str": "credit_mode: exact",
                       "extra_attr": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertEqual(len(self.get_sandbox_page_data()), 3)

        # This is to make sure page_data exists and is ordered
        page_data = self.get_sandbox_page_data()[2]
        self.assertTrue("permutation" in page_data)
        permutation = page_data["permutation"]
        self.assertEqual(permutation, sorted(permutation))

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1', '4']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

    def test_proportional_mode(self):
        markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "False",
                       "credit_mode_str": "credit_mode: proportional",
                       "extra_attr": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertEqual(len(self.get_sandbox_page_data()), 3)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1', '4']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1', '2', '3', '4']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0.6)

    # {{{ choices with disregard or always_correct tag

    def test_choice_item_with_disregard(self):
        markdown = (MULTIPLE_CHOICES_MARKDWON_WITH_DISREGARD_PATTERN
                    % {"credit_mode": "proportional_correct"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['2', '5']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 2/3)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1', '5']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 2/3)

    def test_choice_item_with_always_correct(self):
        markdown = (MULTIPLE_CHOICES_MARKDWON_WITH_ALWAYS_CORRECT_PATTERN
                    % {"credit_mode": "proportional_correct"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['2', '5']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

        # Note that the feedback correctness is different from when the "flawed"
        # option is tagged "~DISREGARD~"
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0.75)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"choice": ['0', '1', '5']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0.75)
        self.assertResponseContextEqual(
            resp, "correct_answer",
            "The correct answer is: "
            "<ul><li>Sprinkles</li>"
            "<li>Chocolate chunks</li>"
            "<li>Almond bits</li>"
            "</ul>"
            "Additional acceptable options are: "
            "<ul><li>A flawed option</li></ul>")

    # }}}

    def test_with_explanation(self):
        markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "False",
                       "credit_mode_str": "credit_mode: proportional",
                       "extra_attr":
                           "answer_explanation: This is the explanation."})

        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

        self.assertResponseContextContains(resp, "correct_answer",
                                           "This is the explanation.")

    def test_with_invalid_credit_mode(self):
        expected_error = (
            "unrecognized credit_mode 'invalid_mode'")

        markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "False",
                       "credit_mode_str": "credit_mode: invalid_mode",
                       "extra_attr": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(resp, PAGE_ERRORS, expected_error)

    def test_with_both_credit_mode_and_allow_partial_credit(self):
        expected_error = (
            "'allow_partial_credit' or "
            "'allow_partial_credit_subset_only' may not be specified"
            "at the same time as 'credit_mode'")

        markdown1 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "False",
                       "credit_mode_str": "credit_mode: proportional",
                       "extra_attr":
                           "allow_partial_credit_subset_only: True"})

        markdown2 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                    % {"shuffle": "False",
                       "credit_mode_str": "credit_mode: proportional",
                       "extra_attr":
                           "allow_partial_credit: True"})

        resp = self.get_page_sandbox_preview_response(markdown1)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(resp, PAGE_ERRORS, expected_error)

        resp = self.get_page_sandbox_preview_response(markdown2)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(resp, PAGE_ERRORS, expected_error)

    def test_without_credit_mode_but_allow_partial_credit(self):
        expected_warning_pattern = (
            "'credit_mode' will be required on multi-select choice "
            "questions in a future version. set "
            "'credit_mode: %s' to match current behavior.")

        markdown_exact1 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr": ""})
        markdown_exact2 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr":
                            "allow_partial_credit_subset_only: False"})
        markdown_exact3 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr": "allow_partial_credit: False"})
        markdown_exact4 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr": (
                            "allow_partial_credit: False\n"
                            "allow_partial_credit_subset_only: False")})

        markdown_proportional1 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr":
                            "allow_partial_credit: True"})
        markdown_proportional2 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr":
                            "allow_partial_credit: True\n"
                            "allow_partial_credit_subset_only: False"})
        markdown_proportional_correct1 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr":
                            "allow_partial_credit_subset_only: True"})
        markdown_proportional_correct2 = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr":
                            "allow_partial_credit_subset_only: True\n"
                            "allow_partial_credit: False"})

        resp = self.get_page_sandbox_preview_response(markdown_exact1)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "exact", loose=True)

        resp = self.get_page_sandbox_preview_response(markdown_exact2)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "exact", loose=True)

        resp = self.get_page_sandbox_preview_response(markdown_exact3)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "exact", loose=True)

        resp = self.get_page_sandbox_preview_response(markdown_exact4)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "exact", loose=True)

        resp = self.get_page_sandbox_preview_response(markdown_proportional1)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "proportional", loose=True)

        resp = self.get_page_sandbox_preview_response(markdown_proportional2)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "proportional", loose=True)

        resp = (
            self.get_page_sandbox_preview_response(markdown_proportional_correct1))
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "proportional_correct", loose=True)

        resp = (
            self.get_page_sandbox_preview_response(markdown_proportional_correct2))
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, expected_warning_pattern % "proportional_correct", loose=True)

    def test_without_credit_mode_but_both_partial_and_partial_correct(self):
        expected_page_error = (
            "'allow_partial_credit' and "
            "'allow_partial_credit_subset_only' are not allowed to "
            "coexist when both attribute are 'True'")

        markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                     % {"shuffle": "False",
                        "credit_mode_str": "",
                        "extra_attr":
                             "allow_partial_credit_subset_only: True\n"
                            "allow_partial_credit: True"})

        resp = (
            self.get_page_sandbox_preview_response(markdown))
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(resp, PAGE_ERRORS, expected_page_error)

    def test_choice_not_stringifiable(self):
        expected_page_error = (
            "choice 2: unable to convert to string")

        class BadChoice:
            def __str__(self):
                raise Exception

        from relate.utils import dict_to_struct
        fake_page_desc = dict_to_struct(
            {'type': 'MultipleChoiceQuestion', 'id': 'ice_cream_toppings',
             'value': 1, 'shuffle': False,
             'prompt': '# Ice Cream Toppings\nWhich of the following are '
                       'ice cream toppings?\n',
             'choices': ['~CORRECT~ Sprinkles',
                         BadChoice(),
                         'Vacuum cleaner dust', 'Spider webs',
                         '~CORRECT~ Almond bits'],
             'allow_partial_credit': True,
             '_field_names': [
                 'type', 'id', 'value', 'shuffle',
                 'prompt', 'choices',
                 'allow_partial_credit']}
        )

        with mock.patch("relate.utils.dict_to_struct") as mock_dict_to_struct:
            mock_dict_to_struct.return_value = fake_page_desc

            markdown = (MULTIPLE_CHOICES_MARKDWON_NORMAL_PATTERN
                         % {"shuffle": "False",
                            "credit_mode_str": "",
                            "extra_attr": "allow_partial_credit: True"})

            resp = (
                self.get_page_sandbox_preview_response(markdown))
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(resp, PAGE_ERRORS,
                                               expected_page_error)


class BrokenPageDataTest(SingleCoursePageTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()

        client = Client()
        client.force_login(cls.student_participation.user)

        cls.start_flow(client, cls.flow_id)
        cls.end_flow(client)
        from course.models import FlowPageData
        cls.page_id = "ice_cream_toppings"
        cls.fpd = FlowPageData.objects.get(page_id=cls.page_id)

    def setUp(self):
        super().setUp()
        self.fpd.refresh_from_db()

    def test_broken_page_data_no_permutation(self):
        # no permutation
        self.fpd.data = {}
        self.fpd.save()
        self.fpd.refresh_from_db()
        resp = self.client.get(self.get_page_url_by_page_id(page_id=self.page_id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, ("existing choice permutation not "
                   "suitable for number of choices in question"))

    def test_broken_page_data_permutation_set_changed(self):
        # no permutation
        self.fpd.data = {"permutation": [0, 1]}
        self.fpd.save()
        self.fpd.refresh_from_db()
        resp = self.client.get(self.get_page_url_by_page_id(page_id=self.page_id))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, ("existing choice permutation not "
                   "suitable for number of choices in question"))


class MarkupToHtmlPlainTest(unittest.TestCase):
    # test course.page.choice.markup_to_html_plain
    def test_markup_to_html_plain_wrapp_by_p_tag(self):
        with mock.patch("course.page.choice.markup_to_html") as mock_mth:
            mock_mth.side_effect = lambda x, y: "<p>%s</p>" % y
            fake_page_context = object
            self.assertEqual(
                markup_to_html_plain(fake_page_context, "abcd"), "abcd")
            self.assertEqual(markup_to_html_plain(fake_page_context, ""), "")

    def test_markup_to_html_plain_wrapp_by_p_other_tag(self):
        with mock.patch("course.page.choice.markup_to_html") as mock_mth:
            mock_mth.side_effect = lambda x, y: "<div>%s</div>" % y
            fake_page_context = object
            self.assertEqual(
                markup_to_html_plain(fake_page_context, "abcd"),
                "<div>abcd</div>")


SURVEY_CHOICE_QUESTION_MARKDOWN = """
type: SurveyChoiceQuestion
id: age_group_with_comment_and_list_item
answer_comment: this is a survey question
prompt: |

    # Age

    How old are you?

choices:

    - 0-10 years
    - 11-20 years
    - 21-30 years
    - 31-40 years
    - 41-50 years
    - 51-60 years
    - 61-70 years
    - 71-80 years
    - 81-90 years
    - -
      - older
"""


class SurveyChoiceQuestionExtra(SingleCoursePageSandboxTestBaseMixin, TestCase):
    # extra tests for SurveyChoiceQuestion which has not been tested in
    # tests.test_pages.test_generic.py
    def test_page_has_answer_comment_attr(self):
        markdown = SURVEY_CHOICE_QUESTION_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertContains(resp, "older")
        self.assertContains(resp, "this is a survey question")

    def test_choice_not_stringifiable(self):
        expected_page_error = (
            "choice 10: unable to convert to string")

        class BadChoice:
            def __str__(self):
                raise Exception

        from relate.utils import dict_to_struct
        fake_page_desc = dict_to_struct(
            {'type': 'SurveyChoiceQuestion', 'id': 'age_group_with_comment',
             'answer_comment': 'this is a survey question',
             'prompt': '\n# Age\n\nHow old are you?\n',
             'choices': [
                 '0-10 years', '11-20 years', '21-30 years', '31-40 years',
                 '41-50 years', '51-60 years', '61-70 years', '71-80 years',
                 '81-90 years', BadChoice()],
             '_field_names': ['type', 'id', 'answer_comment',
                              'prompt', 'choices']}
        )

        with mock.patch("relate.utils.dict_to_struct") as mock_dict_to_struct:
            mock_dict_to_struct.return_value = fake_page_desc

            markdown = SURVEY_CHOICE_QUESTION_MARKDOWN

            resp = (
                self.get_page_sandbox_preview_response(markdown))
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(resp, PAGE_ERRORS,
                                               expected_page_error)

# vim: fdm=marker
