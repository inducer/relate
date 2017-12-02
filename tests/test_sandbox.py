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
from django.utils.safestring import mark_safe
from .base_test_mixins import SingleCourseTestMixin
from course.models import Participation
from course.constants import participation_permission as pperm

QUESTION_MARKUP = """
type: TextQuestion\r
id: half\r
value: 5\r
prompt: |\r
    # A half\r
    What's a half?\r
answers:\r
    - type: float\r
      value: 0.5\r
      rtol: 1e-4\r
    - <plain>half\r
    - <plain>a half
"""

CORRECT_ANSWER = 0.5


class SingleCoursePageSandboxTestBaseMixin(SingleCourseTestMixin):
    @classmethod
    def setUpTestData(cls):  # noqa
        super(SingleCoursePageSandboxTestBaseMixin, cls).setUpTestData()
        participation = (
            Participation.objects.filter(
                course=cls.course,
                roles__permissions__permission=pperm.use_page_sandbox
            ).first()
        )
        assert participation
        cls.c.force_login(participation.user)

    @classmethod
    def get_page_sandbox_post_response(cls, data):
        """
        Get the preview response of content in page sandbox
        :param page_sandbox_content: :class:`String`, RELATE flavored page markdown
        :return: :class: `http.HttpResponse`
        """
        return cls.c.post(
            reverse("relate-view_page_sandbox", args=[cls.course.identifier]),
            data)

    @classmethod
    def get_page_sandbox_preview_response(cls, markup_content):
        """
        Get the preview response of content in page sandbox
        :param markup_content: :class:`String`, RELATE flavored page markdown
        :return: :class: `http.HttpResponse`
        """
        data = {'content': [markup_content], 'preview': ['Preview']}
        return cls.get_page_sandbox_post_response(data)

    @classmethod
    def get_page_sandbox_submit_answer_response(cls, markup_content,
                                                answer_data):
        """
        Get the response of preview content and then post an answer, in page sandbox
        :param markup_content: :class:`String`, RELATE flavored page markdown
        :param answer_data: :class:`Dict`, the answer
        :return: :class: `http.HttpResponse`
        """

        cls.get_page_sandbox_preview_response(markup_content)
        data = {'submit': ['Submit answer']}
        data.update(answer_data)
        return cls.get_page_sandbox_post_response(data)


class SingleCoursePageSandboxTest(SingleCoursePageSandboxTestBaseMixin, TestCase):
    def test_page_sandbox_get(self):
        resp = self.c.get(reverse("relate-view_page_sandbox",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_page_sandbox_preview(self):
        # Check one of the quiz questions
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP)
        self.assertEqual(resp.status_code, 200)

        result_correct_answer = resp.context.__getitem__("correct_answer")
        self.assertIsNone(resp.context.__getitem__("feedback"))

        from course.page.text import CA_PATTERN
        expected_correct_answer = CA_PATTERN % CORRECT_ANSWER
        expected_body = "<h1>A half</h1>\n<p>What's a half?</p>"

        self.assertContains(resp, expected_body)
        self.assertEqual(mark_safe(result_correct_answer), expected_correct_answer)

    def test_page_sandbox_submit_answer(self):
        # Try to answer the rendered question
        answer_data = {'answer': ['0.5']}
        resp = self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertEqual(resp.status_code, 200)

        result_correctness = resp.context.__getitem__("feedback").correctness
        self.assertEquals(int(result_correctness), 1)

        answer_data = {'answer': ['0.6']}
        resp = self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        result_correctness = resp.context.__getitem__("feedback").correctness
        self.assertEquals(int(result_correctness), 0)
