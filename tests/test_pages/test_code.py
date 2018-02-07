from __future__ import division

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

from django.test import TestCase
from course.constants import MAX_EXTRA_CREDIT_FACTOR

from tests.base_test_mixins import (  # noqa
    SubprocessRunpyContainerMixin
)
from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin, PAGE_ERRORS
)

MAX_AUTO_FEEDBACK_POINTS_VALICATION_ERROR_MSG_PATTERN = (  # noqa
    "'max_auto_feedback_points' is invalid: expecting "
    "a value within [0, %(max_extra_credit_factor)s], "
    "got %(invalid_value)s."
)

AUTO_FEEDBACK_POINTS_OUT_OF_RANGE_ERROR_MSG_PATTERN = (  # noqa
    "ValueError: grade point value is invalid: expecting within [0, %s], "
    "got %s."
)

MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN = """
type: PythonCodeQuestion
id: addition
value: 1
timeout: 10
%(extra_attribute)s
prompt: |

    # Adding two numbers in Python

setup_code: |
    import random

    a = random.uniform(-10, 10)
    b = random.uniform(-10, 10)

names_for_user: [a, b]

names_from_user: [c]

test_code: |
    if not isinstance(c, float):
        feedback.finish(0, "Your computed c is not a float.")

    correct_c = a + b
    rel_err = abs(correct_c-c)/abs(correct_c)

    if rel_err < 1e-7:
        feedback.finish(%(full_points)s, "Your computed c was correct.")
    else:
        feedback.finish(%(min_points)s, "Your computed c was incorrect.")

correct_code: |

    c = a + b
"""  # noqa


class CodeQuestionTest(SingleCoursePageSandboxTestBaseMixin,
                       SubprocessRunpyContainerMixin, TestCase):

    # {{{ https://github.com/inducer/relate/pull/448
    def test_max_auto_feedback_points_not_configured(self):
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute": "",
                       "full_points": 1.000000000002,
                       "min_points": 0
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

    def test_max_auto_feedback_points_configured_exceed_ceiling(self):
        invalid_max_points = 10.5
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute":
                           "max_auto_feedback_points: %s" % invalid_max_points,
                       "full_points": 1,
                       "min_points": 0
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxNotHaveValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            MAX_AUTO_FEEDBACK_POINTS_VALICATION_ERROR_MSG_PATTERN
            % {"max_extra_credit_factor": MAX_EXTRA_CREDIT_FACTOR,
               "invalid_value": invalid_max_points}
        )

    def test_max_auto_feedback_points_configured_negative(self):
        invalid_max_points = -0.0001
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute":
                           "max_auto_feedback_points: %s" % invalid_max_points,
                       "full_points": 1,
                       "min_points": 0
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertSandboxNotHaveValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            MAX_AUTO_FEEDBACK_POINTS_VALICATION_ERROR_MSG_PATTERN
            % {"max_extra_credit_factor": MAX_EXTRA_CREDIT_FACTOR,
               "invalid_value": invalid_max_points}
        )

    def test_feedback_code_error_exceed_1(self):
        # max_auto_feedback_points is not configured, so it's value default to 1
        max_auto_feedback_points = 1
        invalid_feedback_points = 1.1
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute": "",
                       "full_points": invalid_feedback_points,
                       "min_points": 0
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, None)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
            resp,
            AUTO_FEEDBACK_POINTS_OUT_OF_RANGE_ERROR_MSG_PATTERN
            % (max_auto_feedback_points, invalid_feedback_points)
        )

    def test_feedback_code_positive_close_to_0(self):
        # https://github.com/inducer/relate/pull/448#issuecomment-363655132
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute": "",
                       "full_points": 1,
                       "min_points": 0.00000000001
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)

        # Post a wrong answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b - a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

    def test_feedback_code_negative_close_to_0(self):
        # https://github.com/inducer/relate/pull/448#issuecomment-363655132
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute": "",
                       "full_points": 1,
                       "min_points": -0.00000000001
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)

        # Post a wrong answer
        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b - a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)

    def test_feedback_code_error_exceed_max_auto_feedback_points(self):
        max_auto_feedback_points = 5
        invalid_feedback_points = 5.1
        markdown = (MAX_AUTO_FEEDBACK_POINTS_CODE_MARKDWON_PATTERN
                    % {"extra_attribute": (
                            "max_auto_feedback_points: %s"
                            % max_auto_feedback_points),
                        "full_points": invalid_feedback_points,
                        "min_points": 0
                       })
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, None)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
            resp,
            AUTO_FEEDBACK_POINTS_OUT_OF_RANGE_ERROR_MSG_PATTERN
            % (max_auto_feedback_points, invalid_feedback_points)
        )

    # }}}

# vim: fdm=marker
