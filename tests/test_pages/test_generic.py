# -*- coding: utf-8 -*-

from __future__ import division

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner, Zesheng Wang, Dong Zhuang"

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
from base64 import b64encode

import unittest
import pytest
from django.test import TestCase
from django.urls import resolve

from course.models import FlowSession
from course.constants import MAX_EXTRA_CREDIT_FACTOR
from course.page.base import (
    AnswerFeedback, get_auto_feedback,
    validate_point_count, InvalidFeedbackPointsError)

from tests.constants import (
    MESSAGE_ANSWER_SAVED_TEXT,
    MESSAGE_ANSWER_FAILED_SAVE_TEXT, TEST_TEXT_FILE_PATH, TEST_PDF_FILE_PATH,
    TEST_HGTEXT_MARKDOWN_ANSWER_WRONG, TEST_HGTEXT_MARKDOWN_ANSWER_TYPE_WRONG)

from tests.base_test_mixins import (
    SingleCourseQuizPageTestMixin, MockAddMessageMixing)
from tests.utils import mock
from tests import factories


@pytest.mark.expensive
class SingleCourseQuizPageTest(SingleCourseQuizPageTestMixin,
                               MockAddMessageMixing, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageTest, cls).setUpTestData()

        # cls.default_flow_params will only be available after a flow is started
        cls.start_flow(cls.flow_id)

    # view all pages
    def test_view_all_flow_pages_ordinal_out_of_range(self):
        page_count = FlowSession.objects.get(
            id=self.default_flow_params["flow_session_id"]).page_count

        # test PageOrdinalOutOfRange
        resp = self.c.get(
            self.get_page_url_by_ordinal(page_ordinal=page_count + 1))
        self.assertEqual(resp.status_code, 302)
        _, _, params = resolve(resp.url)
        #  ensure redirected to last page
        self.assertEqual(int(params["page_ordinal"]), page_count - 1)

    # {{{ auto graded questions
    @unittest.skipIf(six.PY2, "PY2 doesn't support subTest")
    def test_quiz_no_answer(self):
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

        with self.temporarily_switch_to_user(self.instructor_participation.user):
            page_count = FlowSession.objects.first().page_count
            for i in range(page_count):
                page_id, group_id = (
                    self.get_page_id_via_page_oridnal(i, with_group_id=True))
                with self.subTest(page_id=page_id, name="no answer page view"):
                    resp = self.c.get(self.get_page_url_by_page_id(page_id=page_id))
                    self.assertEqual(resp.status_code, 200)
                    if page_id not in ["age_group", "fear", "welcome"]:
                        self.assertContains(resp, "No answer provided.")

                with self.subTest(page_id=page_id, name="no answer page analytics"):
                    # ensure analytics page work, when no answer_data
                    # todo: make more assertions in terms of content
                    resp = self.get_flow_page_analytics(
                        flow_id=self.flow_id, group_id=group_id,
                        page_id=page_id, force_login_instructor=False)
                    self.assertEqual(resp.status_code, 200)

                with self.subTest(page_id=page_id,
                                  name="no answer download submission"):
                    group_page_id = "%s/%s" % (group_id, page_id)

                    # ensure download submissions work when no answer_data
                    resp = self.post_download_all_submissions_by_group_page_id(
                        group_page_id=group_page_id, flow_id=self.flow_id)
                    self.assertEqual(resp.status_code, 200)
                    prefix, zip_file = resp["Content-Disposition"].split('=')
                    self.assertEqual(prefix, "attachment; filename")
                    self.assertEqual(resp.get('Content-Type'), "application/zip")

    def test_quiz_text(self):
        page_id = "half"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id)
        )
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_quiz_choice(self):
        page_id = "krylov"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id)
        )
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_quiz_choice_failed_no_answer(self):
        page_id = "krylov"
        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal, expected_count=0)

        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"choice": []}, do_grading=False)
        )

        self.assertAddMessageCalledWith(MESSAGE_ANSWER_FAILED_SAVE_TEXT)

        # There should be no submission history
        # https://github.com/inducer/relate/issues/351
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)
        self.end_flow()
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_exact_correct(self):
        page_id = "ice_cream_toppings"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id)
        )
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal, expected_count=1)

    def test_quiz_multi_choice_exact_wrong(self):
        page_id = "ice_cream_toppings"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"choice": ['0', '1']}, do_grading=False)
        )
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal, expected_count=1)

        # This page doesn't have permission to change_answer
        # try to change answer to a correct one
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, do_grading=False))
        self.assertAddMessageCalledWith(["Already have final answer.",
                                         "Failed to submit answer."])

        self.assertSubmitHistoryItemsCount(page_ordinal, expected_count=1)

        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_proportion_rule_partial(self):
        page_id = "matrix_props"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"choice": ['0']}, expected_grade=0.8)
        )
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_quiz_multi_choice_proportion_rule_correct(self):
        page_id = "matrix_props"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_quiz_inline_wrong_answer(self):
        page_id = "inlinemulti"
        answer_data = {
            'blank1': 'Bar', 'blank_2': '0.2', 'blank3': '1',
            'blank4': '5', 'blank5': 'Bar', 'choice_a': '0'}
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data=answer_data, expected_grade=8.57))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        # 6 correct answer
        self.assertContains(submit_answer_response, 'correctness="1"', count=6)
        # 1 incorrect answer
        self.assertContains(submit_answer_response, 'correctness="0"', count=1)

    def test_quiz_inline_correct_answer(self):
        page_id = "inlinemulti"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)
        # 7 answer
        self.assertContains(submit_answer_response, 'correctness="1"', count=7)

    # }}}

    # {{{ survey questions

    def test_quiz_survey_text(self):
        page_id = "fear"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_quiz_survey_choice(self):
        page_id = "age_group"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    # }}}

    def test_human_graded_text(self):
        page_id = "hgtext"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_human_graded_text_failed(self):
        page_id = "hgtext"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"answer": TEST_HGTEXT_MARKDOWN_ANSWER_WRONG},
                do_grading=False))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_FAILED_SAVE_TEXT)
        self.assertFormErrorLoose(
            submit_answer_response,
            "ValidationError: submitted page: "
            "one or more correct answer(s) expected, 0 found"
        )
        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)

        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id,
                answer_data={"answer": TEST_HGTEXT_MARKDOWN_ANSWER_TYPE_WRONG},
                do_grading=False))
        self.assertFormErrorLoose(
            submit_answer_response,
            "ValidationError: page must be of type 'ChoiceQuestion'"
        )
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_FAILED_SAVE_TEXT)

        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)

    # {{{ fileupload questions

    def test_fileupload_any(self):
        page_id = "anyup"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, do_grading=False))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        with open(TEST_TEXT_FILE_PATH, 'rb') as fp:
            expected_result1 = b64encode(fp.read()).decode()

        # change answer
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"uploaded_file": TEST_PDF_FILE_PATH},
                expected_grade=5))

        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        with open(TEST_PDF_FILE_PATH, 'rb') as fp:
            expected_result2 = b64encode(fp.read()).decode()

        page_ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=2)

        answer_visits_qset = (
            self.get_page_visits(page_id=page_id, answer_visit=True))
        self.assertEqual(answer_visits_qset.count(), 2)
        self.assertEqual(
            answer_visits_qset[1].answer["base64_data"], expected_result2)
        self.assertEqual(
            answer_visits_qset[0].answer["base64_data"], expected_result1)

    def test_fileupload_pdf_wrong_mime_type(self):
        page_id = "proof"

        # wrong MIME type, a text file
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"uploaded_file": TEST_TEXT_FILE_PATH},
                do_grading=False))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_FAILED_SAVE_TEXT)

        # https://github.com/inducer/relate/issues/351
        self.assertEqual(submit_answer_response.status_code, 200)

        ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        self.end_flow()
        self.assertSessionScoreEqual(0)

    def test_fileupload_pdf(self):
        page_id = "proof"

        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        with open(TEST_PDF_FILE_PATH, 'rb') as fp:
            expected_result = b64encode(fp.read()).decode()

        last_answer_visit = self.get_last_answer_visit()
        self.assertEqual(last_answer_visit.answer["base64_data"], expected_result)

    # }}}

    # {{{ optional page

    def test_optional_page_with_correct_answer(self):
        page_id = "quarter"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(page_id))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

    def test_optional_page_with_wrong_answer(self):
        page_id = "quarter"
        submit_answer_response, post_grade_response = (
            self.default_submit_page_answer_by_page_id_and_test(
                page_id, answer_data={"answer": ['0.15']}, expected_grade=0))
        self.assertAddMessageCalledWith(MESSAGE_ANSWER_SAVED_TEXT)

        # Make sure the page is rendered with 0 max_points
        self.assertResponseContextEqual(submit_answer_response, "max_points", 0)

        # The answer is wrong, there should also be zero score.
        self.assertSessionScoreEqual(0)

    # }}}

    # {{{ tests on submission history dropdown
    def test_submit_history_failure_not_ajax(self):
        self.post_answer_by_ordinal(1, {"answer": ['0.5']})
        resp = self.c.get(
            self.get_page_submit_history_url_by_ordinal(page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_get(self):
        self.post_answer_by_ordinal(1, {"answer": ['0.5']})
        resp = self.c.post(
            self.get_page_submit_history_url_by_ordinal(page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_authenticated(self):
        self.post_answer_by_ordinal(1, {"answer": ['0.5']})

        # anonymous user has not pperm to view submit history
        with self.temporarily_switch_to_user(None):
            resp = self.c.post(
                self.get_page_submit_history_url_by_ordinal(page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_no_perm(self):
        # student have no pperm to view ta's submit history
        ta_flow_session = factories.FlowSessionFactory(
            participation=self.ta_participation)
        resp = self.get_page_submit_history_by_ordinal(
            page_ordinal=1, flow_session_id=ta_flow_session.id)
        self.assertEqual(resp.status_code, 403)

    # }}}


class ValidatePointCountTest(unittest.TestCase):
    """
    test course.page.base.validate_point_count
    """

    def test_none(self):
        self.assertIsNone(validate_point_count(None))

    def test_negative_error(self):
        with self.assertRaises(InvalidFeedbackPointsError):
            validate_point_count(-0.0001)

    def test_above_max_extra_credit_factor_error(self):
        with self.assertRaises(InvalidFeedbackPointsError):
            validate_point_count(MAX_EXTRA_CREDIT_FACTOR + 0.0001)

    def test_close_0_negative(self):
        self.assertEqual(validate_point_count(-0.000009), 0)

    def test_close_0_positive(self):
        self.assertEqual(validate_point_count(0.000009), 0)

    def test_above_close_max_extra_credit_factor(self):
        self.assertEqual(validate_point_count(
            MAX_EXTRA_CREDIT_FACTOR + 0.000009), MAX_EXTRA_CREDIT_FACTOR)

    def test_below_close_max_extra_credit_factor(self):
        self.assertEqual(validate_point_count(
            MAX_EXTRA_CREDIT_FACTOR - 0.000009), MAX_EXTRA_CREDIT_FACTOR)

    def test_int(self):
        self.assertEqual(validate_point_count(5), 5)

    def test_gt_close_int(self):
        self.assertEqual(validate_point_count(5.000009), 5)

    def test_lt_close_int(self):
        self.assertEqual(validate_point_count(4.9999999), 5)

    def test_quarter(self):
        self.assertEqual(validate_point_count(1.25), 1.25)

    def test_gt_quarter(self):
        self.assertEqual(validate_point_count(0.2500009), 0.25)

    def test_lt_quarter(self):
        self.assertEqual(validate_point_count(9.7499999), 9.75)

    def test_half(self):
        self.assertEqual(validate_point_count(1.5), 1.5)

    def test_gt_half(self):
        self.assertEqual(validate_point_count(3.500001), 3.5)

    def test_lt_half(self):
        self.assertEqual(validate_point_count(0.4999999), 0.5)


class AnswerFeedBackTest(unittest.TestCase):
    """
    test course.page.base.AnswerFeedBack
    """

    # TODO: more tests
    def test_correctness_negative(self):
        correctness = -0.1
        with self.assertRaises(InvalidFeedbackPointsError):
            AnswerFeedback(correctness)

    def test_correctness_exceed_max_extra_credit_factor(self):
        correctness = MAX_EXTRA_CREDIT_FACTOR + 0.1
        with self.assertRaises(InvalidFeedbackPointsError):
            AnswerFeedback(correctness)

    def test_correctness_can_be_none(self):
        af = AnswerFeedback(None)
        self.assertIsNone(af.correctness)

    def test_from_json(self):
        json = {
            "correctness": 0.5,
            "feedback": "what ever"
        }
        af = AnswerFeedback.from_json(json, None)
        self.assertEqual(af.correctness, 0.5)
        self.assertEqual(af.feedback, "what ever")
        self.assertEqual(af.bulk_feedback, None)

    def test_from_json_none(self):
        af = AnswerFeedback.from_json(None, None)
        self.assertIsNone(af)

    def test_validate_point_count_called(self):
        import random
        with mock.patch("course.page.base.validate_point_count") \
                as mock_validate_point_count, \
                mock.patch("course.page.base.get_auto_feedback") \
                        as mock_get_auto_feedback:
            mock_validate_point_count.side_effect = lambda x: x

            mock_get_auto_feedback.side_effect = lambda x: x
            for i in range(10):
                correctness = random.uniform(0, 15)
                feedback = "some feedback"
                AnswerFeedback(correctness, feedback)
                mock_validate_point_count.assert_called_once_with(correctness)

                # because feedback is not None
                self.assertEqual(mock_get_auto_feedback.call_count, 0)
                mock_validate_point_count.reset_mock()

            for i in range(10):
                correctness = random.uniform(0, 15)
                AnswerFeedback(correctness)

                # because get_auto_feedback is mocked, the call_count of
                # mock_validate_point_count is only once
                mock_validate_point_count.assert_called_once_with(correctness)
                mock_validate_point_count.reset_mock()

                # because feedback is None
                self.assertEqual(mock_get_auto_feedback.call_count, 1)
                mock_get_auto_feedback.reset_mock()

            AnswerFeedback(correctness=None)
            mock_validate_point_count.assert_called_once_with(None)


class GetAutoFeedbackTest(unittest.TestCase):
    """
    test course.page.base.get_auto_feedback
    """

    def test_none(self):
        self.assertIn("No information", get_auto_feedback(None))

    def test_not_correct(self):
        self.assertIn("not correct", get_auto_feedback(0.000001))
        self.assertIn("not correct", get_auto_feedback(-0.000001))

    def test_correct(self):
        result = get_auto_feedback(0.999999)
        self.assertIn("is correct", result)
        self.assertNotIn("bonus", result)

        result = get_auto_feedback(1)
        self.assertIn("is correct", result)
        self.assertNotIn("bonus", result)

        result = get_auto_feedback(1.000001)
        self.assertIn("is correct", result)
        self.assertNotIn("bonus", result)

    def test_correct_with_bonus(self):
        result = get_auto_feedback(1.01)
        self.assertIn("is correct", result)
        self.assertIn("bonus", result)

        result = get_auto_feedback(2)
        self.assertIn("is correct", result)
        self.assertIn("bonus", result)

        result = get_auto_feedback(9.99999)
        self.assertIn("is correct", result)
        self.assertIn("bonus", result)

    def test_with_mostly_correct(self):
        self.assertIn("mostly correct", get_auto_feedback(0.51))
        self.assertIn("mostly correct", get_auto_feedback(0.999))

    def test_with_somewhat_correct(self):
        self.assertIn("somewhat correct", get_auto_feedback(0.5))
        self.assertIn("somewhat correct", get_auto_feedback(0.5000001))
        self.assertIn("somewhat correct", get_auto_feedback(0.001))
        self.assertIn("somewhat correct", get_auto_feedback(0.2))

    def test_correctness_negative(self):
        correctness = -0.1
        with self.assertRaises(InvalidFeedbackPointsError):
            get_auto_feedback(correctness)

    def test_correctness_exceed_max_extra_credit_factor(self):
        correctness = MAX_EXTRA_CREDIT_FACTOR + 0.1
        with self.assertRaises(InvalidFeedbackPointsError):
            get_auto_feedback(correctness)

    def test_validate_point_count_called(self):
        import random
        with mock.patch("course.page.base.validate_point_count") \
                as mock_validate_point_count:
            mock_validate_point_count.side_effect = lambda x: x
            for i in range(10):
                correctness = random.uniform(0, 15)
                get_auto_feedback(correctness)
                mock_validate_point_count.assert_called_once_with(correctness)
                mock_validate_point_count.reset_mock()

            get_auto_feedback(correctness=None)
            mock_validate_point_count.assert_called_once_with(None)

# vim: fdm=marker
