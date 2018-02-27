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

import os

from django.core import mail
from django.test import TestCase

from tests.base_test_mixins import SingleCoursePageTestMixin
from tests.test_pages import QUIZ_FLOW_ID
from tests import factories


class SingleCourseQuizPageGradeInterfaceTestMixin(SingleCoursePageTestMixin):

    flow_id = QUIZ_FLOW_ID

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTestMixin, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)
        cls.this_flow_session_id = cls.default_flow_params["flow_session_id"]
        cls.any_up_page_id = "anyup"
        cls.submit_any_upload_question()

    def submit_any_upload_question_null(self):
        return self.post_answer_by_page_id(
            "anyup", {"uploaded_file": []})

    @classmethod
    def submit_any_upload_question(cls):
        with open(
                os.path.join(os.path.dirname(__file__),
                             'fixtures', 'test_file.txt'), 'rb') as fp:
            answer_data = {"uploaded_file": fp}
            return cls.post_answer_by_page_id_class(
                cls.any_up_page_id, answer_data, **cls.default_flow_params)


class SingleCourseQuizPageGradeInterfaceTest(
        SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTest, cls).setUpTestData()
        cls.end_flow()

    def setUp(self):  # noqa
        # This is needed to ensure student is logged in to submit page or end flow.
        self.c.force_login(self.student_participation.user)

    def test_post_grades(self):
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

    def test_post_grades_success(self):
        grade_data = {
            "grade_percent": ["100"],
            "released": ['on']
        }

        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)

        self.assertSessionScoreEqual(5)

    def test_post_grades_huge_points_failure(self):
        grade_data = {
            "grade_percent": ["2000"],
            "released": ['on']
        }

        resp = self.post_grade_by_page_id(self.any_up_page_id, grade_data)
        self.assertTrue(resp.status_code, 200)

        # value exceeded allowed
        self.assertResponseContextContains(
            resp, "grading_form_html",
            "Ensure this value is less than or equal to")

        self.assertSessionScoreEqual(None)

    def test_post_grades_forbidden(self):
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
        self.assertEqual(mail.outbox[0].reply_to,
                         [self.ta_participation.user.email])

    def test_notes_and_notify(self):
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
    def test_grade_history_failure_no_perm(self):
        ta_flow_session = factories.FlowSessionFactory(
            participation=self.ta_participation)

        # no pperm to view other's grade_history
        resp = self.c.post(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1, flow_session_id=ta_flow_session.pk))
        self.assertEqual(resp.status_code, 403)

    def test_grade_history_failure_not_ajax(self):
        resp = self.c.get(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1))
        self.assertEqual(resp.status_code, 403)

    def test_submit_history_failure_not_get(self):
        resp = self.c.post(
            self.get_page_grade_history_url_by_ordinal(
                page_ordinal=1), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    def test_grade_history_failure_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(
                self.get_page_grade_history_url_by_ordinal(
                    page_ordinal=1), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 403)

    # }}}


class SingleCourseQuizPageGradeInterfaceTestExtra(
        SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):

    def setUp(self):  # noqa
        # This is needed to ensure student is logged in to submit page or end flow.
        self.c.force_login(self.student_participation.user)

    def test_post_grades_history(self):
        # This submission failed
        resp = self.submit_any_upload_question_null()
        self.assertFormErrorLoose(resp, "This field is required.")

        # 2nd submission succeeded
        resp = self.submit_any_upload_question()
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

# vim: fdm=marker
