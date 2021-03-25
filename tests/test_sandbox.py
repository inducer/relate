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

from course.sandbox import (
    PAGE_SESSION_KEY_PREFIX, PAGE_DATA_SESSION_KEY_PREFIX,
    ANSWER_DATA_SESSION_KEY_PREFIX, make_sandbox_session_key)

from tests.base_test_mixins import (
    SingleCourseTestMixin, MockAddMessageMixing)
from tests.constants import PAGE_WARNINGS, HAVE_VALID_PAGE, PAGE_ERRORS
from tests.utils import mock

QUESTION_MARKUP = """
type: TextQuestion
id: half
value: 5
prompt: |
    # A half
    What's a half?
answers:
    - <regex>half
    - type: float
      value: 0.5
      rtol: 1e-4
    - <plain>half
    - <plain>a half
"""

CORRECT_ANSWER = 0.5

INVALID_QUESTION_MARKUP_WITH_LIST_MAKER = """
-
    type: TextQuestion
    id: half
    value: 5
    prompt: |
        # A half
        What's a half?
    answers:
        - <regex>half
        - type: float
          value: 0.5
          rtol: 1e-4
        - <plain>half
        - <plain>a half
"""

PAGE_MARKUP = """
type: Page
id: welcome
title: "Linear algebra quiz"
content: |

    # Welcome to the linear algebra quiz!

    Don't be scared.
"""


class SingleCoursePageSandboxTestBaseMixin(SingleCourseTestMixin):
    def setUp(self):  # noqa
        super(SingleCoursePageSandboxTestBaseMixin, self).setUp()
        self.c.force_login(self.instructor_participation.user)

    @classmethod
    def get_page_sandbox_url(cls):
        return reverse("relate-view_page_sandbox", args=[cls.course.identifier])

    @classmethod
    def get_page_sandbox_post_response(cls, data, action):
        post_data = {action: ""}
        post_data.update(data)
        return cls.c.post(cls.get_page_sandbox_url(), post_data)

    @classmethod
    def get_page_sandbox_preview_response(cls, markup_content):
        """
        Get the preview response of content in page sandbox
        :param markup_content: :class:`String`, RELATE flavored page markdown
        :return: :class: `http.HttpResponse`
        """
        data = {'content': [markup_content]}
        return cls.get_page_sandbox_post_response(data, action='preview')

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
        return cls.get_page_sandbox_post_response(answer_data, action='submit')

    def get_sandbox_data_by_key(self, key):
        return self.c.session.get(
            make_sandbox_session_key(key, self.course.identifier))

    def get_sandbox_page_data(self):
        return self.get_sandbox_data_by_key(PAGE_DATA_SESSION_KEY_PREFIX)

    def get_sandbox_answer_data(self):
        return self.get_sandbox_data_by_key(ANSWER_DATA_SESSION_KEY_PREFIX)

    def get_sandbox_page_session(self):
        return self.get_sandbox_data_by_key(PAGE_SESSION_KEY_PREFIX)

    def assertSandboxHasValidPage(self, resp):  # noqa
        self.assertResponseContextEqual(resp, HAVE_VALID_PAGE, True)

    def assertSandboxWarningTextContain(self, resp, expected_text, loose=False):  # noqa
        warnings = self.get_response_context_value_by_name(resp, PAGE_WARNINGS)
        warnings_strs = [w.text for w in warnings]
        if expected_text is None:
            return self.assertEqual(
                warnings_strs, [],
                "Page validatioin warning is not None, but %s."
                % repr(warnings_strs))
        if loose:
            warnings_strs = "".join(warnings_strs)
        self.assertIn(expected_text, warnings_strs)

    def assertSandboxNotHasValidPage(self, resp):  # noqa
        self.assertResponseContextEqual(resp, HAVE_VALID_PAGE, False)

    @classmethod
    def get_markup_sandbox_url(cls):
        return reverse("relate-view_markup_sandbox", args=[cls.course.identifier])

    @classmethod
    def get_markup_sandbox_view(cls):
        return cls.c.get(cls.get_markup_sandbox_url())

    @classmethod
    def post_markup_sandbox_view(cls, markup_content, action="preview"):
        post_data = {
            "content": markup_content,
            action: ""}
        return cls.c.post(cls.get_markup_sandbox_url(), post_data)


