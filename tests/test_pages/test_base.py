from __future__ import division

__copyright__ = "Copyright (C) 2018 Dong Zhuang"

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

from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin, PAGE_ERRORS
)
from tests.base_test_mixins import SingleCoursePageTestMixin
from tests.utils import mock

SANDBOX_TITLE_PATTERN = "<title>[SB] %s - RELATE </title>"

TEXT_QUESTION_MARKDOWN = """
type: TextQuestion
id: eigvec
title: Eigenvectors
value: 2
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers:

- <plain>matrix
- <case_sens_plain>Eigenmatrix
- <regex>(?:linear\s+)?\s*map
- <case_sens_regex>(?:operator\s+)?\s*map

"""

OPTIONAL_PAGE_WITH_VALUE_ATTR = """
type: TextQuestion
id: eigvec
is_optional_page: True
value: 2
title: Eigenvectors
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers:

- <plain>matrix
- <case_sens_plain>Eigenmatrix
- <regex>(?:linear\s+)?\s*map
- <case_sens_regex>(?:operator\s+)?\s*map

"""

PAGE_WITH_TITLE_MARKDOWN_PATTERN = """
type: Page
%(attr_title)s
id: welcome

content: |

    %(content_title)s

    Don't be scared.
"""


TEST_ANSWER_MARKDOWN = """
type: ChoiceQuestion
id: myquestion
shuffle: True
prompt: |

    # What is your favorite number?

    There are many beautiful numbers. What's your
    favorite one?

choices:

  - "1"
  - "2"
  - ~CORRECT~ 15
  - ~CORRECT~ $\pi$
  - $\sqrt 2$
"""


def make_page_data_side_effect_has_data(self):
    return {"data": "foo"}


class PageBaseTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_deprecated_make_page_data_has_warning(self):
        with mock.patch("course.page.text.TextQuestionBase.make_page_data",
                        autospec=True) as mock_make_page_data, mock.patch(
                "warnings.warn") as mock_warn:

            mock_make_page_data.side_effect = make_page_data_side_effect_has_data
            resp = self.get_page_sandbox_preview_response(TEXT_QUESTION_MARKDOWN)
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxHasValidPage(resp)
            self.assertSandboxWarningTextContain(resp, None)

            # There are other warnings besides this expected warning
            self.assertTrue(mock_warn.call_count >= 1)

            expected_warn_msg = (
                "TextQuestion is using the make_page_data compatiblity "
                "hook, which is deprecated.")

            warned_with_expected_msg = False

            for args in mock_warn.call_args_list:
                if expected_warn_msg in args[0]:
                    warned_with_expected_msg = True
                    break

            if not warned_with_expected_msg:
                self.fail("'%s' is not warned as expected" % expected_warn_msg)


def update_grade_data_from_grading_form_v2_side_effect_super(
        self, request, page_context, page_data, grade_data,
        grading_form, files_data):
    from course.page.base import PageBaseWithHumanTextFeedback
    return (
        super(
            PageBaseWithHumanTextFeedback, self
        ).update_grade_data_from_grading_form_v2(
            request, page_context, page_data, grade_data, grading_form, files_data))


def process_form_post_side_effect_super(self, page_context, page_data,
                                               post_data, files_data,
                                               page_behavior):
    from course.page.text import TextQuestionBase
    return (
        super(TextQuestionBase, self).process_form_post(page_context, page_data,
                                                        post_data, files_data,
                                                        page_behavior))


def post_form_side_effect(self, page_context, page_data, post_data, files_data):
    from course.page.text import TextAnswerForm
    read_only = False
    return TextAnswerForm(
        read_only,
        "default",
        self.get_validators(), post_data, files_data,
        widget_type=getattr(self.page_desc, "widget", None))


