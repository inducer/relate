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

from django.test import TestCase, Client
from django.contrib.auth.models import User


class CourseCreationTest(TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        # Set up data for the whole TestCase
        cls.admin = User.objects.create(
                username="testadmin",
                password="test",
                email="test@example.com",
                first_name="Test",
                last_name="Admin")

    def test_course_creation(self):
        c = Client()
        c.login(username="testadmin", password="test")

        resp = c.post("/new-course/", dict(
            identifier="test-course",
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

        self.assert_(resp.status_code == 302)
        print resp.content
