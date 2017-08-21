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

from django.test import TestCase
from django.urls import reverse
from base_test_mixins import SingleCourseTestMixin
from course.models import Participation
from course.constants import participation_permission as pperm


class SingleCoursePageSandboxTest(SingleCourseTestMixin, TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCoursePageSandboxTest, cls).setUpTestData()
        participation = (
            Participation.objects.filter(
                course=cls.course,
                roles__permissions__permission=pperm.use_page_sandbox
            ).first()
        )
        assert participation
        cls.c.force_login(participation.user)

    def test_page_sandbox_get(self):
        resp = self.c.get(reverse("relate-view_page_sandbox",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_page_sandbox_post(self):
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
        data = {'content': [question_markup], 'preview': ['Preview']}
        resp = self.c.post(reverse("relate-view_page_sandbox",
                                   args=[self.course.identifier]), data)
        self.assertEqual(resp.status_code, 200)

        # Try to answer the rendered question
        data = {'answer': ['0.5'], 'submit': ['Submit answer']}
        resp = self.c.post(reverse("relate-view_page_sandbox",
                                   args=[self.course.identifier]), data)
        self.assertEqual(resp.status_code, 200)
