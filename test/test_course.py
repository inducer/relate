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
import re
from django.test import TestCase, Client
from accounts.models import User
from course.models import FlowSession
from course.constants import COURSE_ID_REGEX


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
        resp = self.c.get("/course/test-course/")
        # 200 != 302 is better than False is not True
        self.assertEqual(resp.status_code, 200)

    def test_quiz_textual(self):
        session_url = self.start_quiz()

        resp = self.c.post(session_url.format('3'),
                        {"answer": ['0.5'], "submit": ["Submit final answer"]})
        self.assertEqual(resp.status_code, 200)
        
        resp = self.c.post(session_url.format("finish"),
                        {'submit': ['']})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FlowSession.objects.all()[0].points, 5)

    def start_quiz(self):
        self.assertEqual(len(FlowSession.objects.all()), 0)
        resp = self.c.post("/course/test-course/flow/quiz-test/start/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(FlowSession.objects.all()), 1)

        pattern = r"^/course" + \
            "/" + COURSE_ID_REGEX + \
            "/flow-session" + \
            "/(?P<flow_session_id>[0-9]+)" + \
            "/(?P<ordinal>[0-9]+)" + \
            "/$"
        params = re.match(pattern, resp.url).groupdict()
        # Should be in correct course
        self.assertEqual(params["course_identifier"], "test-course")
        # Should redirect us to welcome page
        self.assertEqual(params["ordinal"], '0')

        return "/course/test-course/flow-session/" + \
                    params["flow_session_id"] + "/{0}/"
