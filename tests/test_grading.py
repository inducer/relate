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

from django.core import mail
from django.test import TestCase

from tests.base_test_mixins import SingleCourseQuizPageTestMixin
from tests import factories


class SingleCourseQuizPageGradeInterfaceTestMixin(SingleCourseQuizPageTestMixin):

    page_id = "anyup"

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTestMixin, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)
        cls.start_flow(cls.flow_id)
        cls.this_flow_session_id = cls.default_flow_params["flow_session_id"]
        cls.submit_page_answer_by_page_id_and_test(cls.page_id)


class SingleCourseQuizPageGradeInterfaceTest(
        SingleCourseQuizPageGradeInterfaceTestMixin, TestCase):

    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCourseQuizPageGradeInterfaceTest, cls).setUpTestData()
        cls.end_flow()

    def test_post_grades(self):
        self.submit_page_human_grading_by_page_id_and_test(self.page_id)

        grade_data = {
            "grade_points": "4",
            "released": []
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=None)

        grade_data = {
            "grade_points": "4",
            "released": "on"
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=4)

    def test_post_grades_huge_points_failure(self):
        grade_data = {
            "grade_percent": "2000",
            "released": 'on'
        }

        resp = self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=None)

        # value exceeded allowed
        self.assertResponseContextContains(
            resp, "grading_form_html",
            "Ensure this value is less than or equal to")

    def test_post_grades_forbidden(self):
        # with self.student_participation.user logged in
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, expected_grades=None,
            force_login_instructor=False, expected_post_grading_status_code=403)

    def test_feedback_and_notify(self):
        grade_data_extra_kwargs = {
            "released": 'on',
            "feedback_text": 'test feedback'
        }

        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
        self.assertEqual(len(mail.outbox), 0)

        grade_data_extra_kwargs["notify"] = "on"
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to, [])

    def test_feedback_email_may_reply(self):
        grade_data_extra_kwargs = {
            "feedback_text": 'test feedback',
            "may_reply": "on",
            "notify": "on"
        }

        with self.temporarily_switch_to_user(self.ta_participation.user):
            self.submit_page_human_grading_by_page_id_and_test(
                self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs,
                force_login_instructor=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].reply_to,
                         [self.ta_participation.user.email])

    def test_notes_and_notify(self):
        grade_data_extra_kwargs = {
            "notes": 'test notes'
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
        self.assertEqual(len(mail.outbox), 0)

        grade_data_extra_kwargs["notify_instructor"] = "on"
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data_extra_kwargs=grade_data_extra_kwargs)
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
        resp, _ = self.submit_page_answer_by_page_id_and_test(
            self.page_id, answer_data={"uploaded_file": []})
        self.assertFormErrorLoose(resp, "This field is required.")

        # 2nd submission succeeded
        self.submit_page_answer_by_page_id_and_test(self.page_id, do_grading=False)
        self.end_flow()

        self.submit_page_human_grading_by_page_id_and_test(self.page_id)

        ordinal = self.get_page_ordinal_via_page_id(self.page_id)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=3)

        grade_data = {
            "grade_points": "4",
            "released": []
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=None)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal, expected_count=4)

        grade_data = {
            "grade_points": "4",
            "released": "on"
        }
        self.submit_page_human_grading_by_page_id_and_test(
            self.page_id, grade_data=grade_data, expected_grades=4)
        self.assertGradeHistoryItemsCount(page_ordinal=ordinal,
                                          expected_count=5)

# vim: fdm=marker
