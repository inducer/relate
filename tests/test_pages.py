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
from django.urls import reverse
from django.core import mail
from django.contrib.auth import get_user_model
from course.models import FlowPageVisit, Course, FlowSession
from .base_test_mixins import (
    SingleCoursePageTestMixin, FallBackStorageMessageTestMixin)
from .utils import LocmemBackendTestsMixin

QUIZ_FLOW_ID = "quiz-test"

MESSAGE_ANSWER_SAVED_TEXT = "Answer saved."
MESSAGE_ANSWER_FAILED_SAVE_TEXT = "Failed to submit answer."


class SingleCourseQuizPageTest(SingleCoursePageTestMixin,
                               FallBackStorageMessageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

    def setUp(self):  # noqa
        super(SingleCourseQuizPageTest, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.start_quiz(self.flow_id)

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

    # {{{ auto graded questions
    def test_quiz_no_answer(self):
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_text(self):
        resp = self.client_post_answer_by_ordinal(1, {"answer": ['0.5']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(5)

    def test_quiz_choice(self):
        resp = self.client_post_answer_by_ordinal(2, {"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(2)

    def test_quiz_choice_failed_no_answer(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=2, expected_count=0)
        resp = self.client_post_answer_by_ordinal(2, {"choice": []})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_FAILED_SAVE_TEXT)

        # There should be no submission history
        # https://github.com/inducer/relate/issues/351
        self.assertSubmitHistoryItemsCount(page_ordinal=2, expected_count=0)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_exact_correct(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=0)
        resp = self.client_post_answer_by_ordinal(3, {"choice": ['0', '1', '4']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_quiz_multi_choice_exact_wrong(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=0)
        resp = self.client_post_answer_by_ordinal(3, {"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_failed_change_answer(self):
        # Note: this page doesn't have permission to change_answer
        # submit a wrong answer
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=0)
        resp = self.client_post_answer_by_ordinal(3, {"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)

        # try to change answer to a correct one
        resp = self.client_post_answer_by_ordinal(3, {"choice": ['0', '1', '4']})
        self.assertSubmitHistoryItemsCount(page_ordinal=3, expected_count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(
                    resp, ["Already have final answer.",
                           "Failed to submit answer."])
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_proportion_partial(self):
        resp = self.client_post_answer_by_ordinal(4, {"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0.8)

    def test_quiz_multi_choice_proportion_correct(self):
        resp = self.client_post_answer_by_ordinal(4, {"choice": ['0', '3']})
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_quiz_inline(self):
        answer_data = {
            'blank1': ['Bar'], 'blank_2': ['0.2'], 'blank3': ['1'],
            'blank4': ['5'], 'blank5': ['Bar'], 'choice2': ['0'],
            'choice_a': ['0']}
        resp = self.client_post_answer_by_ordinal(5, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(10)

    # }}}

    # {{{ survey questions

    def test_quiz_survey_text(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=6, expected_count=0)
        resp = self.client_post_answer_by_ordinal(
                            6, {"answer": ["NOTHING!!!"]})
        self.assertSubmitHistoryItemsCount(page_ordinal=6, expected_count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)

        # Survey question won't be counted into final score
        self.assertSessionScoreEqual(0)

        query = FlowPageVisit.objects.filter(
            flow_session__exact=self.page_params["flow_session_id"],
            answer__isnull=False)
        self.assertEqual(query.count(), 1)
        record = query[0]
        self.assertEqual(record.answer["answer"], "NOTHING!!!")

    def test_quiz_survey_choice(self):
        self.assertSubmitHistoryItemsCount(page_ordinal=7, expected_count=0)

        # no answer thus no history
        self.client_post_answer_by_ordinal(7, {"choice": []})
        self.assertSubmitHistoryItemsCount(page_ordinal=7, expected_count=0)

        resp = self.client_post_answer_by_ordinal(7, {"choice": ['8']})
        self.assertSubmitHistoryItemsCount(page_ordinal=7, expected_count=1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)

        # Survey question won't be counted into final score
        self.assertSessionScoreEqual(0)

        query = FlowPageVisit.objects.filter(
                            flow_session__exact=self.page_params["flow_session_id"],
                            answer__isnull=False)
        self.assertEqual(query.count(), 1)
        record = query[0]
        self.assertEqual(record.answer["choice"], 8)

    def test_fileupload_any(self):
        page_id = "anyup"
        page_ordinal = self.get_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.client_post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            fp.seek(0)
            expected_result = b64encode(fp.read()).decode()
            self.assertEqual(resp.status_code, 200)

        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=1)
        query = FlowPageVisit.objects.filter(
                            flow_session__exact=self.page_params["flow_session_id"],
                            answer__isnull=False)
        self.assertEqual(query.count(), 1)
        record = query[0]
        self.assertEqual(record.answer["base64_data"], expected_result)
        self.assertSessionScoreEqual(None)

    def test_fileupload_any_change_answer(self):
        page_id = "anyup"
        page_ordinal = self.get_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.client_post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            fp.seek(0)
            expected_result1 = b64encode(fp.read()).decode()
            self.assertEqual(resp.status_code, 200)

        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=1)

        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.pdf'), 'rb') as fp:
            resp = self.client_post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)
            fp.seek(0)
            expected_result2 = b64encode(fp.read()).decode()

        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=2)

        query = FlowPageVisit.objects.filter(
            flow_session__exact=self.page_params["flow_session_id"],
            answer__isnull=False)
        self.assertEqual(query.count(), 2)
        self.assertEqual(query[1].answer["base64_data"], expected_result2)
        self.assertEqual(query[0].answer["base64_data"], expected_result1)
        self.assertSessionScoreEqual(None)

    def test_fileupload_pdf(self):
        page_id = "proof"
        page_ordinal = self.get_ordinal_via_page_id(page_id)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)
        # wrong MIME type
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            resp = self.client_post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)

        self.assertResponseMessagesContains(resp, [MESSAGE_ANSWER_FAILED_SAVE_TEXT])

        # There should be no submission history
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=0)
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.pdf'), 'rb') as fp:
            resp = self.client_post_answer_by_page_id(
                page_id, {"uploaded_file": fp})
            self.assertEqual(resp.status_code, 200)
            fp.seek(0)
            expected_result = b64encode(fp.read()).decode()

        self.assertResponseMessagesContains(resp, MESSAGE_ANSWER_SAVED_TEXT)
        self.assertSubmitHistoryItemsCount(page_ordinal=page_ordinal,
                                           expected_count=1)
        query = FlowPageVisit.objects.filter(
            flow_session__exact=self.page_params["flow_session_id"],
            answer__isnull=False)
        self.assertEqual(query.count(), 1)
        record = query[0]
        self.assertEqual(record.answer["base64_data"], expected_result)
        self.assertSessionScoreEqual(None)

    # {{{ tests on submission history dropdown
    def test_submit_history_failure_not_ajax(self):
        self.client_post_answer_by_ordinal(1, {"answer": ['0.5']})
        resp = self.c.get(
            self.page_submit_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_get(self):
        self.client_post_answer_by_ordinal(1, {"answer": ['0.5']})
        resp = self.c.post(
            self.page_submit_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_authenticated(self):
        self.client_post_answer_by_ordinal(1, {"answer": ['0.5']})
        self.c.logout()
        resp = self.c.post(
            self.page_submit_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_no_perm(self):
        self.c.force_login(self.ta_participation.user)
        self.start_quiz(self.flow_id)
        self.client_post_answer_by_ordinal(1, {"answer": ['0.5']})
        self.c.logout()
        self.c.force_login(self.student_participation.user)
        resp = self.c.post(
            self.page_submit_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    # }}}


class SingleCourseQuizPageGradeInterfaceTest(LocmemBackendTestsMixin,
                                SingleCoursePageTestMixin,
                                FallBackStorageMessageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

    def setUp(self):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTest, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.start_quiz(self.flow_id)
        self.submit_any_upload_question()

    def get_grading_page_url_by_page_id(self, flow_session_id, page_id):
        return reverse(
            "relate-grade_flow_page",
            kwargs={"course_identifier": self.course.identifier,
                    "flow_session_id": flow_session_id,
                    "page_ordinal": self.get_ordinal_via_page_id(page_id)})

    def submit_any_upload_question_null_failure(self):
        self.client_post_answer_by_page_id(
            "anyup", {"uploaded_file": []})

    def submit_any_upload_question(self):
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            self.client_post_answer_by_page_id(
                "anyup", {"uploaded_file": fp})

    def post_grade(self, flow_session_id, page_id, grade_data):
        post_data = {"submit": [""]}
        post_data.update(grade_data)
        resp = self.c.post(
            self.get_grading_page_url_by_page_id(flow_session_id, page_id),
            data=post_data,
            follow=True)
        return resp

    def test_post_grades(self):
        self.end_quiz()
        last_session = FlowSession.objects.all().last()
        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }
        self.c.force_login(self.ta_participation.user)
        resp = self.post_grade(last_session.pk, "anyup", grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(5)

        grade_data = {
            "grade_points": ["4"],
            "released": []
        }
        resp = self.post_grade(last_session.pk, "anyup", grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(None)

        grade_data = {
            "grade_points": ["4"],
            "released": ["on"]
        }
        resp = self.post_grade(last_session.pk, "anyup", grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(4)

    def test_post_grades_history(self):
        self.c.force_login(self.student_participation.user)
        page_id = "anyup"
        page_ordinal = self.get_ordinal_via_page_id(page_id)

        # failure
        self.submit_any_upload_question_null_failure()

        # 2nd success
        self.submit_any_upload_question()
        self.end_quiz()

        last_session = FlowSession.objects.all().last()
        grade_data = {
            "grade_percent": ["100"],
            "released": ["on"]
        }
        self.c.force_login(self.ta_participation.user)
        resp = self.post_grade(last_session.pk, page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(5)
        self.assertGradeHistoryItemsCount(page_ordinal=page_ordinal,
                                          expected_count=3)

        grade_data = {
            "grade_points": ["4"],
            "released": []
        }
        resp = self.post_grade(last_session.pk, page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(None)
        self.assertGradeHistoryItemsCount(page_ordinal=page_ordinal,
                                          expected_count=4)

        grade_data = {
            "grade_points": ["4"],
            "released": ["on"]
        }
        resp = self.post_grade(last_session.pk, page_id, grade_data)
        self.assertTrue(resp.status_code, 200)
        self.assertSessionScoreEqual(4)
        self.assertGradeHistoryItemsCount(page_ordinal=page_ordinal,
                                          expected_count=5)

    def test_post_grades_success(self):
        self.end_quiz()

        last_session = FlowSession.objects.all().last()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on']
        }

        self.c.force_login(self.ta_participation.user)

        resp = self.post_grade(last_session.pk, "anyup", grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(5)

    def test_post_grades_forbidden(self):
        page_id = "anyup"
        self.end_quiz()
        last_session = FlowSession.objects.all().last()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on']
        }

        # with self.student_participation.user logged in
        resp = self.post_grade(last_session.pk, page_id, grade_data)
        self.assertTrue(resp.status_code, 403)

        self.assertSessionScoreEqual(None)

    def test_feedback_and_notify(self):
        page_id = "anyup"
        self.end_quiz()
        last_session = FlowSession.objects.all().last()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on'],
            "feedback_text": ['test feedback']
        }

        self.c.force_login(self.ta_participation.user)
        self.post_grade(last_session.pk, page_id, grade_data)
        self.assertEqual(len(mail.outbox), 0)

        grade_data["notify"] = ["on"]
        self.post_grade(last_session.pk, page_id, grade_data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [])

    def test_feedback_email_may_reply(self):
        page_id = "anyup"
        self.end_quiz()

        last_session = FlowSession.objects.all().last()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on'],
            "feedback_text": ['test feedback'],
            "notify": ["on"],
            "may_reply": ["on"]
        }

        self.c.force_login(self.ta_participation.user)
        self.post_grade(last_session.pk, page_id, grade_data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [self.ta_participation.user.email])

    def test_notes_and_notify(self):
        page_id = "anyup"
        self.end_quiz()

        last_session = FlowSession.objects.all().last()

        grade_data = {
            "grade_percent": ["100"],
            "released": ['on'],
            "notes": ['test notes']
        }

        self.c.force_login(self.ta_participation.user)
        self.post_grade(last_session.pk, page_id, grade_data)
        self.assertEqual(len(mail.outbox), 0)

        grade_data["notify_instructor"] = ["on"]
        self.post_grade(last_session.pk, page_id, grade_data)
        self.assertEqual(len(mail.outbox), 1)

    # {{{ tests on grading history dropdown
    def test_grade_history_failure_not_ajax(self):
        self.end_quiz()

        self.c.force_login(self.ta_participation.user)
        resp = self.c.get(
            self.page_grade_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_get(self):
        self.end_quiz()

        self.c.force_login(self.ta_participation.user)
        resp = self.c.post(
            self.page_grade_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_authenticated(self):
        self.end_quiz()

        self.c.logout()
        resp = self.c.post(
            self.page_grade_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_no_perm(self):
        self.c.force_login(self.ta_participation.user)
        self.start_quiz(self.flow_id)
        self.end_quiz()

        self.c.force_login(self.student_participation.user)
        resp = self.c.post(
            self.page_grade_history_url(
                flow_session_id=FlowSession.objects.all().last().pk,
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    # }}}

# vim: fdm=marker
