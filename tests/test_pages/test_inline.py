from __future__ import annotations


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

import pytest
from django.test import TestCase

from course.content import get_repo_blob
from course.flow import get_page_behavior
from tests.base_test_mixins import SingleCourseQuizPageTestMixin
from tests.constants import PAGE_ERRORS
from tests.test_sandbox import SingleCoursePageSandboxTestBaseMixin
from tests.utils import mock


INLINE_MULTI_MARKDOWN_SINGLE = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.

answers:

    blank1:
        type: ShortAnswer
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <plain> BAR
        - <plain>bar
"""

INLINE_MULTI_MARKDOWN_TWO_NOT_REQUIRED = r"""
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.
    A quarter equals [[choice1]].

answers:

    blank1:
        type: ShortAnswer
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <regex>(?:bar)?\s+
        - <plain> BAR
        - <plain>bar

    choice1:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - ~CORRECT~ 0.25
        - <div><p>This_should_be_wrapped_by_p_tag</p></div>
        - [0.25]
"""

INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.
    One dollar is [[blank2]].

answers:

    blank1:
        type: ShortAnswer
        %(attr1)s
        correct_answer:
        - <plain> BAR
        - <plain>bar

    blank2:
        type: ShortAnswer
        %(attr2)s
        correct_answer:
        - type: float
          rtol: 0.00001
          value: 1
        - <plain> one
"""

INLINE_MULTI_MARKDOWN_FLOAT_WITHOUT_TOL = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.
    One dollar is [[blank2]].

answers:

    blank1:
        type: ShortAnswer
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <plain> BAR
        - <plain>bar

    blank2:
        type: ShortAnswer
        width: 3em
        prepended_text: "$"
        hint: Blank with prepended text
        correct_answer:
        - type: float
          value: 1

"""

INLINE_MULTI_MARKDOWN_NOT_ALLOWED_EMBEDDED_QTYPE = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.

answers:

    blank1:
        type: SomeQuestionType
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <plain> BAR
        - <plain>bar

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_QUESTION_NOT_STRUCT = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.

answers:

    blank1: Something

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_HAS_NO_EXTRA_HTML = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    [[blank1]][[blank2]]

answers:
    blank1:
        type: ShortAnswer
        correct_answer:
        - <plain> BAR
        - <plain>bar

    blank2:
        type: ShortAnswer
        correct_answer:
        - <plain> BAR
        - <plain>bar
"""

INLINE_MULTI_MARKDOWN_EMBEDDED_NO_CORRECT_ANSWER = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.

answers:

    blank1:
        type: ShortAnswer
        correct_answer: []

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_TEXT_Q_NO_STRINGIFIABLE_CORRECT_ANSWER = r"""
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.

answers:

    blank1:
        type: ShortAnswer
        correct_answer:
        - <regex>(?:foo\s+)?\s

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_CHOICE_Q_NO_CORRECT_ANSWER = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[choice]] are often used in code examples.

answers:

    choice:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - 0.25

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_CHOICE_QUESTION = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[choice]] are often used in code examples.

answers:

    choice:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - ~CORRECT~ 0.25

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_NAMING_ERROR = r"""
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.
    A quarter equals [[1choice]].

answers:

    blank1:
        type: ShortAnswer
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <regex>(?:bar)?\s+
        - <plain> BAR
        - <plain>bar

    choice:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - ~CORRECT~ 0.25
        - <div><p>This_should_be_wrapped_by_p_tag</p></div>
        - [0.25]
"""

INLINE_MULTI_MARKDOWN_ANSWERS_NAMING_ERROR = r"""
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.
    A quarter equals [[choice1]].

answers:

    blank1:
        type: ShortAnswer
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <regex>(?:bar)?\s+
        - <plain> BAR
        - <plain>bar

    choice1:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - ~CORRECT~ 0.25
        - <div><p>This_should_be_wrapped_by_p_tag</p></div>
        - [0.25]

    2choice:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - ~CORRECT~ 0.25
        - <div><p>This_should_be_wrapped_by_p_tag</p></div>
        - [0.25]