class SingleCoursePageSandboxTest(SingleCoursePageSandboxTestBaseMixin, TestCase):
    def test_page_sandbox_get(self):
        resp = self.c.get(reverse("relate-view_page_sandbox",
                                  args=[self.course.identifier]))
        self.assertEqual(resp.status_code, 200)

    def test_page_sandbox_preview(self):
        # Check one of the quiz questions
        resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertResponseContextIsNone(resp, "feedback")

        from course.page.text import CORRECT_ANSWER_PATTERN
        expected_correct_answer = CORRECT_ANSWER_PATTERN % CORRECT_ANSWER
        expected_body_html = "<h1>A half</h1><p>What's a half?</p>"

        self.assertResponseContextContains(
                    resp, "body", expected_body_html, html=True)
        self.assertResponseContextEqual(
                    resp, "correct_answer", expected_correct_answer)

    def test_page_sandbox_submit_answer(self):
        # Try to answer the rendered question
        answer_data = {'answer': ['a half']}
        resp = self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 1)

        answer_data = {'answer': ['0.6']}
        resp = self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, 0)


class ViewPageSandboxTest(SingleCoursePageSandboxTestBaseMixin, TestCase):
    """test course.sandbox.view_page_sandbox
     (for cases not covered by other tests)"""
    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.c.get(self.get_page_sandbox_url())
            self.assertEqual(resp.status_code, 403)

            resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP)
            self.assertEqual(resp.status_code, 403)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.c.get(self.get_page_sandbox_url())
            self.assertEqual(resp.status_code, 403)

            resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP)
            self.assertEqual(resp.status_code, 403)

    def test_edit_form_not_valid(self):
        """make sure edit_form not valid will work"""
        with mock.patch(
                "course.sandbox.PageSandboxForm.is_valid") as mock_form_valid:
            mock_form_valid.return_value = False
            resp = self.get_page_sandbox_preview_response(QUESTION_MARKUP)
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)

    def test_yaml_data_not_struct(self):
        markup = INVALID_QUESTION_MARKUP_WITH_LIST_MAKER
        resp = self.get_page_sandbox_preview_response(markup)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "Provided page source code is not "
            "a dictionary. Do you need to remove a leading "
            "list marker ('-') or some stray indentation?")

    def test_is_clear_post(self):
        answer_data = {'answer': ['a half']}
        self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertIsNotNone(self.get_sandbox_page_data())
        self.assertIsNotNone(self.get_sandbox_answer_data())

        data = {'content': [QUESTION_MARKUP]}
        resp = self.get_page_sandbox_post_response(data, action='clear')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.get_sandbox_page_data())
        self.assertIsNone(self.get_sandbox_answer_data())
        self.assertResponseContextIsNone(resp, "page_form_html")

    def test_is_clear_response_post(self):
        answer_data = {'answer': ['a half']}
        self.get_page_sandbox_submit_answer_response(
            markup_content=QUESTION_MARKUP, answer_data=answer_data)
        self.assertIsNotNone(self.get_sandbox_page_data())
        self.assertIsNotNone(self.get_sandbox_answer_data())

        data = {'content': [QUESTION_MARKUP]}
        resp = self.get_page_sandbox_post_response(data, action='clear_response')
        self.assertEqual(resp.status_code, 200)

        self.assertIsNone(self.get_sandbox_page_data())
        self.assertIsNone(self.get_sandbox_answer_data())
        self.assertResponseContextIsNone(resp, "page_form_html")

    def test_post_form_make_form_failed(self):
        with mock.patch(
                "course.page.text.TextQuestion.make_form") as mock_make_form:
            error_msg = "my make form error"
            mock_make_form.side_effect = RuntimeError(error_msg)
            resp = self.get_page_sandbox_preview_response(
                markup_content=QUESTION_MARKUP)

            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(
                resp, PAGE_ERRORS, error_msg)

    def test_reload_from_storage(self):
        self.get_page_sandbox_preview_response(
            markup_content=QUESTION_MARKUP)
        resp = self.c.get(self.get_page_sandbox_url())

        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

    def test_reload_from_storage_success(self):
        self.get_page_sandbox_preview_response(
            markup_content=QUESTION_MARKUP)
        resp = self.c.get(self.get_page_sandbox_url())

        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

    def test_reload_from_storage_data_not_match(self):
        self.get_page_sandbox_preview_response(
            markup_content=QUESTION_MARKUP)
        from django.core.cache import cache
        cache.clear()

        # change the page_desc stored
        key = make_sandbox_session_key(
            PAGE_SESSION_KEY_PREFIX, self.course.identifier)
        session = self.c.session
        session[key] = PAGE_MARKUP
        session.save()

        resp = self.c.get(self.get_page_sandbox_url())
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)

        self.assertResponseContextIsNone(resp, "page_form_html")

    def test_reload_from_storage_instantiate_page_errored(self):
        self.get_page_sandbox_preview_response(
            markup_content=QUESTION_MARKUP)
        with mock.patch(
                "course.content.instantiate_flow_page") as mock_instantiate:
            error_msg = "my make form error"
            mock_instantiate.side_effect = RuntimeError(error_msg)
            resp = self.c.get(self.get_page_sandbox_url())

            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(resp, PAGE_ERRORS, error_msg)


