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
import unittest

from relate.utils import dict_to_struct

from course.page.base import (
    create_default_point_scale, HumanTextFeedbackForm, get_editor_interaction_mode,
    PageBehavior, PageBase
)

from tests.base_test_mixins import SingleCourseQuizPageTestMixin
from tests.test_sandbox import (
    SingleCoursePageSandboxTestBaseMixin
)
from tests.constants import PAGE_ERRORS
from tests.test_grading import SingleCourseQuizPageGradeInterfaceTestMixin
from tests.utils import mock

SANDBOX_TITLE_PATTERN = "<title>[SB] %s - RELATE </title>"

TEXT_QUESTION_MARKDOWN = r"""
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
- type: regex
  value: (?:operator\s+)?\s*map
  flags: []

"""

TEXT_QUESTION_WITH_NEGATIVE_VALUE_MARKDOWN = r"""
type: TextQuestion
id: eigvec
title: Eigenvectors
value: -2
prompt: |

    # What's an eigenvector?

    Yadda ___________________ yadda.

answers:

- <plain>matrix
- <case_sens_plain>Eigenmatrix
- <regex>(?:linear\s+)?\s*map
- type: regex
  value: (?:operator\s+)?\s*map
  flags: []

"""

OPTIONAL_PAGE_WITH_VALUE_ATTR = r"""
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
- type: regex
  value: (?:operator\s+)?\s*map
  flags: []

"""

PAGE_WITH_TITLE_MARKDOWN_PATTERN = """
type: Page
%(attr_title)s
id: welcome

content: |

    %(content_title)s

    Don't be scared.
"""


