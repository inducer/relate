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

import os
from base64 import b64encode

import unittest
from django.test import TestCase
from django.urls import resolve
from django.core import mail

from course.models import FlowSession
from course.constants import MAX_EXTRA_CREDIT_FACTOR
from course.page.base import (
    AnswerFeedback, get_auto_feedback,
    validate_point_count, InvalidFeedbackPointsError)

from tests.base_test_mixins import (
    SingleCoursePageTestMixin, FallBackStorageMessageTestMixin)
from tests.utils import LocmemBackendTestsMixin, mock

QUIZ_FLOW_ID = "quiz-test"

MESSAGE_ANSWER_SAVED_TEXT = "Answer saved."
MESSAGE_ANSWER_FAILED_SAVE_TEXT = "Failed to submit answer."


class SingleCourseQuizPageTest(SingleCoursePageTestMixin,
                               FallBackStorageMessageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageTest, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)

        # cls.default_flow_params will only be available after a flow is started
        cls.start_flow(cls.flow_id)

    def setUp(self):  # noqa
        super(SingleCourseQuizPageTest, self).setUp()
        # This is needed to ensure student is logged in
        self.c.force_login(self.student_participation.user)

    # view all pages
    def test_view_all_flow_pages(self):
        page_count = FlowSession.objects.get(
            id=self.default_flow_params["flow_session_id"]).page_count
        for i in range(page_count):
            resp = self.c.get(
                self.get_page_url_by_ordinal(page_ordinal=i))
            self.assertEqual(resp.status_code, 200)

        # test PageOrdinalOutOfRange
        resp = self.c.get(
            self.get_page_url_by_ordinal(page_ordinal=page_count+1))
        self.assertEqual(resp.status_code, 302)
        _, _, params = resolve(resp.url)
        #  ensure redirected to last page
        self.assertEqual(int(params["page_ordinal"]), page_count-1)

    # {{{ auto graded questions
    def test_quiz_no_answer(self):
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_text(self):
        resp = self.post_answer_by_ordinal(1, {"answer": ['0.5']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)

        # Make sure the page is rendered with max_points
        self.assertResponseContextEqual(resp, "max_points", 5)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(5)

    def test_quiz_choice(self):
        resp = self.post_answer_by_ordinal(2, {"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(2)

    def test_quiz_choice_failed_no_answer(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=2, expected_count=0)
        resp = self.post_answer_by_ordinal(2, {"choice": []})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_FAILED_SAVE_TEXT)

        # There should be no submission history
        # https://github.com/inducer/relate/issues/351
        self.assertSubmitHistoryItemsCount(page_ordinal=2, expected_count=0)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_exact_correct(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=0)
        resp = self.post_answer_by_ordinal(3, {"choice": ['0', '1', '4']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_quiz_multi_choice_exact_wrong(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=0)
        resp = self.post_answer_by_ordinal(3, {"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_failed_change_answer(self):
        # Note: this page doesn't have permission to change_answer
        # submit a wrong answer
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=0)
        resp = self.post_answer_by_ordinal(3, {"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)

        # try to change answer to a correct one
        resp = self.post_answer_by_ordinal(3, {"choice": ['0', '1', '4']})
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(
                    resp, ["Already have final answer.",
                           "Failed to submit answer."])
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_proportion_partial(self):
        resp = self.post_answer_by_ordinal(4, {"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(0.8)

    def test_quiz_multi_choice_proportion_correct(self):
        resp = self.post_answer_by_ordinal(4, {"choice": ['0', '3']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_quiz_inline(self):
        answer_data = {
            'blank1': ['Bar'], 'blank_2': ['0.2'], 'blank3': ['1'],
            'blank4': ['5'], 'blank5': ['Bar'], 'choice2': ['0'],
            'choice_a': ['0']}
        resp = self.post_answer_by_ordinal(5, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(10)

    # }}}

    # {{{ survey questions

    def test_quiz_survey_text(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=6, expected_count=0)
        resp = self.post_answer_by_ordinal(
                            6, {"answer": ["NOTHING!!!"]})
        self.assertSubmitHistoryItemsCount(page_ordinal=6, expected_count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_flow().status_code, 200)

        # Survey question won't be counted into final score
        self.assertSessionScoreEqual(0)
        last_answer_visit = self.get_last_answer_visit()
        self.assertEqual(last_answer_visit.answer["answer"], "NOTHING!!!")

    def test_quiz_survey_choice(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=7, expected_count=0)

        # no answer thus no history
        self.post_answer_by_ordinal(7, {"choice": []})
        self.assertSubmitHistoryItemsCount(page_ordinal=7, expected_count=0)

        resp = self.post_answer_by_ordinal(7, {"choice": ['8']})
        self.assertSubmitHistoryItemsCount(page_ordinal=7, expected_count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_flow().status_code, 200)

        # Survey question won't be counted into final score
        self.assertSessionScoreEqual(0)

        last_answer_visit = self.get_last_answer_visit()
        self.assertEqual(last_answer_visit.answer["choice"], 8)

    # }}}

    # {{{ fileupload questions

    def test_fileupload_any(self):
        page_id = "anyup"
        ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            fp.seek(0)
            expected_result = b64encode(fp.read()).decode()
            self.assertEqual(resp.status_code, 200)

        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=1)
        last_answer_visit = self.get_last_answer_visit()
        self.assertEqual(last_answer_visit.answer["base64_data"], expected_result)
        self.assertSessionScoreEqual(None)

    def test_fileupload_any_change_answer(self):
        page_id = "anyup"
        ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            fp.seek(0)
            expected_result1 = b64encode(fp.read()).decode()
            self.assertEqual(resp.status_code, 200)

        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=1)

        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'test_file.pdf'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)
            fp.seek(0)
            expected_result2 = b64encode(fp.read()).decode()

        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=2)

        answer_visits_qset = (
            self.get_page_visits(page_id=page_id, answer_visit=True))
        self.assertEqual(answer_visits_qset.count(), 2)
        self.assertEqual(
            answer_visits_qset[1].answer["base64_data"], expected_result2)
        self.assertEqual(
            answer_visits_qset[0].answer["base64_data"], expected_result1)
        self.assertSessionScoreEqual(None)

    def test_fileupload_pdf(self):
        page_id = "proof"
        ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        # wrong MIME type
        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)

        self.assertResponseMessagesContains(resp, [MESSAGE_ANSWER_FAILED_SAVE_TEXT])

        # There should be no submission history
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             '../fixtures', 'test_file.pdf'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)
            fp.seek(0)
            expected_result = b64encode(fp.read()).decode()

        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=1)
        last_answer_visit = self.get_last_answer_visit()
        self.assertEqual(last_answer_visit.answer["base64_data"], expected_result)
        self.assertSessionScoreEqual(None)

    # }}}

    # {{{ optional page

    def test_optional_page_with_correct_answer(self):
        page_id = "quarter"
        resp = self.post_answer_by_page_id(page_id, {"answer": ['0.25']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)

        # Make sure the page is rendered with 0 max_points
        self.assertResponseContextEqual(resp, "max_points", 0)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)

        # Even the answer is correct, there should be zero score.
        self.assertSessionScoreEqual(0)

    def test_optional_page_with_wrong_answer(self):
        page_id = "quarter"
        resp = self.post_answer_by_page_id(page_id, {"answer": ['0.15']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)

        # Make sure the page is rendered with 0 max_points
        self.assertResponseContextEqual(resp, "max_points", 0)
        self.assertEqual(self.end_flow().status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)

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
        with mock.patch("course.page.base.validate_point_count")\
                as mock_validate_point_count,\
                mock.patch("course.page.base.get_auto_feedback")\
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