class PageBaseGradeDeprecateTest(SingleCoursePageTestMixin, TestCase):

    flow_id = "quiz-test"

    def setUp(self):
        super(PageBaseGradeDeprecateTest, self).setUp()
        self.c.force_login(self.student_participation.user)
        self.start_flow(flow_id=self.flow_id)

    def test_update_grade_data_from_grading_form(self):
        page_id = "hgtext"
        self.post_answer_by_page_id(
            page_id, answer_data={"answer": TEST_ANSWER_MARKDOWN})
        self.end_flow()

        with mock.patch(
                "course.page.base.PageBaseWithHumanTextFeedback"
                ".update_grade_data_from_grading_form_v2",
                autospec=True
        ) as mock_update_grade_data_from_grading_form_v2, mock.patch(
                "warnings.warn") as mock_warn:

            mock_update_grade_data_from_grading_form_v2.side_effect = (
                update_grade_data_from_grading_form_v2_side_effect_super)

            grade_data = {
                "grade_percent": ["100"],
                "released": ["on"]
            }
            resp = self.post_grade_by_page_id(page_id, grade_data)

            self.assertTrue(resp.status_code, 200)

            # There are other warnings besides this expected warning
            self.assertTrue(mock_warn.call_count >= 1)

            expected_warn_msg = (
                "HumanGradedTextQuestion is using the "
                "update_grade_data_from_grading_form "
                "compatiblity hook, which is deprecated.")

            warned_with_expected_msg = False

            for args in mock_warn.call_args_list:
                if expected_warn_msg in args[0]:
                    warned_with_expected_msg = True
                    break

            if not warned_with_expected_msg:
                self.fail("'%s' is not warned as expected" % expected_warn_msg)

    def test_post_form_deprecated(self):
        page_id = "half"

        with mock.patch(
                "course.page.text.TextQuestionBase.process_form_post",
                autospec=True
        ) as mock_process_form_post, mock.patch(
                "course.page.text.TextQuestionBase.post_form",
                autospec=True) as mock_post_form, mock.patch(
                "warnings.warn") as mock_warn:

            mock_process_form_post.side_effect = process_form_post_side_effect_super
            mock_post_form.side_effect = post_form_side_effect

            self.post_answer_by_page_id(
                page_id, answer_data={"answer": "1/2"})

            self.assertTrue(mock_warn.call_count >= 1)

            expected_warn_msg = (
                "TextQuestion is using the post_form compatiblity hook, "
                "which is deprecated.")

            warned_with_expected_msg = False

            for args in mock_warn.call_args_list:
                if expected_warn_msg in args[0]:
                    warned_with_expected_msg = True
                    break

            if not warned_with_expected_msg:
                self.fail("'%s' is not warned as expected" % expected_warn_msg)

        self.assertEqual(self.end_flow().status_code, 200)
        self.assertSessionScoreEqual(5)


class PageBaseWithValueTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_optional_page_with_value_attr(self):
        markdown = OPTIONAL_PAGE_WITH_VALUE_ATTR
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "Attribute 'value' should be removed when "
            "'is_optional_page' is True.")


class PageBaseWithTitleTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_markup_body_for_title_not_implemented(self):
        with mock.patch("course.page.static.Page.markup_body_for_title")\
                as mock_markup_body_for_title,\
                mock.patch("warnings.warn") as mock_warn:
            mock_markup_body_for_title.side_effect = NotImplementedError
            mock_warn.side_effect = [None, None, None]

            markdown = (
                    PAGE_WITH_TITLE_MARKDOWN_PATTERN
                    % {"attr_title": "",
                       "content_title": ""})

            resp = self.get_page_sandbox_preview_response(markdown)
            self.assertEqual(resp.status_code, 200)
            self.assertSandboxNotHasValidPage(resp)
            self.assertResponseContextContains(
                resp, PAGE_ERRORS,
                "no title found in body or title attribute")

            # There are other warnings besides this expected warning
            self.assertTrue(mock_warn.call_count >= 1)
            warned_with_expected_msg = False
            expected_warn_msg = ("PageBaseWithTitle subclass 'Page' does not "
                                 "implement markup_body_for_title()")
            for args in mock_warn.call_args_list:
                if expected_warn_msg in args[0]:
                    warned_with_expected_msg = True
                    break

            if not warned_with_expected_msg:
                self.fail("%s is not warned as expected" % expected_warn_msg)

    def test_no_title(self):
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "no title found in body or title attribute")

    def test_no_actual_title(self):
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "#"})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "no title found in body or title attribute")

        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "# "})  # with a space following
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "no title found in body or title attribute")

    def test_attr_title(self):
        expected_title_str = "This is attribute title"
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "title: %s" % expected_title_str,
                   "content_title": ""})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertContains(resp, SANDBOX_TITLE_PATTERN % expected_title_str,
                            html=True)

    def test_content_title(self):
        expected_title_str = "This is content title"
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "# %s" % expected_title_str})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertContains(resp, SANDBOX_TITLE_PATTERN % expected_title_str,
                            html=True)

    def test_used_attr_title(self):
        # when page_desc.title is not None, it will be used as title
        expected_title_str = "This is attribute title"
        content_title_str = "This is content title"
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "title: %s" % expected_title_str,
                   "content_title": "# %s" % content_title_str})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertContains(resp, SANDBOX_TITLE_PATTERN % expected_title_str,
                            html=True)

    def test_title_with_html_tags(self):
        title_str = "<strong>Important</strong>"
        expected_title_str = "Important"
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "# %s" % title_str})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertContains(resp, SANDBOX_TITLE_PATTERN % expected_title_str,
                            html=True)

    def test_title_with_markdown(self):
        title_str = "**Important**"
        expected_title_str = "Important"
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "# %s" % title_str})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertContains(resp, SANDBOX_TITLE_PATTERN % expected_title_str,
                            html=True)

    def test_title_with_lt(self):
        title_str = "<"
        from django.utils.html import escape
        expected_title_str = escape("<")
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "# %s" % title_str})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(resp, None)
        self.assertContains(resp, SANDBOX_TITLE_PATTERN % expected_title_str,
                            html=True)

    def test_title_with_rendered_empty_title_warn(self):
        title_str = "<p>"
        markdown = (
                PAGE_WITH_TITLE_MARKDOWN_PATTERN
                % {"attr_title": "",
                   "content_title": "# %s" % title_str})
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        self.assertSandboxWarningTextContain(
            resp, "the rendered title is an empty string")

# vim: fdm=marker
