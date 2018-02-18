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

import six
import zipfile
import unittest
from unittest import skipIf
from django.test import TestCase, override_settings, RequestFactory

from docker.errors import APIError as DockerAPIError
from socket import error as socket_error, timeout as sock_timeout
import errno

from course.models import FlowSession
from course.page.code import (
    RUNPY_PORT, request_python_run_with_retries, InvalidPingResponse,
    is_nuisance_failure, PythonCodeQuestionWithHumanTextFeedback)
from course.utils import FlowPageContext, CoursePageContext

from tests.test_pages import QUIZ_FLOW_ID
from tests.test_pages.test_generic import MESSAGE_ANSWER_SAVED_TEXT

from tests.base_test_mixins import (
    SubprocessRunpyContainerMixin, SingleCoursePageTestMixin,
    FallBackStorageMessageTestMixin)
from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin, PAGE_ERRORS
)
from tests.utils import LocmemBackendTestsMixin, mock, mail

from . import markdowns

NO_CORRECTNESS_INFO_MSG = "No information on correctness of answer."

NOT_ALLOW_MULTIPLE_SUBMISSION_WARNING = (
    "code question does not explicitly "
    "allow multiple submission. Either add "
    "access_rules/add_permssions/change_answer "
    "or add 'single_submission: True' to confirm that you intend "
    "for only a single submission to be allowed. "
    "While you're at it, consider adding "
    "access_rules/add_permssions/see_correctness."
)

MAX_AUTO_FEEDBACK_POINTS_VALICATION_ERROR_MSG_PATTERN = (  # noqa
    "'max_auto_feedback_points' is invalid: expecting "
    "a value within [0, %(max_extra_credit_factor)s], "
    "got %(invalid_value)s."
)

GRADE_CODE_FAILING_MSG = (
    "The grading code failed. Sorry about that."
)

RUNPY_WITH_RETRIES_PATH = "course.page.code.request_python_run_with_retries"


def get_flow_page_desc_value_zero_human_full_percentage_side_effect(
        flow_id, flow_desc, group_id, page_id):
    from course.content import get_flow_page_desc
    result = get_flow_page_desc(flow_id, flow_desc, group_id, page_id)
    result.value = 0
    result.human_feedback_percentage = 100
    return result


