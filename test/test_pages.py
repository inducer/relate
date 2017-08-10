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
from django.urls import resolve, reverse
from django.contrib.auth import get_user_model
from course.models import FlowSession, FlowPageVisit, Course
from decimal import Decimal
from base_test_mixins import SingleCourseTestMixin


class SingleCoursePageTest(SingleCourseTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCoursePageTest, cls).setUpTestData()
        cls.c.force_login(cls.student_participation.user)

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
        params = self.start_quiz()
        self.end_quiz(params, 0)

    def test_quiz_text(self):
        params = self.start_quiz()
        params["ordinal"] = '1'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                        {"answer": ['0.5'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 5)

    def test_quiz_choice(self):
        params = self.start_quiz()
        params["ordinal"] = '2'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                        {"choice": ['0'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 2)

    def test_quiz_multi_choice_exact_correct(self):
        params = self.start_quiz()
        params["ordinal"] = '3'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                    {"choice": ['0', '1', '4'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 1)

    def test_quiz_multi_choice_exact_wrong(self):
        params = self.start_quiz()
        params["ordinal"] = '3'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                    {"choice": ['0', '1'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 0)

    def test_quiz_multi_choice_propotion_partial(self):
        params = self.start_quiz()
        params["ordinal"] = '4'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                    {"choice": ['0'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 0.8)

    def test_quiz_multi_choice_propotion_correct(self):
        params = self.start_quiz()
        params["ordinal"] = '4'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                    {"choice": ['0', '3'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 1)

    def test_quiz_inline(self):
        params = self.start_quiz()
        params["ordinal"] = '5'
        data = {'blank1': ['Bar'], 'blank_2': ['0.2'], 'blank3': ['1'],
                'blank4': ['5'], 'blank5': ['Bar'], 'choice2': ['0'],
                'choice_a': ['0'], 'submit': ['Submit final answer']}
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params), data)
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 10)

    # All I can do for now since db do not store ordinal value
    def test_quiz_survey_choice(self):
        params = self.start_quiz()
        params["ordinal"] = '6'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                    {"answer": ["NOTHING!!!"], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 0)

        query = FlowPageVisit.objects.filter(
                            flow_session__exact=params["flow_session_id"],
                            answer__isnull=False)
        self.assertEqual(len(query), 1)
        record = query[0]
        self.assertEqual(record.answer["answer"], "NOTHING!!!")

    def test_quiz_survey_text(self):
        params = self.start_quiz()
        params["ordinal"] = '7'
        resp = self.c.post(reverse("relate-view_flow_page", kwargs=params),
                    {"choice": ['8'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        self.end_quiz(params, 0)

        query = FlowPageVisit.objects.filter(
                            flow_session__exact=params["flow_session_id"],
                            answer__isnull=False)
        self.assertEqual(len(query), 1)
        record = query[0]
        self.assertEqual(record.answer["choice"], 8)

    # Decorator won't work here :(
    def start_quiz(self):
        self.assertEqual(len(FlowSession.objects.all()), 0)
        params = {"course_identifier": self.course.identifier,
                  "flow_id": "quiz-test"}
        resp = self.c.post(reverse("relate-view_start_flow", kwargs=params))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(FlowSession.objects.all().count(), 1)

        # Yep, no regax!
        _, _, kwargs = resolve(resp.url)
        # Should be in correct course
        self.assertEqual(kwargs["course_identifier"], self.course.identifier)
        # Should redirect us to welcome page
        self.assertEqual(kwargs["ordinal"], '0')

        return kwargs

    def end_quiz(self, params, expect_score):
        # Let it raise error
        # Use pop() will not
        del params["ordinal"]
        resp = self.c.post(reverse("relate-finish_flow_session_view",
                                kwargs=params), {'submit': ['']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FlowSession.objects.all()[0].points,
                                                Decimal(str(expect_score)))
