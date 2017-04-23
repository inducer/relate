from __future__ import division

__copyright__ = "Copyright (C) 2017 Zesheng Wang"

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
from django.urls import reverse
from accounts.models import User


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
            git_source="git://github.com/inducer/relate-sample",
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

    def test_page_sandbox(self):
        # Check if page is there
        resp = self.c.get(reverse("relate-view_page_sandbox", args=["test-course"]))
        self.assertEqual(resp.status_code, 200)

        # Check one of the quiz questions
        question_markup = ("type: TextQuestion\r\n"
                            "id: half\r\nvalue: 5\r\n"
                            "prompt: |\r\n  # A half\r\n"
                            "  What's a half?\r\n"
                            "answers:\r\n\r\n"
                            "  - type: float\r\n"
                            "    value: 0.5\r\n"
                            "    rtol: 1e-4\r\n"
                            "  - <plain>half\r\n"
                            "  - <plain>a half")
        datas = {'content': [question_markup], 'preview': ['Preview']}
        resp = self.c.post(reverse("relate-view_page_sandbox",
                                                    args=["test-course"]), datas)
        self.assertEqual(resp.status_code, 200)

        # Try to answer the rendered question
        datas = {'answer': ['0.5'], 'submit': ['Submit answer']}
        resp = self.c.post(reverse("relate-view_page_sandbox",
                                                    args=["test-course"]), datas)
        self.assertEqual(resp.status_code, 200)