class SingleCourseQuizPageCodeQuestionTest(
            SingleCoursePageTestMixin, FallBackStorageMessageTestMixin,
            SubprocessRunpyContainerMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageCodeQuestionTest, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)

    def setUp(self):  # noqa
        super(SingleCourseQuizPageCodeQuestionTest, self).setUp()
        # This is needed to ensure student is logged in
        self.c.force_login(self.student_participation.user)

    def test_code_page_correct(self):
        page_id = "addition"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_code_page_wrong(self):
        page_id = "addition"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['c = a - b\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_code_page_identical_to_reference(self):
        page_id = "addition"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['c = a + b\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp,
                ("It looks like you submitted code "
                 "that is identical to the reference "
                 "solution. This is not allowed."))
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_download_code_submissions_no_answer(self):
        group_page_id = "quiz_tail/addition"
        self.end_flow()

        # no answer
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=group_page_id, flow_id=self.flow_id)
            self.assertEqual(resp.status_code, 200)
            prefix, zip_file = resp["Content-Disposition"].split('=')
            self.assertEqual(prefix, "attachment; filename")
            self.assertEqual(resp.get('Content-Type'), "application/zip")

            buf = six.BytesIO(resp.content)
            with zipfile.ZipFile(buf, 'r') as zf:
                self.assertIsNone(zf.testzip())
                self.assertEqual(
                    len([f for f in zf.filelist if f.filename.endswith('.py')]), 0)
                for f in zf.filelist:
                    self.assertGreater(f.file_size, 0)

    def test_download_code_submissions_has_answer(self):
        group_page_id = "quiz_tail/addition"

        # create an answer
        page_id = "addition"
        self.post_answer_by_page_id(
            page_id, {"answer": ['c = a - b\r']})
        self.end_flow()
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.post_download_all_submissions_by_group_page_id(
                group_page_id=group_page_id, flow_id=self.flow_id)
            self.assertEqual(resp.status_code, 200)
            prefix, zip_file = resp["Content-Disposition"].split('=')
            self.assertEqual(prefix, "attachment; filename")
            self.assertEqual(resp.get('Content-Type'), "application/zip")

            buf = six.BytesIO(resp.content)
            with zipfile.ZipFile(buf, 'r') as zf:
                self.assertIsNone(zf.testzip())
                # todo: make more assertions in terms of file content
                self.assertEqual(
                    len([f for f in zf.filelist if f.filename.endswith('.py')]), 1)
                for f in zf.filelist:
                    self.assertGreater(f.file_size, 0)

    def test_code_page_analytics_no_answer(self):
        # analytics with no answer
        page_id = "addition"
        self.end_flow()
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_flow_page_analytics(
                flow_id=self.flow_id, group_id="quiz_tail",
                page_id=page_id)
            self.assertEqual(resp.status_code, 200)

    def test_code_page_analytics_has_answer(self):
        # create an answer
        page_id = "addition"
        self.post_answer_by_page_id(
            page_id, {"answer": ['c = a - b\r']})
        self.end_flow()

        # todo: make more assertions in terms of content
        with self.temporarily_switch_to_user(self.instructor_participation.user):
            resp = self.get_flow_page_analytics(
                flow_id=self.flow_id, group_id="quiz_tail",
                page_id=page_id)
            self.assertEqual(resp.status_code, 200)

    def test_code_human_feedback_page_submit(self):
        page_id = "pymult"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['c = a * b\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(None)

    def test_code_human_feedback_page_grade1(self):
        page_id = "pymult"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['c = b * a\r']})
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "'c' looks good")
        self.assertEqual(self.end_flow().status_code, 200)

        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }

        resp = self.post_grade_by_page_id(page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The human grader assigned 2/2 points.")

        # since the test_code didn't do a feedback.set_points() after
        # check_scalar()
        self.assertSessionScoreEqual(None)

    def test_code_human_feedback_page_grade2(self):
        page_id = "pymult"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['c = a / b\r']})
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "'c' is inaccurate")
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The autograder assigned 0/2 points.")

        self.assertEqual(self.end_flow().status_code, 200)

        feedback_text = "This is the feedback from instructor."

        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"],
            "feedback_text": feedback_text
        }
        resp = self.post_grade_by_page_id(page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The human grader assigned 2/2 points.")
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, feedback_text)
        self.assertSessionScoreEqual(2)

    def test_code_human_feedback_page_grade3(self):
        page_id = "py_simple_list"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['b = [a + 1] * 50\r']})

        # this is testing feedback.finish(0.3, feedback_msg)
        # 2 * 0.3 = 0.6
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The autograder assigned 0.90/3 points.")
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The elements in b have wrong values")
        self.assertEqual(self.end_flow().status_code, 200)

        # The page is not graded before human grading.
        self.assertSessionScoreEqual(None)

    def test_code_human_feedback_page_grade4(self):
        page_id = "py_simple_list"
        resp = self.post_answer_by_page_id(
            page_id, {"answer": ['b = [a] * 50\r']})
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "b looks good")
        self.assertEqual(self.end_flow().status_code, 200)

        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }

        resp = self.post_grade_by_page_id(page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The human grader assigned 1/1 points.")

        self.assertSessionScoreEqual(4)

        grade_data = {
            "released": ["on"]
        }

        resp = self.post_grade_by_page_id(page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertFormErrorLoose(resp, None)
        self.assertSessionScoreEqual(None)

        # not released
        feedback_text = "This is the feedback from instructor."
        grade_data = {
            "grade_percent": ["100"],
            "feedback_text": feedback_text
        }

        resp = self.post_grade_by_page_id(page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackNotContainsFeedback(
                resp, "The human grader assigned 1/1 points.")
        self.assertResponseContextAnswerFeedbackNotContainsFeedback(
                resp, feedback_text)

        self.assertSessionScoreEqual(None)


class CodeQuestionTest(SingleCoursePageSandboxTestBaseMixin,
                       SubprocessRunpyContainerMixin, LocmemBackendTestsMixin,
                       TestCase):

    def test_data_files_missing_random_question_data_file(self):
        file_name = "foo"
        markdown = (
                markdowns.CODE_MARKDWON_PATTERN_WITH_DATAFILES
                % {"extra_data_file": "- %s" % file_name}
        )
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "data file '%s' not found" % file_name)

    def test_data_files_missing_random_question_data_file_bad_format(self):
        markdown = markdowns.CODE_MARKDWON_WITH_DATAFILES_BAD_FORMAT
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "data file '%s' not found" % "['foo', 'bar']")

    def test_not_multiple_submit_warning(self):
        markdown = (
                markdowns.CODE_MARKDWON_PATTERN_WITH_DATAFILES
                % {"extra_data_file": ""}
        )
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            NOT_ALLOW_MULTIPLE_SUBMISSION_WARNING
        )

    def test_not_multiple_submit_warning2(self):
        markdown = markdowns.CODE_MARKDWON_NOT_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT1
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            NOT_ALLOW_MULTIPLE_SUBMISSION_WARNING
        )

    def test_not_multiple_submit_warning3(self):
        markdown = markdowns.CODE_MARKDWON_NOT_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT2
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            NOT_ALLOW_MULTIPLE_SUBMISSION_WARNING
        )

    def test_allow_multiple_submit(self):
        markdown = markdowns.CODE_MARKDWON
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

    def test_explicity_not_allow_multiple_submit(self):
        markdown = (
                markdowns.CODE_MARKDWON_PATTERN_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT
                % {"extra_data_file": ""}
        )
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

    def test_question_without_test_code(self):
        markdown = markdowns.CODE_MARKDWON_PATTERN_WITHOUT_TEST_CODE
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, None)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
            resp, NO_CORRECTNESS_INFO_MSG)

    def test_question_without_correct_code(self):
        markdown = markdowns.CODE_MARKDWON_PATTERN_WITHOUT_CORRECT_CODE
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

    def test_question_with_human_feedback_both_feedback_value_feedback_percentage_present(self):  # noqa
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 3,
                       "human_feedback": "human_feedback_value: 2",
                       "extra_attribute": "human_feedback_percentage: 20"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "'human_feedback_value' and "
                               "'human_feedback_percentage' are not "
                               "allowed to coexist")

    def test_question_with_human_feedback_neither_feedback_value_feedback_percentage_present(self):  # noqa
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 3,
                       "human_feedback": "",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "expecting either 'human_feedback_value' "
                               "or 'human_feedback_percentage', found neither.")

    def test_question_with_human_feedback_used_feedback_value_warning(self):
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 3,
                       "human_feedback": "human_feedback_value: 2",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            "Used deprecated 'human_feedback_value' attribute--"
            "use 'human_feedback_percentage' instead."
        )

    def test_question_with_human_feedback_used_feedback_value_bad_value(self):
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 0,
                       "human_feedback": "human_feedback_value: 2",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "'human_feedback_value' attribute is not allowed "
                               "if value of question is 0, use "
                               "'human_feedback_percentage' instead")

    def test_question_with_human_feedback_used_feedback_value_invalid(self):
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 2,
                       "human_feedback": "human_feedback_value: 3",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "human_feedback_value greater than overall "
                               "value of question")

    def test_question_with_human_feedback_feedback_percentage_invalid(self):
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 2,
                       "human_feedback": "human_feedback_percentage: 120",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "the value of human_feedback_percentage "
                               "must be between 0 and 100")

    def test_question_with_human_feedback_value_0_feedback_full_percentage(self):
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 0,
                       "human_feedback": "human_feedback_percentage: 100",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

    def test_question_with_human_feedback_value_0_feedback_0_percentage(self):
        markdown = (markdowns.CODE_WITH_HUMAN_FEEDBACK_MARKDWON_PATTERN
                    % {"value": 0,
                       "human_feedback": "human_feedback_percentage: 0",
                       "extra_attribute": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

    def test_request_python_run_with_retries_raise_uncaught_error_in_sandbox(self):
        with mock.patch(
            RUNPY_WITH_RETRIES_PATH,
            autospec=True
        ) as mock_runpy:
            expected_error_str = ("This is an error raised with "
                                  "request_python_run_with_retries")

            # correct_code_explanation and correct_code
            expected_feedback = (
                '<p>This is the <a href="http://example.com/1">explanation'
                '</a>.</p>The following code is a valid answer: '
                '<pre>\nc = 2 + 1\n</pre>')
            mock_runpy.side_effect = RuntimeError(expected_error_str)

            resp = self.get_page_sandbox_submit_answer_response(
                markdowns.CODE_MARKDWON,
                answer_data={"answer": ['c = 1 + 2\r']})
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp,
                                                                      None)

            self.assertResponseContextContains(resp, "correct_answer",
                                               expected_feedback)
            # No email when in sandbox
            self.assertEqual(len(mail.outbox), 0)

    def test_request_python_run_with_retries_raise_uncaught_error_debugging(self):
        with mock.patch(
            RUNPY_WITH_RETRIES_PATH,
            autospec=True
        ) as mock_runpy:
            expected_error_str = ("This is an error raised with "
                                  "request_python_run_with_retries")
            mock_runpy.side_effect = RuntimeError(expected_error_str)

            with override_settings(DEBUG=True):
                resp = self.get_page_sandbox_submit_answer_response(
                    markdowns.CODE_MARKDWON,
                    answer_data={"answer": ['c = 1 + 2\r']})
                self.assertEqual(resp.status_code, 200)
                self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp,
                                                                          None)
                # No email when debugging
                self.assertEqual(len(mail.outbox), 0)

    def test_request_python_run_with_retries_raise_uncaught_error(self):
        with mock.patch(
            RUNPY_WITH_RETRIES_PATH,
            autospec=True
        ) as mock_runpy:
            expected_error_str = ("This is an error raised with "
                                  "request_python_run_with_retries")
            mock_runpy.side_effect = RuntimeError(expected_error_str)

            with mock.patch("course.page.PageContext") as mock_page_context:
                mock_page_context.return_value.in_sandbox = False

                # This remove the warning caused by mocked commit_sha value
                # "CacheKeyWarning: Cache key contains characters that
                # will cause errors ..."
                mock_page_context.return_value.commit_sha = b"1234"

                resp = self.get_page_sandbox_submit_answer_response(
                    markdowns.CODE_MARKDWON,
                    answer_data={"answer": ['c = 1 + 2\r']})
                self.assertEqual(resp.status_code, 200)
                self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp,
                                                                          None)
                self.assertEqual(len(mail.outbox), 1)
                self.assertIn(expected_error_str, mail.outbox[0].body)

    def test_send_email_failure_when_request_python_run_with_retries_raise_uncaught_error(self):  # noqa
        with mock.patch(
            RUNPY_WITH_RETRIES_PATH,
            autospec=True
        ) as mock_runpy:
            expected_error_str = ("This is an error raised with "
                                  "request_python_run_with_retries")
            mock_runpy.side_effect = RuntimeError(expected_error_str)

            with mock.patch("course.page.PageContext") as mock_page_context:
                mock_page_context.return_value.in_sandbox = False

                # This remove the warning caused by mocked commit_sha value
                # "CacheKeyWarning: Cache key contains characters that
                # will cause errors ..."
                mock_page_context.return_value.commit_sha = b"1234"

                with mock.patch("django.core.mail.message.EmailMessage.send") as mock_send:  # noqa
                    mock_send.side_effect = RuntimeError("some email send error")

                    resp = self.get_page_sandbox_submit_answer_response(
                        markdowns.CODE_MARKDWON,
                        answer_data={"answer": ['c = 1 + 2\r']})
                    self.assertContains(resp, expected_error_str)
                    self.assertEqual(resp.status_code, 200)
                    self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp,
                                                                              None)
                    self.assertEqual(len(mail.outbox), 0)

    def assert_runpy_result_and_response(self, result_type, expected_msgs=None,
                                         not_execpted_msgs=None,
                                         correctness=0, mail_count=0, in_html=False,
                                         **extra_result):
        with mock.patch(RUNPY_WITH_RETRIES_PATH, autospec=True) as mock_runpy:
            result = {"result": result_type}
            result.update(extra_result)
            mock_runpy.return_value = result

            resp = self.get_page_sandbox_submit_answer_response(
                markdowns.CODE_MARKDWON,
                answer_data={"answer": ['c = 1 + 2\r']})

            if expected_msgs is not None:
                if isinstance(expected_msgs, six.text_type):
                    expected_msgs = [expected_msgs]
                for msg in expected_msgs:
                    self.assertResponseContextAnswerFeedbackContainsFeedback(
                        resp, msg, html=in_html)

            if not_execpted_msgs is not None:
                if isinstance(not_execpted_msgs, six.text_type):
                    not_execpted_msgs = [not_execpted_msgs]
                for msg in not_execpted_msgs:
                    self.assertResponseContextAnswerFeedbackNotContainsFeedback(
                        resp, msg, html=in_html)

            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp,
                                                                      correctness)
            self.assertEqual(len(mail.outbox), mail_count)

    def test_request_python_run_with_retries_timed_out(self):
        self.assert_runpy_result_and_response(
            "timeout",
            "Your code took too long to execute.")

    def test_user_compile_error(self):
        self.assert_runpy_result_and_response(
            "user_compile_error",
            "Your code failed to compile."
        )

    def test_user_error(self):
        self.assert_runpy_result_and_response(
            "user_error",
            "Your code failed with an exception.")

    def test_unknown_error(self):
        with self.assertRaises(RuntimeError) as e:
            self.assert_runpy_result_and_response(
                "unknown_error", None)
        self.assertIn("invalid runpy result: unknown_error", str(e.exception))

    def test_traceback_in_feedback(self):
        self.assert_runpy_result_and_response(
            "user_error",
            "some traceback",
            traceback="some traceback"
        )

    def test_stdout_in_feedback(self):
        self.assert_runpy_result_and_response(
            "user_error",
            "some stdout",
            stdout="some stdout"
        )

    def test_stderr_in_feedback(self):
        self.assert_runpy_result_and_response(
            "user_error",
            "some stderr",
            stderr="some stderr"
        )

    def test_exechost_local(self):
        self.assert_runpy_result_and_response(
            "user_error",
            not_execpted_msgs="Your code ran on",
            exec_host="localhost"
        )

    def test_exechost_ip(self):
        with mock.patch("socket.gethostbyaddr") as mock_get_host:
            ip = "192.168.1.100"
            resovled = "example.com"
            mock_get_host.side_effect = lambda x: (resovled, [], [])
            self.assert_runpy_result_and_response(
                "user_error",
                execpted_msgs="Your code ran on %s" % resovled,
                exec_host=ip
            )

    def test_exechost_ip_resolve_failure(self):
        with mock.patch("socket.gethostbyaddr") as mock_get_host:
            ip = "192.168.1.100"
            mock_get_host.side_effect = socket_error
            self.assert_runpy_result_and_response(
                "user_error",
                execpted_msgs="Your code ran on %s" % ip,
                exec_host=ip
            )

    def test_figures(self):
        bmp_b64 = ("data:image/bmp;base64,Qk1GAAAAAAAAAD4AAAAoAAAAAgAAAAIA"
                   "AAABAAEAAAAAAAgAAADEDgAAxA4AAAAAAAAAAAAAAAAAAP///wDAAAA"
                   "AwAAAAA==")
        jpeg_b64 = ("data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/4QBa"
                    "RXhpZgAATU0AKgAAAAgABQMBAAUAAAABAAAASgMDAAEAAAABAAAAAFE"
                    "QAAEAAAABAQAAAFERAAQAAAABAAAOwlESAAQAAAABAAAOwgAAAAAAAY"
                    "agAACxj//bAEMAAgEBAgEBAgICAgICAgIDBQMDAwMDBgQEAwUHBgcHB"
                    "wYHBwgJCwkICAoIBwcKDQoKCwwMDAwHCQ4PDQwOCwwMDP/bAEMBAgIC"
                    "AwMDBgMDBgwIBwgMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAw"
                    "MDAwMDAwMDAwMDAwMDAwMDAwMDP/AABEIAAIAAgMBIgACEQEDEQH/xA"
                    "AfAAABBQEBAQEBAQAAAAAAAAAAAQIDBAUGBwgJCgv/xAC1EAACAQMDA"
                    "gQDBQUEBAAAAX0BAgMABBEFEiExQQYTUWEHInEUMoGRoQgjQrHBFVLR8"
                    "CQzYnKCCQoWFxgZGiUmJygpKjQ1Njc4OTpDREVGR0hJSlNUVVZXWFlaY"
                    "2RlZmdoaWpzdHV2d3h5eoOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmq"
                    "srO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4eLj5OXm5+jp6vHy8/T"
                    "19vf4+fr/xAAfAQADAQEBAQEBAQEBAAAAAAAAAQIDBAUGBwgJCgv/xA"
                    "C1EQACAQIEBAMEBwUEBAABAncAAQIDEQQFITEGEkFRB2FxEyIygQgUQp"
                    "GhscEJIzNS8BVictEKFiQ04SXxFxgZGiYnKCkqNTY3ODk6Q0RFRkdIS"
                    "UpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqCg4SFhoeIiYqSk5SVlpeY"
                    "mZqio6Slpqeoqaqys7S1tre4ubrCw8TFxsfIycrS09TV1tfY2dri4+T"
                    "l5ufo6ery8/T19vf4+fr/2gAMAwEAAhEDEQA/AP38ooooA//Z")
        png_b64 = (
            "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACAQMAAAB"
            "IeJ9nAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAGUExURQAAAP///"
            "6XZn90AAAAJcEhZcwAADsIAAA7CARUoSoAAAAAMSURBVBjTYzjAcAAAAwQBgXn"
            "6PNcAAAAASUVORK5CYII=")

        self.assert_runpy_result_and_response(
            "user_error",
            expected_msgs=[png_b64, jpeg_b64, "Figure1", "Figure 1",
                           "Figure3", "Figure 3", ],
            not_execpted_msgs=[bmp_b64, "Figure2", "Figure 2"],
            figures=[
                [1, "image/png", png_b64],
                [2, "image/bmp", bmp_b64],
                [3, "image/jpeg", jpeg_b64]
            ]
        )

    def test_html_in_feedback(self):
        html = "<ul><li>some html</li></ul>"
        self.assert_runpy_result_and_response(
            "user_error",
            html,
            html=[html]
        )

        js = "<script>console.log('good')</script>"
        html_with_js = html + js
        self.assert_runpy_result_and_response(
            "user_error",
            expected_msgs=html,
            not_execpted_msgs=js,  # js is sanitized
            html=[html_with_js]
        )

    def test_html_audio(self):
        b64_data = "T2dnUwACAAAAAAAAAAA+HAAAAAAAAGyawCEBQGZpc2h"
        audio1 = (
            '<audio controls><source src="data:audio/wav;base64,'
            '%s" type="audio/wav">'
            '</audio>' % b64_data)
        audio1_1 = (
            '<audio control><source src="data:audio/wav;base64,'
            '%s" type="audio/wav">'
            '</audio>' % b64_data)
        audio1_2 = (
            '<audio controls><source href="data:audio/wav;base64,'
            '%s" type="audio/wav">'
            '</audio>' % b64_data)
        audio2 = (
            '<audio><source src="data:audio/wav;base64,'
            '%s" type="audio/wav">'
            '</audio>' % b64_data)
        audio3 = (
            '<audio controls><source src="data:audio/ogg;base64,'
            '%s" type="audio/ogg">'
            '</audio>' % b64_data)
        audio4 = (
            '<audio controls><source src="hosse.wav" type="audio/wav">'
            '</audio>')

        html = [audio1, audio1_1, audio1_2, audio2, audio3, audio4]

        self.assert_runpy_result_and_response(
            "user_error",
            expected_msgs=[audio1],
            not_execpted_msgs=[audio1_1, audio1_2, audio2, audio3, audio4],
            html=html,
            in_html=True
        )

    def test_html_img(self):
        b64_data = ("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACAQMAAAB"
            "IeJ9nAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAGUExURQAAAP///"
            "6XZn90AAAAJcEhZcwAADsIAAA7CARUoSoAAAAAMSURBVBjTYzjAcAAAAwQBgXn"
            "6PNcAAAAASUVORK5CYII=")

        img1 = (
            '<img src="data:image/png;base64,%s" alt="test img" '
            'title="test image">' % b64_data)

        img1_1 = (
            '<img src="data:image/png;base64,%s" '
            'alt="test img" '
            'width="126" '
            'height="44">' % b64_data)

        img1_2 = (
            '<img href="data:image/png;base64,%s" '
            'alt="test img" title="test image">' % b64_data)

        img2 = (
            '<img src="data:image/bmp;base64,%s" '
            'alt="test img" title="test image">' % b64_data)

        html = [img1, img1_1, img1_2, img2]

        self.assert_runpy_result_and_response(
            "user_error",
            expected_msgs=[img1],
            # not_execpted_msgs=[img1_1, img1_2, img2],
            html=html,
            in_html=True,
        )

    def test_html_non_text_bleached_in_feedback(self):
        self.assert_runpy_result_and_response(
            "user_error",
            "(Non-string in 'HTML' output filtered out)",
            html=b"not string"
        )