class ViewMarkupSandboxTest(SingleCoursePageSandboxTestBaseMixin,
                            MockAddMessageMixing, TestCase):
    """test course.sansbox.view_markup_sandbox"""
    def test_not_authenticated(self):
        with self.temporarily_switch_to_user(None):
            resp = self.get_markup_sandbox_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_markup_sandbox_view(markup_content="abcd")
            self.assertEqual(resp.status_code, 403)

    def test_no_pperm(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            resp = self.get_markup_sandbox_view()
            self.assertEqual(resp.status_code, 403)

            resp = self.post_markup_sandbox_view(markup_content="abcd")
            self.assertEqual(resp.status_code, 403)

    def test_get(self):
        resp = self.get_markup_sandbox_view()
        self.assertEqual(resp.status_code, 200)

    def test_unknown_post_operation(self):
        resp = self.post_markup_sandbox_view(markup_content="abcd", action="unknown")
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(resp, "preview_text", "")

    def test_post_form_not_valid(self):
        with mock.patch("course.sandbox.SandboxForm.is_valid") as mock_form_valid:
            mock_form_valid.return_value = False
            resp = self.post_markup_sandbox_view(markup_content=mock.MagicMock())
            self.assertEqual(resp.status_code, 200)
            self.assertResponseContextEqual(resp, "preview_text", "")

    def test_preview(self):
        resp = self.post_markup_sandbox_view(markup_content="[home](course:)")
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "preview_text",
            '<p><a href="/course/%s/">home</a></p>' % self.course.identifier)

    def test_preview_failed(self):
        with mock.patch("course.content.markup_to_html") as mock_mth:
            error_msg = "my expected error"
            mock_mth.side_effect = RuntimeError(error_msg)
            resp = self.post_markup_sandbox_view(markup_content="[home](course:)")
            self.assertEqual(resp.status_code, 200)
            self.assertAddMessageCallCount(1)
            self.assertAddMessageCalledWith(error_msg)

    def test_subdir_macro_render(self):
        # Test https://github.com/inducer/relate/pull/556
        # Also see https://github.com/inducer/relate/issues/767
        markup_content = """
{% from "macros/test/test-macro.jinja" import button %}
{{ button("flow:exam-1") }}"""
        resp = self.post_markup_sandbox_view(markup_content=markup_content)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, "/course/%s/flow/exam-1/start" % self.course.identifier,
            status_code=200)
