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

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase, override_settings

from tests.factories import UserFactory
from tests.utils import mock


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

    def test_custom_get_full_name_method_failed(self):
        """
        Test when RELATE_USER_FULL_NAME_FORMAT_METHOD failed, default method
        is used.
        """
        user = UserFactory.create(first_name="my_first", last_name="my_last")

        default_get_full_name = user.get_full_name()

        custom_get_full_name_path = (
            "tests.resource.my_customized_get_full_name_method")
        get_custom_full_name_method_path = (
            "accounts.utils.RelateUserMethodSettingsInitializer"
            ".custom_full_name_method")

        with override_settings(
                RELATE_USER_FULL_NAME_FORMAT_METHOD=custom_get_full_name_path):

            from accounts.utils import relate_user_method_settings

            # clear cached value
            relate_user_method_settings.__dict__ = {}

            # If custom method works, the returned value is different with
            # default value.
            self.assertNotEqual(default_get_full_name, user.get_full_name())

            with mock.patch(get_custom_full_name_method_path) as mock_custom_method:
                # clear cached value
                relate_user_method_settings.__dict__ = {}

                # raise an error when calling custom method
                mock_custom_method.side_effect = Exception()

                # the value falls back to default value
                self.assertEqual(user.get_full_name(), default_get_full_name)

    def test_custom_get_full_name_method_is_cached(self):
        """
        Test relate_user_method_settings.custom_full_name_method is cached.
        """

        user = UserFactory.create(first_name="my_first", last_name="my_last")
        custom_get_full_name_path = (
            "tests.resource.my_customized_get_full_name_method")
        custom_full_name_check_path = (
            "accounts.utils.RelateUserMethodSettingsInitializer"
            ".check_custom_full_name_method")

        with override_settings(
                RELATE_USER_FULL_NAME_FORMAT_METHOD=custom_get_full_name_path):

            from accounts.utils import relate_user_method_settings

            # clear cached value
            relate_user_method_settings.__dict__ = {}

            user.get_full_name()

            with mock.patch(custom_full_name_check_path) as mock_check:
                user.get_full_name()
                self.assertEqual(mock_check.call_count, 0)

    def test_get_email_appellation_priority_list(self):
        user = UserFactory.create(first_name="my_first", last_name="my_last")

        from accounts.utils import relate_user_method_settings
        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            self.assertEqual(user.get_email_appellation(), "my_first")

        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=[""]):
            relate_user_method_settings.__dict__ = {}
            self.assertEqual(user.get_email_appellation(), "my_first")

        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=["whatever"]):
            self.assertEqual(user.get_email_appellation(), "my_first")

        relate_user_method_settings.__dict__ = {}

        # not a list
        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST="whatever"):
            self.assertEqual(user.get_email_appellation(), "my_first")

        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=["full_name"],
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            self.assertEqual(user.get_email_appellation(), "my_first my_last")

        # create a user without first_name
        user = UserFactory.create(last_name="my_last")

        relate_user_method_settings.__dict__ = {}

        # the next appelation is email
        with override_settings(
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            self.assertEqual(user.get_email_appellation(), user.email)

        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=["full_name", "username"],
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            # because full_name is None
            self.assertEqual(user.get_email_appellation(), user.username)

    def test_get_email_appellation_priority_list_is_cached(self):
        """
        Test relate_user_method_settings.email_appellation_priority_list is cached.
        """
        user = UserFactory.create(first_name="my_first", last_name="my_last")

        email_appell_priority_list_check_path = (
            "accounts.utils.RelateUserMethodSettingsInitializer"
            ".check_email_appellation_priority_list")

        from accounts.utils import relate_user_method_settings
        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=["full_name", "username"],
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            self.assertEqual(user.get_email_appellation(), "my_first my_last")

            user2 = UserFactory.create(first_name="my_first")
            with mock.patch(email_appell_priority_list_check_path) as mock_check:
                self.assertEqual(user2.get_email_appellation(),
                                 user2.username)
                self.assertEqual(mock_check.call_count, 0)

    def test_get_email_appellation_priority_list_special_case(self):
        """
        In case when course.constants.DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST is set
        to an empty list.
        """
        user = UserFactory.create(first_name="my_first", last_name="my_last")

        from accounts.utils import relate_user_method_settings
        relate_user_method_settings.__dict__ = {}

        with override_settings(
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=None,
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):

            default_list_path = (
                "accounts.utils.DEFAULT_EMAIL_APPELLATION_PRIORITY_LIST")

            with mock.patch(default_list_path, []):
                self.assertEqual(user.get_email_appellation(), "user")

    def test_get_email_appellation_priority_list_deprecated(self):
        user = UserFactory.create(first_name="my_first", last_name="my_last")

        from accounts.utils import relate_user_method_settings
        relate_user_method_settings.__dict__ = {}

        # Use the deprecated one, correct one not configured
        with override_settings(
                RELATE_EMAIL_APPELATION_PRIORITY_LIST=["email"],
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=None,
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            self.assertEqual(user.get_email_appellation(), user.email)

        relate_user_method_settings.__dict__ = {}

        # If the correct name is configured, use the configure of the correct one.
        with override_settings(
                RELATE_EMAIL_APPELATION_PRIORITY_LIST=["first_name"],
                RELATE_EMAIL_APPELLATION_PRIORITY_LIST=["full_name"],
                RELATE_USER_FULL_NAME_FORMAT_METHOD=None):
            self.assertEqual(user.get_email_appellation(), "my_first my_last")

    def test_user_profile_mask_method_is_cached(self):
        user = UserFactory.create(first_name="my_first", last_name="my_last")

        from accounts.utils import relate_user_method_settings

        user_profile_mask_method_check_path = (
            "accounts.utils.RelateUserMethodSettingsInitializer"
            ".check_user_profile_mask_method")

        def custom_method(u):
            return "{}{}".format("User", str(u.pk + 100))

        with override_settings(RELATE_USER_PROFILE_MASK_METHOD=custom_method):
            relate_user_method_settings.__dict__ = {}
            self.assertEqual(user.get_masked_profile(), custom_method(user))

            user2 = UserFactory.create(first_name="my_first")

            with mock.patch(user_profile_mask_method_check_path) as mock_check:
                self.assertEqual(user2.get_masked_profile(),
                                 custom_method(user2))
                self.assertEqual(mock_check.call_count, 0)