class RequestPythonRunWithRetriesTest(unittest.TestCase):
    # Testing course.page.code.request_python_run_with_retries,
    # adding tests for use cases that didn't cover in other tests

    @override_settings(RELATE_DOCKER_RUNPY_IMAGE="some_other_image")
    def test_image_none(self):
        # Testing if image is None, settings.RELATE_DOCKER_RUNPY_IMAGE is used
        with mock.patch("docker.client.Client.create_container") as mock_create_ctn:

            # this will raise KeyError
            mock_create_ctn.return_value = {}

            with self.assertRaises(KeyError):
                request_python_run_with_retries(
                    run_req={}, run_timeout=0.1)
                self.assertEqual(mock_create_ctn.call_count, 1)
                self.assertIn("some_other_image", mock_create_ctn.call_args[0])

    @override_settings(RELATE_DOCKER_RUNPY_IMAGE="some_other_image")
    def test_image_not_none(self):
        # Testing if image is None, settings.RELATE_DOCKER_RUNPY_IMAGE is used
        with mock.patch("docker.client.Client.create_container") as mock_create_ctn:

            # this will raise KeyError
            mock_create_ctn.return_value = {}

            my_image = "my_runpy_image"

            with self.assertRaises(KeyError):
                request_python_run_with_retries(
                    run_req={}, image=my_image, run_timeout=0.1)
                self.assertEqual(mock_create_ctn.call_count, 1)
                self.assertIn(my_image, mock_create_ctn.call_args[0])

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_docker_container_ping_failure(self):
        with (
                mock.patch("docker.client.Client.create_container")) as mock_create_ctn, (  # noqa
                mock.patch("docker.client.Client.start")) as mock_ctn_start, (
                mock.patch("docker.client.Client.logs")) as mock_ctn_logs, (
                mock.patch("docker.client.Client.remove_container")) as mock_remove_ctn, (  # noqa
                mock.patch("docker.client.Client.inspect_container")) as mock_inpect_ctn, (  # noqa
                mock.patch("six.moves.http_client.HTTPConnection.request")) as mock_ctn_request:  # noqa

            mock_create_ctn.return_value = {"Id": "someid"}
            mock_ctn_start.side_effect = lambda x: None
            mock_ctn_logs.side_effect = lambda x: None
            mock_remove_ctn.return_value = None
            fake_host_ip = "192.168.1.100"
            fake_host_port = "69999"

            mock_inpect_ctn.return_value = {
                "NetworkSettings": {
                    "Ports": {"%d/tcp" % RUNPY_PORT: (
                        {"HostIp": fake_host_ip, "HostPort": fake_host_port},
                    )}
                }}

            with self.subTest(case="Docker ping timeout with BadStatusLine Error"):
                from six.moves.http_client import BadStatusLine
                fake_bad_statusline_msg = "my custom bad status"
                mock_ctn_request.side_effect = BadStatusLine(fake_bad_statusline_msg)

                # force timeout
                with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                    res = request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(res["result"], "uncaught_error")
                    self.assertEqual(res['message'],
                                     "Timeout waiting for container.")
                    self.assertEqual(res["exec_host"], fake_host_ip)
                    self.assertIn(fake_bad_statusline_msg, res["traceback"])

            with self.subTest(
                    case="Docker ping timeout with InvalidPingResponse Error"):
                invalid_ping_resp_msg = "my custom invalid ping response exception"
                mock_ctn_request.side_effect = (
                    InvalidPingResponse(invalid_ping_resp_msg))

                # force timeout
                with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                    res = request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(res["result"], "uncaught_error")
                    self.assertEqual(res['message'],
                                     "Timeout waiting for container.")
                    self.assertEqual(res["exec_host"], fake_host_ip)
                    self.assertIn(InvalidPingResponse.__name__, res["traceback"])
                    self.assertIn(invalid_ping_resp_msg, res["traceback"])

            with self.subTest(
                    case="Docker ping socket error with erron ECONNRESET"):
                my_socket_error = socket_error()
                my_socket_error.errno = errno.ECONNRESET
                mock_ctn_request.side_effect = my_socket_error

                # force timeout
                with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                    res = request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(res["result"], "uncaught_error")
                    self.assertEqual(res['message'],
                                     "Timeout waiting for container.")
                    self.assertEqual(res["exec_host"], fake_host_ip)
                    self.assertIn(type(my_socket_error).__name__, res["traceback"])

            with self.subTest(
                    case="Docker ping socket error with erron ECONNREFUSED"):
                my_socket_error = socket_error()
                my_socket_error.errno = errno.ECONNREFUSED
                mock_ctn_request.side_effect = my_socket_error

                # force timeout
                with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                    res = request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(res["result"], "uncaught_error")
                    self.assertEqual(res['message'],
                                     "Timeout waiting for container.")
                    self.assertEqual(res["exec_host"], fake_host_ip)
                    self.assertIn(type(my_socket_error).__name__, res["traceback"])

            with self.subTest(
                    case="Docker ping socket error with erron EAFNOSUPPORT"):
                my_socket_error = socket_error()

                # This errno should raise error
                my_socket_error.errno = errno.EAFNOSUPPORT
                mock_ctn_request.side_effect = my_socket_error

                # force timeout
                with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                    with self.assertRaises(socket_error) as e:
                        request_python_run_with_retries(
                            run_req={}, run_timeout=0.1, retry_count=0)
                        self.assertEqual(e.exception.errno, my_socket_error.errno)

                with self.assertRaises(socket_error) as e:
                    request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(e.exception.errno, my_socket_error.errno)

            # This should be the last subTest, because this will the behavior of
            # change mock_remove_ctn
            with self.subTest(
                    case="Docker ping timeout with InvalidPingResponse and "
                         "remove container failed with APIError"):
                invalid_ping_resp_msg = "my custom invalid ping response exception"
                fake_host_ip = "0.0.0.0"

                mock_inpect_ctn.return_value = {
                    "NetworkSettings": {
                        "Ports": {"%d/tcp" % RUNPY_PORT: (
                            {"HostIp": fake_host_ip, "HostPort": fake_host_port},
                        )}
                    }}

                mock_ctn_request.side_effect = (
                    InvalidPingResponse(invalid_ping_resp_msg))
                mock_remove_ctn.reset_mock()
                from django.http import HttpResponse
                fake_response_content = "this should not appear"
                mock_remove_ctn.side_effect = DockerAPIError(
                    message="my custom docker api error",
                    response=HttpResponse(content=fake_response_content))

                # force timeout
                with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                    res = request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(res["result"], "uncaught_error")
                    self.assertEqual(res['message'],
                                     "Timeout waiting for container.")
                    self.assertEqual(res["exec_host"], "localhost")
                    self.assertIn(InvalidPingResponse.__name__, res["traceback"])
                    self.assertIn(invalid_ping_resp_msg, res["traceback"])

                    # No need to bother the students with this nonsense.
                    self.assertNotIn(DockerAPIError.__name__, res["traceback"])
                    self.assertNotIn(fake_response_content, res["traceback"])

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_docker_container_ping_return_not_ok(self):
        with (
                mock.patch("docker.client.Client.create_container")) as mock_create_ctn, (  # noqa
                mock.patch("docker.client.Client.start")) as mock_ctn_start, (
                mock.patch("docker.client.Client.logs")) as mock_ctn_logs, (
                mock.patch("docker.client.Client.remove_container")) as mock_remove_ctn, (  # noqa
                mock.patch("docker.client.Client.inspect_container")) as mock_inpect_ctn, (  # noqa
                mock.patch("six.moves.http_client.HTTPConnection.request")) as mock_ctn_request, (  # noqa
                mock.patch("six.moves.http_client.HTTPConnection.getresponse")) as mock_ctn_get_response:  # noqa

            mock_create_ctn.return_value = {"Id": "someid"}
            mock_ctn_start.side_effect = lambda x: None
            mock_ctn_logs.side_effect = lambda x: None
            mock_remove_ctn.return_value = None
            fake_host_ip = "192.168.1.100"
            fake_host_port = "69999"

            mock_inpect_ctn.return_value = {
                "NetworkSettings": {
                    "Ports": {"%d/tcp" % RUNPY_PORT: (
                        {"HostIp": fake_host_ip, "HostPort": fake_host_port},
                    )}
                }}

            # force timeout
            with mock.patch("course.page.code.DOCKER_TIMEOUT", 0.0001):
                with self.subTest(
                        case="Docker ping response not OK"):
                    mock_ctn_request.side_effect = lambda x, y: None
                    mock_ctn_get_response.return_value = six.BytesIO(b"NOT OK")

                    res = request_python_run_with_retries(
                        run_req={}, run_timeout=0.1, retry_count=0)
                    self.assertEqual(res["result"], "uncaught_error")
                    self.assertEqual(res['message'],
                                     "Timeout waiting for container.")
                    self.assertEqual(res["exec_host"], fake_host_ip)
                    self.assertIn(InvalidPingResponse.__name__, res["traceback"])

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_docker_container_runpy_timeout(self):
        with (
                mock.patch("docker.client.Client.create_container")) as mock_create_ctn, (  # noqa
                mock.patch("docker.client.Client.start")) as mock_ctn_start, (
                mock.patch("docker.client.Client.logs")) as mock_ctn_logs, (
                mock.patch("docker.client.Client.remove_container")) as mock_remove_ctn, (  # noqa
                mock.patch("docker.client.Client.inspect_container")) as mock_inpect_ctn, (  # noqa
                mock.patch("six.moves.http_client.HTTPConnection.request")) as mock_ctn_request, (  # noqa
                mock.patch("six.moves.http_client.HTTPConnection.getresponse")) as mock_ctn_get_response:  # noqa

            mock_create_ctn.return_value = {"Id": "someid"}
            mock_ctn_start.side_effect = lambda x: None
            mock_ctn_logs.side_effect = lambda x: None
            mock_remove_ctn.return_value = None
            fake_host_ip = "192.168.1.100"
            fake_host_port = "69999"

            mock_inpect_ctn.return_value = {
                "NetworkSettings": {
                    "Ports": {"%d/tcp" % RUNPY_PORT: (
                        {"HostIp": fake_host_ip, "HostPort": fake_host_port},
                    )}
                }}

            with self.subTest(
                    case="Docker ping passed by runpy timed out"):

                # first request is ping, second request raise socket.timeout
                mock_ctn_request.side_effect = [None, sock_timeout]
                mock_ctn_get_response.return_value = six.BytesIO(b"OK")

                res = request_python_run_with_retries(
                    run_req={}, run_timeout=0.1, retry_count=0)
                self.assertEqual(res["result"], "timeout")
                self.assertEqual(res["exec_host"], fake_host_ip)

    @skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_docker_container_runpy_retries_count(self):
        with (
                mock.patch("course.page.code.request_python_run")) as mock_req_run, (  # noqa
                mock.patch("course.page.code.is_nuisance_failure")) as mock_is_nuisance_failure:  # noqa
            expected_result = "this is my custom result"
            mock_req_run.return_value = {"result": expected_result}
            with self.subTest(actual_retry_count=4):
                mock_is_nuisance_failure.side_effect = [True, True, True, False]
                res = request_python_run_with_retries(
                    run_req={}, run_timeout=0.1, retry_count=5)
                self.assertEqual(res["result"], expected_result)
                self.assertEqual(mock_req_run.call_count, 4)
                self.assertEqual(mock_is_nuisance_failure.call_count, 4)

            mock_req_run.reset_mock()
            mock_is_nuisance_failure.reset_mock()
            with self.subTest(actual_retry_count=2):
                mock_is_nuisance_failure.side_effect = [True, True, True, False]
                res = request_python_run_with_retries(
                    run_req={}, run_timeout=0.1, retry_count=1)
                self.assertEqual(res["result"], expected_result)
                self.assertEqual(mock_req_run.call_count, 2)
                self.assertEqual(mock_is_nuisance_failure.call_count, 1)


