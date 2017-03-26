from __future__ import division

__copyright__ = "Copyright (C) 2014 Andreas Kloeckner"

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

import shutil
from django.test import TestCase, Client
from django.urls import resolve, reverse
from accounts.models import User
from course.models import FlowSession, FlowPageVisit
from decimal import Decimal


class CourseTest(TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        # Set up data for the whole TestCase
        cls.admin = User.objects.create_superuser(
                username="testadmin",
                password="test",
                email="test@example.com",
                first_name="Test",
                last_name="Admin")
        cls.admin.save()
        # Create the course here and check later to
        # avoid exceptions raised here
        cls.c = Client()
        cls.c.login(
            username="testadmin",
            password="test")
        cls.c.post("/new-course/", dict(
            identifier="test-course",
            name="Test Course",
            number="CS123",
            time_period="Fall 2016",
            hidden=True,
            listed=True,
            accepts_enrollment=True,
            git_source="git://github.com/zwang180/relate-sample",
            course_file="course.yml",
            events_file="events.yml",
            enrollment_approval_required=True,
            enrollment_required_email_suffix=None,
            from_email="inform@tiker.net",
            notify_email="inform@tiker.net"))

    @classmethod
    def tearDownClass(cls):
        # Remove created folder
        shutil.rmtree('../test-course')
        super(CourseTest, cls).tearDownClass()

    def test_user_creation(self):
        self.assertTrue(self.c.login(
            username="testadmin",
            password="test"))

    def test_course_creation(self):
        resp = self.c.get(reverse("relate-course_page", args=["test-course"]))
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
                            flow_session__exact = params["flow_session_id"],
                            answer__isnull = False)
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
                            flow_session__exact = params["flow_session_id"],
                            answer__isnull = False)
        self.assertEqual(len(query), 1)
        record = query[0]
        self.assertEqual(record.answer["choice"], 8)

    # Decorator won't work here :(
    def start_quiz(self):
        self.assertEqual(len(FlowSession.objects.all()), 0)
        params = {"course_identifier": "test-course", "flow_id": "quiz-test"}
        resp = self.c.post(reverse("relate-view_start_flow", kwargs=params))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(FlowSession.objects.all()), 1)

        # Yep, no regax!
        _, _, kwargs = resolve(resp.url)
        # Should be in correct course
        self.assertEqual(kwargs["course_identifier"], "test-course")
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
        self.assertEqual(FlowSession.objects.all()[0].points, Decimal(str(expect_score)))
