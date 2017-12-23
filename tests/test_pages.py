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
from django.test import TestCase
from django.urls import reverse, resolve
from django.core import mail
from django.contrib.auth import get_user_model
from course.models import Course, FlowSession
from .base_test_mixins import (
    SingleCoursePageTestMixin, FallBackStorageMessageTestMixin,
    SubprocessRunpyContainerMixin)
from .utils import LocmemBackendTestsMixin

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

    # TODO: This should be moved to tests for auth module
    def test_user_creation(self):
        # Should have 4 users
        self.assertEqual(get_user_model().objects.all().count(), 4)
        self.c.logout()

        self.assertTrue(
            self.c.login(
                username=self.instructor_participation.user.username,
                password=(
                    self.courses_setup_list[0]
                    ["participations"][0]
                    ["user"]["password"])))

    # TODO: This should move to tests for course.view module
    def test_course_creation(self):
        # Should only have one course
        self.assertEqual(Course.objects.all().count(), 1)
        resp = self.c.get(reverse("relate-course_page",
                                  args=[self.course.identifier]))
        # 200 != 302 is better than False is not True
        self.assertEqual(resp.status_code, 200)

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

    def test_fileupload_any(self):
        page_id = "anyup"
        ordinal = self.get_page_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
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
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            fp.seek(0)
            expected_result1 = b64encode(fp.read()).decode()
            self.assertEqual(resp.status_code, 200)

        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=1)

        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.pdf'), 'rb') as fp:
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
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)

        self.assertResponseMessagesContains(resp, [MESSAGE_ANSWER_FAILED_SAVE_TEXT])

        # There should be no submission history
        self.assertSubmitHistoryItemsCount(page_ordinal=ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.pdf'), 'rb') as fp:
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


class SingleCourseQuizPageTestExtra(SingleCoursePageTestMixin,
                               FallBackStorageMessageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageTestExtra, cls).setUpTestData()
        # this time we create a session submitted by ta
        cls.c.force_login(cls.ta_participation.user)
        cls.start_flow(cls.flow_id)

    def setUp(self):  # noqa
        super(SingleCourseQuizPageTestExtra, self).setUp()
        # This is needed to ensure student is logged in
        self.c.force_login(self.student_participation.user)

    def test_grade_history_failure_no_perm(self):
        self.end_flow()

        # no pperm to view other's grade_history
        resp = self.c.post(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_no_perm(self):
        # student have no pperm to view ta's submit history
        resp = self.c.post(
            self.get_page_submit_history_url_by_ordinal(page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    # }}}


class SingleCourseQuizPageGradeInterfaceTest(LocmemBackendTestsMixin,
                                SingleCoursePageTestMixin,
                                FallBackStorageMessageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTest, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)
        cls.this_flow_session_id = cls.default_flow_params["flow_session_id"]
        cls.any_up_page_id = "anyup"
        cls.submit_any_upload_question()

    def setUp(self):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTest, self).setUp()
        # This is needed to ensure student is logged in
        self.c.force_login(self.student_participation.user)

    def submit_any_upload_question_null_failure(self):
        self.post_answer_by_page_id(
            "anyup", {"uploaded_file": []})

    @classmethod
    def submit_any_upload_question(cls):
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            answer_data = {"uploaded_file": fp}
            cls.post_answer_by_page_id_class(
                cls.any_up_page_id, answer_data, **cls.default_flow_params)

    def test_post_grades(self):
        self.end_flow()
        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(5)

        grade_data = {
            "grade_points": ["4"],
            "released": []
        }
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(None)

        grade_data = {
            "grade_points": ["4"],
            "released": ["on"]
        }
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(4)

    def test_post_grades_history(self):
        # failure
        self.post_answer_by_page_id("anyup", {"uploaded_file": []})

        # 2nd success
        self.submit_any_upload_question()
        self.end_flow()

        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(5)

        ordinal = self.get_page_ordinal_via_page_id(self.any_up_page_id)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=3)

        grade_data = {
            "grade_points": ["4"],
            "released": []
        }
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(None)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=4)

        grade_data = {
            "grade_points": ["4"],
            "released": ["on"]
        }
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(4)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal,
                                          expected_count=5)

    def test_post_grades_success(self):
        self.end_flow()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on']
        }

        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(5)

    def test_post_grades_forbidden(self):
        self.end_flow()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on']
        }

        # with self.student_participation.user logged in
        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data,
                                          force_login_instructor=False)
        self.assertTrue(resp.status_code, 403)

        self.assertSessionScoreEqual(None)

    def test_feedback_and_notify(self):
        self.end_flow()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on'],
            "feedback_text": ['test feedback']
        }

        self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertEqual(len(mail.outbox), 0)

        grade_data["notify"] = ["on"]
        self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [])

    def test_feedback_email_may_reply(self):
        self.end_flow()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on'],
            "feedback_text": ['test feedback'],
            "notify": ["on"],
            "may_reply": ["on"]
        }

        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.post_grade_by_page_id(self.any_up_page_id, grade_data,
                                       force_login_instructor=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [self.ta_participation.user.email])

    def test_notes_and_notify(self):
        self.end_flow()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on'],
            "notes": ['test notes']
        }

        self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertEqual(len(mail.outbox), 0)

        grade_data["notify_instructor"] = ["on"]
        self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertEqual(len(mail.outbox), 1)

    # {{{ tests on grading history dropdown
    def test_grade_history_failure_not_ajax(self):
        self.end_flow()

        resp = self.c.get(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_get(self):
        self.end_flow()

        resp = self.c.post(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_grade_history_failure_not_authenticated(self):
        self.end_flow()

        with self.temporarily_switch_to_user(None):
            resp = self.c.post(
                self.get_page_grade_history_url_by_ordinal(
                    page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    # }}}


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
                resp, "The autograder assigned 0/1 points.")

        self.assertEqual(self.end_flow().status_code, 200)

        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }
        resp = self.post_grade_by_page_id(page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, "The human grader assigned 2/2 points.")
        self.assertSessionScoreEqual(2)

# vim: fdm=marker