class IsNuisanceFailureTest(unittest.TestCase):
    # Testing is_nuisance_failure

    def test_not_uncaught_error(self):
        result = {"result": "not_uncaught_error"}
        self.assertFalse(is_nuisance_failure(result))

    def test_no_traceback(self):
        result = {"result": "uncaught_error"}
        self.assertFalse(is_nuisance_failure(result))

    def test_traceback_unkown(self):
        result = {"result": "uncaught_error",
                  "traceback": "unknow traceback"}
        self.assertFalse(is_nuisance_failure(result))

    def test_traceback_has_badstatusline(self):
        result = {"result": "uncaught_error",
                  "traceback": "BadStatusLine: \nfoo"}
        self.assertTrue(is_nuisance_failure(result))

    def test_traceback_address_already_in_use(self):
        result = {"result": "uncaught_error",
                  "traceback": "\nbind: address already in use \nfoo"}
        self.assertTrue(is_nuisance_failure(result))

    def test_traceback_new_connection_error(self):
        result = {"result": "uncaught_error",
                  "traceback":
                      "\nrequests.packages.urllib3.exceptions."
                      "NewConnectionError: \nfoo"}
        self.assertTrue(is_nuisance_failure(result))

    def test_traceback_remote_disconnected(self):
        result = {"result": "uncaught_error",
                  "traceback":
                      "\nhttp.client.RemoteDisconnected: \nfoo"}
        self.assertTrue(is_nuisance_failure(result))


