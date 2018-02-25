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

from datetime import datetime

from django.test import TestCase, override_settings

from relate.utils import format_datetime_local

from tests.base_test_mixins import (
    SingleCourseTestMixin, FallBackStorageMessageTestMixin)


class ValidateFlowPageTest(SingleCourseTestMixin,
                           FallBackStorageMessageTestMixin, TestCase):

    def setUp(self):
        super(ValidateFlowPageTest, self).setUp()
        self.current_commit_sha = self.get_course_commit_sha(
            self.instructor_participation)

    custom_page_type = "repo:simple_questions.MyTextQuestion"

    commit_sha_deprecated = b"593a1cdcecc6f4759fd5cadaacec0ba9dd0715a7"

    deprecate_warning_message_pattern = (
        "Custom page type '%(page_type)s' specified. "
        "Custom page types will stop being supported in "
        "RELATE at %(date_time)s.")

    expired_error_message_pattern = (
        "Custom page type '%(page_type)s' specified. "
        "Custom page types were no longer supported in "
        "RELATE since %(date_time)s.")

    def test_custom_page_types_deprecate(self):
        deadline = datetime(2039, 1, 1, 0, 0, 0, 0)
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=deadline):
            resp = self.post_update_course_content(
                commit_sha=self.commit_sha_deprecated)
            self.assertEqual(resp.status_code, 200)
            expected_message = (
                self.deprecate_warning_message_pattern
                % {"page_type": self.custom_page_type,
                   "date_time": format_datetime_local(deadline)}
            )
            self.assertResponseMessagesContains(resp, expected_message, loose=True)
            self.assertEqual(
                self.get_course_commit_sha(self.instructor_participation),
                self.commit_sha_deprecated)

    def test_custom_page_types_not_supported(self):
        deadline = datetime(2017, 1, 1, 0, 0, 0, 0)
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=deadline):
            resp = self.post_update_course_content(
                commit_sha=self.commit_sha_deprecated)
            self.assertEqual(resp.status_code, 200)
            expected_message = (
                self.expired_error_message_pattern
                % {"page_type": self.custom_page_type,
                   "date_time": format_datetime_local(deadline)}
            )
            self.assertResponseMessagesContains(resp, expected_message, loose=True)
            self.assertEqual(
                self.get_course_commit_sha(self.instructor_participation),
                self.current_commit_sha)

    def test_custom_page_types_deadline_configured_none(self):
        with override_settings(
                RELATE_CUSTOM_PAGE_TYPES_REMOVED_DEADLINE=None):
            resp = self.post_update_course_content(
                commit_sha=self.commit_sha_deprecated)
            self.assertEqual(resp.status_code, 200)
            not_expected_message = [
                "Custom page types were no longer supported",
                "Custom page types will stop being supported"
            ]
            for m in not_expected_message:
                self.assertNotContains(resp, not_expected_message)

            self.assertEqual(
                self.get_course_commit_sha(self.instructor_participation),
                self.commit_sha_deprecated)
