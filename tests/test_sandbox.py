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
from .base_test_mixins import SingleCourseTestMixin

QUESTION_MARKUP = """
type: TextQuestion
id: half
value: 5
prompt: |
    # A half
    What's a half?
answers:
    - type: float
      value: 0.5
      rtol: 1e-4
    - <plain>half
    - <plain>a half
"""

CORRECT_ANSWER = 0.5
PAGE_WARNINGS = "page_warnings"
PAGE_ERRORS = "page_errors"
HAVE_VALID_PAGE = "have_valid_page"


class SingleCoursePageSandboxTestBaseMixin(SingleCourseTestMixin):
    def setUp(self):  # noqa
        super(SingleCoursePageSandboxTestBaseMixin, self).setUp()
        self.c.force_login(self.instructor_participation.user)

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

    def get_sandbox_data_by_key(self, key):
        return self.c.session.get("%s:%s" % (key, self.course.identifier))

    def get_sandbox_page_data(self):
        return self.get_sandbox_data_by_key("cf_page_sandbox_page_data")

    def get_sandbox_answer_data(self):
        return self.get_sandbox_data_by_key("cf_page_sandbox_answer_data")

    def get_sandbox_page_session(self):
        return self.get_sandbox_data_by_key("cf_validated_sandbox_page")

    def assertSandboxHaveValidPage(self, resp):  # noqa
        self.assertResponseContextEqual(resp, HAVE_VALID_PAGE, True)

    def assertSandboxWarningTextContain(self, resp, expected_text):  # noqa
        warnings = self.get_response_context_value_by_name(resp, PAGE_WARNINGS)
        warnings_text = [w.text for w in warnings]
        self.assertIn(expected_text, warnings_text)

    def assertSandboxNotHaveValidPage(self, resp):  # noqa
        self.assertResponseContextEqual(resp, HAVE_VALID_PAGE, False)


class SingleCoursePageSandboxTest(SingleCoursePageSandboxTestBaseMixin, TestCase):
    def test_page_sandbox_get(self):
        resp = self.c.get(reverse("relate-view_page_sandbox",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_page_sandbox_preview(self):
        # Check one of the quiz questions
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHaveValidPage(resp)
        self.assertResponseContextIsNone(resp, "feedback")

        from course.page.text import CORRECT_ANSWER_PATTERN
        expected_correct_answer = CORRECT_ANSWER_PATTERN % CORRECT_ANSWER
        expected_body_string = "<h1>A half</h1>\n<p>What's a half?</p>"

        self.assertResponseContextContains(
                    resp, "body", expected_body_string)
        self.assertResponseContextEqual(
                    resp, "correct_answer", expected_correct_answer)

    def test_page_sandbox_submit_answer(self):
        # Try to answer the rendered question
        answer_data = {'answer': ['0.5']}
        resp = self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

        answer_data = {'answer': ['0.6']}
        resp = self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)