class CodeQuestionWithHumanTextFeedbackSpecialCase(
        SingleCoursePageTestMixin, SubprocessRunpyContainerMixin, TestCase):
    """
    https://github.com/inducer/relate/issues/269
    https://github.com/inducer/relate/commit/2af0ad7aa053b735620b2cf0bae0b45822bfb87f  # noqa
    """

    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(CodeQuestionWithHumanTextFeedbackSpecialCase, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)

    def setUp(self):  # noqa
        super(CodeQuestionWithHumanTextFeedbackSpecialCase, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.rf = RequestFactory()

    def get_grade_feedback(self, answer_data, page_value,
                           human_feedback_percentage, grade_data):
        page_id = "py_simple_list"
        course_identifier = self.course.identifier
        flow_session_id = self.get_default_flow_session_id(course_identifier)
        flow_session = FlowSession.objects.get(id=flow_session_id)

        page_ordinal = self.get_page_ordinal_via_page_id(
            page_id, course_identifier, flow_session_id)

        post_data = answer_data.copy()
        post_data.update({"submit": ""})

        request = self.rf.post(
            self.get_page_url_by_ordinal(
                page_ordinal, course_identifier, flow_session_id),
            post_data)
        request.user = self.student_participation.user

        pctx = CoursePageContext(request, course_identifier)
        fpctx = FlowPageContext(
            pctx.repo, pctx.course, self.flow_id, page_ordinal,
            self.student_participation, flow_session, request)
        page_desc = fpctx.page_desc
        page_desc.value = page_value
        page_desc.human_feedback_percentage = human_feedback_percentage

        page = PythonCodeQuestionWithHumanTextFeedback(None, None, page_desc)

        page_context = fpctx.page_context
        grade_data.setdefault('grade_percent', None)
        grade_data.setdefault('released', True)
        grade_data.setdefault('feedback_text', "")
        page_data = fpctx.page_data
        feedback = page.grade(
            page_context=page_context,
            answer_data=answer_data,
            page_data=page_data,
            grade_data=grade_data)

        return feedback

    def test_code_with_human_feedback(self):
        answer_data = {"answer": 'b = [a + 0] * 50'}
        grade_data = {"grade_percent": 100}
        page_value = 4
        human_feedback_percentage = 60
        feedback = self.get_grade_feedback(
            answer_data, page_value, human_feedback_percentage, grade_data)
        self.assertIn("The overall grade is 100%.", feedback.feedback)
        self.assertIn(
            "The autograder assigned 1.60/1.60 points.", feedback.feedback)
        self.assertIn(
            "The human grader assigned 2.40/2.40 points.", feedback.feedback)

    def test_code_with_human_feedback_full_percentage(self):
        answer_data = {"answer": 'b = [a + 0] * 50'}
        grade_data = {"grade_percent": 100}
        page_value = 0
        human_feedback_percentage = 100
        from course.page.base import AnswerFeedback
        with mock.patch(
                "course.page.code.PythonCodeQuestion.grade") as mock_py_grade:

            # In this way, code_feedback.correctness is None
            mock_py_grade.return_value = AnswerFeedback(correctness=None)
            feedback = self.get_grade_feedback(
                answer_data, page_value, human_feedback_percentage, grade_data)
            self.assertIn("The overall grade is 100%.", feedback.feedback)
            self.assertIn(
                "No information on correctness of answer.", feedback.feedback)
            self.assertIn(
                "The human grader assigned 0/0 points.", feedback.feedback)

    def test_code_with_human_feedback_zero_percentage(self):
        answer_data = {"answer": 'b = [a + 0] * 50'}
        grade_data = {}
        page_value = 0
        human_feedback_percentage = 0
        feedback = self.get_grade_feedback(
            answer_data, page_value, human_feedback_percentage, grade_data)
        self.assertIn("The overall grade is 100%.", feedback.feedback)
        self.assertIn(
            "Your answer is correct.", feedback.feedback)
        self.assertIn(
            "The autograder assigned 0/0 points.", feedback.feedback)

# vim: fdm=marker
