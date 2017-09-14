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

from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from course.models import FlowPageVisit, Course
from base_test_mixins import SingleCoursePageTestMixin

QUIZ_FLOW_ID = "quiz-test"


class SingleCourseQuizPageTest(SingleCoursePageTestMixin, TestCase):
    flow_id = QUIZ_FLOW_ID

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

    def test_quiz_no_answer(self):
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_text(self):
        resp = self.client_post_answer_by_ordinal(1, {"answer": ['0.5']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(5)

    def test_quiz_choice(self):
        resp = self.client_post_answer_by_ordinal(2, {"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(2)

    def test_quiz_multi_choice_exact_correct(self):
        resp = self.client_post_answer_by_ordinal(3, {"choice": ['0', '1', '4']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_quiz_multi_choice_exact_wrong(self):
        resp = self.client_post_answer_by_ordinal(3, {"choice": ['0', '1']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

    def test_quiz_multi_choice_proportion_partial(self):
        resp = self.client_post_answer_by_ordinal(4, {"choice": ['0']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0.8)

    def test_quiz_multi_choice_proportion_correct(self):
        resp = self.client_post_answer_by_ordinal(4, {"choice": ['0', '3']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(1)

    def test_quiz_inline(self):
        answer_data = {
            'blank1': ['Bar'], 'blank_2': ['0.2'], 'blank3': ['1'],
            'blank4': ['5'], 'blank5': ['Bar'], 'choice2': ['0'],
            'choice_a': ['0']}
        resp = self.client_post_answer_by_ordinal(5, answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(10)

    # All I can do for now since db do not store ordinal value
    def test_quiz_survey_choice(self):
        resp = self.client_post_answer_by_ordinal(6, {"answer": ["NOTHING!!!"]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

        query = FlowPageVisit.objects.filter(
            flow_session__exact=self.page_params["flow_session_id"],
            answer__isnull=False)
        self.assertEqual(query.count(), 1)
        record = query[0]
        self.assertEqual(record.answer["answer"], "NOTHING!!!")

    def test_quiz_survey_text(self):
        resp = self.client_post_answer_by_ordinal(7, {"choice": ['8']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.end_quiz().status_code, 200)
        self.assertSessionScoreEqual(0)

        query = FlowPageVisit.objects.filter(
                            flow_session__exact=self.page_params["flow_session_id"],
                            answer__isnull=False)
        self.assertEqual(query.count(), 1)
        record = query[0]
        self.assertEqual(record.answer["choice"], 8)