TEST_ANSWER_MARKDOWN = r"""
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


class CreateDefaultPointScaleTest(unittest.TestCase):
    # test create_default_point_scale
    def test_create_default_point_scale(self):
        test_dict = {
            3: [0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3],
            7: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7],
            10: [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 5.5, 6, 6.5, 7, 7.5, 8,
                 8.5, 9, 9.5, 10],
            15: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
            70: [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70],
        }
        for k, v in test_dict.items():
            with self.subTest(total_points=k):
                returned_value = create_default_point_scale(k)
                self.assertIsNotNone(returned_value)
                self.assertTrue(len(returned_value))
                self.assertListEqual(v, returned_value)


def correct_answer_side_effect_super(
        self, page_context, page_data, answer_data, grade_data):
    from course.page.text import TextQuestionBase
    return super(TextQuestionBase, self).correct_answer(
        page_context, page_data, answer_data, grade_data)


def normalized_answer_side_effect_super(
        self, page_context, page_data, answer_data):
    from course.page.text import TextQuestionBase
    return super(TextQuestionBase, self).normalized_answer(
        page_context, page_data, answer_data)


def normalized_bytes_answer_side_effect_super(
        self, page_context, page_data, answer_data):
    from course.page.text import TextQuestionBase
    return super(TextQuestionBase, self).normalized_bytes_answer(
        page_context, page_data, answer_data)


class PageBaseAPITest(SingleCourseQuizPageTestMixin, TestCase):

    page_id = "half"

    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.start_flow(cls.flow_id)

    def test_correctness(self):
        self.submit_page_answer_by_page_id_and_test(self.page_id)
        resp = self.client.get(self.get_page_url_by_page_id(self.page_id))
        self.assertResponseContextIsNotNone(resp, "correct_answer")

        # make sure PageBase.correctness works
        with mock.patch("course.page.text.TextQuestion.correct_answer",
                        autospec=True) as mock_correctness:
            mock_correctness.side_effect = correct_answer_side_effect_super
            resp = self.client.get(self.get_page_url_by_page_id(self.page_id))
            self.assertResponseContextIsNone(resp, "correct_answer")

    def test_normalized_answer(self):
        # make sure PageBase.normalized_answer works
        with mock.patch("course.page.text.TextQuestion.normalized_answer",
                        autospec=True) as mock_normalized_answer:
            mock_normalized_answer.side_effect = normalized_answer_side_effect_super
            self.submit_page_answer_by_page_id_and_test(
                self.page_id,
                ensure_analytic_page_get_before_grading=True,
                ensure_analytic_page_get_after_grading=True, do_grading=True)

    def test_normalized_bytes_answer(self):
        # make sure PageBase.normalized_answer works
        with mock.patch("course.page.text.TextQuestion.normalized_bytes_answer",
                        autospec=True) as mock_normalized_bytes_answer:
            mock_normalized_bytes_answer.side_effect = \
                normalized_bytes_answer_side_effect_super

            self.submit_page_answer_by_page_id_and_test(
                self.page_id,
                ensure_download_before_grading=True,
                ensure_download_after_grading=True,
                dl_file_with_ext_count=0,
                do_grading=True)


class PageBasePageDescBackwardCompatibilityTest(unittest.TestCase):
    def test_page_desc_not_struct_warn(self):
        with mock.patch("warnings.warn") as mock_warn:
            PageBase(None, "", "abcd")
            self.assertTrue(mock_warn.call_count >= 1)

            expected_warn_msg = (
                "Not passing page_desc to PageBase.__init__ is deprecated")

            warned_with_expected_msg = False

            for args in mock_warn.call_args_list:
                if expected_warn_msg in args[0]:
                    warned_with_expected_msg = True
                    break

            if not warned_with_expected_msg:
                self.fail("'%s' is not warned as expected" % expected_warn_msg)


class PageBaseGetModifiedPermissionsForPageTest(unittest.TestCase):
    # test page_base.get_modified_permissions_for_page
    def test_get_modified_permissions_for_page(self):
        access_rule_permissions_list = [
            "view", "submit_answer", "end_session", "see_session_time",
            "lock_down_as_exam_session"]
        access_rule_permissions = frozenset(access_rule_permissions_list)

        with self.subTest(access_rules="Not present"):
            page_desc = dict_to_struct(
                {
                    "id": "abcd",
                    "type": "SomePageType",
                }
            )
            page = PageBase(None, "", page_desc)
            self.assertSetEqual(
                page.get_modified_permissions_for_page(access_rule_permissions),
                access_rule_permissions)

        with self.subTest(access_rules={}):
            page_desc = dict_to_struct(
                {
                    "id": "abcd",
                    "type": "SomePageType",
                    "access_rules": {}
                }
            )
            page = PageBase(None, "", page_desc)
            self.assertSetEqual(
                page.get_modified_permissions_for_page(access_rule_permissions),
                access_rule_permissions)

        with self.subTest(access_rules={"add_permissions": [],
                                        "remove_permissions": []}):
            page_desc = dict_to_struct(
                {
                    "id": "abcd",
                    "type": "SomePageType",
                    "access_rules": {"add_permissions": [],
                                     "remove_permissions": []}
                }
            )
            page = PageBase(None, "", page_desc)
            self.assertSetEqual(
                page.get_modified_permissions_for_page(access_rule_permissions),
                access_rule_permissions)

        with self.subTest(access_rules={"add_permissions": ["some_perm"],
                                        "remove_permissions": []}):
            page_desc = dict_to_struct(
                {
                    "id": "abcd",
                    "type": "SomePageType",
                    "access_rules": {"add_permissions": ["some_perm"],
                                     "remove_permissions": []}
                }
            )
            page = PageBase(None, "", page_desc)
            self.assertSetEqual(
                page.get_modified_permissions_for_page(access_rule_permissions),
                frozenset(access_rule_permissions_list + ["some_perm"]))

        with self.subTest(access_rules={"remove_permissions": ["none_exist_perm"]}):
            page_desc = dict_to_struct(
                {
                    "id": "abcd",
                    "type": "SomePageType",
                    "access_rules": {"remove_permissions": ["none_exist_perm"]}
                }
            )
            page = PageBase(None, "", page_desc)

            self.assertSetEqual(
                page.get_modified_permissions_for_page(access_rule_permissions),
                access_rule_permissions)

        with self.subTest(access_rules={
                "remove_permissions": [access_rule_permissions_list[0]]}):
            page_desc = dict_to_struct(
                {
                    "id": "abcd",
                    "type": "SomePageType",
                    "access_rules": {
                        "remove_permissions": [access_rule_permissions_list[0]]}
                }
            )
            page = PageBase(None, "", page_desc)

            self.assertSetEqual(
                page.get_modified_permissions_for_page(access_rule_permissions),
                frozenset(access_rule_permissions_list[1:]))


def human_text_feedback_form_clean_side_effect(self):
    from course.page.base import StyledForm
    return super(StyledForm, self).clean()


class HumanTextFeedbackFormTest(unittest.TestCase):
    def test_point_value_vs_field(self):
        with mock.patch(
                "course.page.base.create_default_point_scale"
        ) as mock_create_scale:

            form = HumanTextFeedbackForm(None)
            self.assertNotIn("grade_points", form.fields)
            self.assertEqual(mock_create_scale.call_count, 0)
            mock_create_scale.reset_mock()

            form = HumanTextFeedbackForm(0)
            self.assertNotIn("grade_points", form.fields)
            self.assertEqual(mock_create_scale.call_count, 0)
            mock_create_scale.reset_mock()

            form = HumanTextFeedbackForm(1)
            self.assertIn("grade_points", form.fields)
            self.assertEqual(mock_create_scale.call_count, 1)
            mock_create_scale.reset_mock()

    def test_form_disagree(self):
        form_data = {"grade_percent": 30, "grade_points": 2}
        form = HumanTextFeedbackForm(5, form_data)
        self.assertFalse(form.is_valid())
        self.assertEqual(form.non_field_errors(),
                         ['Grade (percent) and Grade (points) disagree'])

    def test_form_points_percentage_valid(self):
        form_data = {"grade_percent": 30, "grade_points": 1.50001}
        form = HumanTextFeedbackForm(5, form_data)
        self.assertTrue(form.is_valid())
        self.assertTrue(form.cleaned_percent() - 30 < 0.001)

    def test_form_no_grade_points(self):
        form_data = {"grade_percent": 30}
        form = HumanTextFeedbackForm(5, form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_percent(), 30)

    def test_form_no_grade_percent(self):
        form_data = {"grade_points": 1.5}
        form = HumanTextFeedbackForm(5, form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_percent(), 30)

    def test_form_point_value_none_cleaned_percentage(self):
        form_data = {"grade_percent": 30}
        form = HumanTextFeedbackForm(None, form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_percent(), 30)

    def test_form_cleaned_percent_raise(self):
        with mock.patch("course.page.base.HumanTextFeedbackForm.clean",
                        autospec=True) as mock_clean:
            mock_clean.side_effect = human_text_feedback_form_clean_side_effect
            form_data = {"grade_percent": 30, "grade_points": 2}
            form = HumanTextFeedbackForm(5, form_data)
            self.assertTrue(form.is_valid())

            with self.assertRaises(RuntimeError):
                form.cleaned_percent()


def make_page_data_side_effect_has_data(self):
    return {"data": "foo"}


class PageBaseDeprecationTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

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


class PageBaseGradeDeprecationTest(SingleCourseQuizPageTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.start_flow(flow_id=self.flow_id)

    def test_update_grade_data_from_grading_form(self):
        page_id = "hgtext"
        self.submit_page_answer_by_page_id_and_test(page_id)
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
                "grade_percent": "100",
                "released": "on"
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


def grading_form_to_html_side_effect_super(
        self, request, page_context, grading_form, grade_data):
    from course.page.base import PageBaseWithHumanTextFeedback
    return (
        super(
            PageBaseWithHumanTextFeedback, self
        ).grading_form_to_html(
            request, page_context, grading_form, grade_data))


def human_feedback_point_value_side_effect_super(self, page_context, page_data):
    from course.page.upload import FileUploadQuestion
    return (
        super(
            FileUploadQuestion, self
        ).human_feedback_point_value(page_context, page_data))


class PageBaseWithHumanTextFeedbackTest(SingleCourseQuizPageGradeInterfaceTestMixin,
                                    TestCase):
    @classmethod
    def setUpTestData(cls):  # noqa
        super().setUpTestData()
        cls.page_id = "anyup"
        cls.submit_page_answer_by_page_id_and_test(page_id=cls.page_id)
        cls.end_flow()

    def test_base_class_grading_form_to_html(self):
        # make sure subclass grading_form_to_html method works
        with mock.patch(
                "course.page.base.PageBaseWithHumanTextFeedback"
                ".grading_form_to_html", autospec=True
        ) as mock_grading_form_to_html:
            mock_grading_form_to_html.side_effect = (
                grading_form_to_html_side_effect_super)

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):

                resp = self.client.get(
                    self.get_page_grading_url_by_page_id(self.page_id))
                self.assertEqual(resp.status_code, 200)

    def test_human_feedback_point_value_subclass(self):
        # make sure subclass PageBase.human_feedback_point_value works
        with mock.patch(
                "course.page.upload.FileUploadQuestion"
                ".human_feedback_point_value", autospec=True
        ) as mock_human_feedback_point_value:
            mock_human_feedback_point_value.side_effect = (
                human_feedback_point_value_side_effect_super)

            with self.temporarily_switch_to_user(
                    self.instructor_participation.user):

                resp = self.client.get(
                    self.get_page_grading_url_by_page_id(self.page_id))
                self.assertEqual(resp.status_code, 200)

    def test_grade(self):
        with self.temporarily_switch_to_user(
                self.instructor_participation.user):

            # not released
            resp = self.post_grade_by_page_id(
                self.page_id,
                grade_data={})
            self.assertIsNone(resp.context.get("feedback"))
            self.assertEqual(resp.status_code, 200)

            # no grade_percent
            resp = self.post_grade_by_page_id(
                self.page_id,
                grade_data={
                    "released": "on"}
            )
            self.assertIsNone(resp.context.get("feedback"))
            self.assertEqual(resp.status_code, 200)

            expected_feedback_str = "I don't know how to grade"
            resp = self.post_grade_by_page_id(
                self.page_id,
                grade_data={
                    "released": "on",
                    "feedback_text": expected_feedback_str}
            )
            self.assertResponseContextAnswerFeedbackContainsFeedback(
                resp, expected_feedback_str)
            self.assertResponseContextAnswerFeedbackCorrectnessEquals(resp, None)
            self.assertEqual(resp.status_code, 200)


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

    def test_optional_page_with_negative_value_attr(self):
        markdown = TEXT_QUESTION_WITH_NEGATIVE_VALUE_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxNotHasValidPage(resp)
        self.assertResponseContextContains(
            resp, PAGE_ERRORS,
            "sandboxAttribute 'value' expects a non-negative value, "
            "got -2 instead")


class PageBaseWithTitleTest(SingleCoursePageSandboxTestBaseMixin, TestCase):

    def test_markup_body_for_title_not_implemented(self):
        with mock.patch("course.page.static.Page.markup_body_for_title")\
                as mock_markup_body_for_title,\
                mock.patch("warnings.warn") as mock_warn:
            mock_markup_body_for_title.side_effect = NotImplementedError

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

            # There may be other warnings besides this expected warning
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


HGTEXT_MARKDOWN = """
type: HumanGradedTextQuestion
id: hgtext
value: 5
widget: "editor:yaml"
validators:

    -
        type: relate_page
        page_type: ChoiceQuestion

