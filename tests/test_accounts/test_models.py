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

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase
from django.contrib.auth import get_user_model

from tests.factories import UserFactory


class UserModelTest(TestCase):
    """
    Different from tests.test_auth, this is testing db operation.
    """
    def test_email_uniqueness(self):
        UserFactory.create(email="test@example.com")
        with self.assertRaises(ValidationError) as error:
            UserFactory.create(email="test@example.com")
        self.assertEqual(
            error.exception.messages,
            ["That email address is already in use."])

    def test_email_uniqueness_case_insensitive(self):
        UserFactory.create(email="test@example.com")
        with self.assertRaises(ValidationError) as error:
            UserFactory.create(email="Test@example.com")
        self.assertEqual(
            error.exception.messages,
            ["That email address is already in use."])

    def test_institutional_uniqueness(self):
        UserFactory.create(institutional_id="1234")
        with self.assertRaises(IntegrityError):
            UserFactory.create(institutional_id="1234")

    def test_save_institutional_id_none(self):
        user = UserFactory.create(institutional_id="1234")
        users = get_user_model().objects.all()
        self.assertTrue(users.count(), 1)
        self.assertEqual(users[0].institutional_id, "1234")

        user.institutional_id = "  "
        user.save()
        self.assertIsNone(get_user_model().objects.first().institutional_id)

    def test_user_must_have_email(self):
        UserFactory.create()
        with self.assertRaises(IntegrityError):
            UserFactory.create(email=None)
