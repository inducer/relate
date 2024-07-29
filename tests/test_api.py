from __future__ import annotations


__copyright__ = "Copyright (C) 2020 Dong Zhuang"

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

from tests import factories
from tests.base_test_mixins import APITestMixin, SingleCourseQuizPageTestMixin


class GetFlowSessionsTest(APITestMixin, TestCase):
    # test get_flow_sessions

    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor_participation.user)

    def test_success(self):
        self.start_flow(self.flow_id)
        token = self.create_token()

        resp = self.client.get(
            self.get_get_flow_session_api_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 200)

    def test_fail_flow_id_not_supplied(self):
        self.start_flow(self.flow_id)
        token = self.create_token()

        resp = self.client.get(
            self.get_get_flow_session_api_url(auto_add_default_flow_id=False),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 400)

    def test_fail_no_permission(self):
        self.start_flow(self.flow_id)
        token = self.create_token(participation=self.student_participation)

        resp = self.client.get(
            self.get_get_flow_session_api_url(auto_add_default_flow_id=False),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)


class GetFlowSessionContentTest(
        SingleCourseQuizPageTestMixin, APITestMixin, TestCase):
    # test get_flow_session_content

    skip_code_question = False

    def setUp(self):
        super().setUp()
        self.client.force_login(self.instructor_participation.user)

    def test_success(self):
        self.start_flow(self.flow_id)
        token = self.create_token()

        resp = self.client.get(
            self.get_get_flow_session_content_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 200)

    def test_success_with_visit(self):
        self.start_flow(self.flow_id)
        self.submit_page_answer_by_page_id_and_test("proof")
        self.submit_page_answer_by_page_id_and_test("age_group")
        self.submit_page_answer_by_page_id_and_test("half")
        self.submit_page_answer_by_page_id_and_test("addition")
        self.end_flow()
        token = self.create_token()

        resp = self.client.get(
            self.get_get_flow_session_content_url(),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 200)

    def test_fail_flow_id_not_supplied(self):
        self.start_flow(self.flow_id)
        token = self.create_token()

        resp = self.client.get(
            self.get_get_flow_session_content_url(
                auto_add_default_flow_session_id=False),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 400)

    def test_fail_no_permission(self):
        self.start_flow(self.flow_id)
        token = self.create_token(participation=self.student_participation)

        resp = self.client.get(
            self.get_get_flow_session_content_url(
                auto_add_default_flow_session_id=False),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)

    def test_fail_course_not_matched(self):
        another_course = factories.CourseFactory(identifier="another-course")
        another_course_fs = factories.FlowSessionFactory(
            participation=factories.ParticipationFactory(course=another_course)
        )

        token = self.create_token()

        resp = self.client.get(
            self.get_get_flow_session_content_url(
                flow_session_id=another_course_fs.id),
            HTTP_AUTHORIZATION="Token %i_%s" % (
                token.id, self.default_token_hash_str))
        self.assertEqual(resp.status_code, 403)


# vim: foldmethod=marker
