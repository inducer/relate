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

from unittest import skipIf

from django.test import TestCase, override_settings

from tests.base_test_mixins import (
    SubprocessRunpyContainerMixin,
    SingleCoursePageTestMixin)
from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin, PAGE_ERRORS
)

from tests.test_pages import QUIZ_FLOW_ID
from tests.test_pages.utils import (
    skip_real_docker_test, SKIP_REAL_DOCKER_REASON,
    REAL_RELATE_DOCKER_URL, REAL_RELATE_DOCKER_RUNPY_IMAGE,
    REAL_RELATE_DOCKER_TLS_CONFIG
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


class RealDockerTestMixin(object):
    @classmethod
    def setUpClass(cls):  # noqa
        from unittest import SkipTest
        if skip_real_docker_test:
            raise SkipTest(SKIP_REAL_DOCKER_REASON)

        super(RealDockerTestMixin, cls).setUpClass()
        cls.override_docker_settings = override_settings(
            RELATE_DOCKER_URL=REAL_RELATE_DOCKER_URL,
            RELATE_DOCKER_RUNPY_IMAGE=REAL_RELATE_DOCKER_RUNPY_IMAGE,
            RELATE_DOCKER_TLS_CONFIG=REAL_RELATE_DOCKER_TLS_CONFIG
        )
        cls.override_docker_settings.enable()
        cls.make_sure_docker_image_pulled()

    @classmethod
    def tearDownClass(cls):  # noqa
        super(RealDockerTestMixin, cls).tearDownClass()
        cls.override_docker_settings.disable()

    @classmethod
    def make_sure_docker_image_pulled(cls):
        import docker
        cli = docker.Client(
            base_url=REAL_RELATE_DOCKER_URL,
            tls=None,
            timeout=15,
            version="1.19")

        if not bool(cli.images(REAL_RELATE_DOCKER_RUNPY_IMAGE)):
            # This should run only once and get cached on Travis-CI
            cli.pull(REAL_RELATE_DOCKER_RUNPY_IMAGE)


@skipIf(skip_real_docker_test, SKIP_REAL_DOCKER_REASON)
class RealDockerCodePageTest(SingleCoursePageTestMixin,
                             RealDockerTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID
    page_id = "addition"

    def setUp(self):  # noqa
        super(RealDockerCodePageTest, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.start_flow(self.flow_id)

    def test_code_page_correct_answer(self):
        answer_data = {"answer": "c = a + b"}
        expected_str = (
            "It looks like you submitted code that is identical to "
            "the reference solution. This is not allowed.")
        resp = self.post_answer_by_page_id(self.page_id, answer_data)
        self.assertContains(resp, expected_str, count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_code_page_wrong_answer(self):
        answer_data = {"answer": "c = a - b"}
        resp = self.post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_code_page_user_code_exception_raise(self):
        answer_data = {"answer": "c = a ^ b"}
        from django.utils.html import escape
        expected_error_str1 = escape(
            "Your code failed with an exception. "
            "A traceback is below.")
        expected_error_str2 = escape(
            "TypeError: unsupported operand type(s) for ^: "
            "'float' and 'float'")
        resp = self.post_answer_by_page_id(self.page_id, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, expected_error_str1, count=1)
        self.assertContains(resp, expected_error_str2, count=1)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)


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
        self.assertSandboxNotHaveValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS, "data file '%s' not found" % file_name)

    def test_not_multiple_submit_warning(self):
        markdown = (
                markdowns.CODE_MARKDWON_PATTERN_WITH_DATAFILES
                % {"extra_data_file": ""}
        )
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp,
            NOT_ALLOW_MULTIPLE_SUBMISSION_WARNING
        )

    def test_explicity_not_allow_multiple_submit(self):
        markdown = (
                markdowns.CODE_MARKDWON_PATTERN_EXPLICITLY_NOT_ALLOW_MULTI_SUBMIT
                % {"extra_data_file": ""}
        )
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

    def test_question_without_test_code(self):
        markdown = markdowns.CODE_MARKDWON_PATTERN_WITHOUT_TEST_CODE
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)
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
        self.assertSandboxHaveValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)

        resp = self.get_page_sandbox_submit_answer_response(
            markdown,
            answer_data={"answer": ['c = b + a\r']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

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
                    answer_data={"answer": ['c = b + a\r']})
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
                        answer_data={"answer": ['c = b + a\r']})
                    self.assertContains(resp, expected_error_str)
                    self.assertEqual(resp.status_code, 200)
                    self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp,
                                                                              None)
                    self.assertEqual(len(mail.outbox), 0)

    def assert_runpy_result_and_response(self, result_type, expected_msg,
                                         correctness=0, mail_count=0,
                                         **extra_result):
        with mock.patch(RUNPY_WITH_RETRIES_PATH, autospec=True) as mock_runpy:
            result = {"result": result_type}
            result.update(extra_result)
            mock_runpy.return_value = result

            resp = self.get_page_sandbox_submit_answer_response(
                markdowns.CODE_MARKDWON,
                answer_data={"answer": ['c = b + a\r']})
            self.assertResponseContextAnswerFeedbackContainsFeedback(resp,
                                                                     expected_msg)
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

    def test_html_bleached_in_feedback(self):
        self.assert_runpy_result_and_response(
            "user_error",
            "",
            html="<p>some html</p>"
        )

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


# vim: fdm=marker