"""

INLINE_MULTI_MARKDOWN_EMBEDDED_NAMING_DUPLICATED = r"""
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]][[blank1]] are often used in code examples.
    A quarter equals [[choice1]][[choice1]].

answers:

    blank1:
        type: ShortAnswer
        width: 4em
        required: False
        hint: Tex can be rendered in hint, e.g. $x_1$.
        hint_title: Hint
        correct_answer:
        - <regex>(?:bar)?\s+
        - <plain> BAR
        - <plain>bar

    choice1:
        type: ChoicesAnswer
        choices:
        - 0.2
        - 1/6
        - ~CORRECT~ 0.25
"""

INLINE_MULTI_MARKDOWN_REDUNDANT = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
answer_explanation: This is an explanation.
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.

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

"""

INLINE_MULTI_EMBEDDED_WITH_MARKDOWN = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
answer_explanation: This is an explanation.
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |

    Foo and [[blank1]] are often used in code examples.
    <img src="media:images/classroom.jpeg">

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
"""

INLINE_MULTI_MARKDOWN_NO_ANSWER_FIELD = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |
    abcd

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

"""

INLINE_MULTI_MARKDOWN_HAS_UNPAIRED_WRAPPER = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.

question: |
    [[[[blank1]]]]

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

"""

INLINE_MULTI_MARKDOWN_FEWER = """
type: InlineMultiQuestion
id: inlinemulti
value: 10
prompt: |

    # An InlineMultiQuestion example

    Complete the following paragraph.(old version)

question: |

    Foo and [[blank1]] are often used in code examples, or
    tutorials. $\\frac{1}{5}$ is equivalent to [[blank_2]].

    The correct answer for this choice question is [[choice_a]].
    The Upper case of "foo" is [[choice2]].

    One dollar is [[blank3]], and five percent is [[blank4]].

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

