from __future__ import annotations


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

import pytest
from django.db.backends.signals import connection_created
from django.test import TestCase

from relate.utils import retry_transaction_decorator
from tests import factories
from tests.base_test_mixins import HackRepoMixin, SingleCourseQuizPageTestMixin
from tests.utils import SKIP_NON_PSQL_REASON, is_connection_psql, mock  # noqa


@pytest.mark.postgres
@pytest.mark.django_db
class PostgreSQLTestMixin:
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    @classmethod
    def tearDownClass(cls):  # biqa
        # No need to keep that signal overhead for non PostgreSQL-related tests.
        from django.contrib.postgres.signals import register_type_handlers
        connection_created.disconnect(register_type_handlers)
        super().tearDownClass()


@pytest.mark.postgres
@pytest.mark.django_db
class PostgreSQLAnalyticsTest(PostgreSQLTestMixin, SingleCourseQuizPageTestMixin,
                              HackRepoMixin, TestCase):

    def test_flow_analytics(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow(self.flow_id)

        resp = self.get_flow_analytics_view(flow_id=self.flow_id)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "flow_identifier", self.flow_id)

        resp = self.get_flow_analytics_view(flow_id=self.flow_id,
                                            restrict_to_first_attempt=1)
        self.assertEqual(resp.status_code, 200)
        self.assertResponseContextEqual(
            resp, "flow_identifier", self.flow_id)

    def test_page_analytics(self):
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow(self.flow_id)

            page_id, group_id = (
                self.get_page_id_via_page_oridnal(1, with_group_id=True))

            self.submit_page_answer_by_page_id_and_test(page_id)

            resp = self.get_flow_page_analytics(
                flow_id=self.flow_id, group_id=group_id, page_id=page_id)
            self.assertEqual(resp.status_code, 200)

    def test_page_analytics_is_multiple_submit(self):
        # A flow desc that may change answer
        self.course.active_git_commit_sha = "my_fake_commit_sha_for_flow_analytics"
        self.course.save()
        with self.temporarily_switch_to_user(self.student_participation.user):
            self.start_flow(self.flow_id)

            page_id, group_id = (
                self.get_page_id_via_page_oridnal(1, with_group_id=True))

            self.submit_page_answer_by_page_id_and_test(page_id)
            self.submit_page_answer_by_page_id_and_test(page_id)

            resp = self.get_flow_page_analytics(
                flow_id=self.flow_id, group_id=group_id, page_id=page_id)
            self.assertEqual(resp.status_code, 200)

            # restrict_to_first_attempt
            resp = self.get_flow_page_analytics(
                flow_id=self.flow_id, group_id=group_id, page_id=page_id,
                restrict_to_first_attempt=True)
            self.assertEqual(resp.status_code, 200)


@pytest.mark.postgres
@pytest.mark.django_db(transaction=True)
class RetryTransactionTest(PostgreSQLTestMixin, TestCase):
    # test relate.utils.retry_transaction
    def test_max_tries(self):
        user = factories.UserFactory()

        @retry_transaction_decorator(max_tries=2)
        def update_object(user):
            user.username = "foo"
            user.save()

        update_object(user)
        user.refresh_from_db()
        self.assertEqual(user.username, "foo")

    def test_exceed_max_tries_raise(self):
        user = factories.UserFactory()
        username = user.username
        from django.db.utils import OperationalError

        i = 0

        @retry_transaction_decorator()
        def update_object(user):
            nonlocal i
            if i < 7:
                i += 1
                raise OperationalError
            user.username = "foo"
            user.save()

        with self.assertRaises(OperationalError):
            update_object(user)

        user.refresh_from_db()
        self.assertEqual(user.username, username)

    def test_retries_success(self):
        user = factories.UserFactory()
        from django.db.utils import OperationalError

        i = 0

        @retry_transaction_decorator()
        def update_object(user):
            nonlocal i
            if i < 2:
                i += 1
                raise OperationalError
            user.username = "foo"
            user.save()

        update_object(user)
        user.refresh_from_db()
        self.assertEqual(user.username, "foo")

# vim: fdm=marker