prompt: |

    # Submit an exam Choice question

rubric: |

    (None yet)

correct_answer: |
    [see here](some/references)

"""


class PageBaseWithCorrectAnswerTest(SingleCoursePageSandboxTestBaseMixin, TestCase):
    def test_correct_answer_not_none(self):
        markdown = HGTEXT_MARKDOWN
        resp = self.get_page_sandbox_preview_response(markdown)
        self.assertEqual(resp.status_code, 200)
        self.assertSandboxHasValidPage(resp)
        expected_html = '<p><a href="some/references">see here</a></p>'
        self.assertResponseContextContains(resp, "correct_answer", expected_html)


class GetEditorInteractionModeTest(unittest.TestCase):
    # test get_editor_interaction_mode
    def test_get_editor_interaction_mode_flow_session_none(self):
        page_context = mock.MagicMock()
        page_context.flow_session = None
        self.assertEqual(get_editor_interaction_mode(page_context), "default")

    def test_get_editor_interaction_mode_participation_none(self):
        page_context = mock.MagicMock()
        page_context.flow_session = mock.MagicMock()
        page_context.flow_session.participation = None
        self.assertEqual(get_editor_interaction_mode(page_context), "default")

    def test_get_editor_interaction_mode_participation_not_none(self):
        page_context = mock.MagicMock()
        page_context.flow_session = mock.MagicMock()
        page_context.flow_session.participation = mock.MagicMock()
        page_context.flow_session.participation.user = mock.MagicMock()
        page_context.flow_session.participation.user.editor_mode = "some_mode"
        self.assertEqual(get_editor_interaction_mode(page_context), "some_mode")


class PageBehaviorTest(unittest.TestCase):
    def test_page_behavior_backward_compatibility(self):
        answer_is_final = PageBehavior(show_correctness=False, show_answer=False,
                          may_change_answer=False)
        if not answer_is_final:
            self.fail(
                "PageBehavior object expected to be True "
                "when may_change_answer is False for backward "
                "compatibility")

        answer_is_final = PageBehavior(show_correctness=False, show_answer=False,
                          may_change_answer=True)

        if answer_is_final:
            self.fail(
                "PageBehavior object expected to be False "
                "when may_change_answer is True for backward "
                "compatibility")

# vim: fdm=marker