"""


def get_repo_blob_side_effect(repo, full_name, commit_sha):
    # Fake the inline multiple question yaml for specific commit
    if not (full_name == "questions/multi-question-example.yml"
            and commit_sha == b"ec41a2de73a99e6022060518cb5c5c162b88cdf5"):
        return get_repo_blob(repo, full_name, commit_sha)
    else:
        class Blob:
            pass
        blob = Blob()
        blob.data = INLINE_MULTI_MARKDOWN_FEWER.encode()
        return blob


def get_page_behavior_not_show_correctness_side_effect(page,
        permissions,
        session_in_progress,
        answer_was_graded,
        generates_grade,
        is_unenrolled_session,
        viewing_prior_version=False):
    page_behavior = get_page_behavior(
        page,
        permissions,
        session_in_progress,
        answer_was_graded,
        generates_grade,
        is_unenrolled_session,
        viewing_prior_version)
    page_behavior.show_correctness = False
    return page_behavior


class InlineMultiQuestionTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_single(self):
        markdown = INLINE_MULTI_MARKDOWN_SINGLE
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        # When there's more than one field, that field is force_required.
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, "This field is required.")

    def test_negative_width(self):
        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "width: -4em",
                       "attr2": "width: 5em"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "blank1: 'width': unrecognized width attribute string: '-4em'")

    def test_negative_weight(self):
        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "weight: 15",
                       "attr2": "weight: -5"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "blank2: 'weight' must be a non-negative value, got '-5' instead")

    def test_two_not_required(self):
        markdown = INLINE_MULTI_MARKDOWN_TWO_NOT_REQUIRED
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        # because this choice was wrapped by p tag before markdown handling
        self.assertContains(
            resp, "<p>This_should_be_wrapped_by_p_tag</p>", html=True)
        self.assertContains(resp, "[0.25]")

        # When there's more than one fields, can submit with no answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

        # partial answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": ["Bar"]})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0.5)

        # full answer, choice wrong answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": "Bar", "choice1": 4})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0.5)

        # full answer, all correct
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": "Bar", "choice1": 2})
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

    def test_submit_validation_error(self):
        markdown = INLINE_MULTI_MARKDOWN_FLOAT_WITHOUT_TOL
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            "Float match should have either rtol or "
            "atol--otherwise it will match any number")

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": "Bar", "blank2": "abc"})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(
            resp, "TypeError: Cannot convert expression to float")

    def test_not_allowed_embedded_question_type(self):
        markdown = INLINE_MULTI_MARKDOWN_NOT_ALLOWED_EMBEDDED_QTYPE
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "unknown embedded question type 'SomeQuestionType'")

    def test_embedded_question_not_struct(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_QUESTION_NOT_STRUCT
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "Embedded question 'blank1' must be a struct")

    def test_embedded_question_no_extra_html(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_HAS_NO_EXTRA_HTML
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

        # There's no html string between rendered blank1 field and blank2 field
        self.assertIn('</div> <div id="div_id_blank2"', resp.content.decode())

    def test_embedded_weight_count(self):
        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "weight: 15",
                       "attr2": "weight: 5"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        # no answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

        # partial answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": ["Bar"]})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0.75)

        # blank2 has not weight set
        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "weight: 15",
                       "attr2": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": ["Bar"]})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank2": "One"})
        self.assertEqual(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

    def test_embedded_width_attr(self):
        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "width: 15",
                       "attr2": "width: 85 %"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertIn("width: 8.5em", resp.context["form"].as_p())

        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "width: 15pt",
                       "attr2": "width: 5pt"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "width: one",
                       "attr2": "width: 5 pt"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "unrecognized width attribute string: 'one'")

        markdown = (INLINE_MULTI_MARKDOWN_EMBEDDED_ATTR_PATTERN
                    % {"attr1": "width: 15 pt",
                       "attr2": "width: 5 km"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "unsupported length unit 'km'")

    def test_embedded_question_no_correct_answer(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_NO_CORRECT_ANSWER
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "blank1: at least one answer must be provided")

    def test_embedded_text_question_no_stringifiable_correct_answer(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_TEXT_Q_NO_STRINGIFIABLE_CORRECT_ANSWER
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "blank1: no matcher is able to provide a plain-text "
            "correct answer")

    def test_embedded_choice_question_no_correct_answer(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_CHOICE_Q_NO_CORRECT_ANSWER
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            " more correct answer(s) expected  for question 'choice', "
            "0 found")

    def test_embedded_choice_not_stringifiable(self):
        expected_page_error = (
            "'choice' choice 2: unable to convert to string")

        class BadChoice:
            def __str__(self):
                raise Exception

        from relate.utils import dict_to_struct
        fake_page_desc = dict_to_struct(
            {"type": "InlineMultiQuestion", "id": "inlinemulti",
             "prompt":
                 "\n# An InlineMultiQuestion example\n\nComplete the "
                 "following paragraph.\n",
             "question": "\nFoo and [[choice]] are often used in code "
                         "examples.\n",
             "_field_names": [
                 "type", "id", "prompt", "question", "answers", "value"],
             "answers": {"_field_names": ["choice"],
                         "choice": {
                             "_field_names": ["type",
                                              "choices"],
                             "type": "ChoicesAnswer",
                             "choices": [0.2,
                                         BadChoice(),
                                         "~CORRECT~ 0.25"]}},
             "value": 10}
        )

        with mock.patch("relate.utils.dict_to_struct") as mock_dict_to_struct:
            mock_dict_to_struct.return_value = fake_page_desc

            markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_CHOICE_QUESTION

            resp = (
                self.get_page_sandbox_preview_response(markdown))
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(resp, PAGE_ERRORS,
                                               expected_page_error)

    def test_embedded_question_no_answer_field_defined(self):
        markdown = INLINE_MULTI_MARKDOWN_NO_ANSWER_FIELD
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "InlineMultiQuestion requires at least one answer field to "
            "be defined.")

    def test_embedded_naming_error(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_NAMING_ERROR
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "ValidationError")
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "could not instantiate flow page")

    def test_answers_naming_error(self):
        markdown = INLINE_MULTI_MARKDOWN_ANSWERS_NAMING_ERROR
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "invalid answers name '2choice'. A valid name should start "
            "with letters. Alphanumeric with underscores. Do not use "
            "spaces.")

    def test_embedded_naming_duplicated(self):
        markdown = INLINE_MULTI_MARKDOWN_EMBEDDED_NAMING_DUPLICATED
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "embedded question name 'blank1', 'choice1' not unique.")

    def test_has_unpaired_wrapper(self):
        markdown = INLINE_MULTI_MARKDOWN_HAS_UNPAIRED_WRAPPER
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "question has unpaired '[['.")

    def test_redundant(self):
        markdown = INLINE_MULTI_MARKDOWN_REDUNDANT
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            "redundant answers 'blank_2' provided for non-existing "
            "question(s).")

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"blank1": "Bar"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "This is an explanation.")
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

    def test_embedded_question_with_markdown(self):

        commit_sha = "b3cca1b997b24f526196a11c7e34098313a8950b"
        self.post_update_course_content(
            commit_sha=commit_sha.encode())

        markdown = INLINE_MULTI_EMBEDDED_WITH_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertContains(
            resp, f'<img src="/course/test-course/media/{commit_sha}'
                  '/images/classroom.jpeg">', html=True)


@pytest.mark.slow
class InlineMultiPageUpdateTest(SingleCourseQuizPageTestMixin, TestCase):
    page_id = "inlinemulti"

    def setUp(self):
        super().setUp()

    def test_quiz_inline_not_show_correctness(self):
        self.start_flow(self.flow_id)

        with mock.patch("course.flow.get_page_behavior") as mock_get_bhv:
            mock_get_bhv.side_effect = (
                get_page_behavior_not_show_correctness_side_effect)

            submit_answer_response, _ = (
                self.submit_page_answer_by_page_id_and_test(
                    self.page_id, do_grading=False))
            self.assertEqual(submit_answer_response.status_code, 200)

            # 7 answer
            self.assertContains(submit_answer_response, 'correctness="1"', count=0)
            self.assertContains(submit_answer_response, 'correctness="0"', count=0)

            self.end_flow()
            self.assertSessionScoreEqual(10)

    # {{{ Test bug fix in https://github.com/inducer/relate/pull/262

    def test_add_new_question(self):
        """Test bug fix in https://github.com/inducer/relate/pull/262
        """
        with mock.patch("course.content.get_repo_blob") as mock_get_repo_blob:
            mock_get_repo_blob.side_effect = get_repo_blob_side_effect

            self.post_update_course_content(
                commit_sha=b"ec41a2de73a99e6022060518cb5c5c162b88cdf5")

            self.start_flow(self.flow_id)
            resp = self.client.get(
                self.get_page_url_by_page_id(page_id=self.page_id))

            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "(old version)")

            answer_data = {
                "blank1": "Bar", "blank_2": "0.2", "blank3": "1",
                "blank4": "5", "choice2": "0", "choice_a": "0"}

            submit_answer_response, _ = (
                self.submit_page_answer_by_page_id_and_test(
                    self.page_id, answer_data=answer_data, expected_grades=10))

            # 6 correct answer
            self.assertContains(submit_answer_response,
                                'correctness="1"', count=6)

        self.post_update_course_content(
            commit_sha=b"4124e0c23e369d6709a670398167cb9c2fe52d35")
        resp = self.client.get(
            self.get_page_url_by_page_id(page_id=self.page_id))

        self.assertEqual(resp.status_code, 200)

        # 7 answer
        self.assertContains(resp, 'correctness="1"', count=7)

# vim: fdm=marker
